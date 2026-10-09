"""Import quote-anchored labels without inventing machine-specific chunk UUIDs."""

import argparse
import json
from pathlib import Path
import sys
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from app.evaluation.api import DatasetImport, import_dataset

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    parser.add_argument("--document-id", required=True, type=UUID)
    args = parser.parse_args()
    payload = json.loads(args.file.read_text())
    payload["document_id"] = args.document_id
    print(json.dumps(import_dataset(DatasetImport(**payload)), default=str))
