from functools import lru_cache
from pathlib import Path
import threading

MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
# Immutable upstream model revision; recorded in every vector-bearing chunk.
MODEL_REVISION = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"
MODEL_VERSION = f"{MODEL_ID}@{MODEL_REVISION}"
_lock = threading.Lock()


class EmbeddingsUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def load_model(model_path: str):
    if not model_path or not Path(model_path).is_dir():
        raise EmbeddingsUnavailable("Local embedding model is unavailable. Follow the vector setup instructions.")
    try:
        import json
        manifest = json.loads(Path(model_path, "raglab-model.json").read_text())
        if manifest != {"model_id": MODEL_ID, "revision": MODEL_REVISION}:
            raise EmbeddingsUnavailable("Model provenance does not match the pinned corpus model.")
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(model_path, device="cpu", local_files_only=True, trust_remote_code=False)
    except (ImportError, OSError, ValueError) as exc:
        raise EmbeddingsUnavailable("Local embedding model cannot be loaded. Check vector dependencies and model files.") from exc


def embed(texts: list[str], model_path: str) -> list[list[float]]:
    model = load_model(model_path)
    with _lock:
        vectors = model.encode(texts, normalize_embeddings=True, batch_size=16).tolist()
    if any(len(vector) != 384 for vector in vectors):
        raise EmbeddingsUnavailable("Embedding dimension does not match the 384-dimensional corpus schema.")
    return vectors


def vector_literal(vector: list[float]) -> str:
    import math
    if len(vector) != 384 or not all(math.isfinite(number) for number in vector) or not any(vector):
        raise ValueError("Expected 384 finite embedding values.")
    return "[" + ",".join(str(float(value)) for value in vector) + "]"
