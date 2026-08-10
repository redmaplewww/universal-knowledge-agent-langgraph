from __future__ import annotations

import hashlib
import sqlite3
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from uka_langgraph.domain.models import DomainRevision, Evidence, SecurityScope
from uka_langgraph.infrastructure.bootstrap import build_services
from uka_langgraph.infrastructure.settings import Settings
from uka_langgraph.orchestration.context import RuntimeContext
from uka_langgraph.orchestration.root_graph import build_root_graph
from uka_langgraph.orchestration.state import WorkflowState


class AgentRuntime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.services = build_services(settings)
        self._checkpoint_connection: sqlite3.Connection | None = None
        self.checkpointer: SqliteSaver | None = None
        self.graph = None

    def __enter__(self) -> AgentRuntime:
        self.settings.initialize_directories()
        self._checkpoint_connection = sqlite3.connect(
            self.settings.checkpoint_db, check_same_thread=False
        )
        self.checkpointer = SqliteSaver(self._checkpoint_connection)
        self.checkpointer.setup()
        self.graph = build_root_graph(self.checkpointer)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._checkpoint_connection is not None:
            self._checkpoint_connection.close()
        self._checkpoint_connection = None
        self.checkpointer = None
        self.graph = None

    @property
    def context(self) -> RuntimeContext:
        return RuntimeContext(self.services, self.settings.graph_version)

    def stage_text(self, text: str) -> str:
        return self.services.objects.put_bytes(text.encode("utf-8"))

    def stage_file(self, path: Path) -> str:
        put_file = getattr(self.services.objects, "put_file", None)
        if put_file is None:
            return self.services.objects.put_bytes(path.read_bytes())
        return put_file(path)

    def invoke(
        self,
        *,
        intent: Literal["ingest", "correct", "build_skill", "evolve", "retrieve"],
        tenant_id: str,
        security_scope_id: str,
        actor_id: str = "local-user",
        classification: str = "internal",
        input_refs: list[str] | None = None,
        payload: dict[str, Any] | None = None,
        thread_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        graph = self._require_graph()
        actual_thread_id = thread_id or str(uuid.uuid4())
        actual_request_id = request_id or str(uuid.uuid4())
        checkpoint_thread_id = self._checkpoint_thread_id(
            actual_thread_id, tenant_id, security_scope_id
        )
        existing = graph.get_state(
            {"configurable": {"thread_id": checkpoint_thread_id}}
        )
        if existing.values:
            raise ValueError("thread already exists in security scope; resume it or use a new id")
        state: WorkflowState = {
            "request_id": actual_request_id,
            "thread_id": actual_thread_id,
            "tenant_id": tenant_id,
            "actor_id": actor_id,
            "intent": intent,
            "security_scope_id": security_scope_id,
            "classification": classification,
            "graph_version": self.settings.graph_version,
            "input_refs": input_refs or [],
            "evidence_ids": [],
            "fragment_ids": [],
            "candidate_ids": [],
            "scope_ids": [],
            "knowledge_ids": [],
            "skill_ids": [],
            "correction_ids": [],
            "impact_ids": [],
            "evaluation_ids": [],
            "evolution_ids": [],
            "receipt_ids": [],
            "warnings": [],
            "errors": [],
            "payload": payload or {},
            "status": "submitted",
            "next_action": intent,
            "approved": False,
            "response": {},
        }
        self._record_event(
            thread_id=actual_thread_id,
            request_id=actual_request_id,
            tenant_id=tenant_id,
            security_scope_id=security_scope_id,
            event_type="graph_run",
            status="submitted",
            metadata={"intent": intent, "graph_version": self.settings.graph_version},
        )
        try:
            result = graph.invoke(
                state,
                {"configurable": {"thread_id": checkpoint_thread_id}},
                context=self.context,
            )
        except Exception as exc:
            self._record_event(
                thread_id=actual_thread_id,
                request_id=actual_request_id,
                tenant_id=tenant_id,
                security_scope_id=security_scope_id,
                event_type="graph_run",
                status="failed",
                metadata={"intent": intent, "error_type": type(exc).__name__},
            )
            raise
        self._record_event(
            thread_id=actual_thread_id,
            request_id=actual_request_id,
            tenant_id=tenant_id,
            security_scope_id=security_scope_id,
            event_type="graph_run",
            status="interrupted" if "__interrupt__" in result else str(result.get("status")),
            metadata={
                "intent": intent,
                "receipt_count": len(result.get("receipt_ids", [])),
                "error_count": len(result.get("errors", [])),
            },
        )
        if "__interrupt__" in result:
            result = {
                **result,
                "approval_context": self._build_approval_context(
                    result, result.get("__interrupt__", [])
                ),
            }
        return result

    def resume(
        self,
        *,
        thread_id: str,
        value: dict[str, Any],
        tenant_id: str,
        security_scope_id: str,
    ) -> dict[str, Any]:
        graph = self._require_graph()
        checkpoint_thread_id = self._checkpoint_thread_id(
            thread_id, tenant_id, security_scope_id
        )
        config = {"configurable": {"thread_id": checkpoint_thread_id}}
        snapshot = graph.get_state(config)
        values = dict(snapshot.values)
        self._assert_snapshot_scope(values, tenant_id, security_scope_id)
        result = graph.invoke(
            Command(resume=value),
            config,
            context=self.context,
        )
        self._record_event(
            thread_id=thread_id,
            request_id=str(values.get("request_id", "unknown")),
            tenant_id=tenant_id,
            security_scope_id=security_scope_id,
            event_type="graph_resume",
            status=str(result.get("status", "unknown")),
            metadata={"decision_type": "approval" if "decision" in value else "resolution"},
        )
        return result

    def status(
        self, thread_id: str, *, tenant_id: str, security_scope_id: str
    ) -> dict[str, Any]:
        checkpoint_thread_id = self._checkpoint_thread_id(
            thread_id, tenant_id, security_scope_id
        )
        snapshot = self._require_graph().get_state(
            {"configurable": {"thread_id": checkpoint_thread_id}}
        )
        values = dict(snapshot.values)
        self._assert_snapshot_scope(values, tenant_id, security_scope_id)
        interrupts = [
            {"id": item.id, "value": item.value} for item in snapshot.interrupts
        ]
        return {
            "thread_id": thread_id,
            "values": values,
            "next": list(snapshot.next),
            "interrupts": interrupts,
            "approval_context": (
                self._build_approval_context(values, interrupts) if interrupts else None
            ),
            "checkpoint_id": snapshot.config.get("configurable", {}).get("checkpoint_id"),
        }

    def _build_approval_context(
        self, values: dict[str, Any], interrupts: list[Any]
    ) -> dict[str, Any]:
        security = SecurityScope(
            tenant_id=str(values.get("tenant_id", "")),
            security_scope_id=str(values.get("security_scope_id", "")),
            classification=str(values.get("classification", "internal")),
        )
        interrupt_value = _interrupt_value(interrupts[-1]) if interrupts else {}
        details = interrupt_value.get("details", {})
        candidate_ids = _string_list(
            values.get("candidate_ids") or details.get("candidate_ids")
        )
        scope_ids = _string_list(values.get("scope_ids") or details.get("scope_ids"))
        evidence_ids = _string_list(
            values.get("evidence_ids") or details.get("evidence_ids")
        )
        candidates = [
            self.services.repository.get_revision(security, "candidate", candidate_id)
            for candidate_id in candidate_ids
        ]
        scopes = [
            self.services.repository.get_revision(security, "scope", scope_id)
            for scope_id in scope_ids
        ]
        evidence = [
            self.services.repository.get_evidence(security, evidence_id)
            for evidence_id in evidence_ids[:12]
        ]
        return {
            "type": str(interrupt_value.get("type", "approval_required")),
            "subject": str(interrupt_value.get("subject", "unknown_approval")),
            "request_id": str(values.get("request_id", "")),
            "thread_id": str(values.get("thread_id", "")),
            "intent": str(values.get("intent", "")),
            "status": str(values.get("status", "review_required")),
            "actor_id": str(values.get("actor_id", "")),
            "classification": security.classification,
            "allowed_decisions": _string_list(
                interrupt_value.get("allowed_decisions") or ["approve", "reject"]
            ),
            "warnings": _string_list(values.get("warnings") or details.get("warnings")),
            "errors": _string_list(values.get("errors")),
            "candidates": [
                _candidate_preview(candidate)
                for candidate in candidates
                if candidate is not None
            ],
            "scopes": [
                _scope_preview(scope) for scope in scopes if scope is not None
            ],
            "evidence": [
                self._evidence_preview(item) for item in evidence if item is not None
            ],
            "evidence_count": len(evidence_ids),
            "evidence_truncated": len(evidence_ids) > 12,
            "decision_effects": {
                "approve": "compile_and_activate_knowledge",
                "reject": "keep_candidate_inactive_and_traceable",
            },
        }

    def _evidence_preview(self, evidence: Evidence) -> dict[str, Any]:
        try:
            excerpt = self.services.objects.read_bytes(evidence.object_ref).decode(
                "utf-8", errors="replace"
            )
        except (OSError, ValueError, UnicodeError):
            excerpt = ""
        return {
            "evidence_id": evidence.evidence_id,
            "parent_evidence_id": evidence.parent_evidence_id,
            "content_hash": evidence.content_hash,
            "media_type": evidence.media_type,
            "source_type": evidence.source_type,
            "locator": asdict(evidence.locator) if evidence.locator else None,
            "excerpt": _bounded_text(excerpt, 2000),
        }

    def events(
        self,
        thread_id: str,
        *,
        tenant_id: str,
        security_scope_id: str,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        self.status(
            thread_id, tenant_id=tenant_id, security_scope_id=security_scope_id
        )
        return self.services.repository.list_events(
            thread_id, tenant_id, security_scope_id, limit
        )

    def _record_event(
        self,
        *,
        thread_id: str,
        request_id: str,
        tenant_id: str,
        security_scope_id: str,
        event_type: str,
        status: str,
        metadata: dict[str, object],
    ) -> None:
        created_at = datetime.now(UTC).isoformat()
        event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{thread_id}:{event_type}:{status}:{created_at}"))
        self.services.repository.record_event(
            event_id=event_id,
            thread_id=thread_id,
            request_id=request_id,
            tenant_id=tenant_id,
            security_scope_id=security_scope_id,
            event_type=event_type,
            status=status,
            metadata=metadata,
            created_at=created_at,
        )

    def _require_graph(self):
        if self.graph is None:
            raise RuntimeError("AgentRuntime must be used as a context manager")
        return self.graph

    @staticmethod
    def _checkpoint_thread_id(
        thread_id: str, tenant_id: str, security_scope_id: str
    ) -> str:
        namespace = hashlib.sha256(
            f"{tenant_id}\x1f{security_scope_id}\x1f{thread_id}".encode("utf-8")
        ).hexdigest()
        return f"uka:{namespace}"

    @staticmethod
    def _assert_snapshot_scope(
        values: dict[str, Any], tenant_id: str, security_scope_id: str
    ) -> None:
        if not values or values.get("tenant_id") != tenant_id or values.get(
            "security_scope_id"
        ) != security_scope_id:
            raise LookupError("thread not found in security scope")


def _interrupt_value(interrupt_item: Any) -> dict[str, Any]:
    if isinstance(interrupt_item, dict):
        value = interrupt_item.get("value", interrupt_item)
    else:
        value = getattr(interrupt_item, "value", {})
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item) for item in value if str(item).strip()]


def _bounded_text(value: Any, limit: int = 1200) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else f"{text[:limit]}…"


def _candidate_preview(candidate: DomainRevision) -> dict[str, Any]:
    payload = candidate.payload
    text_fields = (
        "kind",
        "content",
        "provider_revision",
        "title",
        "context",
        "problem",
        "mechanism",
        "action",
        "outcome",
        "rationale",
        "knowledge_delta",
    )
    preview: dict[str, Any] = {
        "candidate_id": candidate.object_id,
        "revision": candidate.revision,
        "status": str(candidate.status),
        "classification": candidate.security.classification,
        "evidence_ids": list(candidate.evidence_ids),
        "confidence": float(payload.get("confidence", 0.0)),
        "experience_schema_version": int(
            payload.get("experience_schema_version", 1)
        ),
        "scope_ids": _string_list(payload.get("scope_ids")),
        "unknowns": _string_list(payload.get("unknowns")),
        "caveats": [
            _bounded_text(item, 500) for item in _string_list(payload.get("caveats"))
        ],
        "source_identifiers": _string_list(payload.get("source_identifiers")),
        "source_excerpts": [
            _bounded_text(item, 1000)
            for item in _string_list(payload.get("source_excerpts"))[:12]
        ],
        "derived_from_knowledge_ids": _string_list(
            payload.get("derived_from_knowledge_ids")
        ),
        "logical_relations": [],
    }
    preview.update({field: _bounded_text(payload.get(field)) for field in text_fields})
    relations = payload.get("logical_relations", [])
    if isinstance(relations, list):
        preview["logical_relations"] = [
            {
                "source": _bounded_text(item.get("source"), 800),
                "relation": _bounded_text(item.get("relation"), 80),
                "target": _bounded_text(item.get("target"), 800),
            }
            for item in relations[:20]
            if isinstance(item, dict)
        ]
    return preview


def _scope_preview(scope: DomainRevision) -> dict[str, Any]:
    payload = scope.payload
    list_fields = (
        "domain",
        "domain_ids",
        "domain_labels",
        "subjects",
        "tasks",
        "preconditions",
        "exclusions",
        "geography",
        "unknowns",
    )
    return {
        "scope_id": scope.object_id,
        "revision": scope.revision,
        "status": str(scope.status),
        "risk": str(payload.get("risk", "normal")),
        "confidence": float(payload.get("confidence", 0.0)),
        "review_required": bool(payload.get("review_required", False)),
        **{field: _string_list(payload.get(field)) for field in list_fields},
    }
