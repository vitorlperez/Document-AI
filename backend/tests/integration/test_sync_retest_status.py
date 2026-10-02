"""Run N-06 scope selection through PostgreSQL DISTINCT ON, as in production."""
import pytest
from sqlalchemy.orm import Session

from tests.integration.test_pgvector_search import engine  # noqa: F401
from tests.unit.test_sync_retest_status import CASES, assert_file_scope_status

pytestmark = pytest.mark.postgres


def test_n06_file_scopes_on_postgres(engine):  # noqa: F811
    for case in CASES:
        # Roll back each scenario so identities/idempotency keys can be reused.
        with Session(engine) as session:
            assert_file_scope_status(session, *case)
