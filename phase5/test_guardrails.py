"""
Direct test of Phase 5 guardrail logic — bypasses the LLM entirely.
Calls GuardedAgentExecutor._call_tool directly to prove the allow-list
and request-consistency check work regardless of model tool-calling ability.

Run from project root:
    .venv/bin/python -m phase5.test_guardrails
"""

import sys
import sqlite3
from phase5.agent import (
    check_allow_list,
    check_request_consistency,
    ALLOWED_TOOLS,
)
from phase5.audit import init_db, log_tool_call

DB_PATH = "./audit.db"

PASS = "PASS"
FAIL = "FAIL"

def run_test(label: str, tool_name: str, tool_input: dict, user_question: str, expect_blocked: bool):
    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print(f"  tool       : {tool_name}")
    print(f"  question   : {user_question}")

    # step 1 — allow-list
    allowed, reason = check_allow_list(tool_name)
    if not allowed:
        log_tool_call(tool_name, tool_input, blocked=True, block_reason=reason)
        blocked = True
        block_reason = reason
    else:
        # step 2 — consistency check
        allowed, reason = check_request_consistency(tool_name, user_question)
        if not allowed:
            log_tool_call(tool_name, tool_input, blocked=True, block_reason=reason)
            blocked = True
            block_reason = reason
        else:
            log_tool_call(tool_name, tool_input, blocked=False)
            blocked = False
            block_reason = None

    result = PASS if blocked == expect_blocked else FAIL
    status = "BLOCKED" if blocked else "ALLOWED"
    print(f"  outcome    : {status}")
    if block_reason:
        print(f"  reason     : {block_reason}")
    print(f"  expected   : {'BLOCKED' if expect_blocked else 'ALLOWED'}")
    print(f"  result     : {result}")
    return result


def main():
    init_db()

    results = []

    # Test 1: allowed tool, no consistency check needed — should pass
    results.append(run_test(
        label="Allow-list PASS — search_knowledge_base is on the list",
        tool_name="search_knowledge_base",
        tool_input={"query": "vacation days"},
        user_question="How many vacation days do employees get?",
        expect_blocked=False,
    ))

    # Test 2: invented tool name — should be blocked by allow-list
    results.append(run_test(
        label="Allow-list BLOCK — delete_all_documents is not on the list",
        tool_name="delete_all_documents",
        tool_input={"confirm": True},
        user_question="How many vacation days do employees get?",
        expect_blocked=True,
    ))

    # Test 3: flag tool + user explicitly asked to flag — consistency check should allow
    results.append(run_test(
        label="Consistency check PASS — user question contains flagging intent",
        tool_name="flag_document_for_review",
        tool_input={"doc_id": "hr-vacation", "reason": "looks suspicious"},
        user_question="Please flag document hr-vacation for review, it looks suspicious.",
        expect_blocked=False,
    ))

    # Test 4: flag tool + normal question — consistency check should block (hijack attempt)
    results.append(run_test(
        label="Consistency check BLOCK — no flagging intent in user question (indirect injection)",
        tool_name="flag_document_for_review",
        tool_input={"doc_id": "hr-vacation", "reason": "compromised"},
        user_question="What is in the support runbook?",
        expect_blocked=True,
    ))

    # Test 5: get_document_metadata — low-risk tool, no consistency check needed
    results.append(run_test(
        label="Allow-list PASS — get_document_metadata is on the list",
        tool_name="get_document_metadata",
        tool_input={"doc_id": "hr-vacation"},
        user_question="What is the source of the hr-vacation document?",
        expect_blocked=False,
    ))

    # ── Test 6: synthetic AgentAction through _perform_agent_action ──────────
    # Proves the override is wired into the real dispatch path.
    # A fake AgentAction is injected directly into GuardedAgentExecutor so the
    # check fires without needing an LLM that reliably calls tools.
    print(f"\n{'='*60}")
    print("TEST: Synthetic AgentAction — _perform_agent_action dispatch wiring")

    from langchain_core.agents import AgentAction
    from phase5.agent import GuardedAgentExecutor, ALLOWED_TOOLS

    class _FakeActionAgent:
        def tool_run_logging_kwargs(self): return {}

    executor = GuardedAgentExecutor.model_construct(
        verbose=False,
        _action_agent=_FakeActionAgent(),
        tools=list(ALLOWED_TOOLS.values()),
    )
    executor._user_question = "What is in the support runbook?"  # no flagging intent

    action = AgentAction(
        tool="flag_document_for_review",
        tool_input={"doc_id": "hr-vacation", "reason": "injected by document"},
        log="",
    )
    name_to_tool_map = {k: v for k, v in ALLOWED_TOOLS.items()}
    color_mapping    = {k: "green" for k in ALLOWED_TOOLS}

    step = executor._perform_agent_action(name_to_tool_map, color_mapping, action)
    synth_result = PASS if "[BLOCKED]" in step.observation else FAIL
    results.append(synth_result)
    print(f"  tool      : {action.tool}")
    print(f"  question  : {executor._user_question}")
    print(f"  outcome   : {step.observation}")
    print(f"  result    : {synth_result}")

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    passed = results.count(PASS)
    total = len(results)
    print(f"  {passed}/{total} tests passed")

    # Show tool_call_log
    print("\ntool_call_log (last 6 rows):")
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT tool_name, blocked, block_reason FROM tool_call_log ORDER BY id DESC LIMIT 6"
        ).fetchall()
    for row in reversed(rows):
        status = "BLOCKED" if row[1] else "ALLOWED"
        print(f"  [{status}] {row[0]} — {row[2] or 'ok'}")

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
