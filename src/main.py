"""Entry point: python src/main.py --profile <name> [--dry-run]"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import fetcher  # noqa: E402

log = logging.getLogger("digest")


def run_profile(name: str, dry_run: bool) -> None:
    settings, profile = fetcher.load_profile(name)
    log.info("=== Profile '%s' ===", name)

    candidates = fetcher.fetch_candidates(profile, settings)
    log.info("%d candidate article(s) after date and keyword filtering", len(candidates))

    if dry_run:
        for article in candidates:
            log.info("  %s | %s | %s", article["published"], article["source"], article["title"])
        return
    if not candidates:
        log.info("Nothing to evaluate; no digest written")
        return

    from src import compiler, filter as llm_filter

    accepted, scored = llm_filter.evaluate(candidates, profile, settings)
    log.info("%d of %d scored article(s) passed signal_threshold=%s", len(accepted), scored, profile["signal_threshold"])
    if not accepted:
        log.info("No high-signal articles this week; no digest written")
        return

    path = compiler.compile_digest(name, profile, settings, accepted, evaluated=scored)
    log.info("Digest written to %s", path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a weekly topic digest for a profile.")
    parser.add_argument("--profile", help="profile name from config/profiles.yaml, or 'all'")
    parser.add_argument("--list", action="store_true", help="list available profiles and exit")
    parser.add_argument("--dry-run", action="store_true", help="fetch and pre-filter only; no LLM calls, no file output")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    _, profiles = fetcher.load_config()
    if args.list:
        for name, profile in profiles.items():
            print(f"{name}: {profile.get('description', '')}")
        return 0
    if not args.profile:
        parser.error("--profile is required (use --list to see available profiles)")
    if not args.dry_run and not os.environ.get("GEMINI_API_KEY"):
        log.error("GEMINI_API_KEY is not set (use --dry-run to test fetching without it)")
        return 1

    names = list(profiles) if args.profile == "all" else [args.profile]
    exit_code = 0
    for name in names:
        try:
            run_profile(name, args.dry_run)
        except Exception as exc:  # keep going so one broken profile doesn't block the others
            log.error("Profile '%s' failed: %s", name, exc)
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
