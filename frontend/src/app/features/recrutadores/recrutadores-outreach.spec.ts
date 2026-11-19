import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { computed, signal } from '@angular/core';
import { of } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AutoModeService } from '../../core/services/auto-mode.service';
import { RecruiterPost } from '../../core/models/vaga.model';
import {
  RECRUITER_STATE_STORAGE_KEY,
  filterAndSortRecruiterPosts,
  filterAndSortRelevantHistoryPosts,
} from '../../core/services/recruiter-state.service';
import { RecrutadoresComponent, removePostAndFlagEmail, summarizeRecruiterSync } from './recrutadores.component';
import { LinkedinSearchBarComponent } from './components/linkedin-search-bar/linkedin-search-bar.component';
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

describe('RecrutadoresComponent Barra Formatada LinkedIn e Fluxo Manual', () => {
  beforeEach(() => {
    localStorage.removeItem(RECRUITER_STATE_STORAGE_KEY);
  });

  afterEach(() => {
    localStorage.removeItem(RECRUITER_STATE_STORAGE_KEY);
  });

  it('renders formatted LinkedIn search bar with presets, reactive filters, custom override reset and clipboard copy without window.open on Auto Mode', () => {
    const startSpy = jasmine.createSpy('startRecruiters').and.returnValue(of({ ok: true }));
    const openSpy = spyOn(window, 'open');
    const writeTextSpy = jasmine.createSpy('writeText').and.returnValue(Promise.resolve());
    if (navigator?.clipboard) {
      spyOnProperty(navigator, 'clipboard', 'get').and.returnValue({ writeText: writeTextSpy } as unknown as Clipboard);
    }

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
    expect(el.textContent).toContain('Barra de Pesquisa LinkedIn');
    expect(el.textContent).toContain('Google X-Ray');
    expect(el.textContent).not.toContain('LinkedIn Automático');
    expect(el.textContent).not.toContain('Conectar LinkedIn');

    // Altera filtros e valida query booleana enxuta + URL do LinkedIn em tempo real
    const linkedInBar = fixture.debugElement.query(By.directive(LinkedinSearchBarComponent))
      .componentInstance as LinkedinSearchBarComponent;
    comp.filterText = 'Visão Computacional';
    comp.workModelFilter = 'remote';
    comp.regionFilter = 'brasil';
    comp.jobAgeFilter = '7';
    fixture.detectChanges();

    expect(linkedInBar.activeLinkedInQuery()).toBe(
      '("Visão Computacional" OR "Computer Vision") AND (vaga OR contratando OR hiring)'
    );
    const openLink = el.querySelector('.linkedin-search-actions a.linkedin-btn') as HTMLAnchorElement;
    expect(openLink).not.toBeNull();
    expect(openLink.getAttribute('href')).toContain('https://www.linkedin.com/search/results/content/?keywords=');
    expect(openLink.getAttribute('href')).toContain('datePosted=%22past-week%22');
    expect(openLink.getAttribute('target')).toBe('_blank');

    // Alternar preset e idioma
    linkedInBar.setLinkedInPreset('jobs_email');
    linkedInBar.setLinkedInLanguageMode('en');
    fixture.detectChanges();
    expect(linkedInBar.activeLinkedInQuery()).toBe(
      '"Computer Vision" AND (email OR cv OR resume)'
    );

    // Edição manual + restauração
    linkedInBar.onLinkedInQueryInput('Python AND hiring AND "remote"');
    fixture.detectChanges();
    expect(linkedInBar.linkedInCustomQuery()).toBe('Python AND hiring AND "remote"');
    expect(linkedInBar.activeLinkedInUrl()).toContain(encodeURIComponent('Python AND hiring AND "remote"'));
    linkedInBar.resetLinkedInQuery();
    fixture.detectChanges();
    expect(linkedInBar.linkedInCustomQuery()).toBeNull();

    linkedInBar.copyLinkedInQuery();
    if (navigator?.clipboard) {
      expect(writeTextSpy).toHaveBeenCalledTimes(1);
    }

    comp.triggerAutoMode();
    expect(openSpy).not.toHaveBeenCalled();
    expect(startSpy).toHaveBeenCalled();
    fixture.destroy();
  });

  it('imports single and batch LinkedIn posts via manual paste panel into Atuais encontrados', () => {
    const importedSingle: RecruiterPost = {
      id: 701,
      portal: 'linkedin_post',
      company: 'TechRecruiter',
      title: 'Dev Python Remoto',
      description: 'Vaga Python remoto! CV para jobs@techrecruiter.dev',
      emails: ['jobs@techrecruiter.dev'],
      matched_keywords: ['Python'],
      match_score: 80,
      url: 'https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000701/',
      created_at: new Date().toISOString(),
    };
    const importedBatch: RecruiterPost = {
      id: 702,
      portal: 'linkedin_post',
      company: 'CloudTwo',
      title: 'Backend Go',
      description: 'Vaga Go! CV para talent@cloudtwo.dev',
      emails: ['talent@cloudtwo.dev'],
      matched_keywords: ['Go'],
      match_score: 75,
      created_at: new Date().toISOString(),
    };

    let dbPosts: RecruiterPost[] = [];
    const pasteSpy = jasmine.createSpy('pasteRecruiterPost').and.callFake(() => {
      dbPosts = [importedSingle, ...dbPosts.filter(p => p.id !== importedSingle.id)];
      return of({
        ok: true,
        post: importedSingle,
        auto_mode_woken: false,
      });
    });
    const batchSpy = jasmine.createSpy('pasteRecruiterPostsBatch').and.callFake(() => {
      dbPosts = [importedBatch, ...dbPosts.filter(p => p.id !== importedBatch.id)];
      return of({
        ok: true,
        imported: 1,
        updated: 0,
        skipped: 0,
        invalid: 0,
        posts: [importedBatch],
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
            getRecruiterPosts: () => of({ posts: dbPosts }),
            pasteRecruiterPost: pasteSpy,
            pasteRecruiterPostsBatch: batchSpy,
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
    const linkedInBar = fixture.debugElement.query(By.directive(LinkedinSearchBarComponent))
      .componentInstance as LinkedinSearchBarComponent;

    linkedInBar.togglePastePanel();
    expect(linkedInBar.showPastePanel()).toBeTrue();

    linkedInBar.pasteText.set('Vaga Python remoto! CV para jobs@techrecruiter.dev');
    linkedInBar.pasteUrl.set('https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000701/');
    linkedInBar.submitManualPaste();
    fixture.detectChanges();

    expect(pasteSpy).toHaveBeenCalledWith({
      raw_text: 'Vaga Python remoto! CV para jobs@techrecruiter.dev',
      url: 'https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000701/',
      allow_without_email: true,
    });
    expect(linkedInBar.showPastePanel()).toBeTrue();
    expect(linkedInBar.pastedReviews().map(r => r.post.id)).toContain(701);
    expect(comp.filteredPosts().map(p => p.id)).toContain(701);

    // Colagem em lote separada por '---' (painel continua aberto)
    linkedInBar.pasteText.set('Post 1\n---\nVaga Go! CV para talent@cloudtwo.dev');
    linkedInBar.submitManualPaste();
    fixture.detectChanges();

    expect(batchSpy).toHaveBeenCalledWith({
      raw_batch_text: 'Post 1\n---\nVaga Go! CV para talent@cloudtwo.dev',
      allow_without_email: true,
    });
    expect(linkedInBar.pastedReviews().map(r => r.post.id)).toContain(702);
    expect(comp.filteredPosts().map(p => p.id)).toContain(702);

    fixture.destroy();
  });

  it('triggers manual AI triage and renders LinkedIn portal badge + diagnostics', () => {
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
      portal_synced: 1,
      matched_post_ids: [101],
      collected_post_ids: [101],
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
    expect(comp.jobAgeFilter).toBe('');
    comp.filterText = 'Java';
    comp.onSearch();
    expect(syncSpy).toHaveBeenCalledWith('Java');

    comp.state.jobAgeFilter.set('');
    comp.state.hasSearched.set(true);
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
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

    const partialDiag = summarizeRecruiterSync({
      ok: true,
      scanned: 0,
      posts_with_email: 0,
      synced: 0,
      warnings: ['github-vagas: HTTP 403'],
    });
    expect(partialDiag.warning).toContain('github-vagas: HTTP 403');

    comp.filterText = 'Angular';
    comp.state.currentRoundPostIds.set(null);
    comp.allPosts.set([
      {
        id: 202,
        portal: 'linkedin_post',
        company: 'RemotoBR',
        author_name: 'Ana Tech Recruiter',
        title: 'Dev Angular Pleno',
        location: 'Remoto / A Definir',
        description: 'Estamos contratando Dev Angular Pleno 100% remoto. Envie CV para vagas@remotobr.dev.',
        emails: ['vagas@remotobr.dev'],
        matched_keywords: ['Angular'],
        match_score: 85,
        url: 'https://www.linkedin.com/feed/update/urn:li:activity:7400000000000000202/',
        published_date: new Date().toISOString(),
        ai_classification: 'vaga_ativa',
        ai_score: 85,
        ai_evaluated_at: new Date().toISOString(),
        created_at: new Date().toISOString(),
      } as any,
    ]);
    comp.state.regionFilter.set('brasil');
    fixture.detectChanges();

    expect(comp.filteredPosts().length).toBe(1);
    expect(el.textContent).toContain('vagas@remotobr.dev');
    expect(el.textContent).toContain('Ver post original');
    expect(el.textContent).toContain('Já mandei e-mail');
    expect(el.textContent).toContain('Descartar');
    fixture.destroy();
  });

  it('loads all platforms simultaneously, keeps Atuais encontrados empty until search/round, and scopes by round_post_ids', () => {
    localStorage.removeItem(RECRUITER_STATE_STORAGE_KEY);
    const autoStatusSig = signal<any>(null);
    const refreshTickSig = signal<number>(0);
    const startAutoSpy = jasmine.createSpy('startRecruiters').and.callFake(() => {
      autoStatusSig.set({
        running: true,
        run_id: 'run-multi-1',
        round: 1,
        mode: 'recruiters',
        keywords: [],
        phase: 'picking_keywords',
        round_post_ids: [],
      });
      return of({ ok: true, run_id: 'run-multi-1' });
    });

    const todayIso = new Date().toISOString();
    const postCompatible: RecruiterPost = {
      id: 301,
      portal: 'linkedin_post',
      company: 'Alpha Tech',
      title: 'Desenvolvedor Python Sênior',
      description: 'Vaga Python Sênior 100% remoto. CV para rh@alpha.dev',
      emails: ['rh@alpha.dev'],
      matched_keywords: ['Python'],
      match_score: 80,
      ai_classification: 'vaga_ativa',
      ai_score: 78,
      ai_verdict: 'Strong Fit',
      ai_evaluated_at: todayIso,
      auto_promoted: 1,
      job_status: 'interested',
      published_date: todayIso,
      created_at: todayIso,
    };
    const postLowAiScore: RecruiterPost = {
      id: 302,
      portal: 'linkedin_post',
      company: 'Beta Corp',
      title: 'Estágio Angular',
      description: 'Vaga Angular júnior presencial. CV para rh@beta.dev',
      emails: ['rh@beta.dev'],
      matched_keywords: ['Angular'],
      match_score: 45,
      ai_classification: 'vaga_ativa',
      ai_score: 42,
      ai_verdict: 'Weak Fit',
      ai_evaluated_at: todayIso,
      published_date: todayIso,
      created_at: todayIso,
    };
    const postTalentPool: RecruiterPost = {
      id: 303,
      portal: 'linkedin_post',
      company: 'Pool RH',
      title: 'Banco de Talentos Geral',
      description: 'Cadastre seu currículo para futuras vagas em talentos@poolrh.dev',
      emails: ['talentos@poolrh.dev'],
      matched_keywords: [],
      match_score: 10,
      ai_classification: 'banco_talentos',
      ai_score: 25,
      ai_verdict: 'Banco de talentos',
      ai_evaluated_at: todayIso,
      published_date: todayIso,
      created_at: todayIso,
    };
    const nonLinkedInPost: RecruiterPost = {
      id: 304,
      portal: 'freehire-search',
      company: 'FreeHire Inc',
      title: 'Dev Java',
      description: 'Vaga externa com rh@freehire.dev',
      emails: ['rh@freehire.dev'],
      matched_keywords: ['Java'],
      match_score: 90,
      published_date: todayIso,
      created_at: todayIso,
    };
    const noEmailLinkedIn: RecruiterPost = {
      id: 305,
      portal: 'linkedin_post',
      company: 'Sem Email',
      title: 'Dev Go',
      description: 'Vaga Go sem endereço de contato.',
      emails: [],
      matched_keywords: ['Go'],
      match_score: 70,
      published_date: todayIso,
      created_at: todayIso,
    };

    const getPostsSpy = jasmine.createSpy('getRecruiterPosts').and.returnValue(
      of({ total: 5, posts: [postCompatible, postLowAiScore, postTalentPool, nonLinkedInPost, noEmailLinkedIn] })
    );

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
            getRecruiterPosts: getPostsSpy,
          },
        },
        {
          provide: AutoModeService,
          useValue: {
            status: autoStatusSig,
            isRunning: computed(() => Boolean(autoStatusSig()?.running)),
            resultsRefreshTick: refreshTickSig,
            startRecruiters: startAutoSpy,
            cancel: () => {},
          },
        },
      ],
    });

    const fixture = TestBed.createComponent(RecrutadoresComponent);
    const comp = fixture.componentInstance;
    comp.resetSecondaryFilters();
    expect(comp.jobAgeFilter).toBe('');
    comp.autoMinScore = 60;
    comp.onOnlyCvMatchChange(true);
    fixture.detectChanges();

    // Multiplataforma: carrega todos os portais com e-mail sem restringir apenas a linkedin_post
    expect(getPostsSpy).toHaveBeenCalledWith(undefined, false);
    expect(comp.allPosts().map(p => p.id)).toEqual([301, 302, 303, 304]);

    // Ao abrir a tela sem busca/rodada ativa, Atuais encontrados começa vazio (Histórico à direita continua visível, últimas detectadas primeiro)
    expect(comp.hasSearched()).toBeFalse();
    expect(comp.filteredPosts()).toEqual([]);
    expect(comp.relevantHistoryPosts().map(p => p.id)).toEqual([302, 301]);

    // Ao iniciar Modo Automático (picking_keywords), não vaza posts antigos antes da rodada retornar IDs
    comp.triggerAutoMode();
    fixture.detectChanges();
    expect(startAutoSpy).toHaveBeenCalled();
    expect(comp.onlyCvMatch()).toBeTrue();
    expect(comp.jobAgeFilter).toBe('');
    expect(comp.filteredPosts()).toEqual([]);

    // Rodada 1 conclui coleta multiplataforma (LinkedIn + FreeHire)
    autoStatusSig.set({
      running: true,
      run_id: 'run-multi-1',
      round: 1,
      mode: 'recruiters',
      keywords: ['Ruby'],
      phase: 'screening',
      round_post_ids: [301, 302, 303, 304],
    });
    refreshTickSig.update(v => v + 1);
    fixture.detectChanges();

    expect(comp.filterText).toBe('Ruby');
    expect(comp.filteredPosts().map(p => p.id)).toEqual([301, 304]);
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Em Me Interessam');

    // Desmarcando onlyCvMatch, todos os posts da rodada atual (LinkedIn + FreeHire) ficam visíveis
    comp.onOnlyCvMatchChange(false);
    fixture.detectChanges();
    expect(comp.filteredPosts().map(p => p.id)).toEqual([301, 302, 304, 303]);
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Banco de talentos');

    // Ao iniciar Rodada 2 com apenas [304], Atuais encontrados mostra exclusivamente a Rodada 2
    autoStatusSig.set({
      running: true,
      run_id: 'run-multi-1',
      round: 2,
      mode: 'recruiters',
      keywords: ['Java'],
      phase: 'searching',
      round_post_ids: [304],
    });
    refreshTickSig.update(v => v + 1);
    fixture.detectChanges();
    expect(comp.filteredPosts().map(p => p.id)).toEqual([304]);

    fixture.destroy();
  });

  it('renders two columns without card title envelope icon and supports batch Descartadas cleanup in history', () => {
    localStorage.removeItem(RECRUITER_STATE_STORAGE_KEY);
    const localIsoOffset = (deltaDays: number) => {
      const d = new Date();
      d.setDate(d.getDate() + deltaDays);
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      return `${y}-${m}-${day}`;
    };
    const today = localIsoOffset(0);
    const fourDaysAgo = localIsoOffset(-4);

    const postHighAngular: RecruiterPost = {
      id: 401,
      portal: 'linkedin_post',
      company: 'Angular Labs',
      title: 'Frontend Angular Sênior',
      description: 'Vaga Angular com rx@angularlabs.dev',
      emails: ['rx@angularlabs.dev'],
      matched_keywords: ['Angular'],
      match_score: 90,
      ai_classification: 'vaga_ativa',
      ai_score: 84,
      ai_verdict: 'Forte aderência',
      ai_evaluated_at: `${today}T09:00:00Z`,
      published_date: today,
      created_at: `${today}T09:00:00Z`,
    };
    const postLowScorePython: RecruiterPost = {
      id: 402,
      portal: 'linkedin_post',
      company: 'Legacy Corp',
      title: 'Dev Cobol / Python',
      description: 'Vaga com nota baixa rh@legacy.dev',
      emails: ['rh@legacy.dev'],
      matched_keywords: ['Python'],
      match_score: 40,
      ai_classification: 'vaga_ativa',
      ai_score: 32,
      ai_verdict: 'Baixa compatibilidade',
      ai_evaluated_at: `${today}T09:10:00Z`,
      published_date: today,
      created_at: `${today}T09:10:00Z`,
    };
    const postMidReact: RecruiterPost = {
      id: 403,
      portal: 'linkedin_post',
      company: 'React House',
      title: 'Engenheiro React Pleno',
      description: 'Vaga de frontend moderno com Redux e Next.js jobs@reacthouse.dev',
      emails: ['jobs@reacthouse.dev'],
      matched_keywords: ['React'],
      match_score: 70,
      ai_classification: 'vaga_ativa',
      ai_score: 52,
      ai_verdict: 'Moderada',
      ai_evaluated_at: `${fourDaysAgo}T15:00:00Z`,
      published_date: fourDaysAgo,
      created_at: `${fourDaysAgo}T15:00:00Z`,
    };
    const postNonJob: RecruiterPost = {
      id: 404,
      portal: 'linkedin_post',
      company: 'Blog Tech',
      title: 'Dicas de carreira',
      description: 'Artigo com contato@blogtech.dev',
      emails: ['contato@blogtech.dev'],
      matched_keywords: ['Angular'],
      match_score: 20,
      ai_classification: 'nao_e_vaga',
      ai_score: 10,
      ai_evaluated_at: `${today}T08:00:00Z`,
      published_date: today,
      created_at: `${today}T08:00:00Z`,
    };
    const postUntriaged: RecruiterPost = {
      id: 405,
      portal: 'linkedin_post',
      company: 'Pendente Tech',
      title: 'Dev Angular Pleno',
      description: 'Ainda sem triagem dev@pendente.dev',
      emails: ['dev@pendente.dev'],
      matched_keywords: ['Angular'],
      match_score: 80,
      published_date: today,
      created_at: `${today}T09:20:00Z`,
    };

    const dismissBatchSpy = jasmine
      .createSpy('dismissRecruiterPostsBatch')
      .and.callFake((ids: number[]) =>
        of({ ok: true, dismissed_ids: ids, dismissed_count: ids.length })
      );
    const interestedSpy = jasmine
      .createSpy('markRecruiterPostInterested')
      .and.returnValue(of({ ok: true, post_id: 403, job_id: 'recruiter://post/403' }));

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
            getRecruiterPosts: () =>
              of({
                total: 5,
                posts: [postHighAngular, postLowScorePython, postMidReact, postNonJob, postUntriaged],
              }),
            dismissRecruiterPostsBatch: dismissBatchSpy,
            markRecruiterPostInterested: interestedSpy,
          },
        },
        {
          provide: AutoModeService,
          useValue: {
            status: signal({ running: false, mode: 'recruiters', keywords: [] }),
            isRunning: signal(false),
            resultsRefreshTick: signal(0),
            startRecruiters: () => {},
            cancel: () => {},
          },
        },
      ],
    });

    const fixture = TestBed.createComponent(RecrutadoresComponent);
    const comp = fixture.componentInstance;
    comp.filterText = 'Angular';
    comp.state.hasSearched.set(true);
    comp.state.jobAgeFilter.set('1');
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;

    // 1. Ícone bi-envelope-at removido do h2 do card (.filter-console)
    expect(el.querySelector('.filter-console h2 .bi-envelope-at')).toBeNull();
    expect(el.querySelector('.filter-console h2')?.textContent?.trim()).toBe('Recrutadores');

    // 2. Grid de duas colunas: Atuais encontrados (esquerda) e Histórico de vagas relevantes (direita)
    expect(el.querySelector('.recruiters-columns .posts-list-section')).not.toBeNull();
    expect(el.querySelector('.recruiters-columns .history-list-section')).not.toBeNull();
    expect(el.textContent).toContain('Atuais encontrados');
    expect(el.textContent).toContain('Histórico de vagas relevantes');

    // Esquerda obedece busca atual ('Angular' + 24h); direita acumula todas as vaga_ativa triadas (mais recentes detectadas primeiro por padrão)
    expect(comp.filteredPosts().map(p => p.id)).toEqual([401, 405, 404]);
    expect(comp.relevantHistoryPosts().map(p => p.id)).toEqual([402, 401, 403]);
    expect(filterAndSortRelevantHistoryPosts(comp.allPosts()).map(p => p.id)).toEqual([402, 401, 403]);
    expect(filterAndSortRelevantHistoryPosts(comp.allPosts(), { sortBy: 'score-desc' }).map(p => p.id)).toEqual([401, 403, 402]);

    // Trocar keyword da busca altera apenas a esquerda e preserva o histórico à direita
    comp.filterText = 'Cobol';
    fixture.detectChanges();
    expect(comp.filteredPosts().map(p => p.id)).toEqual([402]);
    expect(comp.relevantHistoryPosts().map(p => p.id)).toEqual([402, 401, 403]);

    // 3. Salvar no histórico ('Me interessa') mantém item na coluna direita com badge 'Em Me Interessam'
    comp.saveAsInterested(postMidReact);
    fixture.detectChanges();
    expect(interestedSpy).toHaveBeenCalledWith(403);
    expect(comp.relevantHistoryPosts().find(p => p.id === 403)?.job_status).toBe('interested');
    expect(el.querySelector('.history-list-section')?.textContent).toContain('Em Me Interessam');

    // 4. Botão Descartar nota < 45 no DOM envia apenas ID 402 para Descartadas
    const confirmSpy = spyOn(window, 'confirm').and.returnValue(true);
    const lowScoreBtn = el.querySelector('.history-list-section .btn-bulk-warning') as HTMLButtonElement;
    expect(lowScoreBtn).not.toBeNull();
    expect(lowScoreBtn.textContent).toContain('(1)');
    lowScoreBtn.click();
    fixture.detectChanges();
    expect(confirmSpy).toHaveBeenCalled();
    expect(dismissBatchSpy).toHaveBeenCalledWith([402]);
    expect(comp.relevantHistoryPosts().map(p => p.id)).toEqual([401, 403]);

    // 5. Selecionar por checkbox / selecionar todas + clique no botão Apagar selecionadas no DOM
    const itemCheckbox = el.querySelector('.history-list-section .history-post-checkbox input[type="checkbox"]') as HTMLInputElement;
    expect(itemCheckbox).not.toBeNull();
    itemCheckbox.click();
    fixture.detectChanges();
    expect(comp.selectedHistoryIdList()).toEqual([401]);

    const selectAllCheckbox = el.querySelector('.history-list-section .history-select-all input[type="checkbox"]') as HTMLInputElement;
    selectAllCheckbox.click();
    fixture.detectChanges();
    expect(comp.allHistorySelected()).toBeTrue();
    expect(comp.selectedHistoryIdList()).toEqual([401, 403]);

    const deleteSelectedBtn = el.querySelector('.history-list-section .btn-bulk-danger') as HTMLButtonElement;
    expect(deleteSelectedBtn.textContent).toContain('(2)');
    deleteSelectedBtn.click();
    fixture.detectChanges();
    expect(dismissBatchSpy).toHaveBeenCalledWith([401, 403]);
    expect(comp.relevantHistoryPosts()).toEqual([]);
    expect(comp.selectedHistoryIdList()).toEqual([]);

    fixture.destroy();
  });

  it('paginates relevant history posts at 10 per page, supports page size change, preserves multi-select across pages, and clamps page after dismiss', () => {
    localStorage.removeItem(RECRUITER_STATE_STORAGE_KEY);
    const posts: RecruiterPost[] = Array.from({ length: 25 }, (_, i) => {
      const id = 1001 + i;
      const day = String(25 - i).padStart(2, '0');
      return {
        id,
        portal: 'linkedin_post',
        company: `Empresa ${id}`,
        title: `Dev Spring Boot #${id}`,
        description: `Vaga Spring Boot #${id} rh${id}@spring.dev`,
        emails: [`rh${id}@spring.dev`],
        matched_keywords: ['Spring Boot'],
        match_score: 90,
        ai_classification: 'vaga_ativa',
        ai_score: 95 - i,
        ai_verdict: 'Strong Fit',
        ai_evaluated_at: `2026-11-${day}T10:00:00Z`,
        published_date: `2026-11-${day}`,
        created_at: `2026-11-${day}T10:00:00Z`,
      };
    });

    const dismissBatchSpy = jasmine
      .createSpy('dismissRecruiterPostsBatch')
      .and.callFake((ids: number[]) =>
        of({ ok: true, dismissed_ids: ids, dismissed_count: ids.length })
      );

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
            getRecruiterPosts: () => of({ total: posts.length, posts }),
            dismissRecruiterPostsBatch: dismissBatchSpy,
          },
        },
        {
          provide: AutoModeService,
          useValue: {
            status: signal({ running: false, mode: 'recruiters', keywords: [] }),
            isRunning: signal(false),
            resultsRefreshTick: signal(0),
            startRecruiters: () => {},
            cancel: () => {},
          },
        },
      ],
    });

    const fixture = TestBed.createComponent(RecrutadoresComponent);
    const comp = fixture.componentInstance;
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(comp.relevantHistoryPosts().length).toBe(25);
    expect(comp.historyPageSize()).toBe(10);
    expect(comp.historyTotalPages()).toBe(3);
    expect(comp.pagedHistoryPosts().map(p => p.id)).toEqual(
      Array.from({ length: 10 }, (_, idx) => 1001 + idx)
    );
    expect(el.querySelectorAll('.history-grid .post-card').length).toBe(10);
    expect(el.querySelector('.history-pagination')?.textContent).toContain('Mostrando 1–10 de 25');
    expect(el.querySelector('.history-pagination')?.textContent).toContain('Página 1 de 3');

    // Avança para a página 2 via botão Próxima
    const nextBtn = Array.from(el.querySelectorAll('.history-pagination .btn-history-page'))
      .find(b => b.textContent?.includes('Próxima')) as HTMLButtonElement;
    expect(nextBtn).toBeDefined();
    nextBtn.click();
    fixture.detectChanges();

    expect(comp.effectiveHistoryPage()).toBe(2);
    expect(comp.pagedHistoryPosts().map(p => p.id)).toEqual(
      Array.from({ length: 10 }, (_, idx) => 1011 + idx)
    );
    expect(el.querySelector('.history-pagination')?.textContent).toContain('Mostrando 11–20 de 25');

    // Altera tamanho da página para 20 -> volta para página 1 e renderiza 20 cards
    const sizeSelect = el.querySelector('.history-page-size-select') as HTMLSelectElement;
    expect(sizeSelect).not.toBeNull();
    sizeSelect.value = '20';
    sizeSelect.dispatchEvent(new Event('change'));
    fixture.detectChanges();

    expect(comp.historyPageSize()).toBe(20);
    expect(comp.effectiveHistoryPage()).toBe(1);
    expect(comp.historyTotalPages()).toBe(2);
    expect(el.querySelectorAll('.history-grid .post-card').length).toBe(20);

    // Selecionar todas marca todo o histórico (25 itens, não só os 20 da página atual)
    const selectAllCheckbox = el.querySelector('.history-list-section .history-select-all input[type="checkbox"]') as HTMLInputElement;
    selectAllCheckbox.click();
    fixture.detectChanges();
    expect(comp.selectedHistoryIdList().length).toBe(25);
    selectAllCheckbox.click();
    fixture.detectChanges();
    expect(comp.selectedHistoryIdList().length).toBe(0);

    // Vai à página 2 (5 itens: 1021..1025), seleciona esses 5 itens e descarta -> página reduz para 1 automaticamente
    comp.nextHistoryPage();
    fixture.detectChanges();
    expect(comp.effectiveHistoryPage()).toBe(2);
    expect(comp.pagedHistoryPosts().map(p => p.id)).toEqual([1021, 1022, 1023, 1024, 1025]);
    const page2Boxes = Array.from(el.querySelectorAll('.history-grid .history-post-checkbox input[type="checkbox"]')) as HTMLInputElement[];
    expect(page2Boxes.length).toBe(5);
    page2Boxes.forEach(cb => cb.click());
    fixture.detectChanges();

    spyOn(window, 'confirm').and.returnValue(true);
    comp.dismissSelectedHistory();
    fixture.detectChanges();

    expect(dismissBatchSpy).toHaveBeenCalledWith([1021, 1022, 1023, 1024, 1025]);
    expect(comp.relevantHistoryPosts().length).toBe(20);
    expect(comp.historyTotalPages()).toBe(1);
    expect(comp.effectiveHistoryPage()).toBe(1);
    expect(comp.pagedHistoryPosts().length).toBe(20);

    fixture.destroy();
  });

  it('orders history by newest detected first, filters by best scores, renders View Post button across all platforms, and saves interested cleanly', () => {
    localStorage.removeItem(RECRUITER_STATE_STORAGE_KEY);
    const posts: RecruiterPost[] = [
      {
        id: 2001,
        portal: 'linkedin_post',
        company: 'OlderHighCo',
        title: 'Dev Java Pleno',
        description: 'Vaga Java Pleno. CV para jobs@olderhigh.dev',
        emails: ['jobs@olderhigh.dev'],
        matched_keywords: ['Java'],
        match_score: 85,
        ai_classification: 'vaga_ativa',
        ai_score: 91,
        ai_verdict: 'Strong Fit',
        ai_summary: 'Ótimo fit Java.',
        ai_evaluated_at: '2026-11-10T10:00:00Z',
        published_date: '2026-11-10',
        created_at: '2026-11-10T09:55:00Z',
        url: 'https://www.linkedin.com/feed/update/urn:li:activity:7990000000000002001/',
      },
      {
        id: 2002,
        portal: 'hn-search',
        company: 'MidHN',
        title: 'Python Data Engineer',
        description: 'Python & SQL. Email hiring@midhn.dev',
        emails: ['hiring@midhn.dev'],
        matched_keywords: ['Python'],
        match_score: 70,
        ai_classification: 'vaga_ativa',
        ai_score: 68,
        ai_verdict: 'Good Fit',
        ai_summary: 'Bom fit.',
        ai_evaluated_at: '2026-11-12T10:00:00Z',
        published_date: '2026-11-12',
        created_at: '2026-11-12T09:55:00Z',
        url: 'https://news.ycombinator.com/item?id=99002002',
      },
      {
        id: 2003,
        portal: 'freehire-search',
        company: 'SAPBusiness',
        title: 'Senior AI Engineer',
        description: 'Senior role. Email careers@sap.com',
        emails: ['careers@sap.com'],
        matched_keywords: ['Python'],
        match_score: 60,
        ai_classification: 'vaga_ativa',
        ai_score: 45,
        ai_verdict: 'Weak Fit',
        ai_summary: 'Senioridade acima do alvo.',
        ai_evaluated_at: '2026-11-14T18:00:00Z',
        published_date: '2026-11-14',
        created_at: '2026-11-14T17:58:00Z',
        url: 'https://freehire.me/jobs/sap-2003',
      },
      {
        id: 2004,
        portal: 'github-vagas',
        company: 'NoUrlOrg',
        title: 'Dev Backend Júnior',
        description: 'Vaga colada sem link externo. Email jobs@nourl.dev',
        emails: ['jobs@nourl.dev'],
        matched_keywords: ['Python'],
        match_score: 65,
        ai_classification: 'vaga_ativa',
        ai_score: 62,
        ai_verdict: 'Good Fit',
        ai_summary: 'Vaga colada.',
        ai_evaluated_at: '2026-11-11T10:00:00Z',
        published_date: '2026-11-11',
        created_at: '2026-11-11T09:55:00Z',
        url: '',
      },
    ];

    const interestedSpy = jasmine
      .createSpy('markRecruiterPostInterested')
      .and.callFake((postId: number) => of({ ok: true, post_id: postId, job_id: `job-${postId}`, url: 'https://freehire.me/jobs/sap-2003' }));

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
            getRecruiterPosts: () => of({ total: posts.length, posts }),
            markRecruiterPostInterested: interestedSpy,
          },
        },
        {
          provide: AutoModeService,
          useValue: {
            status: signal({ running: false, mode: 'recruiters', keywords: [] }),
            isRunning: signal(false),
            resultsRefreshTick: signal(0),
            startRecruiters: () => {},
            cancel: () => {},
          },
        },
      ],
    });

    const fixture = TestBed.createComponent(RecrutadoresComponent);
    const comp = fixture.componentInstance;
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    // Padrão: mais recentes detectadas primeiro (2003 FreeHire -> 2002 HN -> 2004 GitHub -> 2001 LinkedIn)
    expect(comp.historySortBy()).toBe('recent');
    expect(comp.relevantHistoryPosts().map(p => p.id)).toEqual([2003, 2002, 2004, 2001]);

    // Botão proeminente "Ver post original" aparece para todas as plataformas com URL HTTP(S) (e "Sem URL externa" no post sem URL)
    const viewLinks = Array.from(el.querySelectorAll('.history-grid .btn-footer-view-post')) as HTMLAnchorElement[];
    expect(viewLinks.length).toBe(3);
    expect(viewLinks.map(a => a.getAttribute('href'))).toEqual([
      'https://freehire.me/jobs/sap-2003',
      'https://news.ycombinator.com/item?id=99002002',
      'https://www.linkedin.com/feed/update/urn:li:activity:7990000000000002001/',
    ]);
    expect(viewLinks.every(a => (a.textContent || '').includes('Ver post original'))).toBeTrue();
    expect(el.querySelector('.history-grid')?.textContent).toContain('Sem URL externa');

    // Trocar ordenação para "Melhores notas (IA)"
    const selects = el.querySelectorAll('.history-control-select') as NodeListOf<HTMLSelectElement>;
    const sortSelect = selects[0];
    const scoreFilterSelect = selects[1];
    sortSelect.value = 'score-desc';
    sortSelect.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    expect(comp.relevantHistoryPosts().map(p => p.id)).toEqual([2001, 2002, 2004, 2003]);

    // Filtrar pelas melhores notas >= 75
    scoreFilterSelect.value = '75+';
    scoreFilterSelect.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    expect(comp.relevantHistoryPosts().map(p => p.id)).toEqual([2001]);
    expect(el.querySelector('.column-count-badge--history')?.textContent?.trim()).toBe('1/4');

    // Remover 2001 mantendo apenas notas < 75 e verificar empty-state do filtro com reset
    comp.allPosts.set(posts.filter(p => p.id !== 2001));
    fixture.detectChanges();
    expect(el.textContent).toContain('Nenhuma vaga nesta faixa de nota');
    const resetBtn = el.querySelector('.history-list-section .btn-clear-all-filters') as HTMLButtonElement;
    expect(resetBtn).not.toBeNull();
    resetBtn.click();
    fixture.detectChanges();
    expect(comp.historyScoreFilter()).toBe('all');
    expect(comp.relevantHistoryPosts().map(p => p.id)).toEqual([2002, 2004, 2003]);

    // Voltar ordenação para "Mais recentes detectadas" retoma ordem de detecção (2003 -> 2002 -> 2004)
    sortSelect.value = 'recent';
    sortSelect.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    expect(comp.relevantHistoryPosts().map(p => p.id)).toEqual([2003, 2002, 2004]);

    // Salvar em Me Interessam mantém card e metadados de triagem íntegros
    comp.saveAsInterested(posts[2]);
    fixture.detectChanges();
    expect(interestedSpy).toHaveBeenCalledWith(2003);
    const updatedSap = comp.relevantHistoryPosts().find(p => p.id === 2003);
    expect(updatedSap?.job_status).toBe('interested');
    expect(updatedSap?.ai_score).toBe(45);
    expect(updatedSap?.ai_summary).toBe('Senioridade acima do alvo.');

    fixture.destroy();
  });

  it('retains promoted external portals across sections, passes explicit jobAge days, and renders multiplatform breakdown pills in manual and Auto Mode', () => {
    localStorage.removeItem(RECRUITER_STATE_STORAGE_KEY);
    const localIsoOffset = (deltaDays: number) => {
      const d = new Date();
      d.setDate(d.getDate() + deltaDays);
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      return `${y}-${m}-${day}`;
    };

    const today = localIsoOffset(0);
    const fiveDaysAgo = localIsoOffset(-5);
    const twelveDaysAgo = localIsoOffset(-12);

    const posts: RecruiterPost[] = [
      {
        id: 3001,
        portal: 'linkedin_post',
        company: 'LinkedToday',
        title: 'Python Engineer',
        description: 'Python role today. CV para li@today.dev',
        emails: ['li@today.dev'],
        matched_keywords: ['Python'],
        match_score: 85,
        ai_classification: 'vaga_ativa',
        ai_score: 84,
        ai_verdict: 'Strong Fit',
        ai_evaluated_at: `${today}T10:00:00Z`,
        published_date: today,
        created_at: `${today}T09:50:00Z`,
        url: 'https://www.linkedin.com/feed/update/urn:li:activity:7990000000000003001/',
      },
      {
        id: 3002,
        portal: 'freehire-search',
        company: 'FreeHireFiveDays',
        title: 'Python Platform Engineer',
        description: 'Python & FastAPI. Email fh@five.dev',
        emails: ['fh@five.dev'],
        matched_keywords: ['Python'],
        match_score: 80,
        ai_classification: 'vaga_ativa',
        ai_score: 88,
        ai_verdict: 'Strong Fit',
        ai_evaluated_at: `${fiveDaysAgo}T10:00:00Z`,
        published_date: fiveDaysAgo,
        created_at: `${fiveDaysAgo}T09:50:00Z`,
        job_status: 'interested',
        auto_promoted: 1,
        url: 'https://freehire.me/jobs/py-3002',
      },
      {
        id: 3003,
        portal: 'solides-search',
        company: 'SolidesTwelveDays',
        title: 'Dev Python Sênior',
        description: 'Python e Docker. Envie CV para rh@solides3003.dev',
        emails: ['rh@solides3003.dev'],
        matched_keywords: ['Python'],
        match_score: 75,
        ai_classification: 'vaga_ativa',
        ai_score: 79,
        ai_verdict: 'Good Fit',
        ai_evaluated_at: `${twelveDaysAgo}T10:00:00Z`,
        published_date: twelveDaysAgo,
        created_at: `${twelveDaysAgo}T09:50:00Z`,
        job_status: 'interested',
        auto_promoted: 1,
        url: 'https://vagas.solides.com.br/vaga/3003',
      },
      {
        id: 3004,
        portal: 'hn-search',
        company: 'HNOld',
        title: 'Backend Python',
        description: 'Python distributed. Email jobs@hn3004.dev',
        emails: ['jobs@hn3004.dev'],
        matched_keywords: ['Python'],
        match_score: 70,
        ai_classification: 'vaga_ativa',
        ai_score: 76,
        ai_verdict: 'Good Fit',
        ai_evaluated_at: `${twelveDaysAgo}T08:00:00Z`,
        published_date: twelveDaysAgo,
        created_at: `${twelveDaysAgo}T07:50:00Z`,
        job_status: 'interested',
        auto_promoted: 1,
        url: 'https://news.ycombinator.com/item?id=3004',
      },
    ];

    const manualBreakdown = {
      linkedin_post: { fetched: 3, matched: 1, errors: 0, last_error: null },
      'freehire-search': { fetched: 15, matched: 1, errors: 0, last_error: null },
      'solides-search': { fetched: 8, matched: 1, errors: 0, last_error: null },
      'hn-search': { fetched: 5, matched: 1, errors: 0, last_error: null },
    };

    const syncSpy = jasmine.createSpy('syncRecruiterPosts').and.callFake(() =>
      of({
        scanned: 31,
        posts_with_email: 4,
        synced: 4,
        matched_post_ids: [3001, 3002, 3003, 3004],
        collected_post_ids: [3001, 3002, 3003, 3004],
        portal_breakdown: manualBreakdown,
        warnings: [],
      })
    );

    const autoStatusSig = signal<any>({
      running: false,
      mode: 'recruiters',
      keywords: [],
      round_post_ids: [],
      round_portal_breakdown: null,
      round_warnings: [],
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
            getRecruiterPosts: () => of({ total: posts.length, posts }),
            syncRecruiterPosts: syncSpy,
          },
        },
        {
          provide: AutoModeService,
          useValue: {
            status: autoStatusSig,
            isRunning: computed(() => !!autoStatusSig()?.running),
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

    // Default jobAgeFilter is '' -> calls sync without { days } and shows promoted external portals in História
    expect(comp.jobAgeFilter).toBe('');
    expect(comp.relevantHistoryPosts().map(p => p.id).sort()).toEqual([3001, 3002, 3003, 3004]);

    comp.filterText = 'Python';
    comp.onSearch();
    fixture.detectChanges();

    expect(syncSpy).toHaveBeenCalledWith('Python');
    expect(comp.filteredPosts().map(p => p.id).sort()).toEqual([3001, 3002, 3003, 3004]);

    const el = fixture.nativeElement as HTMLElement;
    const manualPills = Array.from(el.querySelectorAll('.multiplatform-radar-bar .multiplatform-pill'));
    expect(manualPills.length).toBeGreaterThanOrEqual(4);
    expect(el.querySelector('.multiplatform-radar-bar')?.textContent).toContain('FreeHire');
    expect(el.querySelector('.multiplatform-radar-bar')?.textContent).toContain('Sólides');

    // Quick portal filter via pill toggle isolates solides-search in Atuais encontrados while preserving full Histórico
    comp.togglePortalQuickFilter('solides-search');
    fixture.detectChanges();
    expect(comp.portalFilter).toBe('solides-search');
    expect(comp.filteredPosts().map(p => p.id)).toEqual([3003]);
    expect(comp.relevantHistoryPosts().map(p => p.id).sort()).toEqual([3001, 3002, 3003, 3004]);

    comp.togglePortalQuickFilter('solides-search');
    fixture.detectChanges();
    expect(comp.portalFilter).toBe('');
    expect(comp.filteredPosts().length).toBe(4);

    // Explicit jobAgeFilter '1' and '7' pass { days: 1 } / { days: 7 } and narrow filteredPosts
    comp.jobAgeFilter = '1';
    comp.onSearch();
    fixture.detectChanges();
    expect(syncSpy).toHaveBeenCalledWith('Python', { days: 1 });
    expect(comp.filteredPosts().map(p => p.id)).toEqual([3001]);

    comp.jobAgeFilter = '7';
    comp.onSearch();
    fixture.detectChanges();
    expect(syncSpy).toHaveBeenCalledWith('Python', { days: 7 });
    expect(comp.filteredPosts().map(p => p.id).sort()).toEqual([3001, 3002]);

    comp.jobAgeFilter = '';
    fixture.detectChanges();
    expect(comp.filteredPosts().length).toBe(4);

    // Auto Mode telemetry updates .multiplatform-radar-bar dynamically
    autoStatusSig.set({
      running: true,
      mode: 'recruiters',
      run_id: 'auto-mp-1',
      round: 2,
      keywords: ['Python'],
      phase: 'screening',
      round_post_ids: [3002, 3003],
      round_portal_breakdown: {
        'freehire-search': { fetched: 12, matched: 1, errors: 0, last_error: null },
        'solides-search': { fetched: 9, matched: 1, errors: 0, last_error: null },
        'github-vagas': { fetched: 0, matched: 0, errors: 1, last_error: 'timeout' },
      },
      round_warnings: ['github-vagas: timeout'],
    });
    fixture.detectChanges();

    expect(comp.activePortalBreakdown()?.['solides-search']?.matched).toBe(1);
    const autoPills = Array.from(el.querySelectorAll('.multiplatform-radar-bar .multiplatform-pill'));
    expect(autoPills.length).toBe(5);
    expect(el.querySelector('.multiplatform-radar-bar')?.textContent).toContain('GitHub');

    fixture.destroy();
    localStorage.removeItem(RECRUITER_STATE_STORAGE_KEY);
  });
});
