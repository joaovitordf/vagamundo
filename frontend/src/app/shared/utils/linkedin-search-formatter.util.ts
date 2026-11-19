import {
  BilingualTermEntry,
  SearchLanguageMode,
  expandTermBilingually,
  normalizeBilingualKey,
  shouldRequestAiTermExpansion,
} from './bilingual-terms.util';

export type LinkedInQueryPreset = 'jobs_lean' | 'hiring_email' | 'jobs_email' | 'terms_only';
export type LinkedInDatePosted = 'past-24h' | 'past-week' | 'past-month';
export type LinkedInDateOption = 'auto' | LinkedInDatePosted | 'all';
export type LinkedInQueryHealthLevel = 'optimal' | 'moderate' | 'heavy';

export interface LinkedInPresetMeta {
  readonly id: LinkedInQueryPreset;
  readonly label: string;
  readonly description: string;
}

export const LINKEDIN_QUERY_PRESETS: readonly LinkedInPresetMeta[] = [
  {
    id: 'jobs_lean',
    label: 'Vagas',
    description: 'Busca enxuta (≤ 6 operadores) otimizada para Publicações do LinkedIn sem travar o filtro.',
  },
  {
    id: 'hiring_email',
    label: 'Hiring + E-mail',
    description: 'Filtra posts com hiring/contratando e e-mail identificado no texto, mantendo poucos operadores.',
  },
  {
    id: 'jobs_email',
    label: 'E-mail / CV',
    description: 'Foca em posts curtos que pedem envio de e-mail ou currículo direto.',
  },
  {
    id: 'terms_only',
    label: 'Só termos',
    description: 'Apenas as palavras-chave limpas (já bilíngues), ideal para colar em Vagas ou editar livremente.',
  },
];

export interface LinkedInQueryHealth {
  operatorCount: number;
  andCount: number;
  charCount: number;
  level: LinkedInQueryHealthLevel;
  label: string;
  warning: string | null;
}

export interface LinkedInSearchBuildOptions {
  filterText?: string | null;
  preset?: LinkedInQueryPreset;
  languageMode?: SearchLanguageMode;
  workModelFilter?: string | null;
  regionFilter?: string | null;
  jobAgeFilter?: string | null;
  includeFilters?: boolean;
  dateOverride?: LinkedInDateOption;
  aiTermOverrides?: Readonly<Record<string, BilingualTermEntry>>;
}

export interface FormattedLinkedInSearch {
  query: string;
  url: string;
  xrayUrl: string;
  datePosted: LinkedInDatePosted | null;
  cleanTerms: string[];
  expandedTerms: string[];
  addedVariants: string[];
  pendingAiTerms: string[];
  hasKeywords: boolean;
  health: LinkedInQueryHealth;
}

const GENERIC_ROLE_PREFIX_RE =
  /^\s*(?:desenvolvedor(?:a)?|engenheir[oa](?:\s+de\s+software)?|analista|programador(?:a)?|developer|software\s+engineer|engineer|pessoa\s+desenvolvedora|especialista)\b\s*/i;

const EXPLICIT_BOOLEAN_RE = /\b(?:AND|OR|NOT)\b|[()]/;

const JOBS_LEAN_BY_LANG: Readonly<Record<SearchLanguageMode, string>> = {
  both: '(vaga OR contratando OR hiring)',
  en: '(hiring OR "open role")',
  pt: '(vaga OR vagas OR contratando)',
};

const HIRING_CLAUSE_BY_LANG: Readonly<Record<SearchLanguageMode, string>> = {
  both: '(hiring OR contratando)',
  en: 'hiring',
  pt: 'contratando',
};

const DIRECT_EMAIL_CLAUSE_BY_LANG: Readonly<Record<SearchLanguageMode, string>> = {
  both: '(email OR "e-mail" OR "@gmail.com")',
  en: '(email OR "@gmail.com" OR cv)',
  pt: '(email OR "e-mail" OR "@gmail.com")',
};

const JOBS_EMAIL_BY_LANG: Readonly<Record<SearchLanguageMode, string>> = {
  both: '(email OR cv OR currículo)',
  en: '(email OR cv OR resume)',
  pt: '(email OR currículo OR cv)',
};

const REMOTE_CLAUSE = '(remoto OR remote)';
const WORK_MODEL_CLAUSES: Readonly<Record<string, string>> = {
  remote: REMOTE_CLAUSE,
  hybrid: '(híbrido OR hybrid)',
  'on-site': '(presencial OR "on-site")',
};

const REGION_CLAUSES: Readonly<Record<string, string>> = {
  brasil: '(Brasil OR Brazil)',
  'estados-unidos': '("United States" OR USA)',
  europa: '(Europe OR Europa)',
  global: '(global OR remote)',
  remote: REMOTE_CLAUSE,
};

/** Remove aspas soltas e prefixos genéricos de cargo para manter termos concisos no LinkedIn. */
export function cleanLinkedInKeywordTerm(rawTerm: string): string {
  const stripped = String(rawTerm || '')
    .replace(/["'()]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (!stripped) return '';
  const withoutPrefix = stripped
    .replace(GENERIC_ROLE_PREFIX_RE, '')
    .replace(/^[\s\-/|·,]+|[\s\-/|·,]+$/g, '');
  return (withoutPrefix || stripped).replace(/\s+/g, ' ').trim();
}

/** Formata um termo individual com aspas quando contém espaços ou separadores compostos. */
export function formatBooleanToken(term: string): string {
  const trimmed = term.trim();
  if (!trimmed) return '';
  if (/^".*"$/.test(trimmed)) return trimmed;
  return /[\s/-]/.test(trimmed) ? `"${trimmed}"` : trimmed;
}

/** Avalia a complexidade da string booleana frente aos limites práticos da aba Publicações do LinkedIn. */
export function analyzeLinkedInQueryHealth(query: string): LinkedInQueryHealth {
  const text = String(query || '').trim();
  const opMatches = text.match(/\b(?:AND|OR|NOT)\b/g) || [];
  const andMatches = text.match(/\bAND\b/g) || [];
  const operatorCount = opMatches.length;
  const andCount = andMatches.length;
  const charCount = text.length;

  if (operatorCount >= 10 || andCount >= 3 || charCount > 190) {
    return {
      operatorCount,
      andCount,
      charCount,
      level: 'heavy',
      label: `${operatorCount} ops · risco de 0 resultados`,
      warning: 'Muitos operadores para Publicações do LinkedIn — simplifique ou tente via Google X-Ray.',
    };
  }
  if (operatorCount >= 7 || charCount > 140) {
    return {
      operatorCount,
      andCount,
      charCount,
      level: 'moderate',
      label: `${operatorCount} ops · moderada`,
      warning: null,
    };
  }
  return {
    operatorCount,
    andCount,
    charCount,
    level: 'optimal',
    label: `${operatorCount} ${operatorCount === 1 ? 'op' : 'ops'}`,
    warning: null,
  };
}

function buildTermsClause(
  rawQuery: string,
  languageMode: SearchLanguageMode,
  aiTermOverrides?: Readonly<Record<string, BilingualTermEntry>>
): {
  clause: string;
  cleanTerms: string[];
  expandedTerms: string[];
  addedVariants: string[];
  pendingAiTerms: string[];
} {
  const raw = String(rawQuery || '').trim();
  if (!raw) {
    return { clause: '', cleanTerms: [], expandedTerms: [], addedVariants: [], pendingAiTerms: [] };
  }

  if (EXPLICIT_BOOLEAN_RE.test(raw)) {
    const collapsed = raw.replace(/\s+/g, ' ').trim();
    return {
      clause: collapsed.startsWith('(') && collapsed.endsWith(')') ? collapsed : `(${collapsed})`,
      cleanTerms: [collapsed],
      expandedTerms: [collapsed],
      addedVariants: [],
      pendingAiTerms: [],
    };
  }

  const seenBase = new Set<string>();
  const cleanTerms: string[] = [];
  for (const part of raw.split(',')) {
    const cleaned = cleanLinkedInKeywordTerm(part);
    if (!cleaned) continue;
    const key = normalizeBilingualKey(cleaned);
    if (!key || seenBase.has(key)) continue;
    seenBase.add(key);
    cleanTerms.push(cleaned);
    if (cleanTerms.length >= 3) break;
  }

  if (cleanTerms.length === 0) {
    return { clause: '', cleanTerms: [], expandedTerms: [], addedVariants: [], pendingAiTerms: [] };
  }

  const expandedTerms: string[] = [];
  const seenExpanded = new Set<string>();
  const addedVariants: string[] = [];
  const pendingAiTerms: string[] = [];

  for (const term of cleanTerms) {
    const expanded = expandTermBilingually(term, languageMode, aiTermOverrides);
    if (shouldRequestAiTermExpansion(term, aiTermOverrides)) {
      pendingAiTerms.push(term);
    }
    if (expanded.addedVariant) {
      addedVariants.push(expanded.addedVariant);
    }
    for (const candidate of expanded.terms) {
      const k = normalizeBilingualKey(candidate);
      if (!k || seenExpanded.has(k)) continue;
      seenExpanded.add(k);
      expandedTerms.push(candidate);
      // Limite rígido de 4 termos no bloco OR para manter a query enxuta no LinkedIn Posts.
      if (expandedTerms.length >= 4) break;
    }
    if (expandedTerms.length >= 4) break;
  }

  if (expandedTerms.length === 1) {
    return {
      clause: formatBooleanToken(expandedTerms[0]),
      cleanTerms,
      expandedTerms,
      addedVariants,
      pendingAiTerms,
    };
  }
  const formatted = expandedTerms.map(formatBooleanToken).filter(Boolean);
  return {
    clause: `(${formatted.join(' OR ')})`,
    cleanTerms,
    expandedTerms,
    addedVariants,
    pendingAiTerms,
  };
}

/** Mapeia o filtro de dias do console para datePosted do LinkedIn (default 'past-week' evita 24h vazias em nichos). */
export function mapJobAgeToLinkedInDatePosted(
  jobAgeFilter?: string | null,
  override: LinkedInDateOption = 'auto'
): LinkedInDatePosted | null {
  if (override === 'all') return null;
  if (override === 'past-24h' || override === 'past-week' || override === 'past-month') {
    return override;
  }
  const normalized = String(jobAgeFilter || '').trim();
  if (!normalized) return 'past-week';
  const days = Number(normalized);
  if (!Number.isFinite(days) || days <= 0) return 'past-week';
  if (days <= 1) return 'past-24h';
  if (days <= 7) return 'past-week';
  return 'past-month';
}

/** Monta a URL completa de busca de publicações no LinkedIn ordenada por mais recentes. */
export function buildLinkedInContentSearchUrl(
  query: string,
  datePosted: LinkedInDatePosted | null = null
): string {
  const safeQuery = String(query || '').trim() || 'vaga';
  let url =
    `https://www.linkedin.com/search/results/content/` +
    `?keywords=${encodeURIComponent(safeQuery)}&sortBy=%22date_posted%22`;
  if (datePosted) {
    url += `&datePosted=%22${datePosted}%22`;
  }
  return url;
}

/** Monta URL de Google X-Ray para posts públicos do LinkedIn (contorna limites booleanos e comerciais do LinkedIn). */
export function buildGoogleXRayLinkedInPostsUrl(
  query: string,
  datePosted: LinkedInDatePosted | null = null,
  preset: LinkedInQueryPreset = 'jobs_lean'
): string {
  const safeQuery = String(query || '').trim() || 'vaga';
  const extra =
    preset === 'jobs_email'
      ? ' ("@" OR "email" OR "cv")'
      : preset === 'hiring_email'
        ? ' "@"'
        : '';
  const fullQ = `site:linkedin.com/posts ${safeQuery}${extra}`;
  let url = `https://www.google.com/search?q=${encodeURIComponent(fullQ)}`;
  if (datePosted === 'past-24h') {
    url += '&tbs=qdr:d';
  } else if (datePosted === 'past-week') {
    url += '&tbs=qdr:w';
  } else if (datePosted === 'past-month') {
    url += '&tbs=qdr:m';
  }
  return url;
}

/** Gera query booleana enxuta + URLs prontas (LinkedIn Posts + Google X-Ray) com expansão bilíngue automática. */
export function buildFormattedLinkedInSearch(opts: LinkedInSearchBuildOptions): FormattedLinkedInSearch {
  const preset: LinkedInQueryPreset = opts.preset || 'jobs_lean';
  const languageMode: SearchLanguageMode = opts.languageMode || 'both';
  const includeFilters = opts.includeFilters === true;

  const { clause: termsClause, cleanTerms, expandedTerms, addedVariants, pendingAiTerms } = buildTermsClause(
    opts.filterText || '',
    languageMode,
    opts.aiTermOverrides
  );

  const parts: string[] = [];
  if (termsClause) {
    parts.push(termsClause);
  }

  if (preset === 'jobs_lean') {
    parts.push(JOBS_LEAN_BY_LANG[languageMode]);
  } else if (preset === 'hiring_email') {
    parts.push(HIRING_CLAUSE_BY_LANG[languageMode]);
    parts.push(DIRECT_EMAIL_CLAUSE_BY_LANG[languageMode]);
  } else if (preset === 'jobs_email') {
    parts.push(JOBS_EMAIL_BY_LANG[languageMode]);
  }

  if (parts.length === 0) {
    parts.push(languageMode === 'en' ? 'hiring' : 'vaga');
  }

  if (includeFilters) {
    const workClause = WORK_MODEL_CLAUSES[String(opts.workModelFilter || '').trim()];
    if (workClause && !parts.includes(workClause)) {
      parts.push(workClause);
    }
    const regionClause = REGION_CLAUSES[String(opts.regionFilter || '').trim()];
    if (regionClause && !parts.includes(regionClause)) {
      parts.push(regionClause);
    }
  }

  const query = parts.join(' AND ');
  const datePosted = mapJobAgeToLinkedInDatePosted(opts.jobAgeFilter, opts.dateOverride || 'auto');
  const url = buildLinkedInContentSearchUrl(query, datePosted);
  const xrayUrl = buildGoogleXRayLinkedInPostsUrl(query, datePosted, preset);
  const health = analyzeLinkedInQueryHealth(query);

  return {
    query,
    url,
    xrayUrl,
    datePosted,
    cleanTerms,
    expandedTerms,
    addedVariants,
    pendingAiTerms,
    hasKeywords: cleanTerms.length > 0,
    health,
  };
}
