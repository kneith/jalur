"""Small synchronous PostgreSQL connection boundary."""
from contextlib import contextmanager
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from .config import settings

_pool = None
if settings.database_url:
    _pool = ConnectionPool(settings.database_url, min_size=1, max_size=10,
                           kwargs={"row_factory": dict_row}, open=True)

@contextmanager
def connection():
    if _pool is None:
        raise RuntimeError("DATABASE_URL belum dikonfigurasi.")
    with _pool.connection() as conn:
        yield conn

def close_pool():
    if _pool is not None:
        _pool.close()
