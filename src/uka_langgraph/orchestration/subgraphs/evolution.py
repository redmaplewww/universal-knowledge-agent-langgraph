from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from uka_langgraph.orchestration.context import RuntimeContext
from uka_langgraph.orchestration.nodes import approval_interrupt, security_from_state
from uka_langgraph.orchestration.state import WorkflowState


def _propose(
    state: WorkflowState, runtime: Runtime[RuntimeContext]
) -> dict[str, Any]:
    payload = state.get("payload", {})
    target_type = str(payload.get("target_type", ""))
    baseline = str(payload.get("baseline_revision", ""))
    candidate = str(payload.get("candidate_revision", ""))
    if not target_type or not baseline or not candidate or baseline == candidate:
        return {"status": "rejected", "errors": ["invalid_evolution_proposal"]}
    proposal = runtime.context.services.lifecycle.create_candidate(
        request_id=state["request_id"],
        object_type="evolution",
        payload={
            "target_type": target_type,
            "baseline_revision": baseline,
            "candidate_revision": candidate,
            "metrics": payload.get("metrics", {}),
            "stage": "proposal",
        },
        evidence_ids=state.get("evidence_ids", []),
        security=security_from_state(state),
    )
    return {"evaluation_ids": [proposal.object_id], "status": "proposed"}


def _evaluate_stage(
    state: WorkflowState, runtime: Runtime[RuntimeContext], stage: str
) -> dict[str, Any]:
    payload = state.get("payload", {})
    metrics = state.get("payload", {}).get("metrics", {})
    result = runtime.context.services.lifecycle.verify_evolution_evidence(
        security=security_from_state(state),
        stage=stage,
        target_type=str(payload.get("target_type", "")),
        baseline_revision=str(payload.get("baseline_revision", "")),
        candidate_revision=str(payload.get("candidate_revision", "")),
        evaluation_ids=dict(metrics.get("evaluation_ids", {})),
    )
    passed = bool(result.get("passed"))
    next_by_stage = {"offline": "shadow", "shadow": "canary", "canary": "review"}
    return {
        "status": f"{stage}_passed" if passed else "rejected",
        "next_action": next_by_stage[stage] if passed else "rejected",
        "warnings": [] if passed else [str(result.get("reason", "evaluation_failed"))],
        "evaluation_ids": [str(result["evaluation_id"])] if passed else [],
    }


def _offline_evaluate(
    state: WorkflowState, runtime: Runtime[RuntimeContext]
) -> dict[str, Any]:
    return _evaluate_stage(state, runtime, "offline")


def _review(state: WorkflowState) -> dict[str, Any]:
    return approval_interrupt(
        state,
        subject="evolution_candidate_canary",
        details={
            "proposal_ids": state.get("evaluation_ids", []),
            "metrics": state.get("payload", {}).get("metrics", {}),
            "next_stage": "shadow_then_canary",
        },
    )


def _shadow(
    state: WorkflowState, runtime: Runtime[RuntimeContext]
) -> dict[str, Any]:
    return _evaluate_stage(state, runtime, "shadow")


def _canary(
    state: WorkflowState, runtime: Runtime[RuntimeContext]
) -> dict[str, Any]:
    return _evaluate_stage(state, runtime, "canary")


def _activate(
    state: WorkflowState, runtime: Runtime[RuntimeContext]
) -> dict[str, Any]:
    proposal = runtime.context.services.repository.get_revision(
        security_from_state(state), "evolution", state["evaluation_ids"][0]
    )
    if proposal is None:
        return {"status": "rejected", "errors": ["proposal_missing"]}
    receipt_id = runtime.context.services.lifecycle.activate(
        proposal, request_id=state["request_id"]
    )
    return {
        "status": "active",
        "response": {
            "proposal_ids": state["evaluation_ids"],
            "stage": "active",
            "note": "P0 records approval; production deployment remains external.",
        },
        "receipt_ids": [receipt_id],
    }


def _rejected(state: WorkflowState) -> dict[str, Any]:
    return {
        "status": "rejected",
        "response": {
            "reason": "evolution_fail_closed",
            "warnings": state.get("warnings", []),
            "errors": state.get("errors", []),
        },
    }


def build_evolution_subgraph():
    builder = StateGraph(WorkflowState, context_schema=RuntimeContext)
    builder.add_node("propose", _propose)
    builder.add_node("offline_evaluate", _offline_evaluate)
    builder.add_node("shadow", _shadow)
    builder.add_node("canary", _canary)
    builder.add_node("review", _review)
    builder.add_node("activate", _activate)
    builder.add_node("rejected", _rejected)
    builder.add_edge(START, "propose")
    builder.add_conditional_edges(
        "propose",
        lambda state: "offline" if not state.get("errors") else "rejected",
        {"offline": "offline_evaluate", "rejected": "rejected"},
    )
    builder.add_conditional_edges(
        "offline_evaluate",
        lambda state: state.get("next_action", "rejected"),
        {"shadow": "shadow", "rejected": "rejected"},
    )
    builder.add_conditional_edges(
        "shadow",
        lambda state: state.get("next_action", "rejected"),
        {"canary": "canary", "rejected": "rejected"},
    )
    builder.add_conditional_edges(
        "canary",
        lambda state: state.get("next_action", "rejected"),
        {"review": "review", "rejected": "rejected"},
    )
    builder.add_conditional_edges(
        "review",
        lambda state: "activate" if state.get("approved") else "rejected",
        {"activate": "activate", "rejected": "rejected"},
    )
    builder.add_edge("activate", END)
    builder.add_edge("rejected", END)
    return builder.compile()
