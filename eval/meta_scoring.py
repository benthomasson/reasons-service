"""Scoring for meta-expert evaluation — routing accuracy and citation preservation."""

from dataclasses import dataclass


@dataclass
class RoutingScore:
    question_id: str
    expected_experts: list[str]
    consulted_experts: list[str]
    precision: float
    recall: float
    f1: float
    category: str  # "single", "cross", "out-of-scope"


def score_routing(question_id: str, consulted: list[str], expected: list[str], category: str) -> RoutingScore:
    """Score routing accuracy using precision/recall/F1.

    - Precision: fraction of consulted experts that were correct (penalizes unnecessary consultations)
    - Recall: fraction of required experts that were consulted (penalizes missed experts)
    - F1: harmonic mean
    """
    consulted_set = set(consulted)
    expected_set = set(expected)

    # Out-of-scope: correct if no experts consulted
    if not expected_set:
        correct = not consulted_set
        return RoutingScore(
            question_id=question_id,
            expected_experts=expected,
            consulted_experts=consulted,
            precision=1.0 if correct else 0.0,
            recall=1.0 if correct else 0.0,
            f1=1.0 if correct else 0.0,
            category=category,
        )

    # No experts consulted but some were expected
    if not consulted_set:
        return RoutingScore(
            question_id=question_id,
            expected_experts=expected,
            consulted_experts=consulted,
            precision=0.0,
            recall=0.0,
            f1=0.0,
            category=category,
        )

    precision = len(consulted_set & expected_set) / len(consulted_set)
    recall = len(consulted_set & expected_set) / len(expected_set)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return RoutingScore(
        question_id=question_id,
        expected_experts=expected,
        consulted_experts=consulted,
        precision=precision,
        recall=recall,
        f1=f1,
        category=category,
    )


@dataclass
class CitationScore:
    question_id: str
    expert_citations: list[str]
    final_citations: list[str]
    preservation_rate: float
    fabrication_count: int


def score_citations(
    question_id: str,
    expert_citations: list[str],
    final_citations: list[str],
    known_belief_ids: set[str] | None = None,
) -> CitationScore:
    """Score citation preservation from expert answers to final synthesis.

    - Preservation rate: how many expert citations survived to the final answer
    - Fabrication count: citations in final answer that don't exist in any knowledge base
    """
    expert_set = set(expert_citations)
    final_set = set(final_citations)

    if not expert_set:
        preservation = 1.0  # Nothing to preserve
    else:
        preserved = final_set & expert_set
        preservation = len(preserved) / len(expert_set)

    fabrication = 0
    if known_belief_ids is not None:
        fabricated = final_set - known_belief_ids
        fabrication = len(fabricated)

    return CitationScore(
        question_id=question_id,
        expert_citations=expert_citations,
        final_citations=final_citations,
        preservation_rate=preservation,
        fabrication_count=fabrication,
    )


def aggregate_routing_scores(scores: list[RoutingScore]) -> dict:
    """Aggregate routing scores by category."""
    result = {}
    categories = set(s.category for s in scores)

    for cat in sorted(categories):
        cat_scores = [s for s in scores if s.category == cat]
        n = len(cat_scores)
        result[cat] = {
            "count": n,
            "avg_precision": round(sum(s.precision for s in cat_scores) / n, 4) if n else 0,
            "avg_recall": round(sum(s.recall for s in cat_scores) / n, 4) if n else 0,
            "avg_f1": round(sum(s.f1 for s in cat_scores) / n, 4) if n else 0,
            "perfect": sum(1 for s in cat_scores if s.f1 == 1.0),
        }

    all_scores = scores
    n = len(all_scores)
    result["overall"] = {
        "count": n,
        "avg_precision": round(sum(s.precision for s in all_scores) / n, 4) if n else 0,
        "avg_recall": round(sum(s.recall for s in all_scores) / n, 4) if n else 0,
        "avg_f1": round(sum(s.f1 for s in all_scores) / n, 4) if n else 0,
        "perfect": sum(1 for s in all_scores if s.f1 == 1.0),
    }

    return result
