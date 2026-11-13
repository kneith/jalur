"""Small synchronous PostgreSQL connection boundary for serverless instances."""
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings

# Each warm Vercel instance owns its own pool. Keep it small so concurrent
# instances do not multiply idle PostgreSQL connections unnecessarily.
_pool = None
if settings.database_url:
    _pool = ConnectionPool(
        settings.database_url,
        min_size=1,
        max_size=4,
        timeout=8,
        max_idle=30,
        kwargs={"row_factory": dict_row},
        open=True,
    )


@contextmanager
def connection():
    if _pool is None:
        raise RuntimeError("DATABASE_URL belum dikonfigurasi.")
    with _pool.connection() as conn:
        yield conn


def close_pool():
    if _pool is not None:
        _pool.close()
