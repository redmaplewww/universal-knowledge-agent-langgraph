from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from aawo_agent_tester.adapters import HttpAdapter
from aawo_agent_tester.ledger import EvidenceLedger
from aawo_agent_tester.models import AgentContractProfile, CustomerJourney, JourneyStep
from aawo_agent_tester.runner import CustomerSimulationRunner

BASE_URL = "http://127.0.0.1:8882"
TENANT = "demo-ui"
SCOPE = "private"
IDENTIFIER = "AGENT-EVO-86"

BASELINE_SOURCE = (
    "AGENT-EVO-86：在多智能体研发中，AI 起初只应提出 Agent 修改建议。"
    "只有当沙箱回归连续通过、权限边界已验证并且人工批准后，AI 才能接管 Agent 的实际修改。"
    "修改完成后，失败样本要回流到评估集；如果安全指标退化，系统必须回滚到上一个稳定版本。"
    "因此，所谓“AI 接管 Agent 修改”不是无条件自治，而是由证据、门禁和回滚共同约束的渐进授权。"
)
REFINEMENT_SOURCE = (
    "AGENT-EVO-86 补充：即使沙箱回归通过，也不能永久扩大 AI 权限。"
    "每次生产故障都要形成失败模式、触发条件和回滚结果三部分经验，并在下一次 Agent 修改前重新检索；"
    "如果新证据与既有策略冲突，只能生成演进候选，经过离线、影子、灰度和人工四道门禁后才能替换原策略。"
)
DOMAIN_CASES = (
    {
        "id": "cybersecurity",
        "domain": "cybersecurity",
        "identifier": "CYB-IR-21",
        "text": (
            "CYB-IR-21：特权服务账号一旦出现异常登录，不能只做密码轮换。"
            "因为旧会话和派生令牌可能继续有效，响应人员必须先冻结会话、吊销令牌，再轮换凭据并核对审计日志。"
            "只有四个步骤都完成，账号才能恢复使用；否则事件保持开放状态。"
        ),
        "query": "CYB-IR-21 异常登录后为什么不能只轮换密码",
    },
    {
        "id": "finance",
        "domain": "finance",
        "identifier": "FIN-DEP-33",
        "text": (
            "FIN-DEP-33：可退押金在客户仍享有退款权时属于负债，收到现金本身不构成收入。"
            "只有退款权到期、履约义务已经满足且金额能够可靠计量时，财务人员才能确认收入。"
            "如果合同仍允许退款，应继续保留负债并披露到期条件。"
        ),
        "query": "FIN-DEP-33 可退押金什么时候才能确认收入",
    },
    {
        "id": "mechanical_engineering",
        "domain": "mechanical_engineering",
        "identifier": "MECH-VIB-47",
        "text": (
            "MECH-VIB-47：旋转设备振动突然升高时，直接更换轴承可能掩盖根因。"
            "维护人员应先比较负载、转速和温度，再检查对中与润滑；只有频谱仍指向轴承缺陷时才安排更换。"
            "检修后必须在相同工况复测，确认振动回到基线。"
        ),
        "query": "MECH-VIB-47 振动升高时为什么不能直接换轴承",
    },
    {
        "id": "education",
        "domain": "education",
        "identifier": "EDU-FBK-58",
        "text": (
            "EDU-FBK-58：形成性测验的价值不在分数本身，而在及时暴露概念误区。"
            "教师应按错误模式分组，先调整讲解和练习，再安排间隔复测；如果只公布排名，学生不会获得可执行反馈。"
            "后续教学是否有效，应以复测中误区减少而不是平均分上升作为主要依据。"
        ),
        "query": "EDU-FBK-58 形成性测验怎样用于改进后续教学",
    },
)


class ExperienceGate:
    def __init__(self, evidence_dir: Path) -> None:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = EvidenceLedger(evidence_dir / "evidence-ledger.sqlite3")
        self.runner = CustomerSimulationRunner(self.ledger)
        self.runs: list[dict[str, Any]] = []

    async def request(
        self,
        scenario_id: str,
        method: str,
        url: str,
        payload: dict[str, Any] | None,
        *,
        required_keys: tuple[str, ...] = (),
        expected_status: str | None = None,
        side_effect_policy: str = "read_only",
        output_schema: dict[str, Any] | None = None,
    ) -> tuple[Any, str]:
        assertions: list[dict[str, Any]] = []
        if required_keys:
            assertions.append({"kind": "contains_keys", "keys": list(required_keys)})
        if expected_status is not None:
            assertions.append(
                {"kind": "path_equals", "path": "status", "value": expected_status}
            )
        journey = CustomerJourney(
            scenario_id=scenario_id,
            goal=f"验证上下文经验沉淀客户旅程：{scenario_id}",
            actor={
                "tenant_id": TENANT,
                "security_scope_id": SCOPE,
                "fixture": "isolated-real-llm",
            },
            side_effect_policy=side_effect_policy,
            steps=(
                JourneyStep("request", "user_input", payload=payload or {}),
                JourneyStep("assert", "expect", assertions=tuple(assertions)),
            ),
        )
        profile = AgentContractProfile(
            agent_id="universal-knowledge-agent-langgraph",
            adapter_id=f"http:{scenario_id}",
            purpose="Contextual experience, evidence comparison, retrieval, and evolution gate",
            output_schema=output_schema or {"type": "object"},
            revision=5,
        )
        run = await self.runner.run(
            journey,
            profile,
            HttpAdapter(f"http:{scenario_id}", url, method=method, timeout=150.0),
        )
        self.runs.append(run.to_dict())
        output: Any = None
        if run.step_results and run.step_results[0].observation:
            output = run.step_results[0].observation.output
        return output, run.status.value


def common_payload() -> dict[str, str]:
    return {
        "tenant_id": TENANT,
        "security_scope_id": SCOPE,
        "actor_id": "aawo-experience-customer",
    }


def knowledge_entries(output: Any) -> list[dict[str, Any]]:
    if not isinstance(output, list):
        return []
    return [item for item in output if isinstance(item, dict)]


def database_checks(db_path: Path, baseline_id: str, refined_id: str) -> dict[str, bool]:
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT object_type, object_id, status, payload_json
            FROM revisions
            WHERE tenant_id=? AND security_scope_id=?
              AND object_type IN ('knowledge', 'evolution')
            """,
            (TENANT, SCOPE),
        ).fetchall()
        active_evolution = connection.execute(
            """
            SELECT COUNT(*) FROM active_registry
            WHERE tenant_id=? AND security_scope_id=? AND object_type='evolution'
            """,
            (TENANT, SCOPE),
        ).fetchone()[0]
    knowledge = {
        row["object_id"]: json.loads(row["payload_json"])
        for row in rows
        if row["object_type"] == "knowledge"
    }
    evolution_rows = [row for row in rows if row["object_type"] == "evolution"]
    return {
        "baseline_and_refinement_persisted": baseline_id in knowledge
        and refined_id in knowledge,
        "no_orphan_claim_entry": all(
            payload.get("content") != "AI 才能接管 Agent 修改。"
            for payload in knowledge.values()
        ),
        "evolution_candidate_persisted": any(
            row["status"] == "candidate" for row in evolution_rows
        ),
        "evolution_not_auto_activated": active_evolution == 0,
    }


async def main() -> int:
    root = Path(__file__).resolve().parents[1]
    run_root = root / "build" / "contextual-experience-gate-20260810d"
    evidence_dir = run_root / "evidence"
    gate = ExperienceGate(evidence_dir)
    base = common_payload()

    health, health_run = await gate.request(
        "experience.health.real_llm",
        "GET",
        f"{BASE_URL}/health?connect=true",
        None,
        required_keys=("provider_mode", "llm_model", "provider_health"),
    )

    baseline_thread = "experience-baseline"
    baseline_ingest, baseline_ingest_run = await gate.request(
        "experience.baseline.ingest",
        "POST",
        f"{BASE_URL}/v1/ingest",
        {
            **base,
            "text": BASELINE_SOURCE,
            "classification": "internal",
            "auto_approve": False,
            "thread_id": baseline_thread,
            "request_id": baseline_thread,
        },
        required_keys=("thread_id", "__interrupt__"),
        expected_status="accepted",
        side_effect_policy="sandbox_write",
    )
    baseline_approved, baseline_approve_run = await gate.request(
        "experience.baseline.approve",
        "POST",
        f"{BASE_URL}/v1/threads/{baseline_thread}/resume?"
        + urlencode({"tenant_id": TENANT, "security_scope_id": SCOPE}),
        {"value": {"decision": "approve"}},
        required_keys=("knowledge_ids", "evidence_ids", "scope_ids"),
        expected_status="active",
        side_effect_policy="human_approved_write",
    )
    baseline_id = str((baseline_approved or {}).get("knowledge_ids", [""])[0])

    thread_status, status_run = await gate.request(
        "experience.thread.status",
        "GET",
        f"{BASE_URL}/v1/threads/{baseline_thread}?"
        + urlencode({"tenant_id": TENANT, "security_scope_id": SCOPE}),
        None,
        required_keys=("thread_id", "values", "checkpoint_id"),
    )
    baseline_library, baseline_library_run = await gate.request(
        "experience.baseline.library",
        "GET",
        f"{BASE_URL}/v1/knowledge?"
        + urlencode(
            {"tenant_id": TENANT, "security_scope_id": SCOPE, "limit": "20"}
        ),
        None,
        output_schema={"type": "array"},
    )
    baseline_entries = knowledge_entries(baseline_library)
    baseline_entry = next(
        (item for item in baseline_entries if item.get("knowledge_id") == baseline_id),
        {},
    )

    retrieval, retrieval_run = await gate.request(
        "experience.baseline.retrieve",
        "POST",
        f"{BASE_URL}/v1/retrieve",
        {
            **base,
            "query": "AGENT-EVO-86 AI 接管 Agent 修改需要哪些前提和回滚机制",
            "query_scope": {"domain": "software_engineering"},
            "limit": 5,
        },
        required_keys=("status", "response", "knowledge_ids"),
        expected_status="review_required",
    )

    refinement_thread = "experience-refinement"
    refinement_ingest, refinement_ingest_run = await gate.request(
        "experience.refinement.ingest",
        "POST",
        f"{BASE_URL}/v1/ingest",
        {
            **base,
            "text": REFINEMENT_SOURCE,
            "classification": "internal",
            "auto_approve": False,
            "thread_id": refinement_thread,
            "request_id": refinement_thread,
        },
        required_keys=("thread_id", "__interrupt__"),
        expected_status="accepted",
        side_effect_policy="sandbox_write",
    )
    refinement_approved, refinement_approve_run = await gate.request(
        "experience.refinement.approve",
        "POST",
        f"{BASE_URL}/v1/threads/{refinement_thread}/resume?"
        + urlencode({"tenant_id": TENANT, "security_scope_id": SCOPE}),
        {"value": {"decision": "approve"}},
        required_keys=("knowledge_ids", "evolution_ids"),
        expected_status="active",
        side_effect_policy="human_approved_write",
    )
    refined_id = str((refinement_approved or {}).get("knowledge_ids", [""])[0])
    final_library, final_library_run = await gate.request(
        "experience.refinement.library",
        "GET",
        f"{BASE_URL}/v1/knowledge?"
        + urlencode(
            {"tenant_id": TENANT, "security_scope_id": SCOPE, "limit": "20"}
        ),
        None,
        output_schema={"type": "array"},
    )
    final_entries = knowledge_entries(final_library)
    refined_entry = next(
        (item for item in final_entries if item.get("knowledge_id") == refined_id),
        {},
    )
    domain_results: list[dict[str, Any]] = []
    for case in DOMAIN_CASES:
        thread_id = f"experience-domain-{case['id']}"
        ingested, ingest_run = await gate.request(
            f"experience.domain.{case['id']}.ingest",
            "POST",
            f"{BASE_URL}/v1/ingest",
            {
                **base,
                "text": case["text"],
                "classification": "internal",
                "auto_approve": False,
                "thread_id": thread_id,
                "request_id": thread_id,
            },
            required_keys=("thread_id", "__interrupt__"),
            expected_status="accepted",
            side_effect_policy="sandbox_write",
        )
        approved, approve_run = await gate.request(
            f"experience.domain.{case['id']}.approve",
            "POST",
            f"{BASE_URL}/v1/threads/{thread_id}/resume?"
            + urlencode({"tenant_id": TENANT, "security_scope_id": SCOPE}),
            {"value": {"decision": "approve"}},
            required_keys=("knowledge_ids", "scope_ids", "evidence_ids"),
            expected_status="active",
            side_effect_policy="human_approved_write",
        )
        knowledge_ids = (approved or {}).get("knowledge_ids", [])
        retrieved, retrieve_run = await gate.request(
            f"experience.domain.{case['id']}.retrieve",
            "POST",
            f"{BASE_URL}/v1/retrieve",
            {
                **base,
                "query": case["query"],
                "query_scope": {"domain": case["domain"]},
                "limit": 5,
            },
            required_keys=("status", "response", "knowledge_ids"),
        )
        domain_results.append(
            {
                "case": case,
                "knowledge_id": str(knowledge_ids[0]) if knowledge_ids else "",
                "ingest_run": ingest_run,
                "approve_run": approve_run,
                "retrieve_run": retrieve_run,
                "retrieved": retrieved,
                "interrupted": bool((ingested or {}).get("__interrupt__")),
            }
        )
    domain_library, domain_library_run = await gate.request(
        "experience.domain.library",
        "GET",
        f"{BASE_URL}/v1/knowledge?"
        + urlencode(
            {"tenant_id": TENANT, "security_scope_id": SCOPE, "limit": "50"}
        ),
        None,
        output_schema={"type": "array"},
    )
    domain_entries = knowledge_entries(domain_library)
    denied_library, denied_run = await gate.request(
        "experience.cross_tenant.library",
        "GET",
        f"{BASE_URL}/v1/knowledge?"
        + urlencode(
            {
                "tenant_id": "different-tenant",
                "security_scope_id": SCOPE,
                "limit": "20",
            }
        ),
        None,
        output_schema={"type": "array"},
    )

    retrieval_pack = (retrieval or {}).get("response", {}).get("evidence_pack", {})
    retrieval_items = retrieval_pack.get("items", [])
    learning = refined_entry.get("learning", {})
    evolution = refined_entry.get("evolution") or {}
    domain_checks: dict[str, bool] = {}
    for result in domain_results:
        case = result["case"]
        entry = next(
            (
                item
                for item in domain_entries
                if item.get("knowledge_id") == result["knowledge_id"]
            ),
            {},
        )
        retrieved = result["retrieved"] or {}
        retrieved_items = retrieved.get("response", {}).get("evidence_pack", {}).get(
            "items", []
        )
        domain_checks[f"domain_{case['id']}"] = (
            result["ingest_run"]
            == result["approve_run"]
            == result["retrieve_run"]
            == "pass"
            and result["interrupted"]
            and entry.get("domain_ids") == [case["domain"]]
            and int(entry.get("experience_schema_version", 0)) >= 2
            and bool(entry.get("title"))
            and bool(entry.get("context"))
            and bool(entry.get("rationale"))
            and bool(entry.get("logical_relations"))
            and entry.get("evidence_integrity") == "verified"
            and bool(entry.get("source_evidence"))
            and result["knowledge_id"] in retrieved.get("knowledge_ids", [])
            and bool(retrieved_items)
        )
    checks = {
        "health_real_llm": health_run == "pass"
        and isinstance(health, dict)
        and health.get("provider_mode") == "llm"
        and health.get("llm_model") == "glm-5.2"
        and health.get("provider_health", {}).get("status") == "ok",
        "baseline_journey": baseline_ingest_run == baseline_approve_run == "pass"
        and bool((baseline_ingest or {}).get("__interrupt__")),
        "thread_status_contract_fixed": status_run == "pass"
        and (thread_status or {}).get("thread_id") == baseline_thread,
        "library_schema": baseline_library_run == "pass"
        and int(baseline_entry.get("experience_schema_version", 0)) >= 2,
        "single_contextual_experience": len(baseline_entries) == 1
        and bool(baseline_entry.get("title"))
        and bool(baseline_entry.get("context"))
        and bool(baseline_entry.get("rationale"))
        and baseline_entry.get("content") != "AI 才能接管 Agent 修改。",
        "logic_preserved": len(baseline_entry.get("logical_relations", [])) >= 2,
        "original_comparison_available": baseline_entry.get("evidence_integrity")
        == "verified"
        and bool(baseline_entry.get("source_evidence")),
        "retrieval_returns_experience_and_source": retrieval_run == "pass"
        and bool(retrieval_items)
        and bool(retrieval_items[0].get("experience", {}).get("title"))
        and bool(retrieval_items[0].get("evidence", [{}])[0].get("excerpt")),
        "refinement_journey": refinement_ingest_run
        == refinement_approve_run
        == final_library_run
        == "pass",
        "accumulated_knowledge_used": learning.get("knowledge_delta") == "refines"
        and baseline_id in learning.get("derived_from_knowledge_ids", []),
        "evolution_is_governed": evolution.get("status") == "candidate"
        and evolution.get("automatic_activation") is False
        and evolution.get("required_gates")
        == ["offline", "shadow", "canary", "human"],
        "cross_tenant_isolated": denied_run == "pass" and denied_library == [],
        "four_domain_library_contract": domain_library_run == "pass"
        and len(domain_results) == 4,
    }
    checks.update(domain_checks)
    checks.update(database_checks(run_root / "state" / "domain.sqlite3", baseline_id, refined_id))
    integrity_errors = list(gate.ledger.verify_integrity())
    report = {
        "target": {"base_url": BASE_URL, "adapter": "HttpAdapter"},
        "profile": {
            "agent_id": "universal-knowledge-agent-langgraph",
            "contract_revision": "contextual-experience-v2",
            "provider": "openai-compatible:glm-5.2",
        },
        "journey": {
            "goal": "验证原文逻辑绑定、综合经验、可检索展示和受治理自进化",
            "side_effect_scope": "isolated local fixture",
        },
        "status": "pass" if all(checks.values()) and not integrity_errors else "fail",
        "checks": checks,
        "runs": gate.runs,
        "ledger_records": len(gate.ledger.records()),
        "ledger_integrity_errors": integrity_errors,
        "limitations": [
            "This is an isolated local real-LLM gate, not a production IAM or capacity certification.",
            "The two-source evolution journey validates knowledge reuse and fail-closed proposal creation; it does not auto-activate an evolution.",
            "Four representative domains validate routing and contextual organization; this is not a mathematical proof over every possible domain or expert certification.",
        ],
    }
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    report_path = evidence_dir / "contextual-experience-gate-report.json"
    report_path.write_text(encoded, encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(report_path),
                "report_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
                "ledger_records": report["ledger_records"],
                "ledger_integrity_errors": integrity_errors,
                "checks": checks,
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    gate.ledger.close()
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
