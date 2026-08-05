from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict


def merge_unique(left: list[str] | None, right: list[str] | None) -> list[str]:
    return list(dict.fromkeys([*(left or []), *(right or [])]))


class WorkflowState(TypedDict, total=False):
    request_id: str
    thread_id: str
    tenant_id: str
    actor_id: str
    intent: Literal["ingest", "correct", "build_skill", "evolve", "retrieve"]
    security_scope_id: str
    classification: str
    graph_version: str
    input_refs: Annotated[list[str], merge_unique]
    evidence_ids: Annotated[list[str], merge_unique]
    fragment_ids: Annotated[list[str], merge_unique]
    candidate_ids: Annotated[list[str], merge_unique]
    scope_ids: Annotated[list[str], merge_unique]
    knowledge_ids: Annotated[list[str], merge_unique]
    skill_ids: Annotated[list[str], merge_unique]
    correction_ids: Annotated[list[str], merge_unique]
    impact_ids: Annotated[list[str], merge_unique]
    evaluation_ids: Annotated[list[str], merge_unique]
    receipt_ids: Annotated[list[str], merge_unique]
    warnings: Annotated[list[str], merge_unique]
    errors: Annotated[list[str], merge_unique]
    payload: dict[str, Any]
    status: str
    next_action: str
    approved: bool
    response: dict[str, Any]


SAFE_STATE_FIELDS = frozenset(WorkflowState.__annotations__)
