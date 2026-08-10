from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from uka_langgraph.domain.models import SecurityScope
from uka_langgraph.infrastructure.settings import Settings
from uka_langgraph.orchestration.runtime import AgentRuntime


class UniversalKnowledgeAgent:
    """Stable local SDK facade over the persisted LangGraph runtime."""

    def __init__(
        self, settings: Settings | None = None, *, project_root: Path | str | None = None
    ):
        self.settings = settings or Settings.load(project_root)

    def doctor(self, *, connect: bool = False) -> dict[str, Any]:
        result = self.settings.safe_status()
        if connect:
            with AgentRuntime(self.settings) as runtime:
                result["provider_health"] = runtime.services.ingestion.provider_health()
        return _public(result)

    def ingest_text(
        self,
        text: str,
        *,
        tenant_id: str,
        security_scope_id: str,
        actor_id: str = "sdk-user",
        classification: str = "internal",
        auto_approve: bool = False,
        thread_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if not text.strip():
            raise ValueError("text cannot be empty")
        with AgentRuntime(self.settings) as runtime:
            reference = runtime.stage_text(text)
            result = runtime.invoke(
                intent="ingest",
                tenant_id=tenant_id,
                security_scope_id=security_scope_id,
                actor_id=actor_id,
                classification=classification,
                input_refs=[reference],
                payload={"auto_approve": auto_approve},
                thread_id=thread_id,
                request_id=request_id,
            )
        return _public(result)

    def ingest_file(
        self,
        path: Path,
        *,
        tenant_id: str,
        security_scope_id: str,
        actor_id: str = "sdk-user",
        classification: str = "internal",
        auto_approve: bool = False,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        with AgentRuntime(self.settings) as runtime:
            reference = runtime.stage_file(path)
            result = runtime.invoke(
                intent="ingest",
                tenant_id=tenant_id,
                security_scope_id=security_scope_id,
                actor_id=actor_id,
                classification=classification,
                input_refs=[reference],
                payload={"auto_approve": auto_approve},
                thread_id=thread_id,
            )
        return _public(result)

    def supplement_knowledge_gap(
        self,
        gap_id: str,
        evidence_text: str,
        *,
        tenant_id: str,
        security_scope_id: str,
        actor_id: str = "sdk-user",
        classification: str = "internal",
        source_note: str | None = None,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """Submit human evidence for one open gap without bypassing approval."""
        normalized_gap_id = gap_id.strip()
        if not normalized_gap_id:
            raise ValueError("gap_id cannot be empty")
        if not evidence_text.strip():
            raise ValueError("evidence_text cannot be empty")
        note = (source_note or "").strip()
        supplement = evidence_text.strip()
        if note:
            supplement = f"{supplement}\n\n补证来源说明：{note}"
        with AgentRuntime(self.settings) as runtime:
            security = SecurityScope(
                tenant_id, security_scope_id, classification
            )
            gap = runtime.services.repository.get_revision(
                security, "knowledge_gap", normalized_gap_id
            )
            if gap is None or gap.status == "resolved":
                raise LookupError(
                    f"open knowledge gap not found: {normalized_gap_id}"
                )
            reference = runtime.stage_text(supplement)
            result = runtime.invoke(
                intent="ingest",
                tenant_id=tenant_id,
                security_scope_id=security_scope_id,
                actor_id=actor_id,
                classification=classification,
                input_refs=[reference],
                payload={
                    "auto_approve": False,
                    "target_gap_ids": [normalized_gap_id],
                    "supplement_mode": "human_evidence",
                },
                thread_id=thread_id,
            )
        return _public(result)

    def retrieve(
        self,
        query: str,
        *,
        tenant_id: str,
        security_scope_id: str,
        query_scope: dict[str, Any] | None = None,
        as_of: str | None = None,
        limit: int = 5,
        actor_id: str = "sdk-user",
    ) -> dict[str, Any]:
        with AgentRuntime(self.settings) as runtime:
            result = runtime.invoke(
                intent="retrieve",
                tenant_id=tenant_id,
                security_scope_id=security_scope_id,
                actor_id=actor_id,
                payload={
                    "query": query,
                    "scope": query_scope or {},
                    "as_of": as_of,
                    "limit": limit,
                },
            )
        return _public(result)

    def list_knowledge(
        self,
        *,
        tenant_id: str,
        security_scope_id: str,
        limit: int = 100,
        domain: str | None = None,
    ) -> list[dict[str, Any]]:
        """List active knowledge with its resolved applicability scope."""
        with AgentRuntime(self.settings) as runtime:
            security = SecurityScope(tenant_id, security_scope_id)
            revisions = runtime.services.repository.list_active_knowledge(security, limit)
            entries: list[dict[str, Any]] = []
            for revision in revisions:
                scope_id = str(revision.payload.get("scope_id", ""))
                scope_revision = (
                    runtime.services.repository.get_revision(security, "scope", scope_id)
                    if scope_id
                    else None
                )
                scope_payload = scope_revision.payload if scope_revision else {}
                domains = [
                    str(item)
                    for item in scope_payload.get(
                        "domain_ids", scope_payload.get("domain", [])
                    )
                ]
                labels = [str(item) for item in scope_payload.get("domain_labels", [])]
                aliases = [str(item) for item in scope_payload.get("domain_aliases", [])]
                if domain and domain.casefold() not in {
                    item.casefold() for item in (*domains, *labels, *aliases)
                }:
                    continue
                source_evidence: list[dict[str, Any]] = []
                evidence_integrity = "verified"
                for evidence_id in revision.evidence_ids[:12]:
                    evidence = runtime.services.repository.get_evidence(
                        security, evidence_id
                    )
                    if evidence is None:
                        evidence_integrity = "missing"
                        continue
                    try:
                        content = runtime.services.objects.read_bytes(evidence.object_ref)
                    except (FileNotFoundError, OSError, ValueError):
                        evidence_integrity = "unavailable"
                        continue
                    if hashlib.sha256(content).hexdigest() != evidence.content_hash:
                        evidence_integrity = "hash_mismatch"
                        continue
                    source_evidence.append(
                        {
                            "evidence_id": evidence.evidence_id,
                            "parent_evidence_id": evidence.parent_evidence_id,
                            "content_hash": evidence.content_hash,
                            "locator": (
                                asdict(evidence.locator) if evidence.locator else None
                            ),
                            "excerpt": re.sub(
                                r"\s+",
                                " ",
                                content.decode("utf-8", errors="replace"),
                            ).strip()[:500],
                        }
                    )
                learning = revision.payload.get("learning", {})
                learning = learning if isinstance(learning, dict) else {}
                evolution_id = str(learning.get("evolution_candidate_id") or "")
                evolution = (
                    runtime.services.repository.get_revision(
                        security, "evolution", evolution_id
                    )
                    if evolution_id
                    else None
                )
                entries.append(
                    {
                        "knowledge_id": revision.object_id,
                        "revision": revision.revision,
                        "status": str(revision.status),
                        "classification": revision.security.classification,
                        "content": str(revision.payload.get("content", "")),
                        "title": str(revision.payload.get("title", "")),
                        "context": str(revision.payload.get("context", "")),
                        "problem": str(revision.payload.get("problem", "")),
                        "mechanism": str(revision.payload.get("mechanism", "")),
                        "action": str(revision.payload.get("action", "")),
                        "outcome": str(revision.payload.get("outcome", "")),
                        "rationale": str(revision.payload.get("rationale", "")),
                        "caveats": [
                            str(item) for item in revision.payload.get("caveats", [])
                        ],
                        "logical_relations": list(
                            revision.payload.get("logical_relations", [])
                        ),
                        "source_excerpts": [
                            str(item)
                            for item in revision.payload.get("source_excerpts", [])
                        ],
                        "experience_schema_version": int(
                            revision.payload.get("experience_schema_version", 1)
                        ),
                        "confidence": float(revision.payload.get("confidence", 0.0)),
                        "scope_id": scope_id,
                        "domain_ids": domains,
                        "domain_labels": labels,
                        "domain_aliases": aliases,
                        "subjects": [str(item) for item in scope_payload.get("subjects", [])],
                        "tasks": [str(item) for item in scope_payload.get("tasks", [])],
                        "preconditions": [
                            str(item) for item in scope_payload.get("preconditions", [])
                        ],
                        "exclusions": [
                            str(item) for item in scope_payload.get("exclusions", [])
                        ],
                        "geography": [
                            str(item) for item in scope_payload.get("geography", [])
                        ],
                        "risk": str(scope_payload.get("risk", "normal")),
                        "scope_confidence": float(scope_payload.get("confidence", 0.0)),
                        "review_required": bool(scope_payload.get("review_required", False)),
                        "provider_revision": revision.payload.get(
                            "provider_revision", scope_payload.get("provider_revision")
                        ),
                        "source_identifiers": [
                            str(item) for item in revision.payload.get("source_identifiers", [])
                        ],
                        "evidence_ids": list(revision.evidence_ids),
                        "source_evidence": source_evidence,
                        "evidence_integrity": evidence_integrity,
                        "learning": learning,
                        "evolution": (
                            {
                                "evolution_id": evolution.object_id,
                                "status": str(evolution.status),
                                "stage": evolution.payload.get("stage"),
                                "knowledge_delta": evolution.payload.get(
                                    "knowledge_delta"
                                ),
                                "automatic_activation": evolution.payload.get(
                                    "automatic_activation", False
                                ),
                                "required_gates": evolution.payload.get(
                                    "required_gates", []
                                ),
                            }
                            if evolution is not None
                            else None
                        ),
                        "created_at": revision.created_at,
                    }
                )
            return _public(entries)

    def list_knowledge_gaps(
        self,
        *,
        tenant_id: str,
        security_scope_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List unresolved, tenant-scoped knowledge gaps and research lineage."""
        with AgentRuntime(self.settings) as runtime:
            security = SecurityScope(tenant_id, security_scope_id)
            revisions = runtime.services.repository.list_open_gaps(security, limit)
            entries: list[dict[str, Any]] = []
            for revision in revisions:
                scope_ids = [
                    str(item) for item in revision.payload.get("scope_ids", [])
                ]
                scopes = [
                    runtime.services.repository.get_revision(
                        security, "scope", scope_id
                    )
                    for scope_id in scope_ids
                ]
                domain_ids = sorted(
                    {
                        str(domain)
                        for scope in scopes
                        if scope is not None
                        for domain in scope.payload.get(
                            "domain_ids", scope.payload.get("domain", [])
                        )
                    }
                )
                entries.append(
                    {
                        "gap_id": revision.object_id,
                        "revision": revision.revision,
                        "status": revision.status,
                        "classification": revision.security.classification,
                        "question": str(revision.payload.get("question", "")),
                        "reason_unresolved": str(
                            revision.payload.get("reason_unresolved", "")
                        ),
                        "possible_directions": [
                            str(item)
                            for item in revision.payload.get(
                                "possible_directions", []
                            )
                        ],
                        "missing_evidence": [
                            str(item)
                            for item in revision.payload.get("missing_evidence", [])
                        ],
                        "research_queries": [
                            str(item)
                            for item in revision.payload.get("research_queries", [])
                        ],
                        "linking_keys": [
                            str(item)
                            for item in revision.payload.get("linking_keys", [])
                        ],
                        "confidence": float(
                            revision.payload.get("confidence", 0.0)
                        ),
                        "research_status": str(
                            revision.payload.get("research_status", revision.status)
                        ),
                        "research_attempts": list(
                            revision.payload.get("research_attempts", [])
                        ),
                        "research_evidence_ids": list(
                            revision.payload.get("research_evidence_ids", [])
                        ),
                        "related_knowledge_ids": list(
                            revision.payload.get("related_knowledge_ids", [])
                        ),
                        "resolution_candidate_ids": list(
                            revision.payload.get("resolution_candidate_ids", [])
                        ),
                        "scope_ids": scope_ids,
                        "domain_ids": domain_ids,
                        "evidence_ids": list(revision.evidence_ids),
                        "created_at": revision.created_at,
                    }
                )
            return _public(entries)

    def correct_text(
        self,
        replacement: str,
        *,
        target_id: str,
        expected_revision: int,
        tenant_id: str,
        security_scope_id: str,
        actor_id: str = "sdk-user",
        auto_approve: bool = False,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        if not replacement.strip():
            raise ValueError("replacement cannot be empty")
        with AgentRuntime(self.settings) as runtime:
            reference = runtime.stage_text(replacement)
            result = runtime.invoke(
                intent="correct",
                tenant_id=tenant_id,
                security_scope_id=security_scope_id,
                actor_id=actor_id,
                payload={
                    "target_id": target_id,
                    "expected_revision": expected_revision,
                    "replacement_ref": reference,
                    "auto_approve": auto_approve,
                },
                thread_id=thread_id,
            )
        return _public(result)

    def build_skill(
        self,
        *,
        knowledge_id: str,
        tenant_id: str,
        security_scope_id: str,
        name: str | None = None,
        auto_approve: bool = False,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        with AgentRuntime(self.settings) as runtime:
            result = runtime.invoke(
                intent="build_skill",
                tenant_id=tenant_id,
                security_scope_id=security_scope_id,
                payload={
                    "knowledge_id": knowledge_id,
                    "name": name,
                    "auto_approve": auto_approve,
                },
                thread_id=thread_id,
            )
        return _public(result)

    def propose_evolution(
        self,
        *,
        target_type: str,
        baseline_revision: str,
        candidate_revision: str,
        metrics: dict[str, Any],
        tenant_id: str,
        security_scope_id: str,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        with AgentRuntime(self.settings) as runtime:
            result = runtime.invoke(
                intent="evolve",
                tenant_id=tenant_id,
                security_scope_id=security_scope_id,
                payload={
                    "target_type": target_type,
                    "baseline_revision": baseline_revision,
                    "candidate_revision": candidate_revision,
                    "metrics": metrics,
                },
                thread_id=thread_id,
            )
        return _public(result)

    def resume(
        self,
        thread_id: str,
        value: dict[str, Any],
        *,
        tenant_id: str,
        security_scope_id: str,
    ) -> dict[str, Any]:
        with AgentRuntime(self.settings) as runtime:
            return _public(
                runtime.resume(
                    thread_id=thread_id,
                    value=value,
                    tenant_id=tenant_id,
                    security_scope_id=security_scope_id,
                )
            )

    def status(
        self,
        thread_id: str,
        *,
        tenant_id: str,
        security_scope_id: str,
    ) -> dict[str, Any]:
        with AgentRuntime(self.settings) as runtime:
            return _public(
                runtime.status(
                    thread_id,
                    tenant_id=tenant_id,
                    security_scope_id=security_scope_id,
                )
            )

    def events(
        self,
        thread_id: str,
        limit: int = 100,
        *,
        tenant_id: str,
        security_scope_id: str,
    ) -> list[dict[str, Any]]:
        with AgentRuntime(self.settings) as runtime:
            return _public(
                runtime.events(
                    thread_id,
                    tenant_id=tenant_id,
                    security_scope_id=security_scope_id,
                    limit=limit,
                )
            )


def _public(value: Any) -> Any:
    if is_dataclass(value):
        return _public(asdict(value))
    if isinstance(value, dict):
        return {str(key): _public(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_public(item) for item in value]
    if hasattr(value, "value") and not isinstance(value, (str, bytes)):
        return _public(value.value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
