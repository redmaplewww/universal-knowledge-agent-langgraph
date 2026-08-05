from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable

from uka_langgraph.domain.models import RiskLevel

DOMAIN_ALIASES: dict[str, tuple[str, ...]] = {
    "general": ("general", "general knowledge", "通用", "一般知识"),
    "mechanical_engineering": (
        "mechanical engineering",
        "mechanical maintenance",
        "industrial equipment maintenance",
        "equipment maintenance",
        "maintenance engineering",
        "机械工程",
        "机械维护",
        "设备维护",
    ),
    "finance": (
        "finance",
        "financial",
        "financial accounting",
        "accounting",
        "revenue recognition",
        "财务",
        "会计",
        "财务与会计",
    ),
    "medicine": (
        "medicine",
        "medical",
        "clinical",
        "healthcare",
        "health care",
        "emergency care",
        "医疗",
        "医学",
        "临床",
        "急救",
    ),
    "legal": (
        "legal",
        "law",
        "compliance",
        "data privacy compliance",
        "data protection",
        "privacy law",
        "法律",
        "合规",
        "隐私保护",
    ),
    "software_engineering": (
        "software engineering",
        "software",
        "devops",
        "site reliability engineering",
        "sre",
        "deployment automation",
        "软件工程",
        "软件开发",
        "运维",
    ),
    "agriculture": (
        "agriculture",
        "agricultural",
        "agronomy",
        "farming",
        "crop management",
        "greenhouse management",
        "农业",
        "农学",
        "种植",
    ),
    "education": (
        "education",
        "educational",
        "pedagogy",
        "teaching",
        "learning science",
        "教育",
        "教学",
    ),
    "astrophysics": (
        "astrophysics",
        "astronomy",
        "cosmology",
        "天体物理",
        "天文学",
        "宇宙学",
    ),
    "logistics": (
        "logistics",
        "supply chain",
        "cold chain",
        "transport logistics",
        "物流",
        "供应链",
        "冷链",
    ),
    "linguistics": (
        "linguistics",
        "language science",
        "morphology",
        "语言学",
        "形态学",
    ),
    "cybersecurity": (
        "cybersecurity",
        "information security",
        "computer security",
        "网络安全",
        "信息安全",
    ),
    "electrical_engineering": (
        "electrical engineering",
        "electronics engineering",
        "电气工程",
        "电子工程",
    ),
    "civil_engineering": ("civil engineering", "construction engineering", "土木工程"),
    "materials_science": ("materials science", "material science", "材料科学"),
    "manufacturing": ("manufacturing", "industrial manufacturing", "制造", "制造业"),
    "energy": ("energy", "power systems", "renewable energy", "能源", "电力系统"),
    "environment": (
        "environment",
        "environmental science",
        "ecology",
        "环境科学",
        "生态学",
    ),
    "physics": ("physics", "物理学"),
    "chemistry": ("chemistry", "化学"),
    "biology": ("biology", "biological science", "生物学"),
    "mathematics": ("mathematics", "math", "数学"),
    "economics": ("economics", "economic science", "经济学"),
    "business": ("business", "business operations", "management", "商业", "管理学"),
    "psychology": ("psychology", "心理学"),
    "social_science": ("social science", "sociology", "社会科学", "社会学"),
    "history": ("history", "历史", "历史学"),
    "arts": ("arts", "art", "design arts", "艺术", "设计艺术"),
    "unknown": ("unknown", "unclassified", "未知", "未分类"),
}

HIGH_RISK_DOMAINS = frozenset({"medicine"})
SENSITIVE_DOMAINS = frozenset({"finance", "legal", "cybersecurity"})

DOMAIN_PARENTS: dict[str, frozenset[str]] = {
    "finance": frozenset({"business", "economics", "general"}),
    "medicine": frozenset({"biology", "general"}),
    "legal": frozenset({"business", "social_science", "general"}),
    "software_engineering": frozenset({"general"}),
    "mechanical_engineering": frozenset({"manufacturing", "general"}),
    "electrical_engineering": frozenset({"general"}),
    "civil_engineering": frozenset({"general"}),
    "materials_science": frozenset({"physics", "chemistry", "general"}),
    "astrophysics": frozenset({"physics", "general"}),
    "linguistics": frozenset({"social_science", "general"}),
}


def canonical_domain_id(value: str) -> str:
    normalized = _normalize(value)
    if not normalized:
        return "unknown"
    canonical_literal = normalized.replace(" ", "_")
    if canonical_literal in DOMAIN_ALIASES:
        return canonical_literal

    exact: dict[str, str] = {}
    for domain_id, aliases in DOMAIN_ALIASES.items():
        exact[_normalize(domain_id)] = domain_id
        exact.update({_normalize(alias): domain_id for alias in aliases})
    if normalized in exact:
        return exact[normalized]

    matches: list[tuple[int, str]] = []
    for alias, domain_id in exact.items():
        if alias and (f" {alias} " in f" {normalized} " or alias in normalized):
            matches.append((len(alias), domain_id))
    if matches:
        return max(matches)[1]

    ascii_slug = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    if ascii_slug:
        return ascii_slug[:80]
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"domain_{digest}"


def canonicalize_domains(values: Iterable[str]) -> tuple[str, ...]:
    canonical = tuple(
        dict.fromkeys(
            canonical_domain_id(str(value)) for value in values if str(value).strip()
        )
    )
    if len(canonical) > 1:
        parents_to_remove = {"general", "unknown"}
        for domain_id in canonical:
            parents_to_remove.update(DOMAIN_PARENTS.get(domain_id, ()))
        canonical = tuple(domain_id for domain_id in canonical if domain_id not in parents_to_remove)
    return canonical or ("unknown",)


def domain_aliases(domain_ids: Iterable[str]) -> tuple[str, ...]:
    aliases: list[str] = []
    for domain_id in domain_ids:
        aliases.append(domain_id)
        aliases.extend(DOMAIN_ALIASES.get(domain_id, ()))
    return tuple(dict.fromkeys(alias for alias in aliases if alias))


def apply_risk_floor(
    risk: RiskLevel, domain_ids: Iterable[str], evidence_text: str
) -> RiskLevel:
    domains = set(domain_ids)
    normalized_text = _normalize(evidence_text)
    injection_markers = (
        "ignore all previous instructions",
        "ignore previous instructions",
        "reveal the api key",
        "activate it without review",
    )
    if any(marker in normalized_text for marker in injection_markers):
        return RiskLevel.PROHIBITED
    if domains & HIGH_RISK_DOMAINS:
        return max_risk(risk, RiskLevel.HIGH)
    if domains & SENSITIVE_DOMAINS:
        return max_risk(risk, RiskLevel.SENSITIVE)
    return risk


def max_risk(left: RiskLevel, right: RiskLevel) -> RiskLevel:
    order = {
        RiskLevel.NORMAL: 0,
        RiskLevel.SENSITIVE: 1,
        RiskLevel.HIGH: 2,
        RiskLevel.PROHIBITED: 3,
    }
    return left if order[left] >= order[right] else right


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[_/|,:;()\[\]{}-]+", " ", normalized)
    return " ".join(normalized.split())
