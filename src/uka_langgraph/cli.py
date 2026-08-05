from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from uka_langgraph.infrastructure.settings import Settings
from uka_langgraph.orchestration.runtime import AgentRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uka-lg", description="Independent LangGraph Universal Knowledge Agent"
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root containing .env.local and the runtime state directory",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize local object, domain, and checkpoint stores")
    doctor = subparsers.add_parser(
        "doctor", help="Show non-secret runtime configuration metadata"
    )
    doctor.add_argument(
        "--connect", action="store_true", help="Perform a redacted provider connection check"
    )

    ingest = subparsers.add_parser("ingest", help="Stage and ingest a UTF-8 text input")
    _add_security_arguments(ingest)
    _add_input_arguments(ingest)
    ingest.add_argument("--auto-approve", action="store_true")
    ingest.add_argument("--thread-id")

    retrieve = subparsers.add_parser("retrieve", help="Retrieve active scoped knowledge")
    _add_security_arguments(retrieve)
    retrieve.add_argument("--query", required=True)
    retrieve.add_argument("--limit", type=int, default=5)
    retrieve.add_argument("--domain")
    retrieve.add_argument("--task")
    retrieve.add_argument("--subject")
    retrieve.add_argument("--geography")
    retrieve.add_argument("--as-of")

    correct = subparsers.add_parser("correct", help="Create a new knowledge revision")
    _add_security_arguments(correct)
    _add_input_arguments(correct)
    correct.add_argument("--target-id", required=True)
    correct.add_argument("--expected-revision", required=True, type=int)
    correct.add_argument("--auto-approve", action="store_true")

    skill = subparsers.add_parser("build-skill", help="Compile an advisory Skill candidate")
    _add_security_arguments(skill)
    skill.add_argument("--knowledge-id", required=True)
    skill.add_argument("--name")
    skill.add_argument("--auto-approve", action="store_true")

    evolve = subparsers.add_parser("evolve", help="Create a governed evolution proposal")
    _add_security_arguments(evolve)
    evolve.add_argument("--target-type", required=True)
    evolve.add_argument("--baseline-revision", required=True)
    evolve.add_argument("--candidate-revision", required=True)
    evolve.add_argument("--offline-evaluation-id", required=True)
    evolve.add_argument("--shadow-evaluation-id", required=True)
    evolve.add_argument("--canary-evaluation-id", required=True)

    resume = subparsers.add_parser("resume", help="Resume an interrupted graph thread")
    _add_security_arguments(resume)
    resume.add_argument("--thread-id", required=True)
    resume.add_argument("--decision", choices=("approve", "reject"))
    resume.add_argument("--target-id")
    resume.add_argument("--expected-revision", type=int)

    status = subparsers.add_parser("status", help="Inspect a persisted thread snapshot")
    _add_security_arguments(status)
    status.add_argument("--thread-id", required=True)

    serve = subparsers.add_parser("serve", help="Run the local HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    return parser


def _add_security_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--actor", default="local-user")
    parser.add_argument("--classification", default="internal")


def _add_input_arguments(parser: argparse.ArgumentParser) -> None:
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--file", type=Path)
    inputs.add_argument("--text")


def _stage_input(runtime: AgentRuntime, args: argparse.Namespace) -> str:
    if args.file is not None:
        return runtime.stage_file(args.file)
    return runtime.stage_text(args.text)


def _security_kwargs(args: argparse.Namespace) -> dict[str, str]:
    return {
        "tenant_id": args.tenant,
        "security_scope_id": args.scope,
        "actor_id": args.actor,
        "classification": args.classification,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except Exception as exc:
        _print({"status": "error", "error_type": type(exc).__name__})
        return 1


def _main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.load(args.project_root)
    if args.command == "doctor":
        result = settings.safe_status()
        if args.connect:
            with AgentRuntime(settings) as runtime:
                result["provider_health"] = runtime.services.ingestion.provider_health()
        _print(result)
        return 0
    if args.command == "serve":
        import uvicorn

        from uka_langgraph.interfaces.api import create_app

        uvicorn.run(create_app(settings), host=args.host, port=args.port)
        return 0

    with AgentRuntime(settings) as runtime:
        if args.command == "init":
            _print({"status": "initialized", **settings.safe_status()})
            return 0
        if args.command == "ingest":
            object_ref = _stage_input(runtime, args)
            result = runtime.invoke(
                intent="ingest",
                input_refs=[object_ref],
                payload={"auto_approve": args.auto_approve},
                thread_id=args.thread_id,
                **_security_kwargs(args),
            )
        elif args.command == "retrieve":
            query_scope = {
                key: value
                for key, value in {
                    "domain": args.domain,
                    "task": args.task,
                    "subject": args.subject,
                    "geography": args.geography,
                }.items()
                if value
            }
            result = runtime.invoke(
                intent="retrieve",
                payload={
                    "query": args.query,
                    "limit": args.limit,
                    "scope": query_scope,
                    "as_of": args.as_of,
                },
                **_security_kwargs(args),
            )
        elif args.command == "correct":
            replacement_ref = _stage_input(runtime, args)
            result = runtime.invoke(
                intent="correct",
                payload={
                    "target_id": args.target_id,
                    "expected_revision": args.expected_revision,
                    "replacement_ref": replacement_ref,
                    "auto_approve": args.auto_approve,
                },
                **_security_kwargs(args),
            )
        elif args.command == "build-skill":
            result = runtime.invoke(
                intent="build_skill",
                payload={
                    "knowledge_id": args.knowledge_id,
                    "name": args.name,
                    "auto_approve": args.auto_approve,
                },
                **_security_kwargs(args),
            )
        elif args.command == "evolve":
            result = runtime.invoke(
                intent="evolve",
                payload={
                    "target_type": args.target_type,
                    "baseline_revision": args.baseline_revision,
                    "candidate_revision": args.candidate_revision,
                    "metrics": {
                        "evaluation_ids": {
                            "offline": args.offline_evaluation_id,
                            "shadow": args.shadow_evaluation_id,
                            "canary": args.canary_evaluation_id,
                        },
                    },
                },
                **_security_kwargs(args),
            )
        elif args.command == "resume":
            if args.decision:
                value: dict[str, Any] = {"decision": args.decision}
            elif args.target_id and args.expected_revision is not None:
                value = {
                    "target_id": args.target_id,
                    "expected_revision": args.expected_revision,
                }
            else:
                raise SystemExit(
                    "resume requires --decision or both --target-id and --expected-revision"
                )
            result = runtime.resume(
                thread_id=args.thread_id,
                value=value,
                tenant_id=args.tenant,
                security_scope_id=args.scope,
            )
        elif args.command == "status":
            result = runtime.status(
                args.thread_id,
                tenant_id=args.tenant,
                security_scope_id=args.scope,
            )
        else:  # pragma: no cover - argparse enforces a known command
            raise AssertionError(args.command)
    _print(result)
    return 0


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=_json_default))


def _json_default(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "__dict__"):
        return vars(value)
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
