from __future__ import annotations

import pytest

from uka_langgraph.infrastructure.providers import (
    DeterministicUnderstandingProvider,
    _parse_json_object,
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
        "provider_revision": "deterministic-v1",
        "latency_ms": 0,
    }
