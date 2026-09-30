"""Resumable, API-free conversion of legacy JSON embeddings."""
import argparse
import time

from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import build_engine


def backfill(engine, *, batch=1000, sleep_seconds=0.2, max_batches=None):
    if batch <= 0 or sleep_seconds < 0 or (max_batches is not None and max_batches < 0):
        raise ValueError('batch must be positive; sleep and max_batches must be nonnegative')
    total = batches = 0
    while max_batches is None or batches < max_batches:
        with engine.begin() as connection:
            result = connection.execute(text('''
                UPDATE document_chunks SET embedding_vec = (embedding::text)::vector
                WHERE id IN (
                    SELECT id FROM document_chunks
                    WHERE embedding_vec IS NULL AND embedding IS NOT NULL
                      AND json_typeof(embedding) = 'array'
                    ORDER BY id LIMIT :batch FOR UPDATE SKIP LOCKED)
            '''), {'batch': batch})
            count = result.rowcount
        if count == 0:
            break
        total += count
        batches += 1
        time.sleep(sleep_seconds)
    return total


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=int, default=1000)
    args = parser.parse_args()
    print(backfill(build_engine(get_settings()), batch=args.batch))
