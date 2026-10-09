import hashlib
import importlib.util
from pathlib import Path

import httpx
import pytest

spec = importlib.util.spec_from_file_location(
    "model_download",
    Path(__file__).resolve().parents[3] / "scripts/pull_ollama_model.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_artifact_checksum_failure_never_publishes_manifest(tmp_path, monkeypatch):
    expected = hashlib.sha256(b"expected").hexdigest()
    manifest = {"config": {"digest": "sha256:" + expected, "size": 8}, "layers": []}

    def handler(request):
        return (
            httpx.Response(200, json=manifest)
            if "/manifests/" in str(request.url)
            else httpx.Response(200, content=b"tampered")
        )

    original = httpx.Client
    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    with pytest.raises(ValueError, match="checksum"):
        module.pull("test:small", tmp_path)
    assert not (tmp_path / "manifests").exists()
    assert not list(tmp_path.glob("blobs/*.partial"))


def test_verified_artifacts_are_reused(tmp_path, monkeypatch):
    content = b"verified"
    digest = hashlib.sha256(content).hexdigest()
    manifest = {
        "config": {"digest": "sha256:" + digest, "size": len(content)},
        "layers": [],
    }
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return (
            httpx.Response(200, json=manifest)
            if "/manifests/" in str(request.url)
            else httpx.Response(200, content=content)
        )

    original = httpx.Client
    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    module.pull("test:small", tmp_path)
    module.pull("test:small", tmp_path)
    assert len([url for url in calls if "/blobs/" in url]) == 1
    assert (tmp_path / "manifests/registry.ollama.ai/library/test/small").exists()
