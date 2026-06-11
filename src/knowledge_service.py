from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import textwrap
from pathlib import Path

from ingestion_service import is_supported_source, normalized_source_type
from openai_note_service import api_post_json
from voice_notes_config import (
    DAILY_DIR, INBOX_DIR, REVIEWS_DIR, SNIPPETS_DIR, TEMPLATES_DIR,
    TOPICS_DIR, VOICE_ROOT, XHS_DIR, ensure_dirs, require_api_key,
)
from vault_service import (
    append_log, existing_topic_links, first_content_line, obsidian_link,
    path_for_index, read_index, rebuild_catalog, slugify, topic_file_for_name,
)


def resolve_review_range(
    preset: str | None,
    raw_from: str | None,
    raw_to: str | None,
    today: dt.date | None = None,
) -> tuple[dt.date, dt.date]:
    if raw_from or raw_to:
        if not raw_from or not raw_to:
            raise SystemExit("Custom reviews require both --from and --to.")
        date_from = dt.date.fromisoformat(raw_from)
        date_to = dt.date.fromisoformat(raw_to)
    else:
        current = today or dt.date.today()
        if preset == "weekly":
            date_from = current - dt.timedelta(days=current.weekday())
            date_to = date_from + dt.timedelta(days=6)
        elif preset == "monthly":
            first_this_month = current.replace(day=1)
            date_to = first_this_month - dt.timedelta(days=1)
            date_from = date_to.replace(day=1)
        elif preset == "yearly":
            year = current.year - 1
            date_from = dt.date(year, 1, 1)
            date_to = dt.date(year, 12, 31)
        else:
            raise SystemExit("Pass --preset weekly|monthly|yearly or both --from and --to.")
    if date_from > date_to:
        raise SystemExit("--from must be on or before --to.")
    return date_from, date_to

def note_dirs_for_scope(scope: str) -> list[Path]:
    if scope == "personal":
        return [DAILY_DIR]
    if scope == "xhs":
        return [XHS_DIR]
    if scope == "all":
        return [DAILY_DIR, XHS_DIR]
    raise ValueError(f"Unsupported scope: {scope}")


def load_note_files_in_range(
    date_from: dt.date,
    date_to: dt.date,
    scope: str = "personal",
    query: str | None = None,
) -> list[Path]:
    files: list[Path] = []
    query_pattern = re.compile(re.escape(query), re.IGNORECASE) if query else None
    for base_dir in note_dirs_for_scope(scope):
        for path in sorted(base_dir.glob("*.md")):
            date_prefix = path.name[:10]
            try:
                note_date = dt.date.fromisoformat(date_prefix)
            except ValueError:
                continue
            if not date_from <= note_date <= date_to:
                continue
            if query_pattern and not query_pattern.search(path.read_text(encoding="utf-8")):
                continue
            files.append(path)
    return files


def period_review(
    date_from: dt.date,
    date_to: dt.date,
    label: str,
    scope: str = "personal",
    query: str | None = None,
    force: bool = False,
) -> Path:
    ensure_dirs()
    filename = f"{date_from}_to_{date_to}_{slugify(label)}_snippet.md"
    output_path = SNIPPETS_DIR / filename
    if output_path.exists() and not force:
        print(f"Snippet already exists, skipping: {output_path}")
        return output_path

    note_files = load_note_files_in_range(date_from, date_to, scope, query)
    if not note_files:
        focus = f" matching {query!r}" if query else ""
        raise SystemExit(
            f"No {scope} notes found between {date_from} and {date_to}{focus}."
        )

    api_key = require_api_key()
    notes_blob = "\n\n".join(path.read_text(encoding="utf-8") for path in note_files)
    model = os.environ.get("OPENAI_SUMMARY_MODEL", "gpt-4.1-mini")
    focus_instruction = (
        f"- Focus only on material relevant to: {query}" if query else
        "- Cover the most important material in the selected period."
    )
    prompt = textwrap.dedent(
        f"""
        Read the following personal knowledge notes and write a {label} snippet
        in Markdown.

        Style:
        - This is a personal weekly snippet, not a project status report.
        - Match the user's dominant language in the selected notes. If most
          notes are Mandarin, write in natural, easy Mandarin.
        - Sound warm, close, and readable, like a thoughtful personal digest.
        - Avoid corporate tone, instruction-manual structure, and inflated
          headings.
        - Prefer a few meaningful sections over exhaustive coverage.

        Review scope: {scope}
        Date range: {date_from} to {date_to}
        {focus_instruction}
        Source fidelity:
        - Do not introduce activities, tools, people, or decisions unless they
          appear in the notes.
        - Do not turn analogies into topics. If a note says something is similar
          to badminton, do not call it badminton practice.
        - If a note title/topic conflicts with its raw transcript, mention the
          uncertainty or follow the raw transcript.
        If the scope is "all", clearly distinguish personal observations from
        imported XHS knowledge. Do not attribute imported claims to the user.

        Include, in a natural format:
        - What seemed to matter emotionally or practically this week
        - Repeated themes
        - Loose ends or things to return to
        - A few topic-note promotion suggestions only if they truly feel durable

        Notes:
        {notes_blob}
        """
    ).strip()

    response = api_post_json(
        "https://api.openai.com/v1/responses",
        payload={"model": model, "input": prompt},
        api_key=api_key,
    )
    try:
        review_text = (response.get("output_text") or response["output"][0]["content"][0]["text"]).strip()
    except (KeyError, IndexError) as exc:
        raise SystemExit(f"Could not parse snippet response: {json.dumps(response, ensure_ascii=False)}") from exc

    output_path.write_text(review_text + "\n", encoding="utf-8")
    rebuild_catalog()
    append_log(
        "review",
        f"{label.title()} snippet {date_from} to {date_to}",
        [
            f"- Scope: {scope}",
            f"- Snippet: {obsidian_link(output_path)}",
        ],
    )
    return output_path


def weekly_review(
    date_from: dt.date,
    date_to: dt.date,
    scope: str = "personal",
    query: str | None = None,
    force: bool = False,
) -> Path:
    return period_review(date_from, date_to, "weekly", scope, query, force)


def resolve_scheduled_snippet_range(
    period: str,
    today: dt.date | None = None,
) -> tuple[dt.date, dt.date]:
    current = today or dt.date.today()
    if period == "weekly":
        current_week_start = current - dt.timedelta(days=current.weekday())
        date_to = current_week_start - dt.timedelta(days=1)
        date_from = date_to - dt.timedelta(days=6)
        return date_from, date_to
    if period == "monthly":
        return resolve_review_range("monthly", None, None, current)
    raise SystemExit(f"Unsupported scheduled snippet period: {period}")


def scheduled_snippet(period: str, today: dt.date | None = None) -> Path:
    started = dt.datetime.now().isoformat(timespec="seconds")
    print(f"{period}-snippet start: {started}")
    try:
        if period == "weekly":
            date_from, date_to = resolve_scheduled_snippet_range(period, today)
            output_path = weekly_review(date_from, date_to, scope="personal")
        elif period == "monthly":
            date_from, date_to = resolve_scheduled_snippet_range(period, today)
            output_path = period_review(date_from, date_to, "monthly", scope="personal")
        else:
            raise SystemExit(f"Unsupported scheduled snippet period: {period}")
    except SystemExit as exc:
        print(f"{period}-snippet failed: {exc}")
        raise
    except Exception as exc:
        print(f"{period}-snippet failed: {type(exc).__name__}: {exc}")
        raise
    finished = dt.datetime.now().isoformat(timespec="seconds")
    print(f"{period}-snippet saved: {output_path}")
    print(f"{period}-snippet exit=0: {finished}")
    return output_path


def note_source(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines()[:20]:
        if line.startswith("source:"):
            return line.split(":", 1)[1].strip()
    return "voice"


def search_notes(
    query: str,
    scope: str = "all",
) -> list[tuple[Path, int, str]]:
    ensure_dirs()
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    results: list[tuple[Path, int, str]] = []
    if scope == "all":
        root_files = [
            VOICE_ROOT / "index.md",
            VOICE_ROOT / "00-home.md",
            VOICE_ROOT / "01-methodology.md",
            VOICE_ROOT / "02-operating-system.md",
            VOICE_ROOT / "AGENTS.md",
            VOICE_ROOT / "catalog.md",
            VOICE_ROOT / "log.md",
        ]
        for path in root_files:
            if not path.exists():
                continue
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                if pattern.search(line):
                    results.append((path, line_number, line.strip()))

    base_dirs = (
        [TOPICS_DIR, REVIEWS_DIR, SNIPPETS_DIR, DAILY_DIR, XHS_DIR]
        if scope == "all"
        else note_dirs_for_scope(scope)
    )
    for base_dir in base_dirs:
        for path in sorted(base_dir.glob("*.md")):
            source = note_source(path)
            if scope == "personal" and source == "xhs":
                continue
            if scope == "xhs" and source != "xhs":
                continue
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if pattern.search(line):
                    results.append((path, line_number, line.strip()))
    return results


def markdown_files() -> list[Path]:
    root_files = [
        VOICE_ROOT / "index.md",
        VOICE_ROOT / "catalog.md",
        VOICE_ROOT / "log.md",
        VOICE_ROOT / "00-home.md",
        VOICE_ROOT / "01-methodology.md",
        VOICE_ROOT / "02-operating-system.md",
        VOICE_ROOT / "AGENTS.md",
        VOICE_ROOT / "README.md",
        VOICE_ROOT / "CLAUDE.md",
    ]
    files = [path for path in root_files if path.exists()]
    for base_dir in [TOPICS_DIR, REVIEWS_DIR, SNIPPETS_DIR, DAILY_DIR, XHS_DIR, TEMPLATES_DIR, VOICE_ROOT / "prompts", VOICE_ROOT / "docs"]:
        if base_dir.exists():
            files.extend(sorted(base_dir.glob("*.md")))
    return files


def link_target_exists(target: str, all_files: list[Path]) -> bool:
    clean_target = target.split("#", 1)[0].strip()
    if not clean_target:
        return True

    if clean_target.endswith(".md"):
        direct = VOICE_ROOT / clean_target
    else:
        direct = VOICE_ROOT / f"{clean_target}.md"
    if direct.exists():
        return True

    target_stem = Path(clean_target).stem
    return any(path.stem == target_stem for path in all_files)


def lint_wiki() -> Path:
    ensure_dirs()
    all_files = markdown_files()
    link_pattern = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
    missing_links: list[tuple[Path, str]] = []

    for path in all_files:
        if path.name.endswith("_wiki_lint.md"):
            continue
        for match in link_pattern.finditer(path.read_text(encoding="utf-8")):
            target = match.group(1)
            if not link_target_exists(target, all_files):
                missing_links.append((path, target))

    topic_files = sorted(TOPICS_DIR.glob("*.md"), key=lambda path: path.name.lower())
    topics_without_sources = [
        path for path in topic_files if "[[" not in path.read_text(encoding="utf-8").split("## Source Notes")[-1]
    ]

    topic_counts: dict[str, int] = {}
    for item in read_index():
        for topic in item.get("topics", []):
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
    promotion_candidates = sorted(
        topic for topic, count in topic_counts.items() if count > 1 and not topic_file_for_name(topic).exists()
    )

    today = dt.date.today().isoformat()
    output_path = REVIEWS_DIR / f"{today}_wiki_lint.md"
    lines = [
        f"# Wiki Lint: {today}",
        "",
        "## Missing Link Targets",
        "",
    ]
    if missing_links:
        for path, target in missing_links:
            lines.append(f"- {obsidian_link(path)} links to missing target `{target}`.")
    else:
        lines.append("- No missing link targets found.")

    lines.extend(["", "## Topic Notes Without Source Links", ""])
    if topics_without_sources:
        for path in topics_without_sources:
            lines.append(f"- {obsidian_link(path)}")
    else:
        lines.append("- Every topic note has at least one source-style wikilink.")

    lines.extend(["", "## Promotion Candidates", ""])
    if promotion_candidates:
        for topic in promotion_candidates:
            lines.append(f"- `{topic}` appears repeatedly in daily notes and may deserve a topic note.")
    else:
        lines.append("- No repeated unpromoted topics found.")

    lines.extend(["", "## Follow-Up", ""])
    lines.append("- Review missing links before creating new topic pages; some may be intentionally lightweight tags.")
    lines.append("- Update topic notes only when the evidence has durable value.")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rebuild_catalog()
    append_log("lint", "Wiki health check", [f"- Report: {obsidian_link(output_path)}"])
    return output_path


def init_topics() -> list[Path]:
    ensure_dirs()
    defaults = {
        "career.md": "# Career\n\n## Notes\n\n## Open Questions\n\n## Next Actions\n",
        "health.md": "# Health\n\n## Notes\n\n## Patterns\n\n## Next Actions\n",
        "system-design.md": "# System Design\n\n## Notes\n\n## Concepts\n\n## Practice Ideas\n",
        "ideas.md": "# Ideas\n\n## Active\n\n## Backlog\n",
    }

    created: list[Path] = []
    for filename, content in defaults.items():
        path = TOPICS_DIR / filename
        if not path.exists():
            path.write_text(content, encoding="utf-8")
            created.append(path)
    return created


def save_text_capture(text: str, prefix: str) -> Path:
    ensure_dirs()
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    cleaned = text.strip()
    if not cleaned:
        raise SystemExit("Capture text is empty.")
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    output_path = INBOX_DIR / f"{prefix}-{timestamp}.txt"
    output_path.write_text(cleaned + "\n", encoding="utf-8")
    return output_path


def capture_manifest_as_regular_source(manifest_path: Path) -> tuple[Path, str]:
    if not manifest_path.exists():
        raise SystemExit(f"Manifest not found: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_type = normalized_source_type(str(payload.get("source_type") or "bot"))
    text = str(payload.get("text") or payload.get("body") or "").strip()
    if text:
        source_url = str(payload.get("url") or payload.get("source_uri") or "").strip()
        if source_url:
            text = f"Source: {source_url}\n\n{text}"
        return save_text_capture(text, "shared-capture"), source_type

    files = payload.get("files") or []
    if len(files) == 1:
        source = Path(files[0]).expanduser()
        if not source.is_absolute():
            source = manifest_path.parent / source
        source = source.resolve()
        if source.exists() and is_supported_source(source):
            destination = INBOX_DIR / source.name
            if source != destination:
                shutil.copy2(source, destination)
            return destination, source_type
    raise SystemExit(
        "Manifest compatibility mode requires text/body or one supported local file."
    )
