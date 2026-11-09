-- Schema Vagamundo v2
-- Tabelas centrais do ciclo de busca de vagas, candidaturas e avaliações

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    url TEXT UNIQUE NOT NULL,
    location TEXT,
    portal TEXT,
    source TEXT DEFAULT 'cli',
    work_model TEXT,
    contract_type TEXT,
    seniority TEXT,
    description TEXT,
    posted_date TEXT,
    deadline TEXT,
    first_seen TEXT,
    status TEXT DEFAULT 'new',
    fit TEXT,
    rank_score INTEGER,
    rank_verdict TEXT,
    rank_date TEXT,
    location_verdict TEXT,
    language_gate TEXT,
    language_note TEXT,
    strengths TEXT,
    gaps TEXT,
    signals TEXT,
    also_on TEXT,
    full_posting TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_portal ON jobs(portal);
CREATE INDEX IF NOT EXISTS idx_jobs_fit ON jobs(fit);
CREATE INDEX IF NOT EXISTS idx_jobs_company_title ON jobs(company, title);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'preparando',
    cv_path TEXT,
    cover_letter_path TEXT,
    interview_notes_path TEXT,
    applied_date TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_applications_job_id ON applications(job_id);
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);

CREATE TABLE IF NOT EXISTS status_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    from_status TEXT,
    to_status TEXT NOT NULL,
    source TEXT DEFAULT 'cli',
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_status_log_job_id ON status_log(job_id);

CREATE TABLE IF NOT EXISTS evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    score_technical INTEGER,
    score_experience INTEGER,
    score_behavioral INTEGER,
    score_location TEXT,
    score_career INTEGER,
    score_global INTEGER,
    verdict TEXT,
    strengths TEXT,
    gaps TEXT,
    report_md TEXT,
    ai_provider TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evaluations_job_id ON evaluations(job_id);

CREATE TABLE IF NOT EXISTS profile (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    total_found INTEGER DEFAULT 0,
    total_new INTEGER DEFAULT 0,
    total_seen INTEGER DEFAULT 0,
    portals_summary TEXT,
    health_report TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS application_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    event_date TEXT NOT NULL,
    feedback TEXT,
    questions_and_answers TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_application_events_app_id ON application_events(application_id);

CREATE TABLE IF NOT EXISTS application_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    portal TEXT,
    job_url TEXT,
    applied_date TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    active_in_list INTEGER DEFAULT 1,
    archived_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_ledger_applied_date ON application_ledger(applied_date);
CREATE INDEX IF NOT EXISTS idx_ledger_company_role ON application_ledger(company, role);
CREATE INDEX IF NOT EXISTS idx_ledger_active ON application_ledger(active_in_list);

CREATE TABLE IF NOT EXISTS recruiter_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    emails TEXT NOT NULL,
    email_context TEXT,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    portal TEXT NOT NULL,
    url TEXT,
    location TEXT,
    work_model TEXT,
    published_date TEXT,
    description TEXT NOT NULL,
    matched_keywords TEXT,
    match_score INTEGER DEFAULT 0,
    job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
    dismissed INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_recruiter_posts_url ON recruiter_posts(url) WHERE url IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_recruiter_posts_dismissed ON recruiter_posts(dismissed);


