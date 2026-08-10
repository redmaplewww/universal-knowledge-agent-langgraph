from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Any

from uka_langgraph.application.ports import (
    ObjectStorePort,
    ParserRegistryPort,
    RepositoryPort,
    UnderstandingPort,
    WebSearchPort,
)
from uka_langgraph.domain.models import (
    DomainRevision,
    Evidence,
    EvidenceLocator,
    EvidencePack,
    EvidencePackItem,
    KnowledgeGapCandidate,
    KnowledgeStatus,
    OperationReceipt,
    SecurityScope,
    UnderstandingResult,
)
from uka_langgraph.domain.taxonomy import (
    canonicalize_domains,
    domain_aliases,
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def operation_id(request_id: str, step: str, *parts: str) -> str:
    return stable_id("op", request_id, step, *parts)


def scoped_operation_id(
    security: SecurityScope, request_id: str, step: str, *parts: str
) -> str:
    return operation_id(
        f"{security.tenant_id}:{security.security_scope_id}:{request_id}", step, *parts
    )


@dataclass(slots=True)
class IngestionService:
    repository: RepositoryPort
    objects: ObjectStorePort
    understanding: UnderstandingPort
    parsers: ParserRegistryPort
    research: WebSearchPort | None = None
    research_count: int = 5
    research_max_queries: int = 4

    def provider_health(self) -> dict[str, object]:
        return self.understanding.check_connection()

    def preserve(
        self,
        *,
        request_id: str,
        input_refs: list[str],
        security: SecurityScope,
        source_type: str = "staged",
    ) -> dict[str, Any]:
        op_id = scoped_operation_id(security, request_id, "preserve", *sorted(input_refs))
        if receipt := self.repository.get_receipt(op_id):
            return receipt.result

        evidence_ids: list[str] = []
        for object_ref in input_refs:
            content = self.objects.read_bytes(object_ref)
            content_hash = hashlib.sha256(content).hexdigest()
            evidence_id = stable_id(
                "ev", security.tenant_id, security.security_scope_id, content_hash
            )
            evidence = Evidence(
                evidence_id=evidence_id,
                content_hash=content_hash,
                media_type=self.parsers.detect(content),
                object_ref=object_ref,
                source_type=source_type,
                security=security,
                created_at=utc_now(),
                locator=EvidenceLocator(
                    locator_type="bytes",
                    position={"start": 0, "end": len(content)},
                    fragment_hash=content_hash,
                ),
            )
            self.repository.put_evidence(evidence)
            evidence_ids.append(evidence_id)

        result = {"evidence_ids": sorted(set(evidence_ids)), "receipt_ids": [op_id]}
        self.repository.put_receipt(
            OperationReceipt(op_id, "preserve", "committed", result, utc_now())
        )
        return result

    def parse(
        self, *, request_id: str, evidence_ids: list[str], security: SecurityScope
    ) -> dict[str, Any]:
        op_id = scoped_operation_id(security, request_id, "parse", *sorted(evidence_ids))
        if receipt := self.repository.get_receipt(op_id):
            return receipt.result

        fragment_ids: list[str] = []
        warnings: list[str] = []
        for evidence_id in evidence_ids:
            evidence = self.repository.get_evidence(security, evidence_id)
            if evidence is None:
                raise LookupError(f"evidence not found in security scope: {evidence_id}")
            content = self.objects.read_bytes(evidence.object_ref)
            try:
                fragments = self.parsers.parse(evidence.media_type, content)
            except (UnicodeDecodeError, ValueError) as exc:
                warnings.append(f"parse_failed:{type(exc).__name__}")
                continue
            for fragment in fragments:
                encoded = fragment.text.encode("utf-8")
                content_hash = hashlib.sha256(encoded).hexdigest()
                position_json = json.dumps(
                    fragment.position, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                fragment_id = stable_id(
                    "frag",
                    evidence_id,
                    fragment.locator_type,
                    position_json,
                    content_hash,
                    self.parsers.revision,
                )
                derived_ref = self.objects.put_bytes(encoded)
                derived = Evidence(
                    evidence_id=fragment_id,
                    content_hash=content_hash,
                    media_type=fragment.media_type,
                    object_ref=derived_ref,
                    source_type=f"parser:{self.parsers.revision}",
                    security=security,
                    created_at=utc_now(),
                    locator=EvidenceLocator(
                        locator_type=fragment.locator_type,
                        position=fragment.position,
                        fragment_hash=content_hash,
                    ),
                    parent_evidence_id=evidence_id,
                )
                self.repository.put_evidence(derived)
                fragment_ids.append(fragment_id)
        result = {
            "fragment_ids": sorted(set(fragment_ids)),
            "warnings": sorted(set(warnings)),
            "parser_revision": self.parsers.revision,
            "receipt_ids": [op_id],
        }
        self.repository.put_receipt(
            OperationReceipt(op_id, "parse", "committed", result, utc_now())
        )
        return result

    def understand(
        self, *, request_id: str, evidence_ids: list[str], security: SecurityScope
    ) -> dict[str, Any]:
        op_id = scoped_operation_id(security, request_id, "understand", *sorted(evidence_ids))
        if receipt := self.repository.get_receipt(op_id):
            return receipt.result
        cache_id = scoped_operation_id(
            security,
            "content-addressed-understanding",
            "understand",
            self.understanding.revision,
            self.research.revision if self.research is not None else "web-search:none",
            str(self.research_count),
            str(self.research_max_queries),
            *sorted(evidence_ids),
        )
        if cached := self.repository.get_receipt(cache_id):
            self.repository.put_receipt(
                OperationReceipt(
                    op_id,
                    "understand_cache_hit",
                    "committed",
                    cached.result,
                    utc_now(),
                )
            )
            return cached.result

        grouped: dict[str, list[Evidence]] = {}
        for evidence_id in evidence_ids:
            evidence = self.repository.get_evidence(security, evidence_id)
            if evidence is None:
                raise LookupError(f"evidence not found in security scope: {evidence_id}")
            grouped.setdefault(evidence.parent_evidence_id or evidence.evidence_id, []).append(
                evidence
            )

        candidate_ids: list[str] = []
        scope_ids: list[str] = []
        gap_ids: list[str] = []
        warnings: list[str] = []
        for document_evidence_id, fragments in grouped.items():
            document = self.repository.get_evidence(security, document_evidence_id)
            if document is not None:
                try:
                    text = self.objects.read_bytes(document.object_ref).decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = "\n".join(
                        self.objects.read_bytes(fragment.object_ref).decode("utf-8")
                        for fragment in fragments
                    )
            else:
                text = "\n".join(
                    self.objects.read_bytes(fragment.object_ref).decode("utf-8")
                    for fragment in fragments
                )
            prior_knowledge = self._related_knowledge(security, text)
            prior_gaps = self._related_gaps(security, text)
            result = self._understand_document(
                text,
                document_evidence_id,
                tuple(prior_knowledge),
                tuple(prior_gaps),
            )
            result = self._enforce_epistemic_gate(
                text=text,
                evidence_id=document_evidence_id,
                result=result,
            )
            result = self._research_unresolved_gaps(
                text=text,
                evidence_id=document_evidence_id,
                security=security,
                result=result,
                prior_knowledge=tuple(prior_knowledge),
            )
            warnings.extend(result.warnings)
            document_scope_ids: list[str] = []
            fragment_ids = tuple(fragment.evidence_id for fragment in fragments)
            for scope in result.scopes:
                canonical_domains = scope.domain_ids or canonicalize_domains(scope.domain)
                labels = scope.domain_labels or scope.domain
                revision = DomainRevision(
                    object_type="scope",
                    object_id=scope.scope_id,
                    revision=scope.revision,
                    status="review_required" if scope.review_required else "evaluated",
                    security=security,
                    payload={
                        "domain": list(canonical_domains),
                        "domain_ids": list(canonical_domains),
                        "domain_labels": list(labels),
                        "domain_aliases": list(domain_aliases(canonical_domains)),
                        "subjects": list(scope.subjects),
                        "tasks": list(scope.tasks),
                        "preconditions": list(scope.preconditions),
                        "exclusions": list(scope.exclusions),
                        "valid_from": scope.valid_from,
                        "valid_until": scope.valid_until,
                        "geography": list(scope.geography),
                        "risk": scope.risk.value,
                        "confidence": scope.confidence,
                        "unknowns": list(scope.unknowns),
                        "review_required": scope.review_required,
                        "provider_revision": self.understanding.revision,
                    },
                    evidence_ids=fragment_ids,
                    created_at=utc_now(),
                )
                self.repository.put_revision(
                    revision,
                    scoped_operation_id(security, request_id, "scope", scope.scope_id),
                )
                scope_ids.append(scope.scope_id)
                document_scope_ids.append(scope.scope_id)
            for claim in result.claims:
                claim_evidence_ids = tuple(
                    sorted(
                        {
                            *_match_claim_evidence(
                                claim.content,
                                claim.source_excerpts,
                                fragments,
                                self.objects,
                            ),
                            *(
                                evidence_id
                                for evidence_id in claim.evidence_ids
                                if (
                                    (stored_evidence := self.repository.get_evidence(
                                        security, evidence_id
                                    ))
                                    is not None
                                    and stored_evidence.locator is not None
                                    and stored_evidence.locator.locator_type
                                    == "web_search_result"
                                )
                            ),
                        }
                    )
                )
                matched_source_text = " ".join(
                    self.objects.read_bytes(fragment.object_ref).decode("utf-8")
                    for fragment in fragments
                    if fragment.evidence_id in claim_evidence_ids
                )
                source_text = " ".join(
                    value
                    for value in (" ".join(claim.source_excerpts), matched_source_text)
                    if value
                )
                source_identifiers = _extract_source_identifiers(source_text)
                derived_ids = tuple(
                    knowledge_id
                    for knowledge_id in claim.derived_from_knowledge_ids
                    if any(
                        str(item.get("knowledge_id")) == knowledge_id
                        for item in prior_knowledge
                    )
                )
                if not derived_ids and source_identifiers:
                    current_identifiers = set(source_identifiers)
                    derived_ids = tuple(
                        str(item["knowledge_id"])
                        for item in prior_knowledge
                        if current_identifiers.intersection(
                            str(value)
                            for value in item.get("source_identifiers", [])
                        )
                    )
                knowledge_delta = claim.knowledge_delta
                if derived_ids and knowledge_delta == "new":
                    knowledge_delta = "refines"
                resolves_gap_ids = tuple(dict.fromkeys(claim.resolves_gap_ids))
                revision = DomainRevision(
                    object_type="candidate",
                    object_id=claim.candidate_id,
                    revision=1,
                    status=KnowledgeStatus.CANDIDATE,
                    security=security,
                    payload={
                        "kind": claim.kind,
                        "content": claim.content,
                        "confidence": claim.confidence,
                        "provider_revision": claim.provider_revision,
                        "unknowns": list(claim.unknowns),
                        "scope_ids": sorted(set(document_scope_ids)),
                        "source_identifiers": list(source_identifiers),
                        "experience_schema_version": claim.schema_version,
                        "title": claim.title,
                        "context": claim.context,
                        "problem": claim.problem,
                        "mechanism": claim.mechanism,
                        "action": claim.action,
                        "outcome": claim.outcome,
                        "rationale": claim.rationale,
                        "caveats": list(claim.caveats),
                        "source_excerpts": list(claim.source_excerpts),
                        "logical_relations": [
                            asdict(relation) for relation in claim.logical_relations
                        ],
                        "derived_from_knowledge_ids": list(derived_ids),
                        "resolves_gap_ids": list(resolves_gap_ids),
                        "knowledge_delta": knowledge_delta,
                    },
                    evidence_ids=claim_evidence_ids,
                    created_at=utc_now(),
                )
                self.repository.put_revision(
                    revision,
                    scoped_operation_id(security, request_id, "candidate", claim.candidate_id),
                )
                candidate_ids.append(claim.candidate_id)
            for gap in result.gaps:
                gap_evidence_ids = tuple(
                    sorted(
                        {
                            *fragment_ids,
                            *(
                                evidence_id
                                for evidence_id in gap.research_evidence_ids
                                if self.repository.get_evidence(security, evidence_id)
                                is not None
                            ),
                        }
                    )
                )
                gap_status = (
                    gap.research_status
                    if gap.research_status
                    in {
                        "open",
                        "research_exhausted",
                        "research_unavailable",
                        "partially_resolved",
                    }
                    else "open"
                )
                revision = DomainRevision(
                    object_type="knowledge_gap",
                    object_id=gap.gap_id,
                    revision=1,
                    status=gap_status,
                    security=security,
                    payload={
                        "question": gap.question,
                        "reason_unresolved": gap.reason_unresolved,
                        "possible_directions": list(gap.possible_directions),
                        "missing_evidence": list(gap.missing_evidence),
                        "research_queries": list(gap.research_queries),
                        "linking_keys": list(gap.linking_keys),
                        "confidence": gap.confidence,
                        "source_excerpts": list(gap.source_excerpts),
                        "related_knowledge_ids": list(gap.related_knowledge_ids),
                        "research_status": gap_status,
                        "research_attempts": list(gap.research_attempts),
                        "research_evidence_ids": list(gap.research_evidence_ids),
                        "scope_ids": sorted(set(document_scope_ids)),
                        "provider_revision": self.understanding.revision,
                        "resolved_by_knowledge_ids": [],
                        "resolution_candidate_ids": [
                            claim.candidate_id
                            for claim in result.claims
                            if gap.gap_id in claim.resolves_gap_ids
                        ],
                    },
                    evidence_ids=gap_evidence_ids,
                    created_at=utc_now(),
                )
                self.repository.put_revision(
                    revision,
                    scoped_operation_id(
                        security, request_id, "knowledge_gap", gap.gap_id
                    ),
                )
                gap_ids.append(gap.gap_id)

        result_payload = {
            "candidate_ids": sorted(set(candidate_ids)),
            "scope_ids": sorted(set(scope_ids)),
            "knowledge_gap_ids": sorted(set(gap_ids)),
            "warnings": sorted(set(warnings)),
            "receipt_ids": [cache_id],
        }
        self.repository.put_receipt(
            OperationReceipt(
                cache_id,
                "understand_content_cache",
                "committed",
                result_payload,
                utc_now(),
            )
        )
        self.repository.put_receipt(
            OperationReceipt(op_id, "understand", "committed", result_payload, utc_now())
        )
        return result_payload

    def _related_knowledge(
        self, security: SecurityScope, text: str
    ) -> list[dict[str, Any]]:
        related = self.repository.search_active_knowledge(security, text[:8_000], 8)
        return [
            {
                "knowledge_id": revision.object_id,
                "revision": revision.revision,
                "title": revision.payload.get("title", ""),
                "content": revision.payload.get("content", ""),
                "context": revision.payload.get("context", ""),
                "rationale": revision.payload.get("rationale", ""),
                "caveats": revision.payload.get("caveats", []),
                "source_identifiers": revision.payload.get(
                    "source_identifiers", []
                ),
            }
            for revision in related
        ]

    def _enforce_epistemic_gate(
        self,
        *,
        text: str,
        evidence_id: str,
        result: UnderstandingResult,
    ) -> UnderstandingResult:
        unknown_scope = bool(result.scopes) and all(
            (scope.domain_ids or scope.domain) == ("unknown",)
            for scope in result.scopes
        )
        supported = []
        withheld = []
        for claim in result.claims:
            critical_uncertainty = (
                claim.confidence < 0.65
                or (claim.schema_version >= 2 and not claim.source_excerpts)
                or (unknown_scope and bool(claim.unknowns))
            )
            if critical_uncertainty:
                withheld.append(claim)
            else:
                supported.append(claim)
        gaps = list(result.gaps)
        if withheld and not gaps:
            identifiers = _extract_source_identifiers(text)
            for claim in withheld[:8]:
                question = (
                    f"What critical context or definitions are required before this "
                    f"experience can be understood safely: {claim.title or claim.content[:240]}?"
                )
                linking_keys = tuple(
                    dict.fromkeys(
                        [
                            *identifiers,
                            *re.findall(r"[A-Za-z0-9_-]{3,}", claim.title)[:8],
                        ]
                    )
                )
                gaps.append(
                    KnowledgeGapCandidate(
                        gap_id=stable_id("gap", evidence_id, question),
                        question=question,
                        reason_unresolved=(
                            "The model produced a low-support synthesis whose critical "
                            "meaning or applicability cannot be established safely."
                        ),
                        possible_directions=(
                            "Obtain definitions for the unidentified terms and referents.",
                            "Find a complete source that states the mechanism, conditions, "
                            "and verifiable outcome.",
                        ),
                        missing_evidence=tuple(
                            dict.fromkeys(
                                [
                                    *claim.unknowns,
                                    "A source-specific definition and applicability boundary",
                                ]
                            )
                        )[:12],
                        research_queries=tuple(
                            query[:70]
                            for query in (
                                " ".join(identifiers),
                                f"{claim.title} definitions context",
                            )
                            if query.strip()
                        )[:2],
                        linking_keys=linking_keys,
                        confidence=max(0.8, 1.0 - claim.confidence),
                        source_excerpts=claim.source_excerpts,
                    )
                )
        warnings = tuple(
            dict.fromkeys(
                [
                    *result.warnings,
                    *(("unsupported_candidate_withheld",) if withheld else ()),
                ]
            )
        )
        return UnderstandingResult(
            claims=tuple(supported),
            scopes=result.scopes,
            gaps=tuple(gaps),
            warnings=warnings,
        )

    def _related_gaps(
        self, security: SecurityScope, text: str
    ) -> list[dict[str, Any]]:
        return [
            {
                "gap_id": revision.object_id,
                "question": revision.payload.get("question", ""),
                "reason_unresolved": revision.payload.get("reason_unresolved", ""),
                "possible_directions": revision.payload.get(
                    "possible_directions", []
                ),
                "missing_evidence": revision.payload.get("missing_evidence", []),
                "research_queries": revision.payload.get("research_queries", []),
                "linking_keys": revision.payload.get("linking_keys", []),
                "confidence": revision.payload.get("confidence", 0.0),
                "source_excerpts": revision.payload.get("source_excerpts", []),
                "related_knowledge_ids": revision.payload.get(
                    "related_knowledge_ids", []
                ),
                "research_status": revision.status,
                "research_attempts": revision.payload.get("research_attempts", []),
                "research_evidence_ids": revision.payload.get(
                    "research_evidence_ids", []
                ),
            }
            for revision in self.repository.search_open_gaps(security, text[:8_000], 8)
        ]

    def _research_unresolved_gaps(
        self,
        *,
        text: str,
        evidence_id: str,
        security: SecurityScope,
        result: UnderstandingResult,
        prior_knowledge: tuple[dict[str, Any], ...],
    ) -> UnderstandingResult:
        if not result.gaps:
            return result
        if security.classification.casefold() in {
            "confidential",
            "prohibited",
            "restricted",
            "secret",
        }:
            blocked_at = utc_now()
            blocked_gaps = tuple(
                replace(
                    gap,
                    research_status="research_unavailable",
                    research_attempts=(
                        {
                            "attempt_id": stable_id(
                                "research", evidence_id, gap.gap_id, "egress-blocked"
                            ),
                            "query": "",
                            "status": "blocked",
                            "provider_revision": "web-search:egress-blocked",
                            "result_count": 0,
                            "evidence_ids": [],
                            "error_type": "classification_egress_blocked",
                            "searched_at": blocked_at,
                        },
                    ),
                    research_evidence_ids=(),
                )
                for gap in result.gaps
            )
            return UnderstandingResult(
                claims=result.claims,
                scopes=result.scopes,
                gaps=blocked_gaps,
                warnings=tuple(
                    dict.fromkeys(
                        [
                            *result.warnings,
                            "knowledge_gap_preserved",
                            "web_research_blocked_by_classification",
                        ]
                    )
                ),
            )
        query_gap_ids: dict[str, set[str]] = {}
        gap_queries: dict[str, tuple[str, ...]] = {}
        for gap in result.gaps:
            queries = gap.research_queries or (gap.question,)
            gap_queries[gap.gap_id] = tuple(
                normalized
                for query in queries[:2]
                if (normalized := " ".join(query.split())[:70])
            )
        # Allocate one query to every gap before giving any gap a second query.
        for query_index in range(2):
            for gap in result.gaps:
                queries = gap_queries.get(gap.gap_id, ())
                if query_index < len(queries):
                    query_gap_ids.setdefault(queries[query_index], set()).add(
                        gap.gap_id
                    )
                if len(query_gap_ids) >= self.research_max_queries:
                    break
            if len(query_gap_ids) >= self.research_max_queries:
                break

        attempts_by_gap: dict[str, list[dict[str, Any]]] = {
            gap.gap_id: [] for gap in result.gaps
        }
        research_ids_by_gap: dict[str, set[str]] = {
            gap.gap_id: set() for gap in result.gaps
        }
        observations: list[dict[str, Any]] = []
        for query, related_gap_ids in query_gap_ids.items():
            batch = (
                self.research.search(query, count=self.research_count)
                if self.research is not None
                else None
            )
            batch_status = batch.status if batch is not None else "disabled"
            provider_revision = (
                batch.provider_revision if batch is not None else "web-search:disabled"
            )
            batch_evidence_ids: list[str] = []
            if batch is not None:
                for observation in batch.observations:
                    web_evidence_id = self._preserve_research_observation(
                        security=security,
                        observation=asdict(observation),
                        provider_revision=provider_revision,
                    )
                    batch_evidence_ids.append(web_evidence_id)
                    observations.append(
                        {
                            **asdict(observation),
                            "evidence_id": web_evidence_id,
                            "gap_ids": sorted(related_gap_ids),
                        }
                    )
            attempt = {
                "attempt_id": stable_id(
                    "research", evidence_id, query, provider_revision
                ),
                "query": query,
                "status": batch_status,
                "provider_revision": provider_revision,
                "result_count": len(batch_evidence_ids),
                "evidence_ids": batch_evidence_ids,
                "error_type": batch.error_type if batch is not None else "disabled",
                "searched_at": utc_now(),
            }
            for gap_id in related_gap_ids:
                attempts_by_gap[gap_id].append(attempt)
                research_ids_by_gap[gap_id].update(batch_evidence_ids)

        completed_observations = bool(observations)
        reassessed: UnderstandingResult | None = None
        reassessment_warning = ""
        if completed_observations:
            reassess = getattr(self.understanding, "reassess_gaps", None)
            if callable(reassess):
                try:
                    reassessed = reassess(
                        text,
                        evidence_id,
                        tuple(asdict(gap) for gap in result.gaps),
                        tuple(observations),
                        prior_knowledge=prior_knowledge,
                    )
                except Exception as exc:
                    reassessment_warning = (
                        "gap_reassessment_failed:"
                        f"{getattr(exc, 'code', None) or type(exc).__name__}"
                    )
            else:
                reassessment_warning = "gap_reassessment_unavailable"

        reassessed_gaps = {
            gap.gap_id: gap for gap in (reassessed.gaps if reassessed else ())
        }
        research_claims = tuple(reassessed.claims if reassessed else ())
        resolved_gap_ids = {
            gap_id for claim in research_claims for gap_id in claim.resolves_gap_ids
        }
        final_gaps: list[KnowledgeGapCandidate] = []
        for original in result.gaps:
            updated = reassessed_gaps.get(original.gap_id, original)
            attempts = tuple(attempts_by_gap.get(original.gap_id, []))
            evidence_ids = tuple(sorted(research_ids_by_gap.get(original.gap_id, set())))
            statuses = {str(attempt.get("status")) for attempt in attempts}
            if original.gap_id in resolved_gap_ids:
                status = "partially_resolved"
            elif completed_observations or "no_results" in statuses:
                status = "research_exhausted"
            else:
                status = "research_unavailable"
            final_gaps.append(
                KnowledgeGapCandidate(
                    gap_id=original.gap_id,
                    question=updated.question,
                    reason_unresolved=updated.reason_unresolved,
                    possible_directions=updated.possible_directions,
                    missing_evidence=updated.missing_evidence,
                    research_queries=updated.research_queries or original.research_queries,
                    linking_keys=updated.linking_keys or original.linking_keys,
                    confidence=updated.confidence,
                    source_excerpts=updated.source_excerpts or original.source_excerpts,
                    related_knowledge_ids=(
                        updated.related_knowledge_ids or original.related_knowledge_ids
                    ),
                    research_status=status,
                    research_attempts=attempts,
                    research_evidence_ids=evidence_ids,
                )
            )
        warnings = tuple(
            dict.fromkeys(
                [
                    *result.warnings,
                    *(reassessed.warnings if reassessed else ()),
                    *(("knowledge_gap_preserved",) if final_gaps else ()),
                    *((reassessment_warning,) if reassessment_warning else ()),
                ]
            )
        )
        return UnderstandingResult(
            claims=tuple((*result.claims, *research_claims)),
            scopes=result.scopes,
            gaps=tuple(final_gaps),
            warnings=warnings,
        )

    def _preserve_research_observation(
        self,
        *,
        security: SecurityScope,
        observation: dict[str, Any],
        provider_revision: str,
    ) -> str:
        content = json.dumps(
            {
                "title": observation.get("title", ""),
                "url": observation.get("url", ""),
                "media": observation.get("media", ""),
                "published_at": observation.get("published_at"),
                "snippet": observation.get("snippet", ""),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        content_hash = hashlib.sha256(content).hexdigest()
        web_evidence_id = stable_id(
            "evweb",
            security.tenant_id,
            security.security_scope_id,
            str(observation.get("observation_id", "")),
            content_hash,
        )
        stored = Evidence(
            evidence_id=web_evidence_id,
            content_hash=content_hash,
            media_type="application/vnd.uka.web-search-observation+json",
            object_ref=self.objects.put_bytes(content),
            source_type=provider_revision,
            security=security,
            created_at=utc_now(),
            locator=EvidenceLocator(
                locator_type="web_search_result",
                position={
                    "query": str(observation.get("query", ""))[:70],
                    "rank": int(observation.get("rank", 0)),
                    "url": str(observation.get("url", ""))[:2_000],
                },
                fragment_hash=content_hash,
            ),
        )
        self.repository.put_evidence(stored)
        return web_evidence_id

    def _understand_document(
        self,
        text: str,
        evidence_id: str,
        prior_knowledge: tuple[dict[str, Any], ...],
        prior_gaps: tuple[dict[str, Any], ...],
    ):
        try:
            return self.understanding.understand(
                text,
                evidence_id,
                prior_knowledge=prior_knowledge,
                prior_gaps=prior_gaps,
            )
        except TypeError as exc:
            # Keep third-party v1 providers usable while the public provider contract
            # migrates to retrieval-augmented document understanding.
            if "prior_gaps" in str(exc):
                try:
                    return self.understanding.understand(
                        text, evidence_id, prior_knowledge=prior_knowledge
                    )
                except TypeError as legacy_exc:
                    if "prior_knowledge" not in str(legacy_exc):
                        raise
                    return self.understanding.understand(text, evidence_id)
            if "prior_knowledge" in str(exc):
                return self.understanding.understand(text, evidence_id)
            raise

    def evaluate(
        self,
        *,
        security: SecurityScope,
        candidate_ids: list[str],
        scope_ids: list[str],
        gap_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if not candidate_ids:
            return {
                "decision": "hold",
                "reason": (
                    "knowledge_gap_preserved"
                    if gap_ids
                    else "no_supported_candidates"
                ),
            }
        if not scope_ids:
            return {"decision": "review", "reason": "scope_missing"}
        scopes = [
            self.repository.get_revision(security, "scope", scope_id) for scope_id in scope_ids
        ]
        candidates = [
            self.repository.get_revision(security, "candidate", candidate_id)
            for candidate_id in candidate_ids
        ]
        if any(
            candidate is None
            or _resolve_candidate_scope(candidate, scopes, allowed_scope_ids=set(scope_ids)) is None
            for candidate in candidates
        ):
            return {"decision": "hold", "reason": "scope_association_invalid"}
        if any(scope is None or scope.payload.get("review_required") for scope in scopes):
            return {"decision": "review", "reason": "scope_review_required"}
        if any(
            candidate is None or float(candidate.payload.get("confidence", 0.0)) < 0.75
            for candidate in candidates
        ):
            return {"decision": "review", "reason": "low_confidence"}
        if any(
            candidate is not None
            and int(candidate.payload.get("experience_schema_version", 1)) >= 2
            and (
                not str(candidate.payload.get("title", "")).strip()
                or not str(candidate.payload.get("context", "")).strip()
                or not str(candidate.payload.get("rationale", "")).strip()
                or not candidate.payload.get("source_excerpts")
            )
            for candidate in candidates
        ):
            return {"decision": "review", "reason": "experience_context_incomplete"}
        return {"decision": "review", "reason": "independent_approval_required"}

    def compile_knowledge(
        self,
        *,
        request_id: str,
        security: SecurityScope,
        candidate_ids: list[str],
        scope_ids: list[str],
        approved: bool,
    ) -> dict[str, Any]:
        op_id = scoped_operation_id(
            security, request_id, "compile_knowledge", str(approved), *sorted(candidate_ids)
        )
        if receipt := self.repository.get_receipt(op_id):
            return receipt.result

        knowledge_ids: list[str] = []
        evolution_ids: list[str] = []
        resolved_gap_ids: list[str] = []
        status = KnowledgeStatus.ACTIVE if approved else KnowledgeStatus.EVALUATED
        scopes = [
            self.repository.get_revision(security, "scope", scope_id) for scope_id in scope_ids
        ]
        for candidate_id in candidate_ids:
            candidate = self.repository.get_revision(security, "candidate", candidate_id)
            if candidate is None:
                raise LookupError(f"candidate not found: {candidate_id}")
            scope_id = _resolve_candidate_scope(
                candidate, scopes, allowed_scope_ids=set(scope_ids)
            )
            if scope_id is None:
                raise LookupError(f"candidate scope association invalid: {candidate_id}")
            knowledge_id = stable_id(
                "kn", security.tenant_id, security.security_scope_id, candidate_id
            )
            knowledge_op_id = scoped_operation_id(
                security, request_id, "knowledge", candidate_id
            )
            derived_from = [
                str(knowledge_id)
                for knowledge_id in candidate.payload.get(
                    "derived_from_knowledge_ids", []
                )
                if self.repository.get_active_revision(
                    security, "knowledge", str(knowledge_id)
                )
                is not None
            ]
            knowledge_delta = str(candidate.payload.get("knowledge_delta", "new"))
            evolution_id = (
                stable_id(
                    "evo",
                    security.tenant_id,
                    security.security_scope_id,
                    knowledge_id,
                    knowledge_delta,
                    *sorted(derived_from),
                )
                if derived_from
                and knowledge_delta in {"reinforces", "refines", "contradicts"}
                else ""
            )
            existing = self.repository.get_revision_by_operation(knowledge_op_id)
            if existing is None:
                revision = DomainRevision(
                    object_type="knowledge",
                    object_id=knowledge_id,
                    revision=1,
                    status=status,
                    security=security,
                    payload={
                        **_experience_payload(candidate.payload),
                        "scope_id": scope_id,
                        "candidate_id": candidate_id,
                        "activation_review_completed": approved,
                        "learning": {
                            "mode": "retrieval_augmented_synthesis",
                            "knowledge_delta": knowledge_delta,
                            "derived_from_knowledge_ids": derived_from,
                            "resolves_gap_ids": list(
                                candidate.payload.get("resolves_gap_ids", [])
                            ),
                            "automatic_activation": False,
                            "governance": "human_approval",
                            "evolution_candidate_id": evolution_id or None,
                        },
                    },
                    evidence_ids=candidate.evidence_ids,
                    created_at=utc_now(),
                )
                revision = self.repository.put_revision(revision, knowledge_op_id)
            else:
                revision = existing
            if approved:
                self.repository.activate_revision(revision)
                for gap_id in candidate.payload.get("resolves_gap_ids", []):
                    gap = self.repository.get_revision(
                        security, "knowledge_gap", str(gap_id)
                    )
                    if gap is None:
                        continue
                    if gap.status == "resolved":
                        resolved_gap_ids.append(gap.object_id)
                        continue
                    gap_revision = DomainRevision(
                        object_type="knowledge_gap",
                        object_id=gap.object_id,
                        revision=self.repository.next_revision(
                            security, "knowledge_gap", gap.object_id
                        ),
                        parent_revision=gap.revision,
                        status="resolved",
                        security=security,
                        payload={
                            **gap.payload,
                            "research_status": "resolved",
                            "resolved_by_knowledge_ids": sorted(
                                {
                                    *gap.payload.get(
                                        "resolved_by_knowledge_ids", []
                                    ),
                                    knowledge_id,
                                }
                            ),
                            "resolution_candidate_ids": sorted(
                                {
                                    *gap.payload.get(
                                        "resolution_candidate_ids", []
                                    ),
                                    candidate_id,
                                }
                            ),
                            "resolved_at": utc_now(),
                        },
                        evidence_ids=tuple(
                            sorted({*gap.evidence_ids, *revision.evidence_ids})
                        ),
                        created_at=utc_now(),
                    )
                    self.repository.put_revision(
                        gap_revision,
                        scoped_operation_id(
                            security,
                            request_id,
                            "resolve_knowledge_gap",
                            gap.object_id,
                            knowledge_id,
                        ),
                    )
                    resolved_gap_ids.append(gap.object_id)
            if evolution_id:
                evolution = DomainRevision(
                    object_type="evolution",
                    object_id=evolution_id,
                    revision=1,
                    status=KnowledgeStatus.CANDIDATE,
                    security=security,
                    payload={
                        "target_type": "knowledge_synthesis",
                        "baseline_knowledge_ids": sorted(set(derived_from)),
                        "candidate_knowledge_id": knowledge_id,
                        "knowledge_delta": knowledge_delta,
                        "stage": "proposal",
                        "required_gates": ["offline", "shadow", "canary", "human"],
                        "automatic_activation": False,
                    },
                    evidence_ids=candidate.evidence_ids,
                    created_at=utc_now(),
                )
                self.repository.put_revision(
                    evolution,
                    scoped_operation_id(
                        security, request_id, "knowledge_evolution", evolution_id
                    ),
                )
                evolution_ids.append(evolution_id)
            knowledge_ids.append(knowledge_id)

        result = {
            "knowledge_ids": sorted(set(knowledge_ids)),
            "evolution_ids": sorted(set(evolution_ids)),
            "resolved_knowledge_gap_ids": sorted(set(resolved_gap_ids)),
            "status": status.value,
            "receipt_ids": [op_id],
        }
        self.repository.put_receipt(
            OperationReceipt(op_id, "compile_knowledge", "committed", result, utc_now())
        )
        return result


@dataclass(slots=True)
class CorrectionService:
    repository: RepositoryPort
    objects: ObjectStorePort
    ingestion: IngestionService

    def prepare(
        self,
        *,
        request_id: str,
        target_id: str,
        expected_revision: int,
        replacement_ref: str,
        actor_id: str,
        security: SecurityScope,
    ) -> dict[str, Any]:
        op_id = scoped_operation_id(
            security, request_id, "correction", target_id, str(expected_revision)
        )
        if receipt := self.repository.get_receipt(op_id):
            return receipt.result
        target = self.repository.get_revision(
            security, "knowledge", target_id, expected_revision
        )
        if target is None:
            return {"resolved": False, "reason": "target_or_revision_not_found"}
        active = self.repository.get_active_revision(security, "knowledge", target_id)
        if active is None or active.revision != expected_revision:
            return {"resolved": False, "reason": "stale_active_revision"}
        preserved = self.ingestion.preserve(
            request_id=f"{request_id}:correction",
            input_refs=[replacement_ref],
            security=security,
            source_type="user_correction",
        )
        correction_id = stable_id("cor", request_id, target_id, str(expected_revision))
        revision = DomainRevision(
            object_type="correction",
            object_id=correction_id,
            revision=1,
            status="recorded",
            security=security,
            payload={
                "target_type": "knowledge",
                "target_id": target_id,
                "expected_revision": expected_revision,
                "replacement_ref": replacement_ref,
                "actor_id": actor_id,
            },
            evidence_ids=tuple(preserved["evidence_ids"]),
            created_at=utc_now(),
        )
        self.repository.put_revision(revision, op_id)
        result = {
            "resolved": True,
            "correction_ids": [correction_id],
            "evidence_ids": preserved["evidence_ids"],
            "receipt_ids": sorted(set([op_id, *preserved.get("receipt_ids", [])])),
        }
        self.repository.put_receipt(
            OperationReceipt(op_id, "correction", "committed", result, utc_now())
        )
        return result

    def recompute(
        self,
        *,
        request_id: str,
        correction_id: str,
        security: SecurityScope,
    ) -> dict[str, Any]:
        op_id = scoped_operation_id(security, request_id, "recompute", correction_id)
        if receipt := self.repository.get_receipt(op_id):
            return receipt.result
        correction = self.repository.get_revision(security, "correction", correction_id)
        if correction is None:
            raise LookupError(f"correction not found: {correction_id}")
        target_id = str(correction.payload["target_id"])
        target = self.repository.get_revision(
            security,
            "knowledge",
            target_id,
            int(correction.payload["expected_revision"]),
        )
        if target is None:
            raise LookupError("correction target became unavailable")
        active = self.repository.get_active_revision(security, "knowledge", target_id)
        if active is None or active.revision != target.revision:
            return {"passed": False, "reason": "stale_active_revision"}
        replacement = self.objects.read_bytes(str(correction.payload["replacement_ref"])).decode(
            "utf-8"
        ).strip()
        if not replacement:
            return {"passed": False, "reason": "empty_replacement"}
        parsed = self.ingestion.parse(
            request_id=f"{request_id}:correction",
            evidence_ids=list(correction.evidence_ids),
            security=security,
        )
        if not parsed["fragment_ids"]:
            return {"passed": False, "reason": "correction_parse_failed"}
        understood = self.ingestion.understand(
            request_id=f"{request_id}:correction",
            evidence_ids=parsed["fragment_ids"],
            security=security,
        )
        if not understood["candidate_ids"]:
            return {"passed": False, "reason": "correction_claim_missing"}
        evaluation = self.ingestion.evaluate(
            security=security,
            candidate_ids=understood["candidate_ids"],
            scope_ids=understood["scope_ids"],
        )
        if evaluation["decision"] == "hold":
            return {"passed": False, "reason": str(evaluation["reason"])}
        candidates = [
            self.repository.get_revision(security, "candidate", candidate_id)
            for candidate_id in understood["candidate_ids"]
        ]
        if any(candidate is None for candidate in candidates):
            return {"passed": False, "reason": "correction_candidate_missing"}
        scopes = [
            self.repository.get_revision(security, "scope", scope_id)
            for scope_id in understood["scope_ids"]
        ]
        resolved_scope_ids = {
            resolved
            for candidate in candidates
            if candidate is not None
            and (
                resolved := _resolve_candidate_scope(
                    candidate,
                    scopes,
                    allowed_scope_ids=set(understood["scope_ids"]),
                )
            )
            is not None
        }
        if len(resolved_scope_ids) != 1:
            return {"passed": False, "reason": "correction_scope_invalid"}
        scope_id = resolved_scope_ids.pop()
        scope = next(
            (item for item in scopes if item is not None and item.object_id == scope_id),
            None,
        )
        if scope is None:
            return {"passed": False, "reason": "correction_scope_missing"}
        risk = str(scope.payload.get("risk", "normal"))
        review_required = (
            bool(scope.payload.get("review_required"))
            or risk in {"high", "prohibited"}
            or any(
                candidate is None
                or float(candidate.payload.get("confidence", 0.0)) < 0.75
                for candidate in candidates
            )
        )
        candidate_values = [candidate for candidate in candidates if candidate is not None]
        experience_payload = _merge_candidate_experiences(candidate_values)
        next_revision = self.repository.next_revision(security, "knowledge", target_id)
        impact_id = stable_id("impact", correction_id, target_id, str(next_revision))
        impact = DomainRevision(
            object_type="impact",
            object_id=impact_id,
            revision=1,
            status="evaluated",
            security=security,
            payload={
                "correction_id": correction_id,
                "affected_objects": [
                    {"object_type": "knowledge", "object_id": target_id}
                ],
                "reason": "knowledge_content_revision",
                "recompute_plan": ["knowledge", "fts", "regression"],
            },
            evidence_ids=correction.evidence_ids,
            created_at=utc_now(),
        )
        self.repository.put_revision(
            impact,
            scoped_operation_id(security, request_id, "impact", correction_id),
        )
        revision = DomainRevision(
            object_type="knowledge",
            object_id=target_id,
            revision=next_revision,
            parent_revision=target.revision,
            status=KnowledgeStatus.CANDIDATE,
            security=security,
            payload={
                **experience_payload,
                "scope_id": scope_id,
                "candidate_ids": [candidate.object_id for candidate in candidate_values],
                "correction_id": correction_id,
                "learning": {
                    "mode": "correction_driven_revision",
                    "knowledge_delta": "refines",
                    "derived_from_knowledge_ids": [target_id],
                    "automatic_activation": False,
                    "governance": "human_approval" if review_required else "validated_correction",
                },
            },
            evidence_ids=tuple(
                sorted(
                    {
                        evidence_id
                        for candidate in candidate_values
                        for evidence_id in candidate.evidence_ids
                    }
                )
            ),
            created_at=utc_now(),
        )
        revision = self.repository.put_revision(revision, op_id)
        regression_id = stable_id("reg", correction_id, target_id, str(next_revision))
        regression = DomainRevision(
            object_type="regression",
            object_id=regression_id,
            revision=1,
            status="passed",
            security=security,
            payload={
                "correction_id": correction_id,
                "target_id": target_id,
                "before_hash": hashlib.sha256(
                    str(target.payload.get("content", "")).encode("utf-8")
                ).hexdigest(),
                "after_hash": hashlib.sha256(replacement.encode("utf-8")).hexdigest(),
                "synthesis_hash": hashlib.sha256(
                    str(experience_payload.get("content", "")).encode("utf-8")
                ).hexdigest(),
                "checks": ["non_empty", "revision_monotonic", "evidence_preserved"],
                "passed": True,
                "scope_id": scope_id,
                "risk": risk,
                "review_required": review_required,
            },
            evidence_ids=revision.evidence_ids,
            created_at=utc_now(),
        )
        self.repository.put_revision(
            regression,
            scoped_operation_id(security, request_id, "regression", correction_id),
        )
        result = {
            "passed": True,
            "knowledge_ids": [target_id],
            "candidate_revision": revision.revision,
            "impact_ids": [impact_id],
            "evaluation_ids": [regression_id],
            "scope_ids": [scope_id],
            "review_required": review_required,
            "risk": risk,
            "receipt_ids": [op_id],
        }
        self.repository.put_receipt(
            OperationReceipt(op_id, "recompute", "committed", result, utc_now())
        )
        return result

    def publish(
        self,
        *,
        request_id: str,
        target_id: str,
        revision_number: int,
        security: SecurityScope,
    ) -> dict[str, Any]:
        op_id = scoped_operation_id(
            security, request_id, "publish_correction", target_id, str(revision_number)
        )
        if receipt := self.repository.get_receipt(op_id):
            return receipt.result
        candidate = self.repository.get_revision(
            security, "knowledge", target_id, revision_number
        )
        if candidate is None:
            raise LookupError("candidate correction revision not found")
        active = DomainRevision(
            object_type=candidate.object_type,
            object_id=candidate.object_id,
            revision=candidate.revision,
            parent_revision=candidate.parent_revision,
            status=KnowledgeStatus.ACTIVE,
            security=candidate.security,
            payload=candidate.payload,
            evidence_ids=candidate.evidence_ids,
            created_at=candidate.created_at,
        )
        if candidate.parent_revision is None:
            raise RuntimeError("correction_parent_revision_missing")
        try:
            self.repository.activate_revision(
                active, expected_active_revision=candidate.parent_revision
            )
        except RuntimeError as exc:
            if str(exc) != "stale_active_revision":
                raise
            return {
                "published": False,
                "reason": "stale_active_revision",
                "knowledge_ids": [target_id],
                "candidate_revision": revision_number,
                "receipt_ids": [],
            }
        result = {
            "published": True,
            "knowledge_ids": [target_id],
            "active_revision": revision_number,
            "receipt_ids": [op_id],
        }
        self.repository.put_receipt(
            OperationReceipt(op_id, "publish_correction", "committed", result, utc_now())
        )
        return result


@dataclass(slots=True)
class LifecycleService:
    repository: RepositoryPort
    objects: ObjectStorePort

    def create_candidate(
        self,
        *,
        request_id: str,
        object_type: str,
        payload: dict[str, Any],
        evidence_ids: list[str],
        security: SecurityScope,
    ) -> DomainRevision:
        op_id = scoped_operation_id(security, request_id, f"create_{object_type}")
        if existing := self.repository.get_revision_by_operation(op_id):
            return existing
        object_id = stable_id(object_type[:3], request_id, json.dumps(payload, sort_keys=True))
        revision = DomainRevision(
            object_type=object_type,
            object_id=object_id,
            revision=1,
            status=KnowledgeStatus.CANDIDATE,
            security=security,
            payload=payload,
            evidence_ids=tuple(sorted(set(evidence_ids))),
            created_at=utc_now(),
        )
        stored = self.repository.put_revision(revision, op_id)
        self.repository.put_receipt(
            OperationReceipt(
                op_id,
                f"create_{object_type}",
                "committed",
                {"object_id": stored.object_id, "revision": stored.revision},
                utc_now(),
            )
        )
        return stored

    def activate(self, revision: DomainRevision, *, request_id: str) -> str:
        op_id = scoped_operation_id(
            revision.security,
            request_id,
            f"activate_{revision.object_type}",
            revision.object_id,
            str(revision.revision),
        )
        if self.repository.get_receipt(op_id):
            return op_id
        self.repository.activate_revision(
            DomainRevision(
                object_type=revision.object_type,
                object_id=revision.object_id,
                revision=revision.revision,
                status=KnowledgeStatus.ACTIVE,
                security=revision.security,
                payload=revision.payload,
                evidence_ids=revision.evidence_ids,
                created_at=revision.created_at,
                parent_revision=revision.parent_revision,
            )
        )
        self.repository.put_receipt(
            OperationReceipt(
                op_id,
                f"activate_{revision.object_type}",
                "committed",
                {"object_id": revision.object_id, "revision": revision.revision},
                utc_now(),
            )
        )
        return op_id

    def verify_evolution_evidence(
        self,
        *,
        security: SecurityScope,
        stage: str,
        target_type: str,
        baseline_revision: str,
        candidate_revision: str,
        evaluation_ids: dict[str, Any],
    ) -> dict[str, Any]:
        evaluation_id = str(evaluation_ids.get(stage, "")).strip()
        if not evaluation_id:
            return {"passed": False, "reason": f"{stage}_evaluation_missing"}
        evaluation = self.repository.get_revision(
            security, "evaluation", evaluation_id
        )
        if evaluation is None:
            return {"passed": False, "reason": f"{stage}_evaluation_not_found"}
        payload = evaluation.payload
        expected = {
            "stage": stage,
            "target_type": target_type,
            "baseline_revision": baseline_revision,
            "candidate_revision": candidate_revision,
        }
        if any(str(payload.get(key, "")) != value for key, value in expected.items()):
            return {"passed": False, "reason": f"{stage}_evaluation_mismatch"}
        if evaluation.status != "passed" or payload.get("passed") is not True:
            return {"passed": False, "reason": f"{stage}_evaluation_failed"}
        if payload.get("safety_regression") is True:
            return {"passed": False, "reason": "safety_metric_regression"}
        if not evaluation.evidence_ids:
            return {"passed": False, "reason": f"{stage}_evidence_missing"}
        for evidence_id in evaluation.evidence_ids:
            evidence = self.repository.get_evidence(security, evidence_id)
            if evidence is None or evidence.locator is None:
                return {"passed": False, "reason": f"{stage}_evidence_invalid"}
            try:
                content = self.objects.read_bytes(evidence.object_ref)
            except (FileNotFoundError, OSError, ValueError):
                return {"passed": False, "reason": f"{stage}_evidence_invalid"}
            if hashlib.sha256(content).hexdigest() != evidence.content_hash:
                return {"passed": False, "reason": f"{stage}_evidence_invalid"}
        return {"passed": True, "evaluation_id": evaluation_id}

    def compile_skill(
        self,
        *,
        request_id: str,
        knowledge: DomainRevision,
        name: str,
    ) -> DomainRevision:
        safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-") or "knowledge-skill"
        markdown = (
            f"# {safe_name}\n\n"
            "## Purpose\n\n"
            "Apply the evidence-backed procedure within its declared scope.\n\n"
            "## Procedure Evidence\n\n"
            f"{knowledge.payload.get('content', '')}\n\n"
            "## Safety\n\n"
            "This P0/P1 artifact is advisory-only. External tools and network are denied.\n"
        )
        manifest = {
            "name": safe_name,
            "version": "1.0.0",
            "source_knowledge_id": knowledge.object_id,
            "input_schema": {"type": "object", "additionalProperties": False},
            "output_schema": {"type": "object"},
            "permissions": [],
            "network": "deny",
            "rollback_target": None,
            "tests": ["manifest_schema", "no_permissions", "network_denied"],
        }
        markdown_ref = self.objects.put_bytes(markdown.encode("utf-8"))
        manifest_ref = self.objects.put_bytes(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
        )
        return self.create_candidate(
            request_id=request_id,
            object_type="skill",
            payload={**manifest, "skill_markdown_ref": markdown_ref, "manifest_ref": manifest_ref},
            evidence_ids=list(knowledge.evidence_ids),
            security=knowledge.security,
        )

    def validate_skill(self, skill: DomainRevision) -> dict[str, Any]:
        markdown = self.objects.read_bytes(str(skill.payload["skill_markdown_ref"])).decode(
            "utf-8"
        )
        manifest = json.loads(
            self.objects.read_bytes(str(skill.payload["manifest_ref"])).decode("utf-8")
        )
        required = {
            "name",
            "version",
            "source_knowledge_id",
            "input_schema",
            "output_schema",
            "permissions",
            "network",
        }
        errors: list[str] = []
        if not markdown.startswith("# "):
            errors.append("skill_markdown_heading_missing")
        if not required.issubset(manifest):
            errors.append("manifest_fields_missing")
        if manifest.get("permissions") != [] or manifest.get("network") != "deny":
            errors.append("unsafe_default_permissions")
        return {"passed": not errors, "errors": errors}

    def sandbox_test_skill(self, skill: DomainRevision) -> dict[str, Any]:
        validation = self.validate_skill(skill)
        return {
            "passed": validation["passed"],
            "mode": "advisory-no-side-effects",
            "checks": ["artifact_integrity", "network_denied", "permissions_empty"],
            "errors": validation["errors"],
        }


@dataclass(slots=True)
class RetrievalService:
    repository: RepositoryPort
    objects: ObjectStorePort

    def retrieve(
        self,
        *,
        security: SecurityScope,
        query: str,
        limit: int = 5,
        query_scope: dict[str, Any] | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        if not query.strip():
            return _empty_evidence_pack("empty_query")
        requested_limit = max(1, min(limit, 50))
        open_gaps = self.repository.search_open_gaps(
            security, query, requested_limit
        )
        revisions = self.repository.search_active_knowledge(security, query, 1000)
        if open_gaps and (
            not revisions
            or any(_query_targets_gap(query, gap.payload) for gap in open_gaps)
        ):
            return _knowledge_gap_evidence_pack(open_gaps)
        if not revisions:
            return _empty_evidence_pack("no_active_scope_match")
        effective_as_of = _parse_time(as_of) if as_of else datetime.now(UTC)
        items: list[EvidencePackItem] = []
        conflicts: list[dict[str, Any]] = []
        review_required = False
        for revision in revisions:
            scope_id = revision.payload.get("scope_id")
            scope_revision = (
                self.repository.get_revision(security, "scope", str(scope_id))
                if scope_id
                else None
            )
            if scope_id and scope_revision is None:
                return _empty_evidence_pack("evidence_integrity_failure")
            scope = scope_revision.payload if scope_revision else {}
            if not _scope_matches(scope, query_scope or {}, effective_as_of):
                continue
            risk = str(scope.get("risk", "normal"))
            review_required = review_required or (
                bool(scope.get("review_required"))
                and not bool(
                    revision.payload.get("activation_review_completed", False)
                )
            )
            review_required = review_required or risk in {"high", "prohibited"}
            if revision.payload.get("conflict_status") == "open":
                conflicts.append(
                    {
                        "knowledge_id": revision.object_id,
                        "type": revision.payload.get("conflict_type", "open_conflict"),
                    }
                )
            evidence_payloads: list[dict[str, Any]] = []
            for evidence_id in revision.evidence_ids:
                evidence = self.repository.get_evidence(security, evidence_id)
                if evidence is None or evidence.locator is None:
                    return _empty_evidence_pack("evidence_integrity_failure")
                try:
                    evidence_bytes = self.objects.read_bytes(evidence.object_ref)
                except (FileNotFoundError, OSError, ValueError):
                    return _empty_evidence_pack("evidence_integrity_failure")
                if hashlib.sha256(evidence_bytes).hexdigest() != evidence.content_hash:
                    return _empty_evidence_pack("evidence_integrity_failure")
                if evidence.parent_evidence_id:
                    parent = self.repository.get_evidence(
                        security, evidence.parent_evidence_id
                    )
                    if parent is None or parent.locator is None:
                        return _empty_evidence_pack("evidence_integrity_failure")
                    try:
                        parent_bytes = self.objects.read_bytes(parent.object_ref)
                    except (FileNotFoundError, OSError, ValueError):
                        return _empty_evidence_pack("evidence_integrity_failure")
                    if hashlib.sha256(parent_bytes).hexdigest() != parent.content_hash:
                        return _empty_evidence_pack("evidence_integrity_failure")
                evidence_payloads.append(
                    {
                        "evidence_id": evidence.evidence_id,
                        "content_hash": evidence.content_hash,
                        "parent_evidence_id": evidence.parent_evidence_id,
                        "locator": asdict(evidence.locator) if evidence.locator else None,
                        "excerpt": re.sub(
                            r"\s+",
                            " ",
                            evidence_bytes.decode("utf-8", errors="replace"),
                        ).strip()[:500],
                    }
                )
            items.append(
                EvidencePackItem(
                    knowledge_id=revision.object_id,
                    revision=revision.revision,
                    content=str(revision.payload.get("content", "")),
                    scope=scope,
                    evidence=tuple(evidence_payloads),
                    confidence=float(revision.payload.get("confidence", 0.0)),
                    experience=_experience_view(revision.payload),
                )
            )
        if not items:
            return (
                _knowledge_gap_evidence_pack(open_gaps)
                if open_gaps
                else _empty_evidence_pack("scope_or_time_mismatch")
            )
        selected_ids = {item.knowledge_id for item in items}
        selected_revisions = [
            revision for revision in revisions if revision.object_id in selected_ids
        ]
        for index, left in enumerate(selected_revisions):
            left_sources = set(left.payload.get("source_identifiers", []))
            if not left_sources:
                continue
            for right in selected_revisions[index + 1 :]:
                shared = left_sources.intersection(
                    set(right.payload.get("source_identifiers", []))
                )
                if shared and _contents_conflict(left.payload, right.payload):
                    conflicts.append(
                        {
                            "knowledge_ids": sorted(
                                {left.object_id, right.object_id}
                            ),
                            "type": "source_identifier_conflict",
                            "source_identifiers": sorted(shared),
                        }
                    )
        selected_items = items[:requested_limit]
        status = (
            "review_required"
            if conflicts or review_required
            else ("answered_with_gaps" if open_gaps else "answered")
        )
        answer = (
            "unknown"
            if status == "review_required"
            else "\n".join(item.content for item in selected_items)
        )
        pack = EvidencePack(
            status=status,
            answer=answer,
            items=tuple(selected_items),
            conflicts=tuple(conflicts),
            unknowns=(
                ("human_review_required",)
                if status == "review_required"
                else (("related_knowledge_gaps_open",) if open_gaps else ())
            ),
            knowledge_gaps=_gap_views(open_gaps),
        )
        evidence_ids = sorted(
            {
                evidence["evidence_id"]
                for item in selected_items
                for evidence in item.evidence
            }
        )
        return {
            "answer": answer,
            "status": status,
            "knowledge_ids": [item.knowledge_id for item in selected_items],
            "knowledge_gap_ids": [gap.object_id for gap in open_gaps],
            "evidence_ids": evidence_ids,
            "evidence_pack": asdict(pack),
        }


def _empty_evidence_pack(reason: str) -> dict[str, Any]:
    pack = EvidencePack(
        status="unknown", answer="unknown", items=(), unknowns=(reason,)
    )
    return {
        "answer": "unknown",
        "status": "unknown",
        "knowledge_ids": [],
        "evidence_ids": [],
        "evidence_pack": asdict(pack),
    }


def _knowledge_gap_evidence_pack(
    gaps: list[DomainRevision],
) -> dict[str, Any]:
    gap_views = _gap_views(gaps)
    missing = tuple(
        dict.fromkeys(
            [
                "knowledge_gap_open",
                *(
                    str(item)
                    for gap in gaps
                    for item in gap.payload.get("missing_evidence", [])
                ),
            ]
        )
    )
    pack = EvidencePack(
        status="abstained",
        answer="unknown",
        items=(),
        unknowns=missing,
        knowledge_gaps=gap_views,
    )
    return {
        "answer": "unknown",
        "status": "abstained",
        "knowledge_ids": [],
        "knowledge_gap_ids": [gap.object_id for gap in gaps],
        "evidence_ids": sorted(
            {evidence_id for gap in gaps for evidence_id in gap.evidence_ids}
        ),
        "evidence_pack": asdict(pack),
    }


def _gap_views(gaps: list[DomainRevision]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "gap_id": gap.object_id,
            "revision": gap.revision,
            "status": gap.status,
            "question": str(gap.payload.get("question", "")),
            "reason_unresolved": str(
                gap.payload.get("reason_unresolved", "")
            ),
            "possible_directions": [
                str(item)
                for item in gap.payload.get("possible_directions", [])
            ],
            "missing_evidence": [
                str(item) for item in gap.payload.get("missing_evidence", [])
            ],
            "linking_keys": [
                str(item) for item in gap.payload.get("linking_keys", [])
            ],
            "research_status": str(
                gap.payload.get("research_status", gap.status)
            ),
            "research_attempt_count": len(
                gap.payload.get("research_attempts", [])
            ),
        }
        for gap in gaps
    )


def _query_targets_gap(query: str, payload: dict[str, Any]) -> bool:
    normalized = re.sub(r"\s+", " ", query.casefold()).strip()
    identifiers = re.findall(
        r"\b[A-Za-z][A-Za-z0-9]{1,15}(?:-[A-Za-z0-9]{1,16})+\b", normalized
    )
    remainder = normalized
    for identifier in identifiers:
        remainder = remainder.replace(identifier.casefold(), " ")
    linking_keys = [
        re.sub(r"\s+", " ", str(value).casefold()).strip()
        for value in payload.get("linking_keys", [])
        if str(value).strip()
    ]
    if any(
        key in remainder
        for key in linking_keys
        if key not in {identifier.casefold() for identifier in identifiers}
        and len(key) >= 4
    ):
        return True
    stopwords = {
        "what",
        "when",
        "where",
        "which",
        "this",
        "that",
        "with",
        "from",
        "about",
        "knowledge",
        "experience",
    }
    terms = {
        term
        for term in re.findall(r"[a-z0-9_]{4,}", remainder)
        if term not in stopwords
    }
    gap_text = " ".join(
        [
            str(payload.get("question", "")),
            str(payload.get("reason_unresolved", "")),
            " ".join(linking_keys),
        ]
    ).casefold()
    if terms and len(terms) >= 2:
        matched = sum(term in gap_text for term in terms)
        if matched >= 2 and matched / len(terms) >= 0.5:
            return True
    cjk = "".join(re.findall(r"[\u3400-\u9fff]", remainder))
    if len(cjk) >= 4:
        bigrams = {cjk[index : index + 2] for index in range(len(cjk) - 1)}
        matched = sum(term in gap_text for term in bigrams)
        return matched >= 2 and matched / len(bigrams) >= 0.5
    return False


def _normalized_content(payload: dict[str, Any]) -> str:
    return re.sub(r"\s+", " ", str(payload.get("content", "")).casefold()).strip()


_QUANTITY_WORDS = frozenset(
    {
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
        "hundred",
        "thousand",
    }
)
_NEGATIONS = frozenset({"not", "no", "never", "without", "禁止", "不得", "不"})
_MUTUALLY_EXCLUSIVE = (
    (frozenset({"required", "mandatory"}), frozenset({"optional"})),
    (frozenset({"allowed", "permitted"}), frozenset({"prohibited", "forbidden"})),
    (frozenset({"enabled", "active"}), frozenset({"disabled", "inactive"})),
    (frozenset({"true"}), frozenset({"false"})),
)


def _contents_conflict(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_text = _normalized_content(left)
    right_text = _normalized_content(right)
    if left_text == right_text:
        return False
    identifier_pattern = r"\b[A-Za-z][A-Za-z0-9]{1,15}(?:-[A-Za-z0-9]{1,16})+\b"
    left_without_id = re.sub(identifier_pattern, " ", left_text)
    right_without_id = re.sub(identifier_pattern, " ", right_text)
    left_tokens = set(re.findall(r"[\w.%]+", left_without_id, flags=re.UNICODE))
    right_tokens = set(re.findall(r"[\w.%]+", right_without_id, flags=re.UNICODE))
    left_values = {
        token
        for token in left_tokens
        if re.fullmatch(r"\d+(?:\.\d+)?%?", token) or token in _QUANTITY_WORDS
    }
    right_values = {
        token
        for token in right_tokens
        if re.fullmatch(r"\d+(?:\.\d+)?%?", token) or token in _QUANTITY_WORDS
    }
    left_base = left_tokens - left_values - _NEGATIONS
    right_base = right_tokens - right_values - _NEGATIONS
    union = left_base | right_base
    similarity = len(left_base & right_base) / len(union) if union else 0.0
    if left_values and right_values and left_values != right_values and similarity >= 0.6:
        return True
    left_negative = bool(left_tokens & _NEGATIONS)
    right_negative = bool(right_tokens & _NEGATIONS)
    if left_negative != right_negative and similarity >= 0.7:
        return True
    for positive, negative in _MUTUALLY_EXCLUSIVE:
        if (
            bool(left_tokens & positive)
            and bool(right_tokens & negative)
            or bool(left_tokens & negative)
            and bool(right_tokens & positive)
        ) and similarity >= 0.5:
            return True
    return False


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _scope_matches(
    scope: dict[str, Any], requested: dict[str, Any], as_of: datetime
) -> bool:
    valid_from = scope.get("valid_from")
    valid_until = scope.get("valid_until")
    if valid_from and as_of < _parse_time(str(valid_from)):
        return False
    if valid_until and as_of > _parse_time(str(valid_until)):
        return False
    wanted_domain = requested.get("domain")
    if wanted_domain:
        requested_values = (
            wanted_domain if isinstance(wanted_domain, (list, tuple, set)) else [wanted_domain]
        )
        wanted_ids = set(canonicalize_domains(str(value) for value in requested_values))
        stored_values = scope.get("domain_ids") or scope.get("domain") or []
        allowed_ids = set(canonicalize_domains(str(value) for value in stored_values))
        if allowed_ids and wanted_ids.isdisjoint(allowed_ids):
            return False
    for stored_key, requested_key in (
        ("subjects", "subject"),
        ("tasks", "task"),
        ("geography", "geography"),
    ):
        wanted = requested.get(requested_key)
        allowed = scope.get(stored_key, [])
        if wanted and allowed and str(wanted).casefold() not in {
            str(value).casefold() for value in allowed
        }:
            return False
    return True


def _resolve_candidate_scope(
    candidate: DomainRevision,
    scopes: list[DomainRevision | None],
    *,
    allowed_scope_ids: set[str],
) -> str | None:
    explicit = {
        str(scope_id)
        for scope_id in candidate.payload.get("scope_ids", [])
        if str(scope_id) in allowed_scope_ids
    }
    candidates = [
        scope
        for scope in scopes
        if scope is not None
        and scope.object_id in allowed_scope_ids
        and set(scope.evidence_ids).intersection(candidate.evidence_ids)
        and (not explicit or scope.object_id in explicit)
    ]
    return candidates[0].object_id if len(candidates) == 1 else None


def _extract_source_identifiers(text: str) -> tuple[str, ...]:
    patterns = (
        r"\b[A-Z][A-Z0-9]{1,15}(?:-[A-Z0-9]{1,16})+\b",
        r"\b[A-Za-z]{1,12}[_/][A-Za-z0-9_./~-]{2,80}\b",
    )
    identifiers: list[str] = []
    for pattern in patterns:
        identifiers.extend(re.findall(pattern, text))
    return tuple(dict.fromkeys(identifiers))[:64]


def _match_claim_evidence(
    content: str,
    source_excerpts: tuple[str, ...],
    fragments: list[Evidence],
    objects: ObjectStorePort,
) -> tuple[str, ...]:
    needles = [
        re.sub(r"\s+", " ", value).strip().casefold()
        for value in (*source_excerpts, content)
        if value.strip()
    ]
    matched: list[str] = []
    for fragment in fragments:
        fragment_text = re.sub(
            r"\s+",
            " ",
            objects.read_bytes(fragment.object_ref).decode("utf-8"),
        ).strip().casefold()
        if any(
            fragment_text == needle
            or (len(fragment_text) >= 8 and fragment_text in needle)
            or (len(needle) >= 8 and needle in fragment_text)
            for needle in needles
        ):
            matched.append(fragment.evidence_id)
    # An unsupported model-to-locator alignment must remain broad rather than
    # pretending to have sentence-level precision.
    return tuple(sorted(set(matched or [fragment.evidence_id for fragment in fragments])))


def _experience_payload(candidate_payload: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "kind",
        "content",
        "confidence",
        "provider_revision",
        "experience_schema_version",
        "title",
        "context",
        "problem",
        "mechanism",
        "action",
        "outcome",
        "rationale",
        "caveats",
        "source_excerpts",
        "logical_relations",
        "source_identifiers",
        "derived_from_knowledge_ids",
        "knowledge_delta",
        "unknowns",
    )
    return {key: candidate_payload.get(key) for key in fields}


def _experience_view(payload: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "experience_schema_version",
        "title",
        "context",
        "problem",
        "mechanism",
        "action",
        "outcome",
        "rationale",
        "caveats",
        "source_excerpts",
        "logical_relations",
        "source_identifiers",
        "learning",
    )
    return {key: payload.get(key) for key in fields}


def _merge_candidate_experiences(
    candidates: list[DomainRevision],
) -> dict[str, Any]:
    def joined(field: str) -> str:
        values = [
            str(candidate.payload.get(field, "")).strip()
            for candidate in candidates
            if str(candidate.payload.get(field, "")).strip()
        ]
        return " ".join(dict.fromkeys(values))

    def collected(field: str) -> list[Any]:
        values: list[Any] = []
        for candidate in candidates:
            raw = candidate.payload.get(field, [])
            if isinstance(raw, list):
                values.extend(raw)
        return list(dict.fromkeys(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in values))

    contents = [
        str(candidate.payload.get("content", "")).strip()
        for candidate in candidates
        if str(candidate.payload.get("content", "")).strip()
    ]
    relations = [
        json.loads(value) for value in collected("logical_relations")
    ]
    for left, right in zip(contents, contents[1:], strict=False):
        relations.append({"source": left, "relation": "sequence", "target": right})
    deltas = {
        str(candidate.payload.get("knowledge_delta", "new")) for candidate in candidates
    }
    delta = next(
        (value for value in ("contradicts", "refines", "reinforces") if value in deltas),
        "new",
    )
    return {
        "kind": "experience",
        "content": " ".join(contents),
        "confidence": min(
            (float(candidate.payload.get("confidence", 0.0)) for candidate in candidates),
            default=0.0,
        ),
        "provider_revision": joined("provider_revision"),
        "experience_schema_version": max(
            (
                int(candidate.payload.get("experience_schema_version", 1))
                for candidate in candidates
            ),
            default=1,
        ),
        "title": joined("title")[:200],
        "context": joined("context"),
        "problem": joined("problem"),
        "mechanism": joined("mechanism"),
        "action": joined("action"),
        "outcome": joined("outcome"),
        "rationale": joined("rationale"),
        "caveats": [json.loads(value) for value in collected("caveats")],
        "source_excerpts": [
            json.loads(value) for value in collected("source_excerpts")
        ],
        "logical_relations": relations,
        "source_identifiers": [
            json.loads(value) for value in collected("source_identifiers")
        ],
        "derived_from_knowledge_ids": [
            json.loads(value)
            for value in collected("derived_from_knowledge_ids")
        ],
        "knowledge_delta": delta,
        "unknowns": [json.loads(value) for value in collected("unknowns")],
    }


@dataclass(slots=True)
class ServiceContainer:
    repository: RepositoryPort
    objects: ObjectStorePort
    ingestion: IngestionService
    corrections: CorrectionService
    lifecycle: LifecycleService
    retrieval: RetrievalService


def safe_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?。！？])\s*|\n+", text) if part.strip()]
