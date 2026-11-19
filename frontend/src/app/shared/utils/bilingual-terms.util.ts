export type SearchLanguageMode = 'both' | 'en' | 'pt';

export interface BilingualTermEntry {
  en?: string | null;
  pt?: string | null;
}

export interface BilingualExpansionResult {
  terms: string[];
  addedVariant: string | null;
  matchedInDictionary: boolean;
}

interface DictionaryPair {
  readonly pt: string;
  readonly en: string;
  readonly ptAliases?: readonly string[];
  readonly enAliases?: readonly string[];
}

/**
 * Catálogo whitelabel bidirecional (PT <-> EN) de áreas e especialidades comuns em anúncios de vaga.
 * Serve como camada instantânea (0 ms); termos fora daqui podem ser resolvidos automaticamente pela IA configurada.
 */
const BILINGUAL_PAIRS: readonly DictionaryPair[] = [
  // IA, Dados & Visão Computacional
  { pt: 'Visão Computacional', en: 'Computer Vision', ptAliases: ['visao por computador'] },
  { pt: 'Inteligência Artificial', en: 'Artificial Intelligence' },
  { pt: 'Aprendizado de Máquina', en: 'Machine Learning', ptAliases: ['aprendizagem de maquina'] },
  { pt: 'Aprendizado Profundo', en: 'Deep Learning', ptAliases: ['aprendizagem profunda'] },
  { pt: 'Ciência de Dados', en: 'Data Science', ptAliases: ['cientista de dados'] },
  { pt: 'Engenharia de Dados', en: 'Data Engineering', ptAliases: ['engenheiro de dados'] },
  { pt: 'Análise de Dados', en: 'Data Analytics', ptAliases: ['analista de dados'] },
  { pt: 'Processamento de Linguagem Natural', en: 'NLP', enAliases: ['Natural Language Processing'] },
  { pt: 'Processamento de Imagens', en: 'Image Processing', ptAliases: ['processamento de imagem'] },
  { pt: 'Redes Neurais', en: 'Neural Networks' },
  { pt: 'IA Generativa', en: 'Generative AI', ptAliases: ['inteligencia artificial generativa'] },
  { pt: 'Mineração de Dados', en: 'Data Mining' },
  { pt: 'Inteligência de Negócios', en: 'Business Intelligence' },

  // Engenharia de Software, Cloud, Segurança & Hardware
  { pt: 'Engenharia de Software', en: 'Software Engineering' },
  { pt: 'Arquitetura de Software', en: 'Software Architecture', ptAliases: ['arquiteto de software'] },
  { pt: 'Desenvolvimento Web', en: 'Web Development' },
  { pt: 'Desenvolvimento Mobile', en: 'Mobile Development' },
  { pt: 'Sistemas Embarcados', en: 'Embedded Systems', ptAliases: ['embarcados'] },
  { pt: 'Computação em Nuvem', en: 'Cloud Computing', ptAliases: ['nuvem'] },
  { pt: 'Segurança da Informação', en: 'Cybersecurity', ptAliases: ['ciberseguranca', 'seguranca cibernetica'] },
  { pt: 'Qualidade de Software', en: 'QA', enAliases: ['Quality Assurance'] },
  { pt: 'Testes Automatizados', en: 'Test Automation', ptAliases: ['automacao de testes'] },
  { pt: 'Banco de Dados', en: 'Database', ptAliases: ['bancos de dados'] },
  { pt: 'Microsserviços', en: 'Microservices' },
  { pt: 'Computação Gráfica', en: 'Computer Graphics' },
  { pt: 'Robótica', en: 'Robotics' },
  { pt: 'Automação Industrial', en: 'Industrial Automation' },
  { pt: 'Automação', en: 'Automation' },
  { pt: 'Infraestrutura', en: 'Infrastructure' },
  { pt: 'Redes de Computadores', en: 'Network Engineering' },
  { pt: 'Suporte Técnico', en: 'Technical Support' },
  { pt: 'Sistemas Distribuídos', en: 'Distributed Systems' },

  // Produto, Design, Gestão & Negócios (whitelabel multissetor)
  { pt: 'Gestão de Projetos', en: 'Project Management', ptAliases: ['gerenciamento de projetos'] },
  { pt: 'Gestão de Produto', en: 'Product Management', ptAliases: ['gerenciamento de produto'] },
  { pt: 'Design de Produto', en: 'Product Design' },
  { pt: 'Experiência do Usuário', en: 'UX Design' },
  { pt: 'Análise Financeira', en: 'Financial Analysis' },
  { pt: 'Finanças', en: 'Finance' },
  { pt: 'Contabilidade', en: 'Accounting' },
  { pt: 'Controladoria', en: 'Financial Controlling' },
  { pt: 'Auditoria', en: 'Auditing' },
  { pt: 'Recursos Humanos', en: 'Human Resources' },
  { pt: 'Recrutamento e Seleção', en: 'Talent Acquisition' },
  { pt: 'Marketing Digital', en: 'Digital Marketing' },
  { pt: 'Sucesso do Cliente', en: 'Customer Success' },
  { pt: 'Atendimento ao Cliente', en: 'Customer Support' },
  { pt: 'Vendas', en: 'Sales' },
  { pt: 'Comercial', en: 'Business Development' },
  { pt: 'Operações', en: 'Operations' },
  { pt: 'Cadeia de Suprimentos', en: 'Supply Chain' },
  { pt: 'Logística', en: 'Logistics' },
  { pt: 'Compras', en: 'Procurement' },
  { pt: 'Jurídico', en: 'Legal' },
  { pt: 'Direito', en: 'Law' },
  { pt: 'Direito Tributário', en: 'Tax Law' },
  { pt: 'Conformidade', en: 'Compliance' },
  { pt: 'Engenharia Civil', en: 'Civil Engineering' },
  { pt: 'Engenharia Mecânica', en: 'Mechanical Engineering' },
  { pt: 'Engenharia Elétrica', en: 'Electrical Engineering' },
  { pt: 'Engenharia de Produção', en: 'Industrial Engineering' },
  { pt: 'Engenharia Química', en: 'Chemical Engineering' },
  { pt: 'Agronegócio', en: 'Agribusiness' },
  { pt: 'Agronomia', en: 'Agronomy' },
  { pt: 'Medicina Veterinária', en: 'Veterinary Medicine' },
  { pt: 'Enfermagem', en: 'Nursing' },
  { pt: 'Farmácia', en: 'Pharmacy' },
  { pt: 'Biotecnologia', en: 'Biotechnology' },
];

/**
 * Termos técnicos, linguagens, frameworks e ferramentas universais (idênticos em PT e EN).
 * Evita chamadas desnecessárias à IA e duplicação na string booleana.
 */
const UNIVERSAL_TERMS = new Set<string>([
  'python', 'java', 'javascript', 'typescript', 'golang', 'go', 'rust', 'kotlin', 'swift', 'ruby',
  'php', 'scala', 'elixir', 'dart', 'perl', 'matlab', 'r', 'c', 'c++', 'c#', '.net', 'dotnet',
  'react', 'angular', 'vue', 'nextjs', 'next.js', 'nuxt', 'svelte', 'nodejs', 'node.js', 'node',
  'spring', 'spring boot', 'fastapi', 'django', 'flask', 'laravel', 'rails', 'express', 'nestjs',
  'flutter', 'react native', 'android', 'ios', 'unity', 'unreal',
  'pytorch', 'tensorflow', 'keras', 'opencv', 'yolo', 'scikit-learn', 'pandas', 'numpy', 'spark',
  'pyspark', 'airflow', 'dbt', 'snowflake', 'databricks', 'kafka', 'hadoop', 'mlflow', 'langchain',
  'docker', 'kubernetes', 'terraform', 'ansible', 'jenkins', 'github actions', 'gitlab', 'linux',
  'aws', 'azure', 'gcp', 'google cloud', 'cloudflare', 'nginx', 'devops', 'mlops', 'devsecops',
  'sre', 'ci/cd', 'graphql', 'rest', 'grpc', 'microservices', 'backend', 'frontend', 'fullstack',
  'full stack', 'full-stack', 'back-end', 'front-end', 'tech lead', 'staff', 'principal',
  'sql', 'nosql', 'postgresql', 'postgres', 'mysql', 'mongodb', 'redis', 'elasticsearch', 'oracle',
  'power bi', 'tableau', 'looker', 'excel', 'vba', 'sap', 'abap', 'salesforce', 'hubspot', 'jira',
  'figma', 'photoshop', 'illustrator', 'autocad', 'revit', 'solidworks', 'bim', 'scrum', 'kanban',
  'agile', 'lean', 'six sigma', 'pmo', 'pmp', 'ifrs', 'esg', 'seo', 'sem', 'crm', 'erp', 'bi',
  'ai', 'ia', 'ml', 'dl', 'nlp', 'llm', 'rag', 'qa', 'ux', 'ui', 'ux/ui', 'ui/ux', 'api', 'apis',
  'html', 'css', 'sass', 'tailwind', 'git', 'bash', 'powershell', 'iot', 'fpga', 'vhdl', 'verilog',
]);

export function normalizeBilingualKey(term: string): string {
  return String(term || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

const DICT_INDEX = new Map<string, { pt: string; en: string; sourceLang: 'pt' | 'en' }>();

for (const pair of BILINGUAL_PAIRS) {
  DICT_INDEX.set(normalizeBilingualKey(pair.pt), { pt: pair.pt, en: pair.en, sourceLang: 'pt' });
  for (const alias of pair.ptAliases || []) {
    DICT_INDEX.set(normalizeBilingualKey(alias), { pt: pair.pt, en: pair.en, sourceLang: 'pt' });
  }
  DICT_INDEX.set(normalizeBilingualKey(pair.en), { pt: pair.pt, en: pair.en, sourceLang: 'en' });
  for (const alias of pair.enAliases || []) {
    DICT_INDEX.set(normalizeBilingualKey(alias), { pt: pair.pt, en: pair.en, sourceLang: 'en' });
  }
}

export function isUniversalSearchTerm(term: string): boolean {
  const key = normalizeBilingualKey(term);
  if (!key) return true;
  if (UNIVERSAL_TERMS.has(key)) return true;
  // Siglas técnicas curtas em maiúsculas (ex: RPA, ERP, OCR, ETL, GIS)
  const trimmed = String(term || '').trim();
  if (/^[A-Z0-9+#./-]{2,5}$/.test(trimmed)) return true;
  return false;
}

export function lookupBilingualTerm(
  term: string,
  aiOverrides?: Readonly<Record<string, BilingualTermEntry>>
): { pt: string | null; en: string | null; fromDictionary: boolean } {
  const key = normalizeBilingualKey(term);
  if (!key) return { pt: null, en: null, fromDictionary: false };

  const dictHit = DICT_INDEX.get(key);
  if (dictHit) {
    return { pt: dictHit.pt, en: dictHit.en, fromDictionary: true };
  }

  const aiHit = aiOverrides?.[key];
  if (aiHit) {
    return {
      pt: aiHit.pt ? String(aiHit.pt).trim() : null,
      en: aiHit.en ? String(aiHit.en).trim() : null,
      fromDictionary: false,
    };
  }

  return { pt: null, en: null, fromDictionary: false };
}

export function shouldRequestAiTermExpansion(
  term: string,
  aiOverrides?: Readonly<Record<string, BilingualTermEntry>>
): boolean {
  const trimmed = String(term || '').trim();
  if (trimmed.length < 3) return false;
  if (/\b(?:AND|OR|NOT)\b|[()]/.test(trimmed)) return false;
  if (isUniversalSearchTerm(trimmed)) return false;
  const key = normalizeBilingualKey(trimmed);
  if (!key) return false;
  if (DICT_INDEX.has(key)) return false;
  if (aiOverrides && Object.prototype.hasOwnProperty.call(aiOverrides, key)) {
    return false;
  }
  return true;
}

export function expandTermBilingually(
  term: string,
  mode: SearchLanguageMode = 'both',
  aiOverrides?: Readonly<Record<string, BilingualTermEntry>>
): BilingualExpansionResult {
  const clean = String(term || '').replace(/\s+/g, ' ').trim();
  if (!clean) {
    return { terms: [], addedVariant: null, matchedInDictionary: false };
  }

  const originalKey = normalizeBilingualKey(clean);
  const found = lookupBilingualTerm(clean, aiOverrides);
  const enNorm = found.en ? normalizeBilingualKey(found.en) : '';
  const ptNorm = found.pt ? normalizeBilingualKey(found.pt) : '';

  if (mode === 'en') {
    if (found.en && enNorm !== originalKey) {
      return { terms: [found.en], addedVariant: found.en, matchedInDictionary: found.fromDictionary };
    }
    return { terms: [clean], addedVariant: null, matchedInDictionary: found.fromDictionary };
  }

  if (mode === 'pt') {
    if (found.pt && ptNorm !== originalKey) {
      return { terms: [found.pt], addedVariant: found.pt, matchedInDictionary: found.fromDictionary };
    }
    return { terms: [clean], addedVariant: null, matchedInDictionary: found.fromDictionary };
  }

  // Modo 'both' (PT + EN)
  const variant =
    found.en && enNorm !== originalKey
      ? found.en
      : found.pt && ptNorm !== originalKey
        ? found.pt
        : null;

  if (variant) {
    return {
      terms: [clean, variant],
      addedVariant: variant,
      matchedInDictionary: found.fromDictionary,
    };
  }
  return { terms: [clean], addedVariant: null, matchedInDictionary: found.fromDictionary };
}
