from __future__ import annotations

from typing import Protocol

from uka_langgraph.domain.models import (
    DomainRevision,
    Evidence,
    OperationReceipt,
    ParsedFragment,
    SecurityScope,
    UnderstandingResult,
)


class ObjectStorePort(Protocol):
    def put_bytes(self, content: bytes) -> str: ...

    def read_bytes(self, object_ref: str) -> bytes: ...


class RepositoryPort(Protocol):
    def initialize(self) -> None: ...

    def get_receipt(self, operation_id: str) -> OperationReceipt | None: ...

    def put_receipt(self, receipt: OperationReceipt) -> OperationReceipt: ...

    def put_evidence(self, evidence: Evidence) -> Evidence: ...

    def get_evidence(self, security: SecurityScope, evidence_id: str) -> Evidence | None: ...

    def put_revision(self, revision: DomainRevision, operation_id: str) -> DomainRevision: ...

    def get_revision(
        self,
        security: SecurityScope,
        object_type: str,
        object_id: str,
        revision: int | None = None,
    ) -> DomainRevision | None: ...

    def get_revision_by_operation(self, operation_id: str) -> DomainRevision | None: ...

    def next_revision(
        self, security: SecurityScope, object_type: str, object_id: str
    ) -> int: ...

    def activate_revision(
        self, revision: DomainRevision, *, expected_active_revision: int | None = None
    ) -> None: ...

    def get_active_revision(
        self, security: SecurityScope, object_type: str, object_id: str
    ) -> DomainRevision | None: ...

    def search_active_knowledge(
        self, security: SecurityScope, query: str, limit: int
    ) -> list[DomainRevision]: ...

    def count(self, object_type: str, security: SecurityScope | None = None) -> int: ...

    def record_event(
        self,
        *,
        event_id: str,
        thread_id: str,
        request_id: str,
        tenant_id: str,
        security_scope_id: str,
        event_type: str,
        status: str,
        metadata: dict[str, object],
        created_at: str,
    ) -> None: ...

    def list_events(
        self,
        thread_id: str,
        tenant_id: str,
        security_scope_id: str,
        limit: int = 100,
    ) -> list[dict[str, object]]: ...


class UnderstandingPort(Protocol):
    revision: str

    def understand(self, text: str, evidence_id: str) -> UnderstandingResult: ...

    def check_connection(self) -> dict[str, object]: ...


class ParserPort(Protocol):
    revision: str

    def supports(self, media_type: str, content: bytes) -> bool: ...

    def parse(self, content: bytes) -> list[ParsedFragment]: ...


class ParserRegistryPort(Protocol):
    revision: str

    def detect(self, content: bytes) -> str: ...

    def parse(self, media_type: str, content: bytes) -> list[ParsedFragment]: ...
