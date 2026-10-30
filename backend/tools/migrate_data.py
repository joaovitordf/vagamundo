"""One-shot idempotent data migration from JSON/CSV into SQLite."""

from __future__ import annotations
import csv
import json
import sys
from pathlib import Path

_here = Path(__file__).resolve()
ROOT = _here.parent.parent.parent if _here.parent.parent.name == "backend" else _here.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SEEN_JSON = ROOT / "backend" / "job_scraper" / "seen_jobs.json"
TRACKER_CSV = ROOT / "backend" / "job_search_tracker.csv"
EVOLUCAO_JSON = ROOT / "backend" / "documents" / "evolucao.json"

from backend.db.repository import Repository
from backend.tools.job_key import make_key


def migrate(
    seen_path: Path = SEEN_JSON,
    tracker_path: Path = TRACKER_CSV,
    db_path: Path | str | None = None,
) -> dict[str, int]:
    repo = Repository(db_path)
    jobs_migrated = 0
    apps_migrated = 0

    # 1. Migrate seen_jobs.json
    if seen_path.exists():
        try:
            data = json.loads(seen_path.read_text(encoding="utf-8"))
            seen_dict = data.get("seen", {}) if isinstance(data, dict) else {}
            for key, entry in seen_dict.items():
                if not isinstance(entry, dict):
                    continue
                url = entry.get("url") or ""
                company = entry.get("company") or ""
                title = entry.get("title") or ""
                job_id = key or make_key(company, title, url)

                repo.upsert_job({
                    "id": job_id,
                    "title": title,
                    "company": company,
                    "url": url,
                    "location": entry.get("location"),
                    "portal": entry.get("portal"),
                    "source": entry.get("source", "cli"),
                    "work_model": entry.get("workplace_type"),
                    "contract_type": entry.get("contract"),
                    "seniority": entry.get("seniority"),
                    "description": entry.get("description"),
                    "posted_date": entry.get("posted_date"),
                    "deadline": entry.get("deadline"),
                    "first_seen": entry.get("first_seen"),
                    "status": entry.get("status", "new"),
                    "fit": entry.get("fit"),
                    "rank_score": entry.get("rank_score"),
                    "rank_verdict": entry.get("rank_verdict"),
                    "rank_date": entry.get("rank_date"),
                    "location_verdict": entry.get("location_verdict"),
                    "language_gate": entry.get("language_gate"),
                    "strengths": entry.get("strengths"),
                    "gaps": entry.get("gaps"),
                })
                jobs_migrated += 1
        except Exception as exc:
            print(f"Aviso ao ler seen_jobs.json: {exc}", file=sys.stderr)

    # 2. Migrate job_search_tracker.csv
    if tracker_path.exists():
        try:
            with tracker_path.open(encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    url = (row.get("source") or row.get("url") or "").strip()
                    company = (row.get("company") or "").strip()
                    title = (row.get("role") or row.get("title") or "").strip()
                    if not company and not title:
                        continue

                    job_id = make_key(company, title, url) if url or (company and title) else None
                    if job_id:
                        repo.upsert_job({
                            "id": job_id,
                            "title": title,
                            "company": company,
                            "url": url,
                            "portal": row.get("channel"),
                            "status": row.get("status", "applied"),
                        })

                        existing = repo.conn.execute(
                            "SELECT id FROM applications WHERE job_id = ?", (job_id,)
                        ).fetchone()

                        if not existing:
                            repo.upsert_application({
                                "job_id": job_id,
                                "status": row.get("status", "applied"),
                                "cv_path": row.get("cv_file"),
                                "cover_letter_path": row.get("cover_letter_file"),
                                "applied_date": row.get("date"),
                                "notes": row.get("notes"),
                            })
                            apps_migrated += 1
        except Exception as exc:
            print(f"Aviso ao ler tracker.csv: {exc}", file=sys.stderr)

    repo.close()
    return {"jobs": jobs_migrated, "applications": apps_migrated}


if __name__ == "__main__":
    res = migrate()
    print(f"Migração concluída com sucesso: {res['jobs']} vagas e {res['applications']} candidaturas processadas.")
