"""Les migrations s'installent sur une base neuve, et jamais sur la base de l'ancienne version."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

DOSSIER = Path(__file__).resolve().parents[1]


def _alembic(base: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{base}", "SECRET_KEY": "secret-de-test-" + "x" * 40}
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=DOSSIER, env=env,
                          capture_output=True, text=True)


def _tables(base: Path) -> set[str]:
    return {r[0] for r in sqlite3.connect(base).execute("select name from sqlite_master where type='table'")}


def test_base_neuve_installee(tmp_path):
    base = tmp_path / "neuve.db"
    assert _alembic(base, "upgrade", "head").returncode == 0
    # Les migrations doivent être réellement enregistrées (une transaction englobante les annulait).
    assert {"fiche", "client", "alembic_version"} <= _tables(base)
    assert sqlite3.connect(base).execute("select version_num from alembic_version").fetchall()
    assert _alembic(base, "check").returncode == 0


def test_base_de_l_ancienne_version_refusee(tmp_path):
    base = tmp_path / "ancienne.db"
    with sqlite3.connect(base) as c:
        c.execute("create table reservation (id integer)")
    r = _alembic(base, "upgrade", "head")
    assert r.returncode != 0 and "ancienne version" in (r.stdout + r.stderr)
    assert _tables(base) == {"reservation"}
