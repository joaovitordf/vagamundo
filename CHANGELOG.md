# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Modern Angular Frontend SPA**: Complete domain-neutral interface rewrite with standalone components, signals, interactive World and Brazil opportunity map (`GeoMapComponent`), job cards, interview dossier generator, and dynamic profile editing (`Meu Perfil`).
- **FastAPI Backend Gateway**: Async REST API replacing legacy monolithic handlers, featuring Pydantic schemas, OpenAPI docs (`/docs`), CSRF/Host-header protection, and background task execution.
- **Modular SQLite Persistence (`backend/db/*_repo.py`)**: Atomic relational persistence (`data/vagamundo.db`) with WAL mode, automated schema migrations (`migrations.py`), and domain repositories (`jobs_repo.py`, `applications_repo.py`, `recruiters_repo.py`, `analytics_repo.py`, and facade `repository.py`).
- **Multi-Provider AI Gateway (`backend/tools/ia/`)**: Built-in support for Google Gemini (`gemini-2.5-flash` default), Anthropic Claude, and OpenAI/Ollama (`AI_PROVIDER=auto` default), enabling calibrated AI fit scoring, cover letter creation, tailored CV generation, interview preparation, and one-click PDF profile extraction (`POST /api/profile/organize`).
- **24-Portal Scraper Ecosystem**: 24 specialized portal CLIs under `.agents/skills/` covering Brazil, remote-first, and international markets (`gupy-search`, `solides-search`, `vagas-search`, `infojobs-search`, `remotar-search`, `greenhouse-search`, `programathor-search`, `geekhunter-search`, `trampos-search`, `michaelpage-search`, `roberthalf-search`, `pcd-search`, `agrobase-search`, `agrosearch-search`, `digai-search`, `empregos-search`, `linkedin-search`, `freehire-search`, `ashby-search`, `hn-search`, `jobicy-search`, `remoteok-search`, `hh-search`, `habrcareer-search`), including Russia/Eurasia integration (`hh.ru` and `career.habr.com`) with automatic PT→EN query translation in `scrape_run.py`.
- **Recruiter Radar & LinkedIn Search Bar (`backend/core/recruiters/*`, `LinkedinSearchBarComponent`)**: Direct recruiter email (`@`) mining across HN *Who is Hiring*, GitHub Vagas BR, Remotive, and 9 live portal CLIs, paired with a zero-login LinkedIn Search Bar featuring automatic CV area sorting, lean boolean queries (max 4 operators), bilingual PT↔EN dictionary + AI term expansion (`POST /api/recruiters/expand-search-term`), Google X-Ray fallback, and inline AI evaluation cards under the paste box.
- **Continuous Autonomous Mode & Liveness Check (`backend/core/auto_mode.py`, `backend/core/liveness.py`)**: Background daemon loop for both Jobs and Recruiter Radar with anti-ban jitter/backoff, rate-limit detection, atomic undo, and SSRF-safe TLS job URL liveness verification.

### Changed

- **Zero-Tracked-Edits Onboarding & Unified Developer Workflow**: Single-command installer (`npm run install:all` via `install.js`) and orchestrator (`npm run dev` via `dev.js`) with automatic `.venv` resolution, root `.env` configuration, and local gitignored profile storage (`backend/documents/perfil/`).
- **Centralized Job Age and Date Filtering**: Enforced multi-layered date cutoffs across scraper helpers, LinkedIn Snowflake ID decoding, and backend collector pipelines.

### Removed

- **Legacy Monolithic Handlers & Obsolete Connectors**: Removed outdated ad-hoc HTTP servers and deprecated connectors (`eures.py`, `google_careers.py`, `linkedin_browser.py`) in favor of modular FastAPI routes and safe manual LinkedIn search/paste workflows.
- **Obsolete Upstream Documentation**: Cleaned out foreign project references, legacy licenses, and outdated CLI-only setup guides.

## [2.0.0] - 2026-10-31

### Added

- Initial release of Vagamundo v2 fullstack architecture.
