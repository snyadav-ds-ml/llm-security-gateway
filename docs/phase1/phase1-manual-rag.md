# Phase 1A: manual_rag.py — What, Why, and How

A complete walkthrough of every concept behind `phase1/manual_rag.py` before any code is written.

---

## Big Picture

`manual_rag.py` is a single script that runs the full RAG loop using nothing but `requests`, `chromadb`, and Python's standard library. No LangChain, no magic.

It does two things when you run it:
1. **Ingest** — reads every `.txt` file in `data/`, chunks and embeds them, stores the result in ChromaDB on disk
2. **Query** — takes 3 hardcoded test questions, retrieves the closest chunks, builds a prompt, sends it to Ollama, prints the answer + the source chunk it came from

```bash
# run from project root, venv active
python phase1/manual_rag.py
```

Expected output per question:
```
Q: How many vacation days do employees get per year?
Source: 03-leave-policy.txt (chunk 0)
Answer: Employees receive 24 days of paid annual leave per calendar year.
```

If you see an answer without a source chunk, you can't verify whether retrieval worked or the model just guessed. Printing the source is how you confirm the answer came from the knowledge base, not the model's training memory.

---

## Step 1 — Load Documents

**What the code does:** Walks `data/`, opens each `.txt` file, reads it into a string, tracks the filename as metadata.

```python
import os

def load_documents(data_dir):
    docs = []
    for filename in sorted(os.listdir(data_dir)):
        if filename.endswith(".txt"):
            path = os.path.join(data_dir, filename)
            with open(path, "r") as f:
                docs.append({"text": f.read(), "source": filename})
    return docs
```

**Why track the filename?** When the model answers, you want to print which document it came from. This `source` field also becomes the foundation of trust scoring in Phase 4 — the poisoning detector checks where documents came from.

**Without this step:** The model answers from training memory alone and will hallucinate facts about Aurora Dynamics because it has never seen these files.

---

## Step 2 — Chunk Text

**What the code does:** Splits each document string into smaller overlapping pieces.

```python
def chunk_text(text, chunk_size=500, overlap=50):
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap  # step back by overlap before next chunk
    return chunks
```

**Why not send the whole document to the LLM?**
- LLMs have a context window limit — a long document may not fit.
- Similarity search works better on focused passages. Embedding a full handbook averages the meaning of everything in it; a chunk about "leave policy" has a sharper, more specific embedding.

**Why overlap?**
Imagine a sentence split exactly at character 500: `"Employees receive 24 days of paid annual leave per calendar"` *(cut)* `"year."` — the answer is now split across two chunks and neither contains the complete sentence. A 50-character overlap repeats the tail of one chunk as the head of the next so no sentence is lost at a boundary.

**Chunk size 500:** Reasonable default for short policy documents (~80–100 words). Too small = chunks lose context. Too large = embeddings become vague. You'll tune this in later phases.

---

## Step 3 — Embed Chunks

**What an embedding is:** Text gets turned into a list of ~768 numbers (a vector) that encodes its *meaning*, not its words. Two chunks about the same topic — even phrased differently — will have similar vectors. That's what makes semantic search possible.

**What the code does:** One HTTP POST to Ollama's embedding endpoint per chunk.

```python
import requests

def embed(text):
    response = requests.post(
        "http://localhost:11434/api/embeddings",
        json={"model": "nomic-embed-text", "prompt": text}
    )
    return response.json()["embedding"]  # list of ~768 floats
```

**Why `nomic-embed-text` and not `llama3.2:3b`?**
They are different tools. `nomic-embed-text` is trained to produce vectors where similar texts are numerically close. `llama3.2:3b` is trained to predict the next token — it can produce embeddings too but they are much worse for retrieval.

**What do the numbers mean?**
You never look at them individually. What matters is the *distance* between two vectors. If `embed("vacation days")` and `embed("24 days of paid annual leave")` are 0.05 apart, and `embed("vacation days")` and `embed("password reset")` are 0.87 apart — the first pair is semantically similar, the second is not.

**Performance note:** Embedding all 6 documents takes a few seconds on first run. That's why we persist to disk in Step 4 — embeddings are computed once, reused on every run after.

---

## Step 4 — Store in ChromaDB

**What ChromaDB is:** A vector database that runs as a Python library — no server, no Docker needed. It stores three things per chunk: the raw text, its embedding vector, and any metadata you attach.

**What the code does:**

```python
import chromadb

def build_collection(chunks_with_metadata, persist_path="./chroma_db"):
    client = chromadb.PersistentClient(path=persist_path)
    collection = client.get_or_create_collection(name="rag_docs")

    collection.add(
        ids=[m["id"] for m in chunks_with_metadata],
        documents=[m["text"] for m in chunks_with_metadata],
        embeddings=[m["embedding"] for m in chunks_with_metadata],
        metadatas=[{"source": m["source"], "chunk_index": m["index"]} for m in chunks_with_metadata]
    )
    return collection
```

**What is a collection?** Think of it as a table. This project uses one collection called `rag_docs`. Later phases add more metadata fields — like `trust_score` and `flagged` for the poisoning detector — to the same collection.

**What gets written to disk?** A `chroma_db/` folder at the project root containing SQLite and binary index files. You never edit these directly. On every run after the first, `get_or_create_collection` opens the existing collection instead of rebuilding it.

**Why `PersistentClient` and not `Client()`?** The default in-memory client loses everything when the script exits. `PersistentClient` writes to disk so the database survives between runs.

---

## Step 5 — Retrieve

**What the code does:** Embeds the user's question with the same model, asks ChromaDB for the 3 closest chunks.

```python
def retrieve(question, collection, n_results=3):
    query_embedding = embed(question)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"]
    )
    return results
```

**How does ChromaDB find the closest chunks?** Cosine similarity — it measures the angle between two vectors. A distance of `0.0` is a perfect match; `2.0` is the maximum. Results come back sorted closest to furthest.

**Why 3 results?** Three chunks give the LLM enough context without overloading the prompt. One chunk might miss the answer if it landed at a boundary; five risks including irrelevant text that confuses the model.

**Why the same embedding model for query and chunks?** Critical. If you embed chunks with `nomic-embed-text` and the query with a different model, the vector spaces are incompatible — distances become meaningless and retrieval breaks completely.

---

## Step 6 — Generate

**What the code does:** Joins retrieved chunks into a context block, inserts into a prompt, sends to Ollama.

```python
def generate(question, retrieved_chunks):
    context = "\n\n".join(retrieved_chunks)

    prompt = f"""You are a helpful assistant. Answer using only the context below.
If the answer is not in the context, say "I don't know."

Context:
{context}

Question: {question}
Answer:"""

    response = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": "llama3.2:3b", "prompt": prompt, "stream": False}
    )
    return response.json()["response"]
```

**Why context before the question?** LLMs attend better to text early in the prompt. Putting context first and the question last gives the model the facts before it needs them.

**Why "If the answer is not in the context, say I don't know"?** Without this, the model falls back to training memory when retrieved chunks don't contain the answer — producing confident-sounding hallucinations. This is the simplest form of output grounding. The security gateway in Phase 2 enforces this more strictly.

**Why `stream: False`?** Streaming sends tokens one at a time. For this script we want the complete answer as a single string.

---

## File Layout After Running

```
Security_Project/
├── data/                        # already exists, unchanged
├── phase1/
│   └── manual_rag.py            # the only new file you write (~80–100 lines)
├── chroma_db/                   # created automatically on first run — add to .gitignore
├── pyproject.toml
├── uv.lock
└── .venv/
```

No new dependencies needed — `chromadb` and `requests` are already in `pyproject.toml`.

---

## Done Criteria for Part A

- [ ] `python phase1/manual_rag.py` runs without errors
- [ ] All 3 test questions print a correct answer AND the source chunk it came from
- [ ] You can explain what each of the 6 functions does and why it exists
- [ ] `chroma_db/` folder is created and added to `.gitignore`
