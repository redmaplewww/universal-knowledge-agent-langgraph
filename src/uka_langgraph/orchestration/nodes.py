from __future__ import annotations

import hashlib
from typing import Any

from langgraph.runtime import Runtime
from langgraph.types import interrupt

from uka_langgraph.domain.models import SecurityScope
from uka_langgraph.orchestration.context import RuntimeContext
from uka_langgraph.orchestration.state import WorkflowState


def security_from_state(state: WorkflowState) -> SecurityScope:
    return SecurityScope(
        tenant_id=state["tenant_id"],
        security_scope_id=state["security_scope_id"],
        classification=state.get("classification", "internal"),
    )


def intake_node(
    state: WorkflowState, runtime: Runtime[RuntimeContext]
) -> dict[str, Any]:
    errors: list[str] = []
    if not state.get("request_id") or not state.get("thread_id"):
        errors.append("request_and_thread_id_required")
    if not state.get("tenant_id") or not state.get("security_scope_id"):
        errors.append("security_context_required")
    if state.get("graph_version") != runtime.context.graph_version:
        errors.append("graph_version_mismatch")
    if state.get("intent") not in {
        "ingest",
        "correct",
        "build_skill",
        "evolve",
        "retrieve",
    }:
        errors.append("unsupported_intent")
    return {
        "status": "rejected" if errors else "accepted",
        "next_action": "finalize" if errors else str(state.get("intent")),
        "errors": errors,
    }


def finalize_node(state: WorkflowState) -> dict[str, Any]:
    status = state.get("status", "completed")
    if state.get("errors"):
        status = "failed"
    return {"status": status, "next_action": "end"}


def approval_interrupt(
    state: WorkflowState, *, subject: str, details: dict[str, Any]
) -> dict[str, Any]:
    decision = interrupt(
        {
            "type": "approval_required",
            "subject": subject,
            "request_id": state["request_id"],
            "thread_id": state["thread_id"],
            "details": details,
            "allowed_decisions": ["approve", "reject"],
        }
    )
    if not isinstance(decision, dict) or decision.get("decision") not in {
        "approve",
        "reject",
    }:
        return {
            "approved": False,
            "status": "review_required",
            "errors": ["invalid_approval_payload"],
        }
    approved = decision["decision"] == "approve"
    return {
        "approved": approved,
        "status": "approved" if approved else "rejected",
    }


def evaluation_id(state: WorkflowState, label: str) -> str:
    material = f"{state['request_id']}:{label}".encode()
    return f"eval_{hashlib.sha256(material).hexdigest()[:24]}"

