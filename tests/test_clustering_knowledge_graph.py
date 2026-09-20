from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from uka_langgraph.domain.models import (
    ClusterCandidate,
    ClusteringResult,
    DomainHypothesis,
    DomainRevision,
    SecurityScope,
)
from uka_langgraph.infrastructure.sqlite_repository import SQLiteRepository
from uka_langgraph.orchestration.runtime import AgentRuntime


def _activate(
    runtime: AgentRuntime,
    security: SecurityScope,
    *,
    knowledge_id: str,
    title: str,
    content: str,
    domains: list[str],
    scope_confidence: float,
    hypothesis_domains: list[tuple[str, float]],
    relation_count: int = 0,
) -> None:
    scope_id = f"scope-{knowledge_id}"
    scope = DomainRevision(
        object_type="scope",
        object_id=scope_id,
        revision=1,
        status="evaluated",
        security=security,
        payload={
            "domain": domains,
            "domain_ids": domains,
            "domain_labels": domains,
            "domain_aliases": domains,
            "domain_hypotheses": [
                {
                    "domain_id": domain_id,
                    "probability": probability,
                    "rationale": "测试候选领域",
                    "missing_information": [],
                }
                for domain_id, probability in hypothesis_domains
            ],
            "subjects": [title],
            "tasks": ["跨学科测试"],
            "confidence": scope_confidence,
            "unknowns": ["需要更多领域证据"] if scope_confidence < 0.7 else [],
            "risk": "normal",
            "review_required": False,
        },
        evidence_ids=(),
        created_at="2026-09-19T00:00:00+00:00",
    )
    knowledge = DomainRevision(
        object_type="knowledge",
        object_id=knowledge_id,
        revision=1,
        status="active",
        security=security,
        payload={
            "title": title,
            "content": content,
            "context": "聚类测试上下文",
            "mechanism": content,
            "rationale": "用于验证批次采样和图谱扩展。",
            "confidence": 0.9,
            "scope_id": scope_id,
            "logical_relations": [
                {"source": title, "relation": "supports", "target": content}
                for _ in range(relation_count)
            ],
            "source_identifiers": [],
            "conflict_status": "clean",
            "activation_review_completed": True,
        },
        evidence_ids=(),
        created_at="2026-09-19T00:00:00+00:00",
    )
    runtime.services.repository.put_revision(scope, f"op-{scope_id}")
    runtime.services.repository.put_revision(knowledge, f"op-{knowledge_id}")
    runtime.services.repository.activate_revision(knowledge)


def test_proportional_clustering_persists_graph_and_replays_key_knowledge(settings) -> None:
    security = SecurityScope("tenant-cluster", "private")
    with AgentRuntime(settings) as runtime:
        rows = [
            (
                "kn-turbine",
                "蒸汽涡轮振动",
                "蒸汽涡轮出现叶频振动时应检查叶片和转子状态。",
                ["mechanical_engineering"],
                0.95,
                [("mechanical_engineering", 0.95)],
                4,
            ),
            (
                "kn-bearing",
                "轴承润滑寿命",
                "轴承润滑状态会影响疲劳寿命和温升。",
                ["mechanical_engineering"],
                0.9,
                [("mechanical_engineering", 0.9)],
                1,
            ),
            (
                "kn-neuroeconomics",
                "神经经济学",
                "神经经济学连接心理偏差、脑成像和经济决策。",
                ["psychology", "economics"],
                0.7,
                [("psychology", 0.55), ("economics", 0.45)],
                1,
            ),
            (
                "kn-materials-ai",
                "材料信息学",
                "材料信息学用机器学习连接材料结构与性能预测。",
                ["materials_science", "software_engineering"],
                0.65,
                [("materials_science", 0.5), ("software_engineering", 0.5)],
                1,
            ),
            (
                "kn-history",
                "口述史证据",
                "口述史需要结合讲述者背景和同期档案解释。",
                ["history"],
                0.55,
                [("history", 0.6), ("social_science", 0.35)],
                0,
            ),
            (
                "kn-grid",
                "智能电网",
                "智能电网连接电力系统、通信和软件控制。",
                ["electrical_engineering", "energy", "software_engineering"],
                0.75,
                [
                    ("electrical_engineering", 0.4),
                    ("energy", 0.35),
                    ("software_engineering", 0.25),
                ],
                2,
            ),
            (
                "kn-law",
                "合同解释",
                "合同解释需要结合文义、目的和交易习惯。",
                ["legal"],
                0.9,
                [("legal", 0.9)],
                1,
            ),
            (
                "kn-biology",
                "细胞信号",
                "细胞受体通过信号通路调节下游响应。",
                ["biology"],
                0.85,
                [("biology", 0.85)],
                1,
            ),
        ]
        for row in rows:
            _activate(
                runtime,
                security,
                knowledge_id=row[0],
                title=row[1],
                content=row[2],
                domains=row[3],
                scope_confidence=row[4],
                hypothesis_domains=row[5],
                relation_count=row[6],
            )

        first = runtime.invoke(
            intent="cluster",
            tenant_id=security.tenant_id,
            security_scope_id=security.security_scope_id,
            payload={"batch_size": 4},
            thread_id="cluster-run-1",
        )
        assert first["status"] == "clustered"
        sampling = first["response"]["sampling"]
        assert len(sampling["selected"]) == 4
        assert {item["sampling_reason"] for item in sampling["selected"]} >= {
            "coverage",
            "uncertainty",
            "bridge",
            "replay",
        }
        assert first["response"]["cluster_count"] >= 3

        second = runtime.invoke(
            intent="cluster",
            tenant_id=security.tenant_id,
            security_scope_id=security.security_scope_id,
            payload={"batch_size": 4},
            thread_id="cluster-run-2",
        )
        assert second["status"] == "clustered"
        stats = runtime.services.repository.get_sampling_stats(security)
        assert stats["kn-turbine"]["sample_count"] == 2
        assert runtime.services.repository.list_clusters(security, 100)
        graph = runtime.services.repository.graph_snapshot(security, 100)
        assert graph["clusters"]


def test_graph_expansion_adds_high_confidence_cluster_neighbor(settings) -> None:
    security = SecurityScope("tenant-graph", "private")
    with AgentRuntime(settings) as runtime:
        _activate(
            runtime,
            security,
            knowledge_id="kn-turbine",
            title="蒸汽涡轮振动",
            content="蒸汽涡轮叶频振动指向叶片和转子状态。",
            domains=["mechanical_engineering"],
            scope_confidence=0.95,
            hypothesis_domains=[("mechanical_engineering", 0.95)],
        )
        _activate(
            runtime,
            security,
            knowledge_id="kn-bearing",
            title="轴承润滑寿命",
            content="润滑状态决定轴承疲劳寿命与温升。",
            domains=["mechanical_engineering"],
            scope_confidence=0.9,
            hypothesis_domains=[("mechanical_engineering", 0.9)],
        )
        clustered = runtime.invoke(
            intent="cluster",
            tenant_id=security.tenant_id,
            security_scope_id=security.security_scope_id,
            payload={"batch_size": 2},
            thread_id="cluster-retrieval",
        )
        assert clustered["status"] == "clustered"
        retrieved = runtime.services.retrieval.retrieve(
            security=security,
            query="蒸汽涡轮叶频",
            limit=2,
            query_scope={"domain": "mechanical_engineering"},
        )
        assert retrieved["status"] == "answered"
        assert retrieved["knowledge_ids"][0] == "kn-turbine"
        assert "kn-bearing" in retrieved["knowledge_ids"]
        assert retrieved["graph_expanded_knowledge_ids"] == ["kn-bearing"]


def test_clustering_requires_two_active_knowledge_items(settings) -> None:
    with AgentRuntime(settings) as runtime:
        result = runtime.invoke(
            intent="cluster",
            tenant_id="empty",
            security_scope_id="private",
            payload={"batch_size": 8},
            thread_id="cluster-empty",
        )
    assert result["status"] == "insufficient_knowledge"
    assert result["response"]["available_knowledge"] == 0


def test_ingestion_triggers_auto_clustering_when_unsampled_threshold_is_met(
    settings,
) -> None:
    auto_settings = replace(
        settings,
        clustering_enabled=True,
        cluster_auto_every=2,
        cluster_batch_size=2,
    )
    with AgentRuntime(auto_settings) as runtime:
        first_ref = runtime.stage_text("第一条知识描述机械设备的振动来源。")
        first = runtime.invoke(
            intent="ingest",
            tenant_id="auto-cluster",
            security_scope_id="private",
            input_refs=[first_ref],
            payload={"auto_approve": True},
            thread_id="auto-cluster-1",
        )
        assert first["status"] == "active"
        assert "auto_clustering" not in first
        second_ref = runtime.stage_text("第二条知识描述机械设备的润滑条件。")
        second = runtime.invoke(
            intent="ingest",
            tenant_id="auto-cluster",
            security_scope_id="private",
            input_refs=[second_ref],
            payload={"auto_approve": True},
            thread_id="auto-cluster-2",
        )
        assert second["status"] == "active"
        assert second["auto_clustering"]["status"] == "clustered"


class _RankingProvider:
    revision = "ranking-test"

    @staticmethod
    def cluster_knowledge(knowledge, gaps=()):  # noqa: ANN001, ANN202
        del knowledge, gaps
        return ClusteringResult(
            clusters=(
                ClusterCandidate(
                    cluster_key="low-priority",
                    name="确定的单领域聚类",
                    summary="没有明显缺口。",
                    member_knowledge_ids=("kn-a",),
                    domain_hypotheses=(
                        DomainHypothesis("history", 1.0),
                    ),
                    cross_domain_score=0.0,
                    confidence=0.9,
                ),
                ClusterCandidate(
                    cluster_key="high-priority",
                    name="高缺口跨领域聚类",
                    summary="需要优先探索。",
                    member_knowledge_ids=("kn-b",),
                    domain_hypotheses=(
                        DomainHypothesis(
                            "materials_science",
                            0.5,
                            missing_information=("材料参数",),
                        ),
                        DomainHypothesis(
                            "software_engineering",
                            0.5,
                            missing_information=("模型验证",),
                        ),
                    ),
                    missing_information=("跨域边界条件",),
                    cross_domain_score=1.0,
                    confidence=0.8,
                ),
            ),
            edges=(),
        )


class _FailingClusteringProvider:
    revision = "failing-test"

    @staticmethod
    def cluster_knowledge(knowledge, gaps=()):  # noqa: ANN001, ANN202
        del knowledge, gaps
        raise TimeoutError("sensitive upstream detail")


def test_clusters_are_ranked_by_missing_and_potential_domain_priority(
    settings,
) -> None:
    security = SecurityScope("tenant-ranking", "private")
    with AgentRuntime(settings) as runtime:
        for knowledge_id, domain in (("kn-a", "history"), ("kn-b", "materials_science")):
            _activate(
                runtime,
                security,
                knowledge_id=knowledge_id,
                title=knowledge_id,
                content=f"{knowledge_id} 的测试知识。",
                domains=[domain],
                scope_confidence=0.9,
                hypothesis_domains=[(domain, 0.9)],
            )
        runtime.services.clustering.provider = _RankingProvider()  # type: ignore[assignment]
        result = runtime.services.clustering.run(security=security, batch_size=2)
        clusters = runtime.services.repository.list_clusters(security, 10)

    assert result["status"] == "clustered"
    assert [item["cluster_key"] for item in clusters] == [
        "high-priority",
        "low-priority",
    ]
    assert clusters[0]["missing_score"] > clusters[1]["missing_score"]
    assert clusters[0]["potential_score"] > clusters[1]["potential_score"]
    assert clusters[0]["priority_score"] > clusters[1]["priority_score"]


def test_manual_clustering_provider_failure_settles_without_exception(
    settings,
) -> None:
    security = SecurityScope("tenant-provider-failure", "private")
    with AgentRuntime(settings) as runtime:
        for knowledge_id in ("kn-a", "kn-b"):
            _activate(
                runtime,
                security,
                knowledge_id=knowledge_id,
                title=knowledge_id,
                content="用于验证聚类失败关闭。",
                domains=["general"],
                scope_confidence=0.9,
                hypothesis_domains=[("general", 0.9)],
            )
        runtime.services.clustering.provider = _FailingClusteringProvider()  # type: ignore[assignment]
        result = runtime.invoke(
            intent="cluster",
            tenant_id=security.tenant_id,
            security_scope_id=security.security_scope_id,
            payload={"batch_size": 2},
            thread_id="cluster-provider-failure",
        )

    assert result["status"] == "failed"
    assert result["response"] == {
        "status": "clustering_failed",
        "run_id": None,
        "error_type": "TimeoutError",
    }
    assert result["errors"] == ["clustering_provider_error:TimeoutError"]
    assert "sensitive upstream detail" not in str(result)


def test_repository_migrates_pre_ranking_cluster_table(tmp_path) -> None:
    path = tmp_path / "pre-ranking.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE knowledge_clusters (
                tenant_id TEXT NOT NULL,
                security_scope_id TEXT NOT NULL,
                cluster_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                name TEXT NOT NULL,
                summary TEXT NOT NULL,
                confidence REAL NOT NULL,
                cross_domain_score REAL NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, security_scope_id, cluster_id)
            )
            """
        )

    repository = SQLiteRepository(path)
    repository.initialize()
    with sqlite3.connect(path) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(knowledge_clusters)"
            ).fetchall()
        }
    assert {"missing_score", "potential_score", "priority_score"} <= columns


def test_repository_initialize_is_safe_under_parallel_read_requests(tmp_path) -> None:
    path = tmp_path / "parallel-initialize.sqlite3"

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(
            executor.map(
                lambda _: SQLiteRepository(path).initialize(),
                range(18),
            )
        )

    assert results == [None] * 18


def test_graph_expansion_sql_supports_multiple_seed_placeholders(settings) -> None:
    security = SecurityScope("tenant-multi-seed", "private")
    with AgentRuntime(settings) as runtime:
        for knowledge_id in ("kn-a", "kn-b", "kn-c"):
            _activate(
                runtime,
                security,
                knowledge_id=knowledge_id,
                title=knowledge_id,
                content=f"{knowledge_id} 属于同一机械系统。",
                domains=["mechanical_engineering"],
                scope_confidence=0.9,
                hypothesis_domains=[("mechanical_engineering", 0.9)],
            )
        runtime.services.clustering.run(security=security, batch_size=3)
        expanded = runtime.services.repository.expand_knowledge_graph(
            security,
            ["kn-a", "kn-b"],
            limit=5,
        )

    assert [item.object_id for item in expanded] == ["kn-c"]
