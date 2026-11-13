"""Score candidate articles with Gemini using the profile's system prompt; keep the high-signal ones."""

from __future__ import annotations

import json
import logging
import os
import time

from google import genai
from google.genai import errors, types

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 4
RETRYABLE_CODES = {429, 500, 502, 503, 504}
FATAL_CODES = {400, 401, 403, 404}
REQUEST_TIMEOUT_MS = 120_000
MAX_CONSECUTIVE_FAILURES = 2  # e.g. daily quota exhausted: stop instead of retrying every batch

RESPONSE_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "id": {"type": "INTEGER"},
            "signal_score": {"type": "INTEGER"},
            "core_idea": {"type": "STRING"},
            "key_takeaways": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": ["id", "signal_score", "core_idea", "key_takeaways"],
    },
}

SCORING_INSTRUCTIONS = """
For every article you receive, return one JSON object with:
- "id": the article's id, unchanged
- "signal_score": integer 1-10. 1-3 = noise, marketing or a superficial overview; 4-7 = relevant but incremental;
  8-10 = substantive, novel and actionable for an expert in this domain. Be strict: most articles deserve less than 8.
- "core_idea": the central insight in 1-2 sentences
- "key_takeaways": exactly 3 concise, concrete bullet points

Judge only what the provided text supports; do not invent details. Write core_idea and key_takeaways in {language}.
Return a JSON array with exactly one object per article.
"""


def _build_prompt(batch: list[dict]) -> str:
    parts = ["Evaluate the following articles.\n"]
    for i, article in enumerate(batch):
        parts.append(
            f"### Article id={i}\n"
            f"Source: {article['source']}\n"
            f"Title: {article['title']}\n"
            f"Text: {article['summary'] or '(no summary available)'}\n"
        )
    return "\n".join(parts)


def _generate(client: genai.Client, model: str, config: types.GenerateContentConfig, prompt: str) -> list[dict]:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.models.generate_content(model=model, contents=prompt, config=config)
            data = json.loads(response.text or "")
            if not isinstance(data, list):
                raise ValueError("response is not a JSON array")
            return data
        except errors.APIError as exc:
            if exc.code not in RETRYABLE_CODES or attempt == MAX_ATTEMPTS:
                raise
            reason = f"API error {exc.code}"
        except ValueError as exc:  # includes json.JSONDecodeError
            if attempt == MAX_ATTEMPTS:
                raise
            reason = f"malformed response ({exc})"
        delay = 15 * 2 ** (attempt - 1)
        log.warning("%s; retrying in %ds (attempt %d/%d)", reason, delay, attempt, MAX_ATTEMPTS)
        time.sleep(delay)
    raise RuntimeError("unreachable")


def evaluate(articles: list[dict], profile: dict, settings: dict) -> tuple[list[dict], int]:
    """Return (articles scoring >= signal_threshold enriched with the LLM evaluation, best first; number actually scored)."""
    if not articles:
        return [], 0

    client = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),
    )
    model = os.environ.get("GEMINI_MODEL") or settings["model"]
    threshold = int(profile["signal_threshold"])
    config = types.GenerateContentConfig(
        system_instruction=profile["system_prompt"].strip()
        + "\n"
        + SCORING_INSTRUCTIONS.format(language=settings["output_language"]),
        response_mime_type="application/json",
        response_schema=RESPONSE_SCHEMA,
        temperature=0.2,
    )

    batch_size = max(1, int(settings["batch_size"]))
    batches = [articles[i : i + batch_size] for i in range(0, len(articles), batch_size)]
    accepted: list[dict] = []
    failed = 0
    scored = 0
    consecutive_failures = 0

    for n, batch in enumerate(batches, 1):
        if n > 1:
            time.sleep(settings["request_pause_seconds"])
        try:
            results = _generate(client, model, config, _build_prompt(batch))
        except Exception as exc:  # API errors, malformed JSON, network timeouts: isolate the batch
            if isinstance(exc, errors.APIError) and exc.code in FATAL_CODES:
                # Bad key, unknown model or malformed request: every batch would fail the same way.
                raise RuntimeError(f"Gemini request rejected (model '{model}'): {exc}") from exc
            failed += 1
            consecutive_failures += 1
            log.error("Batch %d/%d failed, skipping %d articles: %s", n, len(batches), len(batch), exc)
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                if not accepted and failed == n:
                    raise RuntimeError(f"Gemini keeps failing (model '{model}'): {exc}") from exc
                log.error("Stopping after %d consecutive failures; %d batch(es) not evaluated", consecutive_failures, len(batches) - n)
                break
            continue
        consecutive_failures = 0

        seen: set[int] = set()
        for item in results:
            idx = item.get("id")
            if not isinstance(idx, int) or not 0 <= idx < len(batch) or idx in seen:
                continue
            seen.add(idx)
            scored += 1
            score = item.get("signal_score", 0)
            log.info("  [%s/10] %s", score, batch[idx]["title"])
            if score >= threshold:
                accepted.append(
                    {
                        **batch[idx],
                        "signal_score": score,
                        "core_idea": item.get("core_idea", "").strip(),
                        "key_takeaways": [t.strip() for t in item.get("key_takeaways", []) if t.strip()][:3],
                    }
                )
        if len(seen) < len(batch):
            log.warning("Batch %d/%d: model skipped %d article(s)", n, len(batches), len(batch) - len(seen))

    if failed == len(batches):
        raise RuntimeError("All LLM requests failed; no digest produced")

    accepted.sort(key=lambda a: a["signal_score"], reverse=True)
    return accepted, scored
