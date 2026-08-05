from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from uka_langgraph.orchestration.context import RuntimeContext
from uka_langgraph.orchestration.nodes import approval_interrupt, security_from_state
from uka_langgraph.orchestration.state import WorkflowState


def _prepare(
    state: WorkflowState, runtime: Runtime[RuntimeContext]
) -> dict[str, Any]:
    payload = state.get("payload", {})
    required = ("target_id", "expected_revision", "replacement_ref")
    if any(name not in payload for name in required):
        return {
            "status": "review_required",
            "next_action": "confirm_target",
            "warnings": ["correction_target_incomplete"],
        }
    result = runtime.context.services.corrections.prepare(
        request_id=state["request_id"],
        target_id=str(payload["target_id"]),
        expected_revision=int(payload["expected_revision"]),
        replacement_ref=str(payload["replacement_ref"]),
        actor_id=state["actor_id"],
        security=security_from_state(state),
    )
    if not result.get("resolved"):
        return {
            "status": "review_required",
            "next_action": "confirm_target",
            "warnings": [str(result.get("reason", "target_ambiguous"))],
        }
    return {
        "correction_ids": result["correction_ids"],
        "evidence_ids": result["evidence_ids"],
        "receipt_ids": result["receipt_ids"],
        "status": "correction_recorded",
        "next_action": "recompute",
    }


def _prepare_route(state: WorkflowState) -> str:
    return state.get("next_action", "confirm_target")


def _confirm_target(state: WorkflowState) -> dict[str, Any]:
    resolution = interrupt(
        {
            "type": "target_resolution_required",
            "request_id": state["request_id"],
            "current_payload": {
                key: state.get("payload", {}).get(key)
                for key in ("target_id", "expected_revision")
            },
            "required": ["target_id", "expected_revision"],
        }
    )
    if not isinstance(resolution, dict):
        return {"status": "rejected", "errors": ["invalid_target_resolution"]}
    payload = dict(state.get("payload", {}))
    payload.update(
        {
            "target_id": resolution.get("target_id"),
            "expected_revision": resolution.get("expected_revision"),
        }
    )
    return {"payload": payload, "next_action": "prepare", "status": "target_resolved"}


def _recompute(
    state: WorkflowState, runtime: Runtime[RuntimeContext]
) -> dict[str, Any]:
    result = runtime.context.services.corrections.recompute(
        request_id=state["request_id"],
        correction_id=state["correction_ids"][0],
        security=security_from_state(state),
    )
    if not result.get("passed"):
        return {
            "status": "held",
            "next_action": "hold",
            "warnings": [str(result.get("reason"))],
        }
    return {
        "knowledge_ids": result["knowledge_ids"],
        "response": result,
        "status": "regression_passed",
        "next_action": "review",
        "impact_ids": result["impact_ids"],
        "evaluation_ids": result["evaluation_ids"],
        "scope_ids": result.get("scope_ids", []),
        "receipt_ids": result["receipt_ids"],
    }


def _review(state: WorkflowState) -> dict[str, Any]:
    if (
        state.get("payload", {}).get("auto_approve") is True
        and not state.get("response", {}).get("review_required", False)
    ):
        return {"approved": True, "status": "approved"}
    return approval_interrupt(
        state,
        subject="correction_revision_activation",
        details={
            "correction_ids": state.get("correction_ids", []),
            "knowledge_ids": state.get("knowledge_ids", []),
            "candidate_revision": state.get("response", {}).get("candidate_revision"),
        },
    )


def _review_route(state: WorkflowState) -> str:
    return "publish" if state.get("approved") else "hold"


def _publish(
    state: WorkflowState, runtime: Runtime[RuntimeContext]
) -> dict[str, Any]:
    result = runtime.context.services.corrections.publish(
        request_id=state["request_id"],
        target_id=state["knowledge_ids"][0],
        revision_number=int(state["response"]["candidate_revision"]),
        security=security_from_state(state),
    )
    if not result.get("published", False):
        return {
            "response": result,
            "status": "held",
            "warnings": [str(result.get("reason", "correction_publish_failed"))],
        }
    return {
        "response": result,
        "receipt_ids": result["receipt_ids"],
        "status": "active",
    }


def _hold(state: WorkflowState) -> dict[str, Any]:
    return {
        "status": "held",
        "response": {
            "reason": "correction_not_activated",
            "warnings": state.get("warnings", []),
        },
    }


def build_correction_subgraph():
    builder = StateGraph(WorkflowState, context_schema=RuntimeContext)
    builder.add_node("prepare", _prepare)
    builder.add_node("confirm_target", _confirm_target)
    builder.add_node("recompute", _recompute)
    builder.add_node("review", _review)
    builder.add_node("publish", _publish)
    builder.add_node("hold", _hold)
    builder.add_edge(START, "prepare")
    builder.add_conditional_edges(
        "prepare",
        _prepare_route,
        {"confirm_target": "confirm_target", "recompute": "recompute"},
    )
    builder.add_edge("confirm_target", "prepare")
    builder.add_conditional_edges(
        "recompute", lambda state: state.get("next_action", "hold"),
        {"review": "review", "hold": "hold"},
    )
    builder.add_conditional_edges(
        "review", _review_route, {"publish": "publish", "hold": "hold"}
    )
    builder.add_edge("publish", END)
    builder.add_edge("hold", END)
    return builder.compile()
