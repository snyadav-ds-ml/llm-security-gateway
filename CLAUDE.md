# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Package manager:** `uv` (see `pyproject.toml` + `uv.lock`).

```bash
uv sync                                        # install / sync all dependencies

# Phase 1 — standalone scripts, run from project root
python phase1/manual_rag.py                    # manual RAG (no framework)
python phase1/langchain_rag.py                 # LangChain + Chroma RAG

# Phase 2 / 3 — FastAPI servers (relative imports require running as a package)
uvicorn phase2.gateway:app --reload            # gateway without guardrails
uvicorn phase3.gateway:app --reload            # gateway with guardrails

# Hit the running server
curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"question": "How many vacation days do employees get?"}'

# Inspect the audit log
sqlite3 audit.db "SELECT * FROM audit_log ORDER BY id DESC LIMIT 10;"
```

No test suite yet — Phase 6 will add ~40 attack/benign cases.

## Project

LLM Security Gateway + RAG Poisoning Detector — capstone project defending a RAG chatbot against prompt injection, knowledge-base poisoning, and excessive agency (OWASP LLM Top 10). Everything runs locally at $0. Full spec: `docs/techspec.md`.

## Build Philosophy

- Build in phases — each phase must run and be understood before starting the next (see phase table below).
- Before making any change, explain what we're doing and why, and compare the LangChain approach to the equivalent code without LangChain.
- Prefer boring, explicit code over clever abstractions — this is a learning project as much as a portfolio piece.
- Everything must run locally, free. No paid APIs, no cloud services.

## Stack

| Layer | Choice | Notes |
|---|---|---|
| LLM inference | Ollama — `llama3.2:3b` | Do not swap silently |
| Embeddings | `nomic-embed-text` via Ollama | Do not swap silently |
| Vector store | ChromaDB | Ask before any schema or collection change |
| Orchestration | LangChain | Explain each LangChain abstraction used |
| API | FastAPI | |
| Audit log | SQLite | Built-in, no server needed |
| Packaging | Docker Compose → `kind` (Kubernetes) | Docker Compose must work before k8s |

## Pipeline Architecture

```
User message
     │
     ▼
┌──────────────────┐
│  SECURITY GATEWAY │  PII redaction, injection detection, rate limiting
└────────┬─────────┘
         ▼
┌──────────────────┐
│  RAG PIPELINE     │  Retrieve relevant chunks from ChromaDB
└────────┬─────────┘
         ▼
┌──────────────────┐
│  LLM (Ollama)    │  Decide: answer or call a tool?
└────────┬─────────┘
         ▼
┌──────────────────┐
│  AGENT LOOP +    │  Allow-list + request-consistency check before
│  TOOL GUARDRAILS │  any sensitive tool runs
└────────┬─────────┘
         ▼
┌──────────────────┐
│  OUTPUT CHECK    │  Block PII / denylist matches before returning
└────────┬─────────┘
         ▼
    Answer to user

Separate path at document upload time:
  New doc → POISONING DETECTOR → accept / flag / reject → ChromaDB
  (embedding outlier score + instruction scan + source trust score)

Every decision at every step is written to the SQLite audit log.
```

## Three Components and What Each Defends

**Component A — Security Gateway** (`gateway/`)
- PII redaction on input → defends against data leakage
- Keyword/regex injection detection → defends against direct prompt injection
- Per-user rate limiting → defends against abuse / cost attacks
- Output filtering (PII + denylist) → defends against data leakage in responses
- SQLite audit log → every request and decision recorded with reason

**Component B — RAG Poisoning Detector** (`poisoning/`)
- Embedding outlier score: compare new doc embedding to corpus centroid; flag if distance exceeds threshold → defends against knowledge-base poisoning
- Instruction scan: regex scan doc content for command patterns → defends against indirect prompt injection hidden in documents
- Source trust score: `verified` vs `user_submitted` provenance tier → defends against untrusted document ingestion
- Decision per document: **accept** / **flag** / **reject**

**Component C — Agent Tool Guardrails** (`agent/`)
- Allow-list of exactly three tools: `search_knowledge_base`, `get_document_metadata`, `flag_document_for_review`
- Request-consistency check before `flag_document_for_review` runs: does the call originate from the user's intent or from retrieved document text? → defends against excessive agency / indirect injection hijacking tool calls
- Every tool call attempt logged as allowed or blocked with reason

## Build Phases

| Phase | Days | Exit Criteria |
|---|---|---|
| 0 — Environment | 1 | `python3 --version`, `docker ps`, `ollama list` all pass |
| 1 — Baseline RAG | 2 | Manual RAG (no framework) answers 3 questions; then LangChain+Chroma version does the same; both explained step-by-step |
| 2 — Gateway skeleton | 3–4 | FastAPI `/chat` wrapping RAG; every request creates a SQLite log row |
| 3 — Guardrails | 5–7 | Known injection blocked with reason logged; PII redacted from input and output |
| 4 — Poisoning detector | 8–9 | Planted poisoned document flagged at ingestion time |
| 5 — Agent layer | 10–11 | Normal requests work; a document-hijack attempt trying to call `flag_document_for_review` is blocked |
| 6 — Testing | 12–13 | ~20 attack cases + ~20 benign cases run with defenses off/on; detection rate, FP rate, latency overhead recorded |
| 7 — Packaging | 14 | `docker compose up` starts the full system from a clean checkout |
| 8 — Kubernetes (stretch) | after 15 | `kind` cluster with NetworkPolicies; only after Docker Compose is solid |

Cut order if time is short: Kubernetes → Redis rate limiting (use in-memory) → classifier-based injection detection (keep keyword rules). **Do not cut testing (phase 6).**

## Conventions

- Comment *why*, not just what — code needs to be defensible in a project review.
- When adding a security control, always note which attack it defends against in a comment.
- Model or embedding swaps must be called out explicitly before implementing.

## Do NOT

- Add cloud API keys or paid services.
- Skip to Kubernetes before Docker Compose works.
- Swap the LLM (`llama3.2:3b`) or embedding model (`nomic-embed-text`) without saying so.
- Change the ChromaDB collection schema without discussion.
