from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

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

