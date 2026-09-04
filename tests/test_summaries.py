"""Summaries stage + dashboard rendering: grounded vs abstract-only prompts,
idempotency, early-stop on provider failure, and the card showing the
generated summary above the abstract dropdown."""
from __future__ import annotations

import json

import pytest


def _brief(con, uid, date, key, title, abstract="An abstract about methods."):
    from app import db as appdb
    cur = con.execute(
        "INSERT INTO papers(key, title, abstract, first_seen) VALUES(?,?,?,?)",
        (key, title, abstract, appdb.now()))
    pid = cur.lastrowid
    con.execute("INSERT INTO briefing_items(user_id, date, paper_id, rank, fit) "
                "VALUES(?,?,?,1,8)", (uid, date, pid))
    con.commit()
    return pid


@pytest.fixture
def owner(test_db):
    from app import db as appdb
    test_db.execute(
        "INSERT INTO users(email, created_at, onboarded_at) VALUES(?,?,?)",
        ("o@x.com", appdb.now(), appdb.now()))
    test_db.commit()
    return appdb.get_user_by_email(test_db, "o@x.com")


def test_stage_writes_and_is_idempotent(test_db, owner, monkeypatch):
    from pipeline import providers, summaries
    calls = []

    def fake_chat(system, user, **kw):
        calls.append(system)
        return "A generated summary of the paper.", "stub"
    monkeypatch.setattr(providers, "chat", fake_chat)
    _brief(test_db, owner["id"], "2026-09-04", "s1", "Paper One")
    out = summaries.run(test_db, "2026-09-04")
    assert out["written"] == 1
    assert "ONLY the abstract" in calls[0]          # abstract-tier prompt
    row = test_db.execute("SELECT * FROM paper_summaries").fetchone()
    assert row["summary"].startswith("A generated") and row["grounded"] == 0
    out = summaries.run(test_db, "2026-09-04")      # second run: nothing to do
    assert out["written"] == 0 and len(calls) == 1


def test_grounded_prompt_when_fulltext_exists(test_db, owner, monkeypatch,
                                              tmp_path):
    from pipeline import providers, summaries
    from app.config import db_path
    calls = []
    monkeypatch.setattr(providers, "chat", lambda s, u, **kw:
                        (calls.append((s, u)) or ("Grounded summary.", "stub")))
    pid = _brief(test_db, owner["id"], "2026-09-04", "s2", "Paper Two")
    ft = db_path().parent / "fulltext" / "2026-09-04"
    ft.mkdir(parents=True, exist_ok=True)
    f = ft / "p2.html"
    f.write_bytes(b"<html><body><p>Methods body with n equals 400</p>"
                  + b"x" * 100 + b"</body></html>")
    test_db.execute(
        "INSERT INTO paper_fulltext(paper_id, status, path, route, kind, "
        "bytes, fetched_at) VALUES(?, 'ok', ?, 'oa_url', 'html', 100, '')",
        (pid, str(f.relative_to(db_path().parent))))
    test_db.commit()
    assert summaries.run(test_db, "2026-09-04")["written"] == 1
    system, user = calls[0]
    assert "full text" in system and "n equals 400" in user
    assert test_db.execute("SELECT grounded FROM paper_summaries "
                           "WHERE paper_id=?", (pid,)).fetchone()[0] == 1


def test_provider_outage_resumes_later(test_db, owner, monkeypatch):
    from pipeline import providers, summaries
    monkeypatch.setattr(providers, "chat", lambda *a, **k:
                        (_ for _ in ()).throw(
                            providers.ProvidersUnavailable("down")))
    _brief(test_db, owner["id"], "2026-09-04", "s3", "Paper Three")
    out = summaries.run(test_db, "2026-09-04")
    assert out["written"] == 0 and out["pending"] == 1


def test_dashboard_card_shows_summary(client, test_db, owner):
    from app import db as appdb
    from tests.conftest import login
    pid = _brief(test_db, owner["id"], "2026-09-04", "s4", "Paper Four")
    test_db.execute(
        "INSERT INTO paper_summaries(paper_id, summary, grounded, provider, "
        "created_at) VALUES(?, 'The full generated summary text.', 1, 'stub', ?)",
        (pid, appdb.now()))
    test_db.commit()
    login(client, "o@x.com")
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "The full generated summary text." in r.text
    assert "full-text summary" in r.text
    assert "<details><summary>Abstract</summary>" in r.text
