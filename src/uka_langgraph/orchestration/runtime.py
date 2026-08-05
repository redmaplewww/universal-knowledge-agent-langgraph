from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

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
        return {
            "values": values,
            "next": list(snapshot.next),
            "interrupts": [
                {"id": item.id, "value": item.value} for item in snapshot.interrupts
            ],
            "checkpoint_id": snapshot.config.get("configurable", {}).get("checkpoint_id"),
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
