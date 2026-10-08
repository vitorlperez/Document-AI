"""Regression: a listed file moved out of its listed folder must not leak its name to the AI.

Same harness as test_agent_revocation_review. The file stays in the same source, so the catalog
still admits it; the inventory reference is denied later as a whole (existing fail-closed), but
before that the classifier must not receive the name from the listing answer or its references.
"""

# Pytest intentionally injects the imported fixture under the same parameter name.
# ruff: noqa: F811

import json

import pytest

from app.library.service import SyncAccessDenied
from tests.unit.test_agent_revocation_review import (
    RecordingAI,
    follow,
    make_case,
    no_external_ai,  # noqa: F401
    semantic_session,  # noqa: F401
)

MOVED = "beta-denied-review.pdf"


def test_moved_listed_file_name_never_reaches_the_classifier(semantic_session):
    case = make_case(semantic_session, listing=True)
    case.nodes[1].parent_id = None  # moved out of the listed folder, same source
    semantic_session.commit()
    provider = RecordingAI()
    with pytest.raises(SyncAccessDenied, match="outside the authorized selection") as error:
        follow(case, provider)
    assert MOVED not in str(error.value)
    assert MOVED not in json.dumps(provider.classifier_inputs, ensure_ascii=False, default=str), (
        "moved listed file: its name reached the classifier"
    )


def test_unmoved_listing_still_hands_names_to_the_classifier(semantic_session):
    case = make_case(semantic_session, listing=True)
    provider = RecordingAI()
    follow(case, provider)
    assert MOVED in json.dumps(provider.classifier_inputs, ensure_ascii=False, default=str)
