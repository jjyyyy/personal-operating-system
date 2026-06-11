from __future__ import annotations

import json
import os
import re
import ssl
import time
import textwrap
import urllib.error
import urllib.request

from extracted_items import extracted_item_schema, normalize_extracted_items
from voice_notes_config import TRANSIENT_API_STATUS_CODES, user_alias_hint

def ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def retry_delay(attempt: int) -> int:
    return min(2**attempt, 8)


def api_post_json(url: str, payload: dict, api_key: str) -> dict:
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(3):
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, context=ssl_context()) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code in TRANSIENT_API_STATUS_CODES and attempt < 2:
                delay = retry_delay(attempt)
                print(f"OpenAI API returned {exc.code}; retrying in {delay}s...")
                time.sleep(delay)
                continue
            raise SystemExit(f"OpenAI API request failed: {exc.code} {body}") from exc
        except urllib.error.URLError as exc:
            if attempt < 2:
                delay = retry_delay(attempt)
                print(f"OpenAI API connection failed; retrying in {delay}s...")
                time.sleep(delay)
                continue
            raise SystemExit(f"Could not reach OpenAI API: {exc.reason}") from exc
    raise SystemExit("OpenAI API request failed after retries.")


def summarize_capture(
    transcript: str,
    note_date: str,
    source_type: str,
    api_key: str,
) -> dict:
    model = os.environ.get("OPENAI_SUMMARY_MODEL", "gpt-4.1-mini")
    prompt = textwrap.dedent(
        f"""
        You are organizing captured material into a clean personal knowledge note.
        Return valid JSON with exactly these keys:
        date, title, source, topics, summary, action_items, people, annotations,
        extracted_items, raw_transcript

        Rules:
        - date must stay "{note_date}"
        - source must be "{source_type}"
        - title should be short and concrete, without a date prefix
        - topics should be a JSON array of 1-5 short strings
        - summary should be 2-5 bullet-worthy sentences combined into one paragraph
        - action_items should be a JSON array
        - people should be a JSON array containing only people or roles
          explicitly mentioned in the transcript; never infer a person
        - annotations should be a JSON array with 0-3 items
        - extracted_items should be a JSON array of independent generic items
          from the transcript. Return [] if there are no distinct items worth
          routing, reviewing, or remembering.
        - raw_transcript should preserve the transcript with light cleanup only
        - USER.md self-alias hint: {user_alias_hint()}
        - Use the self-alias hint only when context is clear.
        - If a person reference remains ambiguous, label it "unsure" instead of
          guessing whether it means the user or another person.
        - Match the transcript's primary language for title, summary, topics,
          action_items, and annotations unless a proper noun requires otherwise.
        - Do not turn analogies into topics or titles. If the transcript says an
          action is "like badminton" or "similar to serving", keep that as an
          analogy, not as the activity being practiced.
        - If the transcript context suggests a likely transcription ambiguity
          between sports terms, prefer the broader established context and mark
          uncertainty instead of inventing a new sport category.

        Extracted item policy:
        - Extract separate items for mixed memos. For example, a massage
          appointment and tennis technique note should become separate items.
        - item_type must be one of: calendar_event, reminder, task, weak_intent,
          knowledge_note.
        - Use calendar_event only for a clearly scheduled event or appointment.
        - Set calendar_ready true only when the event has enough date/time
          information to review as a calendar candidate.
        - Set needs_confirmation false only when the transcript sounds definite,
          not like maybe/consider/should.
        - Use reminder for something to remember that is not clearly scheduled.
        - Use task for a concrete action without a reminder time.
        - Use weak_intent for vague maybe/should/consider items.
        - Use knowledge_note for reusable observations, learning, or technique.
        - route_categories must use only these broad categories: calendar,
          health, sports, food, travel, work, projects, relationships, finance,
          shopping, learning, home, system.
        - Keep route_categories broad and generic. Do not use domain-specific
          project labels.
        - evidence should be a short phrase from the transcript supporting the
          extraction.

        Annotation policy:
        - Returning an empty annotations array is normal and preferred for most notes.
        - Add an annotation only when it clearly helps with a likely knowledge gap,
          a well-established concept or viewpoint, an important ambiguity, or a
          claim that needs verification.
        - Do not add generic encouragement, repeat the summary, comment on obvious
          statements, or manufacture a comment just because the field exists.
        - Match the transcript's primary language.
        - Keep each annotation concise and useful.
        - anchor_quote should be a short exact or lightly cleaned phrase from the
          transcript that the annotation comments on.
        - type must be one of: concept, clarification, verification-needed,
          counterpoint.
        - basis must be one of: established-knowledge, model-inference,
          needs-research.
        - Never present changing or uncertain information as established knowledge.
        - For XHS video evidence, distinguish creator speech, visibly observed
          evidence, OCR text, and AI interpretation. Never turn an AI visual
          inference into a claim made by the creator.
        - For tutorials or demonstrations, preserve ordered steps and attach
          timestamps to important actions when timestamps are available.

        Transcript:
        {transcript}
        """
    ).strip()

    response = api_post_json(
        "https://api.openai.com/v1/responses",
        payload={
            "model": model,
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "voice_note",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "date": {"type": "string"},
                            "title": {"type": "string"},
                            "source": {"type": "string"},
                            "topics": {"type": "array", "items": {"type": "string"}},
                            "summary": {"type": "string"},
                            "action_items": {"type": "array", "items": {"type": "string"}},
                            "people": {"type": "array", "items": {"type": "string"}},
                            "extracted_items": {
                                "type": "array",
                                "items": extracted_item_schema(),
                            },
                            "annotations": {
                                "type": "array",
                                "maxItems": 3,
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "title": {"type": "string"},
                                        "type": {
                                            "type": "string",
                                            "enum": [
                                                "concept",
                                                "clarification",
                                                "verification-needed",
                                                "counterpoint",
                                            ],
                                        },
                                        "anchor_quote": {"type": "string"},
                                        "body": {"type": "string"},
                                        "confidence": {
                                            "type": "string",
                                            "enum": ["low", "medium", "high"],
                                        },
                                        "basis": {
                                            "type": "string",
                                            "enum": [
                                                "established-knowledge",
                                                "model-inference",
                                                "needs-research",
                                            ],
                                        },
                                    },
                                    "required": [
                                        "title",
                                        "type",
                                        "anchor_quote",
                                        "body",
                                        "confidence",
                                        "basis",
                                    ],
                                },
                            },
                            "raw_transcript": {"type": "string"},
                        },
                        "required": [
                            "date",
                            "title",
                            "source",
                            "topics",
                            "summary",
                            "action_items",
                            "people",
                            "annotations",
                            "extracted_items",
                            "raw_transcript",
                        ],
                    },
                }
            },
        },
        api_key=api_key,
    )

    try:
        output_text = response.get("output_text") or response["output"][0]["content"][0]["text"]
        data = json.loads(output_text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not parse summary response: {json.dumps(response, ensure_ascii=False)}") from exc

    required_keys = [
        "date",
        "title",
        "source",
        "topics",
        "summary",
        "action_items",
        "people",
        "annotations",
        "extracted_items",
        "raw_transcript",
    ]
    for key in required_keys:
        if key not in data:
            if key == "extracted_items":
                data[key] = []
                continue
            raise SystemExit(f"Summary response missing key: {key}")

    data["title"] = normalize_note_title(data["title"], note_date)
    data["extracted_items"] = normalize_extracted_items(data.get("extracted_items", []))
    return data


def summarize_transcript(transcript: str, note_date: str, api_key: str) -> dict:
    return summarize_capture(transcript, note_date, "voice", api_key)


def normalize_note_title(title: str, note_date: str) -> str:
    normalized = title.strip()
    date_prefix = re.compile(rf"^{re.escape(note_date)}(?:\s*[-–—:：]\s*|\s+)")
    normalized = date_prefix.sub("", normalized, count=1).strip()
    return normalized or title.strip()


def quote_callout_text(value: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in value.splitlines())


def annotations_markdown(annotations: list[dict]) -> str:
    if not annotations:
        return ""

    blocks = ["## AI Comments", ""]
    for annotation in annotations[:3]:
        annotation_type = annotation["type"].replace("-", " ").title()
        title = annotation["title"].strip()
        anchor_quote = annotation["anchor_quote"].strip()
        body = annotation["body"].strip()
        confidence = annotation["confidence"].strip().title()
        basis = annotation["basis"].replace("-", " ").title()

        blocks.append(f"> [!ai-comment]+ AI Comment · {annotation_type}")
        blocks.append(f"> **{title}**")
        if anchor_quote:
            blocks.append(">")
            blocks.append(f'> <span class="ai-comment-anchor">“{anchor_quote}”</span>')
        if body:
            blocks.append(">")
            blocks.append(quote_callout_text(body))
        blocks.append(">")
        blocks.append(
            f'> <span class="ai-comment-meta">Confidence: {confidence} · Basis: {basis}</span>'
        )
        blocks.append("")
    return "\n".join(blocks).rstrip() + "\n\n"
