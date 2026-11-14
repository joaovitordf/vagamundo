import { Component, DestroyRef, OnInit, OnDestroy, inject, signal, computed, effect } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/services/api.service';
import { AutoModeService } from '../../core/services/auto-mode.service';
import { SearchStateService } from '../../core/services/search-state.service';
import { ToastService } from '../../core/services/toast.service';
import { Vaga } from '../../core/models/vaga.model';
import {
  AVAILABLE_PORTALS,
  ActiveGeoFilter,
  GeoResolution,
  getJobWarning,
  getPortalDisplayName,
  getWorkModelLabel,
  hasVisaSponsorship,
  isWithinDays,
  matchesRegionFilter,
  matchesScoreFilter,
  matchesTextFilter,
  parseCalendarDateMs,
  resolveEffectiveWorkModel,
  resolveGeo as resolveGeoUtil,
} from '../../core/utils/job-filters.util';
import { SearchFiltersPanelComponent } from './components/search-filters-panel.component';
import { GeoMapComponent } from './components/geo-map.component';
import { BuscarJobCardComponent } from './components/buscar-job-card.component';

@Component({
  selector: 'app-buscar-vagas',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    SearchFiltersPanelComponent,
    GeoMapComponent,
    BuscarJobCardComponent,
  ],
  templateUrl: './buscar-vagas.component.html',
  styleUrl: './buscar-vagas.component.css'
})
export class BuscarVagasComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly toast = inject(ToastService);
  readonly autoMode = inject(AutoModeService);
  readonly state = inject(SearchStateService);
  private searchPollInFlight = false;
  private batchPollInFlight = false;

  private lastAutoTick = this.autoMode.resultsRefreshTick();
  private lastAutoKeywords = '';
  private searchEventSource: EventSource | null = null;
  private searchFallbackInterval: any = null;
  private batchPollInterval: any = null;

  constructor() {
    effect(() => {
      const tick = this.autoMode.resultsRefreshTick();
      const st = this.autoMode.status();
      if ((st?.running && st.mode !== 'recruiters') || (tick > 0 && st?.mode !== 'recruiters')) {
        this.api.hasSearchedInSession.set(true);
      }
      if (st?.running && st.mode !== 'recruiters' && st.phase !== 'cooldown' && st.keywords?.length) {
        const kwStr = st.keywords.join(', ');
        if (kwStr !== this.lastAutoKeywords) {
          this.lastAutoKeywords = kwStr;
          this.state.cvAreaBadge.set(`Sorteado pela IA: ${kwStr}`);
          this.state.markSearchExecuted();
          this.onFilterChange();
        }
      }
      if (!st?.running) {
        this.lastAutoKeywords = '';
      }
      if (tick > 0 && tick !== this.lastAutoTick && st?.mode !== 'recruiters') {
        this.lastAutoTick = tick;
        this.loadResults();
      }
    }, { allowSignalWrites: true });
  }

  readonly allVagas = this.state.allVagas;
  readonly baseFilteredVagas = signal<Vaga[]>([]);
  filteredVagas = signal<Vaga[]>([]);
  readonly activeSubtab = this.state.activeSubtab;

  get currentMapMode(): 'world' | 'brasil' { return this.state.currentMapMode(); }
  set currentMapMode(v: 'world' | 'brasil') {
    this.state.currentMapMode.set(v);
    this.state.persist();
  }

  get autoMinScore(): number { return this.state.autoMinScore(); }
  set autoMinScore(v: number) {
    this.state.autoMinScore.set(Number(v) || 60);
    this.state.persist();
  }

  get autoContinuous(): boolean { return this.state.autoContinuous(); }
  set autoContinuous(v: boolean) {
    this.state.autoContinuous.set(Boolean(v));
    this.state.persist();
  }

  get autoCooldownMinutes(): number { return this.state.autoCooldownMinutes(); }
  set autoCooldownMinutes(v: number) {
    const n = Number(v);
    this.state.autoCooldownMinutes.set(Number.isNaN(n) ? 5 : n);
    this.state.persist();
  }

  // Filtros persistidos no SearchStateService
  get filterText(): string { return this.state.filterText(); }
  set filterText(v: string) {
    this.state.filterText.set(v);
    this.state.persist();
  }

  get filterModel(): string { return this.state.filterModel(); }
  set filterModel(v: string) {
    this.state.filterModel.set(v);
    this.state.persist();
  }

  get filterRegion(): string { return this.state.filterRegion(); }
  set filterRegion(v: string) {
    this.state.filterRegion.set(v);
    this.state.persist();
  }

  get filterJobAge(): string { return this.state.filterJobAge(); }
  set filterJobAge(v: string) {
    this.state.filterJobAge.set(v);
    this.state.persist();
  }

  get filterScore(): string { return this.state.filterScore(); }
  set filterScore(v: string) {
    this.state.filterScore.set(v);
    this.state.persist();
  }

  get filterSort(): 'date' | 'score-desc' | 'score-asc' { return this.state.filterSort(); }
  set filterSort(v: 'date' | 'score-desc' | 'score-asc') {
    this.state.filterSort.set(v);
    this.state.persist();
  }

  get filterNoWarn(): boolean { return this.state.filterNoWarn(); }
  set filterNoWarn(v: boolean) {
    this.state.filterNoWarn.set(v);
    this.state.persist();
  }

  get filterHideUndated(): boolean { return this.state.filterHideUndated(); }
  set filterHideUndated(v: boolean) {
    this.state.filterHideUndated.set(v);
    this.state.persist();
  }

  get filterVisa(): boolean { return this.state.filterVisa(); }
  set filterVisa(v: boolean) {
    this.state.filterVisa.set(v);
    this.state.persist();
  }

  readonly availablePortals = AVAILABLE_PORTALS;
  private readonly validPortalIds = new Set(AVAILABLE_PORTALS.map(p => p.id.toLowerCase()));
  readonly selectedPortalIds = this.state.selectedPortalIds;

  readonly cvAreaBadge = this.state.cvAreaBadge;
  private cvAreasList: any[] = [];
  private cvAreaQueue: any[] = [];
  private lastPickedAreaId: string | null = null;

  // Mapa & Dados Geográficos
  readonly geoData = signal<any>(null);
  get activeGeoFilter(): ActiveGeoFilter | null { return this.state.activeGeoFilter(); }
  set activeGeoFilter(v: ActiveGeoFilter | null) {
    this.state.activeGeoFilter.set(v);
    this.state.persist();
  }
  get isTriageMode(): boolean { return this.state.isTriageMode(); }
  set isTriageMode(v: boolean) {
    this.state.isTriageMode.set(v);
    this.state.persist();
  }

  // Status de Busca & Triagem (mantidos no singleton SearchStateService)
  readonly searching = this.state.searching;
  readonly searchStatus = this.state.searchStatus;
  readonly searchError = this.state.searchError;
  readonly searchSummary = this.state.searchSummary;
  readonly lastSearchQuery = this.state.lastSearchQuery;

  // Painel Retrátil de Progresso
  readonly showProgressPanel = this.state.showProgressPanel;
  readonly progressExpanded = this.state.progressExpanded;
  readonly searchProgressPercent = this.state.searchProgressPercent;
  readonly searchCompletedCount = this.state.searchCompletedCount;
  readonly searchTotalCount = this.state.searchTotalCount;
  readonly searchCurrentPortal = this.state.searchCurrentPortal;
  readonly searchJobsFoundCount = this.state.searchJobsFoundCount;
  readonly searchPortalStatuses = this.state.searchPortalStatuses;
  readonly batchRunning = this.state.batchRunning;
  readonly batchStatus = this.state.batchStatus;
  readonly showTriagePanel = this.state.showTriagePanel;
  readonly triageExpanded = this.state.triageExpanded;
  readonly triageProgressPercent = this.state.triageProgressPercent;
  readonly triageCurrentCount = this.state.triageCurrentCount;
  readonly triageTotalCount = this.state.triageTotalCount;
  readonly triageCurrentTitle = this.state.triageCurrentTitle;
  readonly triageHighFitCount = this.state.triageHighFitCount;
  readonly triageMedFitCount = this.state.triageMedFitCount;
  readonly triageLowFitCount = this.state.triageLowFitCount;
  readonly triageErrorCount = this.state.triageErrorCount;
  readonly triageProviderLabel = this.state.triageProviderLabel;

  get batchScope(): string { return this.state.batchScope(); }
  set batchScope(v: string) {
    this.state.batchScope.set(v);
    this.state.persist();
  }

  get selectedUrls(): Set<string> { return this.state.selectedUrls(); }

  // Toast de feedback visual
  toastMessage = signal<string>('');
  private toastTimer: any = null;

  showToast(msg: string): void {
    this.toastMessage.set(msg);
    if (this.toastTimer) clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => {
      this.toastMessage.set('');
    }, 4500);
  }

  ngOnInit(): void {
    this.loadCvAreas();
    this.loadAutoConfig();
    this.api.getSettings().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (s) => {
        if (s?.active?.label) {
          this.triageProviderLabel.set(s.active.label);
        }
      },
      error: (err) => console.warn('Falha ao consultar provedor ativo:', err),
    });

    const isAutoJobsRunning = this.autoMode.isRunning() && this.autoMode.status()?.mode !== 'recruiters';
    const hasPersistedSession = this.state.hasTodaySearch() || this.api.hasSearchedInSession() || isAutoJobsRunning;

    if (hasPersistedSession) {
      this.api.hasSearchedInSession.set(true);
      if (this.allVagas().length > 0) {
        this.onFilterChange();
      } else if (this.api.sessionVagas().length > 0) {
        this.allVagas.set(this.api.sessionVagas());
        this.onFilterChange();
      }
      this.loadResults();
    }

    this.loadGeoData();
    this.checkInitialStatus();
  }

  ngOnDestroy(): void {
    if (this.toastTimer) {
      clearTimeout(this.toastTimer);
      this.toastTimer = null;
    }
    this.cleanupSearchPolling();
    this.cleanupBatchPolling();
  }

  private cleanupSearchPolling(): void {
    if (this.searchEventSource) {
      this.searchEventSource.close();
      this.searchEventSource = null;
    }
    if (this.searchFallbackInterval) {
      clearInterval(this.searchFallbackInterval);
      this.searchFallbackInterval = null;
    }
    this.searchPollInFlight = false;
  }

  private cleanupBatchPolling(): void {
    if (this.batchPollInterval) {
      clearInterval(this.batchPollInterval);
      this.batchPollInterval = null;
    }
    this.batchPollInFlight = false;
  }

  loadAutoConfig(): void {
    this.api.getAutoModeConfig().subscribe({
      next: (res) => {
        const cfg = res?.config;
        if (!cfg) return;
        if (typeof cfg.min_score === 'number') {
          this.state.autoMinScore.set(cfg.min_score);
        }
        if (typeof cfg.continuous === 'boolean') {
          this.state.autoContinuous.set(cfg.continuous);
        }
        if (typeof cfg.cooldown_seconds === 'number' && !Number.isNaN(cfg.cooldown_seconds)) {
          const mins = Math.max(2, Math.min(30, Math.round(cfg.cooldown_seconds / 60)));
          this.state.autoCooldownMinutes.set(mins);
        }
        this.state.persist();
      },
      error: (err) => console.warn('Falha ao carregar configuração automática:', err)
    });
  }

  onAutoConfigChange(): void {
    const clampedScore = Math.max(45, Math.min(95, Number(this.autoMinScore) || 60));
    const clampedMins = Math.max(2, Math.min(30, Math.round(Number(this.autoCooldownMinutes) || 5)));
    this.autoMinScore = clampedScore;
    this.autoCooldownMinutes = clampedMins;
    this.api.saveAutoModeConfig({
      min_score: clampedScore,
      continuous: this.autoContinuous,
      cooldown_seconds: clampedMins * 60,
    }).subscribe({
      error: (err) => this.toast.warning('Não foi possível salvar configuração do Modo Automático: ' + (err?.error?.detail || err?.message || 'Erro'))
    });
  }

  loadCvAreas(): void {
    this.api.getCvAreas().subscribe({
      next: (res) => {
        if (res && Array.isArray(res.areas)) {
          this.cvAreasList = res.areas;
        }
      },
      error: (err) => console.warn('Falha ao carregar áreas do CV:', err)
    });
  }

  pickRandomCvArea(): void {
    if (!this.cvAreasList.length) return;
    if (this.cvAreaQueue.length === 0) {
      const copy = [...this.cvAreasList];
      for (let i = copy.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [copy[i], copy[j]] = [copy[j], copy[i]];
      }
      if (copy.length > 1 && copy[0].id === this.lastPickedAreaId) {
        const swapIdx = 1 + Math.floor(Math.random() * (copy.length - 1));
        [copy[0], copy[swapIdx]] = [copy[swapIdx], copy[0]];
      }
      this.cvAreaQueue = copy;
    }
    const picked = this.cvAreaQueue.shift();
    if (!picked) return;
    this.lastPickedAreaId = picked.id;

    const candidates: string[] = (picked.keywords || [])
      .map((k: unknown) => String(k || '').trim())
      .filter(Boolean);
    const current = (this.filterText || '').trim().toLowerCase();
    const pool = candidates.filter((k: string) => k.toLowerCase() !== current);
    const chosen = (pool.length ? pool[Math.floor(Math.random() * pool.length)] : candidates[0]) || '';
    this.filterText = chosen;
    this.cvAreaBadge.set(`Área CV: ${picked.label || picked.title}`);
    this.state.persist();
    this.onFilterChange();
  }

  clearTextFilter(): void {
    this.filterText = '';
    this.cvAreaBadge.set('');
    this.state.persist();
    this.onFilterChange();
  }

  loadResults(): void {
    this.api.getResults().subscribe({
      next: (res) => {
        const newVagas = res.new || [];
        this.allVagas.set(newVagas);
        // Deseleciona quaisquer vagas que tenham saído da lista (ex: auto-descartadas)
        if (this.selectedUrls.size > 0) {
          const currentUrls = new Set(newVagas.map((v: any) => v.url));
          const remaining = new Set(Array.from(this.selectedUrls).filter(u => currentUrls.has(u)));
          this.state.selectedUrls.set(remaining);
        }
        this.onFilterChange();
      },
      error: (err) => console.error('Erro ao carregar resultados:', err)
    });
  }

  loadGeoData(): void {
    this.api.getGeo().subscribe({
      next: (data) => {
        this.geoData.set(data);
      },
      error: (err) => console.error('Erro ao carregar geo data:', err)
    });
  }

  checkInitialStatus(): void {
    this.api.getSearchStatus().subscribe({
      next: (st) => {
        const searchJob = st?.search;
        if (searchJob?.error) {
          this.searchError.set('A busca não terminou: ' + searchJob.error);
        }
        if (searchJob?.summary) {
          this.searchSummary.set(searchJob.summary);
        }

        if (searchJob?.running) {
          this.api.hasSearchedInSession.set(true);
          this.searching.set(true);
          this.showProgressPanel.set(true);
          if (searchJob.started) {
            this.searchStatus.set(`Buscando desde ${searchJob.started.slice(11, 16)}…`);
          }
          this.pollSearchStatus();
        } else if (this.searching()) {
          this.searching.set(false);
          this.searchProgressPercent.set(100);
          this.searchStatus.set('Busca concluída!');
          this.loadResults();
        }

        const batchJob = st?.batch;
        if (batchJob?.running) {
          this.batchRunning.set(true);
          this.showTriagePanel.set(true);
          this.isTriageMode = true;
          this.pollBatchStatus();
        } else if (this.batchRunning()) {
          this.batchRunning.set(false);
          this.triageProgressPercent.set(100);
          this.loadResults();
          this.api.refreshCounts();
        }
      },
      error: (err) => console.warn('Falha ao verificar status inicial de busca/triagem:', err)
    });
  }

  private _resolvePortalsSelection(): { selectedList: string[]; isAllPortals: boolean } | null {
    const selectedList = Array.from(this.selectedPortalIds());
    if (selectedList.length === 0) {
      this.showToast('⚠️ Selecione pelo menos uma fonte de busca (portal) no dropdown.');
      return null;
    }
    return {
      selectedList,
      isAllPortals: selectedList.length === this.availablePortals.length,
    };
  }

  triggerAutoMode(): void {
    const sel = this._resolvePortalsSelection();
    if (!sel) return;

    const effectiveJobAge = Math.min(Number(this.filterJobAge) || 7, 7);
    const minScore = Math.max(45, Math.min(95, Number(this.autoMinScore) || 60));
    const cooldownMins = Math.max(2, Math.min(30, Math.round(Number(this.autoCooldownMinutes) || 5)));
    this.autoMinScore = minScore;
    this.autoCooldownMinutes = cooldownMins;
    this.filterJobAge = String(effectiveJobAge);
    this.activeGeoFilter = null;
    this.searchError.set('');
    this.batchStatus.set('');
    this.showTriagePanel.set(false);
    this.isTriageMode = true;

    this.autoMode.start({
      region: this.filterRegion || 'all',
      portals: sel.isAllPortals ? ['all'] : sel.selectedList,
      jobage: effectiveJobAge,
      min_score: minScore,
      hide_undated: this.filterHideUndated,
      continuous: this.autoContinuous,
      cooldown_seconds: cooldownMins * 60,
    }).subscribe({
      next: () => {
        this.api.hasSearchedInSession.set(true);
        this.state.markSearchExecuted(this.filterText.trim() || undefined);
        this.showToast('🤖 Modo Automático iniciado! Acompanhe o aviso no topo de qualquer tela.');
      },
      error: (err) => {
        const msg = err?.error?.detail || err?.error?.error || err?.message || 'Falha ao iniciar';
        this.searchError.set('Modo Automático: ' + msg);
      }
    });
  }

  triggerPortalSearch(): void {
    this.searching.set(true);
    this.showProgressPanel.set(true);
    this.progressExpanded.set(true);
    this.searchProgressPercent.set(0);
    this.searchCompletedCount.set(0);
    this.searchTotalCount.set(0);
    this.searchCurrentPortal.set('');
    this.searchJobsFoundCount.set(0);
    this.searchPortalStatuses.set([]);
    this.searchStatus.set('Iniciando busca nos portais…');
    this.searchError.set('');
    this.searchSummary.set('');

    // Mantemos o termo digitado pelo usuário (não apagamos filterText)
    this.activeGeoFilter = null;

    const trimmedQuery = (this.filterText || '').trim();
    this.lastSearchQuery.set(trimmedQuery);
    if (!this.batchRunning()) {
      this.batchStatus.set('');
      this.showTriagePanel.set(false);
    }

    const sel = this._resolvePortalsSelection();
    if (!sel) {
      this.searching.set(false);
      this.searchStatus.set('');
      return;
    }

    const payload = {
      all: true,
      jobage: Number(this.filterJobAge) || 14,
      focus: sel.isAllPortals ? 'all' : sel.selectedList.join(','),
      portals: sel.isAllPortals ? ['all'] : sel.selectedList,
      region: this.filterRegion || 'all',
      query: trimmedQuery || undefined
    };

    this.api.startSearch(payload).subscribe({
      next: () => {
        this.api.hasSearchedInSession.set(true);
        this.state.markSearchExecuted(trimmedQuery);
        this.pollSearchStatus();
      },
      error: (err) => {
        this.searching.set(false);
        this.searchStatus.set('');
        this.searchError.set('Erro ao iniciar busca: ' + (err?.error?.error || err?.message || 'Falha na comunicação'));
      }
    });
  }

  toggleProgressExpanded(): void {
    this.progressExpanded.set(!this.progressExpanded());
  }

  closeProgressPanel(): void {
    this.showProgressPanel.set(false);
  }

  getPortalLabel(portal: string): string {
    return getPortalDisplayName(portal);
  }

  private pollSearchStatus(): void {
    this.cleanupSearchPolling();

    const handleProgressUpdate = (p: any) => {
      if (!p) return;
      this.searchProgressPercent.set(Math.min(100, Math.round(p.percent || 0)));
      this.searchCompletedCount.set(p.completed || 0);
      this.searchTotalCount.set(p.total || 0);
      if (p.current_portal) {
        this.searchCurrentPortal.set(p.current_portal);
      }
      this.searchJobsFoundCount.set(p.jobs_found || 0);
      if (p.portals) {
        const list = Object.entries(p.portals).map(([key, val]: [string, any]) => ({
          portal: key,
          label: getPortalDisplayName(key),
          status: val.status,
          jobs: val.jobs || 0,
          error: val.error
        }));
        this.searchPortalStatuses.set(list);
      }
    };

    const handleDone = (job?: any) => {
      this.cleanupSearchPolling();
      this.searching.set(false);
      this.searchProgressPercent.set(100);
      if (job && job.error) {
        this.searchError.set('A busca não terminou: ' + job.error);
        this.searchStatus.set('');
      } else {
        this.searchStatus.set('Busca concluída!');
      }
      if (job && job.summary) {
        this.searchSummary.set(job.summary);
      }
      this.loadResults();
    };

    const startPolling = () => {
      return setInterval(() => {
        if (this.searchPollInFlight) return;
        this.searchPollInFlight = true;
        this.api.getSearchStatus().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
          next: (st) => {
            this.searchPollInFlight = false;
            const job = st.search || st;
            if (job && job.progress) {
              handleProgressUpdate(job.progress);
            }
            if (job && job.running) {
              this.searchStatus.set(`Buscando desde ${job.started?.slice(11, 16) || ''}…`);
            } else {
              handleDone(job);
            }
          },
          error: (err) => {
            this.cleanupSearchPolling();
            this.searching.set(false);
            this.toast.error('Erro ao acompanhar andamento da busca: ' + (err?.error?.detail || err?.message || 'Erro de rede'));
          }
        });
      }, 1000);
    };

    if (typeof EventSource !== 'undefined') {
      try {
        this.searchEventSource = new EventSource('/api/stream');
        this.searchEventSource.addEventListener('progress', (e: MessageEvent) => {
          try {
            const data = JSON.parse(e.data);
            handleProgressUpdate(data);
          } catch (_) {}
        });
        this.searchEventSource.addEventListener('done', (e: MessageEvent) => {
          try {
            const data = JSON.parse(e.data);
            handleDone(data);
          } catch (_) {
            handleDone();
          }
        });
        this.searchEventSource.onerror = () => {
          this.cleanupSearchPolling();
          this.searchFallbackInterval = startPolling();
        };
      } catch (_) {
        this.searchFallbackInterval = startPolling();
      }
    } else {
      this.searchFallbackInterval = startPolling();
    }
  }

  getHiddenFilterReasons(): string {
    const vagas = this.allVagas();
    if (!vagas.length) return '';
    const reasons: string[] = [];
    const text = this.filterText.trim();
    if (text) {
      const noDescCount = vagas.filter(v => !(v.description && v.description.trim())).length;
      reasons.push(
        noDescCount > 0
          ? `palavra-chave ("${text}") com ${noDescCount} vaga(s) sem descrição detalhada`
          : `palavra-chave ("${text}")`
      );
    }
    const selectedPortals = this.selectedPortalIds();
    if (selectedPortals.size === 0) {
      reasons.push('nenhum portal selecionado');
    } else if (selectedPortals.size < this.availablePortals.length) {
      reasons.push(`seleção de portais (${selectedPortals.size} de ${this.availablePortals.length})`);
    }
    if (this.filterModel) {
      const noModelCount = vagas.filter(v => resolveEffectiveWorkModel(v) === 'none').length;
      reasons.push(
        noModelCount > 0
          ? `modelo "${this.filterModel}" (${noModelCount} vaga(s) sem modelo informado)`
          : `modelo "${this.filterModel}"`
      );
    }
    if (this.filterRegion) reasons.push(`região "${this.filterRegion}"`);
    if (this.filterJobAge) {
      const undated = vagas.filter(v => this.parsePostedDate(v.date) === null).length;
      reasons.push(
        this.filterHideUndated && undated > 0
          ? `período de ${this.filterJobAge} dia(s) (${undated} vaga(s) sem data ocultas)`
          : `período de ${this.filterJobAge} dia(s)`
      );
    } else if (this.filterHideUndated) {
      const undated = vagas.filter(v => this.parsePostedDate(v.date) === null).length;
      reasons.push(undated > 0 ? `ocultando ${undated} vaga(s) sem data` : 'ocultando vagas sem data');
    }
    if (this.filterScore) reasons.push(`afinidade "${this.filterScore}"`);
    if (this.filterNoWarn) reasons.push('somente sem alertas');
    if (this.filterVisa) reasons.push('somente com visto/relocação');
    if (this.activeGeoFilter) reasons.push('filtro de país no mapa');
    return reasons.join(', ');
  }

  getBaseFilteredVagas(): Vaga[] {
    const rawText = this.filterText.trim();
    const model = this.filterModel;
    const days = this.filterJobAge ? Number(this.filterJobAge) : null;
    const score = this.filterScore;
    const nowarn = this.filterNoWarn;
    const hideUndated = this.filterHideUndated;
    const visaOnly = this.filterVisa;
    const region = this.filterRegion;
    const selectedPortals = this.selectedPortalIds();

    return this.allVagas().filter((r) => {
      const geo = this.resolveGeo(r);

      if (region && !matchesRegionFilter(geo, region)) {
        return false;
      }

      if (nowarn && this.getWarning(r)) return false;
      if (visaOnly && !this.hasVisa(r)) return false;

      const effModel = resolveEffectiveWorkModel(r);
      if (model && effModel !== model) {
        return false;
      }

      // Verificação por seleção de portais multi-select
      if (selectedPortals.size === 0) {
        return false;
      }
      if (selectedPortals.size < this.availablePortals.length) {
        const portal = String(r.portal || '').toLowerCase().trim();
        const portalId = portal.endsWith('-search')
          ? portal
          : (this.validPortalIds.has(`${portal}-search`) ? `${portal}-search` : portal);
        if (this.validPortalIds.has(portalId) && !selectedPortals.has(portalId)) {
          return false;
        }
      }

      if (hideUndated || days) {
        const within = isWithinDays(r.date, days || 36500);
        if (within === null) {
          // Sem data confiável: visível com badge "Sem data", salvo se usuário pedir para ocultar.
          if (hideUndated) return false;
        } else if (days && !within) {
          return false;
        }
      }

      if (score && !matchesScoreFilter(r.screening?.score, score, Boolean(r.screening))) {
        return false;
      }

      if (rawText) {
        const hasDesc = Boolean(r.description && r.description.trim());
        const desc = r.description ? (r.description.length > 6000 ? r.description.slice(0, 6000) : r.description) : '';
        const tags = Array.isArray(r.tags) ? r.tags.join(' ') : '';
        const skills = Array.isArray(r.skills) ? r.skills.join(' ') : '';
        const haystack = `${r.title || ''} ${r.company || ''} ${r.location || ''} ${geo.label || ''} ${r.portal || ''} ${getPortalDisplayName(r.portal)} ${r.workplace_type || ''} ${getWorkModelLabel(effModel)} ${r.seniority || ''} ${desc} ${tags} ${skills}`;
        if (!matchesTextFilter(haystack, rawText, {
          hasDescription: hasDesc,
          fallbackQuery: r.query,
          lastSearchQuery: this.lastSearchQuery(),
        })) {
          return false;
        }
      }

      return true;
    });
  }

  onFilterChange(): void {
    const base = this.getBaseFilteredVagas();

    let filtered = [...base];
    if (this.activeGeoFilter) {
      filtered = base.filter((r) => {
        const geo = this.resolveGeo(r);
        if (this.activeGeoFilter!.type === 'remote') {
          return geo.remoteBucket === this.activeGeoFilter!.code || geo.code === this.activeGeoFilter!.code;
        } else if (this.activeGeoFilter!.type === 'uf') {
          return geo.countryCode === 'BR' && geo.code === this.activeGeoFilter!.code;
        } else if (this.activeGeoFilter!.type === 'country') {
          return geo.countryCode === this.activeGeoFilter!.code;
        }
        return true;
      });
    }

    if (this.filterSort === 'date') {
      filtered.sort((a, b) => {
        const da = parseCalendarDateMs(a.date);
        const db = parseCalendarDateMs(b.date);
        if (da === null && db === null) return 0;
        if (da === null) return 1;
        if (db === null) return -1;
        return db - da;
      });
    } else if (this.filterSort === 'score-desc') {
      filtered.sort((a, b) => {
        const sa = a.screening?.score !== undefined && a.screening?.score !== null ? a.screening.score : -1;
        const sb = b.screening?.score !== undefined && b.screening?.score !== null ? b.screening.score : -1;
        return sb - sa;
      });
    } else if (this.filterSort === 'score-asc') {
      filtered.sort((a, b) => {
        const sa = a.screening?.score !== undefined && a.screening?.score !== null ? a.screening.score : 999;
        const sb = b.screening?.score !== undefined && b.screening?.score !== null ? b.screening.score : 999;
        return sa - sb;
      });
    }

    this.baseFilteredVagas.set(base);
    this.filteredVagas.set(filtered);
  }

  resetAllFilters(): void {
    this.state.resetFilters();
    this.onFilterChange();
  }

  switchSubtab(tab: 'mapa' | 'lista'): void {
    this.activeSubtab.set(tab);
    this.state.persist();
  }

  switchMapMode(mode: 'world' | 'brasil'): void {
    this.currentMapMode = mode;
    if (mode === 'brasil' && (!this.activeGeoFilter || this.activeGeoFilter.type === 'country')) {
      const brCnt = this.baseFilteredVagas().filter(r => this.resolveGeo(r).countryCode === 'BR').length;
      this.activeGeoFilter = { type: 'country', code: 'BR', name: 'Brasil (Todos os Estados)', count: brCnt };
      this.onFilterChange();
    } else if (mode === 'world' && (this.activeGeoFilter?.code === 'BR' || this.activeGeoFilter?.type === 'uf')) {
      this.activeGeoFilter = null;
      this.onFilterChange();
    }
  }

  onGeoFilterChange(filter: ActiveGeoFilter | null): void {
    this.activeGeoFilter = filter;
    this.onFilterChange();
  }

  toggleTriageMode(): void {
    this.isTriageMode = !this.isTriageMode;
  }

  mapIndicatorText(): string {
    if (this.activeGeoFilter) {
      return `${this.activeGeoFilter.name} (${this.activeGeoFilter.count} vagas)`;
    }
    if (this.filteredVagas().length < this.allVagas().length) {
      return `Exibindo ${this.filteredVagas().length} de ${this.allVagas().length} vagas (filtros ativos)`;
    }
    return 'Todas as localidades';
  }

  localVagas(): Vaga[] {
    if (!this.activeGeoFilter) return [];
    return this.filteredVagas();
  }

  filterByBestScore(): void {
    if (!this.hasTriagedJobs()) return;
    this.filterScore = 'triadas';
    this.filterSort = 'score-desc';
    this.onFilterChange();
  }

  hasTriagedJobs(): boolean {
    return this.allVagas().some(r => r.screening && typeof r.screening.score === 'number');
  }

  triagedCount(): number {
    return this.allVagas().filter(r => r.screening && typeof r.screening.score === 'number').length;
  }

  highFitCount(): number {
    return this.allVagas().filter(r => r.screening && (r.screening.score || 0) >= 75).length;
  }

  mappedLocationsCount(): number {
    const locs = new Set<string>();
    this.filteredVagas().forEach(r => {
      const g = this.resolveGeo(r);
      if (g.code && g.code !== 'UNKNOWN') locs.add(g.code);
    });
    return locs.size;
  }

  leaderPoleName(): string {
    const counts: Record<string, number> = {};
    this.filteredVagas().forEach(r => {
      const g = this.resolveGeo(r);
      if (g.code) counts[g.code] = (counts[g.code] || 0) + 1;
    });
    let max = 0;
    let leader = 'Diversos Polos';
    Object.entries(counts).forEach(([k, v]) => {
      if (v > max) {
        max = v;
        leader = k;
      }
    });
    return leader;
  }


  affinityHubs(): Array<{
    label: string;
    count: number;
    score: number;
    key: string;
    searchTerm: string;
    companiesSample: string;
    sampleTitles: string;
    scoreText: string;
  }> {
    const list = this.filteredVagas();
    const hubs: Record<string, {
      label: string;
      count: number;
      score: number;
      key: string;
      searchTerm: string;
      companies: Set<string>;
      titles: Set<string>;
    }> = {};

    list.forEach(r => {
      const geo = this.resolveGeo(r);
      const k = geo.label || geo.code || 'Outros';
      const sc = (r.screening && typeof r.screening.score === 'number') ? r.screening.score : -1;
      if (!hubs[k]) {
        const cleanTerm = k === 'Remoto Brasil' ? 'Brasil' : k.replace(/\s*\([A-Z]{2}\)$/, '');
        hubs[k] = {
          label: k,
          count: 0,
          score: -1,
          key: k,
          searchTerm: cleanTerm,
          companies: new Set<string>(),
          titles: new Set<string>(),
        };
      }
      hubs[k].count++;
      if (sc > hubs[k].score) hubs[k].score = sc;
      if (r.company && r.company.trim() && hubs[k].companies.size < 3) {
        hubs[k].companies.add(r.company.trim());
      }
      if (r.title && r.title.trim() && hubs[k].titles.size < 2) {
        hubs[k].titles.add(r.title.trim());
      }
    });

    return Object.values(hubs)
      .sort((a, b) => b.count - a.count)
      .slice(0, 4)
      .map(h => ({
        label: h.label,
        count: h.count,
        score: h.score,
        key: h.key,
        searchTerm: h.searchTerm,
        companiesSample: h.companies.size > 0 ? Array.from(h.companies).join(', ') : 'Diversas empresas',
        sampleTitles: h.titles.size > 0 ? Array.from(h.titles).join(', ') : 'diversos perfis',
        scoreText: h.score >= 0 ? `Melhor nota ${h.score}/100` : 'Aguardando triagem',
      }));
  }

  onAffinityClick(hub: any): void {
    if (!hub || (!hub.searchTerm && !hub.key)) return;
    this.filterText = hub.searchTerm || hub.key;
    this.onFilterChange();
  }

  locationBars(): { label: string; count: number; pct: number }[] {
    const counts: Record<string, number> = {};
    const total = this.filteredVagas().length || 1;
    this.filteredVagas().forEach(r => {
      const g = this.resolveGeo(r);
      const lbl = g.label || g.countryCode || 'Diversos';
      counts[lbl] = (counts[lbl] || 0) + 1;
    });

    return Object.entries(counts)
      .map(([label, count]) => ({ label, count, pct: Math.round((count / total) * 100) }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 5);
  }

  workplaceBars(): { label: string; count: number; pct: number }[] {
    const counts: Record<string, number> = { 'Remoto': 0, 'Híbrido': 0, 'Presencial': 0, 'Não informado': 0 };
    const total = this.filteredVagas().length || 1;
    this.filteredVagas().forEach(r => {
      const lbl = getWorkModelLabel(resolveEffectiveWorkModel(r));
      counts[lbl] = (counts[lbl] || 0) + 1;
    });

    return Object.entries(counts)
      .filter(([_, count]) => count > 0)
      .map(([label, count]) => ({ label, count, pct: Math.round((count / total) * 100) }))
      .sort((a, b) => b.count - a.count);
  }

  portalBars(): { label: string; count: number; pct: number }[] {
    const counts: Record<string, number> = {};
    const total = this.filteredVagas().length || 1;
    this.filteredVagas().forEach(r => {
      const p = this.getPortalName(r.portal);
      counts[p] = (counts[p] || 0) + 1;
    });

    return Object.entries(counts)
      .map(([label, count]) => ({ label, count, pct: Math.round((count / total) * 100) }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 5);
  }

  resolveGeo(r: Vaga): GeoResolution {
    return resolveGeoUtil(r);
  }

  private removeUrlFromSelection(url: string): void {
    if (!this.selectedUrls.has(url)) return;
    const next = new Set(this.selectedUrls);
    next.delete(url);
    this.state.selectedUrls.set(next);
  }

  // --- Ações de Vagas ---
  markInteresse(vaga: Vaga): void {
    this.api.markDecision([vaga.url], 'interesse', vaga).subscribe({
      next: () => {
        this.allVagas.set(this.allVagas().filter(v => v.url !== vaga.url));
        this.removeUrlFromSelection(vaga.url);
        this.api.sessionVagas.set(this.allVagas());
        this.onFilterChange();
        this.showToast(`⭐ Vaga salva! "${vaga.title}" foi movida com segurança para a aba "Me Interessam".`);
      },
      error: (err) => this.toast.error('Não consegui salvar: ' + (err?.error?.detail || err.message))
    });
  }

  markApplied(vaga: Vaga): void {
    this.api.markApplied({
      url: vaga.url,
      company: vaga.company,
      role: vaga.title,
      portal: vaga.portal,
    }).subscribe({
      next: () => {
        this.allVagas.set(this.allVagas().filter(v => v.url !== vaga.url));
        this.removeUrlFromSelection(vaga.url);
        this.api.sessionVagas.set(this.allVagas());
        this.onFilterChange();
        this.showToast(`🎯 Candidatura registrada! "${vaga.title}" foi salva em "Minhas Candidaturas".`);
      },
      error: (err) => this.toast.error('Não consegui registrar candidatura: ' + (err.error?.detail || err.message))
    });
  }

  markDescartar(vaga: Vaga): void {
    this.api.markDecision([vaga.url], 'descartar').subscribe({
      next: () => {
        this.allVagas.set(this.allVagas().filter(v => v.url !== vaga.url));
        this.removeUrlFromSelection(vaga.url);
        this.api.sessionVagas.set(this.allVagas());
        this.onFilterChange();
        this.showToast(`🗑️ Vaga descartada e movida para a aba "Descartadas".`);
      },
      error: (err) => this.toast.error('Não consegui descartar: ' + (err?.error?.detail || err.message))
    });
  }

  isAllSelected(): boolean {
    const list = this.filteredVagas();
    return list.length > 0 && list.every(v => this.selectedUrls.has(v.url));
  }

  toggleSelectAll(e: any): void {
    const checked = e.target.checked;
    const next = new Set(this.selectedUrls);
    this.filteredVagas().forEach(v => {
      if (checked) next.add(v.url);
      else next.delete(v.url);
    });
    this.state.selectedUrls.set(next);
  }

  toggleVagaSelection(url: string, e: any): void {
    const next = new Set(this.selectedUrls);
    if (e.target.checked) next.add(url);
    else next.delete(url);
    this.state.selectedUrls.set(next);
  }

  triggerBatchScreen(): void {
    let urls: string[] = [];
    const list = this.filteredVagas().map(v => v.url);
    if (this.batchScope === 'selected') {
      urls = list.filter(u => this.selectedUrls.has(u));
    } else if (this.batchScope === 'all-visible') {
      urls = list;
    } else {
      const n = parseInt(this.batchScope, 10) || 5;
      urls = list.slice(0, n);
    }

    if (!urls.length) {
      this.toast.warning('Nenhuma vaga selecionada para triagem.');
      return;
    }

    // Ativa automaticamente o modo de triagem para exibir as notas no mapa e nos cards
    this.isTriageMode = true;
    this.batchRunning.set(true);
    this.showTriagePanel.set(true);
    this.triageExpanded.set(true);
    this.triageProgressPercent.set(0);
    this.triageCurrentCount.set(0);
    this.triageTotalCount.set(urls.length);
    this.triageCurrentTitle.set('Iniciando triagem com IA...');
    this.triageHighFitCount.set(0);
    this.triageMedFitCount.set(0);
    this.triageLowFitCount.set(0);
    this.triageErrorCount.set(0);
    this.batchStatus.set(`Iniciando triagem de ${urls.length} vagas...`);

    this.api.startBatchScreen(urls).subscribe({
      next: () => {
        this.pollBatchStatus();
      },
      error: (err) => {
        this.batchRunning.set(false);
        this.batchStatus.set('');
        this.toast.error('Erro ao iniciar triagem: ' + (err?.error?.detail || err?.error?.error || err?.message || 'Falha na comunicação'));
      }
    });
  }

  private pollBatchStatus(): void {
    this.cleanupBatchPolling();
    this.batchPollInterval = setInterval(() => {
      if (this.batchPollInFlight) return;
      this.batchPollInFlight = true;
      this.api.getSearchStatus().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
        next: (st) => {
          this.batchPollInFlight = false;
          const batch = st.batch;
          if (batch) {
            this.triageCurrentCount.set(batch.current || 0);
            this.triageTotalCount.set(batch.total || 0);
            this.triageProgressPercent.set(Math.min(100, Math.round(batch.percent || 0)));
            if (batch.current_title) {
              this.triageCurrentTitle.set(batch.current_title);
            }
            if (batch.provider) {
              this.triageProviderLabel.set(batch.provider);
            }
            this.triageHighFitCount.set(batch.high_fit || 0);
            this.triageMedFitCount.set(batch.med_fit || 0);
            this.triageLowFitCount.set(batch.low_fit || 0);
            this.triageErrorCount.set(batch.errors || 0);

            if (batch.running) {
              this.showTriagePanel.set(true);
              const errs = batch.errors ? ` (${batch.errors} com erro)` : '';
              this.batchStatus.set(`Triando ${batch.current} de ${batch.total}...${errs}`);
              this.loadResults();
              this.api.refreshCounts();
            } else {
              this.cleanupBatchPolling();
              this.batchRunning.set(false);
              this.triageProgressPercent.set(100);
              this.batchStatus.set(batch?.total ? `Triagem de ${batch.total} vagas concluída! Encontradas ${batch.high_fit || 0} de alta afinidade.` : '');
              this.loadResults();
              this.api.refreshCounts();
            }
          }
        },
        error: (err) => {
          this.cleanupBatchPolling();
          this.batchRunning.set(false);
          this.toast.error('Falha ao acompanhar triagem em lote: ' + (err?.error?.detail || err?.message || 'Erro de rede'));
        }
      });
    }, 1500);
  }

  toggleTriageExpanded(): void {
    this.triageExpanded.set(!this.triageExpanded());
  }

  closeTriagePanel(): void {
    this.showTriagePanel.set(false);
  }

  clearPendingJobs(): void {
    if (!confirm('Deseja descartar as vagas pendentes não salvas?')) return;
    this.api.clearPending().subscribe({
      next: (res) => {
        this.showToast(`${res.cleared ?? 0} vagas pendentes foram descartadas.`);
        this.loadResults();
      },
      error: (err) => this.toast.error('Erro ao limpar vagas: ' + (err?.error?.detail || err.message))
    });
  }

  readonly getPortalName = getPortalDisplayName;
  readonly getModelLabel = getWorkModelLabel;
  readonly hasVisa = hasVisaSponsorship;

  /** Timestamp (meia-noite local) da data de publicação ou null se ausente/inválida. */
  parsePostedDate(raw: string | null | undefined): number | null {
    return parseCalendarDateMs(raw);
  }

  readonly getWarning = getJobWarning;
}
