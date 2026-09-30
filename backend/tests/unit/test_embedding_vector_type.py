from sqlalchemy import Column, MetaData, Table, create_engine, select

from app.core.vector import EmbeddingVector


def test_sqlite_vector_round_trip():
    engine = create_engine('sqlite://')
    table = Table('vectors', MetaData(), Column('embedding', EmbeddingVector()))
    table.create(engine)
    with engine.begin() as connection:
        connection.execute(table.insert(), [{'embedding': [0.1, 0.2]}, {'embedding': None}])
        assert connection.scalars(select(table.c.embedding)).all() == [[0.1, 0.2], None]
