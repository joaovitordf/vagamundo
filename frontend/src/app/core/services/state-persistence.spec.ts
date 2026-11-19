import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { RecruiterPost } from '../models/vaga.model';
import { ApiService } from './api.service';
import {
  RECRUITER_STATE_STORAGE_KEY,
  RecruiterStateService,
  filterAndSortRecruiterPosts,
  filterAndSortRelevantHistoryPosts,
} from './recruiter-state.service';
import {
  SEARCH_STATE_STORAGE_KEY,
  SearchStateService,
  localTodayIso,
} from './search-state.service';

describe('State persistence services', () => {
  beforeEach(() => {
    localStorage.removeItem(SEARCH_STATE_STORAGE_KEY);
    localStorage.removeItem(RECRUITER_STATE_STORAGE_KEY);
  });

  afterEach(() => {
    localStorage.removeItem(SEARCH_STATE_STORAGE_KEY);
    localStorage.removeItem(RECRUITER_STATE_STORAGE_KEY);
  });

  it('persists and restores SearchStateService across instances for today', () => {
    const svc = new SearchStateService();
    svc.filterText.set('python, angular');
    svc.filterModel.set('remote');
    svc.filterSort.set('score-desc');
    svc.filterHideUndated.set(true);
    svc.activeSubtab.set('lista');
    svc.markSearchExecuted('python, angular');

    const restored = new SearchStateService();
    expect(restored.filterText()).toBe('python, angular');
    expect(restored.filterModel()).toBe('remote');
    expect(restored.filterSort()).toBe('score-desc');
    expect(restored.filterHideUndated()).toBeTrue();
    expect(restored.activeSubtab()).toBe('lista');
    expect(restored.hasTodaySearch()).toBeTrue();
  });

  it('invalidates stale previous-day search session and strips unknown portals', () => {
    localStorage.setItem(
      SEARCH_STATE_STORAGE_KEY,
      JSON.stringify({
        filterText: 'react',
        selectedPortalIds: ['gupy-search', 'europa'],
        hasSearched: true,
        savedDay: '2020-01-01',
      })
    );

    const restored = new SearchStateService();
    expect(restored.filterText()).toBe('react');
    expect(restored.selectedPortalIds().has('gupy-search')).toBeTrue();
    expect(restored.selectedPortalIds().has('europa')).toBeFalse();
    expect(restored.hasTodaySearch()).toBeFalse();
  });

  it('preserves SearchStateService search session when resetting filters only', () => {
    const svc = new SearchStateService();
    svc.filterModel.set('hybrid');
    svc.filterRegion.set('brasil');
    svc.markSearchExecuted('java');

    svc.resetFilters();
    expect(svc.filterModel()).toBe('');
    expect(svc.filterRegion()).toBe('');
    expect(svc.filterSort()).toBe('date');
    expect(svc.hasTodaySearch()).toBeTrue();
    expect(svc.savedDay()).toBe(localTodayIso());
  });

  it('persists filter preferences in RecruiterStateService without restoring hasSearched across sessions', () => {
    const svc = new RecruiterStateService();
    svc.filterText.set('devops');
    svc.workModelFilter.set('remote');
    svc.regionFilter.set('brasil');
    svc.hideUndated.set(true);
    svc.hasSearched.set(true);
    svc.persist();

    const restored = new RecruiterStateService();
    expect(restored.filterText()).toBe('devops');
    expect(restored.workModelFilter()).toBe('remote');
    expect(restored.regionFilter()).toBe('brasil');
    expect(restored.hideUndated()).toBeTrue();
    expect(restored.hasSearched()).toBeFalse();
    expect(restored.hasActiveKeywordSearch()).toBeFalse();

    restored.hasSearched.set(true);
    expect(restored.hasActiveKeywordSearch()).toBeTrue();

    restored.resetSecondaryFilters();
    expect(restored.filterText()).toBe('devops');
    expect(restored.workModelFilter()).toBe('');
    expect(restored.hideUndated()).toBeFalse();
    expect(restored.hasActiveKeywordSearch()).toBeTrue();
  });

  it('filters and sorts recruiter posts across work_model, undated toggle, AI score and date', () => {
    const posts: RecruiterPost[] = [
      {
        id: 1,
        portal: 'remotar-search',
        title: 'Dev Python Remoto',
        company: 'Acme BR',
        location: 'São Paulo - SP',
        work_model: 'remoto',
        description: 'Vaga python com envio por email',
        emails: ['rh@acme.com'],
        matched_keywords: ['python'],
        match_score: 70,
        ai_classification: 'vaga_ativa',
        ai_score: 82,
        ai_evaluated_at: '2026-11-11',
        published_date: '2026-11-10',
        created_at: '2026-11-10T12:00:00Z',
      },
      {
        id: 2,
        portal: 'freehire-search',
        title: 'Python Engineer',
        company: 'Warsaw Co',
        location: 'Warszawa (Mazowieckie)',
        work_model: 'on_site',
        description: 'Python position in Europe',
        emails: ['jobs@warsaw.eu'],
        matched_keywords: ['python'],
        match_score: 60,
        ai_classification: 'vaga_ativa',
        ai_score: 65,
        ai_evaluated_at: '2026-11-11',
        published_date: undefined,
        created_at: '2026-11-11T12:00:00Z',
      },
      {
        id: 3,
        portal: 'hn-search',
        title: 'Aviso comunidade',
        company: 'HN',
        location: 'Remote',
        work_model: undefined,
        description: 'Python discussion thread',
        emails: ['hi@hn.org'],
        matched_keywords: ['python'],
        match_score: 20,
        ai_classification: 'nao_e_vaga',
        ai_evaluated_at: '2026-11-11',
        published_date: '2026-11-11',
        created_at: '2026-11-11T13:00:00Z',
      },
    ];

    // Filtra por Brasil + Remoto + ocultando sem data + ocultando "Não é vaga"
    const brRemote = filterAndSortRecruiterPosts(posts, {
      hasSearched: true,
      filterText: 'python',
      portalFilter: '',
      workModelFilter: 'remote',
      regionFilter: 'brasil',
      jobAgeFilter: '',
      hideUndated: true,
      scoreFilter: 'high',
      sortBy: 'date',
      onlyCvMatch: false,
      hideNonJobs: true,
    });
    expect(brRemote.map(p => p.id)).toEqual([1]);

    // Sem hideUndated, ordenação por data mantém id=3 (2026-11-11 se não oculto? Wait: non-job fica por último!)
    const sortedByDate = filterAndSortRecruiterPosts(posts, {
      hasSearched: true,
      filterText: 'python',
      portalFilter: '',
      workModelFilter: '',
      regionFilter: '',
      jobAgeFilter: '',
      hideUndated: false,
      scoreFilter: '',
      sortBy: 'date',
      onlyCvMatch: false,
      hideNonJobs: false,
    });
    expect(sortedByDate.map(p => p.id)).toEqual([1, 2, 3]);
  });

  it('derives sidebar recruiterPostsCount strictly from filteredPosts without clobbering on unfiltered fetches', () => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });

    const recruiterState = TestBed.inject(RecruiterStateService);
    const api = TestBed.inject(ApiService);
    const httpMock = TestBed.inject(HttpTestingController);

    // Drena chamadas iniciais do construtor de ApiService
    for (const req of httpMock.match(() => true)) {
      if (req.request.url === '/api/token') req.flush({ token: 'tok' });
      else if (req.request.url === '/api/saved') req.flush({ saved: [] });
      else if (req.request.url === '/api/applications') req.flush({ applications: [] });
      else if (req.request.url === '/api/discarded') req.flush({ discarded: [] });
    }

    recruiterState.filterText.set('Desenvolvedor, Fullstack, Júnior');
    recruiterState.hasSearched.set(true);

    const postsFromDb: RecruiterPost[] = [
      {
        id: 1,
        portal: 'hn-search',
        title: 'Senior Go Backend Engineer',
        company: 'Acme',
        location: 'Boston, MA',
        description: 'Golang distributed systems',
        emails: ['jobs@acme.com'],
        matched_keywords: [],
        match_score: 0,
        created_at: '2026-11-11T10:00:00Z',
      },
      {
        id: 2,
        portal: 'freehire-search',
        title: 'Tech Recruiter Specialist',
        company: 'PeopleOps',
        location: 'Remoto',
        description: 'Recruiting talent',
        emails: ['hr@people.io'],
        matched_keywords: [],
        match_score: 0,
        created_at: '2026-11-11T11:00:00Z',
      },
    ];

    api.getRecruiterPosts().subscribe((res) => {
      recruiterState.allPosts.set(res.posts);
    });

    const req = httpMock.expectOne('/api/recruiters');
    req.flush({ total: 17, posts: postsFromDb });

    expect(api.hasSearchedRecruitersInSession()).toBeTrue();
    // Mesmo com total=17 no payload bruto, nenhum post casa com as palavras-chave -> badge 0
    expect(api.recruiterPostsCount()).toBe(0);

    // Ao mudar o filtro para algo que casa 1 post, o badge reflete 1 automaticamente
    recruiterState.filterText.set('Go Backend');
    expect(api.recruiterPostsCount()).toBe(1);

    // Ao limpar palavras-chave, sidebar zera imediatamente
    recruiterState.filterText.set('');
    expect(api.hasSearchedRecruitersInSession()).toBeFalse();
    expect(api.recruiterPostsCount()).toBe(0);

    httpMock.verify();
  });

  it('persists and clamps continuous auto mode settings across SearchStateService and RecruiterStateService', () => {
    const search = new SearchStateService();
    expect(search.autoContinuous()).toBeTrue();
    expect(search.autoCooldownMinutes()).toBe(5);
    search.autoContinuous.set(false);
    search.autoCooldownMinutes.set(12);
    search.persist();

    const searchRestored = new SearchStateService();
    expect(searchRestored.autoContinuous()).toBeFalse();
    expect(searchRestored.autoCooldownMinutes()).toBe(12);

    localStorage.setItem(
      SEARCH_STATE_STORAGE_KEY,
      JSON.stringify({ autoCooldownMinutes: 999 })
    );
    expect(new SearchStateService().autoCooldownMinutes()).toBe(30);

    const rec = new RecruiterStateService();
    expect(rec.autoContinuous()).toBeTrue();
    expect(rec.autoCooldownSeconds()).toBe(30);
    rec.autoContinuous.set(false);
    rec.autoCooldownSeconds.set(45);
    rec.persist();

    const recRestored = new RecruiterStateService();
    expect(recRestored.autoContinuous()).toBeFalse();
    expect(recRestored.autoCooldownSeconds()).toBe(45);

    localStorage.setItem(
      RECRUITER_STATE_STORAGE_KEY,
      JSON.stringify({ autoCooldownSeconds: 2 })
    );
    expect(new RecruiterStateService().autoCooldownSeconds()).toBe(15);
  });

  it('orders relevant history posts by most recently detected by default, supports best-score sorting/filtering, and persists preferences', () => {
    const olderHighScore: RecruiterPost = {
      id: 10,
      emails: ['rh@oldhigh.dev'],
      title: 'Java Pleno',
      company: 'OldHigh',
      portal: 'linkedin_post',
      url: 'https://www.linkedin.com/feed/update/urn:li:activity:10/',
      description: 'Vaga Java Pleno',
      matched_keywords: ['Java'],
      match_score: 90,
      ai_classification: 'vaga_ativa',
      ai_score: 92,
      ai_verdict: 'Strong Fit',
      ai_evaluated_at: '2026-11-10T10:00:00Z',
      created_at: '2026-11-10T09:50:00Z',
    };
    const midScore: RecruiterPost = {
      id: 20,
      emails: ['jobs@mid.dev'],
      title: 'Python Backend',
      company: 'MidCorp',
      portal: 'hn-search',
      url: 'https://news.ycombinator.com/item?id=20',
      description: 'Python role',
      matched_keywords: ['Python'],
      match_score: 70,
      ai_classification: 'vaga_ativa',
      ai_score: 68,
      ai_verdict: 'Good Fit',
      ai_evaluated_at: '2026-11-12T15:00:00Z',
      created_at: '2026-11-12T14:55:00Z',
    };
    const newestLowScore: RecruiterPost = {
      id: 30,
      emails: ['careers@sap.com'],
      title: 'Senior AI Engineer',
      company: 'SAP',
      portal: 'freehire-search',
      url: 'https://freehire.me/jobs/sap-30',
      description: 'Senior role',
      matched_keywords: ['Python'],
      match_score: 60,
      ai_classification: 'vaga_ativa',
      ai_score: 45,
      ai_verdict: 'Weak Fit',
      ai_evaluated_at: '2026-11-14T21:10:00Z',
      created_at: '2026-11-14T21:05:00Z',
    };

    const recentOrdered = filterAndSortRelevantHistoryPosts([olderHighScore, midScore, newestLowScore]);
    expect(recentOrdered.map(p => p.id)).toEqual([30, 20, 10]);

    const bestScoreOrdered = filterAndSortRelevantHistoryPosts(
      [olderHighScore, midScore, newestLowScore],
      { sortBy: 'score-desc', scoreFilter: 'all' }
    );
    expect(bestScoreOrdered.map(p => p.id)).toEqual([10, 20, 30]);

    const filtered60 = filterAndSortRelevantHistoryPosts(
      [olderHighScore, midScore, newestLowScore],
      { sortBy: 'recent', scoreFilter: '60+' }
    );
    expect(filtered60.map(p => p.id)).toEqual([20, 10]);

    const filtered75 = filterAndSortRelevantHistoryPosts(
      [olderHighScore, midScore, newestLowScore],
      { sortBy: 'recent', scoreFilter: '75+' }
    );
    expect(filtered75.map(p => p.id)).toEqual([10]);

    const svc = new RecruiterStateService();
    expect(svc.historySortBy()).toBe('recent');
    expect(svc.historyScoreFilter()).toBe('all');
    svc.historySortBy.set('score-desc');
    svc.historyScoreFilter.set('75+');
    svc.persist();

    const restored = new RecruiterStateService();
    expect(restored.historySortBy()).toBe('score-desc');
    expect(restored.historyScoreFilter()).toBe('75+');
  });

  it('defaults jobAgeFilter to all dates, migrates legacy 24h flag to empty string, and preserves post-migration choices', () => {
    const fresh = new RecruiterStateService();
    expect(fresh.jobAgeFilter()).toBe('');
    expect(fresh.hasSecondaryFilters()).toBeFalse();

    localStorage.setItem(
      RECRUITER_STATE_STORAGE_KEY,
      JSON.stringify({ jobAgeFilter: '1', jobAgeDefault24hApplied: true })
    );
    const migrated = new RecruiterStateService();
    expect(migrated.jobAgeFilter()).toBe('');
    migrated.persist();
    const savedRaw = JSON.parse(localStorage.getItem(RECRUITER_STATE_STORAGE_KEY) || '{}');
    expect(savedRaw.jobAgeDefaultAllApplied).toBeTrue();

    localStorage.setItem(
      RECRUITER_STATE_STORAGE_KEY,
      JSON.stringify({ jobAgeFilter: '7', jobAgeDefaultAllApplied: true })
    );
    const explicitChoice = new RecruiterStateService();
    expect(explicitChoice.jobAgeFilter()).toBe('7');
    expect(explicitChoice.hasSecondaryFilters()).toBeTrue();

    explicitChoice.resetSecondaryFilters();
    expect(explicitChoice.jobAgeFilter()).toBe('');
    expect(explicitChoice.hasSecondaryFilters()).toBeFalse();
  });
});
