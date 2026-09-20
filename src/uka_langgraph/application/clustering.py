from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from uka_langgraph.application.ports import RepositoryPort, UnderstandingPort
from uka_langgraph.domain.models import DomainRevision, SecurityScope


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _bounded(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else f"{text[:limit]}…"


def _domain_uncertainty(hypotheses: tuple[Any, ...]) -> float:
    probabilities = [
        max(0.0, min(float(item.probability), 1.0))
        for item in hypotheses
        if float(item.probability) > 0
    ]
    if not probabilities:
        return 1.0
    total = sum(probabilities)
    normalized = [value / total for value in probabilities]
    entropy = -sum(value * math.log(value, 2) for value in normalized)
    max_entropy = math.log(max(2, len(normalized)), 2)
    ambiguity = min(1.0, entropy / max_entropy)
    residual = max(0.0, 1.0 - max(probabilities))
    return min(1.0, 0.75 * ambiguity + 0.25 * residual)


def _cluster_scores(cluster: Any) -> tuple[float, float, float]:
    missing = {
        str(value).strip()
        for value in cluster.missing_information
        if str(value).strip()
    }
    for hypothesis in cluster.domain_hypotheses:
        missing.update(
            str(value).strip()
            for value in hypothesis.missing_information
            if str(value).strip()
        )
    missing_score = 1.0 - math.exp(-len(missing) / 3.0)
    potential_score = _domain_uncertainty(cluster.domain_hypotheses)
    priority_score = min(
        1.0,
        0.45 * missing_score
        + 0.35 * potential_score
        + 0.2 * cluster.cross_domain_score,
    )
    return tuple(
        round(value, 6)
        for value in (missing_score, potential_score, priority_score)
    )


@dataclass(frozen=True, slots=True)
class SamplingRatios:
    coverage: float = 0.4
    uncertainty: float = 0.3
    bridge: float = 0.2
    replay: float = 0.1

    def normalized(self) -> dict[str, float]:
        values = {
            "coverage": max(0.0, self.coverage),
            "uncertainty": max(0.0, self.uncertainty),
            "bridge": max(0.0, self.bridge),
            "replay": max(0.0, self.replay),
        }
        total = sum(values.values())
        if total <= 0:
            raise ValueError("at least one clustering sampling ratio must be positive")
        return {key: value / total for key, value in values.items()}


@dataclass(slots=True)
class KnowledgeClusteringService:
    repository: RepositoryPort
    provider: UnderstandingPort

    def run(
        self,
        *,
        security: SecurityScope,
        batch_size: int = 24,
        ratios: SamplingRatios | None = None,
    ) -> dict[str, Any]:
        bounded_batch = max(2, min(batch_size, 64))
        active = self.repository.list_active_knowledge(security, 1000)
        if len(active) < 2:
            return {
                "status": "insufficient_knowledge",
                "run_id": None,
                "available_knowledge": len(active),
                "required_knowledge": 2,
            }
        gaps = self.repository.list_open_gaps(security, 1000)
        stats = self.repository.get_sampling_stats(security)
        scored = [self._score_item(security, item, gaps, stats) for item in active]
        selected = self._sample(scored, bounded_batch, ratios or SamplingRatios())
        selected_ids = {str(item["knowledge_id"]) for item in selected}
        gap_views = tuple(
            self._gap_view(gap)
            for gap in gaps
            if not gap.payload.get("related_knowledge_ids")
            or selected_ids.intersection(
                str(value) for value in gap.payload.get("related_knowledge_ids", [])
            )
        )[:16]
        provider_input = tuple(self._provider_view(item) for item in selected)
        result = self.provider.cluster_knowledge(provider_input, gap_views)
        created_at = _now()
        run_id = _stable_id(
            "cluster_run",
            security.tenant_id,
            security.security_scope_id,
            created_at,
            *sorted(selected_ids),
        )
        clusters = []
        for cluster in result.clusters:
            missing_score, potential_score, priority_score = _cluster_scores(
                cluster
            )
            clusters.append(
                {
                    "cluster_id": _stable_id("cluster", cluster.cluster_key),
                    "cluster_key": cluster.cluster_key,
                    "name": cluster.name,
                    "summary": cluster.summary,
                    "member_knowledge_ids": list(cluster.member_knowledge_ids),
                    "domain_hypotheses": [
                        asdict(item) for item in cluster.domain_hypotheses
                    ],
                    "keywords": list(cluster.keywords),
                    "missing_information": list(cluster.missing_information),
                    "cross_domain_score": cluster.cross_domain_score,
                    "missing_score": missing_score,
                    "potential_score": potential_score,
                    "priority_score": priority_score,
                    "confidence": cluster.confidence,
                    "run_id": run_id,
                    "provider_revision": self.provider.revision,
                    "created_at": created_at,
                }
            )
        edges = [
            {
                "edge_id": _stable_id(
                    "graph_edge", edge.source_id, edge.relation, edge.target_id
                ),
                "source_id": edge.source_id,
                "relation": edge.relation,
                "target_id": edge.target_id,
                "confidence": edge.confidence,
                "rationale": edge.rationale,
                "evidence_knowledge_ids": list(edge.evidence_knowledge_ids),
                "run_id": run_id,
                "provider_revision": self.provider.revision,
                "origin": "llm_semantic_edge",
                "created_at": created_at,
            }
            for edge in result.edges
            if edge.confidence >= 0.65
        ]
        existing_edge_keys = {
            (str(item["source_id"]), str(item["relation"]), str(item["target_id"]))
            for item in edges
        }
        for cluster in result.clusters:
            members = list(dict.fromkeys(cluster.member_knowledge_ids))
            if len(members) < 2 or cluster.confidence < 0.65:
                continue
            relation = (
                "bridges"
                if cluster.cross_domain_score >= 0.5
                or len(cluster.domain_hypotheses) > 1
                else "shares_domain_context"
            )
            anchor = members[0]
            for target in members[1:]:
                edge_key = (anchor, relation, target)
                if edge_key in existing_edge_keys:
                    continue
                confidence = min(
                    cluster.confidence,
                    max(0.65, 0.6 + 0.25 * cluster.cross_domain_score),
                )
                edges.append(
                    {
                        "edge_id": _stable_id(
                            "graph_edge", anchor, relation, target
                        ),
                        "source_id": anchor,
                        "relation": relation,
                        "target_id": target,
                        "confidence": confidence,
                        "rationale": (
                            "由受控 LLM 聚类的共同成员关系生成，用于检索扩展；"
                            f"不作为新的事实断言。{cluster.summary}"
                        ),
                        "evidence_knowledge_ids": [anchor, target],
                        "run_id": run_id,
                        "provider_revision": self.provider.revision,
                        "origin": "cluster_membership_fallback",
                        "created_at": created_at,
                    }
                )
                existing_edge_keys.add(edge_key)
        explorations = [
            {
                "exploration_id": _stable_id(
                    "exploration", item.question, *item.related_knowledge_ids
                ),
                "title": item.title,
                "question": item.question,
                "domain_hypotheses": [
                    asdict(hypothesis) for hypothesis in item.domain_hypotheses
                ],
                "related_knowledge_ids": list(item.related_knowledge_ids),
                "missing_information": list(item.missing_information),
                "priority": item.priority,
                "run_id": run_id,
                "provider_revision": self.provider.revision,
                "created_at": created_at,
            }
            for item in result.explorations
        ]
        sampling = {
            "batch_size": len(selected),
            "requested_batch_size": bounded_batch,
            "ratios": (ratios or SamplingRatios()).normalized(),
            "selected": [
                {
                    key: item[key]
                    for key in (
                        "knowledge_id",
                        "sampling_reason",
                        "primary_domain",
                        "priority_score",
                        "missing_score",
                        "potential_score",
                        "bridge_score",
                        "key_score",
                        "previous_sample_count",
                    )
                }
                for item in selected
            ],
        }
        result_summary = {
            "cluster_count": len(clusters),
            "edge_count": len(edges),
            "exploration_count": len(explorations),
            "warnings": list(result.warnings),
        }
        self.repository.replace_cluster_index(
            security, run_id, clusters, edges, explorations, created_at
        )
        self.repository.upsert_sampling_stats(security, selected, created_at)
        self.repository.record_clustering_run(
            security,
            run_id,
            self.provider.revision,
            sampling,
            result_summary,
            created_at,
        )
        return {
            "status": "clustered",
            "run_id": run_id,
            "provider_revision": self.provider.revision,
            "sampling": sampling,
            **result_summary,
        }

    def _score_item(
        self,
        security: SecurityScope,
        knowledge: DomainRevision,
        gaps: list[DomainRevision],
        stats: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        scope_id = str(knowledge.payload.get("scope_id", ""))
        scope = (
            self.repository.get_revision(security, "scope", scope_id)
            if scope_id
            else None
        )
        scope_payload = scope.payload if scope else {}
        domains = [
            str(value)
            for value in scope_payload.get(
                "domain_ids", scope_payload.get("domain", ["unknown"])
            )
        ] or ["unknown"]
        raw_hypotheses = scope_payload.get("domain_hypotheses", [])
        hypotheses = [
            item for item in raw_hypotheses if isinstance(item, dict)
        ]
        probabilities = sorted(
            (
                max(0.0, min(float(item.get("probability", 0.0)), 1.0))
                for item in hypotheses
            ),
            reverse=True,
        )
        scope_confidence = max(
            0.0, min(float(scope_payload.get("confidence", 0.0)), 1.0)
        )
        related_gap_count = sum(
            knowledge.object_id
            in {str(value) for value in gap.payload.get("related_knowledge_ids", [])}
            for gap in gaps
        )
        unknown_count = len(scope_payload.get("unknowns", []))
        missing_score = min(
            1.0,
            (1.0 - scope_confidence)
            + min(0.25, unknown_count * 0.08)
            + min(0.25, related_gap_count * 0.08)
            + (0.25 if "unknown" in domains else 0.0),
        )
        if probabilities:
            entropy = -sum(
                value * math.log(value, 2) for value in probabilities if value > 0
            )
            max_entropy = math.log(max(2, len(probabilities)), 2)
            uncertainty = min(1.0, entropy / max_entropy)
            alternative = probabilities[1] if len(probabilities) > 1 else 0.0
            potential_score = min(1.0, 0.65 * uncertainty + 0.35 * alternative)
        else:
            potential_score = min(1.0, 1.0 - scope_confidence + 0.2)
        bridge_score = min(
            1.0,
            (0.5 if len(domains) > 1 else 0.0)
            + min(0.5, max(0, len(hypotheses) - 1) * 0.2),
        )
        key_score = min(
            1.0,
            0.35 * float(knowledge.payload.get("confidence", 0.0))
            + min(0.25, len(knowledge.payload.get("logical_relations", [])) * 0.06)
            + min(0.2, len(knowledge.evidence_ids) * 0.08)
            + min(0.2, len(knowledge.payload.get("source_identifiers", [])) * 0.05),
        )
        previous = stats.get(knowledge.object_id, {})
        sample_count = int(previous.get("sample_count", 0))
        novelty = 1.0 / (1.0 + sample_count)
        priority_score = min(
            1.0,
            0.32 * missing_score
            + 0.25 * potential_score
            + 0.2 * bridge_score
            + 0.18 * key_score
            + 0.05 * novelty,
        )
        return {
            "knowledge_id": knowledge.object_id,
            "revision": knowledge.revision,
            "title": str(knowledge.payload.get("title", "")),
            "content": str(knowledge.payload.get("content", "")),
            "context": str(knowledge.payload.get("context", "")),
            "mechanism": str(knowledge.payload.get("mechanism", "")),
            "rationale": str(knowledge.payload.get("rationale", "")),
            "domain_ids": domains,
            "domain_hypotheses": hypotheses,
            "subjects": list(scope_payload.get("subjects", [])),
            "tasks": list(scope_payload.get("tasks", [])),
            "unknowns": list(scope_payload.get("unknowns", [])),
            "logical_relations": list(
                knowledge.payload.get("logical_relations", [])
            ),
            "primary_domain": domains[0],
            "priority_score": round(priority_score, 6),
            "missing_score": round(missing_score, 6),
            "potential_score": round(potential_score, 6),
            "bridge_score": round(bridge_score, 6),
            "key_score": round(key_score, 6),
            "previous_sample_count": sample_count,
        }

    def _sample(
        self,
        rows: list[dict[str, Any]],
        batch_size: int,
        ratios: SamplingRatios,
    ) -> list[dict[str, Any]]:
        normalized = ratios.normalized()
        target = min(batch_size, len(rows))
        positive = [key for key, value in normalized.items() if value > 0]
        quotas = {key: 0 for key in normalized}
        if target >= len(positive):
            for key in positive:
                quotas[key] = 1
        remaining = target - sum(quotas.values())
        for key, value in normalized.items():
            quotas[key] += int(remaining * value)
        while sum(quotas.values()) < target:
            key = max(
                normalized,
                key=lambda name: (
                    remaining * normalized[name]
                    - max(0, quotas[name] - (1 if target >= len(positive) else 0))
                ),
            )
            quotas[key] += 1
        selected: list[dict[str, Any]] = []
        selected_ids: set[str] = set()

        def add(candidates: list[dict[str, Any]], count: int, reason: str) -> None:
            for item in candidates:
                if len([row for row in selected if row["sampling_reason"] == reason]) >= count:
                    break
                if item["knowledge_id"] in selected_ids:
                    continue
                copy = dict(item)
                copy["sampling_reason"] = reason
                selected.append(copy)
                selected_ids.add(str(item["knowledge_id"]))

        uncertainty = sorted(
            rows,
            key=lambda item: (
                -(item["missing_score"] + item["potential_score"]),
                item["previous_sample_count"],
                item["knowledge_id"],
            ),
        )
        add(uncertainty, quotas["uncertainty"], "uncertainty")

        bridge = sorted(
            rows,
            key=lambda item: (
                -(item["bridge_score"] + item["potential_score"]),
                item["previous_sample_count"],
                item["knowledge_id"],
            ),
        )
        add(bridge, quotas["bridge"], "bridge")

        replay = sorted(
            rows,
            key=lambda item: (
                -item["key_score"],
                -item["previous_sample_count"],
                item["knowledge_id"],
            ),
        )
        add(replay, quotas["replay"], "replay")

        coverage_candidates: list[dict[str, Any]] = []
        by_domain: dict[str, list[dict[str, Any]]] = {}
        for item in rows:
            by_domain.setdefault(str(item["primary_domain"]), []).append(item)
        while any(by_domain.values()):
            for domain_id in sorted(by_domain):
                if not by_domain[domain_id]:
                    continue
                by_domain[domain_id].sort(
                    key=lambda item: (
                        item["previous_sample_count"],
                        -item["priority_score"],
                        item["knowledge_id"],
                    )
                )
                coverage_candidates.append(by_domain[domain_id].pop(0))
        add(coverage_candidates, quotas["coverage"], "coverage")

        fill = sorted(
            rows,
            key=lambda item: (
                -item["priority_score"],
                item["previous_sample_count"],
                item["knowledge_id"],
            ),
        )
        for item in fill:
            if len(selected) >= target:
                break
            if item["knowledge_id"] in selected_ids:
                continue
            copy = dict(item)
            copy["sampling_reason"] = "priority_fill"
            selected.append(copy)
            selected_ids.add(str(item["knowledge_id"]))
        return selected

    @staticmethod
    def _provider_view(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "knowledge_id": item["knowledge_id"],
            "title": _bounded(item.get("title"), 240),
            "content": _bounded(item.get("content"), 2400),
            "context": _bounded(item.get("context"), 1200),
            "mechanism": _bounded(item.get("mechanism"), 1200),
            "rationale": _bounded(item.get("rationale"), 1200),
            "domain_ids": item.get("domain_ids", []),
            "domain_hypotheses": item.get("domain_hypotheses", []),
            "subjects": item.get("subjects", [])[:12],
            "tasks": item.get("tasks", [])[:12],
            "unknowns": item.get("unknowns", [])[:12],
            "logical_relations": item.get("logical_relations", [])[:20],
            "sampling_signals": {
                "missing_score": item["missing_score"],
                "potential_score": item["potential_score"],
                "bridge_score": item["bridge_score"],
                "key_score": item["key_score"],
            },
        }

    @staticmethod
    def _gap_view(gap: DomainRevision) -> dict[str, Any]:
        payload = gap.payload
        return {
            "gap_id": gap.object_id,
            "question": _bounded(payload.get("question"), 1200),
            "missing_evidence": list(payload.get("missing_evidence", []))[:12],
            "linking_keys": list(payload.get("linking_keys", []))[:16],
            "related_knowledge_ids": list(
                payload.get("related_knowledge_ids", [])
            )[:16],
            "domain_ids": list(payload.get("domain_ids", []))[:8],
        }
