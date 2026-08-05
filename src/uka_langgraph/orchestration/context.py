from __future__ import annotations

from dataclasses import dataclass

from uka_langgraph.application.services import ServiceContainer


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    services: ServiceContainer
    graph_version: str
    max_fanout: int = 32

