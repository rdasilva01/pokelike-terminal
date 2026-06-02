import sqlite3
import pathlib

DB_PATH = pathlib.Path(__file__).parent / "items.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS items (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT    NOT NULL UNIQUE,
        description TEXT    NOT NULL DEFAULT '',
        points      INTEGER NOT NULL DEFAULT 0
    )""")
    c.commit()
    return c


def upsert_items(choices: list[dict]) -> None:
    """Insert items not yet in the DB (by name). Ignores already-known items."""
    rows = [(ch["name"], ch.get("description", ""))
            for ch in choices if ch.get("name")]
    if not rows:
        return
    with _conn() as c:
        c.executemany(
            "INSERT OR IGNORE INTO items (name, description) VALUES (?, ?)",
            rows,
        )


def get_scores() -> dict[str, int]:
    """Return {item_name: points} for all items in the DB."""
    with _conn() as c:
        rows = c.execute("SELECT name, points FROM items").fetchall()
    return {name: pts for name, pts in rows}
