"""Certification coverage mapping.

Ported from expert_build/coverage.py — replaces CLI invocation with LangChain ChatModel,
replaces file-based parsing with structured dicts from DB.
"""

import re

from reasons_service.llm.provider import get_chat_model
from reasons_service.llm.prompts import CERT_MATCH


def keyword_match(objective_text: str, belief_text: str) -> float:
    """Simple keyword overlap score between objective and belief."""
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "can", "shall",
        "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "and",
        "or", "but", "not", "no", "if", "then", "than", "that",
        "this", "it", "its", "all", "each", "any", "use", "using",
    }

    def tokenize(text):
        words = re.findall(r"\w+", text.lower())
        return {w for w in words if w not in stop_words and len(w) > 2}

    obj_words = tokenize(objective_text)
    belief_words = tokenize(belief_text)

    if not obj_words or not belief_words:
        return 0.0

    overlap = obj_words & belief_words
    return len(overlap) / len(obj_words)


def match_objectives(
    objectives: list[dict],
    beliefs: list[dict],
    model: str | None = None,
    on_progress: callable = None,
) -> dict:
    """Match certification objectives against beliefs.

    Args:
        objectives: List of {id, domain, text} dicts.
        beliefs: List of {id, text} dicts (IN beliefs only).
        model: Model name for LLM semantic matching (None = keyword only).
        on_progress: Callback(obj_index, total, matches_found).

    Returns:
        {
            "results": [{objective, matches: [(belief_id, score)], covered: bool}],
            "score": {covered, total, pct, by_domain: {domain: {covered, total, pct}}}
        }
    """
    use_llm = model is not None
    chat_model = get_chat_model(model) if use_llm else None

    beliefs_text = "\n".join(f"- {b['id']}: {b['text']}" for b in beliefs)

    results = []

    for i, obj in enumerate(objectives):
        matches = []

        # Try LLM matching first
        if use_llm and chat_model:
            prompt = CERT_MATCH.format(objective=obj["text"], beliefs=beliefs_text)
            try:
                response = chat_model.invoke(prompt)
                content = response.content.strip()
                if content.upper() != "NO MATCH":
                    for line in content.split("\n"):
                        bid = line.strip().strip("-").strip()
                        if any(b["id"] == bid for b in beliefs):
                            matches.append((bid, 1.0))
            except Exception:
                pass

        # Fall back to keyword matching
        if not matches:
            for belief in beliefs:
                score = keyword_match(obj["text"], belief["text"])
                if score >= 0.3:
                    matches.append((belief["id"], score))

        matches.sort(key=lambda x: x[1], reverse=True)

        results.append({
            "objective": obj,
            "matches": matches[:5],
            "covered": len(matches) > 0,
        })

        if on_progress:
            on_progress(i + 1, len(objectives), sum(1 for r in results if r["covered"]))

    # Score calculation
    covered_count = sum(1 for r in results if r["covered"])
    total = len(objectives)
    pct = 100 * covered_count // total if total else 0

    # By domain breakdown
    domains = {}
    for r in results:
        domain = r["objective"].get("domain", "general")
        if domain not in domains:
            domains[domain] = {"covered": 0, "total": 0}
        domains[domain]["total"] += 1
        if r["covered"]:
            domains[domain]["covered"] += 1

    for d in domains.values():
        d["pct"] = 100 * d["covered"] // d["total"] if d["total"] else 0

    return {
        "results": results,
        "score": {
            "covered": covered_count,
            "total": total,
            "pct": pct,
            "by_domain": domains,
        },
    }
