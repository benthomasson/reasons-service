"""CLI entry point for the evaluation runner."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from eval.runner import load_questions, run_evaluation

EVAL_DIR = Path(__file__).parent
ALL_SYSTEMS = ["claude-code", "expert-service-gemini", "expert-service-claude"]


def main():
    parser = argparse.ArgumentParser(description="Run Claude Code vs RAG evaluation")
    parser.add_argument(
        "--systems",
        nargs="+",
        default=["all"],
        choices=ALL_SYSTEMS + ["all"],
        help="Systems to evaluate",
    )
    parser.add_argument(
        "--questions",
        default="all",
        choices=["mc", "open-ended", "all"],
        help="Question set to use",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of questions (for testing)",
    )
    parser.add_argument(
        "--project-id",
        required=True,
        help="Expert-service project UUID",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Expert-service base URL",
    )
    parser.add_argument(
        "--aap-dir",
        default="~/git/aap-expert",
        help="Path to aap-expert knowledge base",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path (default: eval/results/YYYY-MM-DD_run.json)",
    )

    args = parser.parse_args()

    # Resolve systems
    systems = ALL_SYSTEMS if "all" in args.systems else args.systems

    # Load questions
    mc_path = EVAL_DIR / "questions.json" if args.questions in ("mc", "all") else None
    oe_path = EVAL_DIR / "open_ended.json" if args.questions in ("open-ended", "all") else None

    questions = load_questions(mc_path, oe_path)
    if not questions:
        print("No questions loaded. Check question files exist.", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(questions)} questions", file=sys.stderr)
    print(f"Systems: {', '.join(systems)}", file=sys.stderr)

    # Run
    results = asyncio.run(
        run_evaluation(
            systems=systems,
            questions=questions,
            project_id=args.project_id,
            base_url=args.base_url,
            aap_dir=args.aap_dir,
            limit=args.limit,
        )
    )

    # Write output
    if args.output:
        output_path = args.output
    else:
        from datetime import datetime
        output_path = EVAL_DIR / "results" / f"{datetime.now():%Y-%m-%d}_run.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2))
    print(f"\nResults saved to {output_path}", file=sys.stderr)

    # Print summary table
    print("\n" + "=" * 70)
    print("EVALUATION SUMMARY")
    print("=" * 70)
    header = f"{'System':<30} {'MC':>10} {'OE Avg':>10} {'Latency':>10} {'Tools':>8}"
    print(header)
    print("-" * 70)
    for name, data in results["systems"].items():
        s = data["summary"]
        mc_str = f"{s['mc_correct']}/{s['mc_total']}" if s["mc_total"] else "N/A"
        oe_str = f"{s['oe_avg_normalized']:.0%}" if s["oe_total"] else "N/A"
        print(f"{name:<30} {mc_str:>10} {oe_str:>10} {s['avg_latency']:>8.1f}s {s['avg_tool_calls']:>8.1f}")


if __name__ == "__main__":
    main()
