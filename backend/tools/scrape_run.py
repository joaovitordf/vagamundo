#!/usr/bin/env python3

"""The mechanical half of /scrape: run the portal searches, deduplicate, flag.



/scrape mixes judgment (how well does a posting fit?) with bookkeeping (run

thirty searches, drop what was seen before, notice the same job on two

portals, record what was shown). The bookkeeping was prose the model redid by

hand each run, with ad hoc scripts; this tool makes it the same every time.

The fit call stays with the model.



  search   Reads the query lines of .claude/skills/job-scraper/search-queries.md

           (`<portal>-search: <args>` inside the "### Prioridade N" sections),

           runs each enabled portal CLI with `--jobage` and `--format json`,

           and writes one JSON file:

             * new postings only - a posting is "seen" when its URL matches any

               job_scraper/seen_jobs.json entry (whatever its key), or its

               company+title matches a seen entry or a job_search_tracker.csv row;

             * the same posting found twice (two portals, or one portal listing

               it twice, e.g. for two cities) is kept once, with `also_on`

               listing the other portals (company names are compared without

               legal suffixes, and "FindMe" matches "FINDME TECNOLOGIA LTDA");

             * a posting relayed by an aggregator (Remotar, Agrobase: an

               `apply_url` to the company's own posting) gets `full_posting`:

               {"portal": <installed portal that reads that URL, or null>,

               "url": <apply_url>}, so the full text is read there, not from

               the aggregator's summary;

             * when those portals label the work model differently ("remote"

               on one, "hybrid" on another), `signals.workplace_conflict` maps

               each portal to its label and the verdict says so;

             * each new posting carries `signals` from tools/posting_signals.py

               (workplace, internal selection, exclusivity, intermediary,

               seniority against the profile's Senioridade-alvo);

             * `meta.portals` has per-portal call/result/error counts for the

               health check, plus the portals skipped (`enabled: false`) and the

               query lines naming a portal that is not installed.

  record   Appends classified postings to job_scraper/seen_jobs.json under the

           canonical tools/job_key.py key. Existing entries are never

           overwritten (their /rank fields stay intact).



Fetched content is third-party data: `search` writes its file outside the

repo (system temp directory by default), like tools/fetch_page.py.



Usage:

  python3 tools/scrape_run.py search [--priority 1,2,3 | --all] [--jobage 14]

                                     [--accept LEVELS] [--out FILE] [--workers 4]

  python3 tools/scrape_run.py record --in FILE



Exit codes: 0 done (even when some searches failed - they are in meta);

2 usage error or unreadable input.

"""



import argparse

import csv

import json

import re

import shlex

import subprocess

import sys

import tempfile

import unicodedata

from concurrent.futures import ThreadPoolExecutor, as_completed

from datetime import date, datetime, timedelta

from pathlib import Path



sys.path.insert(0, str(Path(__file__).resolve().parent))

from job_key import make_key  # noqa: E402

from posting_signals import LEVELS, analyse, verdict  # noqa: E402



ROOT = Path(__file__).resolve().parent.parent

REPO_ROOT = ROOT.parent
QUERIES = REPO_ROOT / ".claude" / "skills" / "job-scraper" / "search-queries.md"

LOCAL_QUERIES = ROOT / "documents" / "perfil" / "search-queries.md"

LOCAL_ANSWERS = ROOT / "documents" / "perfil" / "respostas.json"

SKILLS = REPO_ROOT / ".agents" / "skills"

SEEN = ROOT / "job_scraper" / "seen_jobs.json"

TRACKER = ROOT / "job_search_tracker.csv"

PROFILE = REPO_ROOT / "CLAUDE.md"

CALL_TIMEOUT = 120



QUERY_LINE = re.compile(r"^([a-z0-9-]+-search):\s+(.+)$")

LEGAL_SUFFIXES = {"ltda", "sa", "s", "a", "eireli", "me", "epp", "inc", "llc", "ltd", "corp", "co", "gmbh", "plc"}

REGION_PORTALS = {
    "brasil": {
        "gupy-search", "solides-search", "vagas-search", "infojobs-search",
        "empregos-search", "trampos-search", "pcd-search", "remotar-search",
        "geekhunter-search", "programathor-search", "digai-search",
        "agrobase-search", "agrosearch-search", "michaelpage-search", "roberthalf-search",
        "linkedin-search", "greenhouse-search", "freehire-search"
    },
    "estados-unidos": {
        "remoteok-search", "jobicy-search", "hn-search",
        "freehire-search", "ashby-search", "greenhouse-search",
        "linkedin-search"
    },
    "europa": {
        "jobicy-search", "freehire-search", "greenhouse-search", "linkedin-search"
    },
    "global": {
        "remoteok-search", "jobicy-search", "hn-search",
        "freehire-search", "ashby-search", "greenhouse-search",
        "linkedin-search", "hh-search", "habrcareer-search", "remotar-search"
    },
    "remote": {
        "remotar-search", "remoteok-search", "jobicy-search", "hn-search",
        "freehire-search", "ashby-search", "greenhouse-search", "linkedin-search",
        "gupy-search", "solides-search", "vagas-search", "infojobs-search"
    }
}

REGION_LINKEDIN_LOCATION = {
    "brasil": "Brazil",
    "estados-unidos": "United States",
    "europa": "European Union",
    "remote": "Remote",
}


def _normalize_linkedin_location(cargs: list[str], region: str | None) -> list[str]:
    """Keep linkedin-search -l/--location aligned with the chosen target region."""
    target_loc = REGION_LINKEDIN_LOCATION.get(region or "")
    if not target_loc:
        return list(cargs)
    out = list(cargs)
    was_remote = False
    replaced = False
    for flag in ("-l", "--location"):
        if flag in out:
            idx = out.index(flag)
            if idx + 1 < len(out):
                if out[idx + 1].strip().lower() == "remote":
                    was_remote = True
                out[idx + 1] = target_loc
                replaced = True
                break
    if not replaced:
        out.extend(["-l", target_loc])
    if (was_remote or region == "remote") and "--remote" not in out:
        out.extend(["--remote", "remote"])
    return out


def _apply_query_terms(calls: list[tuple], query_str: str) -> list[tuple]:
    """Split comma-separated keywords into clean single-term portal calls and deduplicate."""
    terms = [t.strip() for t in query_str.split(",") if t.strip()][:3]
    if not terms:
        return calls
    updated_calls = []
    seen_sigs = set()
    for term in terms:
        for prio, portal, cargs in calls:
            new_cargs = list(cargs)
            if "-q" in new_cargs:
                idx = new_cargs.index("-q")
                if idx + 1 < len(new_cargs):
                    new_cargs[idx + 1] = term
            elif "--query" in new_cargs:
                idx = new_cargs.index("--query")
                if idx + 1 < len(new_cargs):
                    new_cargs[idx + 1] = term
            else:
                new_cargs.extend(["-q", term])
            sig = (portal, tuple(new_cargs))
            if sig not in seen_sigs:
                seen_sigs.add(sig)
                updated_calls.append((prio, portal, new_cargs))
    return updated_calls





# ---------------------------------------------------------------------------

# Inputs

# ---------------------------------------------------------------------------



def parse_queries(text: str) -> list:

    """(priority, portal, args) for every query line under a "### Prioridade N" heading."""

    calls, priority = [], None

    for line in text.splitlines():

        heading = re.match(r"^###\s+Prioridade\s+(\d+)", line)

        if heading:

            priority = int(heading.group(1))

            continue

        if line.startswith("## "):

            priority = None

            continue

        m = QUERY_LINE.match(line.strip())

        # A line still carrying a template placeholder ("[YOUR_REGION]") is not a

        # search yet: /setup has not filled it in.

        if m and priority is not None and not re.search(r"\[YOUR_[A-Z0-9_]+\]", m.group(2)):

            try:

                args = shlex.split(m.group(2))

            except ValueError:

                continue

            calls.append((priority, m.group(1), args))

    return calls





def active_queries_path(path: Path | None = None) -> Path:

    """Usa o plano de busca privado local se configurado pelo usuário."""

    if path is not None:

        return path

    return LOCAL_QUERIES if LOCAL_QUERIES.exists() else QUERIES





def local_target_seniority(path: Path | None = None):

    """Lê a senioridade do formulário local sem expor o perfil no Git."""

    target = path or LOCAL_ANSWERS

    try:

        data = json.loads(target.read_text(encoding="utf-8"))

    except (OSError, json.JSONDecodeError):

        return None

    values = data.get("senioridade") if isinstance(data, dict) else None

    if isinstance(values, str):

        values = [values]

    if not isinstance(values, list):

        return None

    result = [str(value).strip().lower() for value in values if str(value).strip().lower() in LEVELS]

    return result or None





def portal_enabled(skill_dir: Path) -> bool:

    """On unless the SKILL.md frontmatter says `enabled: false`."""

    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")

    front = re.match(r"^---\n(.*?)\n---", text, re.S)

    return not (front and re.search(r"^enabled:\s*false\b", front.group(1), re.M))





# A host literal in a portal CLI's sources: the hosts that CLI reads. Same rule

# as tests/test_apply_host_check.py, so both agree on what "installed" covers.

HOST_LITERAL = re.compile(r"https?://([A-Za-z0-9.-]+\.[A-Za-z]{2,})")

NON_PORTAL_HOSTS = {"schema.org", "www.w3.org", "w3.org", "example.com", "localhost", "github.com"}





def portal_hosts(skills: Path = SKILLS) -> dict:

    """{portal: hosts its CLI reads}, `www.` dropped (subdomains match later)."""

    out = {}

    for d in sorted(skills.glob("*-search")):

        src = d / "cli" / "src"

        if not src.is_dir():

            continue

        hosts = set()

        for f in src.rglob("*.ts"):

            for h in HOST_LITERAL.findall(f.read_text(encoding="utf-8")):

                h = h.lower()

                if h not in NON_PORTAL_HOSTS:

                    hosts.add(h[4:] if h.startswith("www.") else h)

        out[d.name] = hosts

    return out





def portal_for_url(url, hosts_by_portal: dict):

    """The installed portal whose CLI reads this URL (host or subdomain match), or None."""

    m = re.match(r"https?://([^/?#:]+)", str(url or ""), re.I)

    if not m:

        return None

    host = m.group(1).lower()

    best, best_len = None, 0

    for portal, hosts in hosts_by_portal.items():

        for h in hosts:

            if (host == h or host.endswith("." + h)) and len(h) > best_len:

                best, best_len = portal, len(h)

    return best





def installed_portals(skills: Path = SKILLS) -> dict:

    """name -> enabled, for every .agents/skills/*-search with a CLI."""

    out = {}

    for d in sorted(skills.glob("*-search")):

        if (d / "SKILL.md").exists() and (d / "cli" / "src" / "cli.ts").exists():

            out[d.name] = portal_enabled(d)

    return out





def target_seniority(profile_text: str):

    """The Senioridade-alvo codes from CLAUDE.md, or None when absent or still a placeholder."""

    m = re.search(r"\*\*Senioridade-alvo:\*\*\s*([^<\n]*)", profile_text)

    if not m or "[" in m.group(1):

        return None

    codes = [c.strip().lower() for c in m.group(1).split(",") if c.strip()]

    codes = [c for c in codes if c in LEVELS]

    return codes or None





# ---------------------------------------------------------------------------

# Identity

# ---------------------------------------------------------------------------



def norm(text) -> str:

    folded = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()

    return re.sub(r"[^a-z0-9]+", " ", folded).strip()





def company_tokens(name) -> list:

    tokens = norm(name).split()

    while tokens and tokens[-1] in LEGAL_SUFFIXES:

        tokens.pop()

    return tokens





def same_company(a, b) -> bool:

    """Equal without legal suffixes, or one name is a word-prefix of the other ("FindMe" / "FINDME TECNOLOGIA LTDA")."""

    ta, tb = company_tokens(a), company_tokens(b)

    if not ta or not tb:

        return False

    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)

    return long_[: len(short)] == short





class SeenIndex:

    """URLs and (company, title) pairs already seen, matched as /scrape Step 2 says."""



    def __init__(self):

        self.urls = set()

        self.by_title = {}



    def add(self, company, title, url=None):

        if url:

            self.urls.add(url)

        if title:

            self.by_title.setdefault(norm(title), []).append(company)



    def match(self, company, title, url=None) -> bool:

        if url and url in self.urls:

            return True

        return any(same_company(company, c) for c in self.by_title.get(norm(title), []))





def load_seen(seen_path: Path = SEEN, tracker_path: Path = TRACKER) -> SeenIndex:

    index = SeenIndex()

    if seen_path.exists():

        for entry in json.loads(seen_path.read_text(encoding="utf-8")).get("seen", {}).values():

            index.add(entry.get("company"), entry.get("title"), entry.get("url"))

    if tracker_path.exists():

        with tracker_path.open(encoding="utf-8", newline="") as fh:

            for row in csv.DictReader(fh):

                index.add(row.get("company"), row.get("role"), row.get("source") or None)

    return index





# ---------------------------------------------------------------------------

# Running the portals

# ---------------------------------------------------------------------------



def build_args(args: list, jobage: int) -> list:

    """The query line's own flags win; --jobage and --format json are added when absent."""

    out = list(args)

    if "--jobage" not in out and "--jobage-minutes" not in out:

        out += ["--jobage", str(jobage)]

    if "--format" in out:

        i = out.index("--format")

        del out[i:i + 2]

    return out + ["--format", "json"]





def run_cli(portal: str, args: list, timeout: int = CALL_TIMEOUT):

    """(results, None) or (None, error) for one `search` call."""

    try:

        proc = subprocess.run(

            ["bun", "run", f".agents/skills/{portal}/cli/src/cli.ts", "search", *args],

            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,

        )

    except (OSError, subprocess.SubprocessError) as exc:

        return None, f"{type(exc).__name__}: {exc}"

    if proc.returncode != 0:

        return None, proc.stderr.strip()[:300] or f"exit {proc.returncode}"

    try:

        return json.loads(proc.stdout).get("results", []), None

    except (json.JSONDecodeError, AttributeError):

        return None, "saída não é o JSON do contrato"





def collect(calls, portals: dict, seen: SeenIndex, accept, jobage: int, runner=run_cli, workers: int = 4,

            hosts: dict | None = None) -> dict:

    hosts = portal_hosts() if hosts is None else hosts

    stats = {name: {"calls": 0, "ok": 0, "results": 0, "errors": []} for name, on in portals.items() if on}

    skipped = sorted(name for name, on in portals.items() if not on)

    unknown = sorted({p for _, p, _ in calls if p not in portals})

    runnable = [(prio, p, build_args(a, jobage)) for prio, p, a in calls if portals.get(p)]



    def one(call):

        prio, portal, args = call

        results, err = runner(portal, args)

        return prio, portal, args, results, err



    with ThreadPoolExecutor(max(1, workers)) as ex:
        futures = {ex.submit(one, c): (i, c) for i, c in enumerate(runnable)}
        outcomes = [None] * len(runnable)
        completed = 0
        total = len(runnable)
        for fut in as_completed(futures):
            i, c = futures[fut]
            res = fut.result()
            outcomes[i] = res
            completed += 1
            prio, portal, args, results, err = res
            prog_evt = {
                "type": "progress",
                "portal": portal,
                "status": "error" if err else "ok",
                "jobs": len(results) if results else 0,
                "error": err,
                "completed": completed,
                "total": total,
                "percent": round((completed / max(1, total)) * 100, 1)
            }
            print("PROGRESS:" + json.dumps(prog_evt, ensure_ascii=False), flush=True)



    collected, seen_before, cross = 0, 0, 0

    new, urls_now = [], set()

    labels = {}  # id(row) -> {portal: workplace_type}, to spot portals that disagree

    for prio, portal, args, results, err in outcomes:

        st = stats[portal]

        st["calls"] += 1

        query = args[args.index("-q") + 1] if "-q" in args else args[args.index("--query") + 1] if "--query" in args else ""

        if err is not None:

            st["errors"].append({"query": query, "error": err})

            continue

        st["ok"] += 1

        st["results"] += len(results)

        visa_query = "--visa-sponsorship" in args or "--visa" in args

        for r in results:

            if not isinstance(r, dict):

                continue

            url, title, company = r.get("url"), r.get("title"), r.get("company")

            if url and url in urls_now:

                continue  # the same posting from two queries of this run

            collected += 1

            if url:

                urls_now.add(url)

            if jobage and jobage < 9999 and r.get("date"):
                cutoff_date = (date.today() - timedelta(days=jobage)).isoformat()
                raw_date_str = str(r["date"]).strip()[:10]
                if len(raw_date_str) == 10 and raw_date_str[2:3] == "/" and raw_date_str[5:6] == "/":
                    try:
                        raw_date_str = datetime.strptime(raw_date_str, "%d/%m/%Y").strftime("%Y-%m-%d")
                    except ValueError:
                        raw_date_str = ""
                if raw_date_str and raw_date_str[:4].isdigit() and raw_date_str < cutoff_date:
                    continue

            if seen.match(company, title, url):

                seen_before += 1

                continue

            twin = next((n for n in new if norm(n.get("title")) == norm(title) and same_company(n.get("company"), company)), None)

            if twin is not None:

                cross += 1

                if portal != twin["portal"] and portal not in twin["also_on"]:

                    twin["also_on"].append(portal)

                if r.get("workplace_type"):

                    labels.setdefault(id(twin), {}).setdefault(portal, r["workplace_type"])

                if visa_query or r.get("visa_sponsorship") is True:

                    twin["visa_sponsorship"] = True

                continue

            row = dict(r)

            row.update(portal=portal, priority=prio, query=query, also_on=[])

            if visa_query or r.get("visa_sponsorship") is True:

                row["visa_sponsorship"] = True

            row["signals"] = analyse(str(r.get("description") or ""), str(title or ""), str(company or ""), accept,

                                     r.get("seniority"))

            if r.get("workplace_type"):

                labels[id(row)] = {portal: r["workplace_type"]}

            apply_url = r.get("apply_url")

            if isinstance(apply_url, str) and re.match(r"https?://", apply_url, re.I):

                reader = portal_for_url(apply_url, hosts)

                if reader != portal:

                    row["full_posting"] = {"portal": reader, "url": apply_url}

            new.append(row)



    for row in new:

        by_portal = labels.get(id(row), {})

        if len(set(by_portal.values())) > 1:

            row["signals"]["workplace_conflict"] = by_portal

        row["signals"]["verdict"] = verdict(row["signals"])



    return {

        "meta": {

            "date": date.today().isoformat(),

            "jobage": jobage,

            "accept": accept,

            "portals": stats,

            "skipped_portals": skipped,

            "unknown_portals": unknown,

            "counts": {"collected": collected, "seen_before": seen_before, "cross_portal": cross, "new": len(new)},

        },

        "new": new,

    }





# ---------------------------------------------------------------------------

# Recording

# ---------------------------------------------------------------------------



FITS = {"high", "medium", "low"}

STATUSES = {"new", "skipped", "expired", "unreachable"}





def record(rows: list, seen_path: Path = SEEN, today: str | None = None) -> dict:

    today = today or date.today().isoformat()

    state = json.loads(seen_path.read_text(encoding="utf-8")) if seen_path.exists() else {"seen": {}}

    state.setdefault("seen", {})

    added, kept, invalid = 0, 0, []

    for row in rows:

        fit, status = row.get("fit"), row.get("status") or ("skipped" if row.get("fit") == "low" else "new")

        if fit not in FITS or status not in STATUSES or not row.get("title"):

            invalid.append(row.get("url") or row.get("title"))

            continue

        key = make_key(str(row.get("company") or ""), str(row.get("title") or ""), str(row.get("url") or ""))

        if key in state["seen"]:

            kept += 1

            continue

        entry = {

            "title": row.get("title"),

            "company": row.get("company"),

            "url": row.get("url"),

            "first_seen": today,

            "posted_date": row.get("date"),

            "deadline": row.get("deadline"),

            "fit": fit,

            "status": status,

            "portal": row.get("portal"),

            "source": row.get("source") or "cli",

        }

        if row.get("visa_sponsorship") is True:

            entry["visa_sponsorship"] = True

        state["seen"][key] = entry

        added += 1

    seen_path.parent.mkdir(parents=True, exist_ok=True)

    seen_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Dual-write to SQLite database (Vagamundo v2 persistence)
    try:
        from backend.db.repository import Repository
        repo = Repository()
        for key, entry in state.get("seen", {}).items():
            if not isinstance(entry, dict):
                continue
            st = entry.get("status")
            if entry.get("source") == "painel":
                if st not in ("applied", "skipped") and entry.get("fit") != "low":
                    st = "interested"
                elif st == "skipped" or entry.get("fit") == "low":
                    st = "discarded"

            repo.upsert_job({
                "id": key,
                "title": entry.get("title"),
                "company": entry.get("company"),
                "url": entry.get("url"),
                "location": entry.get("location"),
                "portal": entry.get("portal"),
                "source": entry.get("source", "cli"),
                "posted_date": entry.get("posted_date"),
                "deadline": entry.get("deadline"),
                "first_seen": entry.get("first_seen"),
                "status": st,
                "fit": entry.get("fit"),
                "rank_score": entry.get("rank_score"),
                "rank_verdict": entry.get("rank_verdict"),
                "rank_date": entry.get("rank_date"),
                "location_verdict": entry.get("location_verdict"),
                "language_gate": entry.get("language_gate"),
                "strengths": entry.get("strengths"),
                "gaps": entry.get("gaps"),
            })
        repo.close()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"scrape_run: sqlite mirror failed: {exc}", file=sys.stderr)

    return {"added": added, "already_seen": kept, "invalid": invalid, "total": len(state["seen"])}





# ---------------------------------------------------------------------------

# CLI

# ---------------------------------------------------------------------------



def _force_utf8_output() -> None:

    for stream in (sys.stdout, sys.stderr):

        reconfigure = getattr(stream, "reconfigure", None)

        if reconfigure:

            reconfigure(encoding="utf-8")





def _inside_repo(path: Path) -> bool:

    try:

        path.resolve().relative_to(REPO_ROOT)

    except ValueError:

        return False

    return True





def summary(result: dict) -> str:

    m = result["meta"]

    c = m["counts"]

    lines = [f"scrape_run: {c['collected']} coletadas; {c['seen_before']} já vistas; "

             f"{c['cross_portal']} repetidas (mesma empresa e título, em outro portal ou outra busca); {c['new']} novas"]

    for name, st in m["portals"].items():

        flag = " ⚠ zero resultados" if st["ok"] and not st["results"] else ""

        err = f"; {len(st['errors'])} erro(s)" if st["errors"] else ""

        if st["calls"]:

            lines.append(f"  {name}: {st['ok']}/{st['calls']} buscas, {st['results']} resultados{err}{flag}")

    if m["skipped_portals"]:

        lines.append(f"  pulados (desligados): {', '.join(m['skipped_portals'])}")

    if m["unknown_portals"]:

        lines.append(f"  linhas de busca para portal não instalado: {', '.join(m['unknown_portals'])}")

    flagged = sum(1 for r in result["new"] if r["signals"]["verdict"] != "posting_signals: none")

    lines.append(f"  sinais: {flagged} das {c['new']} novas com ⚠ (veja `signals` no arquivo)")

    return "\n".join(lines)





def _make_portal_call(portal: str, query: str, region: str | None = None) -> tuple[int, str, list[str]]:
    extra_cargs = ["-q", query]
    if portal == "linkedin-search":
        extra_cargs.extend(["-l", REGION_LINKEDIN_LOCATION.get(region or "brasil", "Brazil")])
    return (1, portal, extra_cargs)


def _default_fallback_portals(installed: dict, region: str | None) -> list[str]:
    if region and region != "all" and region in REGION_PORTALS:
        return [p for p in sorted(REGION_PORTALS[region]) if p in installed]
    preferred = (
        "gupy-search",
        "solides-search",
        "vagas-search",
        "infojobs-search",
        "remotar-search",
        "geekhunter-search",
        "linkedin-search",
        "freehire-search",
    )
    selected = [p for p in preferred if p in installed]
    return selected or sorted(installed)


def _default_search_query(fallback: str = "analista") -> str:

    """Resolve fallback search query from candidate answers (cargos -> palavras_chave_sorteio -> fallback)."""
    if LOCAL_ANSWERS.exists():
        try:
            ans = json.loads(LOCAL_ANSWERS.read_text(encoding="utf-8"))
            if isinstance(ans, dict):
                for key in ("cargos", "palavras_chave_sorteio", "competencias_busca"):
                    vals = ans.get(key)
                    if isinstance(vals, list):
                        first = next((str(v).strip() for v in vals if str(v).strip()), "")
                        if first:
                            return first
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    return fallback


def _filter_calls_by_region(
    calls: list[tuple],
    region: str | None,
    has_explicit_portal: bool = False,
    installed: dict | None = None,
    default_query: str | None = None,
) -> list[tuple]:
    """Filtra chamadas por região sem vazar portais não solicitados quando --portal é explícito."""
    if not region or region == "all":
        return calls

    region_set = REGION_PORTALS.get(region, set())
    filtered = [c for c in calls if c[1] in region_set]
    if not filtered and not has_explicit_portal:
        resolved_installed = installed if installed is not None else installed_portals()
        default_q = default_query or _default_search_query()
        for p in sorted(region_set):
            if resolved_installed.get(p):
                extra_cargs = ["-q", default_q]
                if p == "linkedin-search":
                    extra_cargs = _normalize_linkedin_location(extra_cargs, region)
                    if not REGION_LINKEDIN_LOCATION.get(region):
                        extra_cargs.extend(["-l", "Remote"])
                filtered.append((1, p, extra_cargs))

    normalized_calls = []
    seen_sigs = set()
    for prio, portal, cargs in filtered:
        new_cargs = _normalize_linkedin_location(cargs, region) if portal == "linkedin-search" else list(cargs)
        sig = (portal, tuple(new_cargs))
        if sig not in seen_sigs:
            seen_sigs.add(sig)
            normalized_calls.append((prio, portal, new_cargs))
    return normalized_calls


def main(argv=None) -> int:

    _force_utf8_output()

    parser = argparse.ArgumentParser(prog="scrape_run.py", description="The mechanical half of /scrape; see module docstring.")

    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="run the portal searches, deduplicate, flag")

    s.add_argument("--priority", default="1,2,3", help="comma list of priorities to run (default 1,2,3)")

    s.add_argument("--all", action="store_true", help="every priority in the file")

    s.add_argument("--jobage", type=int, default=2, help="days (default 2), unless the query line sets its own")

    s.add_argument("--accept", default=None, help="seniority codes; default: Senioridade-alvo in CLAUDE.md")

    s.add_argument("--queries", type=Path, default=None, help="search plan file (default: local profile plan or template)")

    s.add_argument("--out", type=Path, default=None, help="results file (default: system temp dir; never inside the repo)")

    s.add_argument("--portal", default=None, help="limit search to a specific portal CLI (e.g. gupy-search)")
    s.add_argument("--region", default="all", choices=["all", "brasil", "estados-unidos", "europa", "global", "remote"], help="filter portals by target region (default all)")
    s.add_argument("--query", "-q", default=None, help="search query / keyword to override or apply across portal calls")

    s.add_argument("--workers", type=int, default=4, help="parallel CLI calls (default 4; keep it low)")

    r = sub.add_parser("record", help="append classified postings to job_scraper/seen_jobs.json")

    r.add_argument("--in", dest="infile", type=Path, required=True, help="JSON list of postings with fit/status")

    args = parser.parse_args(argv)



    if args.cmd == "record":

        try:

            data = json.loads(args.infile.read_text(encoding="utf-8"))

        except (OSError, json.JSONDecodeError) as exc:

            print(f"scrape_run: {exc}", file=sys.stderr)

            return 2

        rows = data.get("new", data) if isinstance(data, dict) else data

        print(json.dumps(record(rows if isinstance(rows, list) else []), ensure_ascii=False))

        return 0



    out = args.out or Path(tempfile.gettempdir()) / f"scrape_run_{date.today().isoformat()}.json"

    if _inside_repo(out):

        print(f"scrape_run: refusing to write inside the repo ({out}); fetched postings are untrusted data "

              "and belong in the session scratchpad or the temp directory", file=sys.stderr)

        return 2

    if args.accept is not None:

        accept = [c.strip().lower() for c in args.accept.split(",") if c.strip()]

        bad = [c for c in accept if c not in LEVELS]

        if bad:

            print(f"scrape_run: unknown level(s) {', '.join(bad)} (known: {', '.join(LEVELS)})", file=sys.stderr)

            return 2

    else:

        accept = local_target_seniority() or (target_seniority(PROFILE.read_text(encoding="utf-8")) if PROFILE.exists() else None)



    try:

        queries_file = active_queries_path(args.queries)

        calls = parse_queries(queries_file.read_text(encoding="utf-8"))

    except OSError as exc:

        print(f"scrape_run: {exc}", file=sys.stderr)

        return 2

    has_explicit_portal = bool(
        getattr(args, "portal", None) and args.portal.strip() and args.portal.strip() != "all"
    )
    if has_explicit_portal:
        raw_portals = [p.strip() for p in args.portal.split(",") if p.strip()]
        target_portals = set()
        for p in raw_portals:
            target_portals.add(p)
            if not p.endswith("-search") and p not in ("europa", "eures", "google"):
                target_portals.add(f"{p}-search")

        filtered_calls = [c for c in calls if c[1] in target_portals]

        # Portais selecionados sem queries prontas ganham chamada default
        installed = installed_portals()
        default_q = None
        raw_queries = parse_queries(queries_file.read_text(encoding="utf-8"))
        for _, _, cargs in raw_queries:
            if "-q" in cargs:
                default_q = cargs[cargs.index("-q") + 1]
                break
            elif "--query" in cargs:
                default_q = cargs[cargs.index("--query") + 1]
                break
        if not default_q:
            default_q = _default_search_query()

        for tp in target_portals:
            if not any(c[1] == tp for c in filtered_calls):
                if tp in installed:
                    filtered_calls.append(_make_portal_call(tp, default_q, getattr(args, "region", None)))

        calls = filtered_calls

    elif not args.all:
        wanted = {int(p) for p in args.priority.split(",") if p.strip().isdigit()}
        calls = [c for c in calls if c[0] in wanted]

    if getattr(args, "region", None) and args.region != "all":
        calls = _filter_calls_by_region(
            calls,
            args.region,
            has_explicit_portal=has_explicit_portal,
        )

    explicit_query = getattr(args, "query", None)
    if explicit_query and explicit_query.strip():
        if not calls and not has_explicit_portal:
            installed = installed_portals()
            first_term = next((t.strip() for t in explicit_query.split(",") if t.strip()), explicit_query.strip())
            calls = [_make_portal_call(p, first_term, getattr(args, "region", None)) for p in _default_fallback_portals(installed, getattr(args, "region", None))]
        calls = _apply_query_terms(calls, explicit_query.strip())
    elif not calls and not has_explicit_portal and args.queries is None:
        answers_query = _default_search_query(fallback="")
        if answers_query:
            installed = installed_portals()
            calls = [_make_portal_call(p, answers_query, getattr(args, "region", None)) for p in _default_fallback_portals(installed, getattr(args, "region", None))]

    if not calls:

        print("scrape_run: nenhuma linha de busca pronta nas prioridades pedidas (as do modelo têm marcadores "

              "[YOUR_...]: rode o /setup, ou escreva as linhas `<portal>-search: ...` em search-queries.md)",

              file=sys.stderr)

        return 2



    result = collect(calls, installed_portals(), load_seen(), accept, args.jobage, workers=args.workers)

    out.parent.mkdir(parents=True, exist_ok=True)

    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    print(summary(result))

    print(f"saved={out}")

    return 0





if __name__ == "__main__":

    sys.exit(main())

