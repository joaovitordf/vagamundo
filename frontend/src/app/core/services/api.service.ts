import { Injectable, computed, inject, signal } from '@angular/core';
import { HttpClient, HttpHeaders, HttpErrorResponse } from '@angular/common/http';
import { Observable, of, throwError } from 'rxjs';
import { map, catchError, switchMap, tap } from 'rxjs/operators';
import { Vaga, ProfileResponse, SettingsResponse, EvolutionResponse, ApplicationTimelineEvent, DashboardStats, RecruiterPost } from '../models/vaga.model';
import { SearchStateService } from './search-state.service';
import { RecruiterStateService } from './recruiter-state.service';

@Injectable({
  providedIn: 'root'
})
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly searchState = inject(SearchStateService);
  private readonly recruiterState = inject(RecruiterStateService);
  private readonly baseUrl = '/api';
  private token = '';
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
    this.initToken();
    this.refreshCounts();
  }

  refreshCounts(): void {
    this.getSaved().subscribe({
      next: (jobs) => this.savedCount.set(jobs.length),
      error: () => {}
    });
    this.getApplications().subscribe({
      next: (apps) => this.applicationsCount.set(apps.length),
      error: () => {}
    });
    this.getDiscarded().subscribe({
      next: (disc) => this.discardedCount.set(disc.length),
      error: () => {}
    });
  }

  private initToken(): void {
    const meta = document.querySelector('meta[name="painel-token"]') as HTMLMetaElement | null;
    if (meta && meta.content && meta.content !== '__PAINEL_TOKEN__') {
      this.token = meta.content;
    } else {
      this.fetchToken().subscribe();
    }
  }

  private fetchToken(): Observable<string> {
    return this.http.get<{ token: string }>(`${this.baseUrl}/token`).pipe(
      map(res => {
        if (res && res.token) {
          this.token = res.token;
        }
        return this.token;
      }),
      catchError(() => of(''))
    );
  }

  private getHeaders(): HttpHeaders {
    let headers = new HttpHeaders({ 'Content-Type': 'application/json' });
    if (this.token) {
      headers = headers.set('X-Painel-Token', this.token);
    }
    return headers;
  }

  private postWithToken<T>(endpoint: string, body: any): Observable<T> {
    const executePost = () => this.http.post<T>(endpoint, body, { headers: this.getHeaders() });

    const initial$ = this.token
      ? executePost()
      : this.fetchToken().pipe(switchMap(() => executePost()));

    return initial$.pipe(
      catchError((err: HttpErrorResponse) => {
        if (err.status === 403) {
          // Se o backend reiniciou e trocou o token, busca o token atualizado e tenta mais uma vez
          return this.fetchToken().pipe(
            switchMap(newToken => {
              if (!newToken) return throwError(() => err);
              return executePost();
            })
          );
        }
        return throwError(() => err);
      })
    );
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
        error: () => {},
      });
    }

    if (this.recruiterState.hasActiveKeywordSearch()) {
      this.getRecruiterPosts().subscribe({
        next: (res) => {
          this.recruiterState.allPosts.set(res.posts || []);
        },
        error: () => {},
      });
    }
  }

  getSaved(): Observable<any[]> {
    return this.http.get<any>(`${this.baseUrl}/saved`).pipe(
      map(res => (res && Array.isArray(res.saved) ? res.saved : []))
    );
  }

  getApplications(): Observable<any[]> {
    return this.http.get<any>(`${this.baseUrl}/applications`).pipe(
      map(res => (res && Array.isArray(res.applications) ? res.applications : []))
    );
  }

  getDiscarded(): Observable<any[]> {
    return this.http.get<any>(`${this.baseUrl}/discarded`).pipe(
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
    return this.postWithToken<{ ok: boolean; evolution: EvolutionResponse }>(`${this.baseUrl}/evolucao/atualizar`, {}).pipe(
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
    return this.postWithToken(`${this.baseUrl}/settings`, payload);
  }

  getCvAreas(): Observable<{ areas: any[] }> {
    return this.http.get<{ areas: any[] }>(`${this.baseUrl}/cv-areas`);
  }

  getDocuments(): Observable<any[]> {
    return this.http.get<any>(`${this.baseUrl}/documents`).pipe(
      map(res => (res && Array.isArray(res.documents) ? res.documents : []))
    );
  }

  getGeo(): Observable<any> {
    return this.http.get<any>(`${this.baseUrl}/geo`).pipe(
      catchError(() => this.http.get<any>('assets/geo_data.json'))
    );
  }

  uploadFile(kind: string, name: string, data: string): Observable<{ saved: string; files: any }> {
    return this.postWithToken<{ saved: string; files: any }>(`${this.baseUrl}/upload`, { kind, name, data });
  }

  removeUpload(kind: string, name: string): Observable<{ files: any }> {
    return this.postWithToken<{ files: any }>(`${this.baseUrl}/upload-remove`, { kind, name });
  }

  saveProfileAnswers(answers: Record<string, any>): Observable<{ answers: any }> {
    return this.postWithToken<{ answers: any }>(`${this.baseUrl}/profile`, answers);
  }

  triggerClaude(payload: { step: string; url?: string; confirm?: boolean }): Observable<any> {
    return this.postWithToken(`${this.baseUrl}/claude`, payload);
  }

  startBatchScreen(urls: string[]): Observable<any> {
    return this.postWithToken(`${this.baseUrl}/batch-screen`, { urls });
  }

  clearPending(): Observable<{ cleared?: number }> {
    return this.postWithToken<{ cleared?: number }>(`${this.baseUrl}/clear-pending`, {}).pipe(
      tap(() => {
        this.sessionVagas.set([]);
        this.hasSearchedInSession.set(false);
        this.searchState.clearSearchSession();
      })
    );
  }

  markDecision(urls: string[], decision: 'interesse' | 'descartar', jobData?: any): Observable<any> {
    return this.postWithToken(`${this.baseUrl}/mark`, { urls, decision, job_data: jobData }).pipe(
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
    return this.postWithToken(`${this.baseUrl}/applied`, payload).pipe(
      tap(() => this.refreshCounts())
    );
  }

  removeApplication(payload: { url?: string; id?: number; job_id?: string }): Observable<any> {
    return this.postWithToken(`${this.baseUrl}/applications/remove`, payload).pipe(
      tap(() => this.refreshCounts())
    );
  }

  reopenRecruiterApplication(payload: {
    id?: number;
    job_id?: string;
    url?: string;
    recruiter_post_id?: number;
  }): Observable<{ ok: boolean; reopened: boolean; post_id?: number; job_id?: string; url?: string }> {
    return this.postWithToken<{ ok: boolean; reopened: boolean; post_id?: number; job_id?: string; url?: string }>(
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
    return this.postWithToken<{ ok: boolean; event_id: number }>(`${this.baseUrl}/applications/event`, payload).pipe(
      tap(() => this.refreshCounts())
    );
  }

  deleteApplicationEvent(eventId: number): Observable<{ ok: boolean; deleted: boolean }> {
    return this.postWithToken<{ ok: boolean; deleted: boolean }>(`${this.baseUrl}/applications/event/${eventId}`, {}).pipe(
      tap(() => this.refreshCounts())
    );
  }

  discardJob(url: string): Observable<any> {
    return this.postWithToken(`${this.baseUrl}/discard`, { url }).pipe(
      tap(() => this.refreshCounts())
    );
  }

  restoreJob(url: string): Observable<any> {
    return this.postWithToken(`${this.baseUrl}/restore`, { url }).pipe(
      tap(() => this.refreshCounts())
    );
  }

  clearDiscarded(): Observable<{ ok: boolean; deleted_db?: number; cleared_seen?: number }> {
    return this.postWithToken<{ ok: boolean; deleted_db?: number; cleared_seen?: number }>(`${this.baseUrl}/discarded/clear`, {}).pipe(
      tap(() => this.refreshCounts())
    );
  }

  deleteDocument(path: string): Observable<any> {
    return this.postWithToken(`${this.baseUrl}/documents/delete?path=${encodeURIComponent(path)}`, {});
  }

  clearDocuments(keepCv = true): Observable<any> {
    return this.postWithToken(`${this.baseUrl}/documents/clear?keep_cv=${keepCv}`, {});
  }

  startSearch(payload: { priority?: number[]; jobage?: number; all?: boolean; focus?: string; portals?: string[]; region?: string; query?: string }): Observable<any> {
    this.hasSearchedInSession.set(true);
    return this.postWithToken(`${this.baseUrl}/search`, payload);
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
    return this.postWithToken<{ ok: boolean; config: any }>(`${this.baseUrl}/recruiters/auto/config`, payload);
  }

  startRecruiterAutoMode(payload: {
    min_score?: number;
    continuous?: boolean;
    cooldown_seconds?: number;
  }): Observable<any> {
    return this.postWithToken(`${this.baseUrl}/recruiters/auto/start`, payload);
  }

  syncRecruiterPosts(query?: string): Observable<{ ok: boolean; scanned: number; posts_with_email: number; synced: number; hn_synced?: number }> {
    const qs = query && query.trim() ? `?q=${encodeURIComponent(query.trim())}` : '';
    return this.postWithToken<{ ok: boolean; scanned: number; posts_with_email: number; synced: number; hn_synced?: number }>(
      `${this.baseUrl}/recruiters/sync${qs}`,
      {}
    ).pipe(
      tap(() => this.refreshCounts())
    );
  }

  pasteRecruiterPost(payload: {
    raw_text: string;
    url?: string;
    title?: string;
    company?: string;
    location?: string;
    work_model?: string;
  }): Observable<{ ok: boolean; post: RecruiterPost }> {
    return this.postWithToken<{ ok: boolean; post: RecruiterPost }>(
      `${this.baseUrl}/recruiters/paste`,
      payload
    ).pipe(
      tap(() => this.refreshCounts())
    );
  }

  markRecruiterPostInterested(postId: number): Observable<{ ok: boolean; post_id: number; job_id: string; url: string }> {
    return this.postWithToken<{ ok: boolean; post_id: number; job_id: string; url: string }>(
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
    return this.postWithToken<{
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
    return this.deleteWithToken<{ ok: boolean; id: number }>(
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
    return this.postWithToken<{ ok: boolean; config: any }>(`${this.baseUrl}/auto-mode/config`, payload);
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
    return this.postWithToken(`${this.baseUrl}/auto-mode/start`, payload);
  }

  cancelAutoMode(): Observable<any> {
    return this.postWithToken(`${this.baseUrl}/auto-mode/cancel`, {});
  }

  skipAutoModeCooldown(): Observable<{ ok: boolean; skipped: boolean }> {
    return this.postWithToken<{ ok: boolean; skipped: boolean }>(`${this.baseUrl}/auto-mode/skip-cooldown`, {});
  }

  undoAutoModeRun(runId?: string): Observable<{ ok: boolean; run_id?: string; reverted: number; error?: string }> {
    return this.postWithToken<{ ok: boolean; run_id?: string; reverted: number; error?: string }>(
      `${this.baseUrl}/auto-mode/undo`,
      runId ? { run_id: runId } : {}
    ).pipe(
      tap(() => this.refreshCounts())
    );
  }

  undoAutoModeJob(payload: { url?: string; job_id?: string }): Observable<{ ok: boolean; reverted: number; error?: string }> {
    return this.postWithToken<{ ok: boolean; reverted: number; error?: string }>(
      `${this.baseUrl}/auto-mode/undo-job`,
      payload
    ).pipe(
      tap(() => this.refreshCounts())
    );
  }

  private deleteWithToken<T>(url: string): Observable<T> {
    const doDelete = (token: string) =>
      this.http.delete<T>(url, {
        headers: new HttpHeaders({ 'X-Painel-Token': token }),
      });

    if (this.token) {
      return doDelete(this.token).pipe(
        catchError((err: HttpErrorResponse) => {
          if (err.status === 403) {
            return this.fetchToken().pipe(switchMap((newToken) => doDelete(newToken)));
          }
          return throwError(() => err);
        })
      );
    }
    return this.fetchToken().pipe(switchMap((token) => doDelete(token)));
  }
}
