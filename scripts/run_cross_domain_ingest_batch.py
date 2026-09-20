"""批量跨领域入库测试驱动：只调用真实 HTTP 边界与真实 LLM，不写密钥。

输出仅包含条目状态、领域 ID、知识谱系统计和报告哈希。
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


def http_json(base: str, path: str, payload: dict, *, timeout: int = 240) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def http_get(base: str, path: str, *, timeout: int = 60) -> list:
    with urllib.request.urlopen(base + path, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_with_retry(base: str, path: str, payload: dict) -> tuple[dict, int, bool]:
    """返回 (响应, HTTP状态码, 是否发生过重试)。"""
    for attempt in (1, 2):
        try:
            return http_json(base, path, payload), 200, attempt == 2
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = exc.read().decode("utf-8", errors="replace")[:500]
            if status in {500, 502, 503, 504} and attempt == 1:
                time.sleep(3)
                continue
            return {"error": True, "http_status": status, "detail": body}, status, attempt == 2
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == 1:
                time.sleep(3)
                continue
            return {"error": True, "detail": type(exc).__name__}, 0, True


def final_knowledge_ids(ingest: dict, resume: dict | None) -> list[str]:
    source = resume if resume is not None else ingest
    return [str(item) for item in source.get("knowledge_ids", [])]


def run_batch(base: str, tenant: str, scope: str) -> tuple[list[dict], dict]:
    records: list[dict] = []
    counters = Counter()
    started = time.time()
    for index, item in enumerate(ITEMS, start=1):
        request_id = f"xdomain-20260917-{index:04d}"
        payload = {
            "text": item["text"],
            "tenant_id": tenant,
            "security_scope_id": scope,
            "actor_id": "cross-domain-batch",
            "classification": "internal",
            "auto_approve": True,
            "request_id": request_id,
        }
        ingest, http_status, retried = post_with_retry(base, "/v1/ingest", payload)
        resume = None
        final_status = "error"
        if http_status == 200 and not ingest.get("error"):
            final_status = str(ingest.get("status", "submitted"))
            thread_id = ingest.get("thread_id")
            if ingest.get("__interrupt__") and thread_id:
                counters["review_required"] += 1
                query = urllib.parse.urlencode(
                    {"tenant_id": tenant, "security_scope_id": scope}
                )
                resume, resume_status, _resume_retried = post_with_retry(
                    base,
                    f"/v1/threads/{urllib.parse.quote(thread_id, safe='')}/resume?{query}",
                    {"value": {"decision": "approve"}},
                )
                if resume_status == 200 and not resume.get("error"):
                    final_status = str(resume.get("status", "active"))
                    if "review_required" in final_status or "held" in final_status:
                        counters["review_unresolved"] += 1
                    else:
                        counters["review_approved"] += 1
                else:
                    final_status = "resume_error"
            else:
                counters["direct"] += 1
        elif http_status == 200 and ingest.get("error"):
            final_status = "http_error"

        if final_status in {"abstained", "rejected"}:
            counters["abstained"] += 1
        if final_status in {"error", "http_error", "resume_error"}:
            counters["errors"] += 1
        if retried:
            counters["retries"] += 1

        records.append(
            {
                "seq": index,
                "title": item["title"],
                "expected_domains": list(item["expected"]),
                "multi_expected": len(item["expected"]) > 1,
                "request_id": request_id,
                "status": final_status,
                "http_status": http_status,
                "retried": retried,
                "knowledge_ids": final_knowledge_ids(ingest, resume),
                "gap_ids": [
                    str(g)
                    for g in (resume or ingest).get("knowledge_gap_ids", [])
                ],
            }
        )
        if index % 10 == 0 or index == len(ITEMS):
            elapsed = int(time.time() - started)
            print(
                f"[{index}/{len(ITEMS)}] elapsed={elapsed}s direct={counters['direct']} "
                f"review={counters['review_required']} approved={counters['review_approved']} "
                f"abstained={counters['abstained']} errors={counters['errors']}",
                flush=True,
            )
        time.sleep(0.1)
    return records, dict(counters)


def analyze(
    base: str, tenant: str, scope: str, records: list[dict], counters: dict
) -> dict:
    entries = http_get(
        base,
        "/v1/knowledge?"
        + urllib.parse.urlencode(
            {"tenant_id": tenant, "security_scope_id": scope, "limit": 2000}
        ),
    )
    gaps = http_get(
        base,
        "/v1/knowledge-gaps?"
        + urllib.parse.urlencode(
            {"tenant_id": tenant, "security_scope_id": scope, "limit": 2000}
        ),
    )
    by_id = {str(entry["knowledge_id"]): entry for entry in entries}
    title_by_id = {str(entry["knowledge_id"]): entry.get("title", "") for entry in entries}

    base_hit = 0
    base_ingested = 0
    base_miss: list[dict] = []
    inter_hits = 0
    inter_ingested = 0
    inter_coverage = 0.0
    multi_detected = 0
    extra_domains = 0
    connected = 0
    total_derived_links = 0
    delta_counter = Counter()
    evolution_candidates = 0
    enriched: list[dict] = []
    for record in records:
        chosen = None
        for knowledge_id in record["knowledge_ids"]:
            entry = by_id.get(knowledge_id)
            if entry is not None:
                chosen = entry
        record["domains"] = []
        record["classification_correct"] = False
        record["multi_domain_detected"] = False
        record["derived_from_knowledge_ids"] = []
        record["derived_from_titles"] = []
        record["knowledge_delta"] = None
        record["evolution"] = None
        if chosen is not None:
            record["knowledge_id"] = str(chosen["knowledge_id"])
            record["title"] = chosen.get("title") or record["title"]
            record["domains"] = [str(d) for d in chosen.get("domain_ids", [])]
            record["confidence"] = chosen.get("confidence")
            record["subjects"] = [str(s) for s in chosen.get("subjects", [])]
            record["tasks"] = [str(t) for t in chosen.get("tasks", [])]
            learning = chosen.get("learning") or {}
            derived = [str(d) for d in learning.get("derived_from_knowledge_ids", [])]
            record["derived_from_knowledge_ids"] = derived
            record["derived_from_titles"] = [
                title_by_id.get(d, d) for d in derived
            ]
            record["knowledge_delta"] = learning.get("knowledge_delta")
            record["evolution"] = chosen.get("evolution")
            expected = set(record["expected_domains"])
            actual = set(record["domains"])
            record["classification_correct"] = bool(expected & actual)
            record["multi_domain_detected"] = len(actual) >= 2
            if record["multi_expected"]:
                inter_ingested += 1
                inter_hits += int(record["classification_correct"])
                inter_coverage += len(expected & actual) / len(expected)
                multi_detected += int(record["multi_domain_detected"])
            else:
                base_ingested += 1
                base_hit += int(record["classification_correct"])
                if not record["classification_correct"]:
                    base_miss.append(
                        {
                            "seq": record["seq"],
                            "title": record["title"],
                            "expected": record["expected_domains"],
                            "actual": record["domains"],
                        }
                    )
                if len(actual) > 1:
                    extra_domains += 1
            if derived:
                connected += 1
                total_derived_links += len(derived)
            if learning.get("knowledge_delta"):
                delta_counter[str(learning["knowledge_delta"])] += 1
            if record["evolution"]:
                evolution_candidates += 1
        enriched.append(record)

    base_total = sum(1 for record in records if not record["multi_expected"])
    inter_total = sum(1 for record in records if record["multi_expected"])
    summary = {
        "tenant_id": tenant,
        "security_scope_id": scope,
        "provider": "http://127.0.0.1:8877 real glm-5.2 boundary",
        "dataset": {
            "total": len(records),
            "single_domain": base_total,
            "interdisciplinary": inter_total,
        },
        "counters": counters,
        "classification": {
            "single_domain_correct": base_hit,
            "single_domain_ingested": base_ingested,
            "single_domain_total": base_total,
            "single_domain_accuracy": round(base_hit / base_ingested, 4) if base_ingested else None,
            "single_domain_misses": base_miss,
            "interdisciplinary_correct": inter_hits,
            "interdisciplinary_total": inter_total,
            "interdisciplinary_ingested": inter_ingested,
            "interdisciplinary_accuracy": round(inter_hits / inter_ingested, 4) if inter_ingested else None,
            "interdisciplinary_mean_coverage": round(inter_coverage / inter_ingested, 4) if inter_ingested else None,
            "interdisciplinary_multi_domain_detected": multi_detected,
            "single_domain_with_extra_domains": extra_domains,
        },
        "connections": {
            "entries_with_derived_links": connected,
            "total_derived_links": total_derived_links,
            "knowledge_delta_distribution": dict(delta_counter),
            "evolution_candidates": evolution_candidates,
        },
        "open_gaps_after_run": len(gaps),
        "active_knowledge_in_tenant": len(entries),
    }
    return {"summary": summary, "items": enriched}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8877")
    parser.add_argument("--tenant-id", default="demo-ui")
    parser.add_argument("--security-scope-id", default="private")
    parser.add_argument(
        "--provider-label",
        default="http://127.0.0.1:8877 real deepseek-v4.1-flash boundary",
    )
    parser.add_argument(
        "--output-dir",
        default="build/cross-domain-batch-20260917",
    )
    args = parser.parse_args()
    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"target={args.base_url} tenant={args.tenant_id} scope={args.security_scope_id} "
        f"items={len(ITEMS)}",
        flush=True,
    )
    records, counters = run_batch(args.base_url, args.tenant_id, args.security_scope_id)
    report = analyze(args.base_url, args.tenant_id, args.security_scope_id, records, counters)
    report["summary"]["provider"] = args.provider_label
    report_path = output_dir / "cross-domain-ingest-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
    (output_dir / "cross-domain-ingest-report.sha256").write_text(
        digest + "\n", encoding="utf-8"
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2), flush=True)
    print(f"report={report_path}", flush=True)
    print(f"report_sha256={digest}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
