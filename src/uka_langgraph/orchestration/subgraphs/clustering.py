from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from uka_langgraph.application.clustering import SamplingRatios
from uka_langgraph.orchestration.context import RuntimeContext
from uka_langgraph.orchestration.nodes import security_from_state
from uka_langgraph.orchestration.state import WorkflowState


def _cluster(
    state: WorkflowState, runtime: Runtime[RuntimeContext]
) -> dict[str, Any]:
    payload = state.get("payload", {})
    ratios = SamplingRatios(
        coverage=float(payload.get("coverage_ratio", 0.4)),
        uncertainty=float(payload.get("uncertainty_ratio", 0.3)),
        bridge=float(payload.get("bridge_ratio", 0.2)),
        replay=float(payload.get("replay_ratio", 0.1)),
    )
    try:
        result = runtime.context.services.clustering.run(
            security=security_from_state(state),
            batch_size=int(payload.get("batch_size", 24)),
            ratios=ratios,
        )
    except Exception as exc:  # Provider failures must settle without leaking details.
        error_type = type(exc).__name__
        return {
            "status": "clustering_failed",
            "errors": [f"clustering_provider_error:{error_type}"],
            "response": {
                "status": "clustering_failed",
                "run_id": None,
                "error_type": error_type,
            },
        }
    run_id = result.get("run_id")
    return {
        "status": str(result.get("status", "unknown")),
        "cluster_run_ids": [str(run_id)] if run_id else [],
        "response": result,
    }


def build_clustering_subgraph():
    builder = StateGraph(WorkflowState, context_schema=RuntimeContext)
    builder.add_node("cluster", _cluster)
    builder.add_edge(START, "cluster")
    builder.add_edge("cluster", END)
    return builder.compile()
