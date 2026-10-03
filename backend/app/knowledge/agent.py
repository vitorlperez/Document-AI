"""The document agent: one framework-independent flow over bounded local tools.

classify intent (small model, closed schema) -> execute tools -> synthesize one
grounded answer -> attach citations. The library is a local projected catalog,
not a live provider inventory. Listing always means direct children from that
catalog; search and retrieval never access remote URLs, credentials, or arbitrary
database records.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import ClassVar, Protocol, runtime_checkable
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.logging import log_agent_phase
from app.core.scoping import OrganizationScope
from app.knowledge.intent import IntentDecision, InvalidIntent, fallback_intent, parse_intent
from app.knowledge.models import Conversation, ConversationMessage, Document
from app.knowledge.questions import (
    ANSWER_MODEL,
    PLANNER_MODEL,
    RETRIEVAL_STATUS_BELOW_THRESHOLD,
    RETRIEVAL_STATUS_NO_COMPATIBLE_EMBEDDINGS,
    RETRIEVAL_STATUS_NO_INDEXED_CONTENT,
    RETRIEVAL_STATUS_SUFFICIENT,
    AIProviderUnavailable,
    Evidence,
    GeneratedAnswer,
    QuestionResult,
    QuestionService,
    SemanticProvider,
    _number_answer_sources,
    _validate_citations,
)
from app.knowledge.untrusted import sanitize_label
from app.library.models import LibraryNode
from app.library.service import CatalogFileSnapshot, LibraryService, SyncAccessDenied
from app.workspaces.models import WorkspaceFolder

MAX_HISTORY_MESSAGES = 12
INVENTORY_PAGE_SIZE = 100
INVENTORY_MAX_ITEMS = 500
MAX_SYNTHESIS_SOURCES = 24
MAX_SYNTHESIS_CATALOG_ITEMS = 200
MAX_PLANNER_HISTORY_MESSAGES = 4
# Document.index_status values meaning the provider no longer has the file (a revocation of the
# cited evidence); every other non-indexed state is an index problem, not an authorization change.
# Production only ever writes "removed"; "deleted" is kept for the test fixtures that mark a
# document withdrawn with that spelling.
WITHDRAWN_STATUSES = frozenset({"deleted", "removed"})
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
class ToolResult:
    name: str
    payload: dict[str, object]
    question_result: QuestionResult | None = None
    # Indexed files behind a catalog answer. Kept out of the payload so source
    # URLs never reach the model; they only become the answer's citations.
    citations: tuple[Evidence, ...] = ()
    # (item id, leading indexed chunks) per file whose content was asked for; kept out of the
    # payload so the byte-bounded tool results stay small. Input of the per-file summaries.
    file_chunks: tuple[tuple[str, tuple[str, ...]], ...] = ()


@runtime_checkable
class IntentClassifierAdapter(Protocol):
    def classify_intent(
        self, *, question: str, history: list[dict[str, object]], context: dict[str, object],
        model: str = ...,
    ) -> dict[str, object]: ...


@runtime_checkable
class SynthesisAdapter(Protocol):
    def synthesize_answer(
        self, *, question: str, intent: str, sources: list[Evidence], catalog: list[dict[str, object]],
        model: str = ..., previous_answer: str = ...,
    ) -> GeneratedAnswer: ...


@runtime_checkable
class FileSummaryAdapter(Protocol):
    def summarize_file_briefs(
        self, *, question: str, files: list[dict[str, object]], target_chars: int, model: str = ...,
    ) -> dict[int, str]: ...


@dataclass(frozen=True)
class FileSummaries:
    """Per-file summaries of a catalog answer: one batched call to a cheap model.

    The length is a target written into the prompt, never a hard cut; when the call
    fails or times out each file falls back to its leading indexed text, ended at a sentence.
    """

    target_chars: int = 350
    model: str = PLANNER_MODEL
    timeout_seconds: float = 8.0


@dataclass(frozen=True)
class AgentLimits:
    max_result_bytes: int = 48_000
    max_seconds: int = 25


@dataclass(frozen=True)
class FlowModels:
    """Models of the classify and synthesize stages."""

    planner_model: str = PLANNER_MODEL
    synthesis_model: str = ANSWER_MODEL
    # The classifier is one short call; past this the request falls back to a relevance search.
    intent_timeout_seconds: float = 8.0


class PlanRejected(ValueError):
    """The decided intent cannot run with the resolved targets; answer by relevance instead."""


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
            file_chunks=tuple(
                (str(item.id), snapshots[item.id].chunks) for item in items if item.id in snapshots
            ) if include_excerpts else (),
        )

    def search_library(
        self, *, scope: OrganizationScope, user_id: UUID, providers: list[str],
        mentions: list[tuple[str, UUID]], query: str,
    ) -> ToolResult:
        items = LibraryService(self.session).catalog_search(
            scope=scope, user_id=user_id, providers=providers, mentions=mentions, query=query, limit=50
        )
        snapshots = LibraryService(self.session).catalog_file_snapshots(
            scope=scope, user_id=user_id, providers=providers,
            node_ids=[item.id for item in items if item.kind == "file"], validate_references=False,
        )
        return ToolResult(
            "search_library",
            {
                "semantics": "local_catalog_name_search_not_remote_inventory",
                "items": [{"id": str(item.id), "kind": item.kind, "name": item.name} for item in items],
            },
            citations=_snapshot_citations(snapshots),
        )

    def retrieve_evidence(
        self, *, scope: OrganizationScope, user_id: UUID, question: str, providers: list[str], mentions: list[tuple[str, UUID]],
        answer_mode: str | None = None, retrieval_question: str | None = None,
    ) -> ToolResult:
        # ask_selection resolves the current catalog again, so stored references
        # cannot retain access after a membership, provider, or folder change.
        result = QuestionService(self.session, self.provider).ask_selection(
            scope=scope, user_id=user_id, question=question, providers=providers, mentions=mentions,
            answer_mode=answer_mode, retrieval_question=retrieval_question,
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
        self, *, scope: OrganizationScope, user_id: UUID, question: str, providers: list[str], mentions: list[tuple[str, UUID]],
        answer_mode: str | None = None,
    ) -> ToolResult:
        result = QuestionService(self.session, self.provider).ask_selection(
            scope=scope, user_id=user_id, question=question, providers=providers, mentions=mentions,
            answer_mode=answer_mode,
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


@dataclass(frozen=True)
class AgentRequest:
    """One authorized question; scope comes from the request, never from a model."""

    scope: OrganizationScope
    user_id: UUID
    question: str
    providers: list[str]
    mentions: list[tuple[str, UUID]]


@dataclass(frozen=True)
class ConversationState:
    """What earlier turns left behind that the current message may refer to."""

    listed_files: list[tuple[UUID, UUID | None, str]]
    previous_turn_mentions: list[tuple[str, UUID]]
    previous_answer: str | None
    # Last messages as the classifier sees them, including the end of cited answers.
    recent_messages: list[dict[str, object]] = field(default_factory=list)
    # The previous answer cited a document that is no longer authorized: it is kept out of everything
    # the AI sees and the request is rebuilt from current sources.
    memory_excluded: bool = False
    # The answer that carries the file listing was excluded: its names are not sent to the classifier.
    # `listed_files` stay as targets only, so the current authorization (and its denials) still decides.
    listing_excluded: bool = False

    @classmethod
    def from_history(
        cls, history: list[ConversationMessage], *, excluded: frozenset[int] = frozenset(),
    ) -> ConversationState:
        """`excluded` holds the indexes of assistant answers whose provenance is no longer authorized."""
        latest = _latest_answer_index(history)
        window_start = max(len(history) - MAX_PLANNER_HISTORY_MESSAGES, 0)
        listed_files, listing = _previous_listed_files(history)
        return cls(
            listed_files=listed_files,
            previous_turn_mentions=_previous_turn_mentions(history),
            previous_answer=None if latest is None or latest in excluded else history[latest].content,
            recent_messages=_planner_history([
                message for index, message in enumerate(history[window_start:], window_start)
                if index not in excluded
            ]),
            memory_excluded=latest in excluded,
            listing_excluded=listing in excluded,
        )

    def files(self) -> list[UUID]:
        """Files the conversation is about: the previous turn's attached files, else the last listed ones."""
        attached = [node_id for kind, node_id in self.previous_turn_mentions if kind == "file"]
        return attached or [node_id for node_id, _folder, _name in self.listed_files]


class AgentService:
    """The single document-agent flow, in four stages with narrow interfaces:

    1. classify: a small model maps the message to a closed IntentDecision;
    2. execute: the decided local tools run, each one tenant/member scoped;
    3. synthesize: one grounded call writes the answer from the tool outputs;
    4. cite: the answer always carries the documents it used, with their links.

    A model failure never ends in a silent empty answer: the classifier falls back to a
    relevance search, an unverifiable synthesis keeps the extractive or per-file answer,
    and missing evidence yields an honest answer that lists the consulted files as Fontes.
    """

    def __init__(
        self, session: Session, provider: SemanticProvider, limits: AgentLimits,
        models: FlowModels | None = None, file_summaries: FileSummaries | None = None,
        intent_classifier: IntentClassifierAdapter | None = None,
    ):
        self.session, self.provider, self.limits = session, provider, limits
        # Decides the intent in place of the provider (AGENT_INTENT_ENGINE=jev); None uses the provider.
        self.intent_classifier = intent_classifier
        self.models = models or FlowModels()
        self.file_summaries = file_summaries or FileSummaries()
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
        deadline = time.monotonic() + self.limits.max_seconds
        request = AgentRequest(scope, user_id, question, providers, list(mentions))
        # Provenance is rechecked against today's authorization before anything reaches the AI.
        excluded, usable_nodes = self._revalidate_memory(request, history)
        conversation = ConversationState.from_history(history, excluded=excluded)
        if not conversation.listed_files:
            cited = _previous_cited_files(self.session, history, scope.organization_id)
            if excluded and usable_nodes is not None:
                cited = [entry for entry in cited if entry[0] in usable_nodes]
            conversation = replace(
                conversation, listed_files=cited, listing_excluded=_latest_answer_index(history) in excluded,
            )
        decision = self.classify(request, conversation, deadline=deadline)
        with _request_deadline(deadline):
            run = self.execute(decision, request, conversation, deadline=deadline)
        return run.finish(self.cite(run))

    def _revalidate_memory(
        self, request: AgentRequest, history: list[ConversationMessage],
    ) -> tuple[frozenset[int], set[UUID] | None]:
        """Indexes of earlier answers whose cited documents are not (all) authorized now.

        Only the answers the flow can actually use are checked: the planner window, the latest
        answer (previous_answer) and the one that carries the file listing. An answer is excluded
        whole, not just the denied sentence: it can paraphrase the revoked source anywhere. Two cases
        count: a cited document is gone from the current scope (removed, folder/provider/membership
        denied, withdrawn index); or the request restricts the selection to part of what the answer
        cited, so the rest would leak into the narrower scope. An answer unrelated to a newly chosen
        selection is plain history and stays (owner decision P2).

        Also returns the file nodes still authorized; None when the current authorization could not
        be resolved (everything checked is then excluded and the later stages raise the real denial).
        """
        used = set(range(max(len(history) - MAX_PLANNER_HISTORY_MESSAGES, 0), len(history)))
        used.update(index for index in (_latest_answer_index(history), _previous_listed_files(history)[1])
                    if index is not None)
        provenance: dict[int, tuple[set[UUID], set[UUID]]] = {}
        for index in sorted(used):
            if history[index].role == "assistant":
                documents, nodes = _answer_provenance(history[index])
                if documents or nodes:
                    provenance[index] = (documents, nodes)
        listed, listing_index = _previous_listed_files(history)
        inventory = {node_id: folder for node_id, folder, _name in listed if folder}
        if not provenance and not inventory:
            return frozenset(), set()
        organization_id = request.scope.organization_id
        library = LibraryService(self.session)

        def authorized(mentions: list[tuple[str, UUID]], all_nodes: dict[UUID, LibraryNode] | None = None):
            return library.authorized_catalog(
                scope=request.scope, user_id=request.user_id, providers=request.providers,
                mentions=mentions, all_nodes=all_nodes,
            )

        try:
            catalog = authorized([])
        except (SyncAccessDenied, ValueError):
            unresolved = set(provenance)
            if inventory and listing_index is not None:
                unresolved.add(listing_index)
            return frozenset(unresolved), None
        allowed, admitted_folders = catalog.nodes, catalog.folder_ids
        cited_ids = {document for documents, _nodes in provenance.values() for document in documents}
        listed_externals = {
            allowed[node_id].external_id for _documents, nodes in provenance.values()
            for node_id in nodes if node_id in allowed
        }
        rows = list(self.session.execute(
            select(
                Document.id, Document.workspace_folder_id, WorkspaceFolder.source_id,
                Document.external_file_id, Document.index_status,
            )
            .join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
            .where(
                Document.organization_id == organization_id, WorkspaceFolder.organization_id == organization_id,
                or_(Document.id.in_(cited_ids), Document.external_file_id.in_(listed_externals)),
            )
        ))
        # A failed or pending index is not a revocation (ADR-0007: retained index, no new ACL); a
        # provider-side deletion is. A document counts only inside a folder admitted today: a ready
        # sibling folder of the same source does not vouch for a denied one.
        live = {
            (source, external) for _id, folder, source, external, status in rows
            if folder in admitted_folders and status not in WITHDRAWN_STATUSES
        }
        known = {(source, external) for _id, _folder, source, external, _status in rows}

        def usable(nodes_in_scope: dict[UUID, LibraryNode]) -> tuple[set[UUID], set[UUID]]:
            """(documents, file nodes) readable inside this node set."""
            files = {
                (node.source_id, node.external_id): node.id for node in nodes_in_scope.values()
                if node.kind == "file" and ((node.source_id, node.external_id) in live
                                            or (node.source_id, node.external_id) not in known)
            }
            documents = {
                document_id for document_id, folder, source, external, status in rows
                if document_id in cited_ids and folder in admitted_folders and status not in WITHDRAWN_STATUSES
                and (source, external) in files
            }
            return documents, set(files.values())

        documents_now, nodes_now = usable(allowed)
        selected: tuple[set[UUID], set[UUID]] | None = None
        excluded = set()
        # A listed file that left its listed folder (same source, so the catalog still admits it) is an
        # inventory reference the later snapshot check denies as a whole; its name must not reach the AI
        # in the meantime, so the answer that carries the listing is kept out like a revoked one.
        if listing_index is not None and any(
            node_id not in catalog.all_nodes
            or library._node_path(catalog.all_nodes[node_id], catalog.all_nodes) is None
            or folder not in catalog.all_nodes
            or not library._descends_from(catalog.all_nodes[node_id], catalog.all_nodes[folder], catalog.all_nodes)
            for node_id, folder in inventory.items()
        ):
            excluded.add(listing_index)
        for index, (documents, nodes) in provenance.items():
            if not documents <= documents_now or not nodes <= nodes_now:
                excluded.add(index)
                continue
            if request.mentions:
                if selected is None:
                    try:
                        selected = usable(authorized(request.mentions, catalog.all_nodes).nodes)
                    except (SyncAccessDenied, ValueError):
                        return frozenset(set(provenance) | excluded), None
                inside = len(documents & selected[0]) + len(nodes & selected[1])
                if inside and not (documents <= selected[0] and nodes <= selected[1]):
                    excluded.add(index)
        return frozenset(excluded), nodes_now

    # Stage 1 -----------------------------------------------------------------

    def classify(
        self, request: AgentRequest, conversation: ConversationState, *, deadline: float,
    ) -> IntentDecision:
        """The configured classifier decides; if it fails, the provider's LLM classifier tries
        within the same deadline, and only then does the request fall back to a relevance search."""
        mentions = request.mentions
        adapters = [
            adapter for adapter in dict.fromkeys([self.intent_classifier, self.provider])
            if isinstance(adapter, IntentClassifierAdapter)
        ]
        context = {
            "mentioned_folders": sum(kind == "folder" for kind, _ in mentions),
            "mentioned_files": sum(kind == "file" for kind, _ in mentions),
            # Names only (the user already saw them); ids and URLs never reach the model.
            # Omitted with an excluded answer: its listing can name files that are no longer authorized.
            "previous_answer_listed_files": (
                [] if conversation.listing_excluded
                else [name for _id, _folder, name in conversation.listed_files]
            ),
            "previous_turn_had_files": bool(conversation.previous_turn_mentions),
            "has_previous_answer": conversation.previous_answer is not None,
        }
        intent_deadline = min(deadline, time.monotonic() + self.models.intent_timeout_seconds)
        for adapter in adapters:
            if time.monotonic() >= intent_deadline:
                break
            started_at = time.monotonic()
            try:
                with _observed_phase("intent_classifier", intent_deadline), _request_deadline(intent_deadline):
                    raw = adapter.classify_intent(
                        question=request.question, history=conversation.recent_messages, context=context,
                        model=self.models.planner_model,
                    )
                return parse_intent(raw, listed_files=len(conversation.listed_files), mentioned=len(mentions))
            except (AIProviderUnavailable, InvalidIntent, ValueError, TypeError, KeyError) as error:
                log_agent_phase(
                    logger, phase="intent_fallback", started_at=started_at, deadline=intent_deadline,
                    failure_kind=(
                        "provider_unavailable" if isinstance(error, AIProviderUnavailable) else "invalid_output"
                    ),
                )
        return fallback_intent(has_mentions=bool(mentions))

    # Stage 2 -----------------------------------------------------------------

    def execute(
        self, decision: IntentDecision, request: AgentRequest, conversation: ConversationState, *,
        deadline: float,
    ) -> AgentRun:
        """Run the tools of the decided intent; a plan the tools cannot serve falls back to relevance."""
        targets = self._resolve_targets(decision, request.mentions, conversation)
        intent = decision.intent
        if intent == "conversation" and targets:
            # Attached files mean the message is about them, whatever its wording.
            intent = "ask_content"
        if (
            intent == "restructure_previous" and conversation.previous_answer is None
            and not conversation.memory_excluded
        ):
            # An excluded answer is not "missing": the request is rebuilt from the current sources.
            intent = "summarize_files"
        _require_time(deadline)
        reachable = self._reauthorize_listed(request, targets, conversation)
        run = AgentRun(
            decision=decision, intent=intent, targets=reachable, conversation=conversation,
            unindexed_listed=len(targets) - len(reachable),
        )
        targets = reachable
        # A message that leans on the conversation has nothing left to lean on when its files are
        # unreadable, or when the answer it refers to was excluded: no widening to the whole library.
        refers_to_history = decision.target in {"previous_ordinals", "previous_answer_files"} or (
            conversation.memory_excluded and not request.mentions and (
                decision.target == "previous_turn_files" or decision.intent == "restructure_previous"
            )
        )
        if not targets and intent != "conversation" and refers_to_history:
            # Every file the message points at was listed without indexed content.
            run.answer = self._honest_insufficient(
                QuestionResult(None, "insufficient_evidence", [], RETRIEVAL_STATUS_NO_INDEXED_CONTENT), request, [],
            )
            return run
        started_at = time.monotonic()
        try:
            run.answer = self._handlers[intent](self, run, request, deadline)
        except PlanRejected:
            log_agent_phase(
                logger, phase="plan_fallback", started_at=started_at, deadline=deadline,
                failure_kind="plan_rejected",
            )
            run.fallback = "plan_rejected"
            run.answer = self._ask_content(run, request, deadline)
        return run

    def _resolve_targets(
        self, decision: IntentDecision, mentions: list[tuple[str, UUID]], conversation: ConversationState,
    ) -> list[tuple[str, UUID]]:
        """Turn the decided target into catalog node ids; the request's mentions stay authoritative."""
        if mentions:
            return mentions
        listed = conversation.listed_files
        if decision.target in {"previous_ordinals", "previous_answer_files"} and listed:
            chosen = [listed[index - 1] for index in decision.ordinals] if decision.ordinals else listed
            return [("file", node_id) for node_id, _folder, _name in chosen]
        if decision.target != "library":
            return conversation.previous_turn_mentions or [
                ("file", node_id) for node_id, _folder, _name in listed
            ]
        return []

    def _reauthorize_listed(
        self, request: AgentRequest, targets: list[tuple[str, UUID]], conversation: ConversationState,
    ) -> list[tuple[str, UUID]]:
        """Files reused from an earlier folder listing must still be inside that folder and authorized.

        Listed files without indexed content are dropped: there is nothing in them to read.
        """
        if request.mentions:
            return targets
        folders = {node_id: folder for node_id, folder, _name in conversation.listed_files if folder}
        reused = {node_id: folders[node_id] for kind, node_id in targets if kind == "file" and node_id in folders}
        if not reused:
            return targets
        snapshots = LibraryService(self.session).catalog_file_snapshots(
            scope=request.scope, user_id=request.user_id, providers=request.providers,
            node_ids=list(reused), inventory_folder_ids=reused,
        )
        unreadable = {snapshot.id for snapshot in snapshots if snapshot.document_id is None}
        return [(kind, node_id) for kind, node_id in targets if node_id not in unreadable]

    def _conversation(self, run: AgentRun, request: AgentRequest, deadline: float) -> QuestionResult:
        # No tool runs; the files the conversation is about stay the answer's sources (stage 4).
        run.conversation_citations = self._reauthorized_citations(request, run.conversation.files())
        text = (
            "Se quiser, posso detalhar, resumir ou reorganizar a resposta anterior com base nos mesmos "
            "documentos, listados nas fontes abaixo. Também posso listar arquivos de uma pasta ou responder "
            "a outras perguntas sobre o conteúdo deles."
            if run.conversation_citations
            else "Posso ajudar com os documentos autorizados: listar os arquivos de uma pasta, resumir um "
            "arquivo ou responder perguntas sobre o conteúdo deles, sempre com as fontes. Mencione arquivos "
            "ou pastas com @ para restringir a consulta."
        )
        return QuestionResult(answer=text, confidence="supported", citations=[], retrieval_status="conversation")

    def _list_files(self, run: AgentRun, request: AgentRequest, deadline: float) -> QuestionResult:
        with_summaries = run.intent == "list_files_with_summaries"
        folders, files = run.folders(), run.files()
        if len(folders) == 1 and not files:
            with _observed_phase("inventory", deadline):
                listing = self._complete_inventory(
                    request, mentions=run.targets, parent_id=folders[0], deadline=deadline,
                    include_excerpts=with_summaries,
                )
        elif files and not folders:
            listing = self._file_snapshots(request, files)
        elif run.decision.tool == "search_library" and run.decision.query:
            listing = self.tools.search_library(
                scope=request.scope, user_id=request.user_id, providers=request.providers,
                mentions=run.targets, query=run.decision.query,
            )
        else:
            raise PlanRejected("listing needs one folder, files, or a name search")
        if _json_size([{"name": listing.name, "result": listing.payload}]) > self.limits.max_result_bytes:
            raise AIProviderUnavailable("document agent result exceeds configured byte limit")
        run.add(listing)
        if not with_summaries:
            return _catalog_question_result(listing)
        return (
            self._synthesize(run, request, deadline=deadline)
            or self._catalog_answer(listing, question=request.question, deadline=deadline)
        )

    def _summarize_files(self, run: AgentRun, request: AgentRequest, deadline: float) -> QuestionResult:
        if not run.targets:
            raise PlanRejected("nothing selected to summarize")
        if len(run.files()) > 1 and not run.folders():
            with _observed_phase("tool_execution", deadline):
                listing = self._file_snapshots(request, run.files())
            run.add(listing)
            return self._catalog_answer(listing, question=request.question, deadline=deadline)
        return self._summary_or_honest(run, request, deadline)

    def _restructure_previous(self, run: AgentRun, request: AgentRequest, deadline: float) -> QuestionResult:
        if not run.targets:
            raise PlanRejected("restructure needs the files of the previous turn")
        with _observed_phase("tool_execution", deadline):
            run.add(self.tools.retrieve_evidence(
                scope=request.scope, user_id=request.user_id, question=request.question,
                providers=request.providers, mentions=run.targets, answer_mode="evidence",
            ))
        previous_answer = run.conversation.previous_answer or ""
        if run.conversation.memory_excluded and not previous_answer:
            # The earlier answer is out; what gets restructured is the current evidence itself.
            previous_answer = _evidence_draft(_synthesis_sources(run.results))
        synthesized = self._synthesize(run, request, deadline=deadline, previous_answer=previous_answer)
        if synthesized is not None:
            return synthesized
        # The model could not restructure verifiably: the evaluated per-file summary is the next best.
        return self._summary_or_honest(run, request, deadline)

    def _ask_content(self, run: AgentRun, request: AgentRequest, deadline: float) -> QuestionResult:
        # The classifier resolves conversational references; retrieval and the answer
        # model must see the same autonomous question, rather than the raw ellipsis.
        question = run.decision.standalone_query or request.question
        with _observed_phase("tool_execution", deadline):
            retrieved = self.tools.retrieve_evidence(
                scope=request.scope, user_id=request.user_id, question=question,
                providers=request.providers, mentions=run.targets, answer_mode="content",
                retrieval_question=run.decision.retrieval_query or None,
            )
        run.add(retrieved)
        assert retrieved.question_result is not None
        if retrieved.question_result.answer:
            return retrieved.question_result
        files = run.files()
        if files and retrieved.question_result.retrieval_status == RETRIEVAL_STATUS_BELOW_THRESHOLD:
            # A question about an attached file often names no topic the embedding can match;
            # the file's own indexed text is still evidence the answer can be checked against.
            run.add(self._file_snapshots(request, files))
            synthesized = self._synthesize(run, request, deadline=deadline)
            if synthesized is not None:
                return synthesized
        return self._honest_insufficient(retrieved.question_result, request, run.targets)

    # Intent -> stage-2 handler; each one is a node of a future graph (see docs/agent-flow.md).
    _handlers: ClassVar[dict[str, Callable[[AgentService, AgentRun, AgentRequest, float], QuestionResult]]] = {
        "conversation": _conversation,
        "list_files": _list_files,
        "list_files_with_summaries": _list_files,
        "summarize_files": _summarize_files,
        "restructure_previous": _restructure_previous,
        "ask_content": _ask_content,
    }

    def _summary_or_honest(self, run: AgentRun, request: AgentRequest, deadline: float) -> QuestionResult:
        with _observed_phase("tool_execution", deadline):
            summary = self.tools.summarize_documents(
                scope=request.scope, user_id=request.user_id, question=request.question,
                providers=request.providers, mentions=run.targets, answer_mode="summary",
            )
        run.add(summary)
        assert summary.question_result is not None
        if summary.question_result.answer:
            return summary.question_result
        return self._honest_insufficient(summary.question_result, request, run.targets)

    # Stage 3 -----------------------------------------------------------------

    def _synthesize(
        self, run: AgentRun, request: AgentRequest, *, deadline: float, previous_answer: str = "",
    ) -> QuestionResult | None:
        """One grounded synthesis call; None when it cannot be verified against the evidence."""
        adapter = self.provider
        if not isinstance(adapter, SynthesisAdapter):
            return None
        sources = _synthesis_sources(run.results)
        catalog = _synthesis_catalog(run.results)
        if not sources and not catalog:
            return None
        try:
            with _observed_phase("synthesis", deadline):
                generated = adapter.synthesize_answer(
                    question=request.question, intent=run.intent, sources=sources, catalog=catalog,
                    model=self.models.synthesis_model,
                    **({"previous_answer": previous_answer} if previous_answer else {}),
                )
        except AIProviderUnavailable:
            return None
        if not generated.text or generated.text.casefold().strip() == "insufficient evidence.":
            return None
        indexes = list(dict.fromkeys(generated.citation_indexes))
        cited = _validate_citations(indexes, sources) if indexes else []
        if (sources or previous_answer) and not cited:
            # Uncited or out-of-range markers cannot back the "Fontes" block.
            return None
        answer = _number_answer_sources(generated.text, indexes, sources, cited) if cited else generated.text
        only_catalog = all(result.question_result is None for result in run.results)
        return QuestionResult(
            answer=answer, confidence="supported", citations=cited,
            retrieval_status="catalog" if only_catalog else RETRIEVAL_STATUS_SUFFICIENT,
        )

    def _catalog_answer(self, result: ToolResult, *, question: str, deadline: float) -> QuestionResult:
        return _catalog_question_result(result, self._file_summaries(result, question=question, deadline=deadline))

    def _file_summaries(self, result: ToolResult, *, question: str, deadline: float) -> dict[str, str]:
        """Summary row text per file id whose content was asked for; none of it is invented."""
        items = result.payload.get("items", [])
        requested = [
            item for item in (items if isinstance(items, list) else [])
            if isinstance(item, dict) and "excerpt" in item and isinstance(item.get("id"), str)
            and isinstance(item.get("name"), str)
        ]
        if not requested:
            return {}
        chunks = dict(result.file_chunks)
        batch: list[tuple[str, str, list[str]]] = []
        for item in requested:
            texts = list(chunks.get(item["id"], ())) or (
                [item["excerpt"]] if isinstance(item.get("excerpt"), str) else []
            )
            texts = [text for text in texts if text.strip()]
            if texts:
                batch.append((item["id"], item["name"], texts))
        target = self.file_summaries.target_chars
        summaries = {item_id: _extractive_row(texts[0], target) for item_id, _name, texts in batch}
        adapter = self.provider
        if not batch or not isinstance(adapter, FileSummaryAdapter):
            return summaries
        call_deadline = min(deadline, time.monotonic() + self.file_summaries.timeout_seconds)
        try:
            with _observed_phase("file_summaries", call_deadline), _request_deadline(call_deadline):
                generated = adapter.summarize_file_briefs(
                    question=question,
                    files=[{"name": name, "chunks": texts} for _item_id, name, texts in batch],
                    target_chars=target, model=self.file_summaries.model,
                )
        except (AIProviderUnavailable, TypeError, ValueError, AttributeError):
            return summaries
        for index, (item_id, _name, _texts) in enumerate(batch, 1):
            text = generated.get(index) if isinstance(generated, dict) else None
            complete = _complete_summary(text, target) if isinstance(text, str) else ""
            if complete:
                summaries[item_id] = complete
        return summaries

    # Stage 4 -----------------------------------------------------------------

    def cite(self, run: AgentRun) -> QuestionResult:
        """Every answer that used documents carries them as citations, with their links.

        The answer's own verified citations win; when a step produced text without
        them (a catalog-only synthesis, a per-file listing), the documents the tools
        read become the Fontes, and a conversation reply keeps the conversation's.
        """
        assert run.answer is not None
        answer = _with_unindexed_notice(
            run.answer, run.unindexed_listed if run.intent != "conversation" else 0,
        )
        if answer.citations:
            return answer
        consulted = _document_citations([
            *(item for result in run.results for item in result.citations),
            *(
                item for result in run.results if result.question_result is not None
                for item in result.question_result.citations
            ),
            *run.conversation_citations,
        ])
        return replace(answer, citations=consulted) if consulted else answer

    # Tools shared by the stages ----------------------------------------------

    def _reauthorized_citations(self, request: AgentRequest, files: list[UUID]) -> list[Evidence]:
        """File-level citations for earlier turns' files, checked against the current catalog again."""
        if not files:
            return []
        try:
            return list(self._file_snapshots(request, files).citations)
        except SyncAccessDenied:
            return []

    def _file_snapshots(self, request: AgentRequest, files: list[UUID]) -> ToolResult:
        snapshots = LibraryService(self.session).catalog_file_snapshots(
            scope=request.scope, user_id=request.user_id, providers=request.providers, node_ids=files,
        )
        return ToolResult(
            "summarize_inventory",
            {
                "semantics": "persisted_inventory_references_with_extractive_content",
                "items": [
                    {
                        "id": str(snapshot.id), "kind": "file", "name": snapshot.name,
                        "index_status": snapshot.index_status, "excerpt": snapshot.excerpt,
                    }
                    for snapshot in snapshots
                ],
            },
            citations=_snapshot_citations(snapshots),
            file_chunks=tuple((str(snapshot.id), snapshot.chunks) for snapshot in snapshots),
        )

    def _honest_insufficient(
        self, result: QuestionResult | None, request: AgentRequest, targets: list[tuple[str, UUID]],
    ) -> QuestionResult:
        """Replace answer=None with an honest message that still carries the consulted files as Fontes."""
        status = result.retrieval_status if result is not None else RETRIEVAL_STATUS_BELOW_THRESHOLD
        citations = _document_citations([
            *(result.citations if result is not None else []),
            *self._reauthorized_citations(request, [node_id for kind, node_id in targets if kind == "file"]),
        ])
        if status == RETRIEVAL_STATUS_NO_INDEXED_CONTENT:
            text = (
                "Ainda não há conteúdo indexado consultável para esta pergunta. Aguarde a sincronização "
                "ou escolha outra pasta ou arquivo."
            )
        elif status == RETRIEVAL_STATUS_NO_COMPATIBLE_EMBEDDINGS:
            text = (
                "O conteúdo foi encontrado, mas a indexação de IA ainda não terminou. Tente novamente em "
                "alguns instantes."
            )
        else:
            text = (
                "Não encontrei, nos trechos indexados, evidência suficiente para responder a isso com "
                "segurança. Os documentos consultados não permitem confirmar esse detalhe. "
                "Você pode esclarecer a pessoa, empresa ou período a que se refere, ou selecionar "
                "uma fonte com @ para continuar a consulta."
            )
        if citations:
            text += "\n\nArquivos consultados:\n" + "\n".join(
                f"- {sanitize_label(item.document_name)} (fonte {index})" for index, item in enumerate(citations, 1)
            )
        return QuestionResult(
            answer=text,
            confidence="insufficient_evidence",
            citations=citations,
            retrieval_status=status,
            coverage=result.coverage if result is not None else None,
            resolved_context=result.resolved_context if result is not None else None,
        )

    def _complete_inventory(
        self, request: AgentRequest, *, mentions: list[tuple[str, UUID]], parent_id: UUID, deadline: float,
        include_excerpts: bool = False,
    ) -> ToolResult:
        items: list[dict[str, object]] = []
        citations: list[Evidence] = []
        file_chunks: list[tuple[str, tuple[str, ...]]] = []
        page = 1
        total = 0
        while len(items) < INVENTORY_MAX_ITEMS:
            _require_time(deadline)
            result = self.tools.list_library_children(
                scope=request.scope, user_id=request.user_id, providers=request.providers, mentions=mentions,
                parent_id=parent_id, page=page, page_size=INVENTORY_PAGE_SIZE,
                include_excerpts=include_excerpts,
            )
            page_items = result.payload["items"]
            assert isinstance(page_items, list)
            items.extend(page_items)
            citations.extend(result.citations)
            file_chunks.extend(result.file_chunks)
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
            file_chunks=tuple(file_chunks),
        )


@dataclass
class AgentRun:
    """State of one request through the stages, and how it becomes the agent's return value."""

    decision: IntentDecision
    intent: str
    targets: list[tuple[str, UUID]]
    conversation: ConversationState
    results: list[ToolResult] = field(default_factory=list)
    answer: QuestionResult | None = None
    conversation_citations: list[Evidence] = field(default_factory=list)
    fallback: str | None = None
    # Listed files still authorized but without indexed content, left out of this answer.
    unindexed_listed: int = 0

    def folders(self) -> list[UUID]:
        return [node_id for kind, node_id in self.targets if kind == "folder"]

    def files(self) -> list[UUID]:
        return [node_id for kind, node_id in self.targets if kind == "file"]

    def add(self, result: ToolResult) -> None:
        self.results.append(result)

    def finish(
        self, result: QuestionResult,
    ) -> tuple[QuestionResult, list[dict[str, object]], list[dict[str, str]]]:
        serialized = [{"name": item.name, "result": item.payload} for item in self.results]
        context = dict(result.resolved_context or {})
        context.update({
            "intent": self.intent, "decided_by": self.decision.decided_by,
            "target": self.decision.target, "tools": [item.name for item in self.results],
        })
        if self.decision.standalone_query:
            context["standalone_query"] = self.decision.standalone_query
        if self.fallback:
            context["fallback"] = self.fallback
        return replace(result, resolved_context=context), serialized, _catalog_references(serialized)


def _require_time(deadline: float) -> None:
    if time.monotonic() >= deadline:
        log_agent_phase(
            logger, phase="tool_execution", started_at=time.monotonic(), deadline=deadline,
            failure_kind="agent_deadline",
        )
        raise AIProviderUnavailable("document agent deadline exceeded")


def _with_unindexed_notice(result: QuestionResult, count: int) -> QuestionResult:
    """Say that listed files were left out for lack of indexed content; count only, no names."""
    if not count or not result.answer or result.retrieval_status == RETRIEVAL_STATUS_NO_INDEXED_CONTENT:
        return result
    notice = (
        f"Observação: {count} arquivo da lista anterior ficou sem conteúdo indexado e não foi "
        "considerado nesta resposta." if count == 1 else
        f"Observação: {count} arquivos da lista anterior ficaram sem conteúdo indexado e não foram "
        "considerados nesta resposta."
    )
    return replace(result, answer=f"{result.answer}\n\n{notice}")


def _document_citations(evidence: Iterable[Evidence]) -> list[Evidence]:
    """One citation per document, in first-use order, preferring an entry that has a link."""
    chosen: dict[UUID, Evidence] = {}
    for item in evidence:
        current = chosen.get(item.document_id)
        if current is None or (not current.source_url.strip() and item.source_url.strip()):
            chosen[item.document_id] = item
    return list(chosen.values())


def _answer_provenance(message: ConversationMessage) -> tuple[set[UUID], set[UUID]]:
    """Documents cited and file nodes listed by one stored answer."""
    documents: set[UUID] = set()
    nodes: set[UUID] = set()
    citations = (message.response or {}).get("citations")
    for item in citations if isinstance(citations, list) else []:
        try:
            documents.add(UUID(str(item.get("document_id"))))
        except (AttributeError, ValueError):
            continue
    references = (message.context or {}).get("references")
    for item in references if isinstance(references, list) else []:
        if isinstance(item, dict) and item.get("kind") == "file":
            try:
                nodes.add(UUID(str(item.get("id"))))
            except ValueError:
                continue
    return documents, nodes


def _previous_turn_mentions(history: list[ConversationMessage]) -> list[tuple[str, UUID]]:
    """Files and folders attached to the most recent earlier user message that had any."""
    for message in reversed(history):
        if message.role != "user":
            continue
        raw = (message.context or {}).get("mentions")
        if not isinstance(raw, list):
            continue
        resolved: list[tuple[str, UUID]] = []
        for item in raw:
            if not isinstance(item, dict) or item.get("kind") not in {"file", "folder"}:
                continue
            try:
                resolved.append((str(item["kind"]), UUID(str(item.get("node_id")))))
            except ValueError:
                continue
        if resolved:
            return resolved
    return []


def _latest_answer_index(history: list[ConversationMessage]) -> int | None:
    """Index of the latest assistant answer with content: the previous answer of the conversation."""
    return next(
        (index for index in range(len(history) - 1, -1, -1)
         if history[index].role == "assistant" and history[index].content.strip()),
        None,
    )


def _previous_listed_files(
    history: list[ConversationMessage],
) -> tuple[list[tuple[UUID, UUID | None, str]], int | None]:
    """Files of the latest answer that listed any, in the order the user saw them, and its index."""
    for position in range(len(history) - 1, -1, -1):
        message = history[position]
        references = (message.context or {}).get("references")
        if not isinstance(references, list):
            continue
        files: list[tuple[UUID, UUID | None, str]] = []
        for item in references:
            if not isinstance(item, dict) or item.get("kind") != "file" or not isinstance(item.get("id"), str):
                continue
            try:
                folder = item.get("folder_id")
                files.append((
                    UUID(item["id"]), UUID(folder) if isinstance(folder, str) else None, str(item.get("name", "")),
                ))
            except ValueError:
                continue
        if files:
            return files, position
    return [], None


def _previous_cited_files(
    session: Session, history: list[ConversationMessage], organization_id: UUID,
) -> list[tuple[UUID, UUID | None, str]]:
    """Recover catalog targets from the latest answer's cited documents.

    Search answers have citations but no inventory references. Match document
    provenance to the local catalog; access is checked again when tools run.
    """
    for message in reversed(history):
        if message.role != "assistant":
            continue
        citations = (message.response or {}).get("citations")
        if not isinstance(citations, list):
            return []
        ids: list[UUID] = []
        for item in citations:
            if not isinstance(item, dict):
                continue
            try:
                ids.append(UUID(str(item.get("document_id"))))
            except ValueError:
                continue
        if not ids:
            return []
        rows = session.execute(
            select(Document.id, LibraryNode.id, LibraryNode.name)
            .join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
            .join(
                LibraryNode,
                (LibraryNode.source_id == WorkspaceFolder.source_id)
                & (LibraryNode.external_id == Document.external_file_id),
            )
            .where(
                Document.id.in_(ids), Document.organization_id == organization_id,
                WorkspaceFolder.organization_id == organization_id,
                LibraryNode.organization_id == organization_id, LibraryNode.kind == "file",
            )
        )
        by_document = {document_id: (node_id, None, name) for document_id, node_id, name in rows}
        return list(dict.fromkeys(by_document[document_id] for document_id in ids if document_id in by_document))
    return []


def _evidence_payload(item: Evidence) -> dict[str, object]:
    return {
        "document_id": str(item.document_id), "document_name": item.document_name,
        "excerpt": item.excerpt, "page_number": item.page_number, "source_provider": item.source_provider,
    }


def _json_size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode())


def _planner_history(history: list[ConversationMessage]) -> list[dict[str, object]]:
    return [
        {"role": item.role, "content": item.content}
        for item in history[-MAX_PLANNER_HISTORY_MESSAGES:]
    ]


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


def _evidence_draft(sources: list[Evidence]) -> str:
    """Excerpts of the current sources with their [n] markers: a base that cites nothing else."""
    return "\n".join(f"{item.excerpt.strip()} [{index}]" for index, item in enumerate(sources, 1))


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


def _catalog_question_result(result: ToolResult, summaries: dict[str, str] | None = None) -> QuestionResult:
    items = result.payload.get("items", [])
    if not isinstance(items, list):
        items = []
    summaries = summaries or {}
    rows = [
        _catalog_item_row(item, summaries.get(str(item.get("id"))))
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


_SENTENCE_END = re.compile(r"[.!?…][\"')\]»”]*(?=\s|$)")


def _sentence_preview(text: str, target: int) -> str:
    """Leading indexed text ended at a sentence near the target; never cut inside a word."""
    flat = " ".join(text.split())
    if len(flat) <= target:
        return flat
    ends = [match.end() for match in _SENTENCE_END.finditer(flat)]
    within = [end for end in ends if end <= target]
    if within and within[-1] >= target // 3:
        return flat[:within[-1]]
    beyond = [end for end in ends if target < end <= target * 2]
    if beyond:
        return flat[:beyond[0]]
    if within:
        return flat[:within[-1]]
    return flat[:target].rsplit(" ", 1)[0].rstrip(" ,;:-|") + "…"


def _extractive_row(text: str, target: int) -> str:
    return f"Síntese extrativa do conteúdo indexado: {_sentence_preview(text, target)}"


def _complete_summary(text: str, target: int) -> str:
    """A model summary as one line ending in a full sentence; empty when it cannot be one."""
    flat = " ".join(text.split())
    if not flat:
        return ""
    ends = [match.end() for match in _SENTENCE_END.finditer(flat)]
    if not ends:
        return ""
    if ends[-1] != len(flat):
        flat = flat[:ends[-1]]
    # The target is an instruction; only a runaway answer is brought back to sentence bounds.
    return _sentence_preview(flat, target * 2) if len(flat) > target * 3 else flat


_NO_INDEXED_TEXT = "não há conteúdo indexado suficiente para resumir este arquivo."


def _catalog_item_row(item: dict[str, object], summary: str | None = None) -> str:
    name = item["name"]
    if summary:
        return f"- {name}: {summary}"
    if isinstance(item.get("excerpt"), str) and item["excerpt"].strip():
        return f"- {name}: {_extractive_row(item['excerpt'], FileSummaries().target_chars)}"
    if item.get("index_status") == "not_indexed":
        return f"- {name}: sem conteúdo indexado disponível."
    if "excerpt" in item:
        return f"- {name}: {_NO_INDEXED_TEXT}"
    return f"- {name} ({'Arquivo' if item.get('kind') == 'file' else 'Pasta'})"


def _request_deadline(deadline: float):
    from app.knowledge.questions import request_deadline

    return request_deadline(deadline)


def agent_service_from_settings(session: Session, provider: SemanticProvider, settings) -> AgentService:
    """Build the same bounded agent for browser and programmatic requests."""
    intent_classifier = None
    if settings.agent_intent_engine == "jev" and settings.typesafe_api_key:
        from app.knowledge.jev import JevIntentClassifier

        intent_classifier = JevIntentClassifier(
            settings.typesafe_api_key.get_secret_value(), model=settings.agent_jev_model,
        )
    elif settings.agent_intent_engine == "jev":
        logger.log(
            logging.ERROR if settings.environment == "production" else logging.WARNING,
            "AGENT_INTENT_ENGINE=jev without TYPESAFE_API_KEY; using the LLM intent classifier",
        )
    return AgentService(
        session=session, provider=provider,
        limits=AgentLimits(max_result_bytes=settings.agent_max_tool_result_bytes,
                           max_seconds=settings.agent_max_seconds),
        models=FlowModels(planner_model=settings.agent_planner_model,
                          synthesis_model=settings.agent_synthesis_model,
                          intent_timeout_seconds=settings.agent_intent_timeout_seconds),
        file_summaries=FileSummaries(target_chars=settings.agent_file_summary_chars,
                                    model=settings.agent_file_summary_model,
                                    timeout_seconds=settings.agent_file_summary_timeout_seconds),
        intent_classifier=intent_classifier,
    )
