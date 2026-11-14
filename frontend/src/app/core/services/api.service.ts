import { Injectable, computed, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map, catchError, tap } from 'rxjs/operators';
import { Vaga, ProfileResponse, SettingsResponse, EvolutionResponse, ApplicationTimelineEvent, ApplicationRecord, GeneratedDoc, DashboardStats, RecruiterPost } from '../models/vaga.model';
import { SearchStateService } from './search-state.service';
import { RecruiterStateService } from './recruiter-state.service';

export interface SyncRecruiterPortalStats {
  fetched: number;
  matched: number;
  errors: number;
  last_error?: string | null;
}

export interface SyncRecruiterPostsResponse {
  ok: boolean;
  scanned: number;
  posts_with_email: number;
  synced: number;
  hn_synced?: number;
  github_synced?: number;
  remotive_synced?: number;
  scrapes_synced?: number;
  portal_synced?: number;
  linkedin_synced?: number;
  linkedin_cards_total?: number;
  linkedin_cooldown_remaining_seconds?: number;
  linkedin_skipped_reason?: string | null;
  linkedin_alert?: string | null;
  collected_urls?: string[];
  collected_post_ids?: number[];
  portal_breakdown?: Record<string, SyncRecruiterPortalStats>;
  warnings?: string[];
  rate_limited?: boolean;
  errors?: number;
}

export interface RecruiterTriageResponse {
  ok: boolean;
  triaged: number;
  active_jobs: number;
  talent_pools_discarded: number;
  not_a_job: number;
  errors: number;
  posts: RecruiterPost[];
}

export interface LinkedInWorkerStatus {
  ok?: boolean;
  status: 'not_connected' | 'awaiting_login' | 'connected' | 'login_required' | 'checkpoint_required' | 'unavailable';
  browser_available: boolean;
  browser_name: string | null;
  profile_initialized: boolean;
  login_window_open?: boolean;
  enabled: boolean;
  headless: boolean;
  cooldown_minutes: number;
  max_daily_searches: number;
  max_scrolls: number;
  daily_date: string | null;
  daily_count: number;
  cooldown_remaining_seconds: number;
  last_run_at: string | null;
  last_error: string;
  last_query: string;
  last_imported: number;
  last_cards_total?: number;
  message?: string;
}

export interface PasteRecruiterPostPayload {
  raw_text: string;
  url?: string;
  title?: string;
  company?: string;
  location?: string;
  work_model?: string;
  published_date?: string;
}

export interface PasteRecruiterBatchResponse {
  ok: boolean;
  imported: number;
  updated: number;
  skipped: number;
  invalid: number;
  posts: RecruiterPost[];
  auto_mode_woken?: boolean;
}

@Injectable({
  providedIn: 'root'
})
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly searchState = inject(SearchStateService);
  private readonly recruiterState = inject(RecruiterStateService);
  private readonly baseUrl = '/api';
  private persistedHydrated = false;

  // Estado de busca da sessão atual: inicia vazio e só popula quando o usuário clica em "Buscar vagas"
  readonly hasSearchedInSession = signal<boolean>(false);
  readonly sessionVagas = signal<Vaga[]>([]);
  readonly hasSearchedRecruitersInSession = computed(() => this.recruiterState.hasActiveKeywordSearch());
  readonly savedCount = signal<number>(0);
  readonly applicationsCount = signal<number>(0);
  readonly discardedCount = signal<number>(0);
  readonly recruiterPostsCount = computed(() =>
    this.recruiterState.hasActiveKeywordSearch() ? this.recruiterState.filteredPosts().length : 0
  );

  constructor() {
    this.refreshCounts();
  }

  refreshCounts(): void {
    this.getSaved().subscribe({
      next: (jobs) => this.savedCount.set(jobs.length),
      error: (err) => console.warn('Falha ao atualizar contagem de salvas:', err)
    });
    this.getApplications().subscribe({
      next: (apps) => this.applicationsCount.set(apps.length),
      error: (err) => console.warn('Falha ao atualizar contagem de candidaturas:', err)
    });
    this.getDiscarded().subscribe({
      next: (disc) => this.discardedCount.set(disc.length),
      error: (err) => console.warn('Falha ao atualizar contagem de descartadas:', err)
    });
  }

  getResults(): Observable<{ new: Vaga[]; total?: number; meta?: any }> {
    return this.http.get<{ new: Vaga[]; total?: number; meta?: any }>(`${this.baseUrl}/results`).pipe(
      tap(res => {
        if (this.hasSearchedInSession()) {
          const items = res.new || [];
          this.sessionVagas.set(items);
          this.searchState.allVagas.set(items);
        }
      })
    );
  }

  hydratePersistedSessions(): void {
    if (this.persistedHydrated) return;
    this.persistedHydrated = true;

    if (this.searchState.hasTodaySearch()) {
      this.hasSearchedInSession.set(true);
      if (this.searchState.allVagas().length > 0) {
        this.sessionVagas.set(this.searchState.allVagas());
      }
      this.getResults().subscribe({
        error: (err) => console.warn('Falha ao reidratar resultados salvos:', err),
      });
    }

    if (this.recruiterState.hasActiveKeywordSearch()) {
      this.getRecruiterPosts().subscribe({
        next: (res) => {
          this.recruiterState.allPosts.set(res.posts || []);
        },
        error: (err) => console.warn('Falha ao reidratar publicações de recrutadores:', err),
      });
    }
  }

  getSaved(): Observable<Vaga[]> {
    return this.http.get<{ saved?: Vaga[] }>(`${this.baseUrl}/saved`).pipe(
      map(res => (res && Array.isArray(res.saved) ? res.saved : []))
    );
  }

  getApplications(): Observable<ApplicationRecord[]> {
    return this.http.get<{ applications?: ApplicationRecord[] }>(`${this.baseUrl}/applications`).pipe(
      map(res => (res && Array.isArray(res.applications) ? res.applications : []))
    );
  }

  getDiscarded(): Observable<Vaga[]> {
    return this.http.get<{ discarded?: Vaga[] }>(`${this.baseUrl}/discarded`).pipe(
      map(res => (res && Array.isArray(res.discarded) ? res.discarded : []))
    );
  }

  getDashboardStats(periodMonths = 6): Observable<DashboardStats> {
    return this.http.get<DashboardStats>(`${this.baseUrl}/dashboard/stats?period_months=${periodMonths}`);
  }

  getEvolution(): Observable<EvolutionResponse> {
    return this.http.get<EvolutionResponse>(`${this.baseUrl}/evolucao`);
  }

  updateEvolution(): Observable<{ ok: boolean; evolution: EvolutionResponse }> {
    return this.http.post<{ ok: boolean; evolution: EvolutionResponse }>(`${this.baseUrl}/evolucao/atualizar`, {}).pipe(
      tap(() => this.refreshCounts())
    );
  }

  getProfile(refresh = false): Observable<ProfileResponse> {
    return this.http.get<ProfileResponse>(`${this.baseUrl}/profile${refresh ? '?refresh=1' : ''}`);
  }

  getSettings(): Observable<SettingsResponse> {
    return this.http.get<SettingsResponse>(`${this.baseUrl}/settings`);
  }

  saveSettings(payload: any): Observable<any> {
    return this.http.post(`${this.baseUrl}/settings`, payload);
  }

  getCvAreas(): Observable<{ areas: any[] }> {
    return this.http.get<{ areas: any[] }>(`${this.baseUrl}/cv-areas`);
  }

  getDocuments(): Observable<GeneratedDoc[]> {
    return this.http.get<{ documents?: GeneratedDoc[] }>(`${this.baseUrl}/documents`).pipe(
      map(res => (res && Array.isArray(res.documents) ? res.documents : []))
    );
  }

  getGeo(): Observable<any> {
    return this.http.get<any>(`${this.baseUrl}/geo`).pipe(
      catchError(() => this.http.get<any>('assets/geo_data.json'))
    );
  }

  uploadFile(kind: string, name: string, data: string): Observable<{ saved: string; files: any }> {
    return this.http.post<{ saved: string; files: any }>(`${this.baseUrl}/upload`, { kind, name, data });
  }

  removeUpload(kind: string, name: string): Observable<{ files: any }> {
    return this.http.post<{ files: any }>(`${this.baseUrl}/upload-remove`, { kind, name });
  }

  saveProfileAnswers(answers: Record<string, any>): Observable<{ answers: any }> {
    return this.http.post<{ answers: any }>(`${this.baseUrl}/profile`, answers);
  }

  triggerClaude(payload: { step: string; url?: string; confirm?: boolean }): Observable<any> {
    return this.http.post(`${this.baseUrl}/claude`, payload);
  }

  startBatchScreen(urls: string[]): Observable<any> {
    return this.http.post(`${this.baseUrl}/batch-screen`, { urls });
  }

  startBatchReevaluate(urls: string[]): Observable<{ ok: boolean; started: boolean; total: number }> {
    return this.http.post<{ ok: boolean; started: boolean; total: number }>(
      `${this.baseUrl}/saved/batch-reevaluate`,
      { urls }
    );
  }

  getSavedBatchStatus(): Observable<any> {
    return this.http.get<any>(`${this.baseUrl}/saved/batch-status`);
  }

  clearPending(): Observable<{ cleared?: number }> {
    return this.http.post<{ cleared?: number }>(`${this.baseUrl}/clear-pending`, {}).pipe(
      tap(() => {
        this.sessionVagas.set([]);
        this.hasSearchedInSession.set(false);
        this.searchState.clearSearchSession();
      })
    );
  }

  markDecision(urls: string[], decision: 'interesse' | 'descartar', jobData?: any): Observable<any> {
    return this.http.post(`${this.baseUrl}/mark`, { urls, decision, job_data: jobData }).pipe(
      tap(() => this.refreshCounts())
    );
  }

  markApplied(payload: {
    url: string;
    company?: string;
    role?: string;
    portal?: string;
    contact_channel?: string;
    contacted_email?: string;
  }): Observable<any> {
    return this.http.post(`${this.baseUrl}/applied`, payload).pipe(
      tap(() => this.refreshCounts())
    );
  }

  markAppliedBatch(items: Array<{
    url: string;
    company?: string;
    role?: string;
    portal?: string;
    contact_channel?: string;
    contacted_email?: string;
  }>): Observable<{ ok: boolean; applied: number }> {
    return this.http.post<{ ok: boolean; applied: number }>(
      `${this.baseUrl}/applied/batch`,
      { items }
    ).pipe(
      tap(() => this.refreshCounts())
    );
  }

  removeApplication(payload: { url?: string; id?: number; job_id?: string }): Observable<any> {
    return this.http.post(`${this.baseUrl}/applications/remove`, payload).pipe(
      tap(() => this.refreshCounts())
    );
  }

  reopenRecruiterApplication(payload: {
    id?: number;
    job_id?: string;
    url?: string;
    recruiter_post_id?: number;
  }): Observable<{ ok: boolean; reopened: boolean; post_id?: number; job_id?: string; url?: string }> {
    return this.http.post<{ ok: boolean; reopened: boolean; post_id?: number; job_id?: string; url?: string }>(
      `${this.baseUrl}/applications/reopen-recruiter`,
      payload
    ).pipe(
      tap(() => this.refreshCounts())
    );
  }

  getApplicationEvents(appId: number): Observable<{ events: ApplicationTimelineEvent[]; total: number }> {
    return this.http.get<{ events: ApplicationTimelineEvent[]; total: number }>(`${this.baseUrl}/applications/${appId}/events`);
  }

  addApplicationEvent(payload: {
    application_id?: number;
    job_id?: string;
    url?: string;
    stage: string;
    event_date?: string;
    feedback?: string;
    questions_and_answers?: string;
    status?: string;
  }): Observable<{ ok: boolean; event_id: number }> {
    return this.http.post<{ ok: boolean; event_id: number }>(`${this.baseUrl}/applications/event`, payload).pipe(
      tap(() => this.refreshCounts())
    );
  }

  deleteApplicationEvent(eventId: number): Observable<{ ok: boolean; deleted: boolean }> {
    return this.http.delete<{ ok: boolean; deleted: boolean }>(`${this.baseUrl}/applications/event/${eventId}`).pipe(
      tap(() => this.refreshCounts())
    );
  }

  discardJob(url: string): Observable<any> {
    return this.http.post(`${this.baseUrl}/discard`, { url }).pipe(
      tap(() => this.refreshCounts())
    );
  }

  discardJobsBatch(urls: string[]): Observable<{ ok: boolean; discarded: number; total: number }> {
    return this.http.post<{ ok: boolean; discarded: number; total: number }>(
      `${this.baseUrl}/saved/batch-discard`,
      { urls }
    ).pipe(
      tap(() => this.refreshCounts())
    );
  }

  restoreJob(url: string): Observable<any> {
    return this.http.post(`${this.baseUrl}/restore`, { url }).pipe(
      tap(() => this.refreshCounts())
    );
  }

  clearDiscarded(): Observable<{ ok: boolean; deleted_db?: number; cleared_seen?: number }> {
    return this.http.post<{ ok: boolean; deleted_db?: number; cleared_seen?: number }>(`${this.baseUrl}/discarded/clear`, {}).pipe(
      tap(() => this.refreshCounts())
    );
  }

  deleteDocument(path: string): Observable<any> {
    return this.http.post(`${this.baseUrl}/documents/delete?path=${encodeURIComponent(path)}`, {});
  }

  clearDocuments(keepCv = true): Observable<any> {
    return this.http.post(`${this.baseUrl}/documents/clear?keep_cv=${keepCv}`, {});
  }

  startSearch(payload: { priority?: number[]; jobage?: number; all?: boolean; focus?: string; portals?: string[]; region?: string; query?: string }): Observable<any> {
    this.hasSearchedInSession.set(true);
    return this.http.post(`${this.baseUrl}/search`, payload);
  }

  getSearchStatus(): Observable<any> {
    return this.http.get(`${this.baseUrl}/status`);
  }

  getRecruiterPosts(query?: string, onlyCv = false, portal?: string, includeNonJobs = true): Observable<{ total: number; posts: RecruiterPost[] }> {
    const params: string[] = [];
    if (query && query.trim()) params.push(`q=${encodeURIComponent(query.trim())}`);
    if (onlyCv) params.push('only_cv=true');
    if (portal && portal.trim()) params.push(`portal=${encodeURIComponent(portal.trim())}`);
    if (!includeNonJobs) params.push('include_non_jobs=false');
    const qs = params.length > 0 ? `?${params.join('&')}` : '';
    return this.http.get<{ total: number; posts: RecruiterPost[] }>(`${this.baseUrl}/recruiters${qs}`);
  }

  getRecruiterAutoConfig(): Observable<{ config: any }> {
    return this.http.get<{ config: any }>(`${this.baseUrl}/recruiters/auto/config`);
  }

  saveRecruiterAutoConfig(payload: {
    min_score?: number;
    continuous?: boolean;
    cooldown_seconds?: number;
  }): Observable<{ ok: boolean; config: any }> {
    return this.http.post<{ ok: boolean; config: any }>(`${this.baseUrl}/recruiters/auto/config`, payload);
  }

  startRecruiterAutoMode(payload: {
    min_score?: number;
    continuous?: boolean;
    cooldown_seconds?: number;
  }): Observable<any> {
    return this.http.post(`${this.baseUrl}/recruiters/auto/start`, payload);
  }

  syncRecruiterPosts(query?: string, opts?: { includeLinkedin?: boolean; forceLinkedin?: boolean; days?: number | null }): Observable<SyncRecruiterPostsResponse> {
    const params = new URLSearchParams();
    if (query && query.trim()) params.set('q', query.trim());
    if (opts?.includeLinkedin === false) params.set('include_linkedin', 'false');
    if (opts?.forceLinkedin) params.set('force_linkedin', 'true');
    if (opts?.days && opts.days > 0) params.set('days', String(opts.days));
    const qs = params.toString() ? `?${params.toString()}` : '';
    return this.http.post<SyncRecruiterPostsResponse>(
      `${this.baseUrl}/recruiters/sync${qs}`,
      {}
    ).pipe(
      tap(() => this.refreshCounts())
    );
  }

  triageRecruiterPosts(payload: {
    post_ids?: number[];
    q?: string;
    portal?: string;
    limit?: number;
  }): Observable<RecruiterTriageResponse> {
    return this.http.post<RecruiterTriageResponse>(
      `${this.baseUrl}/recruiters/triage`,
      payload
    ).pipe(
      tap(() => this.refreshCounts())
    );
  }

  getLinkedInWorkerStatus(): Observable<LinkedInWorkerStatus> {
    return this.http.get<LinkedInWorkerStatus>(`${this.baseUrl}/recruiters/linkedin/status`);
  }

  connectLinkedInWorker(): Observable<LinkedInWorkerStatus> {
    return this.http.post<LinkedInWorkerStatus>(`${this.baseUrl}/recruiters/linkedin/connect`, {});
  }

  verifyLinkedInWorker(): Observable<LinkedInWorkerStatus> {
    return this.http.post<LinkedInWorkerStatus>(`${this.baseUrl}/recruiters/linkedin/verify`, {});
  }

  updateLinkedInWorkerConfig(payload: {
    enabled?: boolean;
    headless?: boolean;
    cooldown_minutes?: number;
    max_daily_searches?: number;
    max_scrolls?: number;
  }): Observable<LinkedInWorkerStatus> {
    return this.http.post<LinkedInWorkerStatus>(`${this.baseUrl}/recruiters/linkedin/config`, payload);
  }

  disconnectLinkedInWorker(): Observable<LinkedInWorkerStatus> {
    return this.http.post<LinkedInWorkerStatus>(`${this.baseUrl}/recruiters/linkedin/disconnect`, {});
  }

  pasteRecruiterPost(payload: PasteRecruiterPostPayload): Observable<{ ok: boolean; post: RecruiterPost; auto_mode_woken?: boolean }> {
    return this.http.post<{ ok: boolean; post: RecruiterPost; auto_mode_woken?: boolean }>(
      `${this.baseUrl}/recruiters/paste`,
      payload
    ).pipe(
      tap(() => this.refreshCounts())
    );
  }

  pasteRecruiterPostsBatch(payload: {
    items?: PasteRecruiterPostPayload[];
    raw_batch_text?: string;
  }): Observable<PasteRecruiterBatchResponse> {
    return this.http.post<PasteRecruiterBatchResponse>(
      `${this.baseUrl}/recruiters/paste-batch`,
      payload
    ).pipe(
      tap(() => this.refreshCounts())
    );
  }

  markRecruiterPostInterested(postId: number): Observable<{ ok: boolean; post_id: number; job_id: string; url: string }> {
    return this.http.post<{ ok: boolean; post_id: number; job_id: string; url: string }>(
      `${this.baseUrl}/recruiters/${postId}/interested`,
      {}
    ).pipe(
      tap(() => this.refreshCounts())
    );
  }

  markRecruiterPostContacted(
    postId: number,
    payload: { email?: string; notes?: string } = {}
  ): Observable<{
    ok: boolean;
    post_id: number;
    job_id: string;
    application_id: number;
    url: string;
    contacted_email: string;
    contacted_at: string;
  }> {
    return this.http.post<{
      ok: boolean;
      post_id: number;
      job_id: string;
      application_id: number;
      url: string;
      contacted_email: string;
      contacted_at: string;
    }>(
      `${this.baseUrl}/recruiters/${postId}/contacted`,
      payload
    ).pipe(
      tap(() => this.refreshCounts())
    );
  }

  dismissRecruiterPost(postId: number): Observable<{ ok: boolean; id: number }> {
    return this.http.delete<{ ok: boolean; id: number }>(
      `${this.baseUrl}/recruiters/${postId}`
    ).pipe(
      tap(() => this.refreshCounts())
    );
  }

  getAutoModeStatus(): Observable<any> {
    return this.http.get(`${this.baseUrl}/auto-mode/status`);
  }

  getAutoModeConfig(): Observable<{ config: any }> {
    return this.http.get<{ config: any }>(`${this.baseUrl}/auto-mode/config`);
  }

  saveAutoModeConfig(payload: {
    region?: string;
    portals?: string[] | null;
    jobage?: number;
    min_score?: number;
    hide_undated?: boolean;
    continuous?: boolean;
    cooldown_seconds?: number;
  }): Observable<{ ok: boolean; config: any }> {
    return this.http.post<{ ok: boolean; config: any }>(`${this.baseUrl}/auto-mode/config`, payload);
  }

  startAutoMode(payload: {
    region?: string;
    portals?: string[] | null;
    jobage?: number;
    min_score?: number;
    hide_undated?: boolean;
    continuous?: boolean;
    cooldown_seconds?: number;
  }): Observable<any> {
    this.hasSearchedInSession.set(true);
    return this.http.post(`${this.baseUrl}/auto-mode/start`, payload);
  }

  cancelAutoMode(): Observable<any> {
    return this.http.post(`${this.baseUrl}/auto-mode/cancel`, {});
  }

  skipAutoModeCooldown(): Observable<{ ok: boolean; skipped: boolean }> {
    return this.http.post<{ ok: boolean; skipped: boolean }>(`${this.baseUrl}/auto-mode/skip-cooldown`, {});
  }

  undoAutoModeRun(runId?: string): Observable<{ ok: boolean; run_id?: string; reverted: number; error?: string }> {
    return this.http.post<{ ok: boolean; run_id?: string; reverted: number; error?: string }>(
      `${this.baseUrl}/auto-mode/undo`,
      runId ? { run_id: runId } : {}
    ).pipe(
      tap(() => this.refreshCounts())
    );
  }

  undoAutoModeJob(payload: { url?: string; job_id?: string }): Observable<{ ok: boolean; reverted: number; error?: string }> {
    return this.http.post<{ ok: boolean; reverted: number; error?: string }>(
      `${this.baseUrl}/auto-mode/undo-job`,
      payload
    ).pipe(
      tap(() => this.refreshCounts())
    );
  }
}
