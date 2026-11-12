import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { AutoModeService, AutoModeStatus } from './auto-mode.service';

function makeStatus(overrides: Partial<AutoModeStatus> = {}): AutoModeStatus {
  return {
    running: true,
    mode: 'recruiters',
    phase: 'picking_keywords',
    run_id: 'run123',
    continuous: true,
    cooldown_seconds: 30,
    cooldown_remaining_s: 0,
    next_run_at: null,
    backoff_reason: null,
    round: 1,
    keywords: ['Python', 'Backend'],
    rationale: 'Teste',
    keyword_source: 'ai',
    jobage: 7,
    min_score: 60,
    region: 'all',
    hide_undated: false,
    started_at: '2026-11-12T00:00:00+00:00',
    finished_at: null,
    error: null,
    undone: false,
    counts: {
      found: 0,
      to_screen: 0,
      screened: 0,
      promoted: 0,
      discarded: 0,
      pending: 0,
      errors: 0,
    },
    promoted_items: [],
    ...overrides,
  };
}

describe('AutoModeService continuous cooldown behavior', () => {
  let service: AutoModeService;
  let httpMock: HttpTestingController;

  function drainApiInitCalls(): void {
    for (const req of httpMock.match(() => true)) {
      if (req.request.url === '/api/token') req.flush({ token: 'tok' });
      else if (req.request.url === '/api/saved') req.flush({ saved: [] });
      else if (req.request.url === '/api/applications') req.flush({ applications: [] });
      else if (req.request.url === '/api/discarded') req.flush({ discarded: [] });
    }
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(AutoModeService);
    httpMock = TestBed.inject(HttpTestingController);
    drainApiInitCalls();
  });

  afterEach(() => {
    service.ngOnDestroy();
    for (const req of httpMock.match(() => true)) {
      req.flush({});
    }
    httpMock.verify();
  });

  it('tracks cooldown phase as running, formats countdown, and increments resultsRefreshTick between rounds', () => {
    const round1 = makeStatus({ phase: 'screening', round: 1 });
    service.applyStatusUpdate(round1);
    const initialTick = service.resultsRefreshTick();

    const futureIso = new Date(Date.now() + 65_000).toISOString();
    service.applyStatusUpdate(
      makeStatus({
        phase: 'cooldown',
        round: 1,
        cooldown_seconds: 65,
        cooldown_remaining_s: 65,
        next_run_at: futureIso,
      })
    );
    drainApiInitCalls();

    expect(service.isRunning()).toBeTrue();
    expect(service.showBanner()).toBeTrue();
    expect(service.resultsRefreshTick()).toBeGreaterThan(initialTick);
    expect(service.cooldownCountdownLabel()).toMatch(/^01:0[45]$/);

    const tickAfterCooldown = service.resultsRefreshTick();
    service.applyStatusUpdate(
      makeStatus({
        phase: 'picking_keywords',
        round: 2,
        keywords: ['Java', 'Spring'],
      })
    );
    drainApiInitCalls();

    expect(service.resultsRefreshTick()).toBeGreaterThan(tickAfterCooldown);
    expect(service.cooldownRemainingSeconds()).toBe(0);
  });

  it('calls POST /api/auto-mode/skip-cooldown and refreshes status', () => {
    service.applyStatusUpdate(
      makeStatus({
        phase: 'cooldown',
        round: 1,
        cooldown_seconds: 30,
        cooldown_remaining_s: 28,
      })
    );

    service.skipCooldown();

    const skipReq = httpMock.expectOne('/api/auto-mode/skip-cooldown');
    expect(skipReq.request.method).toBe('POST');
    skipReq.flush({ ok: true, skipped: true });

    const statusReq = httpMock.expectOne('/api/auto-mode/status');
    statusReq.flush(makeStatus({ phase: 'picking_keywords', round: 2 }));
    drainApiInitCalls();

    expect(service.status()?.round).toBe(2);
    expect(service.skippingCooldown()).toBeFalse();
  });
});
