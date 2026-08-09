from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from uka_langgraph.interfaces.api import create_app
from uka_langgraph.interfaces.sdk import UniversalKnowledgeAgent


def test_sdk_ingest_retrieve_and_resume(settings) -> None:
    agent = UniversalKnowledgeAgent(settings)
    interrupted = agent.ingest_text(
        "SDK knowledge requires approval.",
        tenant_id="tenant-a",
        security_scope_id="private",
        thread_id="sdk-review",
    )
    assert interrupted["__interrupt__"][0]["value"]["subject"] == "knowledge_activation"
    before_events = agent.events(
        "sdk-review", tenant_id="tenant-a", security_scope_id="private"
    )
    assert [event["status"] for event in before_events] == ["submitted", "interrupted"]
    approved = agent.resume(
        "sdk-review",
        {"decision": "approve"},
        tenant_id="tenant-a",
        security_scope_id="private",
    )
    assert approved["status"] == "active"
    library = agent.list_knowledge(tenant_id="tenant-a", security_scope_id="private")
    assert library[0]["knowledge_id"] in approved["knowledge_ids"]
    assert library[0]["status"] == "active"
    assert library[0]["content"] == "SDK knowledge requires approval."
    retrieved = agent.retrieve(
        "approval", tenant_id="tenant-a", security_scope_id="private"
    )
    assert retrieved["status"] == "answered"
    assert retrieved["response"]["evidence_pack"]["items"]
    with pytest.raises(LookupError):
        agent.status(
            "sdk-review", tenant_id="tenant-b", security_scope_id="private"
        )


def test_http_api_contract(settings) -> None:
    client = TestClient(create_app(settings))
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["provider_mode"] == "deterministic"

    ingest = client.post(
        "/v1/ingest",
        json={
            "text": "API evidence is scoped to tenant A.",
            "tenant_id": "tenant-a",
            "security_scope_id": "private",
            "auto_approve": True,
        },
    )
    assert ingest.status_code == 200
    assert ingest.json()["status"] == "active"
    thread_id = ingest.json()["thread_id"]
    status = client.get(
        f"/v1/threads/{thread_id}",
        params={"tenant_id": "tenant-a", "security_scope_id": "private"},
    )
    assert status.status_code == 200
    assert status.json()["thread_id"] == thread_id
    events = client.get(
        f"/v1/threads/{thread_id}/events",
        params={"tenant_id": "tenant-a", "security_scope_id": "private"},
    )
    assert events.status_code == 200
    assert events.json()
    denied_status = client.get(
        f"/v1/threads/{thread_id}",
        params={"tenant_id": "tenant-b", "security_scope_id": "private"},
    )
    assert denied_status.status_code == 422
    retrieve = client.post(
        "/v1/retrieve",
        json={
            "query": "evidence",
            "tenant_id": "tenant-a",
            "security_scope_id": "private",
        },
    )
    assert retrieve.status_code == 200
    assert retrieve.json()["status"] == "answered"
    library = client.get(
        "/v1/knowledge",
        params={"tenant_id": "tenant-a", "security_scope_id": "private"},
    )
    assert library.status_code == 200
    assert library.json()[0]["status"] == "active"
    assert library.json()[0]["content"] == "API evidence is scoped to tenant A."
    forbidden_library = client.get(
        "/v1/knowledge",
        params={"tenant_id": "tenant-b", "security_scope_id": "private"},
    )
    assert forbidden_library.status_code == 200
    assert forbidden_library.json() == []
    forbidden = client.post(
        "/v1/retrieve",
        json={
            "query": "evidence",
            "tenant_id": "tenant-b",
            "security_scope_id": "private",
        },
    )
    assert forbidden.json()["status"] == "unknown"


def test_http_api_rejects_extra_fields(settings) -> None:
    client = TestClient(create_app(settings))
    response = client.post(
        "/v1/ingest",
        json={
            "text": "value",
            "tenant_id": "tenant-a",
            "security_scope_id": "private",
            "api_key": "must-not-be-accepted",
        },
    )
    assert response.status_code == 422
