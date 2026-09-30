import dataclasses
import inspect

from app.knowledge.agent import AgentRequest, LibraryToolExecutor
from app.knowledge.intent import INTENT_SCHEMA

FORBIDDEN = {"organization_id", "org_id", "tenant_id", "user_id", "scope", "providers", "workspace_folder_id"}


def assert_no_scope_parameters(function) -> None:
    names = set(inspect.signature(function).parameters) - {"self"}
    assert not (names & FORBIDDEN), f"{function.__qualname__} exposes {names & FORBIDDEN}"


def test_classifier_schema_cannot_carry_scope():
    assert set(INTENT_SCHEMA["properties"]) == {
        "intent", "target", "ordinals", "tool", "query", "standalone_query",
    }
    assert INTENT_SCHEMA["additionalProperties"] is False


def test_agent_request_is_immutable_and_owns_the_scope():
    assert dataclasses.is_dataclass(AgentRequest) and AgentRequest.__dataclass_params__.frozen
    assert {"scope", "user_id", "providers", "mentions"} <= {f.name for f in dataclasses.fields(AgentRequest)}


def test_tool_executor_scope_arguments_are_keyword_only_and_server_supplied():
    for name in ("list_library_children", "search_library", "retrieve_evidence", "summarize_documents"):
        parameters = inspect.signature(getattr(LibraryToolExecutor, name)).parameters
        for required in ("scope", "user_id"):
            assert parameters[required].kind is inspect.Parameter.KEYWORD_ONLY
