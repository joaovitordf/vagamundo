import {
  AVAILABLE_PORTALS,
  FIT_THRESHOLDS,
  PORTAL_LABELS,
  formatDisplayDate,
  getPortalDisplayName,
  getPrimaryEmail,
  isWithinDateRange,
  isWithinDays,
  matchesRegionFilter,
  matchesScoreFilter,
  matchesTextFilter,
  normalizeWorkModel,
  parseCalendarDateMs,
  resolveEffectiveWorkModel,
  resolveGeo,
} from './job-filters.util';

describe('job-filters.util', () => {
  it('lists the 24 real installed portals without phantom europa entry', () => {
    expect(AVAILABLE_PORTALS.length).toBe(24);
    expect(AVAILABLE_PORTALS.some(p => p.id === 'europa')).toBeFalse();
  });

  it('normalizes work model variants uniformly', () => {
    expect(normalizeWorkModel('on_site')).toBe('on-site');
    expect(normalizeWorkModel('on-site')).toBe('on-site');
    expect(normalizeWorkModel('Presencial')).toBe('on-site');
    expect(normalizeWorkModel('remoto')).toBe('remote');
    expect(normalizeWorkModel('Hybrid')).toBe('hybrid');
    expect(normalizeWorkModel('')).toBe('none');
    expect(normalizeWorkModel(null)).toBe('none');
  });

  it('resolves Brazilian cities without colliding with Portugal substrings', () => {
    const poa = resolveGeo({ location: 'Porto Alegre - RS', portal: 'gupy-search' });
    expect(poa.countryCode).toBe('BR');
    expect(poa.code).toBe('RS');

    const braganca = resolveGeo({ location: 'Bragança Paulista - SP', portal: 'vagas-search' });
    expect(braganca.countryCode).toBe('BR');
    expect(braganca.code).toBe('SP');

    const portoPt = resolveGeo({ location: 'Porto, Portugal', portal: 'linkedin-search' });
    expect(portoPt.countryCode).toBe('PT');
    expect(portoPt.scope).toBe('europa');

    const warsaw = resolveGeo({ location: 'Warszawa (Mazowieckie)', portal: 'freehire-search' });
    expect(warsaw.countryCode).toBe('PL');
    expect(warsaw.scope).toBe('europa');
  });

  it('matches region filter including standalone remote filter', () => {
    const remoteBr = resolveGeo({ location: 'Remoto - Brasil', workplace_type: 'remote', portal: 'remotar-search' });
    const onsiteBr = resolveGeo({ location: 'São Paulo - SP', workplace_type: 'on_site', portal: 'gupy-search' });
    expect(matchesRegionFilter(remoteBr, 'remote')).toBeTrue();
    expect(matchesRegionFilter(onsiteBr, 'remote')).toBeFalse();
    expect(matchesRegionFilter(remoteBr, 'brasil')).toBeTrue();
  });

  it('validates calendar dates and day windows accurately', () => {
    expect(parseCalendarDateMs('2026-02-30')).toBeNull();
    expect(parseCalendarDateMs('')).toBeNull();

    const refNow = new Date(2026, 10, 12, 12, 0, 0); // 2026-11-12 local
    expect(isWithinDays('2026-11-12', 1, refNow)).toBeTrue();
    expect(isWithinDays('2026-11-05', 7, refNow)).toBeTrue();
    expect(isWithinDays('2026-11-04', 7, refNow)).toBeFalse();
    expect(isWithinDays(null, 7, refNow)).toBeNull();
  });

  it('uses fallbackQuery only for description-less jobs matching current query', () => {
    expect(
      matchesTextFilter('Dev Senior | Acme | Remote', 'python', {
        hasDescription: false,
        fallbackQuery: 'python',
        lastSearchQuery: 'python',
      })
    ).toBeTrue();

    expect(
      matchesTextFilter('Dev Senior | Acme | Remote', 'go', {
        hasDescription: false,
        fallbackQuery: 'python',
        lastSearchQuery: 'go',
      })
    ).toBeFalse();
  });

  it('filters scores including 75+ high threshold and score 0 edge cases', () => {
    expect(matchesScoreFilter(75, 'high', true)).toBeTrue();
    expect(matchesScoreFilter(74, 'high', true)).toBeFalse();
    expect(matchesScoreFilter(0, 'triadas', true)).toBeTrue();
    expect(matchesScoreFilter(0, 'low', true)).toBeTrue();
    expect(matchesScoreFilter(60, 'med', true)).toBeTrue();
    expect(matchesScoreFilter(null, 'untriaged', false)).toBeTrue();
  });

  it('recognizes github-vagas as Brazil and maps new recruiter portal display names', () => {
    expect(getPortalDisplayName('github-vagas')).toBe('GitHub Vagas BR');
    expect(getPortalDisplayName('remotive-search')).toBe('Remotive');
    const gh = resolveGeo({ location: 'Remoto / Brasil', portal: 'github-vagas', workplace_type: 'remote' });
    expect(gh.countryCode).toBe('BR');
    expect(gh.scope).toBe('brasil');
    expect(gh.isRemote).toBeTrue();
  });

  it('infers effective work model from location, title and remote-only portals when work_model is null', () => {
    expect(resolveEffectiveWorkModel({ work_model: null, location: 'Remoto', portal: 'remotar-search' })).toBe('remote');
    expect(resolveEffectiveWorkModel({ work_model: null, location: 'Quito,', title: 'Hybrid Quito Bilingual SDR', portal: 'remoteok-search' })).toBe('hybrid');
    expect(resolveEffectiveWorkModel({ work_model: null, location: 'San Francisco, CA', title: 'Fazeshift | Senior Engineer | ONSITE', portal: 'hn-search' })).toBe('on-site');

    const intlOnRemotar = resolveGeo({ location: 'Remoto (internacional)', portal: 'remotar-search', work_model: null });
    expect(intlOnRemotar.scope).toBe('global');
    expect(intlOnRemotar.isRemote).toBeTrue();

    const brSuffix = resolveGeo({ location: 'Curitiba, br', portal: 'freehire-search', work_model: null });
    expect(brSuffix.scope).toBe('brasil');
  });

  it('exposes canonical portal registry labels, fit thresholds, dates, and email helpers', () => {
    expect(FIT_THRESHOLDS.high).toBe(75);
    expect(FIT_THRESHOLDS.medium).toBe(60);
    expect(PORTAL_LABELS['eures']).toBe('EURES (Europa)');
    expect(formatDisplayDate('2026-11-12T10:00:00Z')).toBe('12/11/2026');
    expect(getPrimaryEmail({ contacted_email: 'a@x.com', emails: ['b@x.com'] })).toBe('a@x.com');
    expect(getPrimaryEmail({ emails: ['b@x.com'] })).toBe('b@x.com');
    expect(getPrimaryEmail({})).toBeNull();
  });

  it('matches multi-word queries regardless of word order, accents, gender markers, or role prefixes', () => {
    expect(matchesTextFilter('[Remoto] Desenvolvedor(a) Backend Java Júnior', 'Desenvolvedor Java')).toBeTrue();
    expect(matchesTextFilter('Engenharia de Software (Spring Boot)', 'engenharia spring')).toBeTrue();
    expect(matchesTextFilter('Vaga Frontend React Pleno em São Paulo', 'Desenvolvedor React')).toBeTrue();
    expect(matchesTextFilter('Analista de Dados Python | São Paulo', 'python, golang')).toBeTrue();
    expect(matchesTextFilter('Analista de Dados Python', 'Desenvolvedor Java')).toBeFalse();
  });

  it('distinguishes med_plus (60+) from med (60-74)', () => {
    expect(matchesScoreFilter(82, 'med_plus', true)).toBeTrue();
    expect(matchesScoreFilter(65, 'med_plus', true)).toBeTrue();
    expect(matchesScoreFilter(59, 'med_plus', true)).toBeFalse();
    expect(matchesScoreFilter(82, 'med', true)).toBeFalse();
    expect(matchesScoreFilter(65, 'med', true)).toBeTrue();
  });

  it('avoids false Brazilian UF matches on English phrases and uses BR_NACIONAL for generic non-remote BR jobs', () => {
    const remoteUs = resolveGeo({ location: 'Remote (open to US)', portal: 'hn-search' });
    expect(remoteUs.countryCode).toBe('US');
    expect(remoteUs.code).not.toBe('TO');

    const candidateSe = resolveGeo({ location: 'Candidate-se agora', portal: 'linkedin-search' });
    expect(candidateSe.code).not.toBe('SE');

    const brNational = resolveGeo({ location: 'Brasil', portal: 'gupy-search', workplace_type: 'on_site' });
    expect(brNational.countryCode).toBe('BR');
    expect(brNational.code).toBe('BR_NACIONAL');

    const campinas = resolveGeo({ location: 'Campinas, SP', portal: 'gupy-search' });
    expect(campinas.countryCode).toBe('BR');
    expect(campinas.code).toBe('SP');
  });

  it('evaluates date ranges for ISO and BR date formats including custom windows', () => {
    const refNow = new Date(2026, 10, 12, 12, 0, 0);
    expect(isWithinDateRange('10/11/2026', '7d', '', '', refNow)).toBeTrue();
    expect(isWithinDateRange('01/11/2026', '7d', '', '', refNow)).toBeFalse();
    expect(isWithinDateRange('2026-11-08', 'custom', '2026-11-05', '2026-11-10', refNow)).toBeTrue();
    expect(isWithinDateRange('04/11/2026', 'custom', '2026-11-05', '2026-11-10', refNow)).toBeFalse();
  });
});
