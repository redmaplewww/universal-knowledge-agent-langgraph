from __future__ import annotations

import ast
from pathlib import Path

from uka_langgraph.orchestration.root_graph import build_root_graph
from uka_langgraph.orchestration.state import WorkflowState


def test_root_graph_has_five_independent_subgraphs() -> None:
    graph = build_root_graph()
    nodes = set(graph.get_graph().nodes)
    assert {"ingestion", "correction", "skill", "evolution", "retrieval"} <= nodes
    assert {"intake", "finalize", "__start__", "__end__"} <= nodes


def test_state_contains_referenced_data_not_raw_input_fields() -> None:
    fields = set(WorkflowState.__annotations__)
    assert "input_refs" in fields
    assert "evidence_ids" in fields
    assert "raw_input" not in fields
    assert "api_key" not in fields
    assert "model_response" not in fields


def test_domain_layer_has_no_framework_or_old_project_imports() -> None:
    domain_root = Path(__file__).parents[1] / "src" / "uka_langgraph" / "domain"
    forbidden = ("langgraph", "openai", "sqlite3", "uka", "aawo")
    for path in domain_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [item.name.lower() for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").lower()]
            else:
                continue
            assert not any(
                name == blocked or name.startswith(f"{blocked}.")
                for name in names
                for blocked in forbidden
            ), (path, names)


def test_project_metadata_does_not_reference_aawo_or_old_source_path() -> None:
    root = Path(__file__).parents[1]
    metadata = (root / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert "aawo" not in metadata
    assert "reference/" not in metadata
    assert "pythonpath" not in metadata

