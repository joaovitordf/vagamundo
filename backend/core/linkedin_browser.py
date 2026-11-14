"""Isolated Chrome/Edge CDP worker for hands-free LinkedIn feed post collection."""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
import logging
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request

from backend.core.constants import ROOT, atomic_write_json

logger = logging.getLogger(__name__)

DEFAULT_LINKEDIN_COOLDOWN_MINUTES = 0
DEFAULT_LINKEDIN_MAX_DAILY = 0
DEFAULT_LINKEDIN_MAX_SCROLLS = 3
LINKEDIN_FEED_URL = "https://www.linkedin.com/feed/"

_LOGIN_MARKERS = ("/login", "/uas/login", "/authwall", "linkedin.com/signup")
_CHECKPOINT_MARKERS = ("/checkpoint", "/challenge", "captcha-internal", "security verification")

_BROWSER_WINDOWS_CANDIDATES: Tuple[Path, ...] = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)

_BROWSER_PATH_NAMES: Tuple[str, ...] = (
    "google-chrome",
    "chromium",
    "chromium-browser",
    "chrome",
    "msedge",
    "microsoft-edge",
)

_CHECK_BLOCK_JS = """
(() => {
  const href = String(location.href || '').toLowerCase();
  const title = String(document.title || '').toLowerCase();
  const mainEl = document.querySelector('main');
  const body = String((mainEl && mainEl.innerText) || (document.body && document.body.innerText) || '').slice(0, 2500).toLowerCase();
  const hasCaptchaFrame = Boolean(document.querySelector('iframe[src*="captcha"],#captcha-internal'));
  const hasResultContent = Boolean(document.querySelector(
    '[data-urn*="activity"],[data-urn*="share"],[data-urn*="ugcPost"],[data-id*="activity"],'
    + '[data-chameleon-result-urn*="activity"],[data-view-name="feed-full-update"],'
    + '[data-view-name="search-entity-result-universal-template"],.feed-shared-update-v2,'
    + 'li.reusable-search__result-container,div[role="article"],main div[role="listitem"] [dir="ltr"],'
    + 'a[href*="urn:li:activity"],a[href*="/posts/"]'
  ));
  const hasEmptyState = Boolean(document.querySelector('.search-reusable-search-no-results, .artdeco-empty-state'))
    || body.includes('no results found')
    || body.includes('nenhum resultado encontrado')
    || body.includes('nenhuma publicacao encontrada')
    || body.includes('nenhuma publicação encontrada');
  return {
    href,
    ready: document.readyState,
    hasCaptchaFrame,
    isLogin: href.includes('/login') || href.includes('/uas/login') || href.includes('/authwall') || href.includes('/signup'),
    isCheckpoint: hasCaptchaFrame || href.includes('/checkpoint') || href.includes('/challenge') || title.includes('security verification') || body.includes('let\\u2019s do a quick security check') || body.includes("let's do a quick security check"),
    hasFeedUi: Boolean(document.querySelector('nav.global-nav, .feed-shared-update-v2, [data-urn*="activity"], .search-results-container, main')),
    hasResultContent,
    hasEmptyState,
  };
})()
"""

_EXPAND_SEE_MORE_JS = """
(() => {
  const seen = new Set();
  const candidates = Array.from(document.querySelectorAll(
    'button.feed-shared-inline-show-more-text__see-more-less-toggle,'
    + 'button[data-testid="expandable-text-button"],'
    + 'button[aria-label*="ver mais" i],button[aria-label*="see more" i],button[aria-label*="expand" i],'
    + 'main button,main [role="button"]'
  ));
  const textMatchRe = /^[….\\s]*(?:ver mais|mais|see more|more)[….\\s]*$/i;
  let clicked = 0;
  for (const btn of candidates) {
    if (!btn || seen.has(btn)) continue;
    seen.add(btn);
    if (clicked >= 20) break;
    if (btn.closest('nav, header')) continue;
    if (btn.offsetParent === null || btn.getAttribute('aria-expanded') === 'true') continue;
    const isKnown = btn.matches(
      'button.feed-shared-inline-show-more-text__see-more-less-toggle,button[data-testid="expandable-text-button"],button[aria-label*="ver mais" i],button[aria-label*="see more" i]'
    );
    const labelTxt = String(btn.innerText || btn.textContent || '').replace(/\\s+/g, ' ').trim();
    if (!isKnown && !textMatchRe.test(labelTxt)) continue;
    btn.click();
    clicked++;
  }
  return clicked;
})()
"""

_EXTRACT_POSTS_JS = """
(() => {
  const normalizeObfuscated = (s) => {
    let out = String(s || '').replace(/([A-Za-z0-9._%+-]+)\\s*[\\[\\(\\{]\\s*(?:at|arroba|@)\\s*[\\]\\)\\}]\\s*([A-Za-z0-9-]+)/gi, '$1@$2');
    for (let i = 0; i < 4; i++) {
      const next = out.replace(/(@[A-Za-z0-9.-]+)\\s*[\\[\\(\\{]\\s*(?:dot|ponto)\\s*[\\]\\)\\}]\\s*([A-Za-z0-9-]+)/gi, '$1.$2');
      if (next === out) break;
      out = next;
    }
    return out;
  };
  const emailRe = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}/g;
  const hiringRe = /\\b(vaga|vagas|estamos\\s+contratando|contratando|oportunidade|hiring|we\\s+are\\s+hiring|envie\\s+seu\\s+curr[ií]culo|enviar\\s+curr[ií]culo|curr[ií]culo|curriculo|mande\\s+seu\\s+cv|send\\s+your\\s+cv|send\\s+your\\s+resume|remoto|remote|h[ií]brido|clt|pj|candidat\\w*|apply\\s+now)\\b/i;
  const urnRe = /(?:urn:li:(?:activity|share|ugcPost):|(?:activity|share|ugcPost)-)(\\d{15,20})/i;
  const primarySel = '[data-urn*="activity"],[data-urn*="share"],[data-urn*="ugcPost"],[data-id*="activity"],[data-chameleon-result-urn*="activity"],[data-view-name="feed-full-update"],[data-view-name="search-entity-result-universal-template"],.feed-shared-update-v2,li.reusable-search__result-container,div[role="article"]';
  const rawPrimary = Array.from(document.querySelectorAll(primarySel));
  let cards = rawPrimary.filter(el => !rawPrimary.some(o => o !== el && o.contains(el)));
  if (!cards.length) {
    const rawList = Array.from(document.querySelectorAll('main div[role="listitem"], main li.artdeco-list__item'))
      .filter(el => String(el.innerText || '').trim().length >= 40 && !el.closest('nav, header'));
    cards = rawList.filter(el => !rawList.some(o => o !== el && o.contains(el)));
  }
  if (!cards.length) {
    document.querySelectorAll('a[href*="urn:li:activity"],a[href*="/posts/"]').forEach(a => {
      const box = a.closest('li,article,div[role="article"],div[role="listitem"]') || a.parentElement;
      if (box && !cards.includes(box)) cards.push(box);
    });
  }
  const ageRe = /^\\s*(?:há\\s+|h[aá]\\s+)?(\\d+)\\s*(min|m|h|hr|hrs|d|dia|dias|sem|w|wk|wks|m[eê]s|meses|mo|yr|yrs|ano|anos)\\b/i;
  const posts = [];
  const seen = new Set();
  for (const card of cards) {
    const descEl = card.querySelector(
      '.feed-shared-update-v2__description,.update-components-text,.update-components-update-v2__commentary,'
      + '[data-test-id="main-feed-activity-card__commentary"],[data-testid="expandable-text-box"],[data-view-name="feed-commentary"]'
    );
    const descText = (descEl ? (descEl.innerText || '') : '').trim();
    const fullCardText = (card.innerText || '').trim();
    const normDesc = normalizeObfuscated(descText);
    const normCard = normalizeObfuscated(fullCardText);
    let text = '';
    if (normDesc && emailRe.test(normDesc)) {
      text = normDesc;
    } else if (normDesc && hiringRe.test(normDesc)) {
      text = normDesc;
    } else if (normCard) {
      text = normCard;
    } else {
      text = normDesc;
    }
    emailRe.lastIndex = 0;
    const mailtos = Array.from(card.querySelectorAll('a[href^="mailto:"]'))
      .map(a => (a.getAttribute('href') || '').slice(7).split('?')[0].trim())
      .filter(Boolean);
    for (const m of mailtos) {
      if (!text.toLowerCase().includes(m.toLowerCase())) text += '\\n' + m;
    }
    const urn = (
      card.getAttribute('data-urn')
      || card.getAttribute('data-id')
      || card.getAttribute('data-chameleon-result-urn')
      || ''
    ).trim();
    let url = '';
    const um = urn.match(urnRe);
    if (um) url = `https://www.linkedin.com/feed/update/urn:li:activity:${um[1]}/`;
    if (!url) {
      const links = card.querySelectorAll('[data-urn],[data-id],[data-chameleon-result-urn],a[href*="/feed/update/"],a[href*="/posts/"]');
      for (const el of links) {
        const cand = el.getAttribute('href') || el.getAttribute('data-urn') || el.getAttribute('data-id') || el.getAttribute('data-chameleon-result-urn') || '';
        const lm = cand.match(urnRe);
        if (lm) { url = `https://www.linkedin.com/feed/update/urn:li:activity:${lm[1]}/`; break; }
        if (/linkedin\\.com\\/posts\\//i.test(cand)) { url = cand.split('?')[0]; break; }
      }
    }
    const hasEmail = Boolean(text && emailRe.test(text));
    emailRe.lastIndex = 0;
    const isHiringPost = Boolean(text && text.length >= 40 && url && hiringRe.test(text));
    if (!hasEmail && !isHiringPost) {
      continue;
    }
    const authorEl = card.querySelector(
      '.update-components-actor__title span[aria-hidden="true"],'
      + '.update-components-actor__name span[aria-hidden="true"],'
      + '.update-components-actor__title,'
      + '[data-view-name="feed-actor"] a[href*="/in/"] span,'
      + '[data-view-name="feed-actor"] a[href*="/company/"] span,'
      + 'a[href*="/in/"] span[aria-hidden="true"],'
      + 'a[href*="/company/"] span[aria-hidden="true"]'
    );
    const author = authorEl ? (authorEl.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 80) : '';
    let postedAge = '';
    const timeCandidates = card.querySelectorAll('time, .update-components-actor__sub-description span[aria-hidden="true"], .update-components-actor__sub-description, [data-view-name="feed-actor"] span');
    for (const tel of timeCandidates) {
      const rawT = String(tel.textContent || '').replace(/\\s+/g, ' ').trim().split('•')[0].trim();
      if (ageRe.test(rawT)) { postedAge = rawT; break; }
    }
    const fp = url || text.replace(/\\s+/g, ' ').slice(0, 120).toLowerCase();
    if (seen.has(fp)) continue;
    seen.add(fp);
    posts.push({
      raw_text: text.slice(0, 3500),
      company: author || undefined,
      url: url || undefined,
      posted_age_text: postedAge || undefined,
    });
  }
  return { cards_total: cards.length, posts };
})()
"""


def find_chromium_executable() -> Optional[str]:
    """Locate a local Chrome or Microsoft Edge binary suitable for isolated CDP profiles."""
    override = (os.environ.get("VAGAMUNDO_CHROME_PATH") or "").strip()
    if override and Path(override).is_file():
        return override
    for cand in _BROWSER_WINDOWS_CANDIDATES:
        if str(cand) and cand.is_file():
            return str(cand)
    for name in _BROWSER_PATH_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


_GENERIC_ROLE_PREFIX_RE = re.compile(
    r"^\s*(?:desenvolvedor(?:a)?|engenheiro(?:a)?(?:\s+de\s+software)?|analista|programador(?:a)?|developer|software\s+engineer|engineer|pessoa\s+desenvolvedora|especialista)\b\s*",
    re.IGNORECASE,
)
_HIRING_WORD_RE = re.compile(r"\b(?:vaga|vagas|hiring|oportunidade|oportunidades)\b", re.IGNORECASE)
_VALID_DATE_POSTED = ("past-24h", "past-week", "past-month")


def days_to_linkedin_date_posted(days: Optional[int]) -> str:
    """Map day lookback window to LinkedIn content search datePosted filter."""
    if days is not None:
        if int(days) <= 1:
            return "past-24h"
        if int(days) > 7:
            return "past-month"
    return "past-week"


def _clean_linkedin_term(raw_term: str) -> str:
    """Strip quotes/parentheses and generic role prefixes so LinkedIn keyword search stays broad."""
    stripped = str(raw_term or "").replace('"', " ").replace("'", " ").replace("(", " ").replace(")", " ")
    collapsed = " ".join(stripped.split()).strip()
    if not collapsed:
        return ""
    without_prefix = _GENERIC_ROLE_PREFIX_RE.sub("", collapsed).strip(" -/|·,")
    return " ".join((without_prefix or collapsed).split())


def build_linkedin_content_search_url(
    query: str,
    *,
    date_posted: Optional[str] = "past-week",
    include_vaga_suffix: bool = True,
) -> str:
    """Build a clean LinkedIn content search URL using only keywords, datePosted and sortBy."""
    raw_terms = [t.strip() for t in (query or "").split(",") if t.strip()]
    clean_term = _clean_linkedin_term(raw_terms[0]) if raw_terms else ""
    if not clean_term:
        full_keywords = "vaga"
    elif include_vaga_suffix and not _HIRING_WORD_RE.search(clean_term):
        full_keywords = f"{clean_term} vaga"
    else:
        full_keywords = clean_term

    url = (
        "https://www.linkedin.com/search/results/content/"
        f"?keywords={urllib.parse.quote(full_keywords)}&sortBy=%22date_posted%22"
    )
    if date_posted in _VALID_DATE_POSTED:
        url += f"&datePosted=%22{date_posted}%22"
    return url


def _cdp_call(ws: Any, req_id: int, method: str, params: Optional[dict] = None, timeout: float = 12.0) -> dict:
    """Execute one synchronous Chrome DevTools Protocol command and wait for its matching response."""
    ws.send(json.dumps({"id": req_id, "method": method, "params": params or {}}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = max(0.2, deadline - time.monotonic())
        raw = ws.recv(timeout=remaining)
        msg = json.loads(raw)
        if msg.get("id") == req_id:
            if "error" in msg:
                raise RuntimeError(f"CDP {method} falhou: {msg['error']}")
            return msg.get("result") or {}
    raise TimeoutError(f"Tempo esgotado aguardando CDP {method}.")


def _cdp_eval(ws: Any, req_id: int, expression: str, timeout: float = 12.0) -> Any:
    """Evaluate JavaScript inside the page via CDP and return its JSON value."""
    res = _cdp_call(
        ws,
        req_id,
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": True},
        timeout=timeout,
    )
    if "exceptionDetails" in res:
        desc = res["exceptionDetails"].get("text") or "erro JS"
        raise RuntimeError(f"Falha ao avaliar DOM no LinkedIn: {desc}")
    return (res.get("result") or {}).get("value")


class LinkedInBrowserWorker:
    """Runs visible or headless Chromium against a dedicated user-data-dir for hands-free LinkedIn scraping."""

    def __init__(
        self,
        *,
        profile_dir: Optional[Path] = None,
        state_dir: Optional[Path] = None,
        executable_finder: Callable[[], Optional[str]] = find_chromium_executable,
    ):
        self.profile_dir = Path(profile_dir) if profile_dir else (ROOT / "data" / "browser_profile")
        self.state_dir = Path(state_dir) if state_dir else (ROOT / "data")
        self._executable_finder = executable_finder
        self._state_lock = threading.RLock()
        self._run_lock = threading.Lock()
        self._connect_proc: Optional[subprocess.Popen] = None
        self._state: Dict[str, Any] = self._default_state()
        self._load_state()

    @staticmethod
    def _default_state() -> Dict[str, Any]:
        return {
            "enabled": True,
            "headless": False,  # Janela visível por padrão conforme escolha do usuário
            "cooldown_minutes": DEFAULT_LINKEDIN_COOLDOWN_MINUTES,
            "max_daily_searches": DEFAULT_LINKEDIN_MAX_DAILY,
            "custom_limits": False,
            "max_scrolls": DEFAULT_LINKEDIN_MAX_SCROLLS,
            "daily_date": date.today().isoformat(),
            "daily_count": 0,
            "last_run_at": None,
            "last_run_ts": 0.0,
            "last_status": "not_connected",
            "last_error": "",
            "last_query": "",
            "last_imported": 0,
            "last_cards_total": 0,
        }

    def _state_path(self) -> Path:
        return self.state_dir / "linkedin_worker_state.json"

    def _load_state(self) -> None:
        path = self._state_path()
        if not path.is_file():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(raw, dict):
            return
        with self._state_lock:
            for key in self._state:
                if key in raw:
                    self._state[key] = raw[key]
            # Migrate old automatic throttle defaults (20m cooldown / 15-per-day cap)
            # so Modo Automático / Buscar always include LinkedIn in parallel.
            if (
                raw.get("custom_limits") is not True
                and raw.get("cooldown_minutes") == 20
                and raw.get("max_daily_searches") == 15
            ):
                self._state["cooldown_minutes"] = DEFAULT_LINKEDIN_COOLDOWN_MINUTES
                self._state["max_daily_searches"] = DEFAULT_LINKEDIN_MAX_DAILY
                self._save_state_locked()
            self._rollover_day_locked()

    def _save_state_locked(self) -> None:
        try:
            atomic_write_json(self._state_path(), dict(self._state), indent=2)
        except OSError as exc:
            logger.debug("Falha ao persistir linkedin_worker_state.json: %s", exc)

    def _rollover_day_locked(self) -> None:
        today_str = date.today().isoformat()
        if self._state.get("daily_date") != today_str:
            self._state["daily_date"] = today_str
            self._state["daily_count"] = 0

    def _profile_has_session_files(self) -> bool:
        default_dir = self.profile_dir / "Default"
        if not default_dir.is_dir():
            return False
        return (
            (default_dir / "Network" / "Cookies").is_file()
            or (default_dir / "Cookies").is_file()
            or (default_dir / "Preferences").is_file()
        )

    def _read_live_cdp(self) -> Optional[Tuple[int, str, list]]:
        port_file = self.profile_dir / "DevToolsActivePort"
        if not port_file.is_file():
            return None
        try:
            lines = [ln.strip() for ln in port_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
            port = int(lines[0])
            browser_ws_path = lines[1] if len(lines) > 1 else "/devtools/browser"
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=0.6) as resp:
                tabs = json.loads(resp.read().decode("utf-8"))
            if isinstance(tabs, list):
                return port, browser_ws_path, tabs
        except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
            return None
        return None

    @staticmethod
    def _is_authenticated_linkedin_url(url: str) -> bool:
        low = (url or "").lower()
        if "linkedin.com" not in low:
            return False
        if any(m in low for m in (*_LOGIN_MARKERS, *_CHECKPOINT_MARKERS)):
            return False
        return any(
            seg in low
            for seg in ("/feed", "/in/", "/mynetwork", "/jobs", "/messaging", "/notifications", "/search/")
        )

    def _refresh_status_from_live_tabs_locked(self) -> None:
        live = self._read_live_cdp()
        if not live:
            return
        _port, _bpath, tabs = live
        for tab in tabs:
            if not isinstance(tab, dict):
                continue
            tab_url = str(tab.get("url") or "")
            low = tab_url.lower()
            if "linkedin.com" not in low:
                continue
            if any(m in low for m in _CHECKPOINT_MARKERS):
                self._state["last_status"] = "checkpoint_required"
                self._state["last_error"] = "LinkedIn solicitou verificação/CAPTCHA na janela do navegador."
                self._save_state_locked()
                return
            if self._is_authenticated_linkedin_url(tab_url):
                self._state["last_status"] = "connected"
                self._state["last_error"] = ""
                self._save_state_locked()
                return

    def _is_profile_locked(self) -> bool:
        return (self.profile_dir / "lockfile").exists() or (self.profile_dir / "SingletonLock").is_symlink()

    def _is_connect_window_open_locked(self) -> bool:
        if self._connect_proc is not None and self._connect_proc.poll() is None:
            return True
        return self._is_profile_locked() and self._read_live_cdp() is None

    def get_status(self) -> Dict[str, Any]:
        """Return safe UI status, quotas, cooldown timer, and browser availability."""
        exe = self._executable_finder()
        with self._state_lock:
            self._rollover_day_locked()
            self._refresh_status_from_live_tabs_locked()
            has_profile = self._profile_has_session_files()
            status_val = str(self._state.get("last_status") or "not_connected")
            if not exe:
                status_val = "unavailable"
            elif status_val == "not_connected" and has_profile:
                status_val = "connected"

            raw_cd = self._state.get("cooldown_minutes")
            cooldown_min = max(0, int(DEFAULT_LINKEDIN_COOLDOWN_MINUTES if raw_cd is None else raw_cd))
            raw_max = self._state.get("max_daily_searches")
            max_daily = max(0, int(DEFAULT_LINKEDIN_MAX_DAILY if raw_max is None else raw_max))
            cooldown_sec = cooldown_min * 60
            elapsed = max(0.0, time.time() - float(self._state.get("last_run_ts") or 0.0))
            cooldown_rem = max(0, int(cooldown_sec - elapsed)) if (cooldown_sec > 0 and float(self._state.get("last_run_ts") or 0.0) > 0) else 0

            return {
                "status": status_val,
                "browser_available": bool(exe),
                "browser_name": Path(exe).stem if exe else None,
                "profile_initialized": has_profile,
                "login_window_open": self._is_connect_window_open_locked(),
                "enabled": bool(self._state.get("enabled", True)),
                "headless": bool(self._state.get("headless", False)),
                "cooldown_minutes": cooldown_min,
                "max_daily_searches": max_daily,
                "max_scrolls": int(self._state.get("max_scrolls") or DEFAULT_LINKEDIN_MAX_SCROLLS),
                "daily_date": self._state.get("daily_date"),
                "daily_count": int(self._state.get("daily_count") or 0),
                "cooldown_remaining_seconds": cooldown_rem,
                "last_run_at": self._state.get("last_run_at"),
                "last_error": str(self._state.get("last_error") or ""),
                "last_query": str(self._state.get("last_query") or ""),
                "last_imported": int(self._state.get("last_imported") or 0),
                "last_cards_total": int(self._state.get("last_cards_total") or 0),
            }

    def update_config(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        """Update worker settings cleanly and persist."""
        with self._state_lock:
            if patch.get("enabled") is not None:
                self._state["enabled"] = bool(patch["enabled"])
            if patch.get("headless") is not None:
                self._state["headless"] = bool(patch["headless"])
            if patch.get("cooldown_minutes") is not None:
                self._state["cooldown_minutes"] = max(0, min(180, int(patch["cooldown_minutes"])))
                self._state["custom_limits"] = True
            if patch.get("max_daily_searches") is not None:
                self._state["max_daily_searches"] = max(0, min(500, int(patch["max_daily_searches"])))
                self._state["custom_limits"] = True
            if patch.get("max_scrolls") is not None:
                self._state["max_scrolls"] = max(1, min(8, int(patch["max_scrolls"])))
            self._save_state_locked()
        return self.get_status()

    def _spawn_browser(
        self,
        target_url: str,
        *,
        headless: bool,
        enable_cdp: bool = True,
    ) -> Tuple[subprocess.Popen, Optional[int], Optional[str]]:
        exe = self._executable_finder()
        if not exe:
            raise RuntimeError("Chrome ou Microsoft Edge não encontrado no sistema.")
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        port_file = self.profile_dir / "DevToolsActivePort"
        if port_file.is_file():
            try:
                port_file.unlink()
            except OSError:
                pass

        args = [
            exe,
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if enable_cdp:
            args.append("--remote-debugging-port=0")
        if headless:
            args.append("--headless=new")
        else:
            args.append("--new-window")
        args.append(target_url)

        proc = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not enable_cdp:
            time.sleep(0.4)
            return proc, None, None

        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("O navegador isolado encerrou antes de abrir a depuração CDP.")
            live = self._read_live_cdp()
            if live:
                port, browser_ws_path, _tabs = live
                return proc, port, browser_ws_path
            time.sleep(0.15)
        self._terminate_proc(proc)
        raise TimeoutError("Tempo esgotado aguardando o navegador isolado inicializar.")

    def _close_browser_process(
        self,
        port: Optional[int] = None,
        browser_ws_path: Optional[str] = None,
        proc: Optional[subprocess.Popen] = None,
    ) -> None:
        if port and browser_ws_path:
            try:
                from websockets.sync.client import connect

                with connect(f"ws://127.0.0.1:{port}{browser_ws_path}", open_timeout=2, close_timeout=1) as bws:
                    _cdp_call(bws, 998, "Browser.close", timeout=3.0)
                if proc is not None and proc.poll() is None:
                    proc.wait(timeout=4)
            except Exception:
                pass
        if proc is not None and proc.poll() is None:
            self._terminate_proc(proc)

    @staticmethod
    def _terminate_proc(proc: Optional[subprocess.Popen]) -> None:
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def open_connect_window(self) -> Dict[str, Any]:
        """Open a clean non-debugged browser window so Google/LinkedIn sign-in works natively."""
        live = self._read_live_cdp()
        if live:
            port, bpath, _tabs = live
            self._close_browser_process(port=port, browser_ws_path=bpath, proc=self._connect_proc)
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and self._is_profile_locked():
                time.sleep(0.2)

        with self._state_lock:
            already_open = self._is_connect_window_open_locked()

        if already_open:
            exe = self._executable_finder()
            if exe:
                subprocess.Popen(
                    [
                        exe,
                        f"--user-data-dir={self.profile_dir}",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--new-window",
                        LINKEDIN_FEED_URL,
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        else:
            proc, _port, _bpath = self._spawn_browser(LINKEDIN_FEED_URL, headless=False, enable_cdp=False)
            with self._state_lock:
                self._connect_proc = proc

        with self._state_lock:
            self._state["enabled"] = True
            self._state["last_status"] = "awaiting_login"
            self._state["last_error"] = ""
            self._save_state_locked()
        return self.get_status()

    def verify_connection(self) -> Dict[str, Any]:
        """Verify live session status using an open tab or a quick isolated check."""
        live = self._read_live_cdp()
        if live:
            status = self.get_status()
            if status["status"] == "awaiting_login":
                return {
                    **status,
                    "ok": False,
                    "message": "Ainda na tela de login do LinkedIn. Entre na sua conta na janela aberta.",
                }
            return {**status, "ok": status["status"] == "connected"}

        with self._state_lock:
            if self._is_connect_window_open_locked():
                return {
                    **self.get_status(),
                    "ok": False,
                    "message": "Feche a janela do navegador onde você fez login (clicando no X) para concluirmos a verificação.",
                }

        if not self._profile_has_session_files():
            with self._state_lock:
                self._state["last_status"] = "not_connected"
                self._save_state_locked()
            return {**self.get_status(), "ok": False}

        from websockets.sync.client import connect

        with self._run_lock:
            proc: Optional[subprocess.Popen] = None
            port: Optional[int] = None
            bpath: Optional[str] = None
            try:
                proc, port, bpath = self._spawn_browser(
                    LINKEDIN_FEED_URL,
                    headless=bool(self._state.get("headless", False)),
                    enable_cdp=True,
                )
                assert port is not None
                ws_url = self._wait_page_ws_url(port, match_host="linkedin.com")
                with connect(ws_url, open_timeout=6, close_timeout=2, max_size=8 * 1024 * 1024) as ws:
                    info = self._wait_and_inspect_page(ws, timeout=10.0)
                with self._state_lock:
                    if info.get("isCheckpoint"):
                        self._state["last_status"] = "checkpoint_required"
                        self._state["last_error"] = "LinkedIn pediu verificação/CAPTCHA. Resolva na janela visível."
                    elif info.get("isLogin"):
                        self._state["last_status"] = "login_required"
                        self._state["last_error"] = "Sessão não autenticada; clique em Conectar LinkedIn e entre novamente."
                    else:
                        self._state["enabled"] = True
                        self._state["last_status"] = "connected"
                        self._state["last_error"] = ""
                    self._save_state_locked()
            finally:
                self._close_browser_process(port=port, browser_ws_path=bpath, proc=proc)
        res = self.get_status()
        return {**res, "ok": res["status"] == "connected"}

    def disconnect(self) -> Dict[str, Any]:
        """Close any worker browser process and remove isolated profile cookies."""
        with self._run_lock:
            with self._state_lock:
                self._terminate_proc(self._connect_proc)
                self._connect_proc = None
            live = self._read_live_cdp()
            if live:
                port, bpath, _tabs = live
                try:
                    from websockets.sync.client import connect

                    with connect(f"ws://127.0.0.1:{port}{bpath}", open_timeout=2, close_timeout=1) as ws:
                        _cdp_call(ws, 1, "Browser.close", timeout=2.0)
                    time.sleep(0.6)
                except Exception:
                    pass
            shutil.rmtree(self.profile_dir, ignore_errors=True)
            with self._state_lock:
                self._state["last_status"] = "not_connected"
                self._state["last_error"] = ""
                self._state["daily_count"] = 0
                self._state["last_run_ts"] = 0.0
                self._state["last_run_at"] = None
                self._save_state_locked()
        return self.get_status()

    def shutdown(self) -> None:
        """Terminate any connect browser window owned by this worker on server shutdown."""
        with self._state_lock:
            self._terminate_proc(self._connect_proc)
            self._connect_proc = None

    def _wait_page_ws_url(self, port: int, *, target_id: Optional[str] = None, match_host: str = "linkedin.com") -> str:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1.5) as resp:
                    tabs = json.loads(resp.read().decode("utf-8"))
                for tab in tabs:
                    if not isinstance(tab, dict) or tab.get("type") != "page":
                        continue
                    if target_id and tab.get("id") != target_id:
                        continue
                    ws_url = tab.get("webSocketDebuggerUrl")
                    url = str(tab.get("url") or "").lower()
                    if ws_url and (target_id or match_host in url or "about:blank" not in url):
                        return str(ws_url)
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                pass
            time.sleep(0.2)
        raise TimeoutError("Não foi possível conectar à aba do LinkedIn no navegador isolado.")

    @staticmethod
    def _wait_and_inspect_page(
        ws: Any,
        *,
        timeout: float = 15.0,
        wait_for_results: bool = False,
    ) -> dict:
        deadline = time.monotonic() + timeout
        results_deadline: Optional[float] = None
        req_id = 10
        last_info: dict = {}
        while time.monotonic() < deadline:
            req_id += 1
            info = _cdp_eval(ws, req_id, _CHECK_BLOCK_JS, timeout=6.0)
            if isinstance(info, dict):
                last_info = info
                if info.get("isCheckpoint") or info.get("isLogin"):
                    return info
                if info.get("ready") == "complete" and info.get("hasFeedUi"):
                    if not wait_for_results or "hasResultContent" not in info:
                        return info
                    if info.get("hasResultContent") or info.get("hasEmptyState"):
                        return info
                    if results_deadline is None:
                        results_deadline = min(deadline, time.monotonic() + 8.0)
                    elif time.monotonic() >= results_deadline:
                        return info
            time.sleep(0.5)
        return last_info

    @staticmethod
    def _collect_visible_posts(
        ws: Any,
        req_id: int,
        posts_by_key: Dict[str, dict],
        max_cards_total: int,
    ) -> Tuple[int, int]:
        """Expand 'see more' buttons, extract visible LinkedIn cards, and deduplicate by URN/prefix."""
        req_id += 1
        expanded = _cdp_eval(ws, req_id, _EXPAND_SEE_MORE_JS, timeout=6.0)
        if isinstance(expanded, (int, float)) and expanded > 0:
            time.sleep(0.35)
        req_id += 1
        extracted = _cdp_eval(ws, req_id, _EXTRACT_POSTS_JS, timeout=10.0)
        if isinstance(extracted, dict):
            cards_count = int(extracted.get("cards_total") or 0)
            max_cards_total = max(max_cards_total, cards_count)
            for item in extracted.get("posts") or []:
                if not isinstance(item, dict) or not item.get("raw_text"):
                    continue
                fp = str(item.get("url") or "").strip() or " ".join(str(item["raw_text"]).split())[:140].lower()
                existing = posts_by_key.get(fp)
                if not existing or len(str(item["raw_text"])) > len(str(existing.get("raw_text") or "")):
                    posts_by_key[fp] = item
        return req_id, max_cards_total

    def _handle_block_state(self, page_info: dict) -> Optional[Dict[str, Any]]:
        if page_info.get("isCheckpoint"):
            with self._state_lock:
                self._state["last_status"] = "checkpoint_required"
                self._state["last_error"] = "LinkedIn exibiu verificação de segurança/CAPTCHA. Abra a janela e conclua manualmente."
                self._save_state_locked()
            return {"ok": False, "skipped_reason": "checkpoint_required", "posts": [], "error": self._state["last_error"]}
        if page_info.get("isLogin"):
            with self._state_lock:
                self._state["last_status"] = "login_required"
                self._state["last_error"] = "Sessão do LinkedIn expirou; clique em Conectar LinkedIn para entrar novamente."
                self._save_state_locked()
            return {"ok": False, "skipped_reason": "login_required", "posts": [], "error": self._state["last_error"]}
        return None

    def search_content_posts(
        self,
        query: str,
        *,
        force: bool = False,
        should_stop: Optional[Callable[[], bool]] = None,
        days: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Collect visible recruiter hiring posts from LinkedIn content search via isolated CDP."""
        exe = self._executable_finder()
        if not exe:
            return {"ok": False, "skipped_reason": "unavailable", "posts": []}

        with self._state_lock:
            self._rollover_day_locked()
            self._refresh_status_from_live_tabs_locked()
            if not self._state.get("enabled", True):
                return {"ok": False, "skipped_reason": "disabled", "posts": []}
            if not self._profile_has_session_files():
                return {"ok": False, "skipped_reason": "not_connected", "posts": []}

            cur_status = str(self._state.get("last_status") or "")
            if cur_status in ("login_required", "checkpoint_required", "awaiting_login") and not force:
                return {"ok": False, "skipped_reason": cur_status, "posts": [], "error": self._state.get("last_error", "")}

            raw_max = self._state.get("max_daily_searches")
            max_daily = max(0, int(DEFAULT_LINKEDIN_MAX_DAILY if raw_max is None else raw_max))
            if not force and max_daily > 0 and int(self._state.get("daily_count") or 0) >= max_daily:
                return {"ok": False, "skipped_reason": "daily_limit", "posts": []}

            raw_cd = self._state.get("cooldown_minutes")
            cooldown_sec = max(0, int(DEFAULT_LINKEDIN_COOLDOWN_MINUTES if raw_cd is None else raw_cd)) * 60
            last_ts = float(self._state.get("last_run_ts") or 0.0)
            now = time.time()
            if not force and cooldown_sec > 0 and last_ts > 0 and (now - last_ts) < cooldown_sec:
                return {
                    "ok": False,
                    "skipped_reason": "cooldown",
                    "cooldown_remaining_seconds": int(cooldown_sec - (now - last_ts)),
                    "posts": [],
                }

            headless = bool(self._state.get("headless", False))
            max_scrolls = max(1, min(8, int(self._state.get("max_scrolls") or DEFAULT_LINKEDIN_MAX_SCROLLS)))

        if not self._run_lock.acquire(blocking=False):
            return {"ok": False, "skipped_reason": "busy", "posts": []}

        if self._is_connect_window_open_locked():
            self._run_lock.release()
            return {
                "ok": False,
                "skipped_reason": "awaiting_login",
                "posts": [],
                "error": "Feche a janela de login do LinkedIn aberta para liberar a coleta automática.",
            }

        raw_terms = [t.strip() for t in (query or "").split(",") if t.strip()]
        terms: List[str] = []
        seen_terms: set[str] = set()
        for raw_t in raw_terms:
            cleaned = _clean_linkedin_term(raw_t) or raw_t
            key = cleaned.lower()
            if key not in seen_terms:
                seen_terms.add(key)
                terms.append(cleaned)
            if len(terms) >= 2:
                break
        if not terms:
            terms = ["vaga"]

        date_posted = days_to_linkedin_date_posted(days)
        search_url = build_linkedin_content_search_url(terms[0], date_posted=date_posted, include_vaga_suffix=True)
        spawned_proc: Optional[subprocess.Popen] = None
        spawned_port: Optional[int] = None
        spawned_bpath: Optional[str] = None
        created_target_id: Optional[str] = None
        browser_ws_url: Optional[str] = None

        try:
            from websockets.sync.client import connect

            live = self._read_live_cdp()
            if live:
                port, bpath, _tabs = live
                browser_ws_url = f"ws://127.0.0.1:{port}{bpath}"
                with connect(browser_ws_url, open_timeout=5, close_timeout=2) as bws:
                    created = _cdp_call(bws, 1, "Target.createTarget", {"url": search_url}, timeout=8.0)
                    created_target_id = str(created.get("targetId") or "")
                page_ws_url = self._wait_page_ws_url(port, target_id=created_target_id)
            else:
                spawned_proc, spawned_port, spawned_bpath = self._spawn_browser(
                    search_url,
                    headless=headless,
                    enable_cdp=True,
                )
                assert spawned_port is not None
                page_ws_url = self._wait_page_ws_url(spawned_port, match_host="linkedin.com")

            posts: List[dict] = []
            max_cards_total = 0
            with connect(page_ws_url, open_timeout=8, close_timeout=2, max_size=16 * 1024 * 1024) as ws:
                page_info = self._wait_and_inspect_page(ws, timeout=18.0, wait_for_results=True)
                blocked = self._handle_block_state(page_info)
                if blocked:
                    return blocked

                req_id = 100
                if (
                    (page_info.get("hasEmptyState") or page_info.get("hasResultContent") is False)
                    and not (should_stop and should_stop())
                ):
                    fallback_urls: List[str] = [
                        build_linkedin_content_search_url(
                            terms[0],
                            date_posted="past-month",
                            include_vaga_suffix=False,
                        )
                    ]
                    if len(terms) > 1:
                        fallback_urls.append(
                            build_linkedin_content_search_url(
                                terms[1],
                                date_posted=date_posted,
                                include_vaga_suffix=True,
                            )
                        )
                    for fb_url in fallback_urls:
                        if should_stop and should_stop():
                            break
                        if fb_url == search_url:
                            continue
                        req_id += 1
                        _cdp_call(ws, req_id, "Page.navigate", {"url": fb_url}, timeout=10.0)
                        time.sleep(0.4)
                        page_info = self._wait_and_inspect_page(ws, timeout=15.0, wait_for_results=True)
                        blocked = self._handle_block_state(page_info)
                        if blocked:
                            return blocked
                        search_url = fb_url
                        if not page_info.get("hasEmptyState") and page_info.get("hasResultContent") is not False:
                            break
                posts_by_key: Dict[str, dict] = {}
                for _step in range(max_scrolls):
                    if should_stop and should_stop():
                        break
                    req_id, max_cards_total = self._collect_visible_posts(ws, req_id, posts_by_key, max_cards_total)
                    req_id += 1
                    _cdp_eval(ws, req_id, "window.scrollBy(0, Math.round(window.innerHeight * 0.85))", timeout=5.0)
                    pause = random.uniform(2.2, 3.8)
                    end_wait = time.monotonic() + pause
                    while time.monotonic() < end_wait:
                        if should_stop and should_stop():
                            break
                        time.sleep(0.25)

                if not (should_stop and should_stop()):
                    req_id, max_cards_total = self._collect_visible_posts(ws, req_id, posts_by_key, max_cards_total)
                posts = list(posts_by_key.values())
                max_cards_total = max(max_cards_total, len(posts))

            with self._state_lock:
                self._rollover_day_locked()
                self._state["daily_count"] = int(self._state.get("daily_count") or 0) + 1
                self._state["last_run_ts"] = time.time()
                self._state["last_run_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self._state["last_status"] = "connected"
                self._state["last_error"] = ""
                self._state["last_query"] = query
                self._state["last_imported"] = len(posts)
                self._state["last_cards_total"] = max_cards_total
                self._save_state_locked()

            return {"ok": True, "posts": posts, "query": query, "cards_total": max_cards_total}
        except Exception as exc:
            err_msg = str(exc)[:200]
            logger.warning("LinkedInBrowserWorker falhou ao coletar '%s': %s", query, err_msg)
            with self._state_lock:
                self._state["last_error"] = err_msg
                self._state["last_run_ts"] = time.time()
                self._save_state_locked()
            return {"ok": False, "error": err_msg, "posts": []}
        finally:
            if created_target_id and browser_ws_url:
                try:
                    from websockets.sync.client import connect

                    with connect(browser_ws_url, open_timeout=2, close_timeout=1) as bws:
                        _cdp_call(bws, 999, "Target.closeTarget", {"targetId": created_target_id}, timeout=3.0)
                except Exception:
                    pass
            if spawned_proc is not None:
                self._close_browser_process(
                    port=spawned_port,
                    browser_ws_path=spawned_bpath,
                    proc=spawned_proc,
                )
            self._run_lock.release()
