"""Short-lived connections with one-time schema setup and concurrent readers."""
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

_schema_lock = threading.Lock()
_ready = set()


@contextmanager
def database(path, initialize, schema):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=20)
    db.row_factory = sqlite3.Row
    try:
        stat = path.stat()
        key = (str(path), stat.st_dev, stat.st_ino, schema)
        if key not in _ready:
            with _schema_lock:
                if key not in _ready:
                    db.execute('PRAGMA journal_mode=WAL')
                    with db:
                        initialize(db)
                    _ready.add(key)
        with db:
            yield db
    finally:
        db.close()
