# Phase 2: Gateway Skeleton — What, Why, and How

A FastAPI server with a `/chat` endpoint that wraps the LangChain chain from Phase 1, plus a SQLite audit log that records every request and response.

---

## Big Picture

Phase 1 was a script you ran from the terminal. Phase 2 turns it into a web service — the first real piece of the security gateway architecture.

```
User sends POST /chat  {"question": "..."}
            │
            ▼
      FastAPI endpoint
            │
            ▼
   LangChain chain (Phase 1)
            │
            ▼
    SQLite audit log  ← every request written here
            │
            ▼
    {"answer": "..."}  returned to user
```

Right now the gateway is just a pass-through — it receives the question, runs the chain, logs it, returns the answer. No security controls yet. Those come in Phase 3. The point of this phase is to have the plumbing in place so Phase 3 has somewhere to add its checks.

---

## Why FastAPI?

In Phase 1 you called the chain directly from a script. In a real system, users talk to an API over HTTP. FastAPI is the standard Python framework for this:

- Automatic input validation via type hints — if the request body is missing `question`, FastAPI rejects it before your code runs
- Auto-generated docs at `/docs` (Swagger UI) — you can test the endpoint in a browser without writing any extra code
- Async support — handles multiple requests without blocking
- Used in production by real companies; not a toy

**Comparison to Phase 1:** `chain.invoke(q)` becomes `chain.invoke(request.question)` inside an endpoint function. Almost identical code, now accessible over HTTP.

---

## Step 1 — Project Structure

New files this phase creates:

```
Security_Project/
├── phase2/
│   ├── gateway.py        ← FastAPI app + /chat endpoint
│   └── audit.py          ← SQLite audit log functions
├── audit.db              ← created automatically on first run
```

The LangChain chain setup (loading, chunking, embedding, vectorstore) moves into a shared `build_chain()` function called once at startup — not on every request.

---

## Step 2 — The FastAPI App (`gateway.py`)

**What it does:** Defines the FastAPI app, loads the chain at startup, exposes `/chat`.

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

# request and response shapes
class ChatRequest(BaseModel):
    question: str

class ChatResponse(BaseModel):
    answer: str
```

**Why `BaseModel`?** Pydantic validates the incoming JSON automatically. If `question` is missing or not a string, FastAPI returns a 422 error before your code even runs. This is the first line of input validation — not a security control yet, but the foundation for one.

**The endpoint:**
```python
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    answer = chain.invoke(request.question)
    log_request(request.question, answer)   # write to audit log
    return ChatResponse(answer=answer)
```

**Startup — load chain once:**
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    global chain, retriever
    chain, retriever = build_chain()   # runs once when server starts
    yield

app = FastAPI(lifespan=lifespan)
```

Why load at startup and not per request? Embedding all documents and building the ChromaDB index takes several seconds. Doing it on every `/chat` request would make the API unusably slow.

---

## Step 3 — SQLite Audit Log (`audit.py`)

**What it is:** A SQLite database with one table that records every request. SQLite is a file-based database built into Python — no server, no setup.

**Why log everything?** The security controls in Phase 3 will block some requests. Without a log, you have no record of what was blocked, why, or when. The audit log is also how you compute the detection rate in Phase 6.

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    question    TEXT NOT NULL,
    answer      TEXT,
    blocked     INTEGER DEFAULT 0,   -- 0 = allowed, 1 = blocked
    block_reason TEXT                -- null if allowed, reason string if blocked
);
```

**The `log_request` function:**
```python
import sqlite3
from datetime import datetime, timezone

DB_PATH = "./audit.db"

def init_db():
    # creates the table if it doesn't exist — safe to call on every startup
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp    TEXT NOT NULL,
                question     TEXT NOT NULL,
                answer       TEXT,
                blocked      INTEGER DEFAULT 0,
                block_reason TEXT
            )
        """)

def log_request(question: str, answer: str, blocked: bool = False, block_reason: str = None):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO audit_log (timestamp, question, answer, blocked, block_reason) VALUES (?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), question, answer, int(blocked), block_reason)
        )
```

**Why `blocked` and `block_reason` now?** The table is designed for Phase 3 already. When Phase 3 adds security controls, it calls `log_request(..., blocked=True, block_reason="prompt injection detected")` with no schema change needed.

---

## Step 4 — How to Run It

```bash
# install FastAPI and uvicorn (ASGI server)
uv add fastapi uvicorn

# run from project root
uvicorn phase2.gateway:app --reload --port 8000
```

`--reload` restarts the server automatically when you save a file — useful during development.

**Test it:**
```bash
# in a second terminal
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "How many vacation days do employees get?"}'
```

Or open `http://localhost:8000/docs` in a browser for the Swagger UI.

**Check the audit log:**
```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('audit.db')
for row in conn.execute('SELECT * FROM audit_log'):
    print(row)
"
```

---

## File Layout After Phase 2

```
Security_Project/
├── data/
├── phase1/
│   ├── manual_rag.py
│   └── langchain_rag.py
├── phase2/
│   ├── __init__.py       ← empty file, makes phase2 a Python package
│   ├── gateway.py        ← FastAPI app
│   └── audit.py          ← SQLite log functions
├── audit.db              ← created on first run, add to .gitignore
├── chroma_db_langchain/  ← reused from Phase 1
```

---

## Done Criteria

- [ ] `uvicorn phase2.gateway:app --reload` starts without errors
- [ ] `POST /chat` returns a correct answer for all 3 test questions
- [ ] Every request creates a row in `audit.db` with timestamp, question, and answer
- [ ] `/docs` loads in the browser and shows the `/chat` endpoint
- [ ] Chain is built once at startup, not per request
