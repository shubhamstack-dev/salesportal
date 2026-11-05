"""An existing database from an older version gets the new columns added without losing data."""
import importlib
import os
import sqlite3
import sys
import tempfile


def test_old_materials_table_gets_new_columns(monkeypatch):
    path = f"{tempfile.mkdtemp()}/old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE materials (id INTEGER PRIMARY KEY, code VARCHAR(40) UNIQUE, name VARCHAR(200), uom VARCHAR(10), "
                "hsn VARCHAR(8), blocked BOOLEAN, synced_at DATETIME)")
    con.execute("INSERT INTO materials (code, name, uom, hsn, blocked) VALUES ('SF-001-1000', 'Seekh Kebab', 'KG', '1602', 0)")
    con.commit(); con.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    saved = {k: sys.modules.pop(k) for k in list(sys.modules) if k == "app" or k.startswith("app.")}
    try:
        db = importlib.import_module("app.db")
        importlib.import_module("app.models")
        db.Base.metadata.create_all(db.engine)
        added = db.add_missing_columns()
        assert "materials.mrp" in added and "materials.pack_qty" in added
        assert db.add_missing_columns() == []                       # second start: nothing to do
        con = sqlite3.connect(path)
        assert con.execute("SELECT code, name, mrp FROM materials").fetchall() == [("SF-001-1000", "Seekh Kebab", None)]
    finally:
        for k in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
            sys.modules.pop(k)
        sys.modules.update(saved)
