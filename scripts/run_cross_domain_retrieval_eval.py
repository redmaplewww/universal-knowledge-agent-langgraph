"""Evaluate retrieval against the existing cross-domain batch tenant.

The script is read-only over knowledge: it calls the real HTTP retrieval
endpoint using each source text as the query and reports answer, abstention,
review, and evidence-backed hit quality.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from cross_domain_dataset_20260917 import ITEMS  # noqa: E402


def post_json(base: str, path: str, payload: dict, timeout: int = 240) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(base: str, path: str, timeout: int = 60) -> list:
    with urllib.request.urlopen(base + path, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def run(base: str, tenant: str, scope: str, limit: int) -> dict:
    knowledge = get_json(
        base,
        "/v1/knowledge?"
        + urllib.parse.urlencode(
            {"tenant_id": tenant, "security_scope_id": scope, "limit": 2000}
        ),
    )
    by_id = {str(entry["knowledge_id"]): entry for entry in knowledge}
    records: list[dict] = []
    counters: Counter[str] = Counter()
    started = time.time()
    for index, item in enumerate(ITEMS, 1):
        try:
            result = post_json(
                base,
                "/v1/retrieve",
                {
                    "query": item["text"],
                    "tenant_id": tenant,
                    "security_scope_id": scope,
                    "limit": limit,
                },
            )
        except (urllib.error.URLError, TimeoutError) as exc:
            records.append(
                {
                    "seq": index,
                    "title": item["title"],
                    "expected_domains": list(item["expected"]),
                    "status": "error",
                    "error": type(exc).__name__,
                }
            )
            counters["errors"] += 1
            continue

        response = result.get("response", {})
        status = str(response.get("status", result.get("status", "unknown")))
        hit_ids = [str(value) for value in response.get("knowledge_ids", [])]
        hit_domains: set[str] = set()
        evidence_backed = []
        for knowledge_id in hit_ids:
            entry = by_id.get(knowledge_id)
            if not entry:
                continue
            hit_domains.update(str(value) for value in entry.get("domain_ids", []))
            evidence_backed.append(
                {
                    "knowledge_id": knowledge_id,
                    "title": entry.get("title", ""),
                    "domains": list(entry.get("domain_ids", [])),
                    "evidence_count": len(entry.get("source_evidence", [])),
                }
            )
        expected = set(item["expected"])
        hit = bool(expected.intersection(hit_domains))
        counters[status] += 1
        if hit:
            counters["expected_domain_hit"] += 1
        if status in {"answered", "answered_with_gaps"} and hit:
            counters["evidence_backed_hit"] += 1
        record = {
            "seq": index,
            "title": item["title"],
            "expected_domains": list(expected),
            "status": status,
            "expected_domain_hit": hit,
            "hit_domains": sorted(hit_domains),
            "hit_coverage": round(len(expected & hit_domains) / len(expected), 4)
            if expected
            else None,
            "top_hits": evidence_backed[:limit],
            "gap_ids": [str(value) for value in response.get("knowledge_gap_ids", [])],
            "review_candidates": response.get("review_candidates", []),
            "requires_human_review": bool(
                response.get("evidence_pack", {}).get("requires_human_review")
            ),
            "answer_chars": len(str(response.get("answer", "")))
            if status.startswith("answered")
            else 0,
        }
        records.append(record)
        if index % 20 == 0 or index == len(ITEMS):
            print(
                f"[{index}/{len(ITEMS)}] elapsed={int(time.time() - started)}s "
                f"answered={counters['answered'] + counters['answered_with_gaps']} "
                f"abstained={counters['abstained']} review={counters['review_required']} "
                f"domain_hits={counters['expected_domain_hit']}",
                flush=True,
            )
        time.sleep(0.02)

    total = len(records)
    expected_domain_hits = sum(bool(item.get("expected_domain_hit")) for item in records)
    single = [item for item in records if len(item["expected_domains"]) == 1]
    multi = [item for item in records if len(item["expected_domains"]) > 1]
    single_hits = sum(bool(item.get("expected_domain_hit")) for item in single)
    multi_hits = sum(bool(item.get("expected_domain_hit")) for item in multi)
    multi_full = sum(
        (set(item["expected_domains"]) <= set(item["hit_domains"]))
        for item in multi
    )
    answered = [item for item in records if item["status"].startswith("answered")]
    summary = {
        "tenant_id": tenant,
        "security_scope_id": scope,
        "provider": "http://127.0.0.1:8877 real deepseek-v4.1-flash boundary",
        "dataset_total": total,
        "retrieval_limit": limit,
        "status_counts": dict(counters),
        "expected_domain_hit_rate": round(expected_domain_hits / total, 4),
        "single_domain": {
            "total": len(single),
            "hit": single_hits,
            "hit_rate": round(single_hits / len(single), 4) if single else None,
        },
        "interdisciplinary": {
            "total": len(multi),
            "hit": multi_hits,
            "hit_rate": round(multi_hits / len(multi), 4) if multi else None,
            "full_domain_coverage": multi_full,
            "full_domain_coverage_rate": round(multi_full / len(multi), 4)
            if multi
            else None,
        },
        "answered_items": len(answered),
        "answer_to_dataset_rate": round(len(answered) / total, 4),
        "open_knowledge_count": len(knowledge),
    }
    return {"summary": summary, "items": records}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8877")
    parser.add_argument("--tenant-id", default="cross-domain-deepseekv41")
    parser.add_argument("--security-scope-id", default="private")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--output-dir",
        default="build/cross-domain-retrieval-eval-20260917",
    )
    args = parser.parse_args()
    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"target={args.base_url} tenant={args.tenant_id} items={len(ITEMS)}",
        flush=True,
    )
    report = run(args.base_url, args.tenant_id, args.security_scope_id, args.limit)
    report_path = output_dir / "cross-domain-retrieval-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
    (output_dir / "cross-domain-retrieval-report.sha256").write_text(
        digest + "\n", encoding="utf-8"
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2), flush=True)
    print(f"report={report_path}", flush=True)
    print(f"report_sha256={digest}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
