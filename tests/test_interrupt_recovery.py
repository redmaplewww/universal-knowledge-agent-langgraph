from __future__ import annotations

from uka_langgraph.orchestration.runtime import AgentRuntime


def test_interrupt_survives_runtime_restart_and_resumes_once(settings) -> None:
    with AgentRuntime(settings) as runtime:
        object_ref = runtime.stage_text("人工审批后的知识才可激活。")
        interrupted = runtime.invoke(
            intent="ingest",
            tenant_id="tenant-a",
            security_scope_id="private",
            input_refs=[object_ref],
            payload={"auto_approve": False},
            request_id="review-request",
            thread_id="review-thread",
        )
        assert interrupted["__interrupt__"][0].value["subject"] == "knowledge_activation"
        assert runtime.services.repository.count("knowledge") == 0

    with AgentRuntime(settings) as reopened:
        snapshot = reopened.status(
            "review-thread", tenant_id="tenant-a", security_scope_id="private"
        )
        assert snapshot["interrupts"][0]["value"]["subject"] == "knowledge_activation"
        resumed = reopened.resume(
            thread_id="review-thread",
            value={"decision": "approve"},
            tenant_id="tenant-a",
            security_scope_id="private",
        )
        assert resumed["status"] == "active"
        assert reopened.services.repository.count("knowledge") == 1

    with AgentRuntime(settings) as reopened_again:
        assert reopened_again.services.repository.count("knowledge") == 1


def test_rejected_review_keeps_fail_closed(settings) -> None:
    with AgentRuntime(settings) as runtime:
        ref = runtime.stage_text("This claim needs review.")
        runtime.invoke(
            intent="ingest",
            tenant_id="tenant-a",
            security_scope_id="private",
            input_refs=[ref],
            thread_id="reject-thread",
        )
    with AgentRuntime(settings) as runtime:
        rejected = runtime.resume(
            thread_id="reject-thread",
            value={"decision": "reject"},
            tenant_id="tenant-a",
            security_scope_id="private",
        )
        assert rejected["status"] == "held"
        assert runtime.services.repository.count("knowledge") == 0
