"""Accuracy of the intent classifier on a PT-BR case set.

Needs only OPENAI_API_KEY (no database): each case sends the message, recent
history and conversation context to the classifier and compares the decision
with the expected intent, target and ordinals.

    python -m app.knowledge.intent_eval --cases scripts/intent_eval_cases.json

Without a key it exits with an error instead of reporting numbers.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from app.knowledge.intent import InvalidIntent, parse_intent


@dataclass(frozen=True)
class IntentEvalRun:
    case_id: str
    expected: dict[str, object]
    decided: dict[str, object] | None
    correct: bool
    seconds: float
    error: str | None


def run_cases(provider: object, cases: list[dict[str, object]], *, model: str) -> list[IntentEvalRun]:
    runs: list[IntentEvalRun] = []
    for case in cases:
        context = dict(case.get("context", {}))  # type: ignore[arg-type]
        listed = context.get("previous_answer_listed_files", [])
        context.setdefault("mentioned_folders", 0)
        context.setdefault("mentioned_files", 0)
        context.setdefault("previous_answer_listed_files", [])
        context.setdefault("previous_turn_had_files", False)
        context.setdefault("has_previous_answer", False)
        expected = dict(case["expect"])  # type: ignore[arg-type]
        started = time.monotonic()
        try:
            raw = provider.classify_intent(  # type: ignore[attr-defined]
                question=case["question"], history=case.get("history", []), context=context, model=model,
            )
            decision = parse_intent(
                raw, listed_files=len(listed) if isinstance(listed, list) else 0,
                mentioned=int(context["mentioned_files"]) + int(context["mentioned_folders"]),
            )
        except (InvalidIntent, ValueError, TypeError, RuntimeError) as error:
            runs.append(IntentEvalRun(
                str(case["id"]), expected, None, False, round(time.monotonic() - started, 2), type(error).__name__,
            ))
            continue
        decided = {"intent": decision.intent, "target": decision.target, "ordinals": list(decision.ordinals)}
        correct = all(decided[key] == value for key, value in expected.items())
        runs.append(IntentEvalRun(
            str(case["id"]), expected, decided, correct, round(time.monotonic() - started, 2), None,
        ))
    return runs


def markdown_report(runs: list[IntentEvalRun]) -> str:
    lines = ["| case | expected | decided | ok | s | error |", "|---|---|---|---|---|---|"]
    for run in runs:
        lines.append(
            f"| {run.case_id} | {json.dumps(run.expected, ensure_ascii=False)} | "
            f"{json.dumps(run.decided, ensure_ascii=False) if run.decided else ''} | "
            f"{'yes' if run.correct else 'no'} | {run.seconds} | {run.error or ''} |"
        )
    correct = sum(run.correct for run in runs)
    lines.append(f"\nAccuracy: {correct}/{len(runs)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import os

    from app.knowledge.questions import PLANNER_MODEL, OpenAIQuestionProvider

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", type=Path, default=Path("scripts/intent_eval_cases.json"))
    parser.add_argument("--model", help="classifier model (default: AGENT_PLANNER_MODEL)")
    parser.add_argument("--output", type=Path, help="write the runs as JSON")
    args = parser.parse_args(argv)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY is not configured; no numbers reported.", file=sys.stderr)
        return 2
    provider = OpenAIQuestionProvider(api_key)
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    runs = run_cases(provider, cases, model=args.model or os.environ.get("AGENT_PLANNER_MODEL", PLANNER_MODEL))
    print(markdown_report(runs))
    if args.output:
        args.output.write_text(json.dumps([asdict(run) for run in runs], ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(run.error is None for run in runs) else 1


if __name__ == "__main__":
    sys.exit(main())
