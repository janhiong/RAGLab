"""Run with the API virtualenv after installing the vector extra."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from app.embeddings import MODEL_ID, MODEL_REVISION


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    from huggingface_hub import snapshot_download
    output = snapshot_download(
        repo_id=MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=args.output,
        allow_patterns=["*.json", "*.txt", "*.safetensors", "1_Pooling/*"],
    )
    Path(output, "raglab-model.json").write_text(json.dumps({"model_id": MODEL_ID, "revision": MODEL_REVISION}))
    print(f"Downloaded pinned embedding model to {output}")


if __name__ == "__main__":
    main()
