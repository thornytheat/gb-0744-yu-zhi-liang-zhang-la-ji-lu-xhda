import json
import sqlite3
from contextlib import closing
from pathlib import Path


class Stale(Exception):
    """重算失败：旧版处置单必须原样保留。"""


class History:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS calculations (code TEXT PRIMARY KEY, result TEXT NOT NULL)"
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(calculations)")}
            if "source" not in columns:
                db.execute("ALTER TABLE calculations ADD COLUMN source BLOB")

    def connect(self):
        return sqlite3.connect(self.path, timeout=8)

    def find(self, code):
        with closing(self.connect()) as db:
            row = db.execute("SELECT result FROM calculations WHERE code=?", (code,)).fetchone()
            return json.loads(row[0]) if row else None

    def source_of(self, code):
        with closing(self.connect()) as db:
            row = db.execute("SELECT source FROM calculations WHERE code=?", (code,)).fetchone()
        return None if row is None or row[0] is None else bytes(row[0])

    def publish(self, code, factory, source=None):
        """同一批只开一张处置单；已有结果直接复用，不重算也不覆盖。

        factory 在事务外执行。计算抛错时不会写入任何半批结果，
        也不会影响同一内容已有的处置单。
        """
        with closing(self.connect()) as db:
            existing = db.execute("SELECT result FROM calculations WHERE code=?", (code,)).fetchone()
            if existing is not None:
                return json.loads(existing[0]), True
        value = factory()
        payload = json.dumps(value, ensure_ascii=False)
        with closing(self.connect()) as db, db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO calculations (code, result, source) VALUES (?,?,?)",
                (code, payload, None if source is None else sqlite3.Binary(source)),
            )
            stored = db.execute("SELECT result FROM calculations WHERE code=?", (code,)).fetchone()[0]
            return json.loads(stored), not cursor.rowcount

    def recompute(self, code, factory):
        """只有重算成功才替换处置单；失败抛出 Stale，旧版保持可查。"""
        if self.find(code) is None:
            return None
        try:
            value = factory()
        except Exception as exc:  # 失败不能留下半批结果，也不能弄丢旧版
            raise Stale(str(exc)) from exc
        payload = json.dumps(value, ensure_ascii=False)
        with closing(self.connect()) as db, db:
            db.execute("UPDATE calculations SET result=? WHERE code=?", (payload, code))
            stored = db.execute("SELECT result FROM calculations WHERE code=?", (code,)).fetchone()[0]
            return json.loads(stored)

    def recent(self):
        with closing(self.connect()) as db:
            return [
                json.loads(row[0])["清单"]
                for row in db.execute("SELECT result FROM calculations ORDER BY rowid DESC LIMIT 50")
            ]
