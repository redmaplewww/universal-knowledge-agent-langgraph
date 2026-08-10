from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

AMBIGUOUS_CASES = (
    {
        "case_id": "industrial-vxq-731",
        "domain": "industrial_calibration",
        "query": "VXQ-731",
        "text": (
            "Field note VXQ-731: after the mirror turns grey and the second chime, "
            "set the nap parameter back to 7 to prevent a fold shadow. The note does "
            "not identify the machine or software and does not define mirror, nap "
            "parameter, or fold shadow."
        ),
    },
    {
        "case_id": "oral-history-qelm-204",
        "domain": "oral_history",
        "query": "QELM-204",
        "text": (
            "Oral-history card QELM-204 says that when the third reed falls silent, "
            "the keeper should reverse the pale knot before dawn. The card does not "
            "name a community, language, collection, date, speaker, or define reed, "
            "keeper, or pale knot."
        ),
    },
    {
        "case_id": "agronomy-agr-zeta-91",
        "domain": "agronomy",
        "query": "AGR-ZETA-91",
        "text": (
            "Trial marker AGR-ZETA-91 records: at the amber edge, move the root score "
            "down by two before the quiet pass or silver lodging will follow. The note "
            "does not identify a crop, instrument, trial, unit, root score, quiet pass, "
            "or silver lodging."
        ),
    },
)

SUPPORTED_CASE = {
    "case_id": "software-deploy-44",
    "domain": "software_engineering",
    "query": "DEPLOY-44",
    "text": (
        "RUNBOOK DEPLOY-44 defines a rollback trigger for the payments API. During a "
        "canary rollout, if the five-minute error rate exceeds 2 percent, stop the "
        "rollout, restore the last verified version, and attach the error-rate chart "
        "and deployment identifier to the incident record. The expected result is a "
        "return to the verified baseline before rollout resumes."
    ),
}

RESOLUTION_CASE = {
    "case_id": "industrial-vxq-731-resolution",
    "domain": "industrial_calibration",
    "query": "VXQ-731",
    "text": (
        "VXQ-731 is the calibration procedure for the ArcFold T7 textile scanner. "
        "In this procedure, mirror means the optical alignment preview, grey means "
        "alignment lock, second chime means two completed lock confirmations, nap "
        "parameter is the fabric-direction compensation setting, and fold shadow is "
        "a duplicated edge artifact. After grey lock and the second chime, set nap "
        "compensation to 7; the verification image must contain one edge and no "
        "duplicated shadow."
    ),
}


def request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    timeout: float = 240.0,
) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP_{exc.code}") from exc


def security_body() -> dict[str, str]:
    return {
        "tenant_id": "aawo-gap-gate",
        "security_scope_id": "public",
        "actor_id": "aawo-tester",
    }


def ingest(base_url: str, case: dict[str, str]) -> dict[str, Any]:
    return request_json(
        base_url,
        "/v1/ingest",
        method="POST",
        body={
            **security_body(),
            "text": case["text"],
            "classification": "public",
            "auto_approve": True,
            "thread_id": f"aawo-{case['case_id']}",
            "request_id": f"aawo-{case['case_id']}",
        },
    )


def thread_status(base_url: str, thread_id: str) -> dict[str, Any]:
    params = urllib.parse.urlencode(
        {"tenant_id": "aawo-gap-gate", "security_scope_id": "public"}
    )
    return request_json(
        base_url, f"/v1/threads/{urllib.parse.quote(thread_id)}?{params}"
    )


def resume_approval(base_url: str, thread_id: str) -> dict[str, Any]:
    params = urllib.parse.urlencode(
        {"tenant_id": "aawo-gap-gate", "security_scope_id": "public"}
    )
    return request_json(
        base_url,
        f"/v1/threads/{urllib.parse.quote(thread_id)}/resume?{params}",
        method="POST",
        body={"value": {"decision": "approve"}},
    )


def ingest_with_governance(
    base_url: str, case: dict[str, str], *, allow_approval: bool
) -> dict[str, Any]:
    result = ingest(base_url, case)
    if not result.get("__interrupt__"):
        return result
    status = thread_status(base_url, f"aawo-{case['case_id']}")
    review = status.get("approval_context") or {}
    candidates = review.get("candidates") or []
    scopes = review.get("scopes") or []
    eligible = bool(candidates) and all(
        float(candidate.get("confidence", 0.0)) >= 0.75 for candidate in candidates
    )
    eligible = eligible and all(
        "unknown" not in (scope.get("domain_ids") or scope.get("domain") or [])
        for scope in scopes
    )
    if allow_approval and eligible:
        return resume_approval(base_url, f"aawo-{case['case_id']}")
    return {
        **result,
        "approval_context": review,
        "candidate_ids": [
            candidate.get("candidate_id") for candidate in candidates
        ],
        "knowledge_gap_ids": [
            gap.get("gap_id") for gap in review.get("knowledge_gaps", [])
        ],
    }


def retrieve(base_url: str, query: str, *, tenant_id: str = "aawo-gap-gate") -> dict:
    result = request_json(
        base_url,
        "/v1/retrieve",
        method="POST",
        body={
            "tenant_id": tenant_id,
            "security_scope_id": "public",
            "actor_id": "aawo-tester",
            "query": query,
            "query_scope": {},
            "limit": 5,
        },
    )
    return result.get("response", result)


def list_gaps(base_url: str, *, tenant_id: str = "aawo-gap-gate") -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "tenant_id": tenant_id,
            "security_scope_id": "public",
            "limit": 100,
        }
    )
    value = request_json(base_url, f"/v1/knowledge-gaps?{params}")
    return value if isinstance(value, list) else []


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8884")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    def check(case_id: str, condition: bool, expected: str, observed: Any) -> None:
        checks.append(
            {
                "case_id": case_id,
                "status": "passed" if condition else "failed",
                "expected": expected,
                "observed": observed,
            }
        )

    health = request_json(args.base_url, "/health?connect=true")
    openapi = request_json(args.base_url, "/openapi.json")
    safe = health.get("safe_status", health)
    ledger.append(
        {
            "event": "contract_discovery",
            "provider": safe.get("llm_model"),
            "graph_version": safe.get("graph_version"),
            "web_research_enabled": safe.get("web_research_enabled"),
            "routes": sorted(openapi.get("paths", {}).keys()),
            "side_effect_gate": {
                "allowed": [
                    "isolated SQLite state",
                    "content-addressed test evidence",
                    "bounded LLM calls",
                    "bounded web search queries",
                ],
                "forbidden": ["external writes", "account changes", "production state"],
            },
        }
    )
    check(
        "provider-contract",
        safe.get("provider_mode") == "llm"
        and health.get("provider_health", {}).get("status") == "ok",
        "real LLM provider connection is healthy",
        {
            "provider_mode": safe.get("provider_mode"),
            "model": safe.get("llm_model"),
            "health": health.get("provider_health", {}).get("status"),
        },
    )

    ambiguous_results: dict[str, dict[str, Any]] = {}
    for case in AMBIGUOUS_CASES:
        result = ingest_with_governance(
            args.base_url, case, allow_approval=False
        )
        gaps = list_gaps(args.base_url)
        gap_ids = result.get("knowledge_gap_ids", [])
        matching_gaps = [gap for gap in gaps if gap.get("gap_id") in gap_ids]
        ambiguous_results[case["case_id"]] = {
            "status": result.get("status"),
            "gap_ids": gap_ids,
            "candidate_ids": result.get("candidate_ids", []),
            "model_feedback": [
                {
                    "gap_id": gap.get("gap_id"),
                    "question": gap.get("question"),
                    "reason_unresolved": gap.get("reason_unresolved"),
                    "possible_directions": gap.get("possible_directions"),
                    "missing_evidence": gap.get("missing_evidence"),
                    "linking_keys": gap.get("linking_keys"),
                    "research_status": gap.get("research_status"),
                    "research_attempts": [
                        {
                            "status": attempt.get("status"),
                            "provider_revision": attempt.get("provider_revision"),
                            "result_count": attempt.get("result_count"),
                        }
                        for attempt in gap.get("research_attempts", [])
                    ],
                }
                for gap in matching_gaps
            ],
        }
        ledger.append(
            {
                "event": "ambiguous_ingest",
                "case_id": case["case_id"],
                "domain": case["domain"],
                **ambiguous_results[case["case_id"]],
            }
        )
        check(
            f"{case['case_id']}:refusal",
            result.get("status") == "abstained"
            and bool(gap_ids)
            and not result.get("candidate_ids"),
            "abstained with at least one gap and zero candidates",
            ambiguous_results[case["case_id"]],
        )
        check(
            f"{case['case_id']}:research",
            bool(matching_gaps)
            and all(
                gap.get("research_status") == "research_exhausted"
                and gap.get("research_attempts")
                and any(
                    attempt.get("status") in {"completed", "no_results"}
                    for attempt in gap.get("research_attempts", [])
                )
                for gap in matching_gaps
            ),
            "real web research completed but gap remained unresolved",
            [gap.get("research_status") for gap in matching_gaps],
        )
        refusal = retrieve(args.base_url, case["query"])
        ledger.append(
            {
                "event": "gap_retrieval",
                "case_id": case["case_id"],
                "status": refusal.get("status"),
                "gap_ids": refusal.get("knowledge_gap_ids", []),
                "unknowns": refusal.get("evidence_pack", {}).get("unknowns", []),
            }
        )
        check(
            f"{case['case_id']}:retrieval",
            refusal.get("status") == "abstained"
            and bool(refusal.get("knowledge_gap_ids")),
            "query returns abstained and the linked open gap",
            {
                "status": refusal.get("status"),
                "gap_ids": refusal.get("knowledge_gap_ids", []),
            },
        )

    supported = ingest_with_governance(
        args.base_url, SUPPORTED_CASE, allow_approval=True
    )
    supported_retrieval = retrieve(args.base_url, SUPPORTED_CASE["query"])
    ledger.append(
        {
            "event": "supported_control",
            "case_id": SUPPORTED_CASE["case_id"],
            "domain": SUPPORTED_CASE["domain"],
            "ingest_status": supported.get("status"),
            "gap_ids": supported.get("knowledge_gap_ids", []),
            "knowledge_ids": supported.get("knowledge_ids", []),
            "retrieval_status": supported_retrieval.get("status"),
        }
    )
    check(
        "supported-control:false-refusal",
        supported.get("status") == "active"
        and bool(supported.get("knowledge_ids"))
        and supported_retrieval.get("status") in {"answered", "answered_with_gaps"},
        "well-supported core stays answerable while peripheral gaps remain explicit",
        ledger[-1],
    )

    other_tenant = retrieve(
        args.base_url, AMBIGUOUS_CASES[0]["query"], tenant_id="aawo-gap-other"
    )
    check(
        "tenant-isolation",
        other_tenant.get("status") == "unknown"
        and not other_tenant.get("knowledge_gap_ids"),
        "other tenant cannot observe the gap",
        {
            "status": other_tenant.get("status"),
            "gap_ids": other_tenant.get("knowledge_gap_ids", []),
        },
    )

    vxq_gap_ids = ambiguous_results["industrial-vxq-731"]["gap_ids"]
    open_before_resolution = {gap["gap_id"] for gap in list_gaps(args.base_url)}
    resolution = ingest_with_governance(
        args.base_url, RESOLUTION_CASE, allow_approval=True
    )
    open_after_resolution = {gap["gap_id"] for gap in list_gaps(args.base_url)}
    resolved_ids = resolution.get("response", {}).get(
        "resolved_knowledge_gap_ids", []
    )
    resolution_retrieval = retrieve(args.base_url, RESOLUTION_CASE["query"])
    ledger.append(
        {
            "event": "later_evidence_resolution",
            "case_id": RESOLUTION_CASE["case_id"],
            "domain": RESOLUTION_CASE["domain"],
            "ingest_status": resolution.get("status"),
            "resolved_gap_ids": resolved_ids,
            "target_gap_ids": vxq_gap_ids,
            "open_before": sorted(open_before_resolution),
            "open_after": sorted(open_after_resolution),
            "retrieval_status": resolution_retrieval.get("status"),
        }
    )
    check(
        "later-evidence:link-and-close",
        resolution.get("status") == "active"
        and bool(set(vxq_gap_ids).intersection(resolved_ids))
        and not set(resolved_ids).intersection(open_after_resolution)
        and resolution_retrieval.get("status")
        in {"answered", "answered_with_gaps"},
        "later evidence resolves the exact prior gap only after active knowledge is created",
        ledger[-1],
    )

    unrelated_open = {
        gap["gap_id"] for gap in list_gaps(args.base_url)
    }
    check(
        "unrelated-gaps-remain-open",
        all(
            gap_id in unrelated_open
            for case_id in ("oral-history-qelm-204", "agronomy-agr-zeta-91")
            for gap_id in ambiguous_results[case_id]["gap_ids"]
        ),
        "unrelated later evidence does not close other gaps",
        sorted(unrelated_open),
    )

    failed = [item for item in checks if item["status"] == "failed"]
    metrics = {
        "ambiguous_refusal_rate": sum(
            item["status"] == "passed" and item["case_id"].endswith(":refusal")
            for item in checks
        )
        / len(AMBIGUOUS_CASES),
        "supported_answer_retention_rate": (
            1.0
            if any(
                item["case_id"] == "supported-control:false-refusal"
                and item["status"] == "passed"
                for item in checks
            )
            else 0.0
        ),
        "gap_retrieval_abstention_rate": sum(
            item["status"] == "passed" and item["case_id"].endswith(":retrieval")
            for item in checks
        )
        / len(AMBIGUOUS_CASES),
        "later_evidence_link_rate": (
            1.0
            if any(
                item["case_id"] == "later-evidence:link-and-close"
                and item["status"] == "passed"
                for item in checks
            )
            else 0.0
        ),
    }
    report = {
        "schema": "uka.aawo.knowledge-gap-gate.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "gate_status": "passed" if not failed else "failed",
        "provider": {
            "mode": safe.get("provider_mode"),
            "model": safe.get("llm_model"),
            "provider_revision": health.get("provider_health", {}).get(
                "provider_revision"
            ),
            "web_research_enabled": safe.get("web_research_enabled"),
        },
        "scope": {
            "ambiguous_domains": [case["domain"] for case in AMBIGUOUS_CASES],
            "supported_control_domain": SUPPORTED_CASE["domain"],
            "claims": (
                "Representative correction-driven journeys; not a statistical proof "
                "for every domain or a substitute for domain-expert validation."
            ),
        },
        "metrics": metrics,
        "checks": checks,
        "failed_check_count": len(failed),
    }
    ledger_path = output_dir / "knowledge-gap-evidence-ledger.jsonl"
    report_path = output_dir / "knowledge-gap-gate-report.json"
    ledger_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in ledger)
        + "\n",
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "gate_status": report["gate_status"],
                "failed_check_count": len(failed),
                "metrics": metrics,
                "report": str(report_path),
                "report_sha256": sha256(report_path),
                "ledger": str(ledger_path),
                "ledger_sha256": sha256(ledger_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
