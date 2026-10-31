# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Modern Angular Frontend SPA**: Complete interface rewrite with standalone components, signals, interactive World and Brazil opportunity map, job cards, interview dossier generator, and dynamic profile editing.
- **FastAPI Backend Gateway**: Async REST API replacing legacy monolithic handlers, featuring Pydantic schemas, OpenAPI docs (`/docs`), and robust background task execution.
- **SQLite Database with WAL Mode**: Atomic relational persistence (`data/vagamundo.db`) with full transactional integrity, automated schema migrations, and fast indexed search queries.
- **Multi-Provider AI Gateway**: Built-in support for Google Gemini, Anthropic Claude, and OpenAI/Ollama, enabling AI fit scoring, cover letter creation, tailored CV generation, and interview preparation.
- **Expanded Scraper Ecosystem**: 18 specialized portal CLIs covering Brazil and global tech markets (Gupy, Sólides, Vagas.com, InfoJobs, Remotar, Greenhouse, Programathor, GeekHunter, Trampos, Michael Page, Robert Half, PCD Online, Agrobase, AGROSearch, DigAÍ, Empregos.com.br, LinkedIn, FreeHire).

### Changed

- **Unified Developer Workflow**: Single-command orchestrator `node dev.js` (`npm run dev`) that manages backend Uvicorn, port cleanup, and Angular development server concurrently.
- **Centralized Job Age and Date Filtering**: Enforced multi-layered date cutoffs across scraper helpers, LinkedIn API queries, and backend collector pipelines.

### Removed

- **Legacy Monolithic Handlers**: Removed outdated ad-hoc HTTP servers in favor of modern FastAPI routes.
- **Obsolete Upstream Documentation**: Cleaned out foreign project references, legacy licenses, and outdated CLI-only setup guides.

## [2.0.0] - 2026-10-31

### Added

- Initial release of Vagamundo v2 fullstack architecture.
