"""CLI entry point for meta-expert routing evaluation."""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from eval.meta_scoring import RoutingScore, aggregate_routing_scores, score_routing
from eval.meta_systems import MetaExpertDriver, MetaResponse

EVAL_DIR = Path(__file__).parent


def load_meta_questions(path: Path) -> list[dict]:
    """Load meta-expert evaluation questions."""
    data = json.loads(path.read_text())
    return data["questions"]


async def run_meta_eval(
    questions: list[dict],
    base_url: str,
    model: str,
    limit: int | None = None,
    category: str | None = None,
) -> dict:
    """Run routing evaluation on the meta-expert."""
    if category:
        questions = [q for q in questions if q["category"] == category]
    if limit:
        questions = questions[:limit]

    driver = MetaExpertDriver(base_url, model)
    routing_scores: list[RoutingScore] = []
    results: list[dict] = []
    total = len(questions)

    print(f"Meta-expert routing eval: {total} questions, model={model}", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)

    for i, q in enumerate(questions, 1):
        qid = q["id"]
        expected = q["expected_experts"]
        cat = q["category"]

        print(f"  [{i}/{total}] {qid} ({cat}): ", end="", file=sys.stderr, flush=True)

        try:
            response: MetaResponse = await driver.ask(q["question"])
        except Exception as e:
            print(f"ERROR — {e}", file=sys.stderr)
            rs = score_routing(qid, [], expected, cat)
            routing_scores.append(rs)
            results.append({
                "question_id": qid,
                "category": cat,
                "error": str(e),
                "routing": asdict(rs),
            })
            continue

        rs = score_routing(qid, response.experts_consulted, expected, cat)
        routing_scores.append(rs)

        # Status line
        status = "PERFECT" if rs.f1 == 1.0 else f"P={rs.precision:.2f} R={rs.recall:.2f} F1={rs.f1:.2f}"
        consulted_str = ", ".join(response.experts_consulted) if response.experts_consulted else "(none)"
        expected_str = ", ".join(expected) if expected else "(none)"
        print(
            f"{status} — consulted=[{consulted_str}] expected=[{expected_str}] "
            f"({response.latency_seconds:.1f}s)",
            file=sys.stderr,
        )

        results.append({
            "question_id": qid,
            "question": q["question"],
            "category": cat,
            "expected_experts": expected,
            "consulted_experts": response.experts_consulted,
            "routing": asdict(rs),
            "latency_seconds": round(response.latency_seconds, 2),
            "tool_calls": response.tool_calls,
            "reflection_calls": response.reflection_calls,
            "citations": response.expert_citations,
            "answer_length": len(response.text),
        })

    # Aggregate
    agg = aggregate_routing_scores(routing_scores)
    completed = datetime.now(timezone.utc).isoformat()

    # Print summary
    print(f"\n{'='*70}", file=sys.stderr)
    print("ROUTING EVALUATION SUMMARY", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)
    print(f"{'Category':<20} {'Count':>6} {'Precision':>10} {'Recall':>10} {'F1':>10} {'Perfect':>8}", file=sys.stderr)
    print(f"{'-'*70}", file=sys.stderr)
    for cat, stats in agg.items():
        print(
            f"{cat:<20} {stats['count']:>6} {stats['avg_precision']:>10.2%} "
            f"{stats['avg_recall']:>10.2%} {stats['avg_f1']:>10.2%} "
            f"{stats['perfect']:>5}/{stats['count']}",
            file=sys.stderr,
        )

    return {
        "metadata": {
            "completed_at": completed,
            "question_count": total,
            "model": model,
            "base_url": base_url,
        },
        "summary": agg,
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Run meta-expert routing evaluation")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Expert-service base URL",
    )
    parser.add_argument(
        "--model",
        default="gemini-2.5-pro",
        help="LLM model to use",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of questions (for testing)",
    )
    parser.add_argument(
        "--category",
        choices=["single", "cross", "out-of-scope"],
        default=None,
        help="Only run questions in this category",
    )
    parser.add_argument(
        "--questions",
        type=Path,
        default=EVAL_DIR / "meta_questions.json",
        help="Path to meta questions JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path",
    )

    args = parser.parse_args()

    questions = load_meta_questions(args.questions)
    if not questions:
        print("No questions loaded.", file=sys.stderr)
        sys.exit(1)

    output = asyncio.run(
        run_meta_eval(
            questions=questions,
            base_url=args.base_url,
            model=args.model,
            limit=args.limit,
            category=args.category,
        )
    )

    if args.output:
        output_path = args.output
    else:
        output_path = EVAL_DIR / "results" / f"{datetime.now():%Y-%m-%d}_meta_routing.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2))
    print(f"\nResults saved to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
