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

export interface EvolutionMetrics {
  applications: number;
  applications_with_cv: number;
  applications_with_feedback: number;
  applications_with_questions: number;
  projects_in_source: number;
  linkedin_files: number;
  validation_errors: number;
  validation_warnings: number;
}

export interface EvolutionSummary {
  summary: string;
  metrics: EvolutionMetrics;
  priorities: string[];
}

export interface SourceAuditItem {
  path: string;
  exists: boolean;
  readable: boolean;
  files: number;
  lines: number;
  bytes?: number;
}

export interface EvolutionValidation {
  checked_at: string;
  errors: string[];
  warnings: string[];
  sources: Record<string, SourceAuditItem>;
}

export interface EvolutionResponse {
  version: number;
  updated_at: string;
  applications: Record<string, any>;
  strengths?: string[];
  gaps?: string[];
  actions?: string[];
  projects?: string[];
  evolution?: EvolutionSummary;
  validation?: EvolutionValidation;
}

export interface ApplicationTimelineEvent {
  id?: number;
  application_id?: number;
  stage: string;
  event_date: string;
  feedback?: string;
  questions_and_answers?: string;
  created_at?: string;
}

export interface SearchProgressInfo {
  percent: number;
  completed: number;
  total: number;
  current_portal?: string;
  jobs_found: number;
  portals: Record<string, { status: string; jobs: number; error?: string }>;
}

export interface SearchStatusState {
  running: boolean;
  started?: string;
  error?: string;
  summary?: string;
  progress?: SearchProgressInfo;
}
