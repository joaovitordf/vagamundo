export interface ScreeningResult {
  score?: number;
  verdict?: string;
  summary?: string;
  ai_model?: string | null;
  error?: string;
  subscores?: {
    technical: number;
    experience: number;
    behavioral: number;
    career: number;
  };
  language_gate?: 'PASS' | 'FLAG' | 'FAIL' | string;
  language_note?: string;
  location_verdict?: 'PASS' | 'FLAG' | 'FAIL' | string;
  strengths?: string[];
  gaps?: string[];
  guard_alert?: string;
}

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
  workplace_type?: 'remote' | 'hybrid' | 'on_site' | 'on-site' | string;
  seniority?: string;
  contract?: string;
  salary?: string;
  query?: string;
  tags?: string[];
  skills?: string[];
  visa_sponsorship?: boolean | string | number;
  screening?: ScreeningResult;
  screening_error?: string;
  signals?: {
    warnings?: string[];
  };
  role?: string;
  posted_date?: string;
  saved_at?: string;
  first_seen?: string;
  created_at?: string;
  updated_at?: string;
  auto_promoted?: boolean | number;
  auto_origin?: string;
  recruiter_emails?: string[];
  claude?: {
    avaliar?: any;
    curriculo?: any;
    carta?: any;
    entrevista?: any;
  };
  pdf_cv?: string;
  pdf_carta?: string;
  pdf_entrevista?: string;
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

export interface ActiveProviderInfo {
  provider: string;
  via?: string;
  label: string;
  short?: string;
  model: string;
  available: boolean;
}

export interface ProviderSettingsItem {
  id: string;
  label: string;
  short?: string;
  model: string;
  default_model: string;
  suggested_models: string[];
  has_key: boolean;
  key_hint: string;
  key_url?: string;
  cli_name?: string;
  cli_found: boolean;
  mode: string;
  base_url: string;
  supports_base_url: boolean;
}

export interface SettingsResponse {
  provider: string;
  consent: boolean;
  active?: ActiveProviderInfo;
  providers: ProviderSettingsItem[];
  // Legacy optional fields for test compatibility
  model?: string;
  models?: string[];
  has_key?: boolean;
}

export interface ApplicationRecord {
  id?: number;
  job_id?: string;
  company: string;
  role?: string;
  title?: string;
  job_title?: string;
  channel?: string;
  portal?: string;
  url?: string;
  job_url?: string;
  source?: string;
  status: string;
  applied_date?: string;
  date?: string;
  created_at?: string;
  job_posted_date?: string;
  posted_date?: string;
  notes?: string;
  contact_channel?: string;
  contacted_email?: string;
  recruiter_emails?: string[];
  pdf_cv?: string;
  pdf_carta?: string;
  timeline?: ApplicationTimelineEvent[];
}

export interface GeneratedDoc {
  id?: number | string;
  name: string;
  kind: 'cv' | 'carta' | 'entrevista' | string;
  path: string;
  date: string;
  web_path?: string;
  company?: string;
  role?: string;
  size_kb?: number;
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

export interface DashboardKpis {
  saved_jobs: number;
  active_applications: number;
  lifetime_applications: number;
  active_processes: number;
  interviews: number;
  offers: number;
  rejected: number;
  discarded_jobs: number;
  conversion_rate: string;
}

export interface DashboardMonthlyPoint {
  month_key: string;
  label: string;
  count: number;
  active: number;
  archived: number;
  is_current?: boolean;
}

export interface DashboardDailyPoint {
  date: string;
  label: string;
  count: number;
  is_today?: boolean;
  is_yesterday?: boolean;
}

export interface DashboardStatusPoint {
  status: string;
  label: string;
  count: number;
  percentage: number;
  color: string;
}

export interface DashboardPortalPoint {
  portal: string;
  label: string;
  count: number;
}

export interface DashboardActivityPoint {
  id?: number;
  company: string;
  role: string;
  portal?: string;
  job_url?: string;
  applied_date: string;
  active_in_list: number;
}

export interface DashboardStats {
  kpis: DashboardKpis;
  monthly_timeline: DashboardMonthlyPoint[];
  daily_timeline: DashboardDailyPoint[];
  status_distribution: DashboardStatusPoint[];
  portal_distribution: DashboardPortalPoint[];
  recent_activity: DashboardActivityPoint[];
}

export interface PreviouslyContactedEmail {
  email: string;
  company: string;
  title: string;
  contacted_at: string;
  job_id?: string;
  application_id?: number;
}

export interface RecruiterPost {
  id: number;
  emails: string[];
  email_context?: string;
  title: string;
  company: string;
  portal: string;
  url?: string;
  location?: string;
  work_model?: string;
  published_date?: string;
  description: string;
  matched_keywords: string[];
  match_score: number;
  job_id?: string;
  dismissed?: number;
  ai_classification?: 'vaga_ativa' | 'banco_talentos' | 'nao_e_vaga' | null;
  ai_score?: number | null;
  ai_verdict?: string | null;
  ai_summary?: string | null;
  ai_best_email?: string | null;
  ai_model?: string | null;
  ai_evaluated_at?: string | null;
  auto_promoted?: number;
  auto_run_id?: string | null;
  contacted_email?: string | null;
  contacted_at?: string | null;
  previously_contacted?: PreviouslyContactedEmail[];
  created_at: string;
}
