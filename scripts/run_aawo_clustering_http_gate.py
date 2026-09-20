"""AAWO customer-journey gate for clustering and graph HTTP boundaries."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from codex_agent_tester import (
    AgentContractProfile,
    CustomerJourney,
    CustomerSimulationRunner,
    EvidenceLedger,
    HttpAdapter,
    JourneyStep,
)


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    ledger = EvidenceLedger(args.output_dir / "evidence-ledger.sqlite3")
    runner = CustomerSimulationRunner(ledger)

    async def journey(
        *,
        scenario_id: str,
        goal: str,
        url: str,
        method: str,
        payload: dict[str, Any],
        required: list[str],
        assertions: list[dict[str, Any]],
        side_effect_policy: str = "read_only",
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        adapter_id = f"http:uka-clustering:{scenario_id}"
        profile = AgentContractProfile(
            agent_id="universal-knowledge-agent-clustering",
            adapter_id=adapter_id,
            purpose=goal,
            input_schema={"type": "object"},
            output_schema={"type": "object", "required": required},
        )
        customer_journey = CustomerJourney(
            scenario_id=scenario_id,
            goal=goal,
            actor={"role": "knowledge_curator"},
            steps=(
                JourneyStep("request", "user_input", payload),
                JourneyStep(
                    "verify", "expect", assertions=tuple(assertions)
                ),
            ),
            side_effect_policy=side_effect_policy,
        )
        result = await runner.run(
            customer_journey,
            profile,
            HttpAdapter(adapter_id, url, method=method, timeout=timeout),
        )
        return {
            "scenario_id": scenario_id,
            "goal": goal,
            "status": result.status.value,
            "run": result.to_dict(),
        }

    base = args.base_url.rstrip("/")
    query = (
        f"tenant_id={args.tenant_id}&security_scope_id={args.security_scope_id}"
    )
    runs = []
    runs.append(
        await journey(
            scenario_id="clustering.health",
            goal="确认真实 HTTP 服务暴露聚类能力元数据",
            url=f"{base}/health",
            method="GET",
            payload={},
            required=["provider_mode", "clustering_enabled", "cluster_batch_size"],
            assertions=[
                {"kind": "path_equals", "path": "provider_mode", "value": "llm"},
                {
                    "kind": "path_equals",
                    "path": "clustering_enabled",
                    "value": True,
                },
            ],
        )
    )
    runs.append(
        await journey(
            scenario_id="clustering.graph.read",
            goal="确认客户可读取知识领域聚类和缺口组成的完整图谱",
            url=f"{base}/v1/knowledge-graph?{query}&limit=2000",
            method="GET",
            payload={},
            required=["nodes", "edges", "clusters", "explorations"],
            assertions=[
                {"kind": "text_contains", "text": "member_of_cluster"},
                {"kind": "text_contains", "text": "belongs_to_domain"},
                {"kind": "text_contains", "text": "priority_score"},
                {"kind": "text_contains", "text": "exploration_id"},
            ],
        )
    )
    runs.append(
        await journey(
            scenario_id="clustering.run.real_llm",
            goal="知识管理员通过真实 HTTP 边界触发一轮受控 LLM 聚类",
            url=f"{base}/v1/clustering/runs",
            method="POST",
            payload={
                "tenant_id": args.tenant_id,
                "security_scope_id": args.security_scope_id,
                "actor_id": "aawo-clustering-gate",
                "batch_size": args.batch_size,
                "coverage_ratio": 0.4,
                "uncertainty_ratio": 0.3,
                "bridge_ratio": 0.2,
                "replay_ratio": 0.1,
                "thread_id": args.thread_id,
            },
            required=["status", "response", "cluster_run_ids"],
            assertions=[
                {"kind": "path_equals", "path": "status", "value": "clustered"},
                {"kind": "text_contains", "text": "sampling_reason"},
                {"kind": "text_contains", "text": "edge_count"},
            ],
            side_effect_policy="sandbox_write",
            timeout=300.0,
        )
    )
    runs.append(
        await journey(
            scenario_id="clustering.tenant.isolation",
            goal="确认其他租户无法观察当前知识图谱",
            url=(
                f"{base}/v1/knowledge-graph?tenant_id=other-tenant"
                f"&security_scope_id={args.security_scope_id}&limit=2000"
            ),
            method="GET",
            payload={},
            required=["nodes", "edges", "clusters", "explorations"],
            assertions=[
                {"kind": "path_equals", "path": "nodes", "value": []},
                {"kind": "path_equals", "path": "edges", "value": []},
            ],
        )
    )
    status = "pass" if all(item["status"] == "pass" for item in runs) else "fail"
    report = {
        "status": status,
        "target": {"base_url": base, "boundary": "real_http"},
        "profile": {
            "agent_id": "universal-knowledge-agent-clustering",
            "contract_revision": "0.4.0-clustering-graph",
            "tester_engine": "codex_agent_tester AAWO-compatible runtime",
        },
        "runs": runs,
        "ledger_records": len(ledger.records()),
        "ledger_path": ledger.path,
        "limitations": [
            "隔离本地状态库与真实受管模型，不代表生产容量或领域专家认证。",
            "聚类边是检索索引假设，不自动升级为知识事实。",
        ],
    }
    report_path = args.output_dir / "aawo-clustering-http-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
    (args.output_dir / "aawo-clustering-http-report.sha256").write_text(
        digest + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"sha256={digest}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8878")
    parser.add_argument("--tenant-id", default="clustering-graph-gate")
    parser.add_argument("--security-scope-id", default="private")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument(
        "--thread-id", default="aawo-clustering-http-20260919-retry2"
    )
    args = parser.parse_args()
    report = asyncio.run(_run(args))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
