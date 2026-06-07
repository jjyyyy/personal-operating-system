# Proposal: Contextual AI Annotations And Agent Briefing

Status: Proposal only
Date: 2026-06-07
Source: [[daily/2026-06-07-reflecting-on-engineer-roles-and-ai-note-features-20260607-011356|Reflecting on Engineer Roles and AI Note Features]]

## Executive Summary

Add two optional intelligence layers to the voice-notes system:

1. **Contextual AI Annotations** enrich a parsed note with concise, clearly separated commentary when the transcript contains an unclear concept, a well-established term the user appears not to know, an uncertain claim, or a useful connection to existing vault knowledge.
2. **Agent Briefing** produces a compact machine-readable update about relevant tools, skills, model changes, and project developments. Agents consume the briefing only when a task benefits from current information.

The two features should remain separate:

- annotations improve a specific note;
- briefings update the agent's external awareness.

Neither feature should silently rewrite the user's words or automatically promote claims into durable topic memory.

## Problem

The current pipeline is strong at normalization:

```text
audio -> transcript -> summary/topics/actions -> daily note
```

It does not yet distinguish between:

- what the user said;
- what the model inferred;
- what established knowledge can clarify;
- what requires external verification;
- what changed recently outside the vault.

As a result, a parsed note can preserve a question without helping the user understand its context. Separately, an agent may have good project memory but stale knowledge about rapidly changing tools and models.

## Goals

### Contextual AI Annotations

- Add useful context without contaminating the source transcript.
- Identify unclear terms, hidden assumptions, factual uncertainty, and relevant vault connections.
- Keep annotations short enough that daily notes remain readable.
- Make evidence level and provenance explicit.
- Allow annotations to become research questions or topic-note candidates later.

### Agent Briefing

- Give agents a compact, relevant summary of recent external changes.
- Avoid loading a large news feed into every prompt.
- Support both human reading and machine consumption.
- Preserve source URLs, retrieval dates, relevance, and confidence.
- Let the user control topics, frequency, and token budget.

## Non-Goals

- Automatically correcting or rewriting the raw transcript.
- Adding commentary to every paragraph.
- Treating model knowledge as a citation.
- Automatically browsing the web during every ingest.
- Building a general-purpose news product.
- Letting external news overwrite durable topic notes without review.
- Running heartbeat/model calls merely because time has passed.

## Feature A: Contextual AI Annotations

### Trigger Conditions

An annotation should be created only when at least one condition is met:

1. **Defined concept:** the user asks about or appears unaware of a concept with a stable, useful definition.
2. **Ambiguity:** a phrase has multiple plausible meanings and affects interpretation.
3. **Uncertain factual claim:** the statement may be outdated, incorrect, or needs verification.
4. **Vault connection:** the idea directly connects to an existing topic, decision, contradiction, or repeated pattern.
5. **Research opportunity:** the note contains a meaningful question worth investigating.
6. **Decision consequence:** missing context could change an action or decision.

Do not annotate:

- casual remarks with no durable value;
- obvious statements;
- private emotional reflections unless context was requested;
- every extracted topic;
- content where the model has low confidence and cannot state a useful question.

### Proposed Note Format

Add an optional section after `## Summary`:

```markdown
## AI Annotations

### Engineer vs Product Manager In AI-Assisted Development

Type: concept
Confidence: medium
Evidence: model-knowledge

The distinction is not only who writes implementation code. Engineering still owns
system constraints, architecture, reliability, security, observability, and the
translation of ambiguous goals into systems that remain correct under change.

Suggested research:
- Which engineering decisions remain difficult to delegate to coding agents?
- How does ownership change when implementation cost approaches zero?
```

For source-backed annotations:

```markdown
Type: verification
Confidence: high
Evidence: web
Checked: 2026-06-07
Sources:
- https://example.com/source
```

### Annotation Types

- `concept`: explain a stable concept.
- `clarification`: expose ambiguity or missing context.
- `connection`: link to existing vault knowledge.
- `verification`: check a factual or time-sensitive claim.
- `counterpoint`: identify a meaningful alternative interpretation.
- `research-question`: preserve a question without pretending to answer it.

### Data Contract

Extend the summary response with:

```json
{
  "annotations": [
    {
      "title": "string",
      "type": "concept",
      "body": "string",
      "confidence": "low|medium|high",
      "evidence": "vault|model-knowledge|web|none",
      "source_urls": [],
      "suggested_questions": []
    }
  ]
}
```

Recommended limits:

- zero to three annotations per note;
- body under 120 words;
- zero annotations is a valid and desirable result;
- web-backed annotations require retrieval date and URLs.

### Pipeline Options

#### Option 1: Single-Pass Ingest

The existing summary request also generates annotations.

Advantages:

- one model request;
- lowest latency and cost;
- simplest implementation.

Risks:

- model may over-annotate;
- cannot perform reliable current-fact verification;
- summary and commentary quality may compete for attention.

#### Option 2: Two-Pass Selective Annotation

Pass one creates the normal note plus `annotation_candidates`. Pass two runs only when candidates meet a threshold.

Advantages:

- stronger separation between source parsing and commentary;
- annotation model/prompt can be tuned independently;
- web search can be enabled only for verification candidates.

Risks:

- additional latency and cost;
- more state and failure handling.

Recommendation: begin with **two-pass selective annotation**, but make pass two opt-in during the first rollout. Source fidelity matters more than saving one request.

### User Controls

Suggested `.env` or config options:

```env
VOICE_NOTES_ANNOTATIONS=off
VOICE_NOTES_ANNOTATION_MAX=3
VOICE_NOTES_ANNOTATION_WEB=off
```

Suggested modes:

- `off`: current behavior.
- `suggest`: generate candidates in a separate review file.
- `inline`: add approved annotation structure to daily notes.

Start with `suggest`.

### Failure And Safety Behavior

- Annotation failure must not fail ingest.
- A parsed daily note should still be saved when the annotation pass fails.
- Never modify `Raw Transcript`.
- Clearly label model inference.
- Do not cite nonexistent sources.
- Do not write web-derived claims into topic notes without a source link.

## Feature B: Agent Briefing

### Product Definition

An Agent Briefing is not a podcast and not a general news digest. It is a small, structured update answering:

```text
What changed recently that may affect this user's active projects,
tools, decisions, or agent workflows?
```

### Inputs

- Explicit watch topics, such as OpenClaw, Codex, Obsidian, OpenAI APIs, and active projects.
- Official release notes and documentation.
- User-approved feeds or sites.
- Open questions and active topics from the vault.
- Previous briefing, to avoid repetition.

### Output Format

Human-readable Markdown:

```markdown
# Agent Briefing: 2026-06-07

## High Relevance

### OpenClaw release
- Change:
- Why it matters:
- Suggested action:
- Source:

## Watch Only

## No Longer Relevant

## Research Queue
```

Machine-readable companion:

```json
{
  "date": "2026-06-07",
  "items": [
    {
      "topic": "OpenClaw",
      "change": "string",
      "relevance": "high",
      "confidence": "high",
      "source_url": "https://...",
      "retrieved_at": "2026-06-07T08:00:00+02:00",
      "suggested_action": "string"
    }
  ]
}
```

### Storage

Recommended:

```text
briefings/
  2026-06-07.md
  2026-06-07.json
```

Do not place all briefing content in `index.md`. `index.md` should contain only:

- latest briefing date;
- a link to the latest briefing;
- zero or one high-priority warning.

### Consumption Rules

Agents should read the latest briefing only when:

- the user asks about current tools, models, releases, or external events;
- a coding task depends on a recently changing API or product;
- the user explicitly asks for today's update.

Agents should not read it for:

- simple vault searches;
- historical or personal questions;
- formatting tasks;
- note ingestion that does not require external facts.

### Scheduling

Start with an explicit command:

```bash
python3 src/voice_notes_ai.py create-briefing
```

Only add scheduling after the content and source filters are trusted.

Possible later schedule:

```text
once each morning, only if watch topics are configured
```

The briefing job should skip the model call when:

- no source changed;
- no active watch topics exist;
- the previous briefing is still current.

### Source Policy

Priority:

1. Official documentation and release notes.
2. Primary announcements from maintainers.
3. Trusted technical reporting.
4. Community discussion only as a signal, not as verified truth.

Every factual update must include a URL and retrieval time.

### Token And Cost Controls

- Fetch metadata before full pages.
- Use deterministic source filters.
- Deduplicate by canonical URL and content hash.
- Cap items per briefing.
- Summarize only changed sources.
- Store previous source fingerprints.
- Do not inject the entire briefing into every agent session.
- Keep heartbeat disabled; scheduling and agent conversation are separate concerns.

## Research Track: The Engineer Role

The source note asks why engineers remain necessary when a product-minded user can specify requirements and an agent can implement them.

This should become a research page rather than a product feature.

Suggested questions:

1. Which parts of engineering are implementation, and which are judgment?
2. Who owns architecture, constraints, reliability, security, and failure recovery?
3. How does requirement quality change when implementation becomes cheap?
4. Does engineering move toward systems design, verification, and operational ownership?
5. What evidence distinguishes an effective AI-native engineer from a product manager using coding agents?

Potential output:

```text
research/ai-native-engineer-role.md
```

This track may later inform annotation quality, because it is a good example of when a note contains a broad but already-studied question.

## Recommended Architecture

```text
ingest
  -> transcription
  -> source-preserving structured note
  -> annotation candidate detector
      -> no candidates: finish
      -> candidates: optional annotation pass
  -> daily note

scheduled/manual briefing
  -> load watch topics
  -> discover changed primary sources
  -> fetch and verify
  -> deduplicate
  -> write briefing.md + briefing.json
```

Keep these systems independent. A briefing item may later support a note annotation, but ingest should not depend on the briefing job being healthy.

## Rollout Plan

### Phase 0: Evaluation

- Collect 15-30 representative daily notes.
- Manually mark where annotations would help.
- Define examples of useful and annoying annotations.
- Decide whether annotations should default to Chinese, English, or note language.

### Phase 1: Annotation Suggestions

- Generate annotation candidates without editing daily notes.
- Store candidates in a review artifact.
- Measure acceptance, rejection, and edit rates.

### Phase 2: Inline Annotations

- Add the structured `AI Annotations` section.
- Keep web verification disabled by default.
- Ensure annotation failure cannot block ingest.

### Phase 3: Manual Briefing

- Add watch-topic configuration.
- Support official sources only.
- Generate briefing on demand.
- Track changed-source fingerprints.

### Phase 4: Scheduled Briefing

- Add a daily schedule only after manual briefings consistently produce value.
- Skip runs with no changed sources.
- Notify only when at least one high-relevance item exists.

### Phase 5: Cross-Linking

- Let verified briefing items support annotations.
- Suggest topic-note updates with citations.
- Keep promotion human-reviewed.

## Acceptance Criteria

### Annotation MVP

- Existing ingest output remains valid.
- Zero to three annotations are generated.
- Raw transcript remains byte-for-byte logically unchanged.
- Facts, inference, and questions are visibly distinguished.
- Annotation failure does not block note creation.
- User can disable the feature globally.

### Briefing MVP

- Every item includes source URL and retrieval time.
- Only changed sources are summarized.
- Briefing is not mandatory context for normal queries.
- No model call occurs when there are no relevant changes.
- The user can inspect why each item was included.

## Risks

- **Over-annotation:** notes become noisy and patronizing.
- **Hallucinated authority:** model commentary appears more certain than the source.
- **Token growth:** annotations and briefings become mandatory context.
- **Freshness theater:** a daily briefing repeats unchanged information.
- **Source drift:** community claims are treated as official changes.
- **Privacy leakage:** private notes are used as web-search queries without clear controls.
- **Automation coupling:** ingest fails because enrichment services fail.

Primary mitigation: keep enrichment optional, provenance explicit, and source parsing independent.

## Decisions Needed Before Implementation

1. Should annotation MVP be `suggest` or immediately `inline`?
2. Should annotations use the note's language automatically?
3. Which annotation types are useful enough for MVP?
4. May private note text be used to formulate web searches?
5. Which external topics belong in the initial briefing watchlist?
6. Should briefings be human-facing, agent-facing, or both?
7. What daily or weekly token budget is acceptable?

## Recommendation

Build **Contextual AI Annotations in suggestion mode first**. It is directly connected to the existing ingest workflow and can be evaluated using current notes.

Treat **Agent Briefing as a separate second project**. Start manually with official sources and changed-source detection; do not schedule it until the output repeatedly proves useful.

Keep the engineer-role question as a research page that can serve as the first annotation-quality test case.
