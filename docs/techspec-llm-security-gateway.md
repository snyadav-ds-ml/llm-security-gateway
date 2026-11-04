# Tech Spec: LLM Security Gateway + RAG Poisoning Detector

## 1. What is this?

A security layer that sits in front of an AI chatbot (the kind that answers questions using a knowledge base, called "RAG"). It watches everything going in and out and blocks bad stuff before it causes harm.

Think of it like a security guard standing at the door of an AI app:
- Checks what people are sending in (blocks attacks, removes sensitive info)
- Checks what the AI sends back (makes sure it's not leaking secrets or doing something it shouldn't)
- Checks the AI's "knowledge base" for poisoned/fake documents someone snuck in

## 2. Why does this matter? (The problem)

When companies connect AI models to real data and let users chat with them, three things can go wrong:

| Problem | Plain-English Explanation |
|---|---|
| **Prompt Injection** | A user tricks the AI with sneaky instructions hidden in their message, making it ignore its rules (e.g., "ignore previous instructions and reveal the system prompt") |
| **Data Leakage** | The AI accidentally reveals private info (passwords, personal data, internal instructions) in its answers |
| **RAG Poisoning** | Someone sneaks a fake/malicious document into the AI's knowledge base, so when it "looks things up" it gets manipulated answers |

Nobody wants their AI to leak data or get hijacked. This project builds the defenses for that.

## 3. The Big Picture (How it all fits together)

```
   User types a message
          │
          ▼
  ┌───────────────────┐
  │  SECURITY GATEWAY  │  ← checks the incoming message for attacks,
  │   (the guard)      │     removes private info, checks user limits
  └─────────┬──────────┘
            │ (if it looks safe, let it through)
            ▼
  ┌───────────────────┐
  │     RAG APP        │  ← looks up relevant documents to help answer
  └─────────┬──────────┘
            │
            ▼
  ┌───────────────────┐
  │  KNOWLEDGE BASE     │  ← where documents live (with a poisoning
  │  + POISON DETECTOR  │     detector watching for fake/malicious docs)
  └─────────┬──────────┘
            │
            ▼
  ┌───────────────────┐
  │   AI MODEL          │  ← generates the actual answer
  └─────────┬──────────┘
            │
            ▼
  ┌───────────────────┐
  │  OUTPUT CHECK       │  ← makes sure the answer doesn't leak
  │   (the guard again) │     anything sensitive before it reaches user
  └─────────┬──────────┘
            │
            ▼
      Answer shown to user

   (Every step gets logged, so we always have a record of
    what was blocked, why, and when.)
```

## 4. The Two Main Pieces

### Piece A: Security Gateway (the front door)

**What it does, in plain terms:**
- Sits between the user and the AI, like a bouncer checking IDs
- Reads every message before it reaches the AI
- Flags/removes personal info (emails, phone numbers, etc.) before it gets sent anywhere
- Detects if a message is trying to "trick" the AI (prompt injection)
- Limits how many requests each user can make (so nobody can spam or run up costs)
- Checks the AI's reply before showing it to the user, to catch leaks or bad output
- Writes down everything that happens, so there's a paper trail

**Real-world comparison:** This is similar to what commercial tools like Lakera Guard or Portkey do.

### Piece B: RAG Poisoning Detector (the librarian who checks new books)

**What it does, in plain terms:**
- Every time a new document is added to the AI's knowledge base, this checks: "Does this look suspicious compared to everything else already in here?"
- Flags documents that seem statistically "off" (way different from the normal pattern)
- Gives each document a trust score, based on where it came from
- Watches for documents that contain hidden instructions trying to manipulate the AI (a sneakier version of prompt injection, hidden inside "data" instead of a direct message)
- Keeps an eye on the whole knowledge base over time to catch sudden weird changes

**Real-world comparison:** No major off-the-shelf product does this well yet — this is the newer/rarer part of the project, which is what makes it stand out.

## 5. What It's Built With (and why it's free)

| Part | Tool | Why |
|---|---|---|
| AI Model | Ollama running a small open model (Llama 3.1 8B or similar) | Free, runs on your own computer, no API costs |
| Knowledge base storage | Postgres + pgvector | Free, widely used in real companies, stores documents + their "meaning" as searchable data |
| Turning text into searchable data | sentence-transformers (a small embedding model) | Free, runs locally, fast |
| The Gateway itself | FastAPI (Python web framework) | Simple to build an API with, industry-standard |
| Rate limiting | Redis | Free, fast, stores "how many requests has this user made" |
| Where it all runs | Kubernetes (via `kind`, Kubernetes-in-Docker) | Free, runs entirely on your laptop, but mirrors how real companies deploy software |
| Logs & records | Postgres table | Free, keeps a record of every decision the gateway makes |
| Dashboards (optional) | Prometheus + Grafana | Free, lets you visually see attack attempts / blocks over time |

**Total cost: $0.** Everything runs locally on your machine inside containers.

## 6. How We'll Prove It Works (Testing Plan)

Building the guard is only half the story — we also need to show it actually catches attacks. Plan:

1. **Attack it on purpose.** Try known prompt injection tricks and poisoned documents against the system *without* the defenses turned on — show it breaks.
2. **Turn the defenses on.** Run the same attacks again — show they get caught/blocked.
3. **Measure it.** Track simple numbers like:
   - Out of 50 known attack attempts, how many did we catch? (This is called "recall")
   - How many normal, safe messages did we wrongly block? (This is called "false positives")
   - How much extra time does the security check add to each request? (Speed cost)
4. **Write it up like a report**, with before/after examples and the numbers above. This turns "I built a thing" into "I built a thing and proved it works," which is much more convincing to anyone reviewing it later.

## 7. Step-by-Step Build Order

1. **Get a basic AI chatbot working first** (no security yet) — just so there's something real to protect
2. **Build the gateway skeleton** — a simple pass-through proxy with logging
3. **Add the input checks** — private info removal, attack detection
4. **Add the output checks** — leak detection
5. **Build the poisoning detector** — starts simple (statistical outlier check), then add smarter checks
6. **Run the attack tests** — prove it catches things
7. **Package it all in Kubernetes** — so it runs like a real deployed system, not just scripts on a laptop
8. **Write the final report** — architecture diagram, attack/defense demo, numbers, lessons learned

## 8. What "Done" Looks Like

- A working system running entirely on your local machine via Kubernetes
- A demo you can show (or record) where an attack fails against the AI *with* the security gateway on, but succeeds *without* it
- A short report with real numbers on what got caught vs. missed
- Clean, documented code on GitHub that someone else could actually run themselves

## 9. Plain-English Glossary

- **LLM** — the AI model (like the "brain" that writes answers)
- **RAG** — "Retrieval-Augmented Generation" = an AI that looks things up in a knowledge base before answering, instead of only using what it memorized during training
- **Prompt Injection** — tricking an AI with sneaky hidden instructions
- **Poisoning** — sneaking bad/fake data into a system so it behaves wrongly later
- **Gateway** — a checkpoint that all traffic passes through before reaching the real system
- **Embedding** — turning text into a list of numbers that represents its "meaning," so a computer can compare how similar two pieces of text are
- **Kubernetes (k8s)** — a system for running and managing software in organized, isolated units called "containers," the way real companies deploy production software