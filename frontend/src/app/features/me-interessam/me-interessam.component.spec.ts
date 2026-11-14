import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MeInteressamComponent } from './me-interessam.component';

describe('MeInteressamComponent', () => {
  let fixture: ComponentFixture<MeInteressamComponent>;
  let component: MeInteressamComponent;
  let httpMock: HttpTestingController;

  const initialJobs = [
    {
      id: 'j1',
      url: 'https://example.com/java-1',
      title: 'Dev Java Júnior',
      company: 'Acme',
      portal: 'github-vagas',
      saved_at: '2026-11-12',
      screening: { score: 85, verdict: 'Strong Fit', summary: 'Resumo 1', ai_model: 'gemini-3-flash' },
    },
    {
      id: 'j2',
      url: 'recruiter://post/42',
      title: 'Dev Backend Python',
      company: 'Beta',
      portal: 'recruiter_radar',
      saved_at: '2026-11-11',
      recruiter_emails: ['talent@beta.com'],
      screening: { score: 80, verdict: 'Good Fit', summary: 'Resumo 2', ai_model: 'gemini-3-flash' },
    },
    {
      id: 'j3',
      url: 'https://example.com/frontend-3',
      title: 'Dev Angular Júnior',
      company: 'Gamma',
      portal: 'gupy-search',
      saved_at: '2026-11-10',
      screening: { score: 78, verdict: 'Good Fit', summary: 'Resumo 3', ai_model: 'gemini-4-hydrogen-high' },
    },
  ];

  function flushBootstrapRequests(savedPayload: any[] = initialJobs): void {
    for (const req of httpMock.match('/api/token')) {
      req.flush({ token: 'tok' });
    }
    for (const req of httpMock.match('/api/saved')) {
      req.flush({ saved: savedPayload });
    }
    for (const req of httpMock.match('/api/applications')) {
      req.flush({ applications: [] });
    }
    for (const req of httpMock.match('/api/discarded')) {
      req.flush({ discarded: [] });
    }
    for (const req of httpMock.match('/api/saved/batch-status')) {
      req.flush({ running: false, current: 0, total: 0, percent: 0, errors: 0 });
    }
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [MeInteressamComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(MeInteressamComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.match(() => true);
    fixture.destroy();
  });

  it('allows selecting all visible jobs and toggling individual checkboxes', () => {
    fixture.detectChanges();
    flushBootstrapRequests();
    fixture.detectChanges();

    const toolbar = fixture.nativeElement.querySelector('.selection-toolbar') as HTMLElement;
    expect(toolbar).toBeTruthy();

    const selectAllBtn = toolbar.querySelector('.btn-select-all') as HTMLButtonElement;
    expect(selectAllBtn.textContent).toContain('Selecionar todas (3)');
    expect(component.selectedVisibleCount()).toBe(0);

    // Filter down to "Java" and click "Selecionar todas (1)"
    component.searchTerm.set('Java');
    fixture.detectChanges();
    expect(selectAllBtn.textContent).toContain('Selecionar todas (1)');

    selectAllBtn.click();
    fixture.detectChanges();
    expect(component.selectedVisibleCount()).toBe(1);
    expect(component.isSelected('https://example.com/java-1')).toBeTrue();
    expect(selectAllBtn.textContent).toContain('Desmarcar todas');

    // Clear filter: only the 1 job stays selected
    component.searchTerm.set('');
    fixture.detectChanges();
    expect(component.selectedVisibleCount()).toBe(1);
    expect(selectAllBtn.textContent).toContain('Selecionar todas (3)');

    // Select all 3
    selectAllBtn.click();
    fixture.detectChanges();
    expect(component.selectedVisibleCount()).toBe(3);

    // Deselect all 3
    selectAllBtn.click();
    fixture.detectChanges();
    expect(component.selectedVisibleCount()).toBe(0);
  });

  it('starts batch AI re-evaluation for selected jobs and refreshes cards on completion', fakeAsync(() => {
    fixture.detectChanges();
    flushBootstrapRequests();
    fixture.detectChanges();

    const checkboxes = fixture.nativeElement.querySelectorAll('.job-select-checkbox') as NodeListOf<HTMLInputElement>;
    expect(checkboxes.length).toBe(3);

    checkboxes[0].click();
    fixture.detectChanges();
    expect(component.selectedVisibleCount()).toBe(1);

    const reevalBtn = fixture.nativeElement.querySelector('.btn-bulk-reevaluate') as HTMLButtonElement;
    expect(reevalBtn.disabled).toBeFalse();
    reevalBtn.click();

    const startReq = httpMock.expectOne('/api/saved/batch-reevaluate');
    expect(startReq.request.method).toBe('POST');
    expect(startReq.request.body).toEqual({ urls: ['https://example.com/java-1'] });
    startReq.flush({ ok: true, started: true, total: 1 });

    tick(1500);
    const pollReq = httpMock.expectOne('/api/saved/batch-status');
    pollReq.flush({
      running: false,
      current: 1,
      total: 1,
      percent: 100,
      errors: 0,
      provider: 'Google Gemini (gemini-4-hydrogen-high via Antigravity (agy))',
    });

    const updatedJobs = initialJobs.map((j, idx) =>
      idx === 0 ? { ...j, screening: { ...j.screening, score: 91, ai_model: 'gemini-4-hydrogen-high' } } : j
    );
    flushBootstrapRequests(updatedJobs);
    fixture.detectChanges();

    expect(component.reevalRunning()).toBeFalse();
    expect(component.bulkStatusMsg()).toContain('1 vaga');
    const firstCard = fixture.nativeElement.querySelector('.job-card') as HTMLElement;
    expect(firstCard.querySelector('.vc-badge-model')?.textContent).toContain('gemini-4-hydrogen-high');
    expect(firstCard.querySelector('.vc-badge-fit')?.textContent).toContain('91/100');
  }));

  it('marks selected jobs as applied and discards selected jobs via batch endpoints', () => {
    spyOn(window, 'confirm').and.returnValue(true);
    fixture.detectChanges();
    flushBootstrapRequests();
    fixture.detectChanges();

    // Select the recruiter job (index 1) and send to Candidaturas
    component.toggleJobSelection('recruiter://post/42');
    fixture.detectChanges();

    const applyBtn = fixture.nativeElement.querySelector('.btn-bulk-apply') as HTMLButtonElement;
    applyBtn.click();

    const applyReq = httpMock.expectOne('/api/applied/batch');
    expect(applyReq.request.method).toBe('POST');
    expect(applyReq.request.body.items[0]).toEqual({
      url: 'recruiter://post/42',
      company: 'Beta',
      role: 'Dev Backend Python',
      portal: 'recruiter_radar',
      contact_channel: 'recruiter_email',
      contacted_email: 'talent@beta.com',
    });
    applyReq.flush({ ok: true, applied: 1 });

    const remainingAfterApply = [initialJobs[0], initialJobs[2]];
    flushBootstrapRequests(remainingAfterApply);
    fixture.detectChanges();
    expect(component.selectedVisibleCount()).toBe(0);
    expect(component.savedJobs().length).toBe(2);

    // Select both remaining jobs and discard them
    component.toggleSelectAllVisible();
    fixture.detectChanges();
    const discardBtn = fixture.nativeElement.querySelector('.btn-bulk-discard') as HTMLButtonElement;
    discardBtn.click();

    const discReq = httpMock.expectOne('/api/saved/batch-discard');
    expect(discReq.request.method).toBe('POST');
    expect(discReq.request.body).toEqual({
      urls: ['https://example.com/java-1', 'https://example.com/frontend-3'],
    });
    discReq.flush({ ok: true, discarded: 2, total: 2 });

    flushBootstrapRequests([]);
    fixture.detectChanges();
    expect(component.savedJobs().length).toBe(0);
    expect(component.selectedVisibleCount()).toBe(0);
  });

  it('renders fit badge thresholds at 59/60/75 and displays gate warning chips', () => {
    fixture.detectChanges();
    const calibratedJobs = [
      {
        id: 'c1',
        url: 'https://example.com/c1',
        title: 'Dev Senior',
        company: 'Acme',
        portal: 'gupy-search',
        saved_at: '2026-11-12',
        screening: {
          score: 59,
          verdict: 'Moderate Fit',
          language_gate: 'FLAG',
          language_note: 'Inglês avançado',
          location_verdict: 'FAIL',
        },
      },
      {
        id: 'c2',
        url: 'https://example.com/c2',
        title: 'Dev Pleno',
        company: 'Beta',
        portal: 'gupy-search',
        saved_at: '2026-11-12',
        screening: {
          score: 60,
          verdict: 'Good Fit',
          subscores: { technical: 65, experience: 60, behavioral: 70, career: 52 },
        },
      },
      {
        id: 'c3',
        url: 'https://example.com/c3',
        title: 'Dev Junior',
        company: 'Gamma',
        portal: 'gupy-search',
        saved_at: '2026-11-12',
        screening: { score: 75, verdict: 'Strong Fit' },
      },
    ];
    flushBootstrapRequests(calibratedJobs);
    fixture.detectChanges();

    const cards = Array.from(fixture.nativeElement.querySelectorAll('.job-card')) as HTMLElement[];
    expect(cards.length).toBe(3);

    expect(cards[0].querySelector('.vc-badge-fit--low')?.textContent).toContain('59/100');
    const gates = Array.from(cards[0].querySelectorAll('.vc-badge-gate')).map((el) => el.textContent?.trim());
    expect(gates.some((t) => t?.includes('Idioma: FLAG'))).toBeTrue();
    expect(gates.some((t) => t?.includes('Local: FAIL'))).toBeTrue();

    expect(cards[1].querySelector('.vc-badge-fit--med')?.textContent).toContain('60/100');
    expect(cards[1].querySelector('.vc-badge-fit--med')?.getAttribute('title')).toContain('Téc: 65');

    expect(cards[2].querySelector('.vc-badge-fit--high')?.textContent).toContain('75/100');
  });

  it('applies surface/input/badge styles and prevents header badge overlap or horizontal overflow', () => {
    const hostEl = fixture.nativeElement as HTMLElement;
    const prevTheme = document.documentElement.getAttribute('data-theme');
    document.documentElement.setAttribute('data-theme', 'dark');
    hostEl.style.display = 'block';
    hostEl.style.width = '780px';

    try {
      fixture.detectChanges();
      const layoutJobs = [
        {
          id: 'overlap-1',
          url: 'https://example.com/mimix-backend',
          title: '[Remoto] Desenvolvedor(a) Backend Pleno - White Label e Plataforma - Mimix AI',
          company: 'backend-br/vagas (moneymagic)',
          portal: 'github_vagas',
          saved_at: '2026-11-11',
          auto_promoted: true,
          auto_origin: 'recruiter',
          recruiter_emails: ['recruiter@example.com'],
          screening: {
            score: 82,
            verdict: 'Good Fit',
            summary: 'Vaga backend alinhada.',
            ai_model: 'gemini-4-hydrogen-high',
          },
        },
        {
          id: 'overlap-2',
          url: 'https://example.com/frontend-jr',
          title: 'Desenvolvedor Front-end Jr',
          company: 'Wicomm',
          portal: 'solides-search',
          saved_at: '2026-11-11',
          auto_promoted: true,
          auto_origin: 'search',
          screening: {
            score: 90,
            verdict: 'Strong Fit',
            summary: 'Boa aderência.',
          },
        },
      ];
      flushBootstrapRequests(layoutJobs);
      fixture.detectChanges();

      const searchInput = hostEl.querySelector('#mi-search-text') as HTMLInputElement;
      const inputBg = getComputedStyle(searchInput).backgroundColor;
      expect(inputBg).not.toBe('rgba(0, 0, 0, 0)');
      expect(inputBg).not.toBe('rgb(255, 255, 255)');

      const firstCard = hostEl.querySelector('.job-card') as HTMLElement;
      expect(getComputedStyle(firstCard).backgroundColor).not.toBe('rgba(0, 0, 0, 0)');

      const autoBadge = firstCard.querySelector('.badge-auto-promoted') as HTMLElement;
      expect(autoBadge).toBeTruthy();
      expect(getComputedStyle(autoBadge).backgroundColor).not.toBe('rgba(0, 0, 0, 0)');
      expect(getComputedStyle(autoBadge).borderRadius).toBe('999px');

      const titleEl = firstCard.querySelector('.job-card__title') as HTMLElement;
      const badgesHost = firstCard.querySelector('app-job-badges') as HTMLElement;
      const tRect = titleEl.getBoundingClientRect();
      const bRect = badgesHost.getBoundingClientRect();
      const overlaps =
        tRect.left < bRect.right - 1 &&
        tRect.right > bRect.left + 1 &&
        tRect.top < bRect.bottom - 1 &&
        tRect.bottom > bRect.top + 1;
      expect(overlaps).toBeFalse();

      expect(hostEl.scrollWidth).toBeLessThanOrEqual(hostEl.clientWidth + 1);

      // Verify narrow/mobile width does not cause horizontal overflow either
      hostEl.style.width = '360px';
      fixture.detectChanges();
      expect(hostEl.scrollWidth).toBeLessThanOrEqual(hostEl.clientWidth + 1);
    } finally {
      hostEl.style.width = '';
      if (prevTheme) {
        document.documentElement.setAttribute('data-theme', prevTheme);
      } else {
        document.documentElement.removeAttribute('data-theme');
      }
    }
  });

  it('renders LinkedIn portal badges and filters saved jobs by portal', () => {
    const portalJobs = [
      ...initialJobs,
      {
        id: 'j4',
        url: 'https://www.linkedin.com/feed/update/urn:li:activity:7400000000000000009/',
        title: 'Desenvolvedor Java/Angular',
        company: 'LinkedInCorp',
        portal: 'linkedin_post',
        saved_at: '2026-11-13',
        recruiter_emails: ['talent@linkedincorp.dev'],
        screening: { score: 91, verdict: 'Strong Fit', summary: 'Match ótimo', ai_model: 'gemini-3-flash' },
      },
      {
        id: 'j5',
        url: 'https://www.linkedin.com/jobs/view/999',
        title: 'Engenheiro Pleno',
        company: 'LinkedInJobs Co',
        portal: 'linkedin-search',
        saved_at: '2026-11-13',
        screening: { score: 83, verdict: 'Strong Fit', summary: 'Match bom', ai_model: 'gemini-3-flash' },
      },
    ];

    fixture.detectChanges();
    flushBootstrapRequests(portalJobs);
    fixture.detectChanges();

    expect(component.availablePortals()).toContain('linkedin_post');
    expect(component.availablePortals()).toContain('linkedin-search');

    const el = fixture.nativeElement as HTMLElement;
    const liPostBadge = el.querySelector('app-portal-badge [data-portal="linkedin_post"]') as HTMLElement;
    const liSearchBadge = el.querySelector('app-portal-badge [data-portal="linkedin-search"]') as HTMLElement;
    expect(liPostBadge).not.toBeNull();
    expect(liPostBadge.querySelector('i.bi-linkedin')).not.toBeNull();
    expect(liSearchBadge).not.toBeNull();
    expect(liSearchBadge.querySelector('i.bi-linkedin')).not.toBeNull();

    component.portalFilter.set('linkedin_post');
    fixture.detectChanges();
    expect(component.filteredJobs().length).toBe(1);
    expect(component.filteredJobs()[0].company).toBe('LinkedInCorp');
    expect(component.hasActiveFilters()).toBeTrue();

    component.clearFilters();
    fixture.detectChanges();
    expect(component.portalFilter()).toBe('all');
    expect(component.filteredJobs().length).toBe(5);
  });
});
