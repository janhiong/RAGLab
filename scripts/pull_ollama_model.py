"""Download a public Ollama model through host networking, verifying every OCI digest.

Useful when Docker containers cannot access the cloud egress proxy. Normal local
setups can instead use `ollama pull qwen2.5:1.5b`.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re

import httpx

REGISTRY = "https://registry.ollama.ai"


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pull(model, directory):
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*:[a-zA-Z0-9][a-zA-Z0-9._-]*", model):
        raise ValueError("Use a public library model:name tag; paths are unsupported")
    name, tag = model.split(":", 1)
    root = Path(directory)
    blobs = root / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        response = client.get(f"{REGISTRY}/v2/library/{name}/manifests/{tag}")
        response.raise_for_status()
        manifest = response.json()
        # Publish the manifest only after all referenced content is verified.
        for layer in [manifest["config"], *manifest["layers"]]:
            digest = layer["digest"]
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise ValueError("Unexpected model artifact digest")
            expected = digest.split(":", 1)[1]
            destination = blobs / digest.replace(":", "-")
            if destination.exists() and digest_file(destination) == expected:
                continue
            temporary = destination.with_suffix(".partial")
            calculated = hashlib.sha256()
            try:
                with client.stream(
                    "GET", f"{REGISTRY}/v2/library/{name}/blobs/{digest}"
                ) as download:
                    download.raise_for_status()
                    with temporary.open("wb") as output:
                        for block in download.iter_bytes(1024 * 1024):
                            calculated.update(block)
                            output.write(block)
                if (
                    calculated.hexdigest() != expected
                    or temporary.stat().st_size != layer["size"]
                ):
                    raise ValueError("Model artifact checksum or size mismatch")
                temporary.replace(destination)
                print(f"Verified {digest}", flush=True)
            finally:
                temporary.unlink(missing_ok=True)
        destination = root / "manifests" / "registry.ollama.ai" / "library" / name / tag
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".partial")
        temporary.write_bytes(response.content)
        temporary.replace(destination)
    print(f"Model {model} is ready in {directory}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen2.5:1.5b")
    parser.add_argument("--directory", required=True, help="Ollama models directory")
    arguments = parser.parse_args()
    pull(arguments.model, arguments.directory)
