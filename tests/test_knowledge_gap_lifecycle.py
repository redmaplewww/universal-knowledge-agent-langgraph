from __future__ import annotations

from typing import Any

from uka_langgraph.domain.models import (
    ApplicabilityScope,
    ClaimCandidate,
    KnowledgeGapCandidate,
    RiskLevel,
    SecurityScope,
    UnderstandingResult,
    WebSearchBatch,
    WebSearchObservation,
)
from uka_langgraph.interfaces.sdk import UniversalKnowledgeAgent
from uka_langgraph.orchestration.runtime import AgentRuntime


class GapAwareProvider:
    revision = "gap-aware-test-v1"

    def understand(
        self,
        text: str,
        evidence_id: str,
        prior_knowledge: tuple[dict[str, Any], ...] = (),
        prior_gaps: tuple[dict[str, Any], ...] = (),
    ) -> UnderstandingResult:
        scope = ApplicabilityScope(
            scope_id=f"scope-{evidence_id}",
            domain=("software_engineering",),
            domain_ids=("software_engineering",),
            domain_labels=("Software Engineering",),
            tasks=("incident diagnosis",),
            risk=RiskLevel.NORMAL,
            confidence=0.95,
        )
        if "KX-17" in text and "完整定义" not in text:
            return UnderstandingResult(
                claims=(),
                scopes=(scope,),
                gaps=(
                    KnowledgeGapCandidate(
                        gap_id=f"gap-{evidence_id}",
                        question="KX-17 在蓝色窗口后必须回摆是什么意思？",
                        reason_unresolved="KX-17、蓝色窗口和回摆都没有定义。",
                        possible_directions=("查找 KX-17 术语表", "核对同一设备手册"),
                        missing_evidence=("KX-17 定义", "蓝色窗口条件", "回摆结果"),
                        research_queries=("KX-17 蓝色窗口 回摆",),
                        linking_keys=("KX-17", "蓝色窗口", "回摆"),
                        confidence=0.98,
                        source_excerpts=(text,),
                    ),
                ),
            )
        if prior_gaps and "完整定义" in text:
            gap_id = str(prior_gaps[0]["gap_id"])
            return UnderstandingResult(
                claims=(
                    ClaimCandidate(
                        candidate_id=f"cand-{evidence_id}",
                        content=(
                            "KX-17 的蓝色窗口表示校准信号稳定；完成窗口后执行回摆，"
                            "用于验证执行器能返回安全零位。"
                        ),
                        confidence=0.96,
                        evidence_ids=(evidence_id,),
                        provider_revision=self.revision,
                        kind="experience",
                        title="KX-17 蓝色窗口后的回摆验证",
                        context="KX-17 执行器完成校准窗口。",
                        mechanism="稳定窗口确认校准完成，回摆验证安全零位。",
                        action="蓝色窗口结束后执行一次回摆。",
                        outcome="确认执行器能返回安全零位。",
                        rationale="完整定义明确给出了触发条件、动作和可验证结果。",
                        source_excerpts=(text,),
                        resolves_gap_ids=(gap_id,),
                        schema_version=2,
                    ),
                ),
                scopes=(scope,),
            )
        return UnderstandingResult(
            claims=(
                ClaimCandidate(
                    candidate_id=f"cand-{evidence_id}",
                    content=text,
                    confidence=0.95,
                    evidence_ids=(evidence_id,),
                    provider_revision=self.revision,
                    kind="experience",
                    title="明确经验",
                    context="来源给出完整上下文。",
                    action=text,
                    outcome="结果可验证。",
                    rationale="来源直接支持结论。",
                    source_excerpts=(text,),
                    schema_version=2,
                ),
            ),
            scopes=(scope,),
        )

    def reassess_gaps(
        self,
        text: str,
        evidence_id: str,
        gaps: tuple[dict[str, Any], ...],
        research_observations: tuple[dict[str, Any], ...],
        prior_knowledge: tuple[dict[str, Any], ...] = (),
    ) -> UnderstandingResult:
        gap = gaps[0]
        return UnderstandingResult(
            claims=(),
            scopes=(),
            gaps=(
                KnowledgeGapCandidate(
                    gap_id=str(gap["gap_id"]),
                    question=str(gap["question"]),
                    reason_unresolved="搜索结果只出现相似代号，没有 KX-17 的权威定义。",
                    possible_directions=("索取设备术语表", "联系经验提供者确认型号"),
                    missing_evidence=("KX-17 原厂定义", "动作结果记录"),
                    research_queries=("KX-17 device manual",),
                    linking_keys=("KX-17", "蓝色窗口", "回摆"),
                    confidence=0.99,
                    source_excerpts=tuple(gap.get("source_excerpts", [])),
                ),
            ),
        )

    def check_connection(self) -> dict[str, object]:
        return {"status": "ok", "provider_revision": self.revision}


class FakeWebSearch:
    revision = "fake-web-search:v1"

    def search(self, query: str, *, count: int = 5) -> WebSearchBatch:
        return WebSearchBatch(
            query=query,
            status="completed",
            provider_revision=self.revision,
            observations=(
                WebSearchObservation(
                    observation_id="obs-similar-code",
                    query=query,
                    title="KX 系列颜色指示灯概览",
                    url="https://example.test/kx-colors",
                    snippet="KX 系列不同型号使用不同颜色，但页面未列出 KX-17。",
                    media="Example Manual Index",
                    rank=1,
                ),
            ),
        )


class CountingWebSearch(FakeWebSearch):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def search(self, query: str, *, count: int = 5) -> WebSearchBatch:
        self.calls.append(query)
        return super().search(query, count=count)


def _ingest(runtime: AgentRuntime, text: str, thread_id: str, *, approve: bool) -> dict:
    return runtime.invoke(
        intent="ingest",
        tenant_id="tenant-a",
        security_scope_id="private",
        input_refs=[runtime.stage_text(text)],
        payload={"auto_approve": approve},
        thread_id=thread_id,
    )


def test_unresolved_experience_abstains_and_preserves_researchable_gap(settings) -> None:
    provider = GapAwareProvider()
    with AgentRuntime(settings) as runtime:
        runtime.services.ingestion.understanding = provider
        runtime.services.ingestion.research = FakeWebSearch()
        result = _ingest(
            runtime,
            "经验：KX-17 在蓝色窗口后必须回摆，但记录者未解释这些词。",
            "gap-origin",
            approve=True,
        )
        assert result["status"] == "abstained"
        assert result["response"]["answer"] == "unknown"
        gap_id = result["knowledge_gap_ids"][0]
        gap = runtime.services.repository.get_revision(
            SecurityScope("tenant-a", "private"), "knowledge_gap", gap_id
        )
        assert gap is not None
        assert gap.status == "research_exhausted"
        assert gap.payload["research_attempts"][0]["status"] == "completed"
        assert gap.payload["research_evidence_ids"]
        assert not result["candidate_ids"]

        refusal = runtime.services.retrieval.retrieve(
            security=SecurityScope("tenant-a", "private"),
            query="KX-17 蓝色窗口 回摆",
        )
        assert refusal["status"] == "abstained"
        assert refusal["answer"] == "unknown"
        assert refusal["knowledge_gap_ids"] == [gap_id]
        assert refusal["evidence_pack"]["knowledge_gaps"][0][
            "possible_directions"
        ]

        isolated = runtime.services.retrieval.retrieve(
            security=SecurityScope("tenant-b", "private"), query="KX-17"
        )
        assert isolated["status"] == "unknown"

    gaps = UniversalKnowledgeAgent(settings).list_knowledge_gaps(
        tenant_id="tenant-a", security_scope_id="private"
    )
    assert gaps[0]["gap_id"] == gap_id
    assert gaps[0]["research_status"] == "research_exhausted"


def test_confidential_gap_is_preserved_without_external_search(settings) -> None:
    search = CountingWebSearch()
    with AgentRuntime(settings) as runtime:
        runtime.services.ingestion.understanding = GapAwareProvider()
        runtime.services.ingestion.research = search
        result = runtime.invoke(
            intent="ingest",
            tenant_id="tenant-a",
            security_scope_id="private",
            classification="confidential",
            input_refs=[
                runtime.stage_text(
                    "KX-17 is required after the blue window, but none of the terms "
                    "are defined in this confidential record."
                )
            ],
            payload={"auto_approve": True},
            thread_id="confidential-gap",
        )

        assert result["status"] == "abstained"
        assert search.calls == []
        gap = runtime.services.repository.get_revision(
            SecurityScope("tenant-a", "private", "confidential"),
            "knowledge_gap",
            result["knowledge_gap_ids"][0],
        )
        assert gap is not None
        assert gap.status == "research_unavailable"
        assert gap.payload["research_attempts"][0]["status"] == "blocked"
        assert (
            gap.payload["research_attempts"][0]["error_type"]
            == "classification_egress_blocked"
        )


def test_later_evidence_links_then_closes_gap_only_after_activation(settings) -> None:
    provider = GapAwareProvider()
    with AgentRuntime(settings) as runtime:
        runtime.services.ingestion.understanding = provider
        runtime.services.ingestion.research = FakeWebSearch()
        origin = _ingest(
            runtime,
            "经验：KX-17 在蓝色窗口后必须回摆，但记录者未解释这些词。",
            "gap-to-resolve",
            approve=True,
        )
        gap_id = origin["knowledge_gap_ids"][0]
        proposed = _ingest(
            runtime,
            (
                "KX-17 完整定义：蓝色窗口表示校准信号稳定；窗口结束后执行回摆，"
                "验证执行器返回安全零位。"
            ),
            "gap-resolution-proposal",
            approve=False,
        )
        assert proposed["status"] == "accepted"
        assert proposed["__interrupt__"]
        proposal_snapshot = runtime.status(
            "gap-resolution-proposal",
            tenant_id="tenant-a",
            security_scope_id="private",
        )
        candidate = runtime.services.repository.get_revision(
            SecurityScope("tenant-a", "private"),
            "candidate",
            proposal_snapshot["approval_context"]["candidates"][0]["candidate_id"],
        )
        assert candidate is not None
        assert candidate.payload["resolves_gap_ids"] == [gap_id]
        assert runtime.services.repository.get_revision(
            SecurityScope("tenant-a", "private"), "knowledge_gap", gap_id
        ).status == "research_exhausted"

        rejected = runtime.resume(
            thread_id="gap-resolution-proposal",
            value={"decision": "reject"},
            tenant_id="tenant-a",
            security_scope_id="private",
        )
        assert rejected["status"] == "held"
        assert runtime.services.repository.get_revision(
            SecurityScope("tenant-a", "private"), "knowledge_gap", gap_id
        ).status == "research_exhausted"

        approved = _ingest(
            runtime,
            (
                "KX-17 完整定义：蓝色窗口表示校准信号稳定；窗口结束后执行回摆，"
                "验证执行器返回安全零位。"
            ),
            "gap-resolution-approved",
            approve=True,
        )
        assert approved["status"] == "active"
        assert approved["response"]["resolved_knowledge_gap_ids"] == [gap_id]
        resolved = runtime.services.repository.get_revision(
            SecurityScope("tenant-a", "private"), "knowledge_gap", gap_id
        )
        assert resolved is not None
        assert resolved.status == "resolved"
        assert resolved.revision == 2
        assert resolved.payload["resolved_by_knowledge_ids"] == approved[
            "knowledge_ids"
        ]

        answer = runtime.services.retrieval.retrieve(
            security=SecurityScope("tenant-a", "private"), query="KX-17"
        )
        assert answer["status"] == "answered"
        assert gap_id not in answer.get("knowledge_gap_ids", [])

    assert UniversalKnowledgeAgent(settings).list_knowledge_gaps(
        tenant_id="tenant-a", security_scope_id="private"
    ) == []


def test_manual_supplement_targets_exact_gap_before_model_understanding(settings) -> None:
    provider = GapAwareProvider()
    with AgentRuntime(settings) as runtime:
        runtime.services.ingestion.understanding = provider
        runtime.services.ingestion.research = FakeWebSearch()
        origin = _ingest(
            runtime,
            "经验：KX-17 在蓝色窗口后必须回摆，但记录者未解释这些词。",
            "manual-gap-origin",
            approve=True,
        )
        gap_id = origin["knowledge_gap_ids"][0]
        supplement = runtime.invoke(
            intent="ingest",
            tenant_id="tenant-a",
            security_scope_id="private",
            input_refs=[
                runtime.stage_text(
                    "完整定义：蓝色窗口表示校准信号稳定，结束后执行回摆，"
                    "验证执行器能回到安全零位。"
                )
            ],
            payload={
                "auto_approve": False,
                "target_gap_ids": [gap_id],
                "supplement_mode": "human_evidence",
            },
            thread_id="manual-gap-supplement",
        )

        assert supplement["__interrupt__"], supplement
        approval_candidates = supplement["approval_context"]["candidates"]
        assert approval_candidates, supplement["approval_context"]
        candidate_id = approval_candidates[0]["candidate_id"]
        candidate = runtime.services.repository.get_revision(
            SecurityScope("tenant-a", "private"), "candidate", candidate_id
        )
        assert candidate is not None
        assert candidate.payload["resolves_gap_ids"] == [gap_id]
        assert runtime.services.repository.get_revision(
            SecurityScope("tenant-a", "private"), "knowledge_gap", gap_id
        ).status == "research_exhausted"

        approved = runtime.resume(
            thread_id="manual-gap-supplement",
            value={"decision": "approve"},
            tenant_id="tenant-a",
            security_scope_id="private",
        )
        assert approved["response"]["resolved_knowledge_gap_ids"] == [gap_id]


def test_supported_experience_is_not_falsely_refused(settings) -> None:
    with AgentRuntime(settings) as runtime:
        runtime.services.ingestion.understanding = GapAwareProvider()
        runtime.services.ingestion.research = FakeWebSearch()
        result = _ingest(
            runtime,
            "DEPLOY-9：部署前运行回归测试，全部通过后再发布。",
            "supported-control",
            approve=True,
        )
        assert result["status"] == "active"
        assert result["knowledge_gap_ids"] == []
        answer = runtime.services.retrieval.retrieve(
            security=SecurityScope("tenant-a", "private"), query="DEPLOY-9"
        )
        assert answer["status"] == "answered"
