"""Evaluation runner — orchestrates questions across systems."""

import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from eval.scoring import MCScore, OpenEndedScore, judge_open_ended, score_mc
from eval.systems import ClaudeCodeDriver, DriverResponse, ExpertServiceDriver


@dataclass
class QuestionResult:
    question_id: str
    question_type: str
    raw_response: str
    tool_calls: list[dict]
    latency_seconds: float
    mc_score: MCScore | None = None
    oe_score: OpenEndedScore | None = None
    cost_usd: float | None = None
    num_turns: int | None = None


@dataclass
class SystemResults:
    system_name: str
    config: dict
    results: list[QuestionResult] = field(default_factory=list)

    @property
    def mc_results(self) -> list[QuestionResult]:
        return [r for r in self.results if r.question_type == "mc"]

    @property
    def oe_results(self) -> list[QuestionResult]:
        return [r for r in self.results if r.question_type == "open_ended"]

    def mc_accuracy(self) -> float:
        mc = self.mc_results
        if not mc:
            return 0.0
        return sum(1 for r in mc if r.mc_score and r.mc_score.correct) / len(mc)

    def summary(self) -> dict:
        mc = self.mc_results
        oe = self.oe_results
        mc_correct = sum(1 for r in mc if r.mc_score and r.mc_score.correct)

        oe_scores = [r.oe_score for r in oe if r.oe_score]
        oe_avg = (
            sum(s.total / s.total_max for s in oe_scores) / len(oe_scores)
            if oe_scores
            else 0.0
        )

        all_results = self.results
        return {
            "mc_correct": mc_correct,
            "mc_total": len(mc),
            "mc_accuracy": round(self.mc_accuracy(), 4),
            "oe_avg_normalized": round(oe_avg, 4),
            "oe_total": len(oe),
            "avg_latency": round(
                sum(r.latency_seconds for r in all_results) / len(all_results), 2
            )
            if all_results
            else 0,
            "avg_tool_calls": round(
                sum(len(r.tool_calls) for r in all_results) / len(all_results), 2
            )
            if all_results
            else 0,
        }


def load_questions(mc_path: Path | None, oe_path: Path | None) -> list[dict]:
    """Load questions from JSON files."""
    questions = []
    if mc_path and mc_path.exists():
        data = json.loads(mc_path.read_text())
        for q in data["questions"]:
            q["type"] = "mc"
            questions.append(q)
    if oe_path and oe_path.exists():
        data = json.loads(oe_path.read_text())
        for q in data["questions"]:
            q["type"] = "open_ended"
            questions.append(q)
    return questions


def format_mc_question(q: dict) -> str:
    """Format an MC question with choices."""
    lines = [q["text"]]
    if q.get("choices"):
        for letter, text in sorted(q["choices"].items()):
            lines.append(f"  {letter}) {text}")
    return "\n".join(lines)


def get_driver(system_name: str, project_id: str, base_url: str, aap_dir: str):
    """Create a driver for the given system name."""
    if system_name == "claude-code":
        return ClaudeCodeDriver(cwd=aap_dir)
    elif system_name == "expert-service-gemini":
        return ExpertServiceDriver(base_url, project_id, "gemini-2.5-pro")
    elif system_name == "expert-service-claude":
        return ExpertServiceDriver(base_url, project_id, "claude-sonnet-4-5@20250929")
    else:
        raise ValueError(f"Unknown system: {system_name}")


async def run_evaluation(
    systems: list[str],
    questions: list[dict],
    project_id: str,
    base_url: str = "http://localhost:8000",
    aap_dir: str = "~/git/aap-expert",
    limit: int | None = None,
) -> dict:
    """Run all questions through all systems and score results."""
    if limit:
        questions = questions[:limit]

    started = datetime.now(timezone.utc).isoformat()
    all_system_results = {}

    for system_name in systems:
        driver = get_driver(system_name, project_id, base_url, aap_dir)
        config = {"type": system_name}
        if isinstance(driver, ClaudeCodeDriver):
            config["cwd"] = driver.cwd
        else:
            config["model"] = driver.model

        sr = SystemResults(system_name=system_name, config=config)
        total = len(questions)

        print(f"\n{'='*60}", file=sys.stderr)
        print(f"System: {system_name} ({total} questions)", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)

        for i, q in enumerate(questions, 1):
            q_type = q["type"]
            q_text = format_mc_question(q) if q_type == "mc" else q["text"]

            print(f"  [{i}/{total}] {q['id']}: ", end="", file=sys.stderr, flush=True)

            try:
                response = await driver.ask(q_text)
            except Exception as e:
                print(f"ERROR — {e}", file=sys.stderr)
                sr.results.append(
                    QuestionResult(
                        question_id=q["id"],
                        question_type=q_type,
                        raw_response=f"ERROR: {e}",
                        tool_calls=[],
                        latency_seconds=0,
                    )
                )
                continue

            # Score
            mc_score = None
            oe_score = None

            if q_type == "mc":
                mc_score = score_mc(q, response.text)
                status = "CORRECT" if mc_score.correct else f"WRONG (got={mc_score.extracted}, expected={mc_score.expected})"
            else:
                try:
                    oe_score = await judge_open_ended(q, response.text)
                    status = f"score={oe_score.total}/{oe_score.total_max}"
                except Exception as e:
                    status = f"JUDGE ERROR — {e}"

            cost_str = f", ${response.cost_usd:.4f}" if response.cost_usd else ""
            print(
                f"{status} ({response.latency_seconds:.1f}s, {len(response.tool_calls)} tools{cost_str})",
                file=sys.stderr,
            )

            sr.results.append(
                QuestionResult(
                    question_id=q["id"],
                    question_type=q_type,
                    raw_response=response.text,
                    tool_calls=response.tool_calls,
                    latency_seconds=response.latency_seconds,
                    mc_score=mc_score,
                    oe_score=oe_score,
                    cost_usd=response.cost_usd,
                    num_turns=response.num_turns,
                )
            )

        # Print system summary
        s = sr.summary()
        print(f"\n  Summary: MC={s['mc_correct']}/{s['mc_total']} ({s['mc_accuracy']:.0%})", file=sys.stderr)
        if s["oe_total"]:
            print(f"           OE avg={s['oe_avg_normalized']:.0%}", file=sys.stderr)
        print(f"           Avg latency={s['avg_latency']}s, Avg tools={s['avg_tool_calls']}", file=sys.stderr)

        all_system_results[system_name] = sr

    completed = datetime.now(timezone.utc).isoformat()

    # Build JSON-serializable output
    output = {
        "metadata": {
            "started_at": started,
            "completed_at": completed,
            "question_count": len(questions),
            "systems": systems,
        },
        "systems": {},
    }

    for name, sr in all_system_results.items():
        output["systems"][name] = {
            "config": sr.config,
            "summary": sr.summary(),
            "results": [_serialize_result(r) for r in sr.results],
        }

    return output


def _serialize_result(r: QuestionResult) -> dict:
    d = {
        "question_id": r.question_id,
        "question_type": r.question_type,
        "raw_response": r.raw_response,
        "tool_calls": r.tool_calls,
        "latency_seconds": round(r.latency_seconds, 2),
    }
    if r.mc_score:
        d["mc_score"] = asdict(r.mc_score)
    if r.oe_score:
        d["oe_score"] = asdict(r.oe_score)
    if r.cost_usd is not None:
        d["cost_usd"] = r.cost_usd
    if r.num_turns is not None:
        d["num_turns"] = r.num_turns
    return d
