from __future__ import annotations

from datetime import UTC, datetime

import pytest

from uka_langgraph.application.services import utc_now
from uka_langgraph.domain.models import DomainRevision, SecurityScope
from uka_langgraph.infrastructure.parsers import ParserRegistry
from uka_langgraph.orchestration.runtime import AgentRuntime


@pytest.mark.parametrize(
    ("content", "media_type", "locator_type"),
    [
        (b"first paragraph\n\nsecond paragraph", "text/plain; charset=utf-8", "lines"),
        (b"# Heading\n\nBody", "text/markdown", "markdown_lines"),
        (b'{"device":{"torque":42}}', "application/json", "json_pointer"),
        (b"name,value\nalpha,1\nbeta,2", "text/csv", "csv_row"),
        (b"<!doctype html><html><body><p>Visible</p><script>bad()</script></body></html>", "text/html", "html_text"),
    ],
)
def test_parser_registry_detects_supported_formats(content, media_type, locator_type) -> None:
    registry = ParserRegistry()
    assert registry.detect(content) == media_type
    fragments = registry.parse(media_type, content)
    assert fragments
    assert all(fragment.locator_type == locator_type for fragment in fragments)
    assert all("bad()" not in fragment.text for fragment in fragments)


def test_json_ingestion_preserves_parent_and_json_pointer(settings) -> None:
    with AgentRuntime(settings) as runtime:
        reference = runtime.stage_text('{"pump":{"interval_days":30}}')
        result = runtime.invoke(
            intent="ingest",
            tenant_id="tenant-a",
            security_scope_id="private",
            input_refs=[reference],
            payload={"auto_approve": True},
        )
        assert result["status"] == "active"
        assert result["fragment_ids"]
        fragment = runtime.services.repository.get_evidence(
            SecurityScope("tenant-a", "private"), result["fragment_ids"][0]
        )
        assert fragment is not None
        assert fragment.parent_evidence_id == result["evidence_ids"][0]
        assert fragment.locator is not None
        assert fragment.locator.locator_type == "json_pointer"


def test_unknown_binary_is_held_fail_closed(settings) -> None:
    with AgentRuntime(settings) as runtime:
        reference = runtime.services.objects.put_bytes(b"\x00\x01\x02binary")
        result = runtime.invoke(
            intent="ingest",
            tenant_id="tenant-a",
            security_scope_id="private",
            input_refs=[reference],
            payload={"auto_approve": True},
        )
        assert result["status"] == "held"
        assert not result["knowledge_ids"]


def test_evidence_pack_scope_and_locator(settings) -> None:
    with AgentRuntime(settings) as runtime:
        reference = runtime.stage_text("Calibration interval is thirty days.")
        ingested = runtime.invoke(
            intent="ingest",
            tenant_id="tenant-a",
            security_scope_id="private",
            input_refs=[reference],
            payload={"auto_approve": True},
        )
        matched = runtime.invoke(
            intent="retrieve",
            tenant_id="tenant-a",
            security_scope_id="private",
            payload={"query": "Calibration", "scope": {"domain": "general"}},
        )
        assert matched["status"] == "answered"
        pack = matched["response"]["evidence_pack"]
        assert pack["items"][0]["evidence"][0]["locator"] is not None
        assert pack["items"][0]["evidence"][0]["parent_evidence_id"]
        mismatched = runtime.invoke(
            intent="retrieve",
            tenant_id="tenant-a",
            security_scope_id="private",
            payload={"query": "Calibration", "scope": {"domain": "medical"}},
        )
        assert mismatched["status"] == "unknown"
        assert mismatched["response"]["answer"] == "unknown"
        assert ingested["knowledge_ids"]


def test_high_risk_or_conflicted_knowledge_requires_review(settings) -> None:
    security = SecurityScope("tenant-a", "private")
    with AgentRuntime(settings) as runtime:
        scope = DomainRevision(
            object_type="scope",
            object_id="scope-high",
            revision=1,
            status="evaluated",
            security=security,
            payload={
                "domain": ["medical"],
                "tasks": ["treatment"],
                "risk": "high",
                "confidence": 0.9,
                "valid_from": datetime.now(UTC).replace(year=2020).isoformat(),
                "valid_until": None,
            },
            evidence_ids=(),
            created_at=utc_now(),
        )
        runtime.services.repository.put_revision(scope, "op-test-high-scope")
        knowledge = DomainRevision(
            object_type="knowledge",
            object_id="kn-high",
            revision=1,
            status="active",
            security=security,
            payload={
                "content": "Medication dosage requires clinician review.",
                "confidence": 0.9,
                "scope_id": "scope-high",
                "conflict_status": "open",
            },
            evidence_ids=(),
            created_at=utc_now(),
        )
        runtime.services.repository.put_revision(knowledge, "op-test-high-knowledge")
        runtime.services.repository.activate_revision(knowledge)
        result = runtime.invoke(
            intent="retrieve",
            tenant_id="tenant-a",
            security_scope_id="private",
            payload={
                "query": "Medication dosage",
                "scope": {"domain": "medical", "task": "treatment"},
            },
        )
        assert result["status"] == "review_required"
        assert result["response"]["answer"] == "unknown"
        assert result["response"]["evidence_pack"]["conflicts"]

