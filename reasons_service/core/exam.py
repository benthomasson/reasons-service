"""Practice exam runner.

Ported from expert_build/exam.py — replaces CLI invocation with LangChain ChatModel,
replaces subprocess nogood recording with structured dicts for DB storage.
"""

import re

from reasons_service.llm.provider import get_chat_model
from reasons_service.llm.prompts import EXAM_ANSWER


def extract_answer(response: str) -> str:
    """Extract the answer letter from an LLM response."""
    # Look for ANSWER: line
    match = re.search(r"ANSWER:\s*(.+)", response, re.IGNORECASE)
    if match:
        ans = match.group(1).strip()
        letter_match = re.match(r"([a-d])[.):\s]", ans, re.IGNORECASE)
        if letter_match:
            return letter_match.group(1).lower()
        return ans

    # Fallback: single letter on its own
    for line in response.strip().split("\n"):
        line = line.strip()
        if re.match(r"^[a-d]$", line, re.IGNORECASE):
            return line.lower()

    return response.strip()[:100]


def run_exam_questions(
    questions: list[dict],
    beliefs_context: str,
    domain: str = "",
    model: str | None = None,
    on_progress: callable = None,
) -> dict:
    """Run practice exam questions against beliefs.

    Args:
        questions: List of {id, text, choices, correct, objective} dicts.
        beliefs_context: Formatted beliefs string for LLM context.
        domain: Domain name for the EXAM_ANSWER prompt.
        model: Model name to use.
        on_progress: Callback(q_index, total, correct_so_far).

    Returns:
        {
            "results": [{question, status, got, expected, response}],
            "score": {correct, total, pct, by_objective: {obj: {correct, total, pct}}},
            "nogoods": [{description, resolution, question_id, objective}]
        }
    """
    chat_model = get_chat_model(model)

    results = []
    correct_count = 0
    nogoods = []

    for i, q in enumerate(questions):
        # Format choices
        choices_text = ""
        if q.get("choices"):
            choices_text = "\n".join(
                f"  {k}) {v}" for k, v in sorted(q["choices"].items())
            )

        prompt = EXAM_ANSWER.format(
            domain=domain or "this subject",
            beliefs=beliefs_context,
            question=q["text"],
            choices=choices_text,
        )

        try:
            response = chat_model.invoke(prompt)
            response_text = response.content
        except Exception as e:
            results.append({
                "question": q,
                "status": "ERROR",
                "got": None,
                "expected": q["correct"],
                "error": str(e),
            })
            continue

        answer = extract_answer(response_text)
        expected = q["correct"].strip().lower()

        # Normalize comparison
        if len(expected) == 1:
            is_correct = answer.lower() == expected
        else:
            is_correct = expected in answer.lower() or answer.lower() in expected

        if is_correct:
            correct_count += 1
            results.append({
                "question": q,
                "status": "CORRECT",
                "got": answer,
                "expected": q["correct"],
            })
        else:
            results.append({
                "question": q,
                "status": "WRONG",
                "got": answer,
                "expected": q["correct"],
            })
            # Record as nogood
            nogoods.append({
                "description": (
                    f"Exam {q['id']}: expected '{q['correct']}' "
                    f"but agent answered '{answer}' for: {q['text']}"
                ),
                "resolution": (
                    f"Review and update beliefs about: "
                    f"{q.get('objective') or q['text']}"
                ),
                "question_id": q["id"],
                "objective": q.get("objective"),
            })

        if on_progress:
            on_progress(i + 1, len(questions), correct_count)

    # Score calculation
    total = len(questions)
    pct = 100 * correct_count // total if total else 0

    # By objective breakdown
    obj_scores = {}
    for r in results:
        obj = r["question"].get("objective", "general")
        if obj not in obj_scores:
            obj_scores[obj] = {"correct": 0, "total": 0}
        obj_scores[obj]["total"] += 1
        if r["status"] == "CORRECT":
            obj_scores[obj]["correct"] += 1

    for o in obj_scores.values():
        o["pct"] = 100 * o["correct"] // o["total"] if o["total"] else 0

    return {
        "results": results,
        "score": {
            "correct": correct_count,
            "total": total,
            "pct": pct,
            "by_objective": obj_scores,
        },
        "nogoods": nogoods,
    }
