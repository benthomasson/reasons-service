"""Generate markdown report from evaluation results JSON."""

import json
import sys
from pathlib import Path


def generate_report(results: dict) -> str:
    """Generate a markdown comparison report."""
    meta = results["metadata"]
    systems = results["systems"]
    system_names = list(systems.keys())

    lines = [
        "# Retrieval System Evaluation Report",
        f"**Date:** {meta['started_at'][:10]}",
        f"**Questions:** {meta['question_count']}",
        f"**Systems:** {', '.join(system_names)}",
        "",
        "## Summary",
        "",
    ]

    # Summary table
    header = "| Metric |"
    separator = "|--------|"
    for name in system_names:
        short = name.replace("expert-service-", "ES-")
        header += f" {short} |"
        separator += "------------|"
    lines.append(header)
    lines.append(separator)

    # MC accuracy row
    row = "| MC Accuracy |"
    for name in system_names:
        s = systems[name]["summary"]
        if s["mc_total"]:
            row += f" {s['mc_correct']}/{s['mc_total']} ({s['mc_accuracy']:.0%}) |"
        else:
            row += " N/A |"
    lines.append(row)

    # OE average row
    row = "| Open-Ended Avg |"
    for name in system_names:
        s = systems[name]["summary"]
        if s["oe_total"]:
            row += f" {s['oe_avg_normalized']:.0%} |"
        else:
            row += " N/A |"
    lines.append(row)

    # Latency row
    row = "| Avg Latency |"
    for name in system_names:
        s = systems[name]["summary"]
        row += f" {s['avg_latency']:.1f}s |"
    lines.append(row)

    # Tool calls row
    row = "| Avg Tool Calls |"
    for name in system_names:
        s = systems[name]["summary"]
        row += f" {s['avg_tool_calls']:.1f} |"
    lines.append(row)

    lines.append("")

    # MC detail: by objective
    mc_by_obj = {}  # {system: {objective: {correct, total}}}
    for name in system_names:
        mc_by_obj[name] = {}
        for r in systems[name]["results"]:
            if r["question_type"] != "mc" or "mc_score" not in r:
                continue
            obj = r["mc_score"].get("objective", "general") or "general"
            if obj not in mc_by_obj[name]:
                mc_by_obj[name][obj] = {"correct": 0, "total": 0}
            mc_by_obj[name][obj]["total"] += 1
            if r["mc_score"]["correct"]:
                mc_by_obj[name][obj]["correct"] += 1

    if mc_by_obj.get(system_names[0]):
        lines.extend(["## Multiple Choice: By Objective", ""])
        all_objs = sorted(
            set(obj for sys_objs in mc_by_obj.values() for obj in sys_objs)
        )
        header = "| Objective |"
        sep = "|-----------|"
        for name in system_names:
            short = name.replace("expert-service-", "ES-")
            header += f" {short} |"
            sep += "------|"
        lines.append(header)
        lines.append(sep)

        for obj in all_objs:
            row = f"| {obj} |"
            for name in system_names:
                data = mc_by_obj[name].get(obj, {"correct": 0, "total": 0})
                row += f" {data['correct']}/{data['total']} |"
            lines.append(row)
        lines.append("")

    # Disagreements
    lines.extend(["## Disagreements", ""])
    mc_answers = {}  # {q_id: {system: extracted}}
    for name in system_names:
        for r in systems[name]["results"]:
            if r["question_type"] != "mc" or "mc_score" not in r:
                continue
            qid = r["question_id"]
            if qid not in mc_answers:
                mc_answers[qid] = {}
            mc_answers[qid][name] = r["mc_score"]["extracted"]

    has_disagreement = False
    for qid, answers in sorted(mc_answers.items()):
        values = set(answers.values())
        if len(values) > 1:
            has_disagreement = True
            expected = None
            for name in system_names:
                for r in systems[name]["results"]:
                    if r["question_id"] == qid and "mc_score" in r:
                        expected = r["mc_score"]["expected"]
                        break
                if expected:
                    break
            parts = ", ".join(f"{n}={answers[n]}" for n in system_names)
            lines.append(f"- **{qid}**: {parts} (correct={expected})")

    if not has_disagreement:
        lines.append("No disagreements — all systems gave the same answers.")
    lines.append("")

    # Open-ended detail
    oe_results = {}
    for name in system_names:
        for r in systems[name]["results"]:
            if r["question_type"] == "open_ended" and "oe_score" in r:
                qid = r["question_id"]
                if qid not in oe_results:
                    oe_results[qid] = {}
                oe_results[qid][name] = r["oe_score"]

    if oe_results:
        lines.extend(["## Open-Ended Scores", ""])
        header = "| Question |"
        sep = "|----------|"
        for name in system_names:
            short = name.replace("expert-service-", "ES-")
            header += f" {short} |"
            sep += "------|"
        lines.append(header)
        lines.append(sep)

        for qid in sorted(oe_results):
            row = f"| {qid} |"
            for name in system_names:
                if name in oe_results[qid]:
                    s = oe_results[qid][name]
                    total = s["correctness"] + s["completeness"] + s["citation_quality"]
                    total_max = s["correctness_max"] + s["completeness_max"] + s["citation_max"]
                    row += f" {total}/{total_max} |"
                else:
                    row += " N/A |"
            lines.append(row)
        lines.append("")

    # Tool usage analysis
    lines.extend(["## Tool Usage", ""])
    for name in system_names:
        tool_counts = {}
        total_tools = 0
        for r in systems[name]["results"]:
            for tc in r["tool_calls"]:
                tool_name = tc.get("name", "unknown")
                tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
                total_tools += 1

        lines.append(f"### {name}")
        if tool_counts:
            lines.append(f"Total tool calls: {total_tools}")
            for tool, count in sorted(tool_counts.items(), key=lambda x: -x[1]):
                pct = 100 * count / total_tools
                lines.append(f"- {tool}: {count} ({pct:.0f}%)")
        else:
            lines.append("No tool calls recorded.")
        lines.append("")

    # Wrong answers detail
    lines.extend(["## Wrong MC Answers", ""])
    has_wrong = False
    for name in system_names:
        for r in systems[name]["results"]:
            if r["question_type"] == "mc" and "mc_score" in r and not r["mc_score"]["correct"]:
                has_wrong = True
                lines.append(
                    f"- **{r['question_id']}** ({name}): "
                    f"expected={r['mc_score']['expected']}, "
                    f"got={r['mc_score']['extracted']}"
                )
    if not has_wrong:
        lines.append("All systems answered all MC questions correctly.")
    lines.append("")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python -m eval.report <results.json>", file=sys.stderr)
        sys.exit(1)

    results_path = Path(sys.argv[1])
    results = json.loads(results_path.read_text())
    report = generate_report(results)

    # Write markdown report alongside JSON
    report_path = results_path.with_suffix(".md")
    report_path.write_text(report)
    print(f"Report written to {report_path}", file=sys.stderr)
    print(report)


if __name__ == "__main__":
    main()
