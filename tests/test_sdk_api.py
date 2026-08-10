from __future__ import annotations

import json

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
    approval = interrupted["approval_context"]
    assert approval["subject"] == "knowledge_activation"
    assert approval["decision_effects"]["approve"] == "compile_and_activate_knowledge"
    assert approval["candidates"][0]["content"] == "SDK knowledge requires approval."
    assert approval["candidates"][0]["scope_ids"]
    assert approval["scopes"]
    assert approval["evidence"][0]["excerpt"] == "SDK knowledge requires approval."
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

    review = client.post(
        "/v1/ingest",
        json={
            "text": "Approval preview evidence remains visible to the reviewer.",
            "tenant_id": "tenant-a",
            "security_scope_id": "private",
            "auto_approve": False,
            "thread_id": "api-approval-preview",
        },
    )
    assert review.status_code == 200
    review_payload = review.json()
    assert review_payload["approval_context"]["candidates"][0]["content"].startswith(
        "Approval preview evidence"
    )
    review_status = client.get(
        "/v1/threads/api-approval-preview",
        params={"tenant_id": "tenant-a", "security_scope_id": "private"},
    )
    assert review_status.status_code == 200
    assert review_status.json()["approval_context"]["evidence"][0]["excerpt"].startswith(
        "Approval preview evidence"
    )
    assert "Approval preview evidence" not in json.dumps(
        review_status.json()["values"]
    )

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

    gap_origin = client.post(
        "/v1/ingest",
        json={
            "text": "这条设备经验含义不明，适用条件仍然未知。",
            "tenant_id": "tenant-a",
            "security_scope_id": "private",
            "auto_approve": True,
        },
    )
    assert gap_origin.status_code == 200
    assert gap_origin.json()["status"] == "abstained"
    gap_id = gap_origin.json()["knowledge_gap_ids"][0]
    supplement = client.post(
        f"/v1/knowledge-gaps/{gap_id}/supplements",
        json={
            "evidence_text": "设备手册明确给出了术语定义、触发条件和可核验结果。",
            "source_note": "设备手册第 4.2 节",
            "tenant_id": "tenant-a",
            "security_scope_id": "private",
            "actor_id": "knowledge-curator",
        },
    )
    assert supplement.status_code == 200
    assert supplement.json()["__interrupt__"]
    assert supplement.json()["approval_context"]["evidence"][0]["excerpt"].startswith(
        "设备手册明确给出了"
    )

    missing_gap = client.post(
        "/v1/knowledge-gaps/gap-does-not-exist/supplements",
        json={
            "evidence_text": "不会被接受的补充。",
            "tenant_id": "tenant-a",
            "security_scope_id": "private",
        },
    )
    assert missing_gap.status_code == 422


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
