import math


def retrieval_metrics(retrieved, relevant):
    relevant = set(relevant)
    if not relevant:
        return {"recall_at_k": None, "reciprocal_rank": None}
    ranked = list(dict.fromkeys(str(value) for value in retrieved))
    return {
        "recall_at_k": len(set(ranked) & relevant) / len(relevant),
        "reciprocal_rank": next(
            (1 / rank for rank, value in enumerate(ranked, 1) if value in relevant), 0.0
        ),
    }


def percentile(values, quantile):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * quantile
    lower, upper = math.floor(position), math.ceil(position)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def aggregate(results):
    def mean(values):
        return sum(values) / len(values) if values else None

    completed = [row for row in results if row["status"] == "completed"]
    answerable = [row for row in results if row["question"]["relevant_chunk_ids"]]
    # Failures remain zero-valued in answerable retrieval denominators.
    recalls = [row["metrics"].get("recall_at_k") or 0 for row in answerable]
    ranks = [row["metrics"].get("reciprocal_rank") or 0 for row in answerable]
    unanswerable = [row for row in results if not row["question"]["relevant_chunk_ids"]]
    evaluated_abstention = [
        row
        for row in unanswerable
        if row["metrics"].get("abstention_correct") is not None
    ]
    reviews = [row["review"] for row in results if row.get("review")]
    latencies = [row["elapsed_ms"] for row in results]
    return {
        "attempted": len(results),
        "completed": len(completed),
        "failed": len(results) - len(completed),
        "answerable_count": len(answerable),
        "unanswerable_count": len(unanswerable),
        "recall_at_k": mean(recalls),
        "mrr": mean(ranks),
        "failure_rate": (
            (len(results) - len(completed)) / len(results) if results else None
        ),
        "latency_p50_ms": percentile(latencies, 0.5),
        "latency_p95_ms": percentile(latencies, 0.95),
        "abstention_accuracy": mean(
            [int(row["metrics"]["abstention_correct"]) for row in evaluated_abstention]
        ),
        "abstention_evaluated_count": len(evaluated_abstention),
        "no_evidence_abstentions": sum(
            bool(row.get("answer"))
            and not row["answer"].get("generation_performed", False)
            for row in evaluated_abstention
        ),
        "correctness": mean([row["correctness"] for row in reviews]),
        "faithfulness": mean([row["faithfulness"] for row in reviews]),
        "manually_reviewed_count": len(reviews),
        **{
            f"{stage}_p{int(q*100)}_ms": percentile(
                [
                    row["metrics"][f"{stage}_ms"]
                    for row in results
                    if row["metrics"].get(f"{stage}_ms") is not None
                ],
                q,
            )
            for stage in ("retrieval", "generation")
            for q in (0.5, 0.95)
        },
    }
