# LLM Wiki For Personal Operating System

## Core Idea

Traditional RAG is mostly temporary retrieval at question time. It is useful, but it does not automatically accumulate knowledge.

Voice notes work better as an LLM wiki: each recording becomes a structured daily note, then repeated or durable content is periodically merged into topic notes. Future AI answers should start from promoted topic notes, review notes, and decisions instead of rereading raw transcripts from scratch.

For this vault, `index.md` stays intentionally compact. Use `catalog.md` only for broad discovery, and use `log.md` when the timeline of recent ingests, reviews, or lint passes matters.

## Why Captures Fit This Method

Voice notes tend to be:

- fragmented
- conversational
- spread across time
- repetitive
- valuable mainly through long-term patterns, not single transcripts

The vault should gradually answer:

- Which long-term theme does this idea belong to?
- Has it repeated?
- Does it change a previous judgment?
- Does it create an action?
- Which topic note should it be promoted into?

## Knowledge Principles

### 1. Raw Transcript Is Not Knowledge

A transcript is raw material. Keep it, but do not treat it as the final result.

Each voice note should produce:

- summary
- topics
- action items
- people
- links
- raw transcript

### 2. Daily Notes Are An Intermediate Layer

`daily/` records what was said on a particular date. It is useful for details and traceability, but should not become the final knowledge layer.

### 3. Topic Notes Are Long-Term Memory

`topics/` records durable beliefs, repeated problems, long-term goals, risks, decisions, and next actions. AI should read these first for long-term questions.

### 4. Snippets Synthesize

Weekly and monthly snippets should look across daily notes for:

- repeated themes
- conflicting ideas
- long-term trends
- unfinished actions
- content worth promoting into topic notes

### 5. Do Not Rush Into Complex RAG

First build a stable structure with useful content. After `daily/` and `topics/` have enough high-quality notes, consider vector search, SQLite, or automation agents.

## Workflow

```text
Capture
recordings, quick thoughts, meetings, walking notes

Normalize
transcribe, clean speech, create structured daily notes

Synthesize
weekly snippet of repeated themes, actions, and people

Promote
merge stable reusable content into topic notes

Query
ask AI to read topic notes and reviews before daily notes

Lint
periodically check links, stale claims, contradictions, and promotion candidates
```
