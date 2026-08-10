from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from uka_langgraph.infrastructure.settings import Settings
from uka_langgraph.interfaces.sdk import UniversalKnowledgeAgent


class SecurityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=128)
    security_scope_id: str = Field(min_length=1, max_length=128)
    actor_id: str = Field(default="api-user", min_length=1, max_length=128)


class IngestBody(SecurityRequest):
    text: str = Field(min_length=1, max_length=1_000_000)
    classification: str = "internal"
    auto_approve: bool = False
    thread_id: str | None = None
    request_id: str | None = None


class RetrieveBody(SecurityRequest):
    query: str = Field(min_length=1, max_length=8_000)
    query_scope: dict[str, Any] = Field(default_factory=dict)
    as_of: str | None = None
    limit: int = Field(default=5, ge=1, le=50)


class CorrectionBody(SecurityRequest):
    target_id: str
    expected_revision: int = Field(ge=1)
    replacement: str = Field(min_length=1, max_length=1_000_000)
    auto_approve: bool = False
    thread_id: str | None = None


class SkillBody(SecurityRequest):
    knowledge_id: str
    name: str | None = None
    auto_approve: bool = False
    thread_id: str | None = None


class EvolutionBody(SecurityRequest):
    target_type: str
    baseline_revision: str
    candidate_revision: str
    metrics: dict[str, Any]
    thread_id: str | None = None


class ResumeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: dict[str, Any]


def create_app(
    settings: Settings | None = None, *, project_root: Path | str | None = None
) -> FastAPI:
    agent = UniversalKnowledgeAgent(settings, project_root=project_root)
    app = FastAPI(
        title="Universal Knowledge Agent",
        version="0.3.0",
        description="Evidence-first local LangGraph knowledge agent API",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:8890",
            "http://localhost:8890",
            "http://127.0.0.1:3000",
            "http://localhost:3000",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health")
    def health(connect: bool = False) -> dict[str, Any]:
        return agent.doctor(connect=connect)

    @app.post("/v1/ingest")
    def ingest(body: IngestBody) -> dict[str, Any]:
        return _call(
            agent.ingest_text,
            body.text,
            tenant_id=body.tenant_id,
            security_scope_id=body.security_scope_id,
            actor_id=body.actor_id,
            classification=body.classification,
            auto_approve=body.auto_approve,
            thread_id=body.thread_id,
            request_id=body.request_id,
        )

    @app.post("/v1/retrieve")
    def retrieve(body: RetrieveBody) -> dict[str, Any]:
        return _call(
            agent.retrieve,
            body.query,
            tenant_id=body.tenant_id,
            security_scope_id=body.security_scope_id,
            actor_id=body.actor_id,
            query_scope=body.query_scope,
            as_of=body.as_of,
            limit=body.limit,
        )

    @app.get("/v1/knowledge")
    def list_knowledge(
        tenant_id: str, security_scope_id: str, limit: int = 100, domain: str | None = None
    ) -> list[dict[str, Any]]:
        return _call(
            agent.list_knowledge,
            tenant_id=tenant_id,
            security_scope_id=security_scope_id,
            limit=limit,
            domain=domain,
        )

    @app.get("/v1/knowledge-gaps")
    def list_knowledge_gaps(
        tenant_id: str, security_scope_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        return _call(
            agent.list_knowledge_gaps,
            tenant_id=tenant_id,
            security_scope_id=security_scope_id,
            limit=limit,
        )

    @app.post("/v1/corrections")
    def correct(body: CorrectionBody) -> dict[str, Any]:
        return _call(
            agent.correct_text,
            body.replacement,
            target_id=body.target_id,
            expected_revision=body.expected_revision,
            tenant_id=body.tenant_id,
            security_scope_id=body.security_scope_id,
            actor_id=body.actor_id,
            auto_approve=body.auto_approve,
            thread_id=body.thread_id,
        )

    @app.post("/v1/skills")
    def build_skill(body: SkillBody) -> dict[str, Any]:
        return _call(
            agent.build_skill,
            knowledge_id=body.knowledge_id,
            tenant_id=body.tenant_id,
            security_scope_id=body.security_scope_id,
            name=body.name,
            auto_approve=body.auto_approve,
            thread_id=body.thread_id,
        )

    @app.post("/v1/evolution")
    def evolve(body: EvolutionBody) -> dict[str, Any]:
        return _call(
            agent.propose_evolution,
            target_type=body.target_type,
            baseline_revision=body.baseline_revision,
            candidate_revision=body.candidate_revision,
            metrics=body.metrics,
            tenant_id=body.tenant_id,
            security_scope_id=body.security_scope_id,
            thread_id=body.thread_id,
        )

    @app.get("/v1/threads/{thread_id}")
    def status(
        thread_id: str, tenant_id: str, security_scope_id: str
    ) -> dict[str, Any]:
        return _call(
            agent.status,
            thread_id,
            tenant_id=tenant_id,
            security_scope_id=security_scope_id,
        )

    @app.post("/v1/threads/{thread_id}/resume")
    def resume(
        thread_id: str,
        body: ResumeBody,
        tenant_id: str,
        security_scope_id: str,
    ) -> dict[str, Any]:
        return _call(
            agent.resume,
            thread_id,
            body.value,
            tenant_id=tenant_id,
            security_scope_id=security_scope_id,
        )

    @app.get("/v1/threads/{thread_id}/events")
    def events(
        thread_id: str,
        tenant_id: str,
        security_scope_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return _call(
            agent.events,
            thread_id,
            limit,
            tenant_id=tenant_id,
            security_scope_id=security_scope_id,
        )

    return app


def _call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=422, detail={"error_type": type(exc).__name__}) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail={"error_type": type(exc).__name__}) from exc
