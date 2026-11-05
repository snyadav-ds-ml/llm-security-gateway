from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from .audit import log_request, init_db, log_ingest
from contextlib import asynccontextmanager
from .chain import build_chain
from .guardrails import *
from . detector import *
from .agent import *


#Why BaseModel? Pydantic validates the incoming JSON automatically. 
#If question is missing or not a string, FastAPI returns a 422 error before your code even runs. 
# This is the first line of input validation — not a security control yet, but the foundation for one.#

# request and response shapes
class ChatRequest(BaseModel):
    question:str

class ChatResponse(BaseModel):
    answer:str

@asynccontextmanager
async def lifespan(app: FastAPI):
    import os
    from langchain_ollama import ChatOllama
    global chain, retriever, collection, agent_obj
    init_db()
    chain, retriever = build_chain()   # runs once when server starts
    import phase5.agent as agent_module
    agent_module.retriever = retriever
    collection = retriever.vectorstore._collection # get raw ChromDB collection
    agent_module.collection = collection
    ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    llm = ChatOllama(model="llama3.2:3b", base_url=ollama_url)
    _executor = build_agent(llm, retriever, collection)
    agent_obj = _executor.agent
    yield

app = FastAPI(lifespan=lifespan)

# wiring guardrail in gateway
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, req: Request):
    client_ip = req.client.host
    question = request.question

    # 1. rate limit
    allowed, reason = check_rate_limit(client_ip)
    if not allowed:
        log_request(question, answer=None, blocked=True, block_reason=reason)
        raise HTTPException(status_code=429, detail=reason)

    # 2. PII redaction (mutates question, doesn't block)
    question, pii_found = redact_pii(question)

    # 3. injection detection
    allowed, reason = check_injection(question)
    if not allowed:
        log_request(question, answer=None, blocked=True, block_reason=reason)
        raise HTTPException(status_code=400, detail=reason)

    # 3b. normalize synonyms to match knowledge-base terminology
    question = normalize_query(question)

    # 4. generate
    executor = GuardedAgentExecutor(
        user_question=question,
        agent=agent_obj, tools=list(ALLOWED_TOOLS.values()), verbose=True
    )
    answer = executor.invoke({"input": question})["output"]

    # 5. output filter
    allowed, reason = filter_output(answer)
    if not allowed:
        log_request(question, answer=answer, blocked=True, block_reason=reason)
        raise HTTPException(status_code=400, detail="Response blocked: contains sensitive content")

    log_request(question, answer=answer, blocked=False)
    return ChatResponse(answer=answer)

class IngestRequest(BaseModel):
    content: str
    source: str
    provenance: str = "user_submitted" #default to least trusted

class IngestResponse(BaseModel):
    decision: str # "accept" | "flag" | "reject"
    reason: str
    outlier_distance: float | None

@app.post("/ingest", response_model=IngestResponse)
async def ingest(request: IngestRequest):
    result = assess_document(request.content, request.provenance, collection)
    
    log_ingest(
        source = request.source,
        provenance = request.provenance,
        decision = result["decision"],
        reason = result["reason"],
        outlier_distance = result["outlier_distance"],
    )

    embedding = result.pop("embedding", None)  # remove before passing to IngestResponse

    if result["decision"] == "accept":
        # pass embedding explicitly to match the 768-dim nomic-embed-text collection
        collection.add(
            ids = [request.source],
            documents = [request.content],
            embeddings = [embedding],
            metadatas = [{"source" :  request.source, "provenance" : request.provenance}],
        )

    return IngestResponse(**result)




