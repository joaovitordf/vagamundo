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
  created_at: string;
}
