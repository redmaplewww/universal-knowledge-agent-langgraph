from __future__ import annotations

import pytest

from uka_langgraph.infrastructure.object_store import ContentAddressedObjectStore


def test_content_addressed_store_verifies_hash_and_rejects_unsafe_refs(tmp_path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    ref = store.put_bytes("证据".encode())
    assert store.read_bytes(ref) == "证据".encode()
    with pytest.raises(ValueError):
        store.read_bytes("file:../../secret")
    with pytest.raises(ValueError):
        store.read_bytes("sha256:../" + "0" * 61)

