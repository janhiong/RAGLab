def reciprocal_rank_fusion(lists: list[list[dict]], limit: int, k: int = 60) -> list[dict]:
    """Fuse rank positions, never raw similarity/ranking scores."""
    scores: dict[str, float] = {}
    items: dict[str, dict] = {}
    for ranked in lists:
        seen = set()
        for rank, item in enumerate(ranked, 1):
            key = str(item["id"])
            if key in seen:
                continue
            seen.add(key)
            items.setdefault(key, item)
            scores[key] = scores.get(key, 0.0) + 1 / (k + rank)
    return [dict(items[key], score=scores[key]) for key in sorted(scores, key=lambda key: (-scores[key], key))[:limit]]
