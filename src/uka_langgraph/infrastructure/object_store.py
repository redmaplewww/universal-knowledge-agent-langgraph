from __future__ import annotations

import hashlib
import os
from pathlib import Path


class ContentAddressedObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        target = self.root / digest[:2] / digest
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary = target.with_suffix(f".{os.getpid()}.tmp")
            temporary.write_bytes(content)
            try:
                temporary.replace(target)
            except FileExistsError:
                temporary.unlink(missing_ok=True)
        return f"sha256:{digest}"

    def put_file(self, path: Path, max_bytes: int = 25 * 1024 * 1024) -> str:
        resolved = path.resolve(strict=True)
        size = resolved.stat().st_size
        if size > max_bytes:
            raise ValueError(f"input exceeds {max_bytes} bytes")
        return self.put_bytes(resolved.read_bytes())

    def read_bytes(self, object_ref: str) -> bytes:
        if not object_ref.startswith("sha256:"):
            raise ValueError("unsupported object reference")
        digest = object_ref.removeprefix("sha256:")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("invalid content hash")
        target = (self.root / digest[:2] / digest).resolve()
        if self.root not in target.parents:
            raise ValueError("object reference escapes store")
        content = target.read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("object content hash mismatch")
        return content

