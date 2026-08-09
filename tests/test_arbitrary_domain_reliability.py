from __future__ import annotations

from uka_langgraph.application.services import utc_now
from uka_langgraph.domain.models import (
    ApplicabilityScope,
    ClaimCandidate,
    DomainRevision,
    RiskLevel,
    SecurityScope,
    UnderstandingResult,
)
from uka_langgraph.domain.taxonomy import (
    apply_risk_floor,
    canonical_domain_id,
    canonicalize_domains,
)
from uka_langgraph.infrastructure.parsers import ParserRegistry
from uka_langgraph.orchestration.runtime import AgentRuntime


class IdentifierStrippingProvider:
    revision = "identifier-stripping-experience-v2"

    def understand(
        self, text: str, evidence_id: str, prior_knowledge=()
    ) -> UnderstandingResult:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return UnderstandingResult(
            claims=tuple(
                ClaimCandidate(
                    candidate_id=f"cand-{evidence_id}-{index}",
                    content=line.split(" ", 1)[1],
                    confidence=0.95,
                    evidence_ids=(evidence_id,),
                    provider_revision=self.revision,
                    kind="experience",
                    title=f"Deposit policy {index}",
                    context="A source-specific deposit accounting policy applies.",
                    rationale="The conclusion follows from the cited policy line.",
                    source_excerpts=(line,),
                    schema_version=2,
                )
                for index, line in enumerate(lines)
            ),
            scopes=(
                ApplicabilityScope(
                    scope_id=f"scope-{evidence_id}",
                    domain=("Finance",),
                    domain_ids=("finance",),
                    domain_labels=("Finance",),
                    risk=RiskLevel.SENSITIVE,
                    confidence=0.95,
                ),
            ),
        )

    def check_connection(self) -> dict[str, object]:
        return {"status": "ok", "provider_revision": self.revision}


def test_controlled_taxonomy_normalizes_multilingual_and_specialized_labels() -> None:
    assert canonical_domain_id("Industrial Equipment Maintenance") == "mechanical_engineering"
    assert canonical_domain_id("财务与会计") == "finance"
    assert canonical_domain_id("Medical / Emergency Care") == "medicine"
    assert canonical_domain_id("Data Privacy Compliance") == "legal"
    assert canonical_domain_id("Site Reliability Engineering") == "software_engineering"
    assert canonicalize_domains(("Finance", "General")) == ("finance",)
    assert canonicalize_domains(("Finance", "Business")) == ("finance",)
    assert apply_risk_floor(RiskLevel.NORMAL, ("medicine",), "clinical rule") is RiskLevel.HIGH


def test_plain_text_splits_nonempty_lines_and_markdown_heading_is_context_only() -> None:
    registry = ParserRegistry()
    plain = registry.parse(
        "text/plain; charset=utf-8",
        b"MIX-MECH-1 bearing rule.\nMIX-FIN-2 revenue rule.",
    )
    assert [fragment.position for fragment in plain] == [
        {"start_line": 1, "end_line": 1},
        {"start_line": 2, "end_line": 2},
    ]
    markdown = registry.parse(
        "text/markdown",
        b"# Financial Accounting\n\nWarranty revenue is deferred.",
    )
    assert len(markdown) == 1
    assert markdown[0].text == "Warranty revenue is deferred."
    assert markdown[0].position["section"] == "Financial Accounting"


def test_multi_line_claims_bind_scope_by_shared_evidence(settings) -> None:
    with AgentRuntime(settings) as runtime:
        reference = runtime.stage_text(
            "MIX-MECH-73 bearing housings require lubrication.\n"
            "MIX-FIN-19 prepaid fees remain deferred."
        )
        result = runtime.invoke(
            intent="ingest",
            tenant_id="tenant-a",
            security_scope_id="private",
            input_refs=[reference],
            payload={"auto_approve": True},
        )
        assert result["status"] == "active"
        assert len(result["fragment_ids"]) == 2
        assert len(result["knowledge_ids"]) == 2
        security = SecurityScope("tenant-a", "private")
        for knowledge_id in result["knowledge_ids"]:
            knowledge = runtime.services.repository.get_revision(
                security, "knowledge", knowledge_id
            )
            assert knowledge is not None
            scope = runtime.services.repository.get_revision(
                security, "scope", str(knowledge.payload["scope_id"])
            )
            assert scope is not None
            assert set(knowledge.evidence_ids).intersection(scope.evidence_ids)


def test_review_required_is_fail_closed_and_domain_alias_matches(settings) -> None:
    security = SecurityScope("tenant-a", "private")
    with AgentRuntime(settings) as runtime:
        scope = DomainRevision(
            object_type="scope",
            object_id="scope-mechanical-review",
            revision=1,
            status="review_required",
            security=security,
            payload={
                "domain": ["mechanical_engineering"],
                "domain_ids": ["mechanical_engineering"],
                "domain_labels": ["Industrial Equipment Maintenance"],
                "risk": "normal",
                "confidence": 0.9,
                "unknowns": ["manufacturer"],
                "review_required": True,
                "valid_from": None,
                "valid_until": None,
            },
            evidence_ids=(),
            created_at=utc_now(),
        )
        runtime.services.repository.put_revision(scope, "op-scope-mechanical-review")
        knowledge = DomainRevision(
            object_type="knowledge",
            object_id="kn-mechanical-review",
            revision=1,
            status="active",
            security=security,
            payload={
                "content": "MX-180 calibration is required.",
                "confidence": 0.9,
                "scope_id": scope.object_id,
            },
            evidence_ids=(),
            created_at=utc_now(),
        )
        runtime.services.repository.put_revision(knowledge, "op-kn-mechanical-review")
        runtime.services.repository.activate_revision(knowledge)
        result = runtime.invoke(
            intent="retrieve",
            tenant_id="tenant-a",
            security_scope_id="private",
            payload={
                "query": "MX-180 calibration",
                "scope": {"domain": "Mechanical Engineering"},
            },
        )
        assert result["status"] == "review_required"
        assert result["response"]["answer"] == "unknown"
        assert result["knowledge_ids"] == [knowledge.object_id]


def test_source_identifier_is_indexed_when_provider_rewrites_claim(settings) -> None:
    with AgentRuntime(settings) as runtime:
        runtime.services.ingestion.understanding = IdentifierStrippingProvider()
        reference = runtime.stage_text(
            "JSON-FIN-22 refundable deposits remain liabilities until refund rights expire.\n"
            "JSON-FIN-99 other deposits follow a separate policy."
        )
        ingested = runtime.invoke(
            intent="ingest",
            tenant_id="tenant-a",
            security_scope_id="private",
            input_refs=[reference],
            payload={"auto_approve": True},
        )
        assert ingested["status"] == "active"
        result = runtime.invoke(
            intent="retrieve",
            tenant_id="tenant-a",
            security_scope_id="private",
            payload={"query": "JSON-FIN-22"},
        )
        assert result["status"] == "answered"
        assert len(ingested["knowledge_ids"]) == 2
        assert len(result["knowledge_ids"]) == 1
        knowledge = runtime.services.repository.get_revision(
            SecurityScope("tenant-a", "private"),
            "knowledge",
            result["knowledge_ids"][0],
        )
        assert knowledge is not None
        assert knowledge.payload["source_identifiers"] == ["JSON-FIN-22"]
