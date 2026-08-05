from __future__ import annotations

from uka_langgraph.application.services import (
    CorrectionService,
    IngestionService,
    LifecycleService,
    RetrievalService,
    ServiceContainer,
)
from uka_langgraph.infrastructure.object_store import ContentAddressedObjectStore
from uka_langgraph.infrastructure.parsers import ParserRegistry
from uka_langgraph.infrastructure.providers import (
    DeterministicUnderstandingProvider,
    OpenAICompatibleUnderstandingProvider,
)
from uka_langgraph.infrastructure.settings import Settings
from uka_langgraph.infrastructure.sqlite_repository import SQLiteRepository


def build_services(settings: Settings) -> ServiceContainer:
    settings.initialize_directories()
    repository = SQLiteRepository(settings.domain_db)
    repository.initialize()
    objects = ContentAddressedObjectStore(settings.object_dir)
    parsers = ParserRegistry()
    if settings.use_llm:
        missing = [
            name
            for name, value in {
                "LLM_API_KEY": settings.llm_api_key,
                "LLM_MODEL": settings.llm_model,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f"LLM mode is enabled but configuration is incomplete: {missing}")
        understanding = OpenAICompatibleUnderstandingProvider(
            api_key=settings.llm_api_key or "",
            base_url=settings.llm_base_url,
            model=settings.llm_model or "",
        )
    else:
        understanding = DeterministicUnderstandingProvider()
    ingestion = IngestionService(repository, objects, understanding, parsers)
    return ServiceContainer(
        repository=repository,
        objects=objects,
        ingestion=ingestion,
        corrections=CorrectionService(repository, objects, ingestion),
        lifecycle=LifecycleService(repository, objects),
        retrieval=RetrievalService(repository, objects),
    )
