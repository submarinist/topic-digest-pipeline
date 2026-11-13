"""Load a profile and fetch recent, keyword-relevant articles from its RSS/Atom feeds."""

from __future__ import annotations

import calendar
import html
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests
import yaml

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "profiles.yaml"

DEFAULT_SETTINGS = {
    "model": "gemini-3.5-flash",
    "lookback_days": 7,
    "max_candidates": 80,
    "batch_size": 8,
    "request_pause_seconds": 6,
    "output_language": "English",
    "max_items": 10,
    "max_source_share": 0.5,
}

USER_AGENT = "topic-digest-pipeline/1.0 (RSS reader)"
SUMMARY_MAX_CHARS = 2000


def load_config(path: Path = CONFIG_PATH) -> tuple[dict, dict]:
    """Return (settings, profiles) from the YAML config."""
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    settings = {**DEFAULT_SETTINGS, **(config.get("settings") or {})}
    return settings, config.get("profiles") or {}


def load_profile(name: str, path: Path = CONFIG_PATH) -> tuple[dict, dict]:
    """Return (settings, profile) for the named profile."""
    settings, profiles = load_config(path)
    if name not in profiles:
        raise KeyError(f"Profile '{name}' not found. Available: {', '.join(profiles) or '(none)'}")
    profile = profiles[name]
    for field in ("rss_sources", "system_prompt", "signal_threshold"):
        if not profile.get(field):
            raise ValueError(f"Profile '{name}' is missing required field '{field}'")
    return settings, profile


def _clean_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _entry_datetime(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    return None


def _entry_text(entry) -> str:
    """Longest of summary / full content, cleaned of HTML."""
    candidates = [entry.get("summary", "")]
    candidates += [c.get("value", "") for c in entry.get("content", [])]
    return max((_clean_text(c) for c in candidates), key=len)


def _keyword_pattern(keywords: list[str]) -> re.Pattern | None:
    if not keywords:
        return None
    alternatives = "|".join(re.escape(k.strip()) for k in keywords if k and k.strip())
    return re.compile(rf"(?<!\w)(?:{alternatives})s?(?!\w)", re.IGNORECASE)


def fetch_candidates(profile: dict, settings: dict, now: datetime | None = None) -> list[dict]:
    """Fetch all feeds of a profile; return recent, deduplicated, keyword-matching articles (newest first)."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=settings["lookback_days"])
    pattern = _keyword_pattern(profile.get("keywords") or [])

    articles: dict[str, dict] = {}
    for source in profile["rss_sources"]:
        name, url = source["name"], source["url"]
        try:
            response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
        except requests.RequestException as exc:
            log.warning("Source '%s' failed: %s", name, exc)
            continue
        if feed.bozo and not feed.entries:
            log.warning("Source '%s' is not a valid feed: %s", name, feed.get("bozo_exception"))
            continue

        use_keywords = pattern is not None and source.get("keyword_filter", True)
        recent = matched = 0
        for entry in feed.entries:
            published = _entry_datetime(entry)
            link = entry.get("link")
            title = _clean_text(entry.get("title", ""))
            if not published or published < cutoff or not link or not title:
                continue
            recent += 1
            text = _entry_text(entry)
            if use_keywords and not pattern.search(f"{title} {text}"):
                continue
            matched += 1
            articles.setdefault(
                link,
                {
                    "title": title,
                    "link": link,
                    "source": name,
                    "published": published.date().isoformat(),
                    "summary": text[:SUMMARY_MAX_CHARS],
                },
            )
        log.info("Source '%s': %d entries, %d recent, %d passed pre-filter", name, len(feed.entries), recent, matched)

    result = sorted(articles.values(), key=lambda a: a["published"], reverse=True)
    cap = settings["max_candidates"]
    if len(result) > cap:
        log.warning("%d candidates exceed max_candidates=%d; keeping the newest %d", len(result), cap, cap)
        result = result[:cap]
    return result
