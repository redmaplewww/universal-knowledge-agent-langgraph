from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from uka_langgraph.orchestration.context import RuntimeContext
from uka_langgraph.orchestration.nodes import approval_interrupt, security_from_state
from uka_langgraph.orchestration.state import WorkflowState


def _compile(
    state: WorkflowState, runtime: Runtime[RuntimeContext]
) -> dict[str, Any]:
    payload = state.get("payload", {})
    knowledge_id = str(payload.get("knowledge_id", ""))
    knowledge = runtime.context.services.repository.get_revision(
        security_from_state(state), "knowledge", knowledge_id
    )
    if knowledge is None:
        return {"status": "rejected", "errors": ["knowledge_not_found"]}
    content = str(knowledge.payload.get("content", "")).strip()
    if len(content) < 8:
        return {"status": "rejected", "errors": ["procedure_not_eligible"]}
    candidate = runtime.context.services.lifecycle.compile_skill(
        request_id=state["request_id"],
        knowledge=knowledge,
        name=str(payload.get("name") or f"skill-{knowledge_id[-8:]}"),
    )
    return {"skill_ids": [candidate.object_id], "status": "compiled"}


def _compile_route(state: WorkflowState) -> str:
    return "validate" if not state.get("errors") else "rejected"


def _validate(
    state: WorkflowState, runtime: Runtime[RuntimeContext]
) -> dict[str, Any]:
    skill = runtime.context.services.repository.get_revision(
        security_from_state(state), "skill", state["skill_ids"][0]
    )
    if skill is None:
        return {"status": "rejected", "errors": ["skill_candidate_missing"]}
    result = runtime.context.services.lifecycle.validate_skill(skill)
    return {
        "status": "static_validated" if result["passed"] else "rejected",
        "errors": result["errors"],
        "evaluation_ids": [f"{state['request_id']}:skill-static"],
    }


def _sandbox_test(
    state: WorkflowState, runtime: Runtime[RuntimeContext]
) -> dict[str, Any]:
    skill = runtime.context.services.repository.get_revision(
        security_from_state(state), "skill", state["skill_ids"][0]
    )
    if skill is None:
        return {"status": "rejected", "errors": ["skill_candidate_missing"]}
    result = runtime.context.services.lifecycle.sandbox_test_skill(skill)
    return {
        "status": "sandbox_passed" if result["passed"] else "rejected",
        "errors": result["errors"],
        "evaluation_ids": [f"{state['request_id']}:skill-sandbox"],
        "warnings": ["p0_advisory_skill_no_external_execution"],
    }


def _safety_review(state: WorkflowState) -> dict[str, Any]:
    if state.get("payload", {}).get("auto_approve") is True:
        return {"approved": True, "status": "approved"}
    return approval_interrupt(
        state,
        subject="skill_activation",
        details={
            "skill_ids": state.get("skill_ids", []),
            "permissions": [],
            "network": "deny",
            "test_mode": "advisory-only",
        },
    )


def _activate(
    state: WorkflowState, runtime: Runtime[RuntimeContext]
) -> dict[str, Any]:
    skill = runtime.context.services.repository.get_revision(
        security_from_state(state), "skill", state["skill_ids"][0]
    )
    if skill is None:
        return {"status": "rejected", "errors": ["skill_candidate_missing"]}
    receipt_id = runtime.context.services.lifecycle.activate(
        skill, request_id=state["request_id"]
    )
    return {
        "status": "active",
        "response": {"skill_ids": state["skill_ids"], "stage": "active"},
        "receipt_ids": [receipt_id],
    }


def _rejected(state: WorkflowState) -> dict[str, Any]:
    return {
        "status": "rejected",
        "response": {"reason": "skill_fail_closed", "errors": state.get("errors", [])},
    }


def build_skill_subgraph():
    builder = StateGraph(WorkflowState, context_schema=RuntimeContext)
    builder.add_node("compile", _compile)
    builder.add_node("validate", _validate)
    builder.add_node("sandbox_test", _sandbox_test)
    builder.add_node("safety_review", _safety_review)
    builder.add_node("activate", _activate)
    builder.add_node("rejected", _rejected)
    builder.add_edge(START, "compile")
    builder.add_conditional_edges(
        "compile", _compile_route, {"validate": "validate", "rejected": "rejected"}
    )
    builder.add_edge("validate", "sandbox_test")
    builder.add_conditional_edges(
        "sandbox_test",
        lambda state: "review" if not state.get("errors") else "rejected",
        {"review": "safety_review", "rejected": "rejected"},
    )
    builder.add_conditional_edges(
        "safety_review",
        lambda state: "activate" if state.get("approved") else "rejected",
        {"activate": "activate", "rejected": "rejected"},
    )
    builder.add_edge("activate", END)
    builder.add_edge("rejected", END)
    return builder.compile()
