from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class KnowledgeStatus(StrEnum):
    CANDIDATE = "candidate"
    EVALUATED = "evaluated"
    APPROVED = "approved"
    ACTIVE = "active"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class RiskLevel(StrEnum):
    NORMAL = "normal"
    SENSITIVE = "sensitive"
    HIGH = "high"
    PROHIBITED = "prohibited"


@dataclass(frozen=True, slots=True)
class SecurityScope:
    tenant_id: str
    security_scope_id: str
    classification: str = "internal"

    def __post_init__(self) -> None:
        if not self.tenant_id.strip() or not self.security_scope_id.strip():
            raise ValueError("tenant_id and security_scope_id are required")


@dataclass(frozen=True, slots=True)
class EvidenceLocator:
    locator_type: str
    position: dict[str, Any]
    fragment_hash: str


@dataclass(frozen=True, slots=True)
class Evidence:
    evidence_id: str
    content_hash: str
    media_type: str
    object_ref: str
    source_type: str
    security: SecurityScope
    created_at: str
    locator: EvidenceLocator | None = None
    parent_evidence_id: str | None = None


@dataclass(frozen=True, slots=True)
class ClaimCandidate:
    candidate_id: str
    content: str
    confidence: float
    evidence_ids: tuple[str, ...]
    provider_revision: str
    kind: str = "claim"
    unknowns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if not self.evidence_ids:
            raise ValueError("candidate must reference evidence")


@dataclass(frozen=True, slots=True)
class ApplicabilityScope:
    scope_id: str
    domain: tuple[str, ...] = ("unknown",)
    domain_ids: tuple[str, ...] = ()
    domain_labels: tuple[str, ...] = ()
    subjects: tuple[str, ...] = ()
    tasks: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    valid_from: str | None = None
    valid_until: str | None = None
    geography: tuple[str, ...] = ()
    risk: RiskLevel = RiskLevel.NORMAL
    confidence: float = 0.0
    unknowns: tuple[str, ...] = ()
    revision: int = 1

    @property
    def review_required(self) -> bool:
        return (
            self.risk in {RiskLevel.HIGH, RiskLevel.PROHIBITED}
            or self.confidence < 0.7
            or bool(self.unknowns)
            or (self.domain_ids or self.domain) == ("unknown",)
        )


@dataclass(frozen=True, slots=True)
class DomainRevision:
    object_type: str
    object_id: str
    revision: int
    status: str
    security: SecurityScope
    payload: dict[str, Any]
    evidence_ids: tuple[str, ...]
    created_at: str
    parent_revision: int | None = None

    def as_record(self) -> dict[str, Any]:
        value = asdict(self)
        value["security"] = asdict(self.security)
        return value


@dataclass(frozen=True, slots=True)
class CorrectionEvent:
    correction_id: str
    target_type: str
    target_id: str
    expected_revision: int
    replacement_ref: str
    actor_id: str
    security: SecurityScope
    created_at: str
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OperationReceipt:
    operation_id: str
    operation_type: str
    status: str
    result: dict[str, Any]
    created_at: str


@dataclass(frozen=True, slots=True)
class UnderstandingResult:
    claims: tuple[ClaimCandidate, ...]
    scopes: tuple[ApplicabilityScope, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ParsedFragment:
    text: str
    locator_type: str
    position: dict[str, Any]
    media_type: str = "text/plain; charset=utf-8"

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("parsed fragment text cannot be empty")


@dataclass(frozen=True, slots=True)
class EvidencePackItem:
    knowledge_id: str
    revision: int
    content: str
    scope: dict[str, Any]
    evidence: tuple[dict[str, Any], ...]
    confidence: float


@dataclass(frozen=True, slots=True)
class EvidencePack:
    status: str
    answer: str
    items: tuple[EvidencePackItem, ...]
    conflicts: tuple[dict[str, Any], ...] = ()
    unknowns: tuple[str, ...] = ()
