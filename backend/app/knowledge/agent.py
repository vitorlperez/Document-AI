"""Framework-independent, bounded tool execution for the document agent.

The library is a local projected catalog, not a live provider inventory.  Listing
always means direct children from that catalog; search and retrieval never access
remote URLs, credentials, or arbitrary database records.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import log_agent_phase
from app.core.scoping import OrganizationScope
from app.knowledge.models import Conversation, ConversationMessage
from app.knowledge.questions import (
    _INVENTORY_DOCUMENT_TERMS,
    _INVENTORY_REQUEST_TERMS,
    _QUERY_TOKEN,
    ANSWER_MODEL,
    PLANNER_MODEL,
    RETRIEVAL_STATUS_SUFFICIENT,
    AIProviderUnavailable,
    Evidence,
    GeneratedAnswer,
    QuestionResult,
    QuestionService,
    SemanticProvider,
    _is_document_inventory_question,
    _number_answer_sources,
    _validate_citations,
)
from app.library.service import CatalogFileSnapshot, LibraryService, SyncAccessDenied

MAX_HISTORY_MESSAGES = 12
MAX_MODEL_HISTORY_BYTES = 12_000
INVENTORY_PAGE_SIZE = 100
INVENTORY_MAX_ITEMS = 500
PLAN_INTENTS = ("inventory", "inventory_with_summaries", "question", "summary", "search", "follow_up")
PLAN_TOOLS = (
    "list_folder_inventory", "summarize_previous_files", "retrieve_evidence", "summarize_documents",
    "search_library",
)
MAX_PLAN_STEPS = 3
MAX_SYNTHESIS_SOURCES = 24
MAX_SYNTHESIS_CATALOG_ITEMS = 200
MAX_PLANNER_HISTORY_MESSAGES = 4
logger = logging.getLogger("document_intelligence.agent")


@contextmanager
def _observed_phase(phase: str, deadline: float):
    started_at = time.monotonic()
    failure_kind = None
    try:
        yield
    except AIProviderUnavailable as error:
        failure_kind = (
            "agent_deadline" if str(error) == "document agent deadline exceeded"
            else "provider_deadline_preflight" if str(error) == "AI provider deadline exceeded"
            else "provider_unavailable"
        )
        raise
    except Exception:
        failure_kind = "internal_error"
        raise
    finally:
        log_agent_phase(
            logger, phase=phase, started_at=started_at,
            deadline=deadline, failure_kind=failure_kind,
        )


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class ToolResult:
    name: str
    payload: dict[str, object]
    question_result: QuestionResult | None = None
    # Indexed files behind a catalog answer. Kept out of the payload so source
    # URLs never reach the model; they only become the answer's citations.
    citations: tuple[Evidence, ...] = ()


@runtime_checkable
class ToolCallingAdapter(Protocol):
    def tool_calls(
        self, *, question: str, history: list[dict[str, object]], tool_results: list[dict[str, object]]
    ) -> list[ToolCall]: ...


@runtime_checkable
class PlanningSynthesisAdapter(Protocol):
    def plan_query(
        self, *, question: str, history: list[dict[str, object]], context: dict[str, object],
        tools: list[str], intents: list[str], model: str = ...,
    ) -> dict[str, object]: ...

    def synthesize_answer(
        self, *, question: str, intent: str, sources: list[Evidence], catalog: list[dict[str, object]],
        model: str = ...,
    ) -> GeneratedAnswer: ...


@dataclass(frozen=True)
class AgentLimits:
    max_steps: int = 4
    max_result_bytes: int = 48_000
    max_seconds: int = 25


@dataclass(frozen=True)
class PlannedFlow:
    """Flag-gated planner -> tools -> synthesis flow. Disabled by default."""

    enabled: bool = False
    planner_model: str = PLANNER_MODEL
    synthesis_model: str = ANSWER_MODEL
    # Share of the agent deadline the planned flow may use, so the current
    # path still has time to answer when it falls back.
    budget_fraction: float = 0.5


@dataclass(frozen=True)
class PlannedStep:
    tool: str
    query: str = ""


@dataclass(frozen=True)
class AgentPlan:
    intent: str
    steps: tuple[PlannedStep, ...]


class PlannedFlowRejected(ValueError):
    """The planned flow cannot produce a verifiable answer; use the current path."""


class ConversationService:
    """Persistence boundary that rechecks ownership on every access."""

    def __init__(self, session: Session):
        self.session = session

    def history(
        self, *, scope: OrganizationScope, user_id: UUID, conversation_id: UUID
    ) -> tuple[Conversation, list[ConversationMessage]]:
        LibraryService(self.session).require_member(scope=scope, user_id=user_id)
        conversation = self.session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.organization_id == scope.organization_id,
                Conversation.user_id == user_id,
            )
        )
        if conversation is None:
            raise SyncAccessDenied("conversation unavailable")
        messages = list(
            self.session.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conversation.id)
                .order_by(ConversationMessage.position.desc())
                .limit(MAX_HISTORY_MESSAGES)
            )
        )
        return conversation, list(reversed(messages))

    def create_or_load(
        self, *, scope: OrganizationScope, user_id: UUID, conversation_id: UUID | None, question: str
    ) -> tuple[Conversation, list[ConversationMessage]]:
        LibraryService(self.session).require_member(scope=scope, user_id=user_id)
        if conversation_id is not None:
            return self.history(scope=scope, user_id=user_id, conversation_id=conversation_id)
        conversation = Conversation(
            organization_id=scope.organization_id, user_id=user_id, title=question[:160]
        )
        self.session.add(conversation)
        self.session.flush()
        return conversation, []

    def append(
        self,
        *,
        conversation: Conversation,
        role: str,
        content: str,
        context: dict[str, object] | None = None,
        response: dict[str, object] | None = None,
    ) -> ConversationMessage:
        locked_conversation = self.session.scalar(
            select(Conversation)
            .where(Conversation.id == conversation.id)
            .with_for_update()
        )
        if locked_conversation is None:
            raise SyncAccessDenied("conversation unavailable")
        position = int(
            self.session.scalar(
                select(func.coalesce(func.max(ConversationMessage.position), 0)).where(
                    ConversationMessage.conversation_id == locked_conversation.id
                )
            )
            or 0
        ) + 1
        message = ConversationMessage(
            conversation_id=locked_conversation.id, position=position, role=role, content=content,
            context=context, response=response,
        )
        self.session.add(message)
        self.session.flush()
        return message


class LibraryToolExecutor:
    """Typed local-catalog tools.  Every invocation is tenant/member scoped."""

    def __init__(self, session: Session, provider: SemanticProvider):
        self.session, self.provider = session, provider

    def list_library_children(
        self, *, scope: OrganizationScope, user_id: UUID, providers: list[str], mentions: list[tuple[str, UUID]],
        parent_id: UUID, page: int = 1, page_size: int = 50, include_excerpts: bool = False,
    ) -> ToolResult:
        if not 1 <= page <= 10_000 or not 1 <= page_size <= 100:
            raise ValueError("invalid direct-child page")
        items, total = LibraryService(self.session).catalog_children(
            scope=scope, user_id=user_id, providers=providers, mentions=mentions,
            parent_id=parent_id, page=page, page_size=page_size,
        )
        snapshots = {
            snapshot.id: snapshot
            for snapshot in LibraryService(self.session).catalog_file_snapshots(
                scope=scope,
                user_id=user_id,
                providers=providers,
                node_ids=[item.id for item in items if item.kind == "file"],
                validate_references=False,
            )
        }
        return ToolResult(
            "list_library_children",
            {
                "semantics": "direct_children_local_catalog_snapshot",
                "items": [
                    {
                        "id": str(item.id),
                        "kind": item.kind,
                        "name": item.name,
                        "parent_id": str(item.parent_id) if item.parent_id else None,
                        **(
                            {"index_status": snapshots[item.id].index_status}
                            if item.kind == "file" and item.id in snapshots
                            else {}
                        ),
                        **(
                            {"excerpt": snapshots[item.id].excerpt}
                            if include_excerpts and item.kind == "file" and item.id in snapshots
                            else {}
                        ),
                    }
                    for item in items
                ],
                "page": page, "page_size": page_size, "total": total,
            },
            citations=_snapshot_citations(
                snapshots[item.id] for item in items if item.id in snapshots
            ),
        )

    def search_library(
        self, *, scope: OrganizationScope, user_id: UUID, providers: list[str],
        mentions: list[tuple[str, UUID]], query: str,
    ) -> ToolResult:
        items = LibraryService(self.session).catalog_search(
            scope=scope, user_id=user_id, providers=providers, mentions=mentions, query=query, limit=50
        )
        return ToolResult(
            "search_library",
            {
                "semantics": "local_catalog_name_search_not_remote_inventory",
                "items": [{"id": str(item.id), "kind": item.kind, "name": item.name} for item in items],
            },
        )

    def retrieve_evidence(
        self, *, scope: OrganizationScope, user_id: UUID, question: str, providers: list[str], mentions: list[tuple[str, UUID]]
    ) -> ToolResult:
        # ask_selection resolves the current catalog again, so stored references
        # cannot retain access after a membership, provider, or folder change.
        result = QuestionService(self.session, self.provider).ask_selection(
            scope=scope, user_id=user_id, question=question, providers=providers, mentions=mentions
        )
        return ToolResult(
            "retrieve_evidence",
            {
                "retrieval_status": result.retrieval_status,
                "citation_count": len(result.citations),
                "citations": [_evidence_payload(item) for item in result.citations],
            },
            result,
        )

    def summarize_documents(
        self, *, scope: OrganizationScope, user_id: UUID, question: str, providers: list[str], mentions: list[tuple[str, UUID]]
    ) -> ToolResult:
        result = QuestionService(self.session, self.provider).ask_selection(
            scope=scope, user_id=user_id, question=question, providers=providers, mentions=mentions
        )
        return ToolResult(
            "summarize_documents",
            {
                "retrieval_status": result.retrieval_status,
                "citation_count": len(result.citations),
                "answer": result.answer,
            },
            result,
        )


class AgentService:
    """Runs model-requested local tools within fixed time, step, and byte limits."""

    def __init__(
        self, session: Session, provider: SemanticProvider, limits: AgentLimits,
        planned: PlannedFlow | None = None,
    ):
        self.session, self.provider, self.limits = session, provider, limits
        self.planned = planned or PlannedFlow()
        self.tools = LibraryToolExecutor(session, provider)

    def ask(
        self,
        *,
        scope: OrganizationScope,
        user_id: UUID,
        question: str,
        providers: list[str],
        mentions: list[tuple[str, UUID]],
        history: list[ConversationMessage],
    ) -> tuple[QuestionResult, list[dict[str, object]], list[dict[str, str]]]:
        started = time.monotonic()
        if self.planned.enabled and isinstance(self.provider, PlanningSynthesisAdapter):
            planned = self._try_planned(
                scope=scope, user_id=user_id, question=question, providers=providers,
                mentions=mentions, history=history, started=started,
            )
            if planned is not None:
                return planned
        model = self.provider if isinstance(self.provider, ToolCallingAdapter) else None
        tool_results: list[ToolResult] = []
        serialized: list[dict[str, object]] = []
        effective_mentions = self._follow_up_mentions(
            question=question, history=history, providers=providers, mentions=mentions,
        )
        inventory_folders = [node_id for kind, node_id in effective_mentions if kind == "folder"]
        summary_inventory = _is_inventory_summary_request(question)
        if (_is_document_inventory_question(question) or summary_inventory) and len(inventory_folders) == 1:
            with _observed_phase("inventory", started + self.limits.max_seconds):
                result = self._complete_inventory(
                    scope=scope, user_id=user_id, providers=providers, mentions=effective_mentions,
                    parent_id=inventory_folders[0], deadline=started + self.limits.max_seconds,
                    include_excerpts=summary_inventory,
                )
            item = {"name": result.name, "result": result.payload}
            if _json_size([item]) > self.limits.max_result_bytes:
                raise AIProviderUnavailable("document agent result exceeds configured byte limit")
            return _catalog_question_result(result), [item], _catalog_references([item])
        if not mentions and _plural_file_reference(question):
            references = self._follow_up_file_references(history=history)
            if references:
                result = self._summarize_inventory_follow_up(
                    scope=scope, user_id=user_id, providers=providers, references=references
                )
                item = {"name": result.name, "result": result.payload}
                return _catalog_question_result(result), [item], _catalog_references([item])
        for _step in range(self.limits.max_steps):
            remaining = self.limits.max_seconds - (time.monotonic() - started)
            if remaining <= 0:
                break
            with _observed_phase("planning", started + self.limits.max_seconds), _request_deadline(started + self.limits.max_seconds):
                calls = model.tool_calls(
                    question=question,
                    history=_bounded_history(history),
                    tool_results=serialized,
                ) if model else []
            if not calls:
                break
            for call in calls[:1]:
                with _observed_phase("tool_execution", started + self.limits.max_seconds), _request_deadline(started + self.limits.max_seconds):
                    result = self._execute(
                        call=call, scope=scope, user_id=user_id, question=question,
                        providers=providers, mentions=effective_mentions,
                    )
                item = {"name": result.name, "result": result.payload}
                if _json_size([*serialized, item]) > self.limits.max_result_bytes:
                    break
                tool_results.append(result)
                serialized.append(item)
            if _json_size(serialized) >= self.limits.max_result_bytes:
                break
        question_results = [item.question_result for item in tool_results if item.question_result is not None]
        catalog_results = [item for item in tool_results if item.name in {"search_library", "list_library_children"}]
        if not question_results and not catalog_results and time.monotonic() >= started + self.limits.max_seconds:
            log_agent_phase(
                logger, phase="retrieval_fallback", started_at=time.monotonic(),
                deadline=started + self.limits.max_seconds, failure_kind="agent_deadline",
            )
            raise AIProviderUnavailable("document agent deadline exceeded")
        final_phase = "finalization" if question_results or catalog_results else "retrieval_fallback"
        with _observed_phase(final_phase, started + self.limits.max_seconds), _request_deadline(started + self.limits.max_seconds):
            final = (
                question_results[-1]
                if question_results
                else _catalog_question_result(catalog_results[-1])
                if catalog_results
                else self.tools.retrieve_evidence(
                    scope=scope, user_id=user_id, question=question, providers=providers, mentions=effective_mentions
                ).question_result
            )
        assert final is not None
        return final, serialized, _catalog_references(serialized)

    def _try_planned(
        self, *, scope: OrganizationScope, user_id: UUID, question: str, providers: list[str],
        mentions: list[tuple[str, UUID]], history: list[ConversationMessage], started: float,
    ) -> tuple[QuestionResult, list[dict[str, object]], list[dict[str, str]]] | None:
        """Run the planned flow; None means fall back to the current path.

        Authorization and usage-limit errors are not provider failures and
        propagate unchanged.
        """
        deadline = started + self.limits.max_seconds * self.planned.budget_fraction
        started_at = time.monotonic()
        try:
            with _request_deadline(deadline):
                return self._ask_planned(
                    scope=scope, user_id=user_id, question=question, providers=providers,
                    mentions=mentions, history=history, deadline=deadline,
                )
        except (AIProviderUnavailable, ValueError, TypeError, KeyError) as error:
            log_agent_phase(
                logger, phase="planned_fallback", started_at=started_at, deadline=deadline,
                failure_kind=(
                    "planned_rejected" if isinstance(error, PlannedFlowRejected)
                    else "provider_unavailable" if isinstance(error, AIProviderUnavailable)
                    else "invalid_output"
                ),
            )
            return None

    def _ask_planned(
        self, *, scope: OrganizationScope, user_id: UUID, question: str, providers: list[str],
        mentions: list[tuple[str, UUID]], history: list[ConversationMessage], deadline: float,
    ) -> tuple[QuestionResult, list[dict[str, object]], list[dict[str, str]]]:
        adapter = self.provider
        assert isinstance(adapter, PlanningSynthesisAdapter)
        effective_mentions = self._follow_up_mentions(
            question=question, history=history, providers=providers, mentions=mentions,
        )
        folders = [node_id for kind, node_id in effective_mentions if kind == "folder"]
        # An ordinal follow-up ("resuma o segundo") already narrowed the scope to one
        # file; offering every previously listed file would let the plan ignore it.
        narrowed = bool(effective_mentions) and not _plural_file_reference(question)
        previous_files = [] if mentions or narrowed else self._follow_up_file_references(history=history)
        with _observed_phase("planned_planner", deadline):
            raw_plan = adapter.plan_query(
                question=question,
                history=_planner_history(history),
                context={
                    "mentioned_folders": sum(kind == "folder" for kind, _ in effective_mentions),
                    "mentioned_files": sum(kind == "file" for kind, _ in effective_mentions),
                    "previous_answer_listed_files": len(previous_files),
                },
                tools=list(PLAN_TOOLS), intents=list(PLAN_INTENTS), model=self.planned.planner_model,
            )
        plan = _parse_plan(raw_plan, max_steps=min(MAX_PLAN_STEPS, self.limits.max_steps))
        results: list[ToolResult] = []
        serialized: list[dict[str, object]] = []
        for step in plan.steps:
            if time.monotonic() >= deadline:
                raise AIProviderUnavailable("document agent deadline exceeded")
            with _observed_phase("planned_tool", deadline):
                result = self._execute_planned(
                    step=step, scope=scope, user_id=user_id, question=question, providers=providers,
                    mentions=effective_mentions, folders=folders, previous_files=previous_files,
                    deadline=deadline,
                )
            if result is None:
                continue
            item = {"name": result.name, "result": result.payload}
            if _json_size([*serialized, item]) > self.limits.max_result_bytes:
                break
            results.append(result)
            serialized.append(item)
        sources = _synthesis_sources(results)
        catalog = _synthesis_catalog(results)
        if not sources and not catalog:
            raise PlannedFlowRejected("planned tools returned nothing to synthesize")
        with _observed_phase("planned_synthesis", deadline):
            generated = adapter.synthesize_answer(
                question=question, intent=plan.intent, sources=sources, catalog=catalog,
                model=self.planned.synthesis_model,
            )
        if not generated.text or generated.text.casefold().strip() == "insufficient evidence.":
            raise PlannedFlowRejected("synthesis produced no answer")
        indexes = list(dict.fromkeys(generated.citation_indexes))
        cited = _validate_citations(indexes, sources) if indexes else []
        if sources and not cited:
            # Uncited or out-of-range markers cannot back the "Fontes" block.
            raise PlannedFlowRejected("synthesis citations are invalid")
        answer = (
            _number_answer_sources(generated.text, indexes, sources, cited)
            if cited else generated.text
        )
        only_catalog = all(result.question_result is None for result in results)
        return (
            QuestionResult(
                answer=answer, confidence="supported", citations=cited,
                retrieval_status="catalog" if only_catalog else RETRIEVAL_STATUS_SUFFICIENT,
                resolved_context={
                    "agent_flow": "planned", "intent": plan.intent,
                    "tools": [result.name for result in results],
                },
            ),
            serialized,
            _catalog_references(serialized),
        )

    def _execute_planned(
        self, *, step: PlannedStep, scope: OrganizationScope, user_id: UUID, question: str,
        providers: list[str], mentions: list[tuple[str, UUID]], folders: list[UUID],
        previous_files: list[tuple[UUID, UUID]], deadline: float,
    ) -> ToolResult | None:
        # Like _execute, the plan only picks tools; scope comes from the request.
        if step.tool == "list_folder_inventory":
            if len(folders) != 1:
                return None
            return self._complete_inventory(
                scope=scope, user_id=user_id, providers=providers, mentions=mentions,
                parent_id=folders[0], deadline=deadline, include_excerpts=True,
            )
        if step.tool == "summarize_previous_files":
            if not previous_files:
                return None
            return self._summarize_inventory_follow_up(
                scope=scope, user_id=user_id, providers=providers, references=previous_files,
            )
        if step.tool == "search_library":
            return self.tools.search_library(
                scope=scope, user_id=user_id, providers=providers, mentions=mentions,
                query=step.query or question,
            )
        if step.tool == "summarize_documents":
            return self.tools.summarize_documents(
                scope=scope, user_id=user_id, question=question, providers=providers, mentions=mentions
            )
        return self.tools.retrieve_evidence(
            scope=scope, user_id=user_id, question=question, providers=providers, mentions=mentions
        )

    def _follow_up_mentions(
        self, *, question: str, history: list[ConversationMessage], providers: list[str],
        mentions: list[tuple[str, UUID]],
    ) -> list[tuple[str, UUID]]:
        if mentions:
            return mentions
        ordinal = _ordinal_reference(question)
        follow_up_all = _plural_file_reference(question)
        if ordinal is None and not follow_up_all:
            return mentions
        for message in reversed(history):
            references = (message.context or {}).get("references")
            if not isinstance(references, list):
                continue
            files = [item for item in references if isinstance(item, dict) and item.get("kind") == "file"]
            if follow_up_all:
                resolved: list[tuple[str, UUID]] = []
                for item in files:
                    raw_id = item.get("id")
                    if not isinstance(raw_id, str):
                        continue
                    try:
                        resolved.append(("file", UUID(raw_id)))
                    except ValueError:
                        continue
                if resolved:
                    return resolved
            elif ordinal is not None and ordinal <= len(files):
                raw_id = files[ordinal - 1].get("id")
                if isinstance(raw_id, str):
                    try:
                        return [("file", UUID(raw_id))]
                    except ValueError:
                        continue
        return mentions

    def _follow_up_file_references(self, *, history: list[ConversationMessage]) -> list[tuple[UUID, UUID]]:
        for message in reversed(history):
            references = (message.context or {}).get("references")
            if not isinstance(references, list):
                continue
            result: list[tuple[UUID, UUID]] = []
            for item in references:
                if not isinstance(item, dict) or item.get("kind") != "file":
                    continue
                raw_id, raw_folder_id = item.get("id"), item.get("folder_id")
                if not isinstance(raw_id, str) or not isinstance(raw_folder_id, str):
                    continue
                try:
                    result.append((UUID(raw_id), UUID(raw_folder_id)))
                except ValueError:
                    continue
            if result:
                return result
        return []

    def _complete_inventory(
        self, *, scope: OrganizationScope, user_id: UUID, providers: list[str],
        mentions: list[tuple[str, UUID]], parent_id: UUID, deadline: float,
        include_excerpts: bool = False,
    ) -> ToolResult:
        items: list[dict[str, object]] = []
        citations: list[Evidence] = []
        page = 1
        total = 0
        while len(items) < INVENTORY_MAX_ITEMS:
            if time.monotonic() >= deadline:
                raise AIProviderUnavailable("document agent deadline exceeded")
            with _request_deadline(deadline):
                result = self.tools.list_library_children(
                    scope=scope, user_id=user_id, providers=providers, mentions=mentions,
                    parent_id=parent_id, page=page, page_size=INVENTORY_PAGE_SIZE,
                    include_excerpts=include_excerpts,
                )
            page_items = result.payload["items"]
            assert isinstance(page_items, list)
            items.extend(page_items)
            citations.extend(result.citations)
            total = result.payload["total"]
            assert isinstance(total, int)
            if len(page_items) < INVENTORY_PAGE_SIZE or len(items) >= total:
                break
            page += 1
        returned = min(len(items), INVENTORY_MAX_ITEMS)
        return ToolResult(
            "list_library_children",
            {
                "semantics": "direct_children_local_catalog_snapshot",
                "items": items[:returned],
                "page": 1,
                "page_size": INVENTORY_PAGE_SIZE,
                "total": total,
                "returned": returned,
                "truncated": total > returned,
                "inventory_folder_id": str(parent_id),
            },
            citations=tuple(citations),
        )

    def _summarize_inventory_follow_up(
        self, *, scope: OrganizationScope, user_id: UUID, providers: list[str],
        references: list[tuple[UUID, UUID]],
    ) -> ToolResult:
        snapshots = LibraryService(self.session).catalog_file_snapshots(
            scope=scope,
            user_id=user_id,
            providers=providers,
            node_ids=[node_id for node_id, _folder_id in references],
            inventory_folder_ids=dict(references),
        )
        return ToolResult(
            "summarize_inventory",
            {
                "semantics": "persisted_inventory_references_with_extractive_content",
                "items": [
                    {
                        "id": str(snapshot.id),
                        "kind": "file",
                        "name": snapshot.name,
                        "index_status": snapshot.index_status,
                        "excerpt": snapshot.excerpt,
                    }
                    for snapshot in snapshots
                ],
            },
            citations=_snapshot_citations(snapshots),
        )

    def _execute(
        self, *, call: ToolCall, scope: OrganizationScope, user_id: UUID, question: str,
        providers: list[str], mentions: list[tuple[str, UUID]],
    ) -> ToolResult:
        # Model arguments are untrusted. Scope-bearing arguments are deliberately
        # ignored; only request-authorized providers/mentions are used.
        if call.name == "search_library":
            value = call.arguments.get("query")
            if not isinstance(value, str):
                raise ValueError("invalid tool arguments")
            return self.tools.search_library(
                scope=scope, user_id=user_id, providers=providers, mentions=mentions, query=value
            )
        if call.name == "list_library_children":
            raw_parent, raw_page = call.arguments.get("parent_id"), call.arguments.get("page", 1)
            if not isinstance(raw_parent, str) or not isinstance(raw_page, int):
                raise ValueError("invalid tool arguments")
            return self.tools.list_library_children(
                scope=scope, user_id=user_id, providers=providers, mentions=mentions,
                parent_id=UUID(raw_parent), page=raw_page,
            )
        if call.name == "summarize_documents":
            return self.tools.summarize_documents(
                scope=scope, user_id=user_id, question=question, providers=providers, mentions=mentions
            )
        if call.name == "retrieve_evidence":
            return self.tools.retrieve_evidence(
                scope=scope, user_id=user_id, question=question, providers=providers, mentions=mentions
            )
        raise ValueError("unknown tool")


def _evidence_payload(item: Evidence) -> dict[str, object]:
    return {
        "document_id": str(item.document_id), "document_name": item.document_name,
        "excerpt": item.excerpt, "page_number": item.page_number, "source_provider": item.source_provider,
    }


def _json_size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode())


def _bounded_history(history: list[ConversationMessage]) -> list[dict[str, object]]:
    compact: list[dict[str, object]] = []
    for item in history:
        context = item.context or {}
        compact.append(
            {
                "role": item.role,
                "content": item.content[:1_000],
                "context": {
                    "providers": context.get("providers", []),
                    "mentions": context.get("mentions", []),
                    "references": context.get("references", [])[:INVENTORY_MAX_ITEMS],
                },
            }
        )
    while compact and _json_size(compact) > MAX_MODEL_HISTORY_BYTES:
        compact.pop(0)
    return compact


def _planner_history(history: list[ConversationMessage]) -> list[dict[str, object]]:
    return [
        {"role": item.role, "content": item.content[:500]}
        for item in history[-MAX_PLANNER_HISTORY_MESSAGES:]
    ]


def _parse_plan(raw: object, *, max_steps: int) -> AgentPlan:
    if not isinstance(raw, dict):
        raise PlannedFlowRejected("invalid plan")
    intent, tools = raw.get("intent"), raw.get("tools")
    if intent not in PLAN_INTENTS or not isinstance(tools, list):
        raise PlannedFlowRejected("invalid plan")
    steps: list[PlannedStep] = []
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("name") not in PLAN_TOOLS:
            continue
        query = tool.get("query")
        step = PlannedStep(str(tool["name"]), query.strip()[:200] if isinstance(query, str) else "")
        if step not in steps:
            steps.append(step)
    if not steps:
        raise PlannedFlowRejected("plan selected no tools")
    return AgentPlan(str(intent), tuple(steps[:max(1, max_steps)]))


def _synthesis_sources(results: list[ToolResult]) -> list[Evidence]:
    sources: list[Evidence] = []
    seen: set[UUID] = set()
    for result in results:
        evidence = [*result.citations, *(result.question_result.citations if result.question_result else [])]
        for item in evidence:
            if item.chunk_id in seen or not item.excerpt.strip():
                continue
            seen.add(item.chunk_id)
            sources.append(item)
    return sources[:MAX_SYNTHESIS_SOURCES]


def _synthesis_catalog(results: list[ToolResult]) -> list[dict[str, object]]:
    # Names and index state only: ids and URLs never reach the model.
    catalog: list[dict[str, object]] = []
    for result in results:
        items = result.payload.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                catalog.append({
                    key: item[key] for key in ("name", "kind", "index_status") if key in item
                })
    return catalog[:MAX_SYNTHESIS_CATALOG_ITEMS]


def _catalog_references(results: list[dict[str, object]]) -> list[dict[str, str]]:
    for result in reversed(results):
        payload = result.get("result")
        if not isinstance(payload, dict):
            continue
        items = payload.get("items")
        if not isinstance(items, list):
            continue
        references: list[dict[str, str]] = []
        for item in items:
            if not (
                isinstance(item, dict)
                and isinstance(item.get("id"), str)
                and isinstance(item.get("kind"), str)
                and isinstance(item.get("name"), str)
            ):
                continue
            reference = {"id": item["id"], "kind": item["kind"], "name": item["name"]}
            inventory_folder_id = payload.get("inventory_folder_id")
            if item["kind"] == "file" and isinstance(inventory_folder_id, str):
                reference["folder_id"] = inventory_folder_id
            references.append(reference)
        return references
    return []


def _catalog_question_result(result: ToolResult) -> QuestionResult:
    items = result.payload.get("items", [])
    if not isinstance(items, list):
        items = []
    rows = [
        _catalog_item_row(item)
        for item in items
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    ]
    if result.name == "summarize_inventory":
        answer = "Conteúdo por arquivo do inventário autorizado:\n" + "\n".join(rows)
        return QuestionResult(
            answer=answer, confidence="supported", citations=list(result.citations), retrieval_status="catalog",
            resolved_context={"catalog_tool": result.name},
        )
    if result.payload.get("semantics") == "direct_children_local_catalog_snapshot":
        prefix = (
            "Arquivos no catálogo autorizado "
            "(instantâneo local; não é uma listagem ao vivo do provedor):"
        )
    else:
        prefix = "Itens encontrados no catálogo autorizado:"
    suffix = (
        f"\n\nMostrando os primeiros {result.payload['returned']} de {result.payload['total']} "
        "itens; refine a pasta para continuar."
        if result.payload.get("truncated") else ""
    )
    answer = "Nenhum item encontrado no catálogo autorizado." if not rows else prefix + "\n" + "\n".join(rows) + suffix
    return QuestionResult(
        answer=answer, confidence="supported", citations=list(result.citations), retrieval_status="catalog",
        resolved_context={"catalog_tool": result.name},
    )


def _snapshot_citations(snapshots: Iterable[CatalogFileSnapshot]) -> tuple[Evidence, ...]:
    return tuple(
        Evidence(
            document_id=snapshot.document_id,
            document_name=snapshot.name,
            # Catalog snapshots are file-level; the document id stands in for a chunk.
            chunk_id=snapshot.document_id,
            excerpt=snapshot.excerpt or "",
            page_number=None,
            source_url=snapshot.source_url or "",
            score=1.0,
            source_provider=snapshot.source_provider,
        )
        for snapshot in snapshots
        if snapshot.document_id is not None
    )


def _catalog_item_row(item: dict[str, object]) -> str:
    name = item["name"]
    if item.get("excerpt") is not None:
        return f"- {name}: Síntese extrativa do conteúdo indexado: {item['excerpt']}"
    if item.get("index_status") == "not_indexed":
        return f"- {name}: sem conteúdo indexado disponível."
    return f"- {name} ({'Arquivo' if item.get('kind') == 'file' else 'Pasta'})"


def _ordinal_reference(question: str) -> int | None:
    normalized = question.casefold()
    for index, word in enumerate(("primeiro", "segundo", "terceiro", "quarto", "quinto"), 1):
        if word in normalized:
            return index
    return None


def _plural_file_reference(question: str) -> bool:
    normalized = question.casefold()
    negated = re.search(
        r"\b(?:não|nao)\s+(?:resuma|resumir|liste|listar|analise|analisar|descreva|descrever)\s+"
        r"(?:todos\s+os\s+arquivos|cada\s+(?:um\s+dos\s+)?arquivos?)\b",
        normalized,
    )
    if negated:
        return False
    return bool(
        re.search(
            r"\b(?:eles|elas|deles|delas|ambos|ambas|cada\s+(?:um\s+dos\s+)?arquivos?|todos\s+os\s+arquivos)\b",
            normalized,
        )
    )


def _is_inventory_summary_request(question: str) -> bool:
    """True when a file-listing question also asks what each file is about.

    Such questions often say "sobre o conteúdo", which the topical guard of
    _is_document_inventory_question treats as a search, so they are matched here.
    """
    terms = {token.casefold() for token in _QUERY_TOKEN.findall(question)}
    return bool(terms & _INVENTORY_DOCUMENT_TERMS and terms & _INVENTORY_REQUEST_TERMS) and _asks_content_summary(question)


def _asks_content_summary(question: str) -> bool:
    normalized = question.casefold()
    if re.search(r"\b(?:não|nao|sem)\s+(?:resum|explica|explique|descrev|descri)", normalized):
        return False
    return bool(
        re.search(
            r"\b(?:resum\w*|explica\w*|explique|descri\w*|descrev\w*|s[ií]ntese|sintetiz\w*"
            r"|do\s+que\s+(?:se\s+)?trata)",
            normalized,
        )
    )


def _request_deadline(deadline: float):
    from app.knowledge.questions import request_deadline

    return request_deadline(deadline)
