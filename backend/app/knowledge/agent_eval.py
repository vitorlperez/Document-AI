"""End-to-end evaluation of the document agent against real project data.

    python -m app.knowledge.agent_eval --organization-id ORG --user-id USER \
        --folder-id FOLDER --cases scripts/agent_eval_cases.json --output eval.json

Every case runs once inside a transaction that is rolled back, so usage records
and other writes never persist. It calls the configured OpenAI provider, so it
costs real tokens. The report shows, per case, which intent ran, whether the
classifier fell back, and whether the answer carries sources with links.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.knowledge.agent import AgentLimits, AgentService, FlowModels, agent_service_from_settings
from app.knowledge.answer_assessment import OfflineAnswerJudge
from app.knowledge.questions import SemanticProvider

_URL = re.compile(r"https?://|www\.", re.IGNORECASE)


@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    providers: list[str]
    mentions: list[tuple[str, UUID]]
    must_mention: list[str]


@dataclass(frozen=True)
class EvalRun:
    case_id: str
    intent: str
    decided_by: str
    seconds: float
    error: str | None
    answer: str | None
    answer_chars: int
    citations: int
    citations_with_link: int
    answer_marks_sources: bool
    answer_has_url: bool
    catalog_files: int
    catalog_files_named: int
    must_mention_hits: int
    must_mention_total: int
    assessment: dict | None = None
    judge: dict | None = None
    judge_error: str | None = None


def load_cases(path: Path, *, folder_id: UUID | None) -> list[EvalCase]:
    """Cases may use "$FOLDER" as a mention id, replaced by --folder-id."""
    cases: list[EvalCase] = []
    for raw in json.loads(path.read_text(encoding="utf-8")):
        mentions: list[tuple[str, UUID]] = []
        for mention in raw.get("mentions", []):
            node_id = mention["node_id"]
            if node_id == "$FOLDER":
                if folder_id is None:
                    raise SystemExit(f"case {raw['id']} needs --folder-id")
                mentions.append((mention["kind"], folder_id))
            else:
                mentions.append((mention["kind"], UUID(node_id)))
        cases.append(
            EvalCase(
                id=raw["id"], question=raw["question"], providers=list(raw.get("providers", [])),
                mentions=mentions, must_mention=list(raw.get("must_mention", [])),
            )
        )
    return cases


def run_case(
    session: Session, provider: SemanticProvider, case: EvalCase, *, scope: OrganizationScope,
    user_id: UUID, limits: AgentLimits, models: FlowModels,
    settings=None, judge: OfflineAnswerJudge | None = None,
) -> EvalRun:
    started = time.monotonic()
    judged, judge_error = None, None
    try:
        agent = (agent_service_from_settings(session, provider, settings) if settings is not None
                 else AgentService(session, provider, limits, models=models))
        result, tool_results, references = agent.ask(
            scope=scope, user_id=user_id, question=case.question, providers=case.providers,
            mentions=case.mentions, history=[],
        )
        if judge is not None and result.answer:
            try:
                judged = judge.judge(question=case.question, result=result,
                                     intent=str((result.resolved_context or {}).get('intent', '')),
                                     catalog=tool_results)
            except Exception as error:  # noqa: BLE001 - no provider text in reports
                judge_error = type(error).__name__
    except Exception as error:  # noqa: BLE001 - the report records any failure
        return EvalRun(
            case.id, "error", "error", round(time.monotonic() - started, 2), type(error).__name__,
            None, 0, 0, 0, False, False, 0, 0, 0, len(case.must_mention),
        )
    finally:
        session.rollback()
    answer = result.answer or ""
    folded = answer.casefold()
    files = [item["name"] for item in references if item.get("kind") == "file"]
    context = result.resolved_context or {}
    return EvalRun(
        case_id=case.id,
        intent=str(context.get("intent", "")),
        decided_by=str(context.get("decided_by", "")),
        seconds=round(time.monotonic() - started, 2),
        error=None,
        answer=result.answer,
        answer_chars=len(answer),
        citations=len(result.citations),
        citations_with_link=sum(bool(item.source_url.strip()) for item in result.citations),
        answer_marks_sources="(fonte" in folded,
        answer_has_url=bool(_URL.search(answer)),
        catalog_files=len(files),
        catalog_files_named=sum(name.casefold() in folded for name in files),
        must_mention_hits=sum(term.casefold() in folded for term in case.must_mention),
        must_mention_total=len(case.must_mention),
        assessment=context.get("assessment"), judge=judged, judge_error=judge_error,
    )


def run_all(
    session: Session, provider: SemanticProvider, cases: list[EvalCase], *, scope: OrganizationScope,
    user_id: UUID, limits: AgentLimits, models: FlowModels,
    settings=None, judge: OfflineAnswerJudge | None = None,
) -> list[EvalRun]:
    return [
        run_case(session, provider, case, scope=scope, user_id=user_id, limits=limits, models=models,
                 settings=settings, judge=judge)
        for case in cases
    ]


def markdown_report(runs: list[EvalRun]) -> str:
    lines = [
        "| case | intent | decided by | s | chars | citations (link) | (fonte n) | url | files named | must mention | error |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for run in runs:
        lines.append(
            f"| {run.case_id} | {run.intent} | {run.decided_by} | {run.seconds} | {run.answer_chars} | "
            f"{run.citations} ({run.citations_with_link}) | {'yes' if run.answer_marks_sources else 'no'} | "
            f"{'yes' if run.answer_has_url else 'no'} | {run.catalog_files_named}/{run.catalog_files} | "
            f"{run.must_mention_hits}/{run.must_mention_total} | {run.error or ''} |"
        )
    answered = [run for run in runs if run.error is None]
    if runs:
        classified = sum(run.decided_by == "llm" for run in answered)
        cited = sum(run.citations_with_link > 0 for run in answered)
        lines.append(
            f"\nClassifier decided {classified}/{len(runs)}; answers with linked sources {cited}/{len(runs)}."
        )
    judged = [run for run in runs if run.judge is not None]
    lines.append(f"\nOffline judge: {len(judged)}/{len(runs)} evaluated; "
                 f"{sum(run.judge_error is not None for run in runs)} errors.")
    if judged:
        for key in ('grounding', 'relevance', 'completeness'):
            lines.append(f"Mean {key}: {sum(run.judge[key] for run in judged) / len(judged):.3f}")
    return "\n".join(lines)


def feedback_calibration(session: Session, *, scope: OrganizationScope, user_id: UUID) -> list[dict]:
    """Export only this member's labeled decision metadata, never prompts or excerpts."""
    from sqlalchemy import select

    from app.knowledge.models import Conversation, ConversationMessage
    from app.library.service import LibraryService

    LibraryService(session).require_member(scope=scope, user_id=user_id)
    messages = session.scalars(select(ConversationMessage).join(
        Conversation, Conversation.id == ConversationMessage.conversation_id,
    ).where(Conversation.organization_id == scope.organization_id, Conversation.user_id == user_id,
            ConversationMessage.role == 'assistant'))
    return [{'message_id': str(message.id), 'feedback': message.context['feedback'],
             'assessment': (message.context.get('resolved_context') or {}).get('assessment')}
            for message in messages if (message.context or {}).get('feedback')]


def main(argv: list[str] | None = None) -> int:
    from app.core.config import get_settings
    from app.core.database import build_engine, build_session_factory
    from app.knowledge.questions import OpenAIQuestionProvider

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--organization-id", type=UUID, required=True)
    parser.add_argument("--user-id", type=UUID, required=True)
    parser.add_argument("--folder-id", type=UUID)
    parser.add_argument("--cases", type=Path, default=Path("scripts/agent_eval_cases.json"))
    parser.add_argument("--output", type=Path, help="write the full runs, answers included, as JSON")
    parser.add_argument('--llm-judge', action='store_true', help='opt-in paid offline evaluation')
    parser.add_argument('--judge-model', help='defaults to the configured synthesis model')
    parser.add_argument('--feedback-output', type=Path, help='export own votes and shadow decisions, no content')
    args = parser.parse_args(argv)

    settings = get_settings()
    provider = OpenAIQuestionProvider(
        settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
    )
    limits = AgentLimits(
        max_result_bytes=settings.agent_max_tool_result_bytes,
        max_seconds=settings.agent_max_seconds,
    )
    models = FlowModels(
        planner_model=settings.agent_planner_model, synthesis_model=settings.agent_synthesis_model,
        intent_timeout_seconds=settings.agent_intent_timeout_seconds,
    )
    cases = load_cases(args.cases, folder_id=args.folder_id)
    session_factory = build_session_factory(build_engine(settings))
    with session_factory() as session:
        runs = run_all(
            session, provider, cases, scope=OrganizationScope(args.organization_id), user_id=args.user_id,
            limits=limits, models=models, settings=settings,
            judge=OfflineAnswerJudge(provider.api_key, model=args.judge_model or settings.agent_synthesis_model)
            if args.llm_judge else None,
        )
        if args.feedback_output:
            args.feedback_output.write_text(json.dumps(
                feedback_calibration(session, scope=OrganizationScope(args.organization_id),
                                     user_id=args.user_id), ensure_ascii=False, indent=2), encoding='utf-8')
    print(markdown_report(runs))
    if args.output:
        args.output.write_text(
            json.dumps([asdict(run) for run in runs], ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
