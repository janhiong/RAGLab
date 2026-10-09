import argparse
import json
from pathlib import Path
import sys
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from app.db import connect
from app.evaluation.api import run_detail

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id", type=UUID)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run = run_detail(args.run_id)
    if run["status"] not in ("completed", "failed", "cancelled"):
        parser.error("Export a terminal run so the file is a stable snapshot")
    with connect() as c:
        results = c.execute(
            "SELECT * FROM experiment_results WHERE experiment_id=%s ORDER BY question_id",
            (args.run_id,),
        ).fetchall()
        dataset = c.execute(
            "SELECT * FROM datasets WHERE id=%s", (run["dataset_id"],)
        ).fetchone()
    payload = {"schema_version": 1, "run": run, "dataset": dataset, "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        json.dump(payload, output, indent=2, default=str)
