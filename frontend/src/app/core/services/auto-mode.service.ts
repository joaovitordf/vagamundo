import { Injectable, OnDestroy, computed, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';
import { ApiService } from './api.service';
import { ToastService } from './toast.service';

export type AutoModePhase =
  | 'idle'
  | 'picking_keywords'
  | 'searching'
  | 'screening'
  | 'cooldown'
  | 'done'
  | 'cancelled'
  | 'error';

export interface AutoModeRoundSummary {
  round: number;
  keywords: string[];
  found: number;
  eligible: number;
  promoted: number;
  discarded: number;
  errors: number;
  rate_limited?: boolean;
  error?: string;
  finished_at?: string;
}

export interface AutoModeCounts {
  found: number;
  to_screen: number;
  screened: number;
  promoted: number;
  discarded: number;
  talent_pools_discarded?: number;
  not_a_job?: number;
  kept_low_score?: number;
  pending: number;
  errors: number;
}

export interface AutoModeStatus {
  running: boolean;
  mode?: 'jobs' | 'recruiters';
  phase: AutoModePhase;
  run_id: string | null;
  continuous?: boolean;
  cooldown_seconds?: number;
  cooldown_remaining_s?: number;
  next_run_at?: string | null;
  backoff_reason?: string | null;
  round?: number;
  round_jobs_found?: number;
  round_eligible_count?: number;
  round_screened?: number;
  round_promoted?: number;
  round_discarded?: number;
  round_errors?: number;
  round_history?: AutoModeRoundSummary[];
  keywords: string[];
  rationale: string;
  keyword_source: string;
  jobage: number;
  min_score: number;
  region: string;
  hide_undated: boolean;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  undone: boolean;
  counts: AutoModeCounts;
  promoted_items: any[];
  search_progress?: any;
  batch_progress?: any;
}

@Injectable({ providedIn: 'root' })
export class AutoModeService implements OnDestroy {
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastService);

  status = signal<AutoModeStatus | null>(null);
  bannerDismissed = signal<boolean>(false);
  undoing = signal<boolean>(false);
  cancelling = signal<boolean>(false);
  skippingCooldown = signal<boolean>(false);
  cooldownRemainingSeconds = signal<number>(0);
  resultsRefreshTick = signal<number>(0);

  private pollTimer: any = null;
  private countdownTimer: any = null;
  private pollInFlight = false;
  private consecutivePollErrors = 0;
  private initialized = false;

  isRunning = computed(() => {
    const st = this.status();
    if (!st) return false;
    return (
      Boolean(st.running) ||
      st.phase === 'picking_keywords' ||
      st.phase === 'searching' ||
      st.phase === 'screening' ||
      st.phase === 'cooldown'
    );
  });
  phase = computed(() => this.status()?.phase || 'idle');

  cooldownCountdownLabel = computed(() => {
    const sec = Math.max(0, Math.round(this.cooldownRemainingSeconds()));
    const mm = String(Math.floor(sec / 60)).padStart(2, '0');
    const ss = String(sec % 60).padStart(2, '0');
    return `${mm}:${ss}`;
  });

  showBanner = computed(() => {
    const st = this.status();
    if (!st) return false;
    if (this.isRunning()) return true;
    if (this.bannerDismissed()) return false;
    return st.phase === 'done' || st.phase === 'cancelled' || st.phase === 'error';
  });

  ngOnDestroy(): void {
    this.stopPolling();
    this.stopCountdownTimer();
  }

  init(): void {
    if (this.initialized) return;
    this.initialized = true;
    this.fetchStatusOnce();
  }

  fetchStatusOnce(): void {
    this.api.getAutoModeStatus().subscribe({
      next: (st: AutoModeStatus) => {
        this.applyStatusUpdate(st);
        if (st?.running) {
          this.ensurePolling();
        }
      },
      error: (err) => console.warn('Falha ao consultar status do Modo Automático:', err),
    });
  }

  start(payload: {
    region?: string;
    portals?: string[] | null;
    jobage?: number;
    min_score?: number;
    hide_undated?: boolean;
    continuous?: boolean;
    cooldown_seconds?: number;
  }): Observable<any> {
    this.bannerDismissed.set(false);
    this.cancelling.set(false);
    this.skippingCooldown.set(false);
    return this.api.startAutoMode(payload).pipe(
      tap(() => {
        this.fetchStatusOnce();
        this.ensurePolling();
      })
    );
  }

  startRecruiters(payload: {
    min_score?: number;
    continuous?: boolean;
    cooldown_seconds?: number;
  }): Observable<any> {
    this.bannerDismissed.set(false);
    this.cancelling.set(false);
    this.skippingCooldown.set(false);
    return this.api.startRecruiterAutoMode(payload).pipe(
      tap(() => {
        this.fetchStatusOnce();
        this.ensurePolling();
      })
    );
  }

  cancel(): void {
    this.cancelling.set(true);
    this.api.cancelAutoMode().subscribe({
      next: () => this.fetchStatusOnce(),
      error: (err) => {
        this.cancelling.set(false);
        this.toast.error('Erro ao parar Modo Automático: ' + (err?.error?.detail || err?.message || 'Falha na requisição'));
      },
    });
  }

  skipCooldown(): void {
    this.skippingCooldown.set(true);
    this.api.skipAutoModeCooldown().subscribe({
      next: () => this.fetchStatusOnce(),
      error: (err) => {
        this.skippingCooldown.set(false);
        this.toast.error('Erro ao pular intervalo: ' + (err?.error?.detail || err?.message || 'Falha na requisição'));
      },
    });
  }

  undoRun(runId?: string): Observable<{ ok: boolean; run_id?: string; reverted: number; error?: string }> {
    this.undoing.set(true);
    return this.api.undoAutoModeRun(runId).pipe(
      tap({
        next: () => {
          this.undoing.set(false);
          const cur = this.status();
          if (cur) {
            this.status.set({ ...cur, undone: true });
          }
          this.resultsRefreshTick.update(v => v + 1);
        },
        error: () => this.undoing.set(false),
      })
    );
  }

  undoSingleJob(payload: { url?: string; job_id?: string }): Observable<{ ok: boolean; reverted: number; error?: string }> {
    return this.api.undoAutoModeJob(payload).pipe(
      tap(() => {
        this.resultsRefreshTick.update(v => v + 1);
      })
    );
  }

  dismissBanner(): void {
    if (this.isRunning()) return;
    this.bannerDismissed.set(true);
  }

  private ensurePolling(): void {
    if (this.pollTimer) return;
    this.consecutivePollErrors = 0;
    this.pollTimer = setInterval(() => {
      if (this.pollInFlight) return;
      this.pollInFlight = true;
      this.api.getAutoModeStatus().subscribe({
        next: (st: AutoModeStatus) => {
          this.pollInFlight = false;
          this.consecutivePollErrors = 0;
          this.applyStatusUpdate(st);
          if (!st?.running) {
            this.stopPolling();
            this.cancelling.set(false);
            this.skippingCooldown.set(false);
            this.api.refreshCounts();
            this.resultsRefreshTick.update(v => v + 1);
          }
        },
        error: () => {
          this.pollInFlight = false;
          this.consecutivePollErrors += 1;
          if (this.consecutivePollErrors >= 6) {
            this.stopPolling();
            this.stopCountdownTimer();
            this.cancelling.set(false);
            this.skippingCooldown.set(false);
            const cur = this.status();
            if (cur && this.isRunning()) {
              this.status.set({
                ...cur,
                running: false,
                phase: 'error',
                error: 'Conexão com o servidor perdida (backend inacessível ou reiniciado).',
              });
            }
            this.toast.error('Conexão com o servidor perdida no Modo Automático.');
          }
        },
      });
    }, 2000);
  }

  private stopPolling(): void {
    this.pollInFlight = false;
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  private updateRemainingFromStatus(st: AutoModeStatus): void {
    if (st.next_run_at) {
      const targetMs = Date.parse(st.next_run_at);
      if (!Number.isNaN(targetMs)) {
        const rem = Math.max(0, Math.ceil((targetMs - Date.now()) / 1000));
        this.cooldownRemainingSeconds.set(rem);
        return;
      }
    }
    this.cooldownRemainingSeconds.set(Math.max(0, Math.round(st.cooldown_remaining_s ?? 0)));
  }

  private syncCountdownTimer(st: AutoModeStatus): void {
    if (st.phase !== 'cooldown' || !st.running) {
      this.stopCountdownTimer();
      this.cooldownRemainingSeconds.set(0);
      this.skippingCooldown.set(false);
      return;
    }

    this.updateRemainingFromStatus(st);
    if (!this.countdownTimer) {
      this.countdownTimer = setInterval(() => {
        const cur = this.status();
        if (!cur || cur.phase !== 'cooldown' || !cur.running) {
          this.stopCountdownTimer();
          this.cooldownRemainingSeconds.set(0);
          return;
        }
        this.updateRemainingFromStatus(cur);
        if (this.cooldownRemainingSeconds() <= 0 && !this.pollTimer) {
          this.ensurePolling();
        }
      }, 1000);
    }
  }

  private stopCountdownTimer(): void {
    if (this.countdownTimer) {
      clearInterval(this.countdownTimer);
      this.countdownTimer = null;
    }
  }

  applyStatusUpdate(next: AutoModeStatus): void {
    const prev = this.status();
    const prevChanged =
      (prev?.counts?.promoted ?? 0) !== (next?.counts?.promoted ?? 0) ||
      (prev?.counts?.discarded ?? 0) !== (next?.counts?.discarded ?? 0) ||
      (prev?.counts?.not_a_job ?? 0) !== (next?.counts?.not_a_job ?? 0) ||
      (prev?.counts?.kept_low_score ?? 0) !== (next?.counts?.kept_low_score ?? 0) ||
      (prev?.round ?? 0) !== (next?.round ?? 0) ||
      prev?.phase !== next?.phase;

    if (next?.running) {
      this.bannerDismissed.set(false);
    }
    this.status.set(next);
    this.syncCountdownTimer(next);

    if (prevChanged && prev) {
      this.api.refreshCounts();
      this.resultsRefreshTick.update(v => v + 1);
    }
  }
}
