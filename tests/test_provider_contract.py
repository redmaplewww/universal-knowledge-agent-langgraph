from __future__ import annotations

import pytest

from uka_langgraph.infrastructure.providers import (
    DeterministicUnderstandingProvider,
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
