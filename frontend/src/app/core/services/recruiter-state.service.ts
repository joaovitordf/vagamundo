import { Injectable, computed, signal } from '@angular/core';
import { RecruiterPost } from '../models/vaga.model';
import {
  getPortalDisplayName,
  getWorkModelLabel,
  isWithinDays,
  matchesRegionFilter,
  matchesScoreFilter,
  matchesTextFilter,
  parseCalendarDateMs,
  resolveEffectiveWorkModel,
  resolveGeo,
} from '../utils/job-filters.util';

export const RECRUITER_STATE_STORAGE_KEY = 'vagamundo.recruiterState.v1';

export type RecruiterSortMode = 'relevance' | 'date' | 'score-desc' | 'score-asc';

interface PersistedRecruiterState {
  filterText?: string;
  cvAreaBadge?: string;
  autoRunFilterApplied?: boolean;
  portalFilter?: string;
  workModelFilter?: string;
  regionFilter?: string;
  jobAgeFilter?: string;
  jobAgeDefault24hApplied?: boolean;
  hideUndated?: boolean;
  scoreFilter?: string;
  sortBy?: RecruiterSortMode;
  onlyCvMatch?: boolean;
  hideNonJobs?: boolean;
  autoMinScore?: number;
  autoContinuous?: boolean;
  autoCooldownSeconds?: number;
  hasSearched?: boolean;
}

export function filterAndSortRecruiterPosts(
  allPosts: RecruiterPost[],
  opts: {
    hasSearched: boolean;
    filterText: string;
    portalFilter: string;
    workModelFilter: string;
    regionFilter: string;
    jobAgeFilter: string;
    hideUndated: boolean;
    scoreFilter: string;
    sortBy: RecruiterSortMode;
    onlyCvMatch: boolean;
    hideNonJobs: boolean;
    autoMinScore?: number;
    ignoreTextFilter?: boolean;
  }
): RecruiterPost[] {
  if (!opts.hasSearched) return [];

  const query = opts.filterText.trim();
  const days = opts.jobAgeFilter ? Number(opts.jobAgeFilter) : null;
  const minScore = opts.autoMinScore ?? 60;

  let posts = allPosts.filter(p => {
    if (opts.hideNonJobs && p.ai_classification === 'nao_e_vaga') {
      return false;
    }

    if (opts.onlyCvMatch) {
      const aiMatch = p.ai_classification === 'vaga_ativa' && (p.ai_score ?? 0) >= minScore;
      const matched = p.ai_evaluated_at
        ? aiMatch
        : ((p.matched_keywords && p.matched_keywords.length > 0) || aiMatch);
      if (!matched) return false;
    }

    if (opts.portalFilter && p.portal !== opts.portalFilter) {
      return false;
    }

    if (opts.workModelFilter) {
      if (resolveEffectiveWorkModel(p) !== opts.workModelFilter) {
        return false;
      }
    }

    if (opts.regionFilter) {
      const geo = resolveGeo({
        location: p.location,
        portal: p.portal,
        work_model: p.work_model,
        title: p.title,
      });
      if (!matchesRegionFilter(geo, opts.regionFilter)) {
        return false;
      }
    }

    if (opts.hideUndated || days) {
      const within = isWithinDays(p.published_date, days || 36500);
      if (within === null) {
        if (opts.hideUndated) return false;
      } else if (days && !within) {
        const createdWithin = isWithinDays(p.created_at, days);
        const keepAutoLinkedIn = Boolean(opts.ignoreTextFilter && p.portal === 'linkedin_post');
        if (createdWithin !== true && !keepAutoLinkedIn) {
          return false;
        }
      }
    }

    if (opts.scoreFilter) {
      if (opts.scoreFilter === 'untriaged') {
        if (p.ai_evaluated_at) return false;
      } else {
        const aiScore = p.ai_classification === 'vaga_ativa' ? p.ai_score : null;
        if (!matchesScoreFilter(aiScore, opts.scoreFilter, Boolean(p.ai_evaluated_at))) {
          return false;
        }
      }
    }

    if (query && !opts.ignoreTextFilter) {
      const hay = `${p.title || ''} ${p.company || ''} ${p.location || ''} ${p.description || ''} ${p.portal || ''} ${getPortalDisplayName(p.portal)} ${getWorkModelLabel(resolveEffectiveWorkModel(p))} ${(p.emails || []).join(' ')} ${(p.matched_keywords || []).join(' ')}`;
      if (!matchesTextFilter(hay, query)) return false;
    }

    return true;
  });

  posts = [...posts].sort((a, b) => {
    // Sempre mantém "Não é vaga" abaixo das vagas reais quando visível
    const nonJobA = a.ai_classification === 'nao_e_vaga' ? 1 : 0;
    const nonJobB = b.ai_classification === 'nao_e_vaga' ? 1 : 0;
    if (nonJobA !== nonJobB) return nonJobA - nonJobB;

    if (opts.sortBy === 'date') {
      const da = parseCalendarDateMs(a.published_date);
      const db = parseCalendarDateMs(b.published_date);
      if (da === null && db === null) return b.id - a.id;
      if (da === null) return 1;
      if (db === null) return -1;
      if (db !== da) return db - da;
      return b.id - a.id;
    }

    if (opts.sortBy === 'score-desc') {
      const sa = a.ai_classification === 'vaga_ativa' && a.ai_score !== null && a.ai_score !== undefined ? a.ai_score : -1;
      const sb = b.ai_classification === 'vaga_ativa' && b.ai_score !== null && b.ai_score !== undefined ? b.ai_score : -1;
      if (sb !== sa) return sb - sa;
      const da = parseCalendarDateMs(a.published_date) ?? -1;
      const db = parseCalendarDateMs(b.published_date) ?? -1;
      if (db !== da) return db - da;
      return b.id - a.id;
    }

    if (opts.sortBy === 'score-asc') {
      const sa = a.ai_classification === 'vaga_ativa' && a.ai_score !== null && a.ai_score !== undefined ? a.ai_score : 999;
      const sb = b.ai_classification === 'vaga_ativa' && b.ai_score !== null && b.ai_score !== undefined ? b.ai_score : 999;
      if (sa !== sb) return sa - sb;
      const da = parseCalendarDateMs(a.published_date) ?? -1;
      const db = parseCalendarDateMs(b.published_date) ?? -1;
      if (db !== da) return db - da;
      return b.id - a.id;
    }

    // Padrão 'relevance': maior nota da IA (avaliadas primeiro), depois mais recente e qtd de tags do CV
    const relA = a.ai_classification === 'vaga_ativa' && a.ai_score !== null && a.ai_score !== undefined ? a.ai_score : -1;
    const relB = b.ai_classification === 'vaga_ativa' && b.ai_score !== null && b.ai_score !== undefined ? b.ai_score : -1;
    if (relB !== relA) return relB - relA;
    const da = parseCalendarDateMs(a.published_date) ?? -1;
    const db = parseCalendarDateMs(b.published_date) ?? -1;
    if (db !== da) return db - da;
    const tagDiff = (b.matched_keywords?.length || 0) - (a.matched_keywords?.length || 0);
    if (tagDiff !== 0) return tagDiff;
    return b.id - a.id;
  });

  return posts;
}

/**
 * Filtra e ordena o histórico acumulado de vagas relevantes já triadas pela IA local.
 * Inclui todas as `vaga_ativa` com nota atribuída (inclusive < 45 para limpeza manual),
 * ignorando os filtros temporários do console de busca.
 */
export function filterAndSortRelevantHistoryPosts(posts: RecruiterPost[]): RecruiterPost[] {
  return [...posts]
    .filter(
      p =>
        p.portal === 'linkedin_post' &&
        Array.isArray(p.emails) &&
        p.emails.length > 0 &&
        Boolean(p.ai_evaluated_at) &&
        p.ai_classification === 'vaga_ativa' &&
        typeof p.ai_score === 'number'
    )
    .sort((a, b) => {
      const scoreDiff = (b.ai_score ?? -1) - (a.ai_score ?? -1);
      if (scoreDiff !== 0) return scoreDiff;
      const da = parseCalendarDateMs(a.published_date || a.created_at) ?? -1;
      const db = parseCalendarDateMs(b.published_date || b.created_at) ?? -1;
      if (db !== da) return db - da;
      return b.id - a.id;
    });
}

@Injectable({
  providedIn: 'root',
})
export class RecruiterStateService {
  readonly filterText = signal<string>('');
  readonly cvAreaBadge = signal<string>('');
  readonly autoRunFilterApplied = signal<boolean>(false);

  readonly portalFilter = signal<string>('');
  readonly workModelFilter = signal<string>('');
  readonly regionFilter = signal<string>('');
  readonly jobAgeFilter = signal<string>('1');
  readonly hideUndated = signal<boolean>(false);
  readonly scoreFilter = signal<string>('');
  readonly sortBy = signal<RecruiterSortMode>('relevance');
  readonly onlyCvMatch = signal<boolean>(false);
  readonly hideNonJobs = signal<boolean>(false);
  readonly autoMinScore = signal<number>(60);
  readonly autoContinuous = signal<boolean>(true);
  readonly autoCooldownSeconds = signal<number>(30);
  readonly hasSearched = signal<boolean>(false);

  // Estado em memória durante a sessão
  readonly allPosts = signal<RecruiterPost[]>([]);
  readonly expandedPosts = signal<Set<number>>(new Set());
  readonly loading = signal<boolean>(false);
  readonly statusMessage = signal<string>('');
  readonly errorMessage = signal<string>('');

  readonly filteredPosts = computed(() =>
    filterAndSortRecruiterPosts(this.allPosts(), {
      hasSearched: this.hasSearched(),
      filterText: this.filterText(),
      portalFilter: this.portalFilter(),
      workModelFilter: this.workModelFilter(),
      regionFilter: this.regionFilter(),
      jobAgeFilter: this.jobAgeFilter(),
      hideUndated: this.hideUndated(),
      scoreFilter: this.scoreFilter(),
      sortBy: this.sortBy(),
      onlyCvMatch: this.onlyCvMatch(),
      hideNonJobs: this.hideNonJobs(),
      autoMinScore: this.autoMinScore(),
      ignoreTextFilter: this.autoRunFilterApplied(),
    })
  );

  readonly historyPosts = computed(() =>
    filterAndSortRelevantHistoryPosts(this.allPosts())
  );

  readonly hasSecondaryFilters = computed(() => {
    return Boolean(
      this.portalFilter() ||
      this.workModelFilter() ||
      this.regionFilter() ||
      (this.jobAgeFilter() && this.jobAgeFilter() !== '1') ||
      this.hideUndated() ||
      this.scoreFilter() ||
      this.onlyCvMatch() ||
      this.hideNonJobs() ||
      this.sortBy() !== 'relevance'
    );
  });

  constructor() {
    this.restoreFromStorage();
  }

  hasActiveKeywordSearch(): boolean {
    return this.hasSearched() && this.filterText().trim().length > 0;
  }

  resetSecondaryFilters(): void {
    this.portalFilter.set('');
    this.workModelFilter.set('');
    this.regionFilter.set('');
    this.jobAgeFilter.set('1');
    this.hideUndated.set(false);
    this.scoreFilter.set('');
    this.onlyCvMatch.set(false);
    this.hideNonJobs.set(false);
    this.sortBy.set('relevance');
    this.persist();
  }

  persist(): void {
    try {
      const effectiveHasSearched = this.hasSearched() && this.filterText().trim().length > 0;
      const payload: PersistedRecruiterState = {
        filterText: this.filterText(),
        cvAreaBadge: this.cvAreaBadge(),
        autoRunFilterApplied: this.autoRunFilterApplied(),
        portalFilter: this.portalFilter(),
        workModelFilter: this.workModelFilter(),
        regionFilter: this.regionFilter(),
        jobAgeFilter: this.jobAgeFilter(),
        jobAgeDefault24hApplied: true,
        hideUndated: this.hideUndated(),
        scoreFilter: this.scoreFilter(),
        sortBy: this.sortBy(),
        onlyCvMatch: this.onlyCvMatch(),
        hideNonJobs: this.hideNonJobs(),
        autoMinScore: this.autoMinScore(),
        autoContinuous: this.autoContinuous(),
        autoCooldownSeconds: this.autoCooldownSeconds(),
        hasSearched: effectiveHasSearched,
      };
      localStorage.setItem(RECRUITER_STATE_STORAGE_KEY, JSON.stringify(payload));
    } catch {
      // Ignora falhas de storage
    }
  }

  restoreFromStorage(): void {
    try {
      const raw = localStorage.getItem(RECRUITER_STATE_STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as PersistedRecruiterState;
      if (!parsed || typeof parsed !== 'object') return;

      if (typeof parsed.filterText === 'string') this.filterText.set(parsed.filterText);
      if (typeof parsed.cvAreaBadge === 'string') this.cvAreaBadge.set(parsed.cvAreaBadge);
      if (typeof parsed.autoRunFilterApplied === 'boolean') this.autoRunFilterApplied.set(parsed.autoRunFilterApplied);
      if (typeof parsed.portalFilter === 'string') this.portalFilter.set(parsed.portalFilter);
      if (typeof parsed.workModelFilter === 'string') this.workModelFilter.set(parsed.workModelFilter);
      if (typeof parsed.regionFilter === 'string') this.regionFilter.set(parsed.regionFilter);
      if (parsed.jobAgeDefault24hApplied !== true) {
        if (typeof parsed.jobAgeFilter === 'string' && parsed.jobAgeFilter) {
          this.jobAgeFilter.set(parsed.jobAgeFilter);
        } else {
          this.jobAgeFilter.set('1');
        }
      } else if (typeof parsed.jobAgeFilter === 'string') {
        this.jobAgeFilter.set(parsed.jobAgeFilter);
      }
      if (typeof parsed.hideUndated === 'boolean') this.hideUndated.set(parsed.hideUndated);
      if (
        typeof parsed.scoreFilter === 'string' &&
        ['', 'high', 'med_plus', 'med', 'low', 'triadas', 'untriaged'].includes(parsed.scoreFilter)
      ) {
        this.scoreFilter.set(parsed.scoreFilter);
      } else {
        this.scoreFilter.set('');
      }

      if (
        parsed.sortBy === 'relevance' ||
        parsed.sortBy === 'date' ||
        parsed.sortBy === 'score-desc' ||
        parsed.sortBy === 'score-asc'
      ) {
        this.sortBy.set(parsed.sortBy);
      } else {
        this.sortBy.set('relevance');
      }

      if (typeof parsed.onlyCvMatch === 'boolean') this.onlyCvMatch.set(parsed.onlyCvMatch);
      if (typeof parsed.hideNonJobs === 'boolean') this.hideNonJobs.set(parsed.hideNonJobs);

      if (typeof parsed.autoMinScore === 'number' && !Number.isNaN(parsed.autoMinScore)) {
        this.autoMinScore.set(Math.max(45, Math.min(95, parsed.autoMinScore)));
      }
      if (typeof parsed.autoContinuous === 'boolean') {
        this.autoContinuous.set(parsed.autoContinuous);
      }
      if (typeof parsed.autoCooldownSeconds === 'number' && !Number.isNaN(parsed.autoCooldownSeconds)) {
        this.autoCooldownSeconds.set(Math.max(15, Math.min(300, Math.round(parsed.autoCooldownSeconds))));
      }

      if (typeof parsed.hasSearched === 'boolean') {
        const hasTerms = this.filterText().trim().length > 0;
        this.hasSearched.set(parsed.hasSearched && hasTerms);
      }
    } catch {
      // Mantém defaults seguros
    }
  }
}
