"""Compile accepted articles into a Markdown digest at digests/YYYY-WW-<profile>.md."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIGESTS_DIR = ROOT / "digests"


def digest_path(profile_name: str, now: datetime, out_dir: Path = DIGESTS_DIR) -> Path:
    year, week, _ = now.isocalendar()
    return out_dir / f"{year}-{week:02d}-{profile_name}.md"


def links_path(profile_name: str, now: datetime, out_dir: Path = DIGESTS_DIR) -> Path:
    return digest_path(profile_name, now, out_dir).with_name(
        digest_path(profile_name, now, out_dir).stem + "-links.txt"
    )


def source_url(link: str) -> str:
    """URL to give NotebookLM as a website source: full-text PDF for arXiv, the article link otherwise."""
    return re.sub(r"^https?://(?:www\.|export\.)?arxiv\.org/abs/", "https://arxiv.org/pdf/", link)


def render_links(items: list[dict]) -> str:
    """One URL per line, ready to paste into NotebookLM's 'Add source -> Website' dialog."""
    return "\n".join(source_url(item["link"]) for item in items) + "\n"


def select_items(items: list[dict], profile: dict, settings: dict) -> list[dict]:
    """Keep the top `max_items` by score, with at most `max_source_share` of them from any one source.

    Both limits can be set in `settings` and overridden per profile. Ties keep the input order.
    """
    max_items = int(profile.get("max_items", settings["max_items"]))
    share = float(profile.get("max_source_share", settings["max_source_share"]))
    per_source = max(1, int(max_items * share))

    selected: list[dict] = []
    counts: dict[str, int] = {}
    for item in sorted(items, key=lambda a: a["signal_score"], reverse=True):
        if len(selected) >= max_items:
            break
        if counts.get(item["source"], 0) >= per_source:
            continue
        counts[item["source"]] = counts.get(item["source"], 0) + 1
        selected.append(item)
    return selected


def render(
    profile_name: str, profile: dict, settings: dict, items: list[dict], evaluated: int, passed: int, now: datetime
) -> str:
    year, week, _ = now.isocalendar()
    start = (now - timedelta(days=settings["lookback_days"])).date().isoformat()
    end = now.date().isoformat()

    lines = [
        "---",
        f'title: "Topic Digest: {profile_name} — {year}-W{week:02d}"',
        f"profile: {profile_name}",
        f"week: {year}-W{week:02d}",
        f"period: {start}..{end}",
        f"generated: {now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "---",
        "",
        f"# Topic Digest: {profile_name} — Week {week}, {year}",
        "",
        f"**Focus:** {profile.get('description', profile_name)}",
        "",
        f"**Period:** {start} to {end}. "
        f"**Selection:** {passed} of {evaluated} evaluated articles scored "
        f"{profile['signal_threshold']}/10 or higher; the top {len(items)} are included.",
        "",
    ]

    for i, item in enumerate(items, 1):
        lines += [
            "---",
            "",
            f"## {i}. {item['title']}",
            "",
            f"- **Source:** {item['source']}",
            f"- **Published:** {item['published']}",
            f"- **Signal score:** {item['signal_score']}/10",
            f"- **Link:** <{item['link']}>",
            "",
            "### Core idea",
            "",
            item["core_idea"],
            "",
            "### Key takeaways",
            "",
            *[f"- {t}" for t in item["key_takeaways"]],
            "",
        ]
    return "\n".join(lines)


def compile_digest(
    profile_name: str,
    profile: dict,
    settings: dict,
    items: list[dict],
    evaluated: int,
    now: datetime | None = None,
    out_dir: Path = DIGESTS_DIR,
) -> Path:
    now = now or datetime.now(timezone.utc)
    path = digest_path(profile_name, now, out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    selected = select_items(items, profile, settings)
    path.write_text(
        render(profile_name, profile, settings, selected, evaluated, len(items), now), encoding="utf-8"
    )
    links_path(profile_name, now, out_dir).write_text(render_links(selected), encoding="utf-8")
    return path
