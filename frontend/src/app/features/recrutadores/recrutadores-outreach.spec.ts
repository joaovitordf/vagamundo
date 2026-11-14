import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of } from 'rxjs';
import { ApiService, LinkedInWorkerStatus } from '../../core/services/api.service';
import { AutoModeService } from '../../core/services/auto-mode.service';
import { RecruiterPost } from '../../core/models/vaga.model';
import { filterAndSortRecruiterPosts } from '../../core/services/recruiter-state.service';
import { RecrutadoresComponent, removePostAndFlagEmail, summarizeRecruiterSync } from './recrutadores.component';
import {
  filterApplicationsList,
  isDirectEmailApplication,
} from '../candidaturas/candidaturas.component';

describe('Recruiter outreach history helpers', () => {
  it('removes contacted post and immediately flags sibling posts sharing the email', () => {
    const posts: RecruiterPost[] = [
      {
        id: 1,
        emails: ['arturo.gutierrez@ibertech.org'],
        title: 'Fullstack Angular / Java',
        company: 'Ibertech',
        portal: 'freehire-search',
        description: 'Vaga 1',
        matched_keywords: ['Angular'],
        match_score: 90,
        created_at: '2026-11-10T10:00:00',
      },
      {
        id: 2,
        emails: ['rh@ibertech.org', 'ARTURO.GUTIERREZ@ibertech.org'],
        title: 'Tech Lead Java',
        company: 'Ibertech Latam',
        portal: 'linkedin_post',
        description: 'Vaga 2',
        matched_keywords: ['Java'],
        match_score: 80,
        created_at: '2026-11-11T10:00:00',
      },
      {
        id: 3,
        emails: ['jobs@outra.io'],
        title: 'Backend Go',
        company: 'Outra Corp',
        portal: 'hn-search',
        description: 'Vaga 3',
        matched_keywords: [],
        match_score: 50,
        created_at: '2026-11-11T11:00:00',
      },
    ];

    const next = removePostAndFlagEmail(posts, 1, 'arturo.gutierrez@ibertech.org', {
      company: 'Ibertech',
      title: 'Fullstack Angular / Java',
      contacted_at: '2026-11-11',
    });

    expect(next.map(p => p.id)).toEqual([2, 3]);
    expect(next[0].previously_contacted?.length).toBe(1);
    expect(next[0].previously_contacted?.[0].email).toBe('arturo.gutierrez@ibertech.org');
    expect(next[0].previously_contacted?.[0].company).toBe('Ibertech');
    expect(next[1].previously_contacted).toBeUndefined();
  });

  it('filters applications by direct email channel and recruiter email text search', () => {
    const apps = [
      {
        id: 10,
        company: 'Ibertech',
        role: 'Fullstack Angular',
        channel: 'freehire-search',
        portal: 'freehire-search',
        contact_channel: 'recruiter_email',
        contacted_email: 'arturo.gutierrez@ibertech.org',
        recruiter_emails: ['arturo.gutierrez@ibertech.org'],
        status: 'applied',
        applied_date: '2026-11-11',
      },
      {
        id: 11,
        company: 'Acme Portal',
        role: 'Engenheiro de Software',
        channel: 'gupy-search',
        portal: 'gupy-search',
        contact_channel: 'portal',
        url: 'https://acme.gupy.io/jobs/123',
        status: 'applied',
        applied_date: '2026-11-10',
      },
    ];

    expect(isDirectEmailApplication(apps[0])).toBeTrue();
    expect(isDirectEmailApplication(apps[1])).toBeFalse();

    const baseOpts = {
      searchTerm: '',
      statusFilter: 'all',
      channelFilter: 'recruiter_email' as const,
      dateCriterion: 'applied' as const,
      dateRange: 'all',
      customStartDate: '',
      customEndDate: '',
      sortOrder: 'recent' as const,
    };

    const directOnly = filterApplicationsList(apps, baseOpts);
    expect(directOnly.map(a => a.id)).toEqual([10]);

    const portalOnly = filterApplicationsList(apps, { ...baseOpts, channelFilter: 'portal' });
    expect(portalOnly.map(a => a.id)).toEqual([11]);

    const byEmailSearch = filterApplicationsList(apps, {
      ...baseOpts,
      channelFilter: 'all',
      searchTerm: 'arturo.gutierrez',
    });
    expect(byEmailSearch.map(a => a.id)).toEqual([10]);

    const byBrDateWindow = filterApplicationsList(
      [{ ...apps[0], applied_date: '10/11/2026' }, { ...apps[1], applied_date: '01/10/2026' }],
      { ...baseOpts, channelFilter: 'all', dateRange: 'custom', customStartDate: '2026-11-01', customEndDate: '2026-11-30' }
    );
    expect(byBrDateWindow.map(a => a.id)).toEqual([10]);
  });

  it('filters recruiter posts with multi-word queries, med_plus scores, and empty text when searched', () => {
    const posts: RecruiterPost[] = [
      {
        id: 1,
        emails: ['rh@alpha.com'],
        title: 'Desenvolvedor(a) Backend Java Júnior',
        company: 'Alpha',
        portal: 'linkedin_post',
        description: 'Vaga remota Java Spring',
        matched_keywords: ['Java'],
        match_score: 82,
        ai_classification: 'vaga_ativa',
        ai_score: 82,
        ai_evaluated_at: '2026-11-11T10:00:00',
        created_at: '2026-11-11T10:00:00',
      },
      {
        id: 2,
        emails: ['rh@beta.com'],
        title: 'Tech Recruiter',
        company: 'Beta',
        portal: 'hn-search',
        description: 'Hiring Python engineers',
        matched_keywords: ['Python'],
        match_score: 64,
        ai_classification: 'vaga_ativa',
        ai_score: 64,
        ai_evaluated_at: '2026-11-11T10:00:00',
        created_at: '2026-11-11T10:00:00',
      },
    ];

    const multiWord = filterAndSortRecruiterPosts(posts, {
      hasSearched: true,
      filterText: 'Desenvolvedor Java',
      portalFilter: '',
      workModelFilter: '',
      regionFilter: '',
      jobAgeFilter: '',
      hideUndated: false,
      scoreFilter: 'med_plus',
      sortBy: 'score-desc',
      onlyCvMatch: false,
      hideNonJobs: true,
    });
    expect(multiWord.map(p => p.id)).toEqual([1]);

    const clearedTextAll = filterAndSortRecruiterPosts(posts, {
      hasSearched: true,
      filterText: '',
      portalFilter: '',
      workModelFilter: '',
      regionFilter: '',
      jobAgeFilter: '',
      hideUndated: false,
      scoreFilter: 'med_plus',
      sortBy: 'score-desc',
      onlyCvMatch: false,
      hideNonJobs: true,
    });
    expect(clearedTextAll.map(p => p.id)).toEqual([1, 2]);
  });

  it('summarizes multi-platform sync breakdown and partial rate-limit warnings', () => {
    const okSummary = summarizeRecruiterSync({
      ok: true,
      scanned: 10,
      posts_with_email: 2,
      synced: 7,
      portal_breakdown: {
        'github-vagas': { fetched: 6, matched: 4, errors: 0 },
        'hn-search': { fetched: 2, matched: 2, errors: 0 },
        'remotar-search': { fetched: 1, matched: 1, errors: 0 },
      },
      warnings: ['GitHub Vagas BR atingiu limite temporário de requisições'],
      rate_limited: true,
      errors: 1,
    });
    expect(okSummary.status).toContain('7 oportunidade(s)');
    expect(okSummary.status).toContain('GitHub Vagas BR: 4');
    expect(okSummary.status).toContain('Hacker News (Who is Hiring): 2');
    expect(okSummary.status).toContain('Remotar: 1');
    expect(okSummary.warning).toContain('GitHub Vagas BR atingiu limite');

    const fallbackSummary = summarizeRecruiterSync({
      ok: true,
      scanned: 0,
      posts_with_email: 0,
      synced: 3,
      github_synced: 2,
      remotive_synced: 1,
    });
    expect(fallbackSummary.status).toContain('GitHub Vagas BR: 2');
    expect(fallbackSummary.status).toContain('Remotive: 1');
    expect(fallbackSummary.warning).toBeNull();
  });
});

describe('RecrutadoresComponent LinkedIn Automático worker UI', () => {
  const baseWorkerStatus = (overrides: Partial<LinkedInWorkerStatus> = {}): LinkedInWorkerStatus => ({
    ok: true,
    status: 'not_connected',
    browser_available: true,
    browser_name: 'chrome',
    profile_initialized: false,
    enabled: true,
    headless: false,
    cooldown_minutes: 20,
    max_daily_searches: 15,
    max_scrolls: 3,
    daily_date: '2026-11-13',
    daily_count: 0,
    cooldown_remaining_seconds: 0,
    last_run_at: null,
    last_error: '',
    last_query: '',
    last_imported: 0,
    ...overrides,
  });

  it('renders minimal LinkedIn bar without extra clutter buttons and starts Auto Mode without window.open', () => {
    const startSpy = jasmine.createSpy('startRecruiters').and.returnValue(of({ ok: true }));
    const openSpy = spyOn(window, 'open');
    const connectSpy = jasmine
      .createSpy('connectLinkedInWorker')
      .and.returnValue(of(baseWorkerStatus({ status: 'connected', profile_initialized: true })));

    TestBed.configureTestingModule({
      imports: [RecrutadoresComponent],
      providers: [
        {
          provide: ApiService,
          useValue: {
            getCvAreas: () => of({ areas: [{ id: 'be', label: 'Backend', keywords: ['Python'] }] }),
            getRecruiterAutoConfig: () => of({ ok: true, config: { min_score: 60, continuous: true, cooldown_seconds: 30 } }),
            saveRecruiterAutoConfig: () => of({ ok: true }),
            getRecruiterPosts: () => of({ posts: [] }),
            getLinkedInWorkerStatus: () => of(baseWorkerStatus()),
            connectLinkedInWorker: connectSpy,
            verifyLinkedInWorker: () => of(baseWorkerStatus({ status: 'connected' })),
            disconnectLinkedInWorker: () => of(baseWorkerStatus({ status: 'not_connected' })),
          },
        },
        {
          provide: AutoModeService,
          useValue: {
            status: signal(null),
            isRunning: signal(false),
            resultsRefreshTick: signal(0),
            startRecruiters: startSpy,
            cancel: () => {},
          },
        },
      ],
    });

    const fixture = TestBed.createComponent(RecrutadoresComponent);
    const comp = fixture.componentInstance;
    fixture.detectChanges();

    expect(comp.availablePortals()).toContain('linkedin_post');
    const el: HTMLElement = fixture.nativeElement;
    expect(el.textContent).toContain('LinkedIn Automático');
    expect(el.textContent).toContain('Conectar LinkedIn (1ª vez)');
    expect(el.textContent).not.toContain('Rebuscar LinkedIn');
    expect(el.textContent).not.toContain('Incluir LinkedIn');
    expect(el.textContent).not.toContain('Colar post avulso');
    expect(el.textContent).not.toContain('Capturar LinkedIn');
    expect(el.textContent).not.toContain('Copiar código');
    expect(el.textContent).not.toContain('+ Aba LinkedIn');

    comp.connectLinkedIn();
    expect(connectSpy).toHaveBeenCalled();
    expect(comp.linkedInStatus()?.status).toBe('connected');
    fixture.detectChanges();
    expect(el.textContent).toContain('Desconectar');
    expect(el.textContent).not.toContain('Rebuscar LinkedIn');
    expect(el.textContent).not.toContain('Descanso:');

    comp.filterText = 'Angular';
    comp.triggerAutoMode();

    expect(openSpy).not.toHaveBeenCalled();
    expect(startSpy).toHaveBeenCalled();
    fixture.destroy();
  });

  it('auto-verifies once when awaiting_login window closes cleanly', () => {
    let statusStep = 0;
    const verifySpy = jasmine
      .createSpy('verifyLinkedInWorker')
      .and.returnValue(of(baseWorkerStatus({ status: 'connected', profile_initialized: true, login_window_open: false })));

    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      imports: [RecrutadoresComponent],
      providers: [
        {
          provide: ApiService,
          useValue: {
            getCvAreas: () => of({ areas: [] }),
            getRecruiterAutoConfig: () => of({ ok: true, config: { min_score: 60, continuous: true, cooldown_seconds: 30 } }),
            saveRecruiterAutoConfig: () => of({ ok: true }),
            getRecruiterPosts: () => of({ posts: [] }),
            getLinkedInWorkerStatus: () => {
              statusStep++;
              return of(baseWorkerStatus({
                status: 'awaiting_login',
                login_window_open: statusStep === 1,
              }));
            },
            connectLinkedInWorker: () => of(baseWorkerStatus({ status: 'awaiting_login', login_window_open: true })),
            verifyLinkedInWorker: verifySpy,
            updateLinkedInWorkerConfig: () => of(baseWorkerStatus()),
            disconnectLinkedInWorker: () => of(baseWorkerStatus({ status: 'not_connected' })),
          },
        },
        {
          provide: AutoModeService,
          useValue: {
            status: signal(null),
            isRunning: signal(false),
            resultsRefreshTick: signal(0),
            startRecruiters: () => of({ ok: true }),
            cancel: () => {},
          },
        },
      ],
    });

    const fixture = TestBed.createComponent(RecrutadoresComponent);
    const comp = fixture.componentInstance;
    fixture.detectChanges();

    expect(comp.linkedInStatus()?.status).toBe('awaiting_login');
    expect(fixture.nativeElement.textContent).toContain('Esqueci a senha');
    expect(verifySpy).not.toHaveBeenCalled();

    // Segunda checagem simula o usuário tendo fechado a janela do navegador (login_window_open: false)
    comp.loadLinkedInStatus();
    expect(verifySpy).toHaveBeenCalledTimes(1);
    expect(comp.linkedInStatus()?.status).toBe('connected');
    fixture.destroy();
  });

  it('triggers manual AI triage, force LinkedIn re-search, and renders LinkedIn portal badge + diagnostics', () => {
    let triagedDone = false;
    const postBefore: RecruiterPost = {
      id: 101,
      emails: ['talentos@fintech.dev'],
      title: 'Java / Angular Dev',
      company: 'FinTech BR',
      portal: 'linkedin_post',
      description: 'Vaga Java Angular remota. CV para talentos@fintech.dev',
      matched_keywords: ['Java', 'Angular'],
      match_score: 70,
      published_date: new Date().toISOString().slice(0, 10),
      created_at: new Date().toISOString(),
    };
    const postTriaged: RecruiterPost = {
      ...postBefore,
      ai_classification: 'vaga_ativa',
      ai_score: 89,
      ai_verdict: 'Strong Fit',
      ai_summary: 'Ótima aderência com Java e Angular.',
      ai_evaluated_at: new Date().toISOString(),
    };
    const syncSpy = jasmine.createSpy('syncRecruiterPosts').and.returnValue(of({
      ok: true,
      scanned: 1,
      posts_with_email: 1,
      synced: 1,
      linkedin_synced: 1,
      linkedin_cards_total: 5,
    }));
    const triageSpy = jasmine.createSpy('triageRecruiterPosts').and.callFake(() => {
      triagedDone = true;
      return of({
        ok: true,
        triaged: 1,
        active_jobs: 1,
        talent_pools_discarded: 0,
        not_a_job: 0,
        errors: 0,
        posts: [postTriaged],
      });
    });

    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      imports: [RecrutadoresComponent],
      providers: [
        {
          provide: ApiService,
          useValue: {
            getCvAreas: () => of({ areas: [] }),
            getRecruiterAutoConfig: () => of({ ok: true, config: { min_score: 60, continuous: true, cooldown_seconds: 30 } }),
            saveRecruiterAutoConfig: () => of({ ok: true }),
            getRecruiterPosts: () => of({ posts: [triagedDone ? postTriaged : postBefore] }),
            syncRecruiterPosts: syncSpy,
            triageRecruiterPosts: triageSpy,
            getLinkedInWorkerStatus: () => of(baseWorkerStatus({
              status: 'connected',
              profile_initialized: true,
              last_query: 'Java',
              last_imported: 1,
              last_cards_total: 5,
            })),
            connectLinkedInWorker: () => of(baseWorkerStatus({ status: 'connected' })),
            verifyLinkedInWorker: () => of(baseWorkerStatus({ status: 'connected' })),
            updateLinkedInWorkerConfig: () => of(baseWorkerStatus({ status: 'connected' })),
            disconnectLinkedInWorker: () => of(baseWorkerStatus({ status: 'not_connected' })),
          },
        },
        {
          provide: AutoModeService,
          useValue: {
            status: signal(null),
            isRunning: signal(false),
            resultsRefreshTick: signal(0),
            startRecruiters: () => of({ ok: true }),
            cancel: () => {},
          },
        },
      ],
    });

    const fixture = TestBed.createComponent(RecrutadoresComponent);
    const comp = fixture.componentInstance;
    comp.resetSecondaryFilters();
    comp.state.jobAgeFilter.set('');
    comp.filterText = 'Java';
    comp.state.hasSearched.set(true);
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('Última: "Java" · 5 cards · 1 c/ e-mail');
    expect(el.textContent).not.toContain('Rebuscar LinkedIn');
    const liBadge = el.querySelector('app-portal-badge [data-portal="linkedin_post"]') as HTMLElement;
    expect(liBadge).not.toBeNull();
    expect(liBadge.querySelector('i.bi-linkedin')).not.toBeNull();

    comp.onSearch();
    expect(syncSpy).toHaveBeenCalledWith('Java');

    comp.state.jobAgeFilter.set('7');
    comp.onSearch();
    expect(syncSpy).toHaveBeenCalledWith('Java', { days: 7 });

    comp.onTriagePending();
    expect(triageSpy).toHaveBeenCalledWith({ post_ids: [101], limit: 12 });
    fixture.detectChanges();
    expect(el.textContent).toContain('89/100');

    const cooldownDiag = summarizeRecruiterSync({
      ok: true,
      scanned: 0,
      posts_with_email: 0,
      synced: 0,
      linkedin_skipped_reason: 'cooldown',
      linkedin_cooldown_remaining_seconds: 900,
    });
    expect(cooldownDiag.warning).toContain('15 min');

    comp.filterText = 'Angular';
    comp.allPosts.set([
      {
        id: 202,
        portal: 'linkedin_post',
        company: 'RemotoBR',
        author_name: 'Ana Tech Recruiter',
        title: 'Dev Angular Pleno',
        location: 'Remoto / A Definir',
        text: 'Estamos contratando Dev Angular Pleno 100% remoto. Inscreva-se pelo post.',
        emails: [],
        url: 'https://www.linkedin.com/feed/update/urn:li:activity:7400000000000000202/',
        published_date: new Date().toISOString(),
        status: 'new',
        ai_classification: 'vaga_ativa',
        ai_score: 85,
        created_at: new Date().toISOString(),
      } as any,
    ]);
    comp.state.regionFilter.set('brasil');
    fixture.detectChanges();

    expect(comp.filteredPosts().length).toBe(1);
    expect(el.textContent).toContain('Abrir publicação no LinkedIn');
    expect(el.textContent).not.toContain('Já mandei e-mail');
    fixture.destroy();
  });
});
