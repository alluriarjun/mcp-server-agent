from contextlib import contextmanager

import psycopg2
import psycopg2.extras

from shared.config import settings


@contextmanager
def get_connection():
    conn = psycopg2.connect(settings.db_dsn)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_cursor():
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
            conn.commit()
