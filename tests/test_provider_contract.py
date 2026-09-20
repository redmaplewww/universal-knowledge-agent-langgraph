from __future__ import annotations

import pytest

from uka_langgraph.application.services import IngestionService
from uka_langgraph.domain.models import (
    ApplicabilityScope,
    ClaimCandidate,
    UnderstandingResult,
)
from uka_langgraph.infrastructure.providers import (
    DeterministicUnderstandingProvider,
    _clustering_result,
    _output_language_instruction,
    _parse_json_object,
    _payload_needs_chinese_repair,
)


def test_provider_json_parser_accepts_fenced_object_and_rejects_array() -> None:
    assert _parse_json_object('```json\n{"ok": true}\n```') == {"ok": True}
    with pytest.raises(ValueError, match="root_not_object"):
        _parse_json_object("[]")
    assert _parse_json_object('{"ok": true}\nmodel note') == {"ok": True}


def test_deterministic_provider_health_is_redacted() -> None:
    health = DeterministicUnderstandingProvider().check_connection()
    assert health == {
        "status": "ok",
        "mode": "deterministic",
        "provider_revision": "deterministic-experience-v2",
        "latency_ms": 0,
    }


def test_chinese_source_enforces_chinese_generated_fields() -> None:
    instruction = _output_language_instruction(
        "这是一段中文经验，其中包含设备代号 KX-17。"
    )
    assert "Simplified Chinese" in instruction
    assert "Do not switch to English" in instruction
    assert _payload_needs_chinese_repair(
        {
            "knowledge_gaps": [
                {
                    "question": "What machine does this undocumented field code refer to?",
                    "reason_unresolved": "The source does not define the operational context.",
                }
            ]
        },
        "这是一段中文材料，但术语定义还不清楚。",
    )
    assert not _payload_needs_chinese_repair(
        {
            "knowledge_gaps": [
                {
                    "question": "KX-17 具体指什么设备？",
                    "reason_unresolved": "原文没有给出设备型号和适用条件。",
                }
            ]
        },
        "这是一段中文材料，但术语定义还不清楚。",
    )


def test_epistemic_gate_generates_chinese_gap_for_chinese_source() -> None:
    service = IngestionService(None, None, None, None)  # type: ignore[arg-type]
    result = UnderstandingResult(
        claims=(
            ClaimCandidate(
                candidate_id="cand-low-support",
                content="设备可能需要特殊校准。",
                title="设备校准",
                confidence=0.4,
                evidence_ids=("ev-1",),
                provider_revision="test",
                source_excerpts=("设备可能需要特殊校准。",),
            ),
        ),
        scopes=(
            ApplicabilityScope(
                scope_id="scope-1",
                domain=("general",),
                domain_ids=("general",),
                domain_labels=("通用",),
            ),
        ),
    )
    gated = service._enforce_epistemic_gate(
        text="设备可能需要特殊校准，但原文没有说明校准对象和具体周期。",
        evidence_id="ev-1",
        result=result,
    )
    assert not gated.claims
    assert gated.gaps
    gap = gated.gaps[0]
    assert "在安全复用这条经验前" in gap.question
    assert "模型生成的综合结论证据不足" in gap.reason_unresolved
    assert all("English" not in value for value in gap.possible_directions)


def test_clustering_contract_filters_unknown_ids_and_weak_schema() -> None:
    result = _clustering_result(
        {
            "clusters": [
                {
                    "cluster_key": "bridge",
                    "name": "跨学科桥接",
                    "summary": "连接材料与软件。",
                    "member_knowledge_ids": ["kn-a", "kn-unknown"],
                    "domain_hypotheses": [
                        {
                            "domain_id": "materials_science",
                            "probability": 0.7,
                            "rationale": "材料结构是核心对象。",
                        },
                        {
                            "domain_id": "not-a-domain",
                            "probability": 0.9,
                        },
                    ],
                    "cross_domain_score": 0.8,
                    "confidence": 0.85,
                }
            ],
            "edges": [
                {
                    "source_id": "kn-a",
                    "relation": "bridges",
                    "target_id": "kn-b",
                    "confidence": 0.9,
                    "rationale": "共享建模方法。",
                    "evidence_knowledge_ids": ["kn-a", "kn-b", "kn-unknown"],
                },
                {
                    "source_id": "kn-a",
                    "relation": "invented_relation",
                    "target_id": "kn-b",
                    "confidence": 1.0,
                },
            ],
        },
        allowed_ids={"kn-a", "kn-b"},
    )
    assert result.clusters[0].member_knowledge_ids == ("kn-a",)
    assert [item.domain_id for item in result.clusters[0].domain_hypotheses] == [
        "materials_science"
    ]
    assert len(result.edges) == 1
    assert result.edges[0].evidence_knowledge_ids == ("kn-a", "kn-b")


def test_clustering_contract_derives_and_accepts_exploration_priority() -> None:
    result = _clustering_result(
        {
            "explorations": [
                {
                    "title": "补齐材料寿命模型",
                    "question": "环境温度如何影响材料寿命预测？",
                    "domain_hypotheses": [
                        {
                            "domain_id": "materials_science",
                            "probability": 0.5,
                        },
                        {
                            "domain_id": "mechanical_engineering",
                            "probability": 0.5,
                        },
                    ],
                    "related_knowledge_ids": ["kn-a", "kn-b"],
                    "missing_information": ["温度范围", "疲劳试验数据"],
                },
                {
                    "title": "显式优先级",
                    "question": "是否需要补充边界条件？",
                    "related_knowledge_ids": ["kn-a"],
                    "priority_score": 0.73,
                },
            ]
        },
        allowed_ids={"kn-a", "kn-b"},
    )
    assert result.explorations[0].priority > 0.5
    assert result.explorations[1].priority == 0.73
