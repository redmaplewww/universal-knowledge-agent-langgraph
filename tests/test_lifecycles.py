from __future__ import annotations

from uka_langgraph.application.services import utc_now
from uka_langgraph.domain.models import DomainRevision
from uka_langgraph.orchestration.runtime import AgentRuntime


def _active_knowledge(runtime: AgentRuntime) -> str:
    ref = runtime.stage_text("Step 1: validate input. Step 2: produce an evidence-backed result.")
    result = runtime.invoke(
        intent="ingest",
        tenant_id="tenant-a",
        security_scope_id="private",
        input_refs=[ref],
        payload={"auto_approve": True},
    )
    return result["knowledge_ids"][0]


def test_correction_creates_new_revision_without_overwriting_history(settings) -> None:
    with AgentRuntime(settings) as runtime:
        knowledge_id = _active_knowledge(runtime)
        replacement_ref = runtime.stage_text(
            "Step 1: validate and authorize input. Step 2: produce cited output."
        )
        corrected = runtime.invoke(
            intent="correct",
            tenant_id="tenant-a",
            security_scope_id="private",
            payload={
                "target_id": knowledge_id,
                "expected_revision": 1,
                "replacement_ref": replacement_ref,
                "auto_approve": True,
            },
        )
        assert corrected["status"] == "active"
        first = runtime.services.repository.get_revision(
            corrected_security(), "knowledge", knowledge_id, 1
        )
        second = runtime.services.repository.get_revision(
            corrected_security(), "knowledge", knowledge_id, 2
        )
        assert first is not None and second is not None
        assert first.payload["content"] != second.payload["content"]
        assert second.parent_revision == 1
        assert corrected["impact_ids"]
        assert corrected["evaluation_ids"]
        assert runtime.services.repository.count("impact") == 1
        assert runtime.services.repository.count("regression") == 1

        retrieved = runtime.invoke(
            intent="retrieve",
            tenant_id="tenant-a",
            security_scope_id="private",
            payload={"query": "authorize"},
        )
        assert retrieved["knowledge_ids"] == [knowledge_id]


def corrected_security():
    from uka_langgraph.domain.models import SecurityScope

    return SecurityScope("tenant-a", "private")


def _seed_evolution_evaluations(runtime: AgentRuntime) -> dict[str, str]:
    evidence_ref = runtime.stage_text("Independent immutable evolution evaluation report.")
    preserved = runtime.services.ingestion.preserve(
        request_id="evolution-evidence",
        input_refs=[evidence_ref],
        security=corrected_security(),
        source_type="evaluation_report",
    )
    ids: dict[str, str] = {}
    for stage in ("offline", "shadow", "canary"):
        evaluation_id = f"evaluation-{stage}"
        evaluation = DomainRevision(
            object_type="evaluation",
            object_id=evaluation_id,
            revision=1,
            status="passed",
            security=corrected_security(),
            payload={
                "stage": stage,
                "target_type": "retrieval_policy",
                "baseline_revision": "v1",
                "candidate_revision": "v2",
                "passed": True,
                "safety_regression": False,
            },
            evidence_ids=tuple(preserved["evidence_ids"]),
            created_at=utc_now(),
        )
        runtime.services.repository.put_revision(evaluation, f"op-{evaluation_id}")
        ids[stage] = evaluation_id
    return ids


def test_skill_and_evolution_require_governed_activation(settings) -> None:
    with AgentRuntime(settings) as runtime:
        knowledge_id = _active_knowledge(runtime)
        skill = runtime.invoke(
            intent="build_skill",
            tenant_id="tenant-a",
            security_scope_id="private",
            payload={"knowledge_id": knowledge_id, "auto_approve": True},
        )
        assert skill["status"] == "active"
        assert skill["skill_ids"]
        assert skill["receipt_ids"]
        skill_revision = runtime.services.repository.get_revision(
            corrected_security(), "skill", skill["skill_ids"][0]
        )
        assert skill_revision is not None
        assert runtime.services.objects.read_bytes(
            skill_revision.payload["skill_markdown_ref"]
        ).startswith(b"# ")

        evolution = runtime.invoke(
            intent="evolve",
            tenant_id="tenant-a",
            security_scope_id="private",
            payload={
                "target_type": "retrieval_policy",
                "baseline_revision": "v1",
                "candidate_revision": "v2",
                "metrics": {
                    "evaluation_ids": _seed_evolution_evaluations(runtime),
                },
            },
            thread_id="evolution-thread",
        )
        assert evolution["__interrupt__"][0].value["subject"] == "evolution_candidate_canary"

    with AgentRuntime(settings) as runtime:
        activated = runtime.resume(
            thread_id="evolution-thread",
            value={"decision": "approve"},
            tenant_id="tenant-a",
            security_scope_id="private",
        )
        assert activated["status"] == "active"
        assert activated["receipt_ids"]
        assert "evaluation-shadow" in activated["evaluation_ids"]
        assert "evaluation-canary" in activated["evaluation_ids"]


def test_safety_regression_blocks_evolution_without_interrupt(settings) -> None:
    with AgentRuntime(settings) as runtime:
        result = runtime.invoke(
            intent="evolve",
            tenant_id="tenant-a",
            security_scope_id="private",
            payload={
                "target_type": "prompt",
                "baseline_revision": "v1",
                "candidate_revision": "v2",
                "metrics": {"passed": True, "safety_regression": True},
            },
        )
        assert result["status"] == "rejected"
        assert "__interrupt__" not in result
