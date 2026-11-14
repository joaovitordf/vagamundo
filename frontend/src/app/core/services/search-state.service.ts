import { Injectable, signal } from '@angular/core';
import { Vaga } from '../models/vaga.model';
import {
  ActiveGeoFilter,
  AVAILABLE_PORTALS,
  VALID_PORTAL_IDS,
} from '../utils/job-filters.util';

export const SEARCH_STATE_STORAGE_KEY = 'vagamundo.searchState.v1';

export interface SearchPortalStatus {
  portal: string;
  label: string;
  status: string;
  jobs: number;
  error?: string;
}

interface PersistedSearchState {
  filterText?: string;
  cvAreaBadge?: string;
  lastSearchQuery?: string;
  selectedPortalIds?: string[];
  filterModel?: string;
  filterRegion?: string;
  filterJobAge?: string;
  filterScore?: string;
  filterSort?: 'date' | 'score-desc' | 'score-asc';
  filterNoWarn?: boolean;
  filterHideUndated?: boolean;
  filterVisa?: boolean;
  activeSubtab?: 'mapa' | 'lista';
  currentMapMode?: 'world' | 'brasil';
  activeGeoFilter?: ActiveGeoFilter | null;
  isTriageMode?: boolean;
  batchScope?: string;
  autoMinScore?: number;
  autoContinuous?: boolean;
  autoCooldownMinutes?: number;
  hasSearched?: boolean;
  savedDay?: string | null;
}

export function localTodayIso(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

@Injectable({
  providedIn: 'root',
})
export class SearchStateService {
  // Preferências / filtros persistidos em localStorage
  readonly filterText = signal<string>('');
  readonly cvAreaBadge = signal<string>('');
  readonly lastSearchQuery = signal<string>('');
  readonly selectedPortalIds = signal<Set<string>>(new Set(AVAILABLE_PORTALS.map(p => p.id)));
  readonly filterPortalSearchText = signal<string>('');
  readonly filterModel = signal<string>('');
  readonly filterRegion = signal<string>('');
  readonly filterJobAge = signal<string>('');
  readonly filterScore = signal<string>('');
  readonly filterSort = signal<'date' | 'score-desc' | 'score-asc'>('date');
  readonly filterNoWarn = signal<boolean>(false);
  readonly filterHideUndated = signal<boolean>(false);
  readonly filterVisa = signal<boolean>(false);
  readonly activeSubtab = signal<'mapa' | 'lista'>('mapa');
  readonly currentMapMode = signal<'world' | 'brasil'>('world');
  readonly activeGeoFilter = signal<ActiveGeoFilter | null>(null);
  readonly isTriageMode = signal<boolean>(false);
  readonly batchScope = signal<string>('all-visible');
  readonly autoMinScore = signal<number>(60);
  readonly autoContinuous = signal<boolean>(true);
  readonly autoCooldownMinutes = signal<number>(5);
  readonly hasSearched = signal<boolean>(false);
  readonly savedDay = signal<string | null>(null);

  // Estado em memória durante a sessão (preservado entre trocas de rota)
  readonly allVagas = signal<Vaga[]>([]);
  readonly selectedUrls = signal<Set<string>>(new Set());

  readonly searching = signal<boolean>(false);
  readonly searchStatus = signal<string>('');
  readonly searchError = signal<string>('');
  readonly searchSummary = signal<string>('');
  readonly showProgressPanel = signal<boolean>(false);
  readonly progressExpanded = signal<boolean>(true);
  readonly searchProgressPercent = signal<number>(0);
  readonly searchCompletedCount = signal<number>(0);
  readonly searchTotalCount = signal<number>(0);
  readonly searchCurrentPortal = signal<string>('');
  readonly searchJobsFoundCount = signal<number>(0);
  readonly searchPortalStatuses = signal<SearchPortalStatus[]>([]);

  readonly batchRunning = signal<boolean>(false);
  readonly batchStatus = signal<string>('');
  readonly showTriagePanel = signal<boolean>(false);
  readonly triageExpanded = signal<boolean>(true);
  readonly triageProgressPercent = signal<number>(0);
  readonly triageCurrentCount = signal<number>(0);
  readonly triageTotalCount = signal<number>(0);
  readonly triageCurrentTitle = signal<string>('');
  readonly triageHighFitCount = signal<number>(0);
  readonly triageMedFitCount = signal<number>(0);
  readonly triageLowFitCount = signal<number>(0);
  readonly triageErrorCount = signal<number>(0);
  readonly triageProviderLabel = signal<string>('IA ativa');

  constructor() {
    this.restoreFromStorage();
  }

  hasTodaySearch(): boolean {
    return this.hasSearched() && this.savedDay() === localTodayIso();
  }

  markSearchExecuted(query?: string): void {
    this.hasSearched.set(true);
    this.savedDay.set(localTodayIso());
    if (query !== undefined) {
      this.lastSearchQuery.set(query);
    }
    this.persist();
  }

  clearSearchSession(): void {
    this.allVagas.set([]);
    this.selectedUrls.set(new Set());
    this.hasSearched.set(false);
    this.savedDay.set(null);
    this.searchSummary.set('');
    this.searchStatus.set('');
    this.persist();
  }

  resetFilters(): void {
    this.filterText.set('');
    this.cvAreaBadge.set('');
    this.filterModel.set('');
    this.selectedPortalIds.set(new Set(AVAILABLE_PORTALS.map(p => p.id)));
    this.filterRegion.set('');
    this.filterJobAge.set('');
    this.filterScore.set('');
    this.filterSort.set('date');
    this.filterNoWarn.set(false);
    this.filterHideUndated.set(false);
    this.filterVisa.set(false);
    this.activeGeoFilter.set(null);
    this.persist();
  }

  persist(): void {
    try {
      const payload: PersistedSearchState = {
        filterText: this.filterText(),
        cvAreaBadge: this.cvAreaBadge(),
        lastSearchQuery: this.lastSearchQuery(),
        selectedPortalIds: Array.from(this.selectedPortalIds()),
        filterModel: this.filterModel(),
        filterRegion: this.filterRegion(),
        filterJobAge: this.filterJobAge(),
        filterScore: this.filterScore(),
        filterSort: this.filterSort(),
        filterNoWarn: this.filterNoWarn(),
        filterHideUndated: this.filterHideUndated(),
        filterVisa: this.filterVisa(),
        activeSubtab: this.activeSubtab(),
        currentMapMode: this.currentMapMode(),
        activeGeoFilter: this.activeGeoFilter(),
        isTriageMode: this.isTriageMode(),
        batchScope: this.batchScope(),
        autoMinScore: this.autoMinScore(),
        autoContinuous: this.autoContinuous(),
        autoCooldownMinutes: this.autoCooldownMinutes(),
        hasSearched: this.hasSearched(),
        savedDay: this.savedDay(),
      };
      localStorage.setItem(SEARCH_STATE_STORAGE_KEY, JSON.stringify(payload));
    } catch {
      // Ignora falhas de storage (modo privado / cota)
    }
  }

  restoreFromStorage(): void {
    try {
      const raw = localStorage.getItem(SEARCH_STATE_STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as PersistedSearchState;
      if (!parsed || typeof parsed !== 'object') return;

      if (typeof parsed.filterText === 'string') this.filterText.set(parsed.filterText);
      if (typeof parsed.cvAreaBadge === 'string') this.cvAreaBadge.set(parsed.cvAreaBadge);
      if (typeof parsed.lastSearchQuery === 'string') this.lastSearchQuery.set(parsed.lastSearchQuery);

      if (Array.isArray(parsed.selectedPortalIds)) {
        const sanitized = parsed.selectedPortalIds.filter(id => VALID_PORTAL_IDS.has(id));
        this.selectedPortalIds.set(new Set(sanitized));
      }

      if (typeof parsed.filterModel === 'string') this.filterModel.set(parsed.filterModel);
      if (typeof parsed.filterRegion === 'string') this.filterRegion.set(parsed.filterRegion);
      if (typeof parsed.filterJobAge === 'string') this.filterJobAge.set(parsed.filterJobAge);
      if (typeof parsed.filterScore === 'string') this.filterScore.set(parsed.filterScore);
      if (parsed.filterSort === 'date' || parsed.filterSort === 'score-desc' || parsed.filterSort === 'score-asc') {
        this.filterSort.set(parsed.filterSort);
      }

      if (typeof parsed.filterNoWarn === 'boolean') this.filterNoWarn.set(parsed.filterNoWarn);
      if (typeof parsed.filterHideUndated === 'boolean') this.filterHideUndated.set(parsed.filterHideUndated);
      if (typeof parsed.filterVisa === 'boolean') this.filterVisa.set(parsed.filterVisa);

      if (parsed.activeSubtab === 'mapa' || parsed.activeSubtab === 'lista') {
        this.activeSubtab.set(parsed.activeSubtab);
      }
      if (parsed.currentMapMode === 'world' || parsed.currentMapMode === 'brasil') {
        this.currentMapMode.set(parsed.currentMapMode);
      }
      if (parsed.activeGeoFilter && typeof parsed.activeGeoFilter === 'object' && parsed.activeGeoFilter.code) {
        this.activeGeoFilter.set(parsed.activeGeoFilter);
      }
      if (typeof parsed.isTriageMode === 'boolean') this.isTriageMode.set(parsed.isTriageMode);
      if (typeof parsed.batchScope === 'string') this.batchScope.set(parsed.batchScope);

      if (typeof parsed.autoMinScore === 'number' && !Number.isNaN(parsed.autoMinScore)) {
        this.autoMinScore.set(Math.max(45, Math.min(95, parsed.autoMinScore)));
      }
      if (typeof parsed.autoContinuous === 'boolean') {
        this.autoContinuous.set(parsed.autoContinuous);
      }
      if (typeof parsed.autoCooldownMinutes === 'number' && !Number.isNaN(parsed.autoCooldownMinutes)) {
        this.autoCooldownMinutes.set(Math.max(2, Math.min(30, Math.round(parsed.autoCooldownMinutes))));
      }
      if (typeof parsed.savedDay === 'string') this.savedDay.set(parsed.savedDay);
      if (typeof parsed.hasSearched === 'boolean') {
        this.hasSearched.set(parsed.hasSearched && parsed.savedDay === localTodayIso());
      }
    } catch {
      // Mantém defaults seguros se JSON estiver corrompido
    }
  }
}
