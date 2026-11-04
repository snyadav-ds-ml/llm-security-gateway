from langchain_core.tools import tool
import re

from langchain_classic.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from .audit import log_tool_call

retriever = None
collection = None

@tool
def search_knowledge_base(query: str) -> str:
    """Search the knowledge base for additional context."""
    # re-uses the existing retriever from chain.py
    docs = retriever.invoke(query)
    return "\n\n".join(doc.page_content for doc in docs)


@tool
def get_document_metadata(doc_id: str) -> str:
    """Look up the source and truct score of a document by its ID."""
    result = collection.get(ids=[doc_id], include=["metadatas"])
    
    if not result["metadatas"]:
        return f"No document found with id: {doc_id}"
    return str(result["metadatas"][0])


@tool
def flag_document_for_review(doc_id: str, reason: str) -> str:
    """Flag document for human review . Only call this if the user explicityly asked to flag something."""
    # the actual falgging  logic - updates metadata in ChromaDB
    #guardrail in the agent look checks consistency BEFORE this runs

    result = collection.get (ids=[doc_id], include=["metadatas"])
    if not result["metadatas"]:
        return f"No document found with id : {doc_id}"

    collection.update(
        ids=[doc_id],
        metadatas=[{**result["metadatas"][0], "flagged" : True, "flag_reason" : reason}]
    )

    return f"Document {doc_id} flagged for review : {reason}"


ALLOWED_TOOLS = {
    "search_knowledge_base" :  search_knowledge_base,
    "get_document_metadata" : get_document_metadata,
    "flag_document_for_review" : flag_document_for_review
}

def check_allow_list(tool_name :  str) -> tuple[bool, str | None]:
    if tool_name not in ALLOWED_TOOLS:
        return False, f"tool '{tool_name}' is not on the allow-list"
    return True, None

FLAG_INTENT_KEYWORDS = [
    r'\bflag\b', r'\breview\b', r'\bmark\b', r'\breport\b', r'\bsuspicious\b'
]

def check_request_consistency(tool_name :  str, user_question: str) -> tuple[bool, str|None]:
    # only the sensitive tool needs the consistency check
    if tool_name != "flag_document_for_review":
        return True, None
    
    for pattern in FLAG_INTENT_KEYWORDS:
        if re.search(pattern, user_question, re.IGNORECASE):
            return True, None
        
    return False, (
       "flag_document_for_review blocked: no flagging intent found in user question. "
       "Call likely originated from retrieved document text, not user intent."
    )

# Agent Loop

def build_agent(llm, retriever, collection):
    tools = list(ALLOWED_TOOLS.values())

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a helpful assiatant. Answer using only the knowledge base
         If the answer is not in the Knowledge base, say "I don't know."
         Only call falg_document_for_review if the user explicitly asks you to flag something."""),
         ("human", "{input}"),
         MessagesPlaceholder("agent_scratchpad"),
    ])

    agent = create_tool_calling_agent(llm, tools, prompt)
    return GuardedAgentExecutor(user_question="", agent=agent, tools=tools, verbose=True)

class GuardedAgentExecutor(AgentExecutor):
    def __init__(self, user_question: str, **kwargs):
        super().__init__(**kwargs)
        self._user_question = user_question

    def _perform_agent_action(self, name_to_tool_map, color_mapping, agent_action, run_manager=None):
        # _call_tool does not exist in langchain_classic — the framework calls
        # tool.run() directly inside _perform_agent_action. We override here so
        # the allow-list and consistency check actually intercept live tool calls.
        from langchain_classic.agents.agent import AgentStep

        tool_name  = agent_action.tool
        tool_input = agent_action.tool_input

        # 1. allow-list
        allowed, reason = check_allow_list(tool_name)
        if not allowed:
            log_tool_call(tool_name, tool_input, blocked=True, block_reason=reason)
            return AgentStep(action=agent_action, observation=f"[BLOCKED] {reason}")

        # 2. consistency check (only for flag_document_for_review)
        allowed, reason = check_request_consistency(tool_name, self._user_question)
        if not allowed:
            log_tool_call(tool_name, tool_input, blocked=True, block_reason=reason)
            return AgentStep(action=agent_action, observation=f"[BLOCKED] {reason}")

        log_tool_call(tool_name, tool_input, blocked=False)
        return super()._perform_agent_action(name_to_tool_map, color_mapping, agent_action, run_manager)