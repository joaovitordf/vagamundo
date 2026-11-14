import { Component, DestroyRef, OnDestroy, OnInit, inject, signal, computed, effect } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService, LinkedInWorkerStatus, SyncRecruiterPostsResponse } from '../../core/services/api.service';
import { PortalBadgeComponent } from '../../shared/components/portal-badge.component';
import { AutoModeService } from '../../core/services/auto-mode.service';
import { RecruiterSortMode, RecruiterStateService } from '../../core/services/recruiter-state.service';
import { ToastService } from '../../core/services/toast.service';
import { PreviouslyContactedEmail, RecruiterPost } from '../../core/models/vaga.model';

export function summarizeRecruiterSync(
  res?: SyncRecruiterPostsResponse | null
): { status: string; warning: string | null } {
  if (!res) return { status: '', warning: null };
  const breakdown = res.portal_breakdown || {};
  const parts: string[] = [];
  let matchedTotal = 0;

  for (const [portal, stats] of Object.entries(breakdown)) {
    const count = Number(stats?.matched || 0);
    if (count > 0) {
      matchedTotal += count;
      parts.push(`${getPortalDisplayName(portal)}: ${count}`);
    }
  }

  if (parts.length === 0) {
    const fallbackSources: Array<[string, number]> = [
      ['hn-search', Number(res.hn_synced || 0)],
      ['github-vagas', Number(res.github_synced || 0)],
      ['remotive-search', Number(res.remotive_synced || 0)],
      ['linkedin_post', Number(res.linkedin_synced || 0)],
      ['portal', Number(res.portal_synced || 0)],
    ];
    for (const [key, val] of fallbackSources) {
      if (val > 0) {
        matchedTotal += val;
        parts.push(`${key === 'portal' ? 'Portais remotos' : getPortalDisplayName(key)}: ${val}`);
      }
    }
  }

  let status = '';
  if (parts.length > 0) {
    status = `${matchedTotal} oportunidade(s) compatível(is) nas fontes (${parts.join(' • ')})`;
  } else if ((res.synced || 0) > 0) {
    status = `${res.synced} oportunidade(s) com e-mail sincronizada(s) na base multiplataforma.`;
  } else if ((res.linkedin_cards_total || 0) > 0 && Number(res.linkedin_synced || 0) === 0 && !res.linkedin_skipped_reason) {
    status = `LinkedIn: ${res.linkedin_cards_total} cards lidos no feed, mas nenhum revelou e-mail direto.`;
  }

  let warning: string | null = null;
  if (Array.isArray(res.warnings) && res.warnings.length > 0) {
    warning = `Sincronização parcial: ${res.warnings.join('; ')}.`;
  } else if (res.rate_limited) {
    warning = 'Alguma plataforma atingiu limite temporário de requisições; resultados locais foram carregados.';
  } else if ((res.errors || 0) > 0) {
    warning = `${res.errors} falha(s) parcial(is) em fontes externas; exibindo demais resultados.`;
  } else if (res.linkedin_skipped_reason === 'cooldown' && (res.linkedin_cooldown_remaining_seconds || 0) > 0) {
    const mins = Math.ceil(Number(res.linkedin_cooldown_remaining_seconds) / 60);
    warning = `LinkedIn em pausa configurada (${mins} min restantes).`;
  }

  return { status, warning };
}

export function removePostAndFlagEmail(
  posts: RecruiterPost[],
  removedPostId: number,
  email: string,
  meta: { company: string; title: string; contacted_at: string; job_id?: string; application_id?: number }
): RecruiterPost[] {
  const norm = (email || '').trim().toLowerCase();
  const nextEntry: PreviouslyContactedEmail = {
    email: norm || email,
    company: meta.company,
    title: meta.title,
    contacted_at: meta.contacted_at,
    job_id: meta.job_id,
    application_id: meta.application_id,
  };

  return posts
    .filter(p => p.id !== removedPostId)
    .map(p => {
      if (!norm) return p;
      const hasEmail = (p.emails || []).some(e => e.trim().toLowerCase() === norm);
      if (!hasEmail) return p;
      const existing = p.previously_contacted || [];
      const alreadyListed = existing.some(m => m.email.trim().toLowerCase() === norm);
      const updated = alreadyListed
        ? existing.map(m => (m.email.trim().toLowerCase() === norm ? nextEntry : m))
        : [...existing, nextEntry];
      return { ...p, previously_contacted: updated };
    });
}
import {
  FIT_THRESHOLDS,
  getPortalDisplayName,
  getWorkModelLabel,
  isWithinDays,
  matchesRegionFilter,
  matchesScoreFilter,
  matchesTextFilter,
  parseCalendarDateMs,
  resolveEffectiveWorkModel,
  resolveGeo,
} from '../../core/utils/job-filters.util';

@Component({
  selector: 'app-recrutadores',
  standalone: true,
  imports: [CommonModule, FormsModule, PortalBadgeComponent],
  templateUrl: './recrutadores.component.html',
  styleUrl: './recrutadores.component.css'
})
export class RecrutadoresComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly toast = inject(ToastService);
  readonly autoMode = inject(AutoModeService);
  readonly state = inject(RecruiterStateService);
  readonly fitThresholds = FIT_THRESHOLDS;
  private lastSeenAutoTick = this.autoMode.resultsRefreshTick();
  private lastAutoKeywords = '';
  private copyEmailTimer: ReturnType<typeof setTimeout> | null = null;
  private linkedInPollTimer: ReturnType<typeof setInterval> | null = null;
  private autoVerifyingLogin = false;

  constructor() {
    // Atualiza palavras-chave e publicações quando Modo Automático (Recrutadores) está ativo/concluído
    effect(() => {
      const st = this.autoMode.status();
      const tick = this.autoMode.resultsRefreshTick();
      if (st?.mode === 'recruiters') {
        const kwStr = (st.keywords || []).join(', ');
        if (st.phase !== 'cooldown' && kwStr && kwStr !== this.lastAutoKeywords && (!this.filterText.trim() || this.state.autoRunFilterApplied())) {
          this.lastAutoKeywords = kwStr;
          this.state.filterText.set(kwStr);
          this.state.autoRunFilterApplied.set(true);
          this.state.cvAreaBadge.set('Sorteado pela IA (Modo Automático)');
          this.state.hasSearched.set(true);
          this.state.persist();
          this.fetchPosts(false);
        }
        if (!st.running) {
          this.lastAutoKeywords = '';
        }
        if (tick > this.lastSeenAutoTick) {
          this.lastSeenAutoTick = tick;
          if (this.filterText.trim()) {
            this.state.hasSearched.set(true);
            this.state.persist();
          }
          this.fetchPosts(false);
          this.loadLinkedInStatus();
        }
      }
    }, { allowSignalWrites: true });
  }

  // Estados principais (delegados ao singleton RecruiterStateService)
  readonly allPosts = this.state.allPosts;
  readonly loading = this.state.loading;
  readonly hasSearched = this.state.hasSearched;
  readonly statusMessage = this.state.statusMessage;
  readonly errorMessage = this.state.errorMessage;
  readonly copiedEmail = signal<string | null>(null);
  readonly copiedPrompt = signal<{ postId: number; email: string } | null>(null);
  readonly busyPostIds = signal<Set<number>>(new Set());
  readonly multiEmailPickerPostId = signal<number | null>(null);
  readonly linkedInStatus = signal<LinkedInWorkerStatus | null>(null);
  readonly linkedInBusy = signal<boolean>(false);
  readonly linkedInPostsCount = computed(() =>
    this.allPosts().filter(p => p.portal === 'linkedin_post').length
  );
  readonly linkedInStatusLabel = computed(() => {
    const st = this.linkedInStatus();
    if (!st) return 'Não conectado';
    switch (st.status) {
      case 'connected':
        return 'Conectado';
      case 'awaiting_login':
        return 'Aguardando login na janela...';
      case 'login_required':
        return 'Sessão expirada';
      case 'checkpoint_required':
        return 'Verificação pendente';
      case 'unavailable':
        return 'Navegador indisponível';
      default:
        return 'Não conectado';
    }
  });
  readonly filteredPosts = this.state.filteredPosts;
  readonly hasSecondaryFilters = this.state.hasSecondaryFilters;
  readonly triaging = signal<boolean>(false);
  readonly untriagedVisibleCount = computed(() =>
    this.filteredPosts().filter(p => !p.ai_evaluated_at).length
  );

  // Filtros persistidos no RecruiterStateService
  readonly onlyCvMatch = this.state.onlyCvMatch;
  readonly hideNonJobs = this.state.hideNonJobs;
  readonly hideUndated = this.state.hideUndated;
  readonly cvAreaBadge = this.state.cvAreaBadge;
  readonly expandedPosts = this.state.expandedPosts;

  get filterText(): string { return this.state.filterText(); }
  set filterText(v: string) {
    this.state.filterText.set(v);
    if (!v.trim() && this.allPosts().length === 0) {
      this.state.hasSearched.set(false);
    }
    this.state.persist();
  }

  get portalFilter(): string { return this.state.portalFilter(); }
  set portalFilter(v: string) {
    this.state.portalFilter.set(v);
    this.state.persist();
  }

  get workModelFilter(): string { return this.state.workModelFilter(); }
  set workModelFilter(v: string) {
    this.state.workModelFilter.set(v);
    this.state.persist();
  }

  get regionFilter(): string { return this.state.regionFilter(); }
  set regionFilter(v: string) {
    this.state.regionFilter.set(v);
    this.state.persist();
  }

  get jobAgeFilter(): string { return this.state.jobAgeFilter(); }
  set jobAgeFilter(v: string) {
    this.state.jobAgeFilter.set(v);
    this.state.persist();
  }

  get scoreFilter(): string { return this.state.scoreFilter(); }
  set scoreFilter(v: string) {
    this.state.scoreFilter.set(v);
    this.state.persist();
  }

  get sortBy(): RecruiterSortMode { return this.state.sortBy(); }
  set sortBy(v: RecruiterSortMode) {
    this.state.sortBy.set(v);
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

  get autoCooldownSeconds(): number { return this.state.autoCooldownSeconds(); }
  set autoCooldownSeconds(v: number) {
    const n = Number(v);
    this.state.autoCooldownSeconds.set(Number.isNaN(n) ? 30 : n);
    this.state.persist();
  }

  // Sorteador de CV
  private cvAreasList: any[] = [];
  private cvAreaQueue: any[] = [];
  private lastPickedAreaId: string | null = null;

  // Subconjunto que bate com as palavras-chave da busca (base antes dos filtros secundários)
  readonly keywordMatchedPosts = computed(() => {
    if (!this.hasSearched()) return [];
    const query = this.state.filterText().trim();
    if (!query) return this.allPosts();
    return this.allPosts().filter(p => {
      const hay = `${p.title || ''} ${p.company || ''} ${p.location || ''} ${p.description || ''} ${p.portal || ''} ${getPortalDisplayName(p.portal)} ${getWorkModelLabel(resolveEffectiveWorkModel(p))} ${(p.emails || []).join(' ')} ${(p.matched_keywords || []).join(' ')}`;
      return matchesTextFilter(hay, query);
    });
  });

  readonly keywordMatchedCount = computed(() => this.keywordMatchedPosts().length);

  readonly evaluatedCount = computed(() =>
    this.keywordMatchedPosts().filter(p => Boolean(p.ai_evaluated_at)).length
  );

  // Lista dinâmica de portais encontrados nos resultados da busca (LinkedIn sempre listado)
  readonly availablePortals = computed(() => {
    const source = this.keywordMatchedPosts().length > 0 ? this.keywordMatchedPosts() : this.allPosts();
    const set = new Set<string>(['linkedin_post']);
    for (const p of source) {
      if (p.portal) set.add(p.portal);
    }
    const active = this.state.portalFilter();
    if (active) set.add(active);
    return Array.from(set).sort();
  });

  ngOnInit(): void {
    this.loadLinkedInStatus();
    this.loadCvAreas();
    this.loadAutoConfig();
    const st = this.autoMode.status();
    if (st?.mode === 'recruiters' && st.keywords?.length && st.running) {
      this.state.filterText.set(st.keywords.join(', '));
      this.state.autoRunFilterApplied.set(true);
      this.state.hasSearched.set(true);
      this.state.persist();
      this.fetchPosts(this.allPosts().length === 0);
      return;
    }

    // Mantém busca restaurada quando há termo + pesquisa ativa na sessão / localStorage
    if (this.state.hasActiveKeywordSearch()) {
      this.fetchPosts(this.allPosts().length === 0);
    } else {
      this.state.hasSearched.set(false);
      this.state.persist();
    }
  }

  onOnlyCvMatchChange(checked: boolean): void {
    this.state.onlyCvMatch.set(checked);
    this.state.persist();
  }

  onHideNonJobsChange(checked: boolean): void {
    this.state.hideNonJobs.set(checked);
    this.state.persist();
  }

  onHideUndatedChange(checked: boolean): void {
    this.state.hideUndated.set(checked);
    this.state.persist();
  }

  resetSecondaryFilters(): void {
    this.state.resetSecondaryFilters();
  }

  getHiddenFilterReasons(): string {
    const base = this.keywordMatchedPosts();
    if (!base.length) return '';
    const reasons: string[] = [];
    const fallbackReasons: string[] = [];

    if (this.portalFilter) {
      const label = `portal "${this.getPortalLabel(this.portalFilter)}"`;
      fallbackReasons.push(label);
      const hidden = base.filter(p => p.portal !== this.portalFilter).length;
      if (hidden > 0) reasons.push(`${label} (${hidden} ocultas)`);
    }
    if (this.workModelFilter) {
      const label = `modelo "${this.getWorkModelDisplay(this.workModelFilter)}"`;
      fallbackReasons.push(label);
      const hidden = base.filter(p => resolveEffectiveWorkModel(p) !== this.workModelFilter).length;
      if (hidden > 0) reasons.push(`${label} (${hidden} ocultas)`);
    }
    if (this.regionFilter) {
      const label = `região "${this.regionFilter}"`;
      fallbackReasons.push(label);
      const hidden = base.filter(p => !matchesRegionFilter(resolveGeo({
        location: p.location,
        portal: p.portal,
        work_model: p.work_model,
        title: p.title,
      }), this.regionFilter)).length;
      if (hidden > 0) reasons.push(`${label} (${hidden} ocultas)`);
    }
    if (this.jobAgeFilter) {
      const days = Number(this.jobAgeFilter);
      const label = `período de ${this.jobAgeFilter} dia(s)`;
      fallbackReasons.push(label);
      const hidden = base.filter(p => {
        const within = isWithinDays(p.published_date, days || 36500);
        if (within === null) return this.hideUndated();
        return !within;
      }).length;
      if (hidden > 0) reasons.push(`${label} (${hidden} ocultas)`);
    } else if (this.hideUndated()) {
      const undated = base.filter(p => parseCalendarDateMs(p.published_date) === null).length;
      fallbackReasons.push('ocultando publicações sem data');
      if (undated > 0) reasons.push(`ocultando ${undated} sem data`);
    }
    if (this.scoreFilter) {
      const label = `avaliação da IA "${this.scoreFilter}"`;
      fallbackReasons.push(label);
      const hidden = base.filter(p => {
        if (this.scoreFilter === 'untriaged') return Boolean(p.ai_evaluated_at);
        const aiScore = p.ai_classification === 'vaga_ativa' ? p.ai_score : null;
        return !matchesScoreFilter(aiScore, this.scoreFilter, Boolean(p.ai_evaluated_at));
      }).length;
      if (hidden > 0) reasons.push(`${label} (${hidden} ocultas)`);
    }
    if (this.onlyCvMatch()) {
      const label = 'apenas compatíveis com CV';
      fallbackReasons.push(label);
      const hidden = base.filter(p => {
        const matched =
          (p.matched_keywords && p.matched_keywords.length > 0) ||
          (p.ai_classification === 'vaga_ativa' && (p.ai_score || 0) > 0);
        return !matched;
      }).length;
      if (hidden > 0) reasons.push(`${label} (${hidden} ocultas)`);
    }
    if (this.hideNonJobs()) {
      const label = 'ocultando "Não é vaga"';
      fallbackReasons.push(label);
      const hidden = base.filter(p => p.ai_classification === 'nao_e_vaga').length;
      if (hidden > 0) reasons.push(`${label} (${hidden} ocultas)`);
    }

    return (reasons.length > 0 ? reasons : fallbackReasons).join(', ');
  }

  isUndated(post: RecruiterPost): boolean {
    return parseCalendarDateMs(post.published_date) === null;
  }

  getWorkModelDisplay(model?: string): string {
    return getWorkModelLabel(model);
  }

  getPostWorkModelDisplay(post: RecruiterPost): string {
    return getWorkModelLabel(resolveEffectiveWorkModel(post));
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

  loadAutoConfig(): void {
    this.api.getRecruiterAutoConfig().subscribe({
      next: (res) => {
        const cfg = res?.config;
        if (!cfg) return;
        const score = Number(cfg.min_score);
        if (!Number.isNaN(score) && score >= 45 && score <= 95) {
          this.autoMinScore = score;
        }
        if (typeof cfg.continuous === 'boolean') {
          this.autoContinuous = cfg.continuous;
        }
        const cooldown = Number(cfg.cooldown_seconds);
        if (!Number.isNaN(cooldown) && cooldown >= 15 && cooldown <= 300) {
          this.autoCooldownSeconds = Math.round(cooldown);
        }
      },
      error: (err) => console.warn('Falha ao carregar configuração automática de recrutadores:', err),
    });
  }

  onAutoConfigChange(): void {
    const clampedScore = Math.max(45, Math.min(95, Math.round(Number(this.autoMinScore) || 60)));
    const clampedSeconds = Math.max(15, Math.min(300, Math.round(Number(this.autoCooldownSeconds) || 30)));
    this.autoMinScore = clampedScore;
    this.autoCooldownSeconds = clampedSeconds;
    this.api.saveRecruiterAutoConfig({
      min_score: clampedScore,
      continuous: this.autoContinuous,
      cooldown_seconds: clampedSeconds,
    }).subscribe({
      error: (err) => this.toast.warning('Não foi possível salvar configuração do Modo Automático: ' + (err?.error?.detail || err?.message || 'Erro')),
    });
  }

  triggerAutoMode(): void {
    if (this.autoMode.isRunning()) {
      this.autoMode.cancel();
      return;
    }

    this.errorMessage.set('');
    this.statusMessage.set('');
    this.cvAreaBadge.set('');
    this.state.scoreFilter.set('');
    this.state.portalFilter.set('');
    this.state.onlyCvMatch.set(false);
    if (this.jobAgeFilter === '1' || this.jobAgeFilter === '2' || this.jobAgeFilter === '3') {
      this.state.jobAgeFilter.set('');
    }
    this.state.autoRunFilterApplied.set(true);
    const minScore = Math.max(45, Math.min(95, Math.round(Number(this.autoMinScore) || 60)));
    const cooldownSeconds = Math.max(15, Math.min(300, Math.round(Number(this.autoCooldownSeconds) || 30)));
    this.autoMinScore = minScore;
    this.autoCooldownSeconds = cooldownSeconds;
    this.state.persist();

    this.autoMode.startRecruiters({
      min_score: minScore,
      continuous: this.autoContinuous,
      cooldown_seconds: cooldownSeconds,
    }).subscribe({
      next: () => {
        if (this.filterText.trim()) {
          this.hasSearched.set(true);
        }
        this.state.persist();
      },
      error: (err) => {
        this.state.autoRunFilterApplied.set(false);
        this.state.persist();
        this.errorMessage.set(err?.error?.detail || err?.message || 'Não foi possível iniciar o Modo Automático em Recrutadores.');
      },
    });
  }

  onSearch(): void {
    const term = (this.filterText || '').trim();
    if (!term) {
      this.errorMessage.set('Por favor, digite pelo menos uma palavra-chave (ex: tecnologia ou cargo) ou clique em "Sortear área CV" antes de buscar.');
      return;
    }

    this.state.autoRunFilterApplied.set(false);
    this.hasSearched.set(true);
    this.state.persist();
    this.loading.set(true);
    this.errorMessage.set('');
    this.statusMessage.set('');

    const days = this.jobAgeFilter ? Number(this.jobAgeFilter) : null;
    const sync$ = days && days > 0
      ? this.api.syncRecruiterPosts(term, { days })
      : this.api.syncRecruiterPosts(term);
    sync$.subscribe({
      next: (res) => {
        const { status, warning } = summarizeRecruiterSync(res);
        if (status) {
          this.statusMessage.set(status);
        }
        if (warning) {
          this.toast.warning(warning);
        }
        this.fetchPosts(true);
        this.loadLinkedInStatus();
      },
      error: (err) => {
        console.warn('Falha parcial ao sincronizar recrutadores:', err);
        this.toast.warning('Sincronização parcial concluída; carregando publicações locais.');
        this.fetchPosts(true);
        this.loadLinkedInStatus();
      }
    });
  }

  onTriagePending(): void {
    if (this.triaging() || this.loading()) return;
    const pendingIds = this.filteredPosts()
      .filter(p => !p.ai_evaluated_at)
      .slice(0, 12)
      .map(p => p.id);

    if (pendingIds.length === 0) {
      this.toast.info('Nenhuma publicação visível pendente de nota da IA.');
      return;
    }

    this.triaging.set(true);
    this.errorMessage.set('');
    this.api.triageRecruiterPosts({ post_ids: pendingIds, limit: 12 }).subscribe({
      next: (res) => {
        this.triaging.set(false);
        const msg = `IA avaliou ${res.triaged} publicação(ões): ${res.active_jobs} vaga(s) ativa(s), ${res.talent_pools_discarded} banco(s) descartado(s).`;
        this.statusMessage.set(msg);
        this.toast.success(msg);
        this.fetchPosts(false);
      },
      error: (err) => {
        this.triaging.set(false);
        const detail = err?.error?.detail || err?.message || 'Não foi possível triar publicações com IA.';
        this.errorMessage.set(detail);
        this.toast.error(detail);
      }
    });
  }

  private fetchPosts(showSpinner = true): void {
    if (showSpinner) {
      this.loading.set(true);
    }
    this.api.getRecruiterPosts().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (res) => {
        this.allPosts.set(res.posts || []);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.errorMessage.set('Erro ao carregar publicações: ' + (err?.error?.detail || err?.message || 'Falha na comunicação'));
      }
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
    this.errorMessage.set('');
    this.statusMessage.set('');
    if (this.allPosts().length > 0) {
      this.hasSearched.set(true);
      this.state.persist();
    } else if (chosen && !this.loading()) {
      this.onSearch();
    } else {
      this.state.persist();
    }
  }

  clearTextFilter(): void {
    this.filterText = '';
    this.cvAreaBadge.set('');
    this.hasSearched.set(false);
    this.errorMessage.set('');
    this.statusMessage.set('');
    this.state.persist();
  }

  loadLinkedInStatus(): void {
    if (!this.api.getLinkedInWorkerStatus) return;
    this.api.getLinkedInWorkerStatus()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (st) => {
          this.linkedInStatus.set(st);
          this.syncLoginPollTimer(st?.status);
          if (
            st?.status === 'awaiting_login'
            && st.login_window_open === false
            && !this.autoVerifyingLogin
            && !this.linkedInBusy()
          ) {
            this.autoVerifyingLogin = true;
            this.verifyLinkedIn();
          }
        },
        error: () => {
          // status opcional em caso de falha transitória
        },
      });
  }

  private syncLoginPollTimer(status?: string): void {
    if (status === 'awaiting_login') {
      if (!this.linkedInPollTimer) {
        this.linkedInPollTimer = setInterval(() => {
          this.loadLinkedInStatus();
        }, 3000);
      }
      return;
    }
    this.stopLoginPollTimer();
  }

  private stopLoginPollTimer(): void {
    if (this.linkedInPollTimer) {
      clearInterval(this.linkedInPollTimer);
      this.linkedInPollTimer = null;
    }
  }

  connectLinkedIn(): void {
    if (this.linkedInBusy()) return;
    this.autoVerifyingLogin = false;
    this.linkedInBusy.set(true);
    this.api.connectLinkedInWorker()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (st) => {
          this.linkedInBusy.set(false);
          this.linkedInStatus.set(st);
          this.syncLoginPollTimer(st?.status);
          if (st?.status === 'connected') {
            this.toast.success('LinkedIn conectado! Agora o Modo Automático e a Busca já incluem publicações de lá.');
          } else {
            this.toast.info('Janela aberta! Entre no LinkedIn lá e feche a janela ao terminar (ou clique em "Já entrei").');
          }
        },
        error: (err) => {
          this.linkedInBusy.set(false);
          this.toast.error(err?.error?.detail || err?.message || 'Não foi possível abrir o navegador isolado.');
        },
      });
  }

  verifyLinkedIn(): void {
    if (this.linkedInBusy()) return;
    this.linkedInBusy.set(true);
    this.api.verifyLinkedInWorker()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (st) => {
          this.linkedInBusy.set(false);
          this.linkedInStatus.set(st);
          this.syncLoginPollTimer(st?.status);
          if (st?.status === 'connected') {
            this.toast.success('Sessão do LinkedIn confirmada! Pronto para coleta automática.');
          } else {
            this.toast.warning(st?.message || st?.last_error || 'Conclua o login na janela aberta e feche-a ao terminar.');
          }
        },
        error: (err) => {
          this.linkedInBusy.set(false);
          this.toast.warning(err?.error?.detail || err?.message || 'Falha ao verificar a sessão do LinkedIn.');
        },
      });
  }

  disconnectLinkedIn(): void {
    if (this.linkedInBusy()) return;
    this.autoVerifyingLogin = false;
    this.linkedInBusy.set(true);
    this.stopLoginPollTimer();
    this.api.disconnectLinkedInWorker()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (st) => {
          this.linkedInBusy.set(false);
          this.linkedInStatus.set(st);
          this.toast.info('LinkedIn desconectado e perfil isolado limpo.');
        },
        error: (err) => {
          this.linkedInBusy.set(false);
          this.toast.error(err?.error?.detail || err?.message || 'Falha ao desconectar LinkedIn.');
        },
      });
  }

  dismissPost(postId: number): void {
    this.api.dismissRecruiterPost(postId).subscribe({
      next: () => {
        if (this.copiedPrompt()?.postId === postId) {
          this.copiedPrompt.set(null);
        }
        this.allPosts.update(posts => posts.filter(p => p.id !== postId));
      },
      error: (err) => {
        this.errorMessage.set('Erro ao remover publicação: ' + (err?.error?.detail || err?.message || 'Falha'));
      }
    });
  }

  isPostBusy(postId: number): boolean {
    return this.busyPostIds().has(postId);
  }

  private setPostBusy(postId: number, busy: boolean): void {
    this.busyPostIds.update(set => {
      const next = new Set(set);
      if (busy) {
        next.add(postId);
      } else {
        next.delete(postId);
      }
      return next;
    });
  }

  getPreviouslyContactedMatch(post: RecruiterPost, email: string): PreviouslyContactedEmail | undefined {
    const norm = (email || '').trim().toLowerCase();
    return (post.previously_contacted || []).find(m => m.email.trim().toLowerCase() === norm);
  }

  formatShortDate(raw?: string): string {
    if (!raw) return 'recentemente';
    const d = String(raw).substring(0, 10);
    const parts = d.split('-');
    if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
    return d;
  }

  saveAsInterested(post: RecruiterPost): void {
    if (this.isPostBusy(post.id)) return;
    this.errorMessage.set('');
    this.setPostBusy(post.id, true);

    this.api.markRecruiterPostInterested(post.id).subscribe({
      next: () => {
        this.setPostBusy(post.id, false);
        if (this.copiedPrompt()?.postId === post.id) {
          this.copiedPrompt.set(null);
        }
        if (this.multiEmailPickerPostId() === post.id) {
          this.multiEmailPickerPostId.set(null);
        }
        this.allPosts.update(posts => posts.filter(p => p.id !== post.id));
        this.statusMessage.set(`"${post.company}" salva em Me Interessam!`);
      },
      error: (err) => {
        this.setPostBusy(post.id, false);
        this.errorMessage.set('Erro ao salvar em Me Interessam: ' + (err?.error?.detail || err?.message || 'Falha'));
      }
    });
  }

  onMarkContactedClick(post: RecruiterPost, explicitEmail?: string): void {
    if (this.isPostBusy(post.id)) return;
    const emails = post.emails || [];

    if (!explicitEmail && emails.length > 1) {
      this.multiEmailPickerPostId.set(
        this.multiEmailPickerPostId() === post.id ? null : post.id
      );
      return;
    }

    const targetEmail = (explicitEmail || post.ai_best_email || emails[0] || '').trim();
    if (!targetEmail) {
      this.errorMessage.set('Nenhum e-mail de contato disponível nesta publicação.');
      return;
    }

    const prev = this.getPreviouslyContactedMatch(post, targetEmail);
    if (prev) {
      const ok = confirm(
        `Você já registrou envio para ${targetEmail} em ${this.formatShortDate(prev.contacted_at)} (${prev.company || 'empresa anterior'}). Deseja registrar este novo envio também?`
      );
      if (!ok) return;
    }

    this.submitMarkContacted(post, targetEmail);
  }

  private submitMarkContacted(post: RecruiterPost, targetEmail: string): void {
    this.errorMessage.set('');
    this.setPostBusy(post.id, true);

    this.api.markRecruiterPostContacted(post.id, { email: targetEmail }).subscribe({
      next: (res) => {
        this.setPostBusy(post.id, false);
        if (this.copiedPrompt()?.postId === post.id) {
          this.copiedPrompt.set(null);
        }
        if (this.multiEmailPickerPostId() === post.id) {
          this.multiEmailPickerPostId.set(null);
        }
        this.allPosts.update(posts =>
          removePostAndFlagEmail(posts, post.id, targetEmail, {
            company: post.company,
            title: post.title,
            contacted_at: res?.contacted_at || new Date().toISOString().substring(0, 10),
            job_id: res?.job_id,
            application_id: res?.application_id,
          })
        );
        this.statusMessage.set(`Envio para ${res?.contacted_email || targetEmail} registrado em Minhas Candidaturas!`);
      },
      error: (err) => {
        this.setPostBusy(post.id, false);
        this.errorMessage.set('Erro ao registrar contato: ' + (err?.error?.detail || err?.message || 'Falha'));
      }
    });
  }

  dismissCopyPrompt(): void {
    this.copiedPrompt.set(null);
  }

  ngOnDestroy(): void {
    this.stopLoginPollTimer();
    if (this.copyEmailTimer) {
      clearTimeout(this.copyEmailTimer);
      this.copyEmailTimer = null;
    }
  }

  copyEmail(email: string, post?: RecruiterPost): void {
    if (!email) return;
    const onCopied = () => {
      this.copiedEmail.set(email);
      if (post?.id) {
        this.copiedPrompt.set({ postId: post.id, email });
      }
      if (this.copyEmailTimer) {
        clearTimeout(this.copyEmailTimer);
      }
      this.copyEmailTimer = setTimeout(() => {
        this.copyEmailTimer = null;
        if (this.copiedEmail() === email) {
          this.copiedEmail.set(null);
        }
      }, 2500);
    };

    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(email).then(onCopied).catch(onCopied);
    } else {
      onCopied();
    }
  }

  toggleExpand(postId: number): void {
    this.expandedPosts.update(set => {
      const next = new Set(set);
      if (next.has(postId)) {
        next.delete(postId);
      } else {
        next.add(postId);
      }
      return next;
    });
  }

  isExpanded(postId: number): boolean {
    return this.expandedPosts().has(postId);
  }

  getPortalLabel(portal: string): string {
    return getPortalDisplayName(portal);
  }

  getPortalOriginInfo(post: RecruiterPost): string {
    if (post.portal === 'linkedin_post') {
      return 'Publicação coletada do feed do LinkedIn';
    }
    if (post.portal === 'hn-search') {
      return 'Thread "Who is Hiring" do Hacker News';
    }
    if (post.portal === 'github-vagas') {
      return 'Issue aberta em repositório brasileiro de vagas tech no GitHub (e-mail direto)';
    }
    const label = this.getPortalLabel(post.portal);
    return `Vaga do portal ${label} (e-mail de contato direto minerado da descrição)`;
  }
}
