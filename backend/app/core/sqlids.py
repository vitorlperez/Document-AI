"""``column = ANY(:ids)`` on PostgreSQL instead of ``IN (…thousands of binds…)`` (spike M3).

PostgreSQL's wire protocol caps a statement at 65,535 bind parameters; an array parameter is one bind
whatever its length. SQLite (unit tests) keeps the portable ``IN``.
"""

from collections.abc import Collection
from typing import Any

from sqlalchemy import ColumnElement, any_, literal
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session


def ids_clause(session: Session, column: Any, ids: Collection[Any]) -> ColumnElement[bool]:
    values = list(ids)
    if session.get_bind().dialect.name == "postgresql":
        return column == any_(literal(values, ARRAY(column.type)))
    return column.in_(values)
