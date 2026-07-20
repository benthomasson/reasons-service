"""CLI entry point for meta-expert citation preservation evaluation (Phase 3).

Measures whether the meta-expert's final synthesized answer preserves citations
(belief IDs, entry IDs, source references) from the domain experts' answers.

Limitation: The SSE stream truncates tool_result summaries to 200 chars, so we
cannot directly compare expert-level citations vs final-answer citations. Instead
we measure:
  1. Citation presence: does the final answer contain any traceable references?
  2. Citation density: how many citations per answer?
  3. Fabrication: are cited IDs real or hallucinated? (requires DB access)
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from eval.meta_systems import MetaExpertDriver, MetaResponse, extract_citations

EVAL_DIR = Path(__file__).parent


def load_questions(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    return data["questions"]


async def run_citation_eval(
    questions: list[dict],
    base_url: str,
    model: str,
    limit: int | None = None,
    category: str | None = None,
) -> dict:
    """Run citation preservation evaluation on the meta-expert."""
    if category:
        questions = [q for q in questions if q.get("category") == category]
    if limit:
        questions = questions[:limit]

    driver = MetaExpertDriver(base_url, model)
    results: list[dict] = []
    total = len(questions)

    # Counters
    total_final_citations = 0
    questions_with_citations = 0
    questions_with_expert_answer_citations = 0
    total_expert_citations = 0
    total_preserved = 0

    print(f"Meta-expert citation eval: {total} questions, model={model}", file=sys.stderr)
    print(f"{'='*80}", file=sys.stderr)

    for i, q in enumerate(questions, 1):
        qid = q["id"]
        print(f"  [{i}/{total}] {qid}: ", end="", file=sys.stderr, flush=True)

        try:
            response: MetaResponse = await driver.ask(q["question"])
        except Exception as e:
            print(f"ERROR — {e}", file=sys.stderr)
            results.append({"question_id": qid, "error": str(e)})
            continue

        final_cites = response.expert_citations
        expert_cites = response.expert_answer_citations

        # Citation presence
        has_citations = len(final_cites) > 0
        if has_citations:
            questions_with_citations += 1
        total_final_citations += len(final_cites)

        # Expert answer citations (from truncated tool_result summaries)
        if expert_cites:
            questions_with_expert_answer_citations += 1
            total_expert_citations += len(expert_cites)
            preserved = set(expert_cites) & set(final_cites)
            total_preserved += len(preserved)
            preservation_rate = len(preserved) / len(expert_cites)
        else:
            preservation_rate = None  # Can't measure without expert citations

        # Status
        consulted_str = ", ".join(response.experts_consulted) if response.experts_consulted else "(none)"
        print(
            f"final_cites={len(final_cites)} expert_cites={len(expert_cites)} "
            f"consulted=[{consulted_str}] ({response.latency_seconds:.1f}s)",
            file=sys.stderr,
        )
        if final_cites:
            print(f"         refs: {final_cites[:8]}", file=sys.stderr)

        results.append({
            "question_id": qid,
            "question": q["question"],
            "category": q.get("category", "unknown"),
            "consulted_experts": response.experts_consulted,
            "final_citations": final_cites,
            "expert_answer_citations": expert_cites,
            "citation_count": len(final_cites),
            "has_citations": has_citations,
            "preservation_rate": round(preservation_rate, 4) if preservation_rate is not None else None,
            "latency_seconds": round(response.latency_seconds, 2),
            "answer_length": len(response.text),
        })

    # Summary
    completed = datetime.now(timezone.utc).isoformat()
    n = len(results)
    errors = sum(1 for r in results if "error" in r)
    answered = n - errors

    overall_preservation = total_preserved / total_expert_citations if total_expert_citations else None

    summary = {
        "questions_total": n,
        "questions_answered": answered,
        "questions_with_final_citations": questions_with_citations,
        "citation_presence_rate": round(questions_with_citations / answered, 4) if answered else 0,
        "total_final_citations": total_final_citations,
        "avg_citations_per_answer": round(total_final_citations / answered, 2) if answered else 0,
        "questions_with_expert_citations": questions_with_expert_answer_citations,
        "total_expert_citations": total_expert_citations,
        "total_preserved": total_preserved,
        "overall_preservation_rate": round(overall_preservation, 4) if overall_preservation is not None else None,
    }

    # Print summary
    print(f"\n{'='*80}", file=sys.stderr)
    print("CITATION PRESERVATION EVALUATION SUMMARY", file=sys.stderr)
    print(f"{'='*80}", file=sys.stderr)
    print(f"Questions answered:                {answered}/{n}", file=sys.stderr)
    print(f"Questions with citations:          {questions_with_citations}/{answered} ({summary['citation_presence_rate']:.0%})", file=sys.stderr)
    print(f"Total citations in final answers:  {total_final_citations}", file=sys.stderr)
    print(f"Avg citations per answer:          {summary['avg_citations_per_answer']}", file=sys.stderr)
    if total_expert_citations:
        print(f"Expert citations captured:         {total_expert_citations} (from truncated summaries)", file=sys.stderr)
        print(f"Citations preserved:               {total_preserved}/{total_expert_citations} ({overall_preservation:.0%})", file=sys.stderr)
    else:
        print(f"Expert citations captured:         0 (tool_result summaries too short)", file=sys.stderr)
        print(f"NOTE: Preservation rate cannot be measured — expert answers are truncated to 200 chars in SSE stream", file=sys.stderr)

    return {
        "metadata": {
            "completed_at": completed,
            "question_count": n,
            "model": model,
            "base_url": base_url,
            "note": "Expert answer citations are from 200-char truncated tool_result SSE summaries. "
                    "Full preservation measurement requires expanding tool_result summaries or "
                    "capturing expert answers server-side.",
        },
        "summary": summary,
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Run meta-expert citation preservation evaluation (Phase 3)")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--model", default="gemini-2.5-pro")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--category", choices=["single", "cross", "out-of-scope"], default=None)
    parser.add_argument(
        "--questions",
        type=Path,
        default=EVAL_DIR / "meta_questions.json",
        help="Path to questions JSON (default: routing questions)",
    )
    parser.add_argument("--output", type=Path, default=None)

    args = parser.parse_args()

    questions = load_questions(args.questions)
    if not questions:
        print("No questions loaded.", file=sys.stderr)
        sys.exit(1)

    output = asyncio.run(
        run_citation_eval(
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
        output_path = EVAL_DIR / "results" / f"{datetime.now():%Y-%m-%d}_meta_citations.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2))
    print(f"\nResults saved to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
