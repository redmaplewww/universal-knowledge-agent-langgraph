from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from uka_langgraph.domain.models import (
    DomainRevision,
    Evidence,
    EvidenceLocator,
    OperationReceipt,
    SecurityScope,
)


class SQLiteRepository:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS evidence (
                    tenant_id TEXT NOT NULL,
                    security_scope_id TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    object_ref TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    locator_json TEXT,
                    parent_evidence_id TEXT,
                    PRIMARY KEY (tenant_id, security_scope_id, evidence_id)
                );

                CREATE TABLE IF NOT EXISTS revisions (
                    tenant_id TEXT NOT NULL,
                    security_scope_id TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    evidence_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    parent_revision INTEGER,
                    operation_id TEXT NOT NULL UNIQUE,
                    PRIMARY KEY (
                        tenant_id, security_scope_id, object_type, object_id, revision
                    )
                );

                CREATE TABLE IF NOT EXISTS active_registry (
                    tenant_id TEXT NOT NULL,
                    security_scope_id TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    activated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (tenant_id, security_scope_id, object_type, object_id)
                );

                CREATE TABLE IF NOT EXISTS operation_receipts (
                    operation_id TEXT PRIMARY KEY,
                    operation_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS revisions_scope_type
                    ON revisions (tenant_id, security_scope_id, object_type, object_id);
                CREATE INDEX IF NOT EXISTS evidence_hash
                    ON evidence (tenant_id, security_scope_id, content_hash);

                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                    tenant_id UNINDEXED,
                    security_scope_id UNINDEXED,
                    object_id UNINDEXED,
                    revision UNINDEXED,
                    content,
                    tokenize = 'unicode61'
                );

                CREATE TABLE IF NOT EXISTS runtime_events (
                    event_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    security_scope_id TEXT NOT NULL DEFAULT '',
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS runtime_events_thread
                    ON runtime_events (thread_id, created_at);
                """
            )
            event_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(runtime_events)").fetchall()
            }
            if "security_scope_id" not in event_columns:
                connection.execute(
                    "ALTER TABLE runtime_events "
                    "ADD COLUMN security_scope_id TEXT NOT NULL DEFAULT ''"
                )
            connection.execute("DROP INDEX IF EXISTS runtime_events_thread")
            connection.execute(
                "CREATE INDEX runtime_events_thread ON runtime_events "
                "(tenant_id, security_scope_id, thread_id, created_at)"
            )
            connection.execute("DELETE FROM knowledge_fts")
            connection.execute(
                """
                INSERT INTO knowledge_fts
                    (tenant_id, security_scope_id, object_id, revision, content)
                SELECT r.tenant_id, r.security_scope_id, r.object_id, r.revision,
                       json_extract(r.payload_json, '$.content') || ' ' ||
                       COALESCE(json_extract(r.payload_json, '$.source_identifiers'), '') || ' ' ||
                       COALESCE(json_extract(r.payload_json, '$.domain_ids'), '') || ' ' ||
                       COALESCE(json_extract(r.payload_json, '$.domain_labels'), '') || ' ' ||
                       COALESCE(json_extract(r.payload_json, '$.domain_aliases'), '')
                FROM active_registry a
                JOIN revisions r
                  ON r.tenant_id = a.tenant_id
                 AND r.security_scope_id = a.security_scope_id
                 AND r.object_type = a.object_type
                 AND r.object_id = a.object_id
                 AND r.revision = a.revision
                WHERE a.object_type = 'knowledge'
                """
            )

    def get_receipt(self, operation_id: str) -> OperationReceipt | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM operation_receipts WHERE operation_id = ?", (operation_id,)
            ).fetchone()
        if row is None:
            return None
        return OperationReceipt(
            operation_id=row["operation_id"],
            operation_type=row["operation_type"],
            status=row["status"],
            result=json.loads(row["result_json"]),
            created_at=row["created_at"],
        )

    def put_receipt(self, receipt: OperationReceipt) -> OperationReceipt:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO operation_receipts
                (operation_id, operation_type, status, result_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    receipt.operation_id,
                    receipt.operation_type,
                    receipt.status,
                    _json(receipt.result),
                    receipt.created_at,
                ),
            )
        return self.get_receipt(receipt.operation_id) or receipt

    def put_evidence(self, evidence: Evidence) -> Evidence:
        locator = asdict(evidence.locator) if evidence.locator else None
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO evidence
                (tenant_id, security_scope_id, evidence_id, content_hash, media_type,
                 object_ref, source_type, created_at, locator_json, parent_evidence_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.security.tenant_id,
                    evidence.security.security_scope_id,
                    evidence.evidence_id,
                    evidence.content_hash,
                    evidence.media_type,
                    evidence.object_ref,
                    evidence.source_type,
                    evidence.created_at,
                    _json(locator) if locator else None,
                    evidence.parent_evidence_id,
                ),
            )
        return self.get_evidence(evidence.security, evidence.evidence_id) or evidence

    def get_evidence(self, security: SecurityScope, evidence_id: str) -> Evidence | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM evidence
                WHERE tenant_id = ? AND security_scope_id = ? AND evidence_id = ?
                """,
                (security.tenant_id, security.security_scope_id, evidence_id),
            ).fetchone()
        if row is None:
            return None
        locator_data = json.loads(row["locator_json"]) if row["locator_json"] else None
        locator = EvidenceLocator(**locator_data) if locator_data else None
        return Evidence(
            evidence_id=row["evidence_id"],
            content_hash=row["content_hash"],
            media_type=row["media_type"],
            object_ref=row["object_ref"],
            source_type=row["source_type"],
            security=SecurityScope(
                tenant_id=row["tenant_id"],
                security_scope_id=row["security_scope_id"],
            ),
            created_at=row["created_at"],
            locator=locator,
            parent_evidence_id=row["parent_evidence_id"],
        )

    def put_revision(self, revision: DomainRevision, operation_id: str) -> DomainRevision:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO revisions
                (tenant_id, security_scope_id, object_type, object_id, revision, status,
                 classification, payload_json, evidence_ids_json, created_at,
                 parent_revision, operation_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision.security.tenant_id,
                    revision.security.security_scope_id,
                    revision.object_type,
                    revision.object_id,
                    revision.revision,
                    str(revision.status),
                    revision.security.classification,
                    _json(revision.payload),
                    _json(list(revision.evidence_ids)),
                    revision.created_at,
                    revision.parent_revision,
                    operation_id,
                ),
            )
        stored = self.get_revision_by_operation(operation_id)
        if stored is not None:
            return stored
        if cursor.rowcount == 0:
            existing = self.get_revision(
                revision.security,
                revision.object_type,
                revision.object_id,
                revision.revision,
            )
            if existing is not None and (
                existing.status == str(revision.status)
                and existing.payload == revision.payload
                and existing.evidence_ids == revision.evidence_ids
                and existing.parent_revision == revision.parent_revision
            ):
                return existing
            raise RuntimeError("revision_conflict")
        raise RuntimeError("revision_insert_not_visible")

    def get_revision(
        self,
        security: SecurityScope,
        object_type: str,
        object_id: str,
        revision: int | None = None,
    ) -> DomainRevision | None:
        where = """
            tenant_id = ? AND security_scope_id = ? AND object_type = ? AND object_id = ?
        """
        params: list[Any] = [
            security.tenant_id,
            security.security_scope_id,
            object_type,
            object_id,
        ]
        if revision is None:
            suffix = "ORDER BY revision DESC LIMIT 1"
        else:
            where += " AND revision = ?"
            params.append(revision)
            suffix = "LIMIT 1"
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT * FROM revisions WHERE {where} {suffix}", params
            ).fetchone()
        return _revision_from_row(row) if row else None

    def get_revision_by_operation(self, operation_id: str) -> DomainRevision | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM revisions WHERE operation_id = ?", (operation_id,)
            ).fetchone()
        return _revision_from_row(row) if row else None

    def next_revision(
        self, security: SecurityScope, object_type: str, object_id: str
    ) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(revision), 0) AS current_revision
                FROM revisions
                WHERE tenant_id = ? AND security_scope_id = ?
                  AND object_type = ? AND object_id = ?
                """,
                (
                    security.tenant_id,
                    security.security_scope_id,
                    object_type,
                    object_id,
                ),
            ).fetchone()
        return int(row["current_revision"]) + 1

    def get_active_revision(
        self, security: SecurityScope, object_type: str, object_id: str
    ) -> DomainRevision | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT r.*
                FROM active_registry a
                JOIN revisions r
                  ON r.tenant_id = a.tenant_id
                 AND r.security_scope_id = a.security_scope_id
                 AND r.object_type = a.object_type
                 AND r.object_id = a.object_id
                 AND r.revision = a.revision
                WHERE a.tenant_id = ? AND a.security_scope_id = ?
                  AND a.object_type = ? AND a.object_id = ?
                """,
                (
                    security.tenant_id,
                    security.security_scope_id,
                    object_type,
                    object_id,
                ),
            ).fetchone()
        return _revision_from_row(row) if row else None

    def list_active_knowledge(
        self, security: SecurityScope, limit: int = 100
    ) -> list[DomainRevision]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT r.*
                FROM active_registry a
                JOIN revisions r
                  ON r.tenant_id = a.tenant_id
                 AND r.security_scope_id = a.security_scope_id
                 AND r.object_type = a.object_type
                 AND r.object_id = a.object_id
                 AND r.revision = a.revision
                WHERE a.tenant_id = ? AND a.security_scope_id = ?
                  AND a.object_type = 'knowledge'
                ORDER BY a.activated_at DESC, r.created_at DESC, r.object_id ASC
                LIMIT ?
                """,
                (
                    security.tenant_id,
                    security.security_scope_id,
                    max(1, min(limit, 1000)),
                ),
            ).fetchall()
        return [_revision_from_row(row) for row in rows]

    def activate_revision(
        self, revision: DomainRevision, *, expected_active_revision: int | None = None
    ) -> None:
        existing = self.get_revision(
            revision.security, revision.object_type, revision.object_id, revision.revision
        )
        if existing is None:
            raise LookupError("cannot activate a revision that is not stored")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                """
                SELECT revision FROM active_registry
                WHERE tenant_id = ? AND security_scope_id = ?
                  AND object_type = ? AND object_id = ?
                """,
                (
                    revision.security.tenant_id,
                    revision.security.security_scope_id,
                    revision.object_type,
                    revision.object_id,
                ),
            ).fetchone()
            if expected_active_revision is not None and (
                current is None or int(current["revision"]) != expected_active_revision
            ):
                if current is not None and int(current["revision"]) == revision.revision:
                    return
                raise RuntimeError("stale_active_revision")
            connection.execute(
                """
                INSERT INTO active_registry
                (tenant_id, security_scope_id, object_type, object_id, revision)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (tenant_id, security_scope_id, object_type, object_id)
                DO UPDATE SET revision = excluded.revision, activated_at = CURRENT_TIMESTAMP
                """,
                (
                    revision.security.tenant_id,
                    revision.security.security_scope_id,
                    revision.object_type,
                    revision.object_id,
                    revision.revision,
                ),
            )
            if revision.object_type == "knowledge":
                connection.execute(
                    """
                    DELETE FROM knowledge_fts
                    WHERE tenant_id = ? AND security_scope_id = ? AND object_id = ?
                    """,
                    (
                        revision.security.tenant_id,
                        revision.security.security_scope_id,
                        revision.object_id,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO knowledge_fts
                        (tenant_id, security_scope_id, object_id, revision, content)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        revision.security.tenant_id,
                        revision.security.security_scope_id,
                        revision.object_id,
                        revision.revision,
                        _fts_document(existing.payload),
                    ),
                )

    def search_active_knowledge(
        self, security: SecurityScope, query: str, limit: int
    ) -> list[DomainRevision]:
        # Security and active revision filtering are part of the same SQL plan as FTS matching.
        identifiers = re.findall(
            r"\b[A-Za-z][A-Za-z0-9]{1,15}(?:-[A-Za-z0-9]{1,16})+\b",
            query,
        )
        terms = identifiers or [
            term for term in re.findall(r"[\w-]+", query, flags=re.UNICODE) if term
        ]
        if not terms:
            return []
        operator = " AND " if identifiers else " OR "
        if identifiers:
            match_query = operator.join(
                f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms[:16]
            )
        else:
            # Prefix matching keeps short Latin tokens searchable when FTS unicode61
            # attaches adjacent CJK text to the same token (for example, "Agent开发").
            match_query = operator.join(
                f'"{term.replace(chr(34), chr(34) * 2)}"*' for term in terms[:16]
            )
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT r.*
                FROM knowledge_fts f
                JOIN active_registry a
                  ON a.tenant_id = f.tenant_id
                 AND a.security_scope_id = f.security_scope_id
                 AND a.object_type = 'knowledge'
                 AND a.object_id = f.object_id
                 AND a.revision = f.revision
                JOIN revisions r
                  ON r.tenant_id = a.tenant_id
                 AND r.security_scope_id = a.security_scope_id
                 AND r.object_type = a.object_type
                 AND r.object_id = a.object_id
                 AND r.revision = a.revision
                WHERE a.tenant_id = ? AND a.security_scope_id = ?
                  AND knowledge_fts MATCH ?
                ORDER BY bm25(knowledge_fts), a.activated_at DESC, r.object_id ASC
                LIMIT ?
                """,
                (
                    security.tenant_id,
                    security.security_scope_id,
                    match_query,
                    max(1, min(limit, 1000)),
                ),
            ).fetchall()
        return [_revision_from_row(row) for row in rows]

    def count(self, object_type: str, security: SecurityScope | None = None) -> int:
        query = "SELECT COUNT(*) AS count FROM revisions WHERE object_type = ?"
        params: list[Any] = [object_type]
        if security is not None:
            query += " AND tenant_id = ? AND security_scope_id = ?"
            params.extend([security.tenant_id, security.security_scope_id])
        with self._connect() as connection:
            return int(connection.execute(query, params).fetchone()["count"])

    def record_event(
        self,
        *,
        event_id: str,
        thread_id: str,
        request_id: str,
        tenant_id: str,
        security_scope_id: str,
        event_type: str,
        status: str,
        metadata: dict[str, object],
        created_at: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO runtime_events
                (event_id, thread_id, request_id, tenant_id, security_scope_id,
                 event_type, status,
                 metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    thread_id,
                    request_id,
                    tenant_id,
                    security_scope_id,
                    event_type,
                    status,
                    _json(metadata),
                    created_at,
                ),
            )

    def list_events(
        self,
        thread_id: str,
        tenant_id: str,
        security_scope_id: str,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id, thread_id, request_id, tenant_id, security_scope_id,
                       event_type, status,
                       metadata_json, created_at
                FROM runtime_events
                WHERE thread_id = ? AND tenant_id = ? AND security_scope_id = ?
                ORDER BY created_at ASC, event_id ASC
                LIMIT ?
                """,
                (
                    thread_id,
                    tenant_id,
                    security_scope_id,
                    max(1, min(limit, 1000)),
                ),
            ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "thread_id": row["thread_id"],
                "request_id": row["request_id"],
                "tenant_id": row["tenant_id"],
                "security_scope_id": row["security_scope_id"],
                "event_type": row["event_type"],
                "status": row["status"],
                "metadata": json.loads(row["metadata_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fts_document(payload: dict[str, Any]) -> str:
    values: list[str] = [str(payload.get("content", ""))]
    for key in ("source_identifiers", "domain_ids", "domain_labels", "domain_aliases"):
        raw = payload.get(key, [])
        if isinstance(raw, (list, tuple, set)):
            values.extend(str(item) for item in raw)
        elif raw:
            values.append(str(raw))
    return " ".join(value for value in values if value)


def _revision_from_row(row: sqlite3.Row) -> DomainRevision:
    return DomainRevision(
        object_type=row["object_type"],
        object_id=row["object_id"],
        revision=int(row["revision"]),
        status=row["status"],
        security=SecurityScope(
            tenant_id=row["tenant_id"],
            security_scope_id=row["security_scope_id"],
            classification=row["classification"],
        ),
        payload=json.loads(row["payload_json"]),
        evidence_ids=tuple(json.loads(row["evidence_ids_json"])),
        created_at=row["created_at"],
        parent_revision=row["parent_revision"],
    )
