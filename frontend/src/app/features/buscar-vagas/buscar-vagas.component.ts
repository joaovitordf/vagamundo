import { Component, HostListener, OnInit, OnDestroy, ElementRef, ViewChild, AfterViewInit, inject, signal, computed, effect } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/services/api.service';
import { AutoModeService } from '../../core/services/auto-mode.service';
import { SearchStateService } from '../../core/services/search-state.service';
import { Vaga } from '../../core/models/vaga.model';
import {
  AVAILABLE_PORTALS,
  ActiveGeoFilter,
  GeoResolution,
  PORTAL_CATEGORIES,
  PortalOption,
  getPortalDisplayName,
  getWorkModelLabel,
  isWithinDays,
  matchesRegionFilter,
  matchesScoreFilter,
  matchesTextFilter,
  normalizeWorkModel,
  parseCalendarDateMs,
  resolveGeo as resolveGeoUtil,
} from '../../core/utils/job-filters.util';

const SVG_NS = 'http://www.w3.org/2000/svg';

@Component({
  selector: 'app-buscar-vagas',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './buscar-vagas.component.html',
  styleUrl: './buscar-vagas.component.css'
})
export class BuscarVagasComponent implements OnInit, AfterViewInit, OnDestroy {
  private readonly api = inject(ApiService);
  readonly autoMode = inject(AutoModeService);
  readonly state = inject(SearchStateService);

  private lastAutoTick = this.autoMode.resultsRefreshTick();
  private lastAutoKeywords = '';
  private searchEventSource: EventSource | null = null;
  private searchFallbackInterval: any = null;
  private batchPollInterval: any = null;

  constructor() {
    effect(() => {
      const tick = this.autoMode.resultsRefreshTick();
      const st = this.autoMode.status();
      if (st?.running && st.mode !== 'recruiters' && st.phase !== 'cooldown' && st.keywords?.length) {
        const kwStr = st.keywords.join(', ');
        if (kwStr !== this.lastAutoKeywords) {
          this.lastAutoKeywords = kwStr;
          if (this.filterText !== kwStr) {
            this.state.filterText.set(kwStr);
            this.state.cvAreaBadge.set('Sorteado pela IA (Modo Automático)');
            this.state.markSearchExecuted(kwStr);
          }
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

  @ViewChild('mapWorldContainer') mapWorldContainer!: ElementRef<HTMLDivElement>;
  @ViewChild('mapBrasilContainer') mapBrasilContainer!: ElementRef<HTMLDivElement>;

  readonly allVagas = this.state.allVagas;
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
  readonly portalCategories = PORTAL_CATEGORIES;
  portalsDropdownOpen = signal<boolean>(false);
  readonly selectedPortalIds = this.state.selectedPortalIds;
  readonly filterPortalSearchText = this.state.filterPortalSearchText;

  portalsSummaryLabel = computed(() => {
    const total = this.availablePortals.length;
    const selected = this.selectedPortalIds();
    if (selected.size === total) return `Todas as fontes (${total})`;
    if (selected.size === 0) return 'Nenhum portal selecionado';
    if (selected.size === 1) {
      const id = Array.from(selected)[0];
      const p = this.availablePortals.find(x => x.id === id);
      return p ? p.name : id;
    }
    if (selected.size <= 2) {
      return Array.from(selected)
        .map(id => this.availablePortals.find(x => x.id === id)?.name || id)
        .join(', ');
    }
    return `${selected.size} portais selecionados`;
  });

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    if (this.portalsDropdownOpen()) {
      this.portalsDropdownOpen.set(false);
    }
  }

  togglePortalsDropdown(event: MouseEvent): void {
    event.stopPropagation();
    this.portalsDropdownOpen.update(v => !v);
  }

  isPortalSelected(id: string): boolean {
    return this.selectedPortalIds().has(id);
  }

  togglePortal(id: string, event?: Event): void {
    if (event) {
      event.stopPropagation();
    }
    const current = new Set(this.selectedPortalIds());
    if (current.has(id)) {
      current.delete(id);
    } else {
      current.add(id);
    }
    this.selectedPortalIds.set(current);
    this.state.persist();
    this.onFilterChange();
  }

  selectAllPortals(): void {
    this.selectedPortalIds.set(new Set(this.availablePortals.map(p => p.id)));
    this.state.persist();
    this.onFilterChange();
  }

  deselectAllPortals(): void {
    this.selectedPortalIds.set(new Set());
    this.state.persist();
    this.onFilterChange();
  }

  isCategoryFullySelected(catId: string): boolean {
    const inCat = this.availablePortals.filter(p => p.category === catId);
    if (!inCat.length) return false;
    const sel = this.selectedPortalIds();
    return inCat.every(p => sel.has(p.id));
  }

  toggleCategoryPortals(catId: string): void {
    const inCat = this.availablePortals.filter(p => p.category === catId);
    const fullySelected = this.isCategoryFullySelected(catId);
    const current = new Set(this.selectedPortalIds());
    if (fullySelected) {
      inCat.forEach(p => current.delete(p.id));
    } else {
      inCat.forEach(p => current.add(p.id));
    }
    this.selectedPortalIds.set(current);
    this.state.persist();
    this.onFilterChange();
  }

  getFilteredPortalsByCategory(catId: string): PortalOption[] {
    const q = this.filterPortalSearchText().trim().toLowerCase();
    const inCat = this.availablePortals.filter(p => p.category === catId);
    if (!q) return inCat;
    return inCat.filter(p => p.name.toLowerCase().includes(q) || (p.badge && p.badge.toLowerCase().includes(q)));
  }

  hasMatchingPortalsInCategory(catId: string): boolean {
    return this.getFilteredPortalsByCategory(catId).length > 0;
  }

  readonly cvAreaBadge = this.state.cvAreaBadge;
  private cvAreasList: any[] = [];
  private cvAreaQueue: any[] = [];
  private lastPickedAreaId: string | null = null;

  // Mapa & Dados Geográficos
  private geoData: any = null;
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
  remoteCounts: Record<string, number> = { REMOTO_BR: 0, EU_REMOTE: 0, GLOBAL_REMOTE: 0 };
  remoteScores: Record<string, number> = { REMOTO_BR: -1, EU_REMOTE: -1, GLOBAL_REMOTE: -1 };

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
  }

  private cleanupBatchPolling(): void {
    if (this.batchPollInterval) {
      clearInterval(this.batchPollInterval);
      this.batchPollInterval = null;
    }
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
      error: () => {}
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
    }).subscribe({ error: () => {} });
  }

  ngAfterViewInit(): void {
    this.loadGeoData();
  }

  loadCvAreas(): void {
    this.api.getCvAreas().subscribe({
      next: (res) => {
        if (res && Array.isArray(res.areas)) {
          this.cvAreasList = res.areas;
        }
      },
      error: () => {}
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
        this.geoData = data;
        this.updateMap();
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
      error: () => {}
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
        this.api.getSearchStatus().subscribe({
          next: (st) => {
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
          error: () => {
            this.cleanupSearchPolling();
            this.searching.set(false);
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
      const noModelCount = vagas.filter(v => normalizeWorkModel(v.workplace_type) === 'none').length;
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

      if (model && normalizeWorkModel(r.workplace_type) !== model) {
        return false;
      }

      // Verificação por seleção de portais multi-select
      if (selectedPortals.size === 0) {
        return false;
      }
      if (selectedPortals.size < this.availablePortals.length) {
        const portal = String(r.portal || '').toLowerCase();
        let matches = selectedPortals.has(portal);
        if (!matches && !portal.endsWith('-search')) {
          matches = selectedPortals.has(`${portal}-search`);
        }
        if (!matches) {
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
        const haystack = `${r.title || ''} ${r.company || ''} ${r.location || ''} ${r.seniority || ''} ${desc} ${tags} ${skills}`;
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

    this.filteredVagas.set(filtered);
    this.updateMap();
  }

  resetAllFilters(): void {
    this.state.resetFilters();
    this.onFilterChange();
  }

  switchSubtab(tab: 'mapa' | 'lista'): void {
    this.activeSubtab.set(tab);
    this.state.persist();
    if (tab === 'mapa') {
      setTimeout(() => this.updateMap(), 50);
    }
  }

  switchMapMode(mode: 'world' | 'brasil'): void {
    this.currentMapMode = mode;
    if (mode === 'brasil' && (!this.activeGeoFilter || this.activeGeoFilter.type === 'country')) {
      const brCnt = this.allVagas().filter(r => this.resolveGeo(r).countryCode === 'BR').length;
      this.activeGeoFilter = { type: 'country', code: 'BR', name: 'Brasil (Todos os Estados)', count: brCnt };
    }
    this.updateMap();
  }

  selectRemoteChip(code: string, name: string): void {
    if (this.activeGeoFilter?.type === 'remote' && this.activeGeoFilter.code === code) {
      this.activeGeoFilter = null;
    } else {
      const cnt = this.remoteCounts[code] || 0;
      this.activeGeoFilter = { type: 'remote', code, name, count: cnt };
    }
    this.onFilterChange();
  }

  clearGeoFilter(): void {
    this.activeGeoFilter = null;
    this.onFilterChange();
  }

  toggleTriageMode(): void {
    this.isTriageMode = !this.isTriageMode;
    this.updateMap();
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


  affinityHubs(): any[] {
    const list = this.filteredVagas();
    const hubs: Record<string, { label: string; count: number; score: number; key: string }> = {};

    list.forEach(r => {
      const geo = this.resolveGeo(r);
      const k = geo.label || geo.code || 'Outros';
      const sc = (r.screening && typeof r.screening.score === 'number') ? r.screening.score : -1;
      if (!hubs[k]) {
        hubs[k] = { label: k, count: 0, score: -1, key: k };
      }
      hubs[k].count++;
      if (sc > hubs[k].score) hubs[k].score = sc;
    });

    return Object.values(hubs)
      .sort((a, b) => b.count - a.count)
      .slice(0, 4);
  }

  onAffinityClick(hub: any): void {
    if (!hub || !hub.key) return;
    this.filterText = hub.key;
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
      const lbl = getWorkModelLabel(r.workplace_type);
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

  private updateMap(): void {
    if (!this.geoData) return;

    // Sincronização 100%: o mapa agora usa as mesmas vagas base dos filtros ativos!
    const baseRows = this.getBaseFilteredVagas();
    const brCounts: Record<string, number> = {};
    const worldCounts: Record<string, number> = {};
    const brScores: Record<string, number> = {};
    const worldScores: Record<string, number> = {};
    this.remoteCounts = { REMOTO_BR: 0, EU_REMOTE: 0, GLOBAL_REMOTE: 0 };
    this.remoteScores = { REMOTO_BR: -1, EU_REMOTE: -1, GLOBAL_REMOTE: -1 };

    baseRows.forEach(r => {
      const geo = this.resolveGeo(r);
      const score = (r.screening && typeof r.screening.score === 'number') ? r.screening.score : -1;

      if (geo.remoteBucket) {
        this.remoteCounts[geo.remoteBucket] = (this.remoteCounts[geo.remoteBucket] || 0) + 1;
        if (score > this.remoteScores[geo.remoteBucket]) this.remoteScores[geo.remoteBucket] = score;
      }

      if (geo.countryCode === 'BR') {
        worldCounts['BR'] = (worldCounts['BR'] || 0) + 1;
        if (score > (worldScores['BR'] || -1)) worldScores['BR'] = score;
        if (geo.code && geo.code !== 'REMOTO_BR') {
          brCounts[geo.code] = (brCounts[geo.code] || 0) + 1;
          if (score > (brScores[geo.code] || -1)) brScores[geo.code] = score;
        }
      } else if (geo.countryCode && geo.countryCode !== 'GLOBAL_REMOTE' && geo.countryCode !== 'EU_REMOTE') {
        worldCounts[geo.countryCode] = (worldCounts[geo.countryCode] || 0) + 1;
        if (score > (worldScores[geo.countryCode] || -1)) worldScores[geo.countryCode] = score;
      }
    });

    if (this.mapWorldContainer?.nativeElement) {
      this.renderWorldMapSvg(this.geoData.world || {}, worldCounts, worldScores);
    }
    if (this.mapBrasilContainer?.nativeElement) {
      this.renderBrasilMapSvg(this.geoData.brasil || {}, brCounts, brScores);
    }
  }

  private createSvgEl(tag: string, attrs: Record<string, string | number>, text?: string): SVGElement {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [key, val] of Object.entries(attrs)) {
      node.setAttribute(key, String(val));
    }
    if (text !== undefined) {
      node.textContent = text;
    }
    return node;
  }

  private appendOceanGradient(svg: SVGElement, id: string, cx: string, cy: string): void {
    const defs = document.createElementNS(SVG_NS, 'defs');
    const grad = this.createSvgEl('radialGradient', { id, cx, cy, r: '70%' });
    grad.appendChild(this.createSvgEl('stop', { offset: '0%', 'stop-color': '#0d1525' }));
    grad.appendChild(this.createSvgEl('stop', { offset: '100%', 'stop-color': '#070b13' }));
    defs.appendChild(grad);
    svg.appendChild(defs);
  }

  private createMapBadge(
    code: string,
    cx: number,
    cy: number,
    cnt: number,
    maxScore: number,
    isHighFit: boolean
  ): SVGElement {
    const gBadge = this.createSvgEl('g', { style: 'cursor: pointer;' });
    const hasScore = this.isTriageMode && maxScore >= 0;
    const rectW = hasScore ? 62 : 46;

    gBadge.appendChild(
      this.createSvgEl('rect', {
        class: `geo-badge-bg ${isHighFit ? 'fit-high' : ''}`.trim(),
        x: cx - rectW / 2,
        y: cy - 12,
        width: rectW,
        height: 24,
      })
    );
    gBadge.appendChild(this.createSvgEl('text', { class: 'geo-badge', x: cx, y: cy - 1 }, code));
    gBadge.appendChild(
      this.createSvgEl(
        'text',
        {
          class: 'geo-badge-sub',
          style: `fill: ${isHighFit ? '#34d399' : '#38bdf8'}; font-size: 8.5px;`,
          x: cx,
          y: cy + 9,
        },
        hasScore ? `${cnt} (${maxScore}p)` : `${cnt} vaga(s)`
      )
    );
    return gBadge;
  }

  private renderWorldMapSvg(world: Record<string, any>, counts: Record<string, number>, scores: Record<string, number>): void {
    const el = this.mapWorldContainer.nativeElement;
    el.replaceChildren();

    const svg = this.createSvgEl('svg', {
      viewBox: '0 0 1000 500',
      style: 'width: 100%; height: auto; max-height: 500px; display: block;',
    });

    this.appendOceanGradient(svg, 'world-ocean-grad', '50%', '45%');

    svg.appendChild(
      this.createSvgEl('rect', {
        width: 1000,
        height: 500,
        rx: 10,
        fill: 'url(#world-ocean-grad)',
      })
    );

    const gGrid = this.createSvgEl('g', { style: 'pointer-events: none;' });
    const gridLines: Array<Record<string, string | number>> = [
      { x1: 20, y1: 250, x2: 980, y2: 250, stroke: 'rgba(51, 65, 85, 0.28)', 'stroke-dasharray': '4 6' },
      { x1: 20, y1: 180, x2: 980, y2: 180, stroke: 'rgba(51, 65, 85, 0.16)', 'stroke-dasharray': '3 6' },
      { x1: 20, y1: 320, x2: 980, y2: 320, stroke: 'rgba(51, 65, 85, 0.16)', 'stroke-dasharray': '3 6' },
      { x1: 250, y1: 20, x2: 250, y2: 480, stroke: 'rgba(51, 65, 85, 0.16)', 'stroke-dasharray': '3 6' },
      { x1: 500, y1: 20, x2: 500, y2: 480, stroke: 'rgba(51, 65, 85, 0.22)', 'stroke-dasharray': '4 6' },
      { x1: 750, y1: 20, x2: 750, y2: 480, stroke: 'rgba(51, 65, 85, 0.16)', 'stroke-dasharray': '3 6' },
    ];
    for (const attrs of gridLines) {
      gGrid.appendChild(this.createSvgEl('line', attrs));
    }
    svg.appendChild(gGrid);

    const gPaths = document.createElementNS(SVG_NS, 'g');
    const gBadges = document.createElementNS(SVG_NS, 'g');

    for (const [code, info] of Object.entries(world)) {
      if (code === 'AQ') continue;
      const cnt = counts[code] || 0;
      const maxScore = scores[code] || -1;
      const isHighFit = this.isTriageMode && maxScore >= 75;
      const isActive = this.activeGeoFilter?.type === 'country' && this.activeGeoFilter.code === code;
      const fill = this.getGeoColor(cnt, maxScore, isActive);

      const path = this.createSvgEl('path', {
        class: `geo-state ${isActive ? 'active' : ''} ${isHighFit ? 'fit-high' : ''}`.trim(),
        d: info.path,
        fill,
        'data-code': code,
        'data-name': info.name,
      });

      const selectCountry = () => {
        if (code === 'BR') {
          this.switchMapMode('brasil');
        } else {
          this.activeGeoFilter = { type: 'country', code, name: `${info.name} (${code})`, count: cnt };
          this.onFilterChange();
        }
      };

      path.addEventListener('click', selectCountry);
      gPaths.appendChild(path);

      if (cnt > 0 && info.cx > 0 && info.cy > 0) {
        const gBadge = this.createMapBadge(code, info.cx, info.cy, cnt, maxScore, isHighFit);
        gBadge.addEventListener('click', selectCountry);
        gBadges.appendChild(gBadge);
      }
    }

    svg.appendChild(gPaths);
    svg.appendChild(gBadges);
    el.appendChild(svg);
  }

  private renderBrasilMapSvg(states: Record<string, any>, counts: Record<string, number>, scores: Record<string, number>): void {
    const el = this.mapBrasilContainer.nativeElement;
    el.replaceChildren();

    const svg = this.createSvgEl('svg', {
      viewBox: '0 0 600 600',
      style: 'width: 100%; height: auto; max-height: 500px; display: block;',
    });

    this.appendOceanGradient(svg, 'br-ocean-grad', '50%', '50%');

    svg.appendChild(
      this.createSvgEl('rect', {
        width: 600,
        height: 600,
        rx: 10,
        fill: 'url(#br-ocean-grad)',
      })
    );

    const gPaths = document.createElementNS(SVG_NS, 'g');
    const gBadges = document.createElementNS(SVG_NS, 'g');

    for (const [uf, info] of Object.entries(states)) {
      const cnt = counts[uf] || 0;
      const maxScore = scores[uf] || -1;
      const isHighFit = this.isTriageMode && maxScore >= 75;
      const isActive = this.activeGeoFilter?.type === 'uf' && this.activeGeoFilter.code === uf;
      const fill = this.getGeoColor(cnt, maxScore, isActive);

      const path = this.createSvgEl('path', {
        class: `geo-state ${isActive ? 'active' : ''} ${isHighFit ? 'fit-high' : ''}`.trim(),
        d: info.path,
        fill,
        'data-uf': uf,
        'data-name': info.name,
      });

      const selectUf = () => {
        this.activeGeoFilter = { type: 'uf', code: uf, name: `${info.name} (${uf})`, count: cnt };
        this.onFilterChange();
      };

      path.addEventListener('click', selectUf);
      gPaths.appendChild(path);

      if (cnt > 0) {
        const gBadge = this.createMapBadge(uf, info.cx, info.cy, cnt, maxScore, isHighFit);
        gBadge.addEventListener('click', selectUf);
        gBadges.appendChild(gBadge);
      } else {
        gBadges.appendChild(
          this.createSvgEl(
            'text',
            {
              class: 'geo-badge-sub',
              style: 'fill: #475569; font-size: 8px;',
              x: info.cx,
              y: info.cy + 3,
            },
            uf
          )
        );
      }
    }

    svg.appendChild(gPaths);
    svg.appendChild(gBadges);
    el.appendChild(svg);
  }

  private getGeoColor(cnt: number, maxScore: number, isActive: boolean): string {
    if (isActive) return '#38bdf8';
    if (!cnt || cnt <= 0) return '#131b2b';
    if (this.isTriageMode) {
      if (maxScore >= 75) return '#10b981';
      if (maxScore >= 60) return '#0ea5e9';
      return '#64748b';
    }
    if (cnt >= 10) return '#f59e0b';
    if (cnt >= 5) return '#0284c7';
    return '#0369a1';
  }

  formatSalaryBRL(raw?: string): string {
    if (!raw) return '';
    const text = raw.trim();
    if (text.includes('R$') || text.toLowerCase().includes('brl')) {
      return text;
    }

    const USD_RATE = 5.70;
    const EUR_RATE = 6.20;
    const GBP_RATE = 7.40;

    let rate = USD_RATE;
    let currencySymbol = 'USD';

    if (text.includes('€') || text.toLowerCase().includes('eur')) {
      rate = EUR_RATE;
      currencySymbol = 'EUR';
    } else if (text.includes('£') || text.toLowerCase().includes('gbp')) {
      rate = GBP_RATE;
      currencySymbol = 'GBP';
    }

    const matches = text.match(/\d+([.,]\d+)?/g);
    if (!matches || matches.length === 0) return text;

    const nums = matches.map(m => {
      let clean = m.replace(/\./g, '').replace(/,/g, '');
      let val = Number(clean);
      if (val < 1000 && (text.toLowerCase().includes('k') || text.toLowerCase().includes('mil'))) {
        val = val * 1000;
      }
      return val;
    }).filter(n => !isNaN(n) && n > 0);

    if (nums.length === 0) return text;

    const isAnnual = text.toLowerCase().includes('/ano') || text.toLowerCase().includes('/yr') || text.toLowerCase().includes('annual') || nums[0] > 25000;

    const toBrlMonthly = (val: number) => {
      const annualOrMonthly = isAnnual ? val / 12 : val;
      const brl = Math.round(annualOrMonthly * rate);
      return 'R$ ' + brl.toLocaleString('pt-BR');
    };

    if (nums.length >= 2) {
      return `${toBrlMonthly(nums[0])} - ${toBrlMonthly(nums[1])}/mês (~${currencySymbol})`;
    }
    return `${toBrlMonthly(nums[0])}/mês (~${currencySymbol})`;
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
      error: (err) => alert('Não consegui salvar: ' + err.message)
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
      error: (err) => alert('Não consegui registrar candidatura: ' + (err.error?.detail || err.message))
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
      error: (err) => alert('Não consegui descartar: ' + err.message)
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
      alert('Nenhuma vaga selecionada para triagem.');
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
    this.triageCurrentTitle.set('Iniciando triagem com Antigravity (Gemini)...');
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
        alert('Erro ao iniciar triagem: ' + (err?.error?.error || err?.message || 'Falha na comunicação'));
      }
    });
  }

  private pollBatchStatus(): void {
    this.cleanupBatchPolling();
    this.batchPollInterval = setInterval(() => {
      this.api.getSearchStatus().subscribe({
        next: (st) => {
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
        error: () => {
          this.cleanupBatchPolling();
          this.batchRunning.set(false);
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
        alert(`${res.cleared ?? 0} vagas pendentes foram descartadas.`);
        this.loadResults();
      },
      error: (err) => alert('Erro ao limpar vagas: ' + err.message)
    });
  }

  getPortalName(portal?: string): string {
    return portal ? getPortalDisplayName(portal) : 'Portal';
  }

  getModelLabel(type?: string): string {
    return getWorkModelLabel(type);
  }

  hasVisa(vaga: Vaga): boolean {
    return (vaga as any).visa_sponsorship === true || (vaga as any).visa_sponsorship === 'true' || (vaga as any).visa_sponsorship === 1;
  }

  /** Timestamp (meia-noite local) da data de publicação ou null se ausente/inválida. */
  parsePostedDate(raw: string | null | undefined): number | null {
    return parseCalendarDateMs(raw);
  }

  isUndated(vaga: Vaga): boolean {
    return this.parsePostedDate(vaga.date) === null;
  }

  getWarning(vaga: Vaga): string | null {
    const v = vaga.signals?.warnings?.[0];
    return v ? v.replace(/^posting_signals:\s*/, '').trim() : null;
  }
}
