# Tech Spec (Final): Secure RAG Gateway
### LLM Security Gateway + RAG Poisoning Detector + Agent Guardrails

**Course:** Security Engineering | **Version:** Final | **Stack:** fully local, $0 cost

---

## 1. What is this?

A security layer that sits in front of an AI chatbot (the kind that answers questions using a knowledge base, called "RAG"). It watches everything going in and out and blocks bad stuff before it causes harm.

Think of it like a security guard standing at the door of an AI app:
- Checks what people send in (blocks attacks, removes sensitive info)
- Checks what the AI sends back (makes sure it isn't leaking secrets)
- Checks the knowledge base for poisoned or fake documents someone snuck in
- Checks what *actions* the AI tries to take, if it is allowed to act on its own (the "agentic" part)

## 2. Why does this matter? (The problem)

When companies connect AI models to real data and let users chat with them, four things can go wrong:

| Problem | Plain-English Explanation |
|---|---|
| **Prompt Injection** | Someone tricks the AI with sneaky instructions, in their message or hidden in a document, making it ignore its rules |
| **Data Leakage** | The AI accidentally reveals private info (personal data, secrets, internal instructions) in its answers |
| **RAG Poisoning** | Someone adds a fake or malicious document to the knowledge base so the AI's answers get manipulated |
| **Excessive Agency** | If the AI can call tools, a trick hidden in a document can make it take an action nobody asked for |

These map to the OWASP Top 10 for LLM Applications (Prompt Injection, Sensitive Information Disclosure, Vector and Embedding Weaknesses / Data Poisoning, Excessive Agency).

## 3. Scope

**In scope:** a working RAG app, a security gateway, a poisoning detector, a small agent with guarded tools, and a test suite that proves the defenses work.

**Out of scope:** attacks on the model itself (training-time attacks, model theft), attacks on the host machine or network, and production-scale performance.

**Attacker assumed to be able to:** send queries to the chatbot, and add documents to the knowledge base (for example through an upload feature).

## 4. The Big Picture

```
   User types a message
          │
          ▼
  ┌────────────────────┐
  │  SECURITY GATEWAY   │  ← rate limit, PII redaction,
  │   (input checks)    │     prompt-injection detection
  └─────────┬──────────┘
            ▼
  ┌────────────────────┐
  │  RAG PIPELINE       │  ← retrieves relevant chunks from the
  │  + KNOWLEDGE BASE   │     knowledge base (Chroma)
  └─────────┬──────────┘
            ▼
  ┌────────────────────┐
  │  AI MODEL           │  ← decides: answer now, or use a tool first?
  └─────────┬──────────┘
            ▼
  ┌────────────────────┐
  │  AGENT LOOP +       │  ← every tool call is checked: is the tool
  │  TOOL GUARDRAILS    │     allowed, and does it match the request?
  └─────────┬──────────┘
            ▼
  ┌────────────────────┐
  │  OUTPUT CHECK       │  ← blocks leaks before the user sees them
  └─────────┬──────────┘
            ▼
      Answer shown to user

  Separate path, at document upload time:
  New document → POISONING DETECTOR → (accept / flag / reject) → knowledge base

  Every decision at every step is written to the audit log (SQLite).
```

## 5. The Three Components

### Component A: Security Gateway (the front door)

| Control | What it does | Attack it defends against |
|---|---|---|
| PII redaction | Finds emails, phone numbers, etc. in the message and masks them before the AI sees them | Data leakage |
| Injection detection | Flags messages containing known attack patterns ("ignore previous instructions", "reveal your system prompt"), using keyword/regex rules and optionally a small open classifier model | Direct prompt injection |
| Rate limiting | Caps requests per user per minute | Abuse, cost attacks |
| Output filtering | Scans the AI's answer for sensitive patterns and a denylist before returning it | Data leakage |
| Audit logging | Records every request and decision with a reason | Lack of visibility |

### Component B: RAG Poisoning Detector (the librarian who checks new books)

Runs when a document is added to the knowledge base:

| Check | What it does |
|---|---|
| Embedding outlier score | Compares the new document's embedding to the existing corpus; documents far from everything else are suspicious |
| Instruction scan | Looks for text that tries to command the AI ("ignore all previous instructions", "call the flag tool") inside what should be plain content |
| Source trust score | Gives each document a trust level based on where it came from (for example `verified` vs `user_submitted`) |

Each document gets a decision: **accept**, **flag for review**, or **reject**. All scores are logged.

### Component C: Agent Tool Guardrails (the bodyguard)

The AI gets a small, fixed set of tools:

| Tool | Risk level | Purpose |
|---|---|---|
| `search_knowledge_base(query)` | Low | Search again with different terms |
| `get_document_metadata(doc_id)` | Low | Look up a document's source and trust score |
| `flag_document_for_review(doc_id, reason)` | **Sensitive** | Mark a document for human review |

Guardrails:
- **Allow-list:** only these three tools exist; any other tool name is refused.
- **Request-consistency check:** before the sensitive tool runs, the guardrail checks that the call is justified by what the *user* asked, not by text that came from a retrieved document.
- **Logging:** every tool call attempt is logged as allowed or blocked, with the reason.

## 6. What It's Built With (all free, all local)

| Part | Tool | Why |
|---|---|---|
| AI model | Ollama running Llama 3.1 8B | Free, runs on your own computer |
| Knowledge base | **ChromaDB** | Free, simple, no server to manage |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | Free, small, fast on CPU |
| Orchestration | LangChain | Standard framework for RAG and tool calling |
| Gateway | FastAPI | Simple Python API framework |
| Rate limiting | Redis (or an in-memory limiter if time is short) | Fast counters per user |
| Audit log | **SQLite** | Built into Python, no server needed |
| Packaging | Docker Compose | One command to start the system |
| Stretch goal | Kubernetes (`kind`) with NetworkPolicies | Shows production-style isolation |

**Design note:** ChromaDB and SQLite were chosen over PostgreSQL/pgvector to keep setup small. The security controls do not depend on the vector store, and LangChain's retriever interface makes a later swap to pgvector a small change.

## 7. How We'll Prove It Works (Test Plan)

1. **Build two test sets**
   - *Attack set* (about 20 cases): direct injections, injections hidden in documents, poisoned documents, documents that try to trigger the flag tool, and prompts that try to extract PII.
   - *Benign set* (about 20 cases): normal questions and normal documents.
2. **Run both sets with defenses OFF.** Record what happens (attacks should succeed).
3. **Run both sets with defenses ON.** Record what happens.
4. **Measure**
   - Detection rate: attacks blocked ÷ total attacks
   - False-positive rate: benign requests wrongly blocked ÷ total benign requests
   - Latency overhead: average extra time per request
5. **Show the failures too.** List which attacks got through and why. This is the residual risk section of the report.

**Three headline demos:**
- A direct prompt injection succeeds without the gateway and is blocked with it.
- A poisoned document is accepted without the detector and flagged with it.
- A poisoned document hijacks the agent into calling the flag tool without the guardrail, and the guardrail blocks it.

## 8. Build Plan (15 days)

The project starts from zero. Days 1-2 build the base RAG application that everything else protects.

| Days | Work | Done when |
|---|---|---|
| 1 | Install and verify Python, Docker, and Ollama; download the local model (`ollama pull llama3.1`) | `python3 --version`, `docker ps`, and `ollama list` all work |
| 2 | **Base RAG:** (a) build RAG by hand with no framework (load, chunk, embed, retrieve, generate) to understand each step, then (b) rebuild it with LangChain and Chroma | Both versions answer 3 test questions, and each retrieved chunk can be explained |
| 3-4 | Gateway skeleton: FastAPI `/chat` endpoint wrapping the RAG pipeline, SQLite audit log | Every request creates a log row |
| 5-7 | Guardrails: PII redaction, injection detection, output filtering, rate limiting | A known injection and fake PII are both caught, with reasons logged |
| 8-9 | Poisoning detector: outlier score, instruction scan, trust score | A planted poisoned document is flagged |
| 10-11 | Agent layer: three tools, allow-list, request-consistency check | Normal requests work; a hijack attempt is blocked |
| 12-13 | Attack and benign test sets, run defenses off/on, compute metrics | A results table with real numbers |
| 14 | Docker Compose packaging, README | `docker compose up` starts the system |
| 15 | Buffer and cleanup | Everything runs from a clean checkout |

Day 2 is the riskiest day (framework version mismatches, slow model downloads). If it overruns, take the time from day 15.

**After day 15 (before the final deadline):** Kubernetes packaging as a stretch goal, then the final report.

**If time runs short, cut in this order:** Kubernetes, Redis rate limiting (use a simple in-memory limiter), classifier-based injection detection (keep keyword rules). Do not cut the testing step; it is the proof.

## 9. What "Done" Looks Like

- A working system started with `docker compose up`
- The three headline demos, runnable or recorded
- A results table: detection rate, false-positive rate, latency overhead
- A short list of known limitations (what the defenses miss)
- Clean code and a README that someone else can follow

## 10. Known Limitations (stated up front)

- Keyword and pattern detection can be bypassed by rephrasing; the classifier reduces this but does not eliminate it.
- Embedding outlier detection can miss a poisoned document written to look topically normal, and can flag unusual but legitimate documents.
- The small local model is less capable than commercial models, so absolute results may differ elsewhere.
- The test sets are small and hand-built, so results show the controls work on these cases, not that they are complete.

## 11. Glossary

- **LLM:** the AI model that writes answers
- **RAG:** Retrieval-Augmented Generation. The AI looks things up in a knowledge base before answering
- **Prompt injection:** tricking an AI with hidden instructions
- **Poisoning:** adding bad data to a system so it behaves wrongly later
- **Embedding:** text turned into a list of numbers that captures its meaning, so similar texts can be compared
- **Gateway:** a checkpoint all traffic passes through
- **Agentic AI / agent:** an AI that can take multiple steps on its own, including calling tools
- **Tool calling:** the AI triggering a pre-defined action (search, lookup, flag) as part of answering
- **Excessive agency:** the risk of an AI taking an action it shouldn't, especially one triggered by a hidden trick
- **Allow-list:** a fixed list of permitted actions; everything else is refused
- **Residual risk:** the risk that remains after the defenses are in place