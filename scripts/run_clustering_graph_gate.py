"""Real-provider gate for domain hypotheses, clustering and knowledge graph use."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from uka_langgraph.domain.models import DomainRevision, SecurityScope
from uka_langgraph.interfaces.sdk import UniversalKnowledgeAgent
from uka_langgraph.orchestration.runtime import AgentRuntime

ITEMS = (
    (
        "傅里叶变换把时域信号分解为频率成分，并利用卷积定理加速图像与音频处理。",
        ("mathematics", "software_engineering"),
    ),
    (
        "桥梁振动与应变传感器数据经信号处理和机器学习可用于损伤识别与养护决策。",
        ("civil_engineering", "mechanical_engineering", "software_engineering"),
    ),
    (
        "多光谱和雷达遥感反演作物长势、土壤水分与病虫害，为精准农业生成处方图。",
        ("agriculture", "environment", "software_engineering"),
    ),
    (
        "信用风险模型结合统计概率、财务特征和软件系统，对违约概率进行分层评估。",
        ("finance", "mathematics", "software_engineering"),
    ),
    (
        "材料信息学用机器学习建立成分、微观结构、工艺与材料性能之间的预测关系。",
        ("materials_science", "software_engineering"),
    ),
    (
        "数字人文把历史档案、文本标注、地理信息和计算方法结合起来研究长期社会变化。",
        ("history", "software_engineering"),
    ),
    (
        "神经经济学用脑成像与行为实验研究损失厌恶和时间贴现如何影响经济决策。",
        ("psychology", "economics"),
    ),
    (
        "智能电网把电力系统、通信网络、实时数据和软件控制结合起来实现供需协调。",
        ("electrical_engineering", "energy", "software_engineering"),
    ),
)


def _seed_active(
    agent: UniversalKnowledgeAgent,
    *,
    tenant_id: str,
    security_scope_id: str,
    index: int,
    text: str,
    domains: tuple[str, ...],
) -> str:
    knowledge_id = f"kn_cluster_gate_{index:02d}"
    scope_id = f"scope_cluster_gate_{index:02d}"
    security = SecurityScope(tenant_id, security_scope_id)
    created_at = datetime.now(UTC).isoformat()
    with AgentRuntime(agent.settings) as runtime:
        scope = DomainRevision(
            object_type="scope",
            object_id=scope_id,
            revision=1,
            status="evaluated",
            security=security,
            payload={
                "domain": list(domains),
                "domain_ids": list(domains),
                "domain_labels": list(domains),
                "domain_aliases": list(domains),
                "domain_hypotheses": [
                    {
                        "domain_id": domain_id,
                        "probability": round(1.0 / len(domains), 4),
                        "rationale": "隔离 Gate 的已知领域基线。",
                        "missing_information": [],
                    }
                    for domain_id in domains
                ],
                "subjects": [text[:40]],
                "tasks": ["跨学科聚类"],
                "confidence": 0.9,
                "unknowns": [],
                "risk": "normal",
                "review_required": False,
            },
            evidence_ids=(),
            created_at=created_at,
        )
        knowledge = DomainRevision(
            object_type="knowledge",
            object_id=knowledge_id,
            revision=1,
            status="active",
            security=security,
            payload={
                "title": text[:40],
                "content": text,
                "context": "隔离真实模型聚类 Gate 的知识样本。",
                "mechanism": text,
                "rationale": "用于验证真实 LLM 聚类和图谱索引。",
                "confidence": 0.9,
                "scope_id": scope_id,
                "logical_relations": [],
                "source_identifiers": [],
                "conflict_status": "clean",
                "activation_review_completed": True,
            },
            evidence_ids=(),
            created_at=created_at,
        )
        runtime.services.repository.put_revision(scope, f"gate-{scope_id}")
        runtime.services.repository.put_revision(knowledge, f"gate-{knowledge_id}")
        runtime.services.repository.activate_revision(knowledge)
    return knowledge_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tenant-id", default="clustering-graph-gate")
    parser.add_argument("--security-scope-id", default="private")
    parser.add_argument(
        "--seed-mode", choices=("llm", "hybrid", "direct"), default="hybrid"
    )
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    os.environ["UKA_STATE_DIR"] = str((args.output_dir / "state").resolve())
    run_token = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    agent = UniversalKnowledgeAgent(project_root=args.project_root)
    health = agent.doctor(connect=True)
    checks: list[dict[str, object]] = []

    def check(name: str, passed: bool, observed: object) -> None:
        checks.append({"name": name, "passed": bool(passed), "observed": observed})

    provider_health = health.get("provider_health", {})
    check(
        "real_provider_connection",
        provider_health.get("status") == "ok",
        provider_health,
    )
    ingested: list[dict[str, object]] = []
    for index, (text, domains) in enumerate(ITEMS, 1):
        use_llm_ingest = args.seed_mode == "llm" or (
            args.seed_mode == "hybrid" and index == 1
        )
        if not use_llm_ingest:
            knowledge_id = _seed_active(
                agent,
                tenant_id=args.tenant_id,
                security_scope_id=args.security_scope_id,
                index=index,
                text=text,
                domains=domains,
            )
            ingested.append(
                {
                    "index": index,
                    "status": "active_fixture",
                    "knowledge_ids": [knowledge_id],
                    "knowledge_gap_ids": [],
                }
            )
            print(f"[{index}/{len(ITEMS)}] active_fixture", flush=True)
            continue
        thread_id = f"cluster-gate-ingest-{run_token}-{index:02d}"
        result = agent.ingest_text(
            text,
            tenant_id=args.tenant_id,
            security_scope_id=args.security_scope_id,
            actor_id="clustering-gate",
            auto_approve=True,
            thread_id=thread_id,
            request_id=thread_id,
        )
        if "__interrupt__" in result:
            result = agent.resume(
                thread_id,
                {"decision": "approve"},
                tenant_id=args.tenant_id,
                security_scope_id=args.security_scope_id,
            )
        ingested.append(
            {
                "index": index,
                "status": result.get("status"),
                "knowledge_ids": result.get("knowledge_ids", []),
                "knowledge_gap_ids": result.get("knowledge_gap_ids", []),
            }
        )
        print(f"[{index}/{len(ITEMS)}] {result.get('status')}", flush=True)

    library = agent.list_knowledge(
        tenant_id=args.tenant_id,
        security_scope_id=args.security_scope_id,
        limit=100,
    )
    check(
        "all_inputs_produced_active_knowledge",
        len(library) >= len(ITEMS),
        {"input_count": len(ITEMS), "active_knowledge": len(library)},
    )
    hypothesis_count = sum(bool(item.get("domain_hypotheses")) for item in library)
    check(
        "ingestion_domain_hypotheses",
        hypothesis_count == len(library),
        {"with_hypotheses": hypothesis_count, "knowledge": len(library)},
    )

    first = agent.cluster_knowledge(
        tenant_id=args.tenant_id,
        security_scope_id=args.security_scope_id,
        batch_size=args.batch_size,
        thread_id=f"cluster-gate-run-{run_token}-1",
    )
    first_response = first.get("response", {})
    if first.get("status") == "clustered":
        second = agent.cluster_knowledge(
            tenant_id=args.tenant_id,
            security_scope_id=args.security_scope_id,
            batch_size=args.batch_size,
            thread_id=f"cluster-gate-run-{run_token}-2",
        )
        second_response = second.get("response", {})
    else:
        second_response = {
            "status": "skipped_after_first_failure",
            "first_status": first.get("status"),
            "first_error_type": first_response.get("error_type"),
        }
    reasons = {
        str(item.get("sampling_reason"))
        for item in first_response.get("sampling", {}).get("selected", [])
    }
    check(
        "proportional_sampling_buckets",
        {"coverage", "uncertainty", "bridge", "replay"} <= reasons,
        sorted(reasons),
    )
    replayed = [
        item
        for item in second_response.get("sampling", {}).get("selected", [])
        if int(item.get("previous_sample_count", 0)) > 0
    ]
    check("key_knowledge_replayed", bool(replayed), {"replayed": len(replayed)})
    check(
        "llm_clusters_created",
        int(first_response.get("cluster_count", 0)) > 0,
        first_response.get("cluster_count", 0),
    )
    check(
        "llm_graph_edges_created",
        int(first_response.get("edge_count", 0)) > 0,
        first_response.get("edge_count", 0),
    )

    clusters = agent.list_clusters(
        tenant_id=args.tenant_id,
        security_scope_id=args.security_scope_id,
        limit=100,
    )
    graph = agent.knowledge_graph(
        tenant_id=args.tenant_id,
        security_scope_id=args.security_scope_id,
        limit=2000,
    )
    cross_domain_clusters = [
        item for item in clusters if float(item.get("cross_domain_score", 0.0)) >= 0.5
    ]
    check(
        "cross_domain_emergence",
        bool(cross_domain_clusters),
        {"clusters": len(clusters), "cross_domain": len(cross_domain_clusters)},
    )
    cluster_priorities = [
        float(item.get("priority_score", 0.0)) for item in clusters
    ]
    check(
        "cluster_priority_scores_present_and_sorted",
        bool(clusters)
        and all(
            {"missing_score", "potential_score", "priority_score"} <= item.keys()
            for item in clusters
        )
        and cluster_priorities == sorted(cluster_priorities, reverse=True),
        cluster_priorities,
    )
    exploration_priorities = [
        float(item.get("priority", 0.0))
        for item in graph.get("explorations", [])
    ]
    check(
        "exploration_priorities_meaningful",
        bool(exploration_priorities)
        and all(value > 0.0 for value in exploration_priorities),
        exploration_priorities,
    )
    node_types = {str(node.get("node_type")) for node in graph.get("nodes", [])}
    check(
        "complete_graph_node_types",
        {"knowledge", "domain", "cluster"} <= node_types,
        sorted(node_types),
    )
    check(
        "graph_has_provenanced_edges",
        bool(graph.get("edges"))
        and all("confidence" in edge for edge in graph.get("edges", [])),
        {"edge_count": len(graph.get("edges", []))},
    )

    with AgentRuntime(agent.settings) as runtime:
        stats = runtime.services.repository.get_sampling_stats(
            SecurityScope(args.tenant_id, args.security_scope_id)
        )
    check(
        "sampling_stats_persisted",
        bool(stats) and max(int(item["sample_count"]) for item in stats.values()) >= 2,
        {"tracked": len(stats), "max_sample_count": max((int(item["sample_count"]) for item in stats.values()), default=0)},
    )

    passed = all(bool(item["passed"]) for item in checks)
    report = {
        "status": "pass" if passed else "fail",
        "provider": {
            "mode": health.get("provider_mode"),
            "model": health.get("llm_model"),
            "revision": provider_health.get("provider_revision"),
        },
        "tenant_id": args.tenant_id,
        "security_scope_id": args.security_scope_id,
        "seed_mode": args.seed_mode,
        "batch_size": args.batch_size,
        "ingested": ingested,
        "first_clustering": first_response,
        "second_clustering": second_response,
        "checks": checks,
        "graph_summary": {
            "nodes": len(graph.get("nodes", [])),
            "edges": len(graph.get("edges", [])),
            "clusters": len(clusters),
            "explorations": len(graph.get("explorations", [])),
        },
    }
    report_path = args.output_dir / "clustering-graph-gate-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
    (args.output_dir / "clustering-graph-gate-report.sha256").write_text(
        digest + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": report["status"], "checks": checks}, ensure_ascii=False, indent=2))
    print(f"report={report_path}")
    print(f"sha256={digest}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
