from __future__ import annotations

import json

from uka_langgraph.domain.models import SecurityScope
from uka_langgraph.orchestration.runtime import AgentRuntime


def test_ingestion_persists_evidence_before_active_knowledge_and_retrieves(settings) -> None:
    raw_text = "LangGraph checkpoints support durable execution."
    with AgentRuntime(settings) as runtime:
        object_ref = runtime.stage_text(raw_text)
        result = runtime.invoke(
            intent="ingest",
            tenant_id="tenant-a",
            security_scope_id="private",
            input_refs=[object_ref],
            payload={"auto_approve": True},
            request_id="ingest-1",
            thread_id="ingest-1",
        )
        assert result["status"] == "active"
        assert len(result["evidence_ids"]) == 1
        assert len(result["knowledge_ids"]) == 1
        assert len(result["receipt_ids"]) >= 3
        assert runtime.services.repository.count(
            "candidate", SecurityScope("tenant-a", "private")
        ) == 1
        checkpoint_safe = json.dumps(result, ensure_ascii=False)
        assert raw_text not in checkpoint_safe
        assert "LLM_API_KEY" not in checkpoint_safe

        retrieved = runtime.invoke(
            intent="retrieve",
            tenant_id="tenant-a",
            security_scope_id="private",
            payload={"query": "checkpoints"},
        )
        assert retrieved["response"]["answer"] == raw_text
        assert retrieved["knowledge_ids"] == result["knowledge_ids"]


def test_security_filter_precedes_retrieval(settings) -> None:
    with AgentRuntime(settings) as runtime:
        object_ref = runtime.stage_text("Tenant A secret maintenance interval is 30 days.")
        runtime.invoke(
            intent="ingest",
            tenant_id="tenant-a",
            security_scope_id="private",
            input_refs=[object_ref],
            payload={"auto_approve": True},
        )
        other_tenant = runtime.invoke(
            intent="retrieve",
            tenant_id="tenant-b",
            security_scope_id="private",
            payload={"query": "maintenance"},
        )
        other_scope = runtime.invoke(
            intent="retrieve",
            tenant_id="tenant-a",
            security_scope_id="public",
            payload={"query": "maintenance"},
        )
        assert other_tenant["status"] == "unknown"
        assert other_tenant["response"]["answer"] == "unknown"
        assert other_scope["status"] == "unknown"


def test_receipts_are_idempotent_and_tenant_scoped(settings) -> None:
    with AgentRuntime(settings) as runtime:
        object_ref = runtime.stage_text("Same payload.")
        first = runtime.services.ingestion.preserve(
            request_id="shared-request",
            input_refs=[object_ref],
            security=SecurityScope("tenant-a", "private"),
        )
        repeated = runtime.services.ingestion.preserve(
            request_id="shared-request",
            input_refs=[object_ref],
            security=SecurityScope("tenant-a", "private"),
        )
        other_tenant = runtime.services.ingestion.preserve(
            request_id="shared-request",
            input_refs=[object_ref],
            security=SecurityScope("tenant-b", "private"),
        )
        assert first == repeated
        assert first["evidence_ids"] != other_tenant["evidence_ids"]
        assert runtime.services.repository.count("candidate") == 0
