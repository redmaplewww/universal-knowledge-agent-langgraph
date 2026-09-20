from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from typing import Any


def request_json(
    url: str, *, method: str = "GET", payload: dict[str, Any] | None = None
) -> Any:
    data = (
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if payload is not None
        else None
    )
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Real HTTP/LLM smoke for Chinese gap language and manual supplementation."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8877")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    suffix = str(int(time.time()))
    tenant_id = f"manual-gap-zh-{suffix}"
    security_scope_id = "private"
    origin_thread = f"zh-gap-origin-{suffix}"
    supplement_thread = f"zh-gap-supplement-{suffix}"

    origin = request_json(
        f"{base_url}/v1/ingest",
        method="POST",
        payload={
            "text": (
                "中文现场记录 ZH-GAP-81：完成‘青铜窗’后要执行‘回声归零’，"
                "但记录没有说明设备型号，也没有解释两个术语的定义，因此当前无法判断"
                "这条经验的真实含义和适用条件。"
            ),
            "tenant_id": tenant_id,
            "security_scope_id": security_scope_id,
            "actor_id": "language-gate",
            "classification": "internal",
            "auto_approve": False,
            "thread_id": origin_thread,
        },
    )
    gap_ids = list(origin.get("knowledge_gap_ids", []))
    if origin.get("status") != "abstained" or not gap_ids:
        raise AssertionError(f"origin did not preserve a gap: {origin.get('status')}")
    gap_id = str(gap_ids[0])
    query = urllib.parse.urlencode(
        {
            "tenant_id": tenant_id,
            "security_scope_id": security_scope_id,
            "limit": 10,
        }
    )
    open_gaps = request_json(f"{base_url}/v1/knowledge-gaps?{query}")
    target = next(gap for gap in open_gaps if gap.get("gap_id") == gap_id)
    language_fields = [
        str(target.get("question", "")),
        str(target.get("reason_unresolved", "")),
        *[str(value) for value in target.get("missing_evidence", [])],
        *[str(value) for value in target.get("possible_directions", [])],
    ]
    if not all(any("\u4e00" <= char <= "\u9fff" for char in value) for value in language_fields):
        raise AssertionError("a generated gap field did not remain Chinese")

    proposed = request_json(
        f"{base_url}/v1/knowledge-gaps/{urllib.parse.quote(gap_id)}/supplements",
        method="POST",
        payload={
            "evidence_text": (
                "设备手册 ZH-81 第 4.2 节明确规定：‘青铜窗’表示校准信号连续 30 秒"
                "处于允许偏差内；窗口结束后执行‘回声归零’，即驱动执行器返回机械零位"
                "并记录位置误差。只有回零误差不超过 0.2 毫米时，校准才算通过。"
            ),
            "source_note": "设备手册 ZH-81 第 4.2 节，人工录入的验证样例",
            "tenant_id": tenant_id,
            "security_scope_id": security_scope_id,
            "actor_id": "knowledge-curator",
            "classification": "internal",
            "thread_id": supplement_thread,
        },
    )
    candidates = proposed.get("approval_context", {}).get("candidates", [])
    if not candidates:
        raise AssertionError(
            f"manual supplement did not produce a candidate: {proposed.get('status')}"
        )
    candidate = candidates[0]
    if gap_id not in candidate.get("resolves_gap_ids", []):
        raise AssertionError("manual supplement did not link the exact target gap")
    if not any("\u4e00" <= char <= "\u9fff" for char in str(candidate.get("content", ""))):
        raise AssertionError("supplement candidate was not generated in Chinese")

    resume_query = urllib.parse.urlencode(
        {"tenant_id": tenant_id, "security_scope_id": security_scope_id}
    )
    approved = request_json(
        f"{base_url}/v1/threads/{supplement_thread}/resume?{resume_query}",
        method="POST",
        payload={"value": {"decision": "approve"}},
    )
    resolved_ids = approved.get("response", {}).get(
        "resolved_knowledge_gap_ids", []
    )
    remaining = request_json(f"{base_url}/v1/knowledge-gaps?{query}")
    if gap_id not in resolved_ids or remaining:
        raise AssertionError("approved supplement did not close only the target gap")

    print(
        json.dumps(
            {
                "status": "passed",
                "provider_boundary": "real-http-llm",
                "tenant_id": tenant_id,
                "origin_status": origin.get("status"),
                "gap_id": gap_id,
                "gap_question": target.get("question"),
                "candidate_title": candidate.get("title"),
                "resolves_gap_ids": candidate.get("resolves_gap_ids"),
                "approval_status": approved.get("status"),
                "remaining_open_gaps": len(remaining),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
