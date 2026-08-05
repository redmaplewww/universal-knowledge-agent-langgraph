from __future__ import annotations

from pathlib import Path

import pytest

from uka_langgraph.infrastructure.settings import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    state_dir = tmp_path / "state"
    return Settings(
        project_root=tmp_path,
        state_dir=state_dir,
        domain_db=state_dir / "domain.sqlite3",
        checkpoint_db=state_dir / "checkpoints.sqlite3",
        object_dir=state_dir / "objects",
        use_llm=False,
        llm_provider=None,
        llm_base_url=None,
        llm_model=None,
        llm_api_key=None,
    )

