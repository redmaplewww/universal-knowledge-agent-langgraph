from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from uka_langgraph.application.services import stable_id, utc_now
from uka_langgraph.domain.models import (
    ApplicabilityScope,
    ClaimCandidate,
    DomainRevision,
    RiskLevel,
    SecurityScope,
    UnderstandingResult,
)
from uka_langgraph.infrastructure.parsers import FragmentLimitExceeded, ParserRegistry
from uka_langgraph.orchestration.runtime import AgentRuntime

SECURITY = SecurityScope("tenant-a", "private")


def _ingest(runtime: AgentRuntime, text: str, *, thread_id: str | None = None) -> dict:
    ref = runtime.stage_text(text)
    return runtime.invoke(
        intent="ingest",
        tenant_id=SECURITY.tenant_id,
        security_scope_id=SECURITY.security_scope_id,
        input_refs=[ref],
        payload={"auto_approve": True},
        thread_id=thread_id,
    )


def test_public_thread_ids_are_security_namespaced(settings) -> None:
    with AgentRuntime(settings) as runtime:
        first = _ingest(runtime, "Tenant A checkpoint content.", thread_id="shared")
        other_ref = runtime.stage_text("Tenant B independent checkpoint content.")
        second = runtime.invoke(
            intent="ingest",
            tenant_id="tenant-b",
            security_scope_id="private",
            input_refs=[other_ref],
            payload={"auto_approve": True},
            thread_id="shared",
        )
        assert first["tenant_id"] == "tenant-a"
        assert second["tenant_id"] == "tenant-b"
        a = runtime.status("shared", tenant_id="tenant-a", security_scope_id="private")
        b = runtime.status("shared", tenant_id="tenant-b", security_scope_id="private")
        assert a["values"]["knowledge_ids"] != b["values"]["knowledge_ids"]
        assert all(
            event["tenant_id"] == "tenant-a"
            for event in runtime.events(
                "shared", tenant_id="tenant-a", security_scope_id="private"
            )
        )
        with pytest.raises(ValueError, match="thread already exists"):
            _ingest(runtime, "Must not merge state.", thread_id="shared")


def test_legacy_event_schema_migrates_before_scoped_index_creation(settings) -> None:
    settings.initialize_directories()
    with sqlite3.connect(settings.domain_db) as connection:
        connection.executescript(
            """
            CREATE TABLE runtime_events (
                event_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX runtime_events_thread
                ON runtime_events (thread_id, created_at);
            """
        )
    with AgentRuntime(settings) as runtime:
        columns = {
            row[1]
            for row in sqlite3.connect(settings.domain_db).execute(
                "PRAGMA table_info(runtime_events)"
            )
        }
        assert "security_scope_id" in columns
        assert runtime.services.repository.count("knowledge") == 0


def test_stale_correction_cannot_replace_active_revision(settings) -> None:
    with AgentRuntime(settings) as runtime:
        knowledge_id = _ingest(runtime, "Original governed statement.")["knowledge_ids"][0]
        first_ref = runtime.stage_text("Current corrected governed statement.")
        current = runtime.invoke(
            intent="correct",
            tenant_id="tenant-a",
            security_scope_id="private",
            payload={
                "target_id": knowledge_id,
                "expected_revision": 1,
                "replacement_ref": first_ref,
                "auto_approve": True,
            },
        )
        assert current["status"] == "active"
        stale_ref = runtime.stage_text("Stale overwrite attempt.")
        stale = runtime.invoke(
            intent="correct",
            tenant_id="tenant-a",
            security_scope_id="private",
            payload={
                "target_id": knowledge_id,
                "expected_revision": 1,
                "replacement_ref": stale_ref,
                "auto_approve": True,
            },
        )
        assert stale["__interrupt__"][0].value["type"] == "target_resolution_required"
        active = runtime.services.repository.get_active_revision(
            SECURITY, "knowledge", knowledge_id
        )
        assert active is not None and active.revision == 2


def test_concurrent_correction_publish_loser_is_held(settings) -> None:
    with AgentRuntime(settings) as runtime:
        knowledge_id = _ingest(runtime, "Concurrent correction baseline.")[
            "knowledge_ids"
        ][0]
        for thread_id, replacement in (
            ("correction-one", "First concurrent correction."),
            ("correction-two", "Second concurrent correction."),
        ):
            ref = runtime.stage_text(replacement)
            result = runtime.invoke(
                intent="correct",
                tenant_id="tenant-a",
                security_scope_id="private",
                thread_id=thread_id,
                payload={
                    "target_id": knowledge_id,
                    "expected_revision": 1,
                    "replacement_ref": ref,
                    "auto_approve": False,
                },
            )
            assert "__interrupt__" in result
        winner = runtime.resume(
            thread_id="correction-one",
            value={"decision": "approve"},
            tenant_id="tenant-a",
            security_scope_id="private",
        )
        loser = runtime.resume(
            thread_id="correction-two",
            value={"decision": "approve"},
            tenant_id="tenant-a",
            security_scope_id="private",
        )
        assert winner["status"] == "active"
        assert loser["status"] == "held"
        assert loser["response"]["reason"] == "stale_active_revision"
        active = runtime.services.repository.get_active_revision(
            SECURITY, "knowledge", knowledge_id
        )
        assert active is not None and active.revision == 2


class _MedicalCorrectionProvider:
    revision = "test-medical-v1"

    def understand(self, text: str, evidence_id: str) -> UnderstandingResult:
        return UnderstandingResult(
            claims=(
                ClaimCandidate(
                    candidate_id=stable_id("cand", evidence_id, text),
                    content=text,
                    confidence=0.95,
                    evidence_ids=(evidence_id,),
                    provider_revision=self.revision,
                ),
            ),
            scopes=(
                ApplicabilityScope(
                    scope_id=stable_id("scope", evidence_id, "medical"),
                    domain=("medical",),
                    domain_ids=("medical",),
                    domain_labels=("medical",),
                    tasks=("treatment",),
                    risk=RiskLevel.HIGH,
                    confidence=0.95,
                ),
            ),
        )

    def check_connection(self) -> dict[str, object]:
        return {"status": "ok", "provider_revision": self.revision}


def test_correction_is_reclassified_and_high_risk_cannot_autoapprove(settings) -> None:
    with AgentRuntime(settings) as runtime:
        knowledge_id = _ingest(runtime, "Routine non-medical note.")["knowledge_ids"][0]
        runtime.services.ingestion.understanding = _MedicalCorrectionProvider()
        ref = runtime.stage_text("Administer emergency medicine under clinician direction.")
        result = runtime.invoke(
            intent="correct",
            tenant_id="tenant-a",
            security_scope_id="private",
            payload={
                "target_id": knowledge_id,
                "expected_revision": 1,
                "replacement_ref": ref,
                "auto_approve": True,
            },
        )
        assert result["__interrupt__"][0].value["subject"] == (
            "correction_revision_activation"
        )
        candidate = runtime.services.repository.get_revision(
            SECURITY, "knowledge", knowledge_id, 2
        )
        assert candidate is not None
        scope = runtime.services.repository.get_revision(
            SECURITY, "scope", str(candidate.payload["scope_id"])
        )
        assert scope is not None
        assert scope.payload["domain_ids"] == ["medical"]
        assert scope.payload["risk"] == "high"
        active = runtime.services.repository.get_active_revision(
            SECURITY, "knowledge", knowledge_id
        )
        assert active is not None and active.revision == 1


def test_retrieval_fails_closed_when_evidence_row_is_missing(settings) -> None:
    with AgentRuntime(settings) as runtime:
        ingested = _ingest(runtime, "Integrity marker sapphire.")
        knowledge = runtime.services.repository.get_active_revision(
            SECURITY, "knowledge", ingested["knowledge_ids"][0]
        )
        assert knowledge is not None and knowledge.evidence_ids
        with sqlite3.connect(settings.domain_db) as connection:
            connection.execute(
                "DELETE FROM evidence WHERE tenant_id=? AND security_scope_id=? "
                "AND evidence_id=?",
                ("tenant-a", "private", knowledge.evidence_ids[0]),
            )
        result = runtime.invoke(
            intent="retrieve",
            tenant_id="tenant-a",
            security_scope_id="private",
            payload={"query": "sapphire"},
        )
        assert result["status"] == "unknown"
        assert result["response"]["evidence_pack"]["unknowns"] == (
            "evidence_integrity_failure",
        )


def _seed_scoped_knowledge(
    runtime: AgentRuntime,
    object_id: str,
    domain: str,
    content: str,
    *,
    source_identifiers: list[str] | None = None,
) -> None:
    scope_id = f"scope-{object_id}"
    scope = DomainRevision(
        object_type="scope",
        object_id=scope_id,
        revision=1,
        status="evaluated",
        security=SECURITY,
        payload={
            "domain": [domain],
            "domain_ids": [domain],
            "risk": "normal",
            "confidence": 0.9,
            "valid_from": datetime(2020, 1, 1, tzinfo=UTC).isoformat(),
            "valid_until": None,
        },
        evidence_ids=(),
        created_at=utc_now(),
    )
    runtime.services.repository.put_revision(scope, f"op-{scope_id}")
    knowledge = DomainRevision(
        object_type="knowledge",
        object_id=object_id,
        revision=1,
        status="active",
        security=SECURITY,
        payload={
            "content": content,
            "confidence": 0.9,
            "scope_id": scope_id,
            "source_identifiers": source_identifiers or [],
        },
        evidence_ids=(),
        created_at=utc_now(),
    )
    runtime.services.repository.put_revision(knowledge, f"op-{object_id}")
    runtime.services.repository.activate_revision(knowledge)


def test_scope_filter_is_applied_before_final_limit(settings) -> None:
    with AgentRuntime(settings) as runtime:
        _seed_scoped_knowledge(runtime, "a-mechanical", "mechanical", "sharedterm rule")
        _seed_scoped_knowledge(runtime, "z-finance", "finance", "sharedterm rule")
        result = runtime.invoke(
            intent="retrieve",
            tenant_id="tenant-a",
            security_scope_id="private",
            payload={
                "query": "sharedterm",
                "limit": 1,
                "scope": {"domain": "finance"},
            },
        )
        assert result["status"] == "answered"
        assert result["knowledge_ids"] == ["z-finance"]


def test_shared_source_identifier_conflict_requires_review(settings) -> None:
    with AgentRuntime(settings) as runtime:
        _seed_scoped_knowledge(
            runtime,
            "kn-one",
            "general",
            "SPEC-42 retention is thirty days",
            source_identifiers=["SPEC-42"],
        )
        _seed_scoped_knowledge(
            runtime,
            "kn-two",
            "general",
            "SPEC-42 retention is ninety days",
            source_identifiers=["SPEC-42"],
        )
        result = runtime.invoke(
            intent="retrieve",
            tenant_id="tenant-a",
            security_scope_id="private",
            payload={"query": "SPEC-42", "limit": 1},
        )
        assert result["status"] == "review_required"
        assert result["response"]["evidence_pack"]["conflicts"][0]["type"] == (
            "source_identifier_conflict"
        )


def test_compatible_claims_from_same_source_are_not_conflicts(settings) -> None:
    with AgentRuntime(settings) as runtime:
        _seed_scoped_knowledge(
            runtime,
            "kn-edu-one",
            "education",
            "EDU-S14 formative quizzes are used each week",
            source_identifiers=["EDU-S14"],
        )
        _seed_scoped_knowledge(
            runtime,
            "kn-edu-two",
            "education",
            "EDU-S14 formative quizzes adjust instruction before assessment",
            source_identifiers=["EDU-S14"],
        )
        result = runtime.invoke(
            intent="retrieve",
            tenant_id="tenant-a",
            security_scope_id="private",
            payload={"query": "EDU-S14 formative quizzes"},
        )
        assert result["status"] == "answered"
        assert result["response"]["evidence_pack"]["conflicts"] == ()


def test_repeated_identical_ingestion_is_content_idempotent(settings) -> None:
    with AgentRuntime(settings) as runtime:
        first = _ingest(runtime, "IDEM-42 stable repeated knowledge.")
        provider = runtime.services.ingestion.understanding

        def must_not_run(*args, **kwargs):
            raise AssertionError("content-addressed understanding cache was bypassed")

        provider.understand = must_not_run  # type: ignore[method-assign]
        second = _ingest(runtime, "IDEM-42 stable repeated knowledge.")
        assert first["status"] == second["status"] == "active"
        assert first["knowledge_ids"] == second["knowledge_ids"]
        assert runtime.services.repository.count("knowledge", SECURITY) == 1


def test_parser_overlimit_is_explicit() -> None:
    content = "\n".join(f"line {index}" for index in range(257)).encode()
    with pytest.raises(FragmentLimitExceeded):
        ParserRegistry().parse("text/plain; charset=utf-8", content)


def test_evolution_rejects_self_reported_metrics_without_evaluation_evidence(settings) -> None:
    with AgentRuntime(settings) as runtime:
        result = runtime.invoke(
            intent="evolve",
            tenant_id="tenant-a",
            security_scope_id="private",
            payload={
                "target_type": "prompt",
                "baseline_revision": "v1",
                "candidate_revision": "v2",
                "metrics": {"passed": True, "safety_regression": False},
            },
        )
        assert result["status"] == "rejected"
        assert "offline_evaluation_missing" in result["warnings"]
