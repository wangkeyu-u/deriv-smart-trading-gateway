from contextlib import contextmanager
from pathlib import Path
import sqlite3

from persistence.migrations import migrate

DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / 'local_data' / 'gateway.sqlite3'


def resolve_database_path(path):
    value=Path(path).expanduser()
    return (value if value.is_absolute() else DEFAULT_DB_PATH.parent.parent/value).resolve()


class Database:
    def __init__(self, path=DEFAULT_DB_PATH):
        self.path = resolve_database_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as conn:
            migrate(conn)

    @contextmanager
    def transaction(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
