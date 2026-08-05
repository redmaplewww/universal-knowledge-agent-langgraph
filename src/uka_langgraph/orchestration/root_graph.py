from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from uka_langgraph.orchestration.context import RuntimeContext
from uka_langgraph.orchestration.nodes import finalize_node, intake_node
from uka_langgraph.orchestration.state import WorkflowState
from uka_langgraph.orchestration.subgraphs import (
    build_correction_subgraph,
    build_evolution_subgraph,
    build_ingestion_subgraph,
    build_retrieval_subgraph,
    build_skill_subgraph,
)


def build_root_graph(checkpointer=None):
    builder = StateGraph(WorkflowState, context_schema=RuntimeContext)
    builder.add_node("intake", intake_node)
    builder.add_node("ingestion", build_ingestion_subgraph())
    builder.add_node("correction", build_correction_subgraph())
    builder.add_node("skill", build_skill_subgraph())
    builder.add_node("evolution", build_evolution_subgraph())
    builder.add_node("retrieval", build_retrieval_subgraph())
    builder.add_node("finalize", finalize_node)
    builder.add_edge(START, "intake")
    builder.add_conditional_edges(
        "intake",
        lambda state: state.get("next_action", "finalize"),
        {
            "ingest": "ingestion",
            "correct": "correction",
            "build_skill": "skill",
            "evolve": "evolution",
            "retrieve": "retrieval",
            "finalize": "finalize",
        },
    )
    for node in ("ingestion", "correction", "skill", "evolution", "retrieval"):
        builder.add_edge(node, "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)

