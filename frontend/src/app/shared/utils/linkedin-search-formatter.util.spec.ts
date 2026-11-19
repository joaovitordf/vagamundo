import {
  analyzeLinkedInQueryHealth,
  buildFormattedLinkedInSearch,
  buildGoogleXRayLinkedInPostsUrl,
  buildLinkedInContentSearchUrl,
  cleanLinkedInKeywordTerm,
  mapJobAgeToLinkedInDatePosted,
} from './linkedin-search-formatter.util';
import { normalizeBilingualKey } from './bilingual-terms.util';

describe('linkedin-search-formatter.util', () => {
  it('cleans generic Portuguese/English role prefixes from keyword terms', () => {
    expect(cleanLinkedInKeywordTerm('Desenvolvedor Python')).toBe('Python');
    expect(cleanLinkedInKeywordTerm('Engenheira de Software Angular')).toBe('Angular');
    expect(cleanLinkedInKeywordTerm('Software Engineer Backend')).toBe('Backend');
    expect(cleanLinkedInKeywordTerm('Desenvolvedor')).toBe('Desenvolvedor');
  });

  it('builds lean bilingual query for Visão Computacional within safe LinkedIn Posts operator limits', () => {
    const res = buildFormattedLinkedInSearch({
      filterText: 'Visão Computacional',
    });

    expect(res.cleanTerms).toEqual(['Visão Computacional']);
    expect(res.expandedTerms).toEqual(['Visão Computacional', 'Computer Vision']);
    expect(res.addedVariants).toEqual(['Computer Vision']);
    expect(res.pendingAiTerms).toEqual([]);
    expect(res.query).toBe('("Visão Computacional" OR "Computer Vision") AND (vaga OR contratando OR hiring)');
    expect(res.health.operatorCount).toBe(4);
    expect(res.health.level).toBe('optimal');
    expect(res.datePosted).toBe('past-week');
    expect(res.url).toContain('https://www.linkedin.com/search/results/content/?keywords=');
    expect(res.url).toContain('datePosted=%22past-week%22');
    expect(res.xrayUrl).toContain('https://www.google.com/search?q=');
    expect(res.xrayUrl).toContain('tbs=qdr:w');
  });

  it('supports EN-only, PT-only, E-mail/CV lean preset, and AI term overrides', () => {
    const enOnly = buildFormattedLinkedInSearch({
      filterText: 'Visão Computacional',
      preset: 'jobs_lean',
      languageMode: 'en',
    });
    expect(enOnly.query).toBe('"Computer Vision" AND (hiring OR "open role")');
    expect(enOnly.health.operatorCount).toBe(2);

    const ptOnly = buildFormattedLinkedInSearch({
      filterText: 'Visão Computacional',
      preset: 'jobs_lean',
      languageMode: 'pt',
    });
    expect(ptOnly.query).toBe('"Visão Computacional" AND (vaga OR vagas OR contratando)');

    const emailPreset = buildFormattedLinkedInSearch({
      filterText: 'Visão Computacional',
      preset: 'jobs_email',
      languageMode: 'both',
    });
    expect(emailPreset.query).toBe('("Visão Computacional" OR "Computer Vision") AND (email OR cv OR currículo)');
    expect(emailPreset.health.operatorCount).toBe(4);

    const hiringEmailBoth = buildFormattedLinkedInSearch({
      filterText: 'Visão Computacional',
      preset: 'hiring_email',
      languageMode: 'both',
    });
    expect(hiringEmailBoth.query).toBe(
      '("Visão Computacional" OR "Computer Vision") AND (hiring OR contratando) AND (email OR "e-mail" OR "@gmail.com")'
    );
    expect(hiringEmailBoth.health.operatorCount).toBe(6);
    expect(hiringEmailBoth.health.level).toBe('optimal');
    expect(hiringEmailBoth.xrayUrl).toContain(encodeURIComponent('"@"'));

    const hiringEmailEn = buildFormattedLinkedInSearch({
      filterText: 'Visão Computacional',
      preset: 'hiring_email',
      languageMode: 'en',
    });
    expect(hiringEmailEn.query).toBe('"Computer Vision" AND hiring AND (email OR "@gmail.com" OR cv)');
    expect(hiringEmailEn.health.operatorCount).toBe(4);

    const hiringEmailPt = buildFormattedLinkedInSearch({
      filterText: 'Visão Computacional',
      preset: 'hiring_email',
      languageMode: 'pt',
    });
    expect(hiringEmailPt.query).toBe('"Visão Computacional" AND contratando AND (email OR "e-mail" OR "@gmail.com")');
    expect(hiringEmailPt.health.operatorCount).toBe(4);

    // Termo whitelabel fora do dicionário pede expansão IA e passa a usar o override quando disponível
    const unknown = buildFormattedLinkedInSearch({
      filterText: 'Fisioterapia Esportiva',
      preset: 'jobs_lean',
    });
    expect(unknown.pendingAiTerms).toEqual(['Fisioterapia Esportiva']);

    const withAi = buildFormattedLinkedInSearch({
      filterText: 'Fisioterapia Esportiva',
      preset: 'jobs_lean',
      aiTermOverrides: {
        [normalizeBilingualKey('Fisioterapia Esportiva')]: { en: 'Sports Physiotherapy', pt: null },
      },
    });
    expect(withAi.pendingAiTerms).toEqual([]);
    expect(withAi.query).toBe('("Fisioterapia Esportiva" OR "Sports Physiotherapy") AND (vaga OR contratando OR hiring)');
  });

  it('keeps model/region out of Posts query by default and flags overly heavy manual queries', () => {
    const defaultNoFilters = buildFormattedLinkedInSearch({
      filterText: 'Desenvolvedor Python, FastAPI',
      workModelFilter: 'remote',
      regionFilter: 'brasil',
      jobAgeFilter: '7',
    });
    expect(defaultNoFilters.query).toBe('(Python OR FastAPI) AND (vaga OR contratando OR hiring)');
    expect(defaultNoFilters.query).not.toContain('Brasil');
    expect(defaultNoFilters.query).not.toContain('remoto');

    const heavy = analyzeLinkedInQueryHealth(
      '"Visão Computacional" AND (vaga OR vagas OR contratando OR hiring OR oportunidade) AND (email OR "e-mail" OR currículo OR cv) AND (remoto OR remote) AND (Brasil OR Brazil)'
    );
    expect(heavy.level).toBe('heavy');
    expect(heavy.operatorCount).toBeGreaterThanOrEqual(10);
    expect(heavy.warning).toBeTruthy();
  });

  it('preserves explicit user boolean expressions and maps date overrides accurately', () => {
    const explicit = buildFormattedLinkedInSearch({
      filterText: '(Kotlin OR Java) AND NOT Estágio',
      preset: 'terms_only',
    });
    expect(explicit.query).toBe('((Kotlin OR Java) AND NOT Estágio)');
    expect(explicit.pendingAiTerms).toEqual([]);

    expect(mapJobAgeToLinkedInDatePosted('', 'auto')).toBe('past-week');
    expect(mapJobAgeToLinkedInDatePosted('1', 'auto')).toBe('past-24h');
    expect(mapJobAgeToLinkedInDatePosted('3', 'auto')).toBe('past-week');
    expect(mapJobAgeToLinkedInDatePosted('30', 'auto')).toBe('past-month');
    expect(mapJobAgeToLinkedInDatePosted('1', 'past-month')).toBe('past-month');
    expect(mapJobAgeToLinkedInDatePosted('1', 'all')).toBeNull();

    const noDateUrl = buildLinkedInContentSearchUrl('Python', null);
    expect(noDateUrl).not.toContain('datePosted=');
    expect(noDateUrl).toContain('sortBy=%22date_posted%22');

    const xrayDay = buildGoogleXRayLinkedInPostsUrl('"Computer Vision"', 'past-24h', 'jobs_email');
    expect(xrayDay).toContain('site%3Alinkedin.com%2Fposts');
    expect(xrayDay).toContain('&tbs=qdr:d');
  });
});
