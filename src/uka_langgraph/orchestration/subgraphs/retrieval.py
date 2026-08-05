from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from uka_langgraph.orchestration.context import RuntimeContext
from uka_langgraph.orchestration.nodes import security_from_state
from uka_langgraph.orchestration.state import WorkflowState


def _retrieve(
    state: WorkflowState, runtime: Runtime[RuntimeContext]
) -> dict[str, Any]:
    payload = state.get("payload", {})
    result = runtime.context.services.retrieval.retrieve(
        security=security_from_state(state),
        query=str(payload.get("query", "")),
        limit=int(payload.get("limit", 5)),
        query_scope=payload.get("scope"),
        as_of=payload.get("as_of"),
    )
    return {
        "response": result,
        "knowledge_ids": result["knowledge_ids"],
        "evidence_ids": result["evidence_ids"],
        "status": result["status"],
    }


def build_retrieval_subgraph():
    builder = StateGraph(WorkflowState, context_schema=RuntimeContext)
    builder.add_node("retrieve", _retrieve)
    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", END)
    return builder.compile()
