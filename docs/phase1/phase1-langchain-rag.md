# Phase 1B: langchain_rag.py — What, Why, and How

The same 6-step RAG pipeline rebuilt with LangChain. Every LangChain class maps directly to a function you already wrote in `manual_rag.py`. Read both side by side.

---

## Why Rebuild It With LangChain?

In Part A you controlled every line. In Part B LangChain handles the boilerplate — file loading, text splitting, embedding batching, vector store management, prompt formatting, chain wiring. The framework doesn't change *what* happens, only *how much you write*.

More importantly: Phase 2's security gateway wraps the LangChain chain. Understanding what the chain does internally makes it much easier to intercept the right place.

---

## The Mapping: Manual → LangChain

| Part A (manual) | Part B (LangChain) | What the framework adds |
|---|---|---|
| `open()` loop over `.txt` files | `DirectoryLoader` + `TextLoader` | Yields `Document` objects with `page_content` and `metadata` auto-filled |
| `chunk_text()` with string slicing | `RecursiveCharacterTextSplitter` | Splits on paragraph → sentence → word boundaries before falling back to character count |
| `embed()` calling `/api/embeddings` | `OllamaEmbeddings(model="nomic-embed-text")` | Batches multiple chunks in one call, handles retries |
| `build_collection()` with `collection.add()` | `Chroma.from_documents()` | Creates collection, embeds, and stores in one call |
| `collection.query()` | `vectorstore.as_retriever()` | Standard retriever interface any chain can call |
| f-string prompt template | `ChatPromptTemplate.from_template()` | Typed, validates variables at construction time |
| `POST /api/generate` | `ChatOllama(model="llama3.2:3b")` | Handles message formatting, retries |
| manual join → HTTP call | LCEL chain with `\|` operator | Wires retriever → prompt → LLM in one object |

---

## Step 1 — Load Documents

**Manual version:**
```python
for filename in os.listdir(data_dir):
    with open(...) as f:
        documents.append({"source": filename, "content": f.read()})
```

**LangChain version:**
```python
from langchain_community.document_loaders import DirectoryLoader, TextLoader

loader = DirectoryLoader("data", glob="*.txt", loader_cls=TextLoader)
docs = loader.load()
```

`docs` is a list of `Document` objects. Each has:
- `doc.page_content` — the raw text (was `doc["content"]`)
- `doc.metadata` — dict with `source` key auto-filled (was `doc["source"]`)

**Why `DirectoryLoader`?** It handles multiple file types, recursive folder traversal, and error handling. For now it does the same thing as your loop, but the interface is standardised — every LangChain component downstream expects `Document` objects, not plain dicts.

---

## Step 2 — Chunk Text

**Manual version:**
```python
def chunk_text(text, chunk_size=500, overlap=50):
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks
```

**LangChain version:**
```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
chunks = splitter.split_documents(docs)
```

`chunks` is still a list of `Document` objects — `page_content` is now the chunk text, `metadata` carries the source filename forward automatically.

**Key difference:** Your manual splitter cuts at exactly 500 characters regardless of where a sentence ends. `RecursiveCharacterTextSplitter` tries to split on `\n\n` first (paragraph), then `\n` (line), then `. ` (sentence), then ` ` (word), and only falls back to character count if none of those work. This produces more natural chunks that don't cut mid-sentence as often.

---

## Step 3 + 4 — Embed and Store (combined)

**Manual version:** two separate steps — call `embed()` per chunk, then call `collection.add()`.

**LangChain version:** one call does both:
```python
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma

embeddings = OllamaEmbeddings(model="nomic-embed-text")

vectorstore = Chroma.from_documents(
    documents=chunks,
    embedding=embeddings,
    persist_directory="./chroma_db_langchain"
)
```

`Chroma.from_documents()` loops over every chunk, calls `OllamaEmbeddings` to get the vector, and stores text + vector + metadata in ChromaDB — all in one line. Internally it's doing exactly what your `embed()` + `build_collection()` did.

**Why a separate `chroma_db_langchain/` folder?** Keeps Part A and Part B collections separate so they don't conflict. Same underlying ChromaDB, different collection name.

**On subsequent runs** — load the existing store instead of rebuilding:
```python
vectorstore = Chroma(
    persist_directory="./chroma_db_langchain",
    embedding_function=embeddings
)
```

---

## Step 5 — Retrieve

**Manual version:**
```python
def retrieve(question, collection, n_results=3):
    query_embedding = embed(question)
    results = collection.query(query_embeddings=[query_embedding], n_results=n_results, ...)
    return results
```

**LangChain version:**
```python
retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
```

`retriever` is a standard LangChain interface. Calling `retriever.invoke("question")` returns a list of `Document` objects. The chain in Step 6 calls this automatically — you don't invoke it manually.

---

## Step 6 — Generate (the full chain)

**Manual version:** build prompt string → POST to `/api/generate` → parse response.

**LangChain version uses LCEL** (LangChain Expression Language) — a pipe `|` operator that chains steps:

```python
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

llm = ChatOllama(model="llama3.2:3b")

prompt = ChatPromptTemplate.from_template("""You are a helpful assistant. Answer using only the context below.
If the answer is not in the context, say "I don't know."

Context: {context}

Question: {question}

Answer:""")

def format_docs(docs):
    # joins retrieved Document objects into one context string
    return "\n\n".join(doc.page_content for doc in docs)

chain = (
    {"context": retriever | format_docs, "question": RunnablePassthrough()}
    | prompt
    | llm
    | StrOutputParser()
)
```

**What each `|` does:**
1. `retriever | format_docs` — retrieves top-3 chunks, joins them into a string → fills `{context}`
2. `RunnablePassthrough()` — passes the question through unchanged → fills `{question}`
3. `| prompt` — inserts both into the prompt template
4. `| llm` — sends to `llama3.2:3b`
5. `| StrOutputParser()` — extracts the string from the LLM response object

**To get an answer:**
```python
answer = chain.invoke("How many vacation days do employees get per year?")
```

This single call triggers all 5 steps above in sequence. In Phase 2, the security gateway intercepts `invoke()` to check the question before it reaches the retriever and check the answer before it returns.

---

## Full Main Block

```python
if __name__ == "__main__":
    # Steps 1-2: load and chunk
    loader = DirectoryLoader("data", glob="*.txt", loader_cls=TextLoader)
    docs = loader.load()
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_documents(docs)

    # Steps 3-4: embed and store
    embeddings = OllamaEmbeddings(model="nomic-embed-text")
    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory="./chroma_db_langchain"
    )

    # Step 5: retriever
    retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

    # Step 6: chain
    chain = (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )

    # test questions
    questions = [
        "How many vacation days do employees get per year?",
        "What are the support hours for the premium plan?",
        "Who should an employee contact to report a security incident?",
    ]

    for q in questions:
        answer = chain.invoke(q)
        print(f"\nQ: {q}")
        print(f"Answer: {answer}")
```

---

## Done Criteria for Part B

- [ ] `python phase1/langchain_rag.py` runs without errors
- [ ] All 3 test questions produce answers equivalent to Part A
- [ ] You can map each LangChain class back to its Part A equivalent (the table above)
- [ ] `chroma_db_langchain/` added to `.gitignore`
- [ ] You can explain what LCEL's `|` operator does at each step
