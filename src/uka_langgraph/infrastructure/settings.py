from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    project_root: Path
    state_dir: Path
    domain_db: Path
    checkpoint_db: Path
    object_dir: Path
    use_llm: bool
    llm_provider: str | None
    llm_base_url: str | None
    llm_model: str | None
    llm_api_key: str | None
    graph_version: str = "0.3.0"
    web_research_enabled: bool = False
    web_search_url: str | None = None
    web_search_engine: str = "search_std"
    web_search_count: int = 5
    web_search_max_queries: int = 4
    web_search_timeout_seconds: float = 20.0

    @classmethod
    def load(cls, project_root: Path | str | None = None) -> Settings:
        root = Path(project_root or Path.cwd()).resolve()
        load_dotenv(root / ".env.local", override=False)
        configured_state = os.getenv("UKA_STATE_DIR", ".uka-state")
        state_dir = Path(configured_state)
        if not state_dir.is_absolute():
            state_dir = root / state_dir
        state_dir = state_dir.resolve()
        api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        model = os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL")
        use_llm_value = os.getenv("UKA_USE_LLM", "auto").strip().lower()
        use_llm = (
            bool(api_key and model)
            if use_llm_value == "auto"
            else use_llm_value in {"1", "true", "yes", "llm"}
        )
        llm_provider = os.getenv("LLM_PROVIDER") or os.getenv("OPENAI_PROVIDER")
        llm_base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        research_value = os.getenv("UKA_WEB_RESEARCH", "auto").strip().lower()
        auto_research = bool(
            use_llm
            and (
                "bigmodel.cn" in (llm_base_url or "").casefold()
                or "glm" in (model or "").casefold()
                or "zhipu" in (llm_provider or "").casefold()
            )
        )
        web_research_enabled = (
            auto_research
            if research_value == "auto"
            else research_value in {"1", "true", "yes", "enabled"}
        )
        web_search_url = os.getenv("UKA_WEB_SEARCH_URL")
        if not web_search_url and web_research_enabled and auto_research:
            web_search_url = "https://open.bigmodel.cn/api/paas/v4/web_search"
        return cls(
            project_root=root,
            state_dir=state_dir,
            domain_db=state_dir / "domain.sqlite3",
            checkpoint_db=state_dir / "checkpoints.sqlite3",
            object_dir=state_dir / "objects",
            use_llm=use_llm,
            llm_provider=llm_provider,
            llm_base_url=llm_base_url,
            llm_model=model,
            llm_api_key=api_key,
            web_research_enabled=web_research_enabled,
            web_search_url=web_search_url,
            web_search_engine=os.getenv("UKA_WEB_SEARCH_ENGINE", "search_std"),
            web_search_count=max(1, min(int(os.getenv("UKA_WEB_SEARCH_COUNT", "5")), 10)),
            web_search_max_queries=max(
                1, min(int(os.getenv("UKA_WEB_SEARCH_MAX_QUERIES", "4")), 8)
            ),
            web_search_timeout_seconds=max(
                3.0, min(float(os.getenv("UKA_WEB_SEARCH_TIMEOUT_SECONDS", "20")), 60.0)
            ),
        )

    def initialize_directories(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.object_dir.mkdir(parents=True, exist_ok=True)

    def safe_status(self) -> dict[str, object]:
        return {
            "project_root": str(self.project_root),
            "state_dir": str(self.state_dir),
            "graph_version": self.graph_version,
            "provider_mode": "llm" if self.use_llm else "deterministic",
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "llm_base_url_configured": bool(self.llm_base_url),
            "llm_credential_configured": bool(self.llm_api_key),
            "web_research_enabled": self.web_research_enabled,
            "web_search_endpoint_configured": bool(self.web_search_url),
            "web_search_engine": self.web_search_engine,
            "web_search_max_queries": self.web_search_max_queries,
        }
