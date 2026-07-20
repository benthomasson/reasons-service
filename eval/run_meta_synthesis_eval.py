"""CLI entry point for meta-expert synthesis quality evaluation (Phase 2)."""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from eval.meta_scoring import score_routing
from eval.meta_synthesis_scoring import CIAKScore, aggregate_synthesis_scores, score_synthesis
from eval.meta_systems import MetaExpertDriver, MetaResponse

EVAL_DIR = Path(__file__).parent


def load_synthesis_questions(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    return data["questions"]


async def run_synthesis_eval(
    questions: list[dict],
    base_url: str,
    model: str,
    judge_model: str,
    limit: int | None = None,
) -> dict:
    """Run synthesis quality evaluation on the meta-expert."""
    if limit:
        questions = questions[:limit]

    driver = MetaExpertDriver(base_url, model)
    scores: list[CIAKScore] = []
    results: list[dict] = []
    total = len(questions)

    print(f"Meta-expert synthesis eval: {total} questions, model={model}, judge={judge_model}", file=sys.stderr)
    print(f"{'='*80}", file=sys.stderr)

    for i, q in enumerate(questions, 1):
        qid = q["id"]
        expected = q["expected_experts"]

        print(f"  [{i}/{total}] {qid}: ", end="", file=sys.stderr, flush=True)

        try:
            response: MetaResponse = await driver.ask(q["question"])
        except Exception as e:
            print(f"ERROR — {e}", file=sys.stderr)
            results.append({
                "question_id": qid,
                "error": str(e),
            })
            continue

        # Routing score (for reference)
        rs = score_routing(qid, response.experts_consulted, expected, "cross")

        print(f"routing F1={rs.f1:.2f}, ", end="", file=sys.stderr, flush=True)

        # CIAK synthesis score
        try:
            ciak = await score_synthesis(
                q, response.text, response.experts_consulted, judge_model
            )
        except Exception as e:
            print(f"JUDGE ERROR — {e}", file=sys.stderr)
            results.append({
                "question_id": qid,
                "question": q["question"],
                "routing_f1": rs.f1,
                "consulted_experts": response.experts_consulted,
                "answer_length": len(response.text),
                "error": f"judge error: {e}",
            })
            continue

        scores.append(ciak)

        # Status
        print(
            f"C={ciak.correctness:.2f} I={ciak.integration:.2f} "
            f"A={ciak.attribution:.2f} K={ciak.completeness:.0%} "
            f"composite={ciak.composite:.2f} "
            f"({response.latency_seconds:.1f}s)",
            file=sys.stderr,
        )
        if ciak.facts_missing:
            print(f"         missing: {ciak.facts_missing}", file=sys.stderr)

        results.append({
            "question_id": qid,
            "question": q["question"],
            "expected_experts": expected,
            "consulted_experts": response.experts_consulted,
            "routing_f1": rs.f1,
            "ciak": asdict(ciak),
            "latency_seconds": round(response.latency_seconds, 2),
            "answer_length": len(response.text),
            "answer_text": response.text,
        })

    # Aggregate
    agg = aggregate_synthesis_scores(scores)
    completed = datetime.now(timezone.utc).isoformat()

    # Print summary
    print(f"\n{'='*80}", file=sys.stderr)
    print("SYNTHESIS QUALITY EVALUATION SUMMARY (CIAK)", file=sys.stderr)
    print(f"{'='*80}", file=sys.stderr)
    print(
        f"{'Dimension':<20} {'Score':>10}",
        file=sys.stderr,
    )
    print(f"{'-'*35}", file=sys.stderr)
    if agg:
        print(f"{'Correctness':<20} {agg['avg_correctness']:>10.2%}", file=sys.stderr)
        print(f"{'Integration':<20} {agg['avg_integration']:>10.2%}", file=sys.stderr)
        print(f"{'Attribution':<20} {agg['avg_attribution']:>10.2%}", file=sys.stderr)
        print(f"{'Completeness':<20} {agg['avg_completeness']:>10.2%}", file=sys.stderr)
        print(f"{'-'*35}", file=sys.stderr)
        print(f"{'Composite (CIAK)':<20} {agg['avg_composite']:>10.2%}", file=sys.stderr)
        print(f"{'Perfect completeness':<20} {agg['perfect_completeness']:>7}/{agg['count']}", file=sys.stderr)

    return {
        "metadata": {
            "completed_at": completed,
            "question_count": total,
            "model": model,
            "judge_model": judge_model,
            "base_url": base_url,
        },
        "summary": agg,
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Run meta-expert synthesis quality evaluation (Phase 2)")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Expert-service base URL",
    )
    parser.add_argument(
        "--model",
        default="gemini-2.5-pro",
        help="LLM model for the meta-expert",
    )
    parser.add_argument(
        "--judge-model",
        default="sonnet",
        help="LLM model for the judge",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of questions",
    )
    parser.add_argument(
        "--questions",
        type=Path,
        default=EVAL_DIR / "meta_synthesis_questions.json",
        help="Path to synthesis questions JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path",
    )

    args = parser.parse_args()

    questions = load_synthesis_questions(args.questions)
    if not questions:
        print("No questions loaded.", file=sys.stderr)
        sys.exit(1)

    output = asyncio.run(
        run_synthesis_eval(
            questions=questions,
            base_url=args.base_url,
            model=args.model,
            judge_model=args.judge_model,
            limit=args.limit,
        )
    )

    if args.output:
        output_path = args.output
    else:
        output_path = EVAL_DIR / "results" / f"{datetime.now():%Y-%m-%d}_meta_synthesis.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2))
    print(f"\nResults saved to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
