from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send

from uka_langgraph.orchestration.context import RuntimeContext
from uka_langgraph.orchestration.nodes import approval_interrupt, security_from_state
from uka_langgraph.orchestration.state import WorkflowState


def _preflight(
    state: WorkflowState, runtime: Runtime[RuntimeContext]
) -> dict[str, Any]:
    refs = state.get("input_refs", [])
    errors: list[str] = []
    if not refs:
        errors.append("input_ref_required")
    if len(refs) > runtime.context.max_fanout:
        errors.append("fanout_limit_exceeded")
    for object_ref in refs:
        if not object_ref.startswith("sha256:"):
            errors.append("untrusted_input_reference")
            break
    return {
        "status": "preflight_passed" if not errors else "rejected",
        "errors": errors,
    }


def _preflight_route(state: WorkflowState) -> str:
    return "hold" if state.get("errors") else "preserve"


def _preserve(
    state: WorkflowState, runtime: Runtime[RuntimeContext]
) -> dict[str, Any]:
    result = runtime.context.services.ingestion.preserve(
        request_id=state["request_id"],
        input_refs=state["input_refs"],
        security=security_from_state(state),
    )
    return {
        "evidence_ids": result["evidence_ids"],
        "receipt_ids": result["receipt_ids"],
        "status": "evidence_preserved",
    }


def _fanout_parsing(state: WorkflowState) -> list[Send]:
    return [
        Send(
            "parse_one",
            {
                "request_id": state["request_id"],
                "thread_id": state["thread_id"],
                "tenant_id": state["tenant_id"],
                "actor_id": state["actor_id"],
                "intent": state["intent"],
                "security_scope_id": state["security_scope_id"],
                "classification": state.get("classification", "internal"),
                "graph_version": state["graph_version"],
                "evidence_ids": [evidence_id],
                "payload": state.get("payload", {}),
            },
        )
        for evidence_id in state.get("evidence_ids", [])
    ]


def _parse_one(
    state: WorkflowState, runtime: Runtime[RuntimeContext]
) -> dict[str, Any]:
    result = runtime.context.services.ingestion.parse(
        request_id=state["request_id"],
        evidence_ids=state["evidence_ids"],
        security=security_from_state(state),
    )
    return {
        "fragment_ids": result["fragment_ids"],
        "warnings": result["warnings"],
        "receipt_ids": result["receipt_ids"],
    }


def _fanout_understanding(state: WorkflowState) -> list[Send] | str:
    fragment_ids = state.get("fragment_ids", [])
    if not fragment_ids:
        return "hold"
    return [
        Send(
            "understand_one",
            {
                "request_id": state["request_id"],
                "thread_id": state["thread_id"],
                "tenant_id": state["tenant_id"],
                "actor_id": state["actor_id"],
                "intent": state["intent"],
                "security_scope_id": state["security_scope_id"],
                "classification": state.get("classification", "internal"),
                "graph_version": state["graph_version"],
                "evidence_ids": [fragment_id],
                "fragment_ids": [fragment_id],
                "payload": state.get("payload", {}),
            },
        )
        for fragment_id in fragment_ids
    ]


def _understand_one(
    state: WorkflowState, runtime: Runtime[RuntimeContext]
) -> dict[str, Any]:
    try:
        result = runtime.context.services.ingestion.understand(
            request_id=state["request_id"],
            evidence_ids=state["evidence_ids"],
            security=security_from_state(state),
        )
    except Exception as exc:  # Provider exceptions are converted to a redacted graph error.
        error_code = getattr(exc, "code", type(exc).__name__)
        return {
            "errors": [f"provider_error:{error_code}"],
        }
    return {
        "candidate_ids": result["candidate_ids"],
        "scope_ids": result["scope_ids"],
        "warnings": result["warnings"],
        "receipt_ids": result["receipt_ids"],
    }


def _evaluate(
    state: WorkflowState, runtime: Runtime[RuntimeContext]
) -> dict[str, Any]:
    if state.get("errors"):
        return {
            "next_action": "hold",
            "approved": False,
            "status": "review_required",
            "warnings": ["provider_or_contract_failure"],
        }
    result = runtime.context.services.ingestion.evaluate(
        security=security_from_state(state),
        candidate_ids=state.get("candidate_ids", []),
        scope_ids=state.get("scope_ids", []),
    )
    payload = state.get("payload", {})
    can_auto_approve = (
        payload.get("auto_approve") is True
        and result["reason"] == "independent_approval_required"
    )
    return {
        "next_action": "compile" if can_auto_approve else result["decision"],
        "approved": can_auto_approve,
        "status": "evaluated",
        "evaluation_ids": [f"{state['request_id']}:ingestion"],
        "warnings": [] if can_auto_approve else [str(result["reason"])],
    }


def _decision_route(state: WorkflowState) -> str:
    action = state.get("next_action", "hold")
    return action if action in {"review", "compile", "hold"} else "hold"


def _review(state: WorkflowState) -> dict[str, Any]:
    return approval_interrupt(
        state,
        subject="knowledge_activation",
        details={
            "candidate_ids": state.get("candidate_ids", []),
            "scope_ids": state.get("scope_ids", []),
            "evidence_ids": state.get("evidence_ids", []),
            "warnings": state.get("warnings", []),
        },
    )


def _review_route(state: WorkflowState) -> str:
    return "compile" if state.get("approved") else "hold"


def _compile(
    state: WorkflowState, runtime: Runtime[RuntimeContext]
) -> dict[str, Any]:
    result = runtime.context.services.ingestion.compile_knowledge(
        request_id=state["request_id"],
        security=security_from_state(state),
        candidate_ids=state.get("candidate_ids", []),
        scope_ids=state.get("scope_ids", []),
        approved=bool(state.get("approved")),
    )
    return {
        "knowledge_ids": result["knowledge_ids"],
        "receipt_ids": result["receipt_ids"],
        "status": result["status"],
        "response": result,
    }


def _hold(state: WorkflowState) -> dict[str, Any]:
    return {
        "status": "held" if not state.get("errors") else "rejected",
        "response": {
            "reason": "fail_closed",
            "errors": state.get("errors", []),
            "warnings": state.get("warnings", []),
        },
    }


def build_ingestion_subgraph():
    builder = StateGraph(WorkflowState, context_schema=RuntimeContext)
    builder.add_node("preflight", _preflight)
    builder.add_node("preserve", _preserve)
    builder.add_node("parse_one", _parse_one)
    builder.add_node("understand_one", _understand_one)
    builder.add_node("evaluate", _evaluate)
    builder.add_node("review", _review)
    builder.add_node("compile", _compile)
    builder.add_node("hold", _hold)
    builder.add_edge(START, "preflight")
    builder.add_conditional_edges(
        "preflight", _preflight_route, {"preserve": "preserve", "hold": "hold"}
    )
    builder.add_conditional_edges("preserve", _fanout_parsing, ["parse_one"])
    builder.add_conditional_edges(
        "parse_one", _fanout_understanding, ["understand_one", "hold"]
    )
    builder.add_edge("understand_one", "evaluate")
    builder.add_conditional_edges(
        "evaluate",
        _decision_route,
        {"review": "review", "compile": "compile", "hold": "hold"},
    )
    builder.add_conditional_edges(
        "review", _review_route, {"compile": "compile", "hold": "hold"}
    )
    builder.add_edge("compile", END)
    builder.add_edge("hold", END)
    return builder.compile()
