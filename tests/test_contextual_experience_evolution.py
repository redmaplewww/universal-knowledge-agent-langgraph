from __future__ import annotations

from typing import Any

from uka_langgraph.domain.models import (
    ApplicabilityScope,
    ClaimCandidate,
    LogicalRelation,
    RiskLevel,
    SecurityScope,
    UnderstandingResult,
)
from uka_langgraph.interfaces.sdk import UniversalKnowledgeAgent
from uka_langgraph.orchestration.runtime import AgentRuntime


class ContextualExperienceProvider:
    revision = "contextual-experience-test-v2"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def understand(
        self,
        text: str,
        evidence_id: str,
        prior_knowledge: tuple[dict[str, Any], ...] = (),
    ) -> UnderstandingResult:
        self.calls.append(
            {"text": text, "prior_knowledge": prior_knowledge, "evidence_id": evidence_id}
        )
        lines = tuple(line.strip() for line in text.splitlines() if line.strip())
        prior_ids = tuple(
            str(item["knowledge_id"])
            for item in prior_knowledge
            if item.get("knowledge_id")
        )
        refined = bool(prior_ids)
        content = (
            "当 Agent 修改从建议升级为 AI 沙箱执行时，必须把权限边界、回归评估和人工批准作为同一治理链；"
            "只有门禁持续稳定后才能扩大自治范围，避免把能力提升误当成无条件接管。"
        )
        if refined:
            content += "后续材料将失败回滚纳入同一闭环，因此该经验是在既有治理知识上的修正。"
        return UnderstandingResult(
            claims=(
                ClaimCandidate(
                    candidate_id=f"cand-{evidence_id}",
                    content=content,
                    confidence=0.95,
                    evidence_ids=(evidence_id,),
                    provider_revision=self.revision,
                    kind="experience",
                    title="AI 接管 Agent 修改的受控升级条件",
                    context="团队正在把 AI 从建议者逐步升级为可修改 Agent 的执行者。",
                    problem="孤立地描述 AI 接管会掩盖权限扩大所依赖的安全前提。",
                    mechanism="自治范围随评估门禁的稳定性逐级扩大，并由沙箱隔离潜在副作用。",
                    action="先验证回归与权限边界，再经人工批准扩大 AI 的修改权限。",
                    outcome="AI 能利用既有经验优化后续修改，同时保持可回滚和可审计。",
                    rationale="修改能力与治理门禁必须共同演进，否则一次能力升级会放大错误。",
                    caveats=("不得在生产环境跳过人工批准。",),
                    source_excerpts=lines,
                    logical_relations=(
                        LogicalRelation(
                            source="评估门禁持续稳定",
                            relation="condition",
                            target="扩大 AI 自治范围",
                        ),
                        LogicalRelation(
                            source="沙箱执行与回归评估",
                            relation="enables",
                            target="可回滚的 Agent 修改",
                        ),
                    ),
                    derived_from_knowledge_ids=prior_ids[:1],
                    knowledge_delta="refines" if refined else "new",
                    schema_version=2,
                ),
            ),
            scopes=(
                ApplicabilityScope(
                    scope_id=f"scope-{evidence_id}",
                    domain=("software_engineering",),
                    domain_ids=("software_engineering",),
                    domain_labels=("Agent Engineering",),
                    subjects=("agent governance",),
                    tasks=("agent modification",),
                    risk=RiskLevel.NORMAL,
                    confidence=0.95,
                ),
            ),
        )

    def check_connection(self) -> dict[str, object]:
        return {"status": "ok", "provider_revision": self.revision}


def _ingest(runtime: AgentRuntime, text: str, thread_id: str) -> dict[str, Any]:
    return runtime.invoke(
        intent="ingest",
        tenant_id="tenant-a",
        security_scope_id="private",
        input_refs=[runtime.stage_text(text)],
        payload={"auto_approve": True},
        thread_id=thread_id,
    )


def test_document_logic_is_synthesized_into_one_traceable_experience(settings) -> None:
    provider = ContextualExperienceProvider()
    source = (
        "AGENT-GOV-42：AI 最初只负责给 Agent 修改建议。\n"
        "评估门禁连续稳定后，AI 才能在沙箱中接管 Agent 修改。\n"
        "所有变更仍必须通过回归测试和人工批准，防止自治升级放大错误。"
    )
    with AgentRuntime(settings) as runtime:
        runtime.services.ingestion.understanding = provider
        result = _ingest(runtime, source, "contextual-source")
        assert result["status"] == "active"
        assert len(provider.calls) == 1
        assert provider.calls[0]["text"] == source
        assert len(result["fragment_ids"]) == 3
        assert len(result["knowledge_ids"]) == 1
        knowledge = runtime.services.repository.get_active_revision(
            SecurityScope("tenant-a", "private"),
            "knowledge",
            result["knowledge_ids"][0],
        )
        assert knowledge is not None
        assert knowledge.payload["title"] == "AI 接管 Agent 修改的受控升级条件"
        assert "权限边界" in knowledge.payload["content"]
        assert "建议者" in knowledge.payload["context"]
        assert "评估门禁" in knowledge.payload["mechanism"]
        assert len(knowledge.payload["logical_relations"]) == 2
        assert len(knowledge.evidence_ids) == 3
        assert knowledge.payload["content"] != "AI 才能在沙箱中接管 Agent 修改。"

    library = UniversalKnowledgeAgent(settings).list_knowledge(
        tenant_id="tenant-a", security_scope_id="private"
    )
    assert library[0]["evidence_integrity"] == "verified"
    assert len(library[0]["source_evidence"]) == 3
    assert any(
        "回归测试和人工批准" in item["excerpt"]
        for item in library[0]["source_evidence"]
    )


def test_accumulated_knowledge_guides_a_governed_evolution_candidate(settings) -> None:
    provider = ContextualExperienceProvider()
    first_source = (
        "AGENT-GOV-42：AI 最初只负责建议。\n"
        "门禁稳定后才允许在沙箱中修改 Agent。"
    )
    second_source = (
        "AGENT-GOV-42：沙箱修改失败时必须自动回滚。\n"
        "回滚证据应加入下一轮评估，之后再决定是否扩大权限。"
    )
    with AgentRuntime(settings) as runtime:
        runtime.services.ingestion.understanding = provider
        first = _ingest(runtime, first_source, "learning-baseline")
        second = _ingest(runtime, second_source, "learning-refinement")
        baseline_id = first["knowledge_ids"][0]
        refined = runtime.services.repository.get_active_revision(
            SecurityScope("tenant-a", "private"),
            "knowledge",
            second["knowledge_ids"][0],
        )
        assert refined is not None
        assert provider.calls[1]["prior_knowledge"][0]["knowledge_id"] == baseline_id
        assert refined.payload["learning"]["derived_from_knowledge_ids"] == [baseline_id]
        assert refined.payload["learning"]["knowledge_delta"] == "refines"
        evolution_id = refined.payload["learning"]["evolution_candidate_id"]
        evolution = runtime.services.repository.get_revision(
            SecurityScope("tenant-a", "private"), "evolution", evolution_id
        )
        assert evolution is not None
        assert evolution.status == "candidate"
        assert evolution.payload["automatic_activation"] is False
        assert evolution.payload["required_gates"] == [
            "offline",
            "shadow",
            "canary",
            "human",
        ]
        assert (
            runtime.services.repository.get_active_revision(
                SecurityScope("tenant-a", "private"), "evolution", evolution_id
            )
            is None
        )
