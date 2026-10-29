export interface Vaga {
  id?: string;
  url: string;
  title: string;
  company: string;
  location?: string;
  country_code?: string;
  portal?: string;
  date?: string;
  description?: string;
  workplace_type?: 'remote' | 'hybrid' | 'on_site' | string;
  seniority?: string;
  contract?: string;
  salary?: string;
  screening?: {
    score?: number;
    verdict?: string;
    summary?: string;
    error?: string;
  };
  screening_error?: string;
  signals?: {
    warnings?: string[];
  };
}

export interface ProfileResponse {
  schema: Array<{ title: string; fields: any[] }>;
  answers: Record<string, any>;
  files: {
    cv?: Array<{ name: string; size: number }>;
    linkedin?: Array<{ name: string; size: number }>;
  };
  privacy: {
    status: 'privado' | 'publico' | 'local' | 'outro' | 'desconhecido';
    repo?: string;
  };
  ready: boolean;
  profile: string;
  report?: string;
}

export interface SettingsResponse {
  provider: string;
  model: string;
  models: string[];
  providers: Array<{ id: string; name: string }>;
  has_key: boolean;
  consent: boolean;
}

export interface EvolutionResponse {
  version: number;
  updated_at: string;
  applications: Record<string, any>;
}
