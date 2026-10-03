import inspect
import re

from app.knowledge.agent import AgentService, LibraryToolExecutor
from app.knowledge.intent import ALLOWED_TOOLS, INTENT_TOOLS


def test_tools_are_read_only():
    allowed = {
        "list_folder_inventory",
        "summarize_documents",
        "retrieve_evidence",
        "search_library",
        "previous_answer",
        "none",
        "catalog_inventory",
        "analyze_file_topics",
    }
    assert set(INTENT_TOOLS) <= allowed
    assert {tool for tools in ALLOWED_TOOLS.values() for tool in tools} <= allowed
    assert not any(
        re.search(r"write|send|delete|create|update|post|email", name) for name in INTENT_TOOLS
    )
    for handler in AgentService._handlers.values():
        code = inspect.getsource(handler)
        for method in re.findall(r"self\.tools\.(\w+)\(", code):
            source = inspect.getsource(getattr(LibraryToolExecutor, method))
            assert not re.search(
                r"session\.(add|delete)\s*\(|session\.execute\s*\(\s*(update|delete|insert)\s*\(",
                source,
            )

    assert not re.search(
        r"session\.(add|delete)\s*\(|session\.execute\s*\(\s*(update|delete|insert)\s*\(",
        inspect.getsource(LibraryToolExecutor),
    )
    # Catalog handlers read through the domain service rather than the semantic executor.
    from app.library.service import LibraryService

    assert not re.search(
        r"session\.(add|delete)\s*\(|session\.execute\s*\(\s*(update|delete|insert)\s*\(",
        inspect.getsource(LibraryService.catalog_inventory),
    )
