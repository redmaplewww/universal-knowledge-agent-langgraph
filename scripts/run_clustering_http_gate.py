"""Project-local HTTP acceptance gate for clustering and graph boundaries."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> tuple[int, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        status = int(exc.code)
        raw = exc.read().decode("utf-8", errors="replace")
    except URLError as exc:
        return 0, {"transport_error": type(exc.reason).__name__}
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, {"invalid_json": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8877")
    parser.add_argument("--tenant-id", default="clustering-graph-gate")
    parser.add_argument("--security-scope-id", default="private")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--thread-id", default="clustering-http-gate")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    base = args.base_url.rstrip("/")
    query = urlencode(
        {
            "tenant_id": args.tenant_id,
            "security_scope_id": args.security_scope_id,
            "limit": 2000,
        }
    )
    runs: list[dict[str, Any]] = []

    def record(
        scenario_id: str,
        goal: str,
        status_code: int,
        output: Any,
        passed: bool,
        assertions: list[str],
        side_effect_policy: str = "read_only",
    ) -> None:
        runs.append(
            {
                "scenario_id": scenario_id,
                "goal": goal,
                "status": "pass" if passed else "fail",
                "status_code": status_code,
                "assertions": assertions,
                "side_effect_policy": side_effect_policy,
                "output": output,
            }
        )

    health_status, health = request_json(f"{base}/health")
    health_assertions = [
        "HTTP 200",
        "provider_mode=llm",
        "clustering_enabled=true",
    ]
    record(
        "clustering.health",
        "确认真实 HTTP 服务暴露聚类能力元数据",
        health_status,
        health,
        health_status == 200
        and isinstance(health, dict)
        and health.get("provider_mode") == "llm"
        and health.get("clustering_enabled") is True,
        health_assertions,
    )

    graph_status, graph = request_json(f"{base}/v1/knowledge-graph?{query}")
    graph_text = json.dumps(graph, ensure_ascii=False)
    graph_assertions = [
        "HTTP 200",
        "包含 nodes/edges/clusters/explorations",
        "包含 member_of_cluster 与 belongs_to_domain",
    ]
    record(
        "clustering.graph.read",
        "确认客户可读取知识、领域、聚类和缺口组成的图谱",
        graph_status,
        graph,
        graph_status == 200
        and isinstance(graph, dict)
        and {"nodes", "edges", "clusters", "explorations"} <= graph.keys()
        and "member_of_cluster" in graph_text
        and "belongs_to_domain" in graph_text,
        graph_assertions,
    )

    cluster_status, clustered = request_json(
        f"{base}/v1/clustering/runs",
        method="POST",
        payload={
            "tenant_id": args.tenant_id,
            "security_scope_id": args.security_scope_id,
            "actor_id": "clustering-http-gate",
            "batch_size": args.batch_size,
            "coverage_ratio": 0.4,
            "uncertainty_ratio": 0.3,
            "bridge_ratio": 0.2,
            "replay_ratio": 0.1,
            "thread_id": args.thread_id,
        },
        timeout=300.0,
    )
    response = clustered.get("response", {}) if isinstance(clustered, dict) else {}
    cluster_assertions = [
        "HTTP 200",
        "status=clustered",
        "返回 sampling 与 edge_count",
    ]
    record(
        "clustering.run.real_llm",
        "通过真实 HTTP 边界触发受控 LLM 聚类",
        cluster_status,
        clustered,
        cluster_status == 200
        and isinstance(clustered, dict)
        and clustered.get("status") == "clustered"
        and isinstance(response.get("sampling"), dict)
        and "edge_count" in response,
        cluster_assertions,
        side_effect_policy="isolated_test_write",
    )

    other_query = urlencode(
        {
            "tenant_id": f"{args.tenant_id}-other",
            "security_scope_id": args.security_scope_id,
            "limit": 2000,
        }
    )
    isolation_status, isolated = request_json(
        f"{base}/v1/knowledge-graph?{other_query}"
    )
    isolation_assertions = ["HTTP 200", "其他租户的 nodes 与 edges 均为空"]
    record(
        "clustering.tenant.isolation",
        "确认其他租户无法观察当前知识图谱",
        isolation_status,
        isolated,
        isolation_status == 200
        and isinstance(isolated, dict)
        and isolated.get("nodes") == []
        and isolated.get("edges") == [],
        isolation_assertions,
    )

    report = {
        "status": "pass" if all(run["status"] == "pass" for run in runs) else "fail",
        "target": {"base_url": base, "boundary": "real_http"},
        "profile": {
            "agent_id": "universal-knowledge-agent-clustering",
            "contract_revision": "0.4.0-clustering-graph",
            "tester": "project-local-standard-library-http-gate",
        },
        "runs": runs,
        "limitations": [
            "隔离本地状态库与真实受管模型，不代表生产容量或领域专家认证。",
            "聚类边是检索索引假设，不自动升级为知识事实。",
        ],
    }
    report_path = args.output_dir / "clustering-http-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
    (args.output_dir / "clustering-http-report.sha256").write_text(
        digest + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "runs": [
                    {"scenario_id": run["scenario_id"], "status": run["status"]}
                    for run in runs
                ],
                "report": str(report_path),
                "sha256": digest,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
