export interface PortalOption {
  id: string;
  name: string;
  category: 'brasil' | 'tech' | 'global' | 'executivo' | 'agro';
  categoryLabel: string;
  badge?: string;
}

export type NormalizedWorkModel = 'remote' | 'hybrid' | 'on-site' | 'none';

export interface GeoResolution {
  scope: 'brasil' | 'europa' | 'global';
  countryCode: string;
  code: string;
  label: string;
  isRemote: boolean;
  remoteBucket: string | null;
}

export interface ActiveGeoFilter {
  type: 'country' | 'uf' | 'remote';
  code: string;
  name: string;
  count: number;
}

export const PORTAL_LABELS: Record<string, string> = {
  'gupy-search': 'Gupy',
  'solides-search': 'Sólides Vagas',
  'vagas-search': 'VAGAS.com',
  'infojobs-search': 'InfoJobs',
  'remotar-search': 'Remotar',
  'greenhouse-search': 'Greenhouse',
  'programathor-search': 'Programathor',
  'geekhunter-search': 'GeekHunter',
  'michaelpage-search': 'Michael Page',
  'roberthalf-search': 'Robert Half',
  'trampos-search': 'Trampos',
  'pcd-search': 'PCD Online',
  'agrobase-search': 'Agrobase',
  'agrosearch-search': 'AGROSearch',
  'digai-search': 'DigAÍ',
  'empregos-search': 'Empregos.com.br',
  'linkedin-search': 'LinkedIn',
  'freehire-search': 'FreeHire',
  'hh-search': 'HeadHunter (hh.ru)',
  'habrcareer-search': 'Habr Career',
  'remoteok-search': 'RemoteOK',
  'jobicy-search': 'Jobicy',
  'hn-search': 'Hacker News (Who is Hiring)',
  'ashby-search': 'Ashby',
  'linkedin_post': 'LinkedIn (Post)',
  'github-vagas': 'GitHub Vagas BR',
  'remotive-search': 'Remotive',
  'jobs': 'Banco Local de Vagas',
  'recruiter_radar': 'Recrutadores',
  'google-careers': 'Google Careers',
  'eures': 'EURES (Europa)',
  'wwr-search': 'We Work Remotely',
  'lever': 'Lever',
};

export const PORTAL_CATEGORIES: Array<{ id: PortalOption['category']; label: string }> = [
  { id: 'brasil', label: 'Portais Brasil' },
  { id: 'tech', label: 'Tecnologia & Inovação' },
  { id: 'global', label: 'Internacional & Remoto Global (Career-Ops)' },
  { id: 'executivo', label: 'Executivo & Especialistas' },
  { id: 'agro', label: 'Agronegócio' },
];

export const AVAILABLE_PORTALS: PortalOption[] = [
  // Portais Brasil (8)
  { id: 'gupy-search', name: 'Gupy', category: 'brasil', categoryLabel: 'Portais Brasil', badge: 'portal.gupy.io' },
  { id: 'solides-search', name: 'Sólides Vagas', category: 'brasil', categoryLabel: 'Portais Brasil', badge: 'PMEs BR' },
  { id: 'vagas-search', name: 'VAGAS.com', category: 'brasil', categoryLabel: 'Portais Brasil' },
  { id: 'infojobs-search', name: 'InfoJobs Brasil', category: 'brasil', categoryLabel: 'Portais Brasil' },
  { id: 'empregos-search', name: 'Empregos.com.br', category: 'brasil', categoryLabel: 'Portais Brasil' },
  { id: 'trampos-search', name: 'Trampos', category: 'brasil', categoryLabel: 'Portais Brasil', badge: 'Freelas & Tech' },
  { id: 'digai-search', name: 'DigAÍ', category: 'brasil', categoryLabel: 'Portais Brasil', badge: 'Entrevista IA' },
  { id: 'pcd-search', name: 'PCD Online', category: 'brasil', categoryLabel: 'Portais Brasil', badge: 'PcD Exclusivo' },

  // Tecnologia & Inovação (5)
  { id: 'geekhunter-search', name: 'GeekHunter', category: 'tech', categoryLabel: 'Tecnologia & Inovação', badge: 'Tech BR' },
  { id: 'programathor-search', name: 'Programathor', category: 'tech', categoryLabel: 'Tecnologia & Inovação', badge: 'Devs BR' },
  { id: 'remotar-search', name: 'Remotar', category: 'tech', categoryLabel: 'Tecnologia & Inovação', badge: '100% Remoto' },
  { id: 'greenhouse-search', name: 'Greenhouse ATS', category: 'tech', categoryLabel: 'Tecnologia & Inovação', badge: 'Global & BR' },
  { id: 'ashby-search', name: 'Ashby ATS', category: 'tech', categoryLabel: 'Tecnologia & Inovação', badge: 'IA & Startups' },

  // Internacional & Remoto Global (7)
  { id: 'remoteok-search', name: 'RemoteOK', category: 'global', categoryLabel: 'Internacional & Global', badge: 'Remoto USD' },
  { id: 'jobicy-search', name: 'Jobicy', category: 'global', categoryLabel: 'Internacional & Global', badge: '100% Remoto' },
  { id: 'hn-search', name: 'Hacker News (HN)', category: 'global', categoryLabel: 'Internacional & Global', badge: 'Who is hiring' },
  { id: 'freehire-search', name: 'FreeHire', category: 'global', categoryLabel: 'Internacional & Global', badge: 'Tech Global' },
  { id: 'linkedin-search', name: 'LinkedIn', category: 'global', categoryLabel: 'Internacional & Global', badge: 'Global' },
  { id: 'hh-search', name: 'HeadHunter (hh.ru)', category: 'global', categoryLabel: 'Internacional & Global', badge: 'Internacional' },
  { id: 'habrcareer-search', name: 'Habr Career', category: 'global', categoryLabel: 'Internacional & Global', badge: 'Tech RU' },

  // Executivo & Especialistas (2)
  { id: 'michaelpage-search', name: 'Michael Page', category: 'executivo', categoryLabel: 'Executivo & Especialistas' },
  { id: 'roberthalf-search', name: 'Robert Half', category: 'executivo', categoryLabel: 'Executivo & Especialistas' },

  // Agronegócio (2)
  { id: 'agrobase-search', name: 'Agrobase', category: 'agro', categoryLabel: 'Agronegócio', badge: 'Agro BR' },
  { id: 'agrosearch-search', name: 'AGROSearch', category: 'agro', categoryLabel: 'Agronegócio', badge: 'Gestão Agro' },
];

export const VALID_PORTAL_IDS = new Set(AVAILABLE_PORTALS.map(p => p.id));

const WORK_MODEL_LABELS: Record<NormalizedWorkModel, string> = {
  remote: 'Remoto',
  hybrid: 'Híbrido',
  'on-site': 'Presencial',
  none: 'Não informado',
};

const BR_PORTALS = new Set([
  'gupy-search', 'solides-search', 'vagas-search', 'infojobs-search', 'remotar-search',
  'programathor-search', 'geekhunter-search', 'trampos-search', 'pcd-search',
  'agrobase-search', 'agrosearch-search', 'digai-search', 'empregos-search',
  'github-vagas',
]);

interface BrUfPattern {
  uf: string;
  name: string;
  cities: string[];
}

const BR_UF_WORDS: BrUfPattern[] = [
  { uf: 'SP', name: 'São Paulo', cities: ['são paulo', 'sao paulo', 'campinas', 'santos', 'sorocaba', 'ribeirão preto', 'ribeirao preto', 'são josé dos campos', 'sao jose dos campos', 'barueri', 'osasco', 'são bernardo', 'sao bernardo', 'jundiaí', 'jundiai', 'bragança paulista', 'braganca paulista'] },
  { uf: 'MG', name: 'Minas Gerais', cities: ['minas gerais', 'belo horizonte', 'uberlândia', 'uberlandia', 'juiz de fora', 'contagem', 'betim'] },
  { uf: 'RJ', name: 'Rio de Janeiro', cities: ['rio de janeiro', 'niterói', 'niteroi', 'petrópolis', 'petropolis'] },
  { uf: 'PR', name: 'Paraná', cities: ['paraná', 'parana', 'curitiba', 'maringá', 'maringa', 'londrina', 'cascavel'] },
  { uf: 'SC', name: 'Santa Catarina', cities: ['santa catarina', 'florianópolis', 'florianopolis', 'joinville', 'blumenau', 'chapecó', 'chapeco', 'itajai', 'itajaí'] },
  { uf: 'RS', name: 'Rio Grande do Sul', cities: ['rio grande do sul', 'porto alegre', 'caxias do sul', 'canoas', 'são leopoldo', 'sao leopoldo', 'novo hamburgo'] },
  { uf: 'BA', name: 'Bahia', cities: ['bahia', 'salvador', 'feira de santana', 'lauro de freitas', 'porto seguro'] },
  { uf: 'PE', name: 'Pernambuco', cities: ['pernambuco', 'recife', 'olinda', 'jaboatao', 'jaboatão'] },
  { uf: 'CE', name: 'Ceará', cities: ['ceará', 'ceara', 'fortaleza'] },
  { uf: 'DF', name: 'Distrito Federal', cities: ['distrito federal', 'brasília', 'brasilia'] },
  { uf: 'GO', name: 'Goiás', cities: ['goiás', 'goias', 'goiânia', 'goiania', 'anápolis', 'anapolis'] },
  { uf: 'ES', name: 'Espírito Santo', cities: ['espírito santo', 'espirito santo', 'vitória', 'vitoria', 'vila velha', 'serra'] },
  { uf: 'MT', name: 'Mato Grosso', cities: ['mato grosso', 'cuiabá', 'cuiaba'] },
  { uf: 'MS', name: 'Mato Grosso do Sul', cities: ['mato grosso do sul', 'campo grande', 'dourados'] },
  { uf: 'AM', name: 'Amazonas', cities: ['amazonas', 'manaus'] },
  { uf: 'PA', name: 'Pará', cities: ['pará', 'belem', 'belém'] },
  { uf: 'RN', name: 'Rio Grande do Norte', cities: ['rio grande do norte', 'natal'] },
  { uf: 'PB', name: 'Paraíba', cities: ['paraíba', 'paraiba', 'joão pessoa', 'joao pessoa', 'campina grande'] },
  { uf: 'AL', name: 'Alagoas', cities: ['alagoas', 'maceió', 'maceio'] },
  { uf: 'SE', name: 'Sergipe', cities: ['sergipe', 'aracaju'] },
  { uf: 'PI', name: 'Piauí', cities: ['piauí', 'piaui', 'teresina'] },
  { uf: 'MA', name: 'Maranhão', cities: ['maranhão', 'maranhao', 'são luís', 'sao luis'] },
  { uf: 'RO', name: 'Rondônia', cities: ['rondônia', 'rondonia', 'porto velho'] },
  { uf: 'TO', name: 'Tocantins', cities: ['tocantins', 'palmas', 'porto nacional'] },
  { uf: 'AC', name: 'Acre', cities: ['acre', 'rio branco'] },
  { uf: 'AP', name: 'Amapá', cities: ['amapá', 'amapa', 'macapá', 'macapa'] },
  { uf: 'RR', name: 'Roraima', cities: ['roraima', 'boa vista'] },
];

interface WorldPattern {
  code: string;
  name: string;
  scope: 'europa' | 'global';
  countries: string[];
  cities: string[];
  ambiguousCities?: string[];
}

const WORLD_PATTERNS: WorldPattern[] = [
  { code: 'DE', name: 'Alemanha', scope: 'europa', countries: ['germany', 'deutschland', 'alemanha'], cities: ['berlin', 'munich', 'münchen', 'frankfurt', 'hamburg', 'stuttgart', 'kiel'] },
  { code: 'NL', name: 'Holanda', scope: 'europa', countries: ['netherlands', 'holanda', 'países baixos'], cities: ['amsterdam', 'rotterdam', 'eindhoven', 'utrecht'] },
  { code: 'GB', name: 'Reino Unido', scope: 'europa', countries: ['united kingdom', 'reino unido', 'england', 'scotland', 'wales', 'uk'], cities: ['london', 'manchester', 'cambridge', 'oxford'] },
  { code: 'ES', name: 'Espanha', scope: 'europa', countries: ['spain', 'espanha', 'españa'], cities: ['madrid', 'barcelona', 'valencia', 'seville', 'bilbao'] },
  { code: 'FR', name: 'França', scope: 'europa', countries: ['france', 'frança'], cities: ['paris', 'lyon', 'toulouse', 'marseille', 'bordeaux'], ambiguousCities: ['nice'] },
  { code: 'IT', name: 'Itália', scope: 'europa', countries: ['italy', 'itália', 'italia'], cities: ['milan', 'milano', 'rome', 'roma', 'turin'] },
  { code: 'PL', name: 'Polônia', scope: 'europa', countries: ['poland', 'polônia', 'polska'], cities: ['warsaw', 'warszawa', 'mazowieckie', 'krakow', 'kraków', 'wroclaw', 'gdansk'] },
  { code: 'CH', name: 'Suíça', scope: 'europa', countries: ['switzerland', 'suíça', 'suica', 'schweiz'], cities: ['zürich', 'zurich', 'geneva'] },
  { code: 'SE', name: 'Suécia', scope: 'europa', countries: ['sweden', 'suécia', 'suecia'], cities: ['stockholm', 'gothenburg', 'göteborg'] },
  { code: 'FI', name: 'Finlândia', scope: 'europa', countries: ['finland', 'finlândia', 'finlandia'], cities: ['helsinki', 'espoo'] },
  { code: 'PT', name: 'Portugal', scope: 'europa', countries: ['portugal'], cities: ['lisbon', 'lisboa', 'coimbra'], ambiguousCities: ['porto', 'braga'] },
  { code: 'IE', name: 'Irlanda', scope: 'europa', countries: ['ireland', 'irlanda'], cities: ['dublin', 'cork', 'galway'] },
  { code: 'BE', name: 'Bélgica', scope: 'europa', countries: ['belgium', 'bélgica', 'belgica'], cities: ['brussels', 'bruxelles'] },
  { code: 'AT', name: 'Áustria', scope: 'europa', countries: ['austria', 'áustria'], cities: ['vienna', 'wien'] },
  { code: 'NO', name: 'Noruega', scope: 'europa', countries: ['norway', 'noruega'], cities: ['oslo', 'bergen'] },
  { code: 'DK', name: 'Dinamarca', scope: 'europa', countries: ['denmark', 'dinamarca'], cities: ['copenhagen'] },
  { code: 'CZ', name: 'República Tcheca', scope: 'europa', countries: ['czech', 'czechia'], cities: ['prague', 'praha'] },
  { code: 'RO', name: 'Romênia', scope: 'europa', countries: ['romania', 'romênia'], cities: ['bucharest'] },
  { code: 'HU', name: 'Hungria', scope: 'europa', countries: ['hungary', 'hungria'], cities: ['budapest'] },
  { code: 'CA', name: 'Canadá', scope: 'global', countries: ['canada', 'canadá'], cities: ['toronto', 'ontario', 'vancouver', 'montreal'] },
  { code: 'US', name: 'Estados Unidos', scope: 'global', countries: ['united states', 'estados unidos', 'usa', 'u.s.'], cities: ['washington', 'd.c.', 'san francisco', 'california', 'new york', 'seattle', 'austin', 'boston', 'chicago', 'texas', 'florida', 'los angeles', 'colorado', 'denver', 'mountain view', 'sunnyvale'] },
  { code: 'RU', name: 'Rússia', scope: 'global', countries: ['russia', 'rússia', 'россия'], cities: ['moscow', 'москва', 'saint petersburg'] },
  { code: 'JP', name: 'Japão', scope: 'global', countries: ['japan', 'japão'], cities: ['tokyo', 'osaka'] },
  { code: 'SG', name: 'Singapura', scope: 'global', countries: ['singapore', 'singapura', 'cingapura'], cities: [] },
  { code: 'AU', name: 'Austrália', scope: 'global', countries: ['australia', 'austrália'], cities: ['sydney', 'melbourne'] },
  { code: 'IN', name: 'Índia', scope: 'global', countries: ['india', 'índia'], cities: ['bangalore', 'bengaluru', 'hyderabad'] },
  { code: 'AR', name: 'Argentina', scope: 'global', countries: ['argentina'], cities: ['buenos aires', 'cordoba'] },
  { code: 'CL', name: 'Chile', scope: 'global', countries: ['chile'], cities: ['santiago'] },
  { code: 'CO', name: 'Colômbia', scope: 'global', countries: ['colombia', 'colômbia'], cities: ['bogota', 'bogotá', 'medellin'] },
  { code: 'MX', name: 'México', scope: 'global', countries: ['mexico', 'méxico'], cities: ['mexico city', 'cdmx', 'guadalajara'] },
  { code: 'UY', name: 'Uruguai', scope: 'global', countries: ['uruguay', 'uruguai'], cities: ['montevideo'] },
  { code: 'IL', name: 'Israel', scope: 'global', countries: ['israel'], cities: ['tel aviv'] },
  { code: 'KR', name: 'Coreia do Sul', scope: 'global', countries: ['south korea', 'coreia do sul'], cities: ['seoul'], ambiguousCities: ['korea'] },
  { code: 'AE', name: 'Emirados Árabes', scope: 'global', countries: ['uae', 'emirates'], cities: ['dubai', 'abu dhabi'] },
];

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function hasTokenMatch(text: string, word: string): boolean {
  if (!text || !word) return false;
  const escaped = escapeRegex(word);
  const re = new RegExp(`(^|[^\\p{L}\\p{N}])${escaped}($|[^\\p{L}\\p{N}])`, 'iu');
  return re.test(text);
}

function toGeoResult(country: WorldPattern, isRemote: boolean): GeoResolution {
  return {
    scope: country.scope,
    countryCode: country.code,
    code: country.code,
    label: country.name,
    isRemote,
    remoteBucket: isRemote ? (country.scope === 'europa' ? 'EU_REMOTE' : 'GLOBAL_REMOTE') : null,
  };
}

export function foldText(s?: string | null): string {
  return String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
}

export function getPortalDisplayName(portal?: string | null): string {
  if (!portal) return 'Portal';
  return PORTAL_LABELS[portal] || portal.replace(/-search$/, '').toUpperCase();
}

const REMOTE_ONLY_PORTALS = new Set([
  'remotar-search',
  'remotive-search',
  'remoteok-search',
  'jobicy-search',
  'wwr-search',
]);

export function normalizeWorkModel(raw?: string | null): NormalizedWorkModel {
  const v = String(raw || '').trim().toLowerCase();
  if (!v || v === 'none' || v === 'não informado' || v === 'nao informado') return 'none';
  if (v === 'remote' || v === 'remoto' || v.includes('remot') || v.includes('home office') || v.includes('teletrabalho')) {
    return 'remote';
  }
  if (v === 'hybrid' || v === 'hibrido' || v === 'híbrido') {
    return 'hybrid';
  }
  if (v === 'on-site' || v === 'on_site' || v === 'onsite' || v === 'presencial') {
    return 'on-site';
  }
  return 'none';
}

export function resolveEffectiveWorkModel(item: {
  work_model?: string | null;
  workplace_type?: string | null;
  location?: string | null;
  title?: string | null;
  portal?: string | null;
}): NormalizedWorkModel {
  const direct = normalizeWorkModel(item.work_model ?? item.workplace_type);
  if (direct !== 'none') return direct;

  const text = `${item.location || ''} ${item.title || ''}`.toLowerCase();
  if (/\b(h[ií]brid[oa]?|hybrid)\b/i.test(text)) return 'hybrid';
  if (/\b(presencial|on[-\s]?site|in[-\s]?office)\b/i.test(text) && !/\b(remot[oaew]*)\b/i.test(text)) {
    return 'on-site';
  }
  if (/\b(remot[oaew]*|home\s*office|teletrabalho|anywhere|worldwide)\b/i.test(text)) return 'remote';

  const portal = String(item.portal || '').toLowerCase();
  if (REMOTE_ONLY_PORTALS.has(portal)) return 'remote';
  return 'none';
}

export function getWorkModelLabel(raw?: string | null): string {
  const norm = normalizeWorkModel(raw);
  return WORK_MODEL_LABELS[norm] || 'Não informado';
}

/**
 * Timestamp (meia-noite UTC) da data de publicação ou null se ausente/inválida.
 * Aceita YYYY-MM-DD (incluindo ISO completo) e DD/MM/YYYY com validação estrita de calendário.
 */
export function parseCalendarDateMs(raw?: string | null): number | null {
  const s = String(raw || '').trim();
  if (!s) return null;

  let year: number;
  let month: number;
  let day: number;

  const iso = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (iso) {
    year = Number(iso[1]);
    month = Number(iso[2]);
    day = Number(iso[3]);
  } else {
    const br = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(s);
    if (!br) return null;
    day = Number(br[1]);
    month = Number(br[2]);
    year = Number(br[3]);
  }

  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  const utcMs = Date.UTC(year, month - 1, day);
  const check = new Date(utcMs);
  if (check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day) {
    return null;
  }
  return utcMs;
}

/** Retorna null quando não há data válida; true/false se dentro de `days` dias corridos até hoje. */
export function isWithinDays(raw: string | null | undefined, days: number, now: Date = new Date()): boolean | null {
  const postedMs = parseCalendarDateMs(raw);
  if (postedMs === null) return null;
  const todayUtcMs = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const diffDays = Math.floor((todayUtcMs - postedMs) / 86400000);
  return diffDays <= days;
}

export function resolveGeo(item: {
  location?: string | null;
  portal?: string | null;
  workplace_type?: string | null;
  work_model?: string | null;
  title?: string | null;
}): GeoResolution {
  const rawLoc = String(item.location || '').trim();
  const loc = rawLoc.toLowerCase();
  const portal = String(item.portal || '').toLowerCase();
  const normWork = resolveEffectiveWorkModel(item);

  const isRemote =
    normWork === 'remote' ||
    /\b(remot\w*|home\s+office|teletrabalho|anywhere|worldwide)\b/i.test(loc);

  const hasExplicitBrasil = /\b(brasil|brazil)\b|(?:,|\/|-)\s*br\b/i.test(loc);
  const hasExplicitInternational = !hasExplicitBrasil && /\b(internacional|international|worldwide|global|anywhere)\b/i.test(loc);

  if (loc.includes('latam') || loc.includes('latin america')) {
    return {
      scope: 'global',
      countryCode: 'LATAM_REMOTE',
      code: 'LATAM_REMOTE',
      label: 'Remoto LATAM',
      isRemote: true,
      remoteBucket: 'GLOBAL_REMOTE',
    };
  }

  if (
    loc.includes('us only') ||
    loc.includes('u.s. only') ||
    loc.includes('us time zones') ||
    loc.includes('united states remote')
  ) {
    return {
      scope: 'global',
      countryCode: 'US',
      code: 'US_REMOTE',
      label: 'Remoto EUA',
      isRemote: true,
      remoteBucket: 'GLOBAL_REMOTE',
    };
  }

  // 1. Países explícitos estrangeiros (quando "Brasil" não está citado explicitamente)
  if (!hasExplicitBrasil) {
    for (const country of WORLD_PATTERNS) {
      if (country.countries.some(w => hasTokenMatch(loc, w))) {
        return toGeoResult(country, isRemote);
      }
    }

    // 2. Cidades estrangeiras não ambíguas
    for (const country of WORLD_PATTERNS) {
      if (country.cities.some(w => hasTokenMatch(loc, w))) {
        return toGeoResult(country, isRemote);
      }
    }
  }

  // 3. Cidades e UFs brasileiras (antes de termos ambíguos como 'porto'/'braga')
  for (const m of BR_UF_WORDS) {
    if (m.cities.some(city => hasTokenMatch(loc, city)) || hasTokenMatch(loc, m.uf.toLowerCase())) {
      return {
        scope: 'brasil',
        countryCode: 'BR',
        code: m.uf,
        label: `${m.name} (${m.uf})`,
        isRemote,
        remoteBucket: isRemote ? 'REMOTO_BR' : null,
      };
    }
  }

  // 4. Cidades estrangeiras ambíguas (ex: Porto, Braga, Nice) apenas se não houve match brasileiro acima
  if (!hasExplicitBrasil && !BR_PORTALS.has(portal)) {
    for (const country of WORLD_PATTERNS) {
      if (country.ambiguousCities?.some(w => hasTokenMatch(loc, w))) {
        return toGeoResult(country, isRemote);
      }
    }
  }

  if (portal === 'eures') {
    return {
      scope: 'europa',
      countryCode: 'DE',
      code: isRemote ? 'EU_REMOTE' : 'DE',
      label: isRemote ? 'Remoto Europa' : 'Europa (EURES)',
      isRemote,
      remoteBucket: isRemote ? 'EU_REMOTE' : null,
    };
  }

  if (hasExplicitInternational) {
    return {
      scope: 'global',
      countryCode: 'GLOBAL_REMOTE',
      code: 'GLOBAL_REMOTE',
      label: 'Remoto Global',
      isRemote: true,
      remoteBucket: 'GLOBAL_REMOTE',
    };
  }

  if (hasExplicitBrasil || BR_PORTALS.has(portal)) {
    return {
      scope: 'brasil',
      countryCode: 'BR',
      code: isRemote ? 'REMOTO_BR' : 'SP',
      label: isRemote ? 'Remoto Brasil' : 'Brasil (Nacional)',
      isRemote,
      remoteBucket: isRemote ? 'REMOTO_BR' : null,
    };
  }

  if (isRemote) {
    return {
      scope: 'global',
      countryCode: 'GLOBAL_REMOTE',
      code: 'GLOBAL_REMOTE',
      label: 'Remoto Global',
      isRemote: true,
      remoteBucket: 'GLOBAL_REMOTE',
    };
  }

  return {
    scope: 'global',
    countryCode: '',
    code: 'UNKNOWN',
    label: rawLoc || 'Localidade não informada',
    isRemote: false,
    remoteBucket: null,
  };
}

export function matchesRegionFilter(geo: GeoResolution, region: string): boolean {
  if (!region) return true;
  if (region === 'remote') return geo.isRemote;
  if (region === 'brasil') return geo.scope === 'brasil';
  if (region === 'estados-unidos') {
    return geo.countryCode === 'US' || geo.remoteBucket === 'US_REMOTE' || geo.label.includes('Estados Unidos');
  }
  if (region === 'europa') return geo.scope === 'europa';
  if (region === 'global') return geo.scope === 'global' || geo.isRemote;
  return true;
}

export function matchesTextFilter(
  haystack: string,
  rawText: string,
  options?: { hasDescription?: boolean; fallbackQuery?: string; lastSearchQuery?: string }
): boolean {
  const trimmed = rawText.trim();
  if (!trimmed) return true;

  const terms = trimmed.split(',').map(t => foldText(t.trim())).filter(Boolean);
  if (!terms.length) return true;

  const hay = foldText(haystack);
  if (terms.some(t => hay.includes(t))) return true;

  const hasDesc = options?.hasDescription ?? true;
  const isCurrentSearchQuery = Boolean(options?.lastSearchQuery && trimmed === options.lastSearchQuery);
  if (!hasDesc && isCurrentSearchQuery && options?.fallbackQuery) {
    const qFold = foldText(options.fallbackQuery);
    return terms.some(t => qFold.includes(t));
  }

  return false;
}

export function matchesScoreFilter(
  score: number | null | undefined,
  filterScore: string,
  evaluated = true
): boolean {
  if (!filterScore) return true;
  const hasScore = score !== null && score !== undefined && !Number.isNaN(Number(score));
  const numScore = hasScore ? Number(score) : null;

  if (filterScore === 'untriaged') return !evaluated || numScore === null;
  if (filterScore === 'triadas') return numScore !== null;
  if (numScore === null) return false;
  if (filterScore === 'high') return numScore >= 75;
  if (filterScore === 'med') return numScore >= 60;
  if (filterScore === 'low') return numScore < 60;
  return true;
}
