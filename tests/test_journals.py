# SPDX-License-Identifier: AGPL-3.0-or-later
"""Priority journals: autocomplete + add/remove, gather of journal works and
source-country enrichment, the guaranteed-judge-slot rule (percentile floor +
cap), and the priority marking on dashboard and email."""
import json

import numpy as np

from app import db as appdb
from pipeline import briefings, gather
from pipeline.shortlist import shortlist_for_user
from tests.conftest import login
from tests.test_shortlist import _mk_paper, _mk_seed, _mk_user, _unit


def _add_pj(con, uid, source_id="S10", name="Journal of Communication", cc="US"):
    con.execute("INSERT OR IGNORE INTO priority_journals(user_id, source_id, "
                "display_name, country_code, added_at) VALUES(?,?,?,?,?)",
                (uid, source_id, name, cc, appdb.now()))
    con.commit()


# --- endpoints ----------------------------------------------------------------

def test_search_requires_login_and_returns_stub_sources(client):
    r = client.get("/journals/search?q=communication")
    assert r.status_code == 401
    login(client, "pj@example.com")
    r = client.get("/journals/search?q=communication")
    assert r.status_code == 200
    names = [s["display_name"] for s in r.json()["results"]]
    assert "Journal of Communication" in names
    assert "Asian Journal of Communication" in names
    # searched sources are remembered with their country (geo filter data)
    con = appdb.connect()
    row = con.execute("SELECT * FROM sources WHERE id='S10'").fetchone()
    assert row and row["country_code"] == "US"
    con.close()


def test_add_and_remove_priority_journal(client):
    login(client, "pj2@example.com")
    r = client.post("/journals/add",
                    data={"source_id": "S10", "display_name": "Journal of Communication",
                          "country_code": "US", "next": "/settings"})
    assert r.status_code == 303 and r.headers["location"] == "/settings"
    con = appdb.connect()
    user = appdb.get_user_by_email(con, "pj2@example.com")
    rows = con.execute("SELECT * FROM priority_journals WHERE user_id=?",
                       (user["id"],)).fetchall()
    assert [r_["source_id"] for r_ in rows] == ["S10"]
    con.close()
    # duplicate add is a no-op; bad id rejected
    client.post("/journals/add", data={"source_id": "S10"})
    r = client.post("/journals/add", data={"source_id": "W123"})
    assert r.status_code == 400
    r = client.post("/journals/remove", data={"source_id": "S10", "next": "/settings"})
    assert r.status_code == 303
    con = appdb.connect()
    assert con.execute("SELECT COUNT(*) c FROM priority_journals").fetchone()["c"] == 0
    con.close()


def test_journals_search_marks_selected(client):
    login(client, "pj3@example.com")
    client.post("/journals/add", data={"source_id": "S10",
                                       "display_name": "Journal of Communication"})
    r = client.get("/journals/search?q=communication")
    sel = {s["id"]: s["selected"] for s in r.json()["results"]}
    assert sel["S10"] is True and sel["S20"] is False


# --- gather -------------------------------------------------------------------

def test_gather_pulls_priority_journal_works_and_enriches_sources(client, test_db):
    login(client, "pjg@example.com")
    user = appdb.get_user_by_email(test_db, "pjg@example.com")
    _add_pj(test_db, user["id"], "S10")
    # a profile so union_concepts has something (stub returns WORKS for concepts)
    appdb.save_profile(test_db, user["id"],
                       {"core_statement": "x", "flavors": [],
                        "retrieval_concepts": ["https://openalex.org/C1"]}, "v1")
    summary = gather.run(test_db, since="2026-07-01")
    assert summary["new_priority_journal"] == 1        # the S10-only work (delta)
    row = test_db.execute("SELECT * FROM papers WHERE doi='10.1000/delta'").fetchone()
    assert row and row["source_id"] == "S10"
    # enrichment stored country codes for venue ids seen on papers
    assert summary["sources_enriched"] >= 1
    s = test_db.execute("SELECT * FROM sources WHERE id='S1'").fetchone()
    assert s and s["country_code"] == "US"
    # re-run: idempotent
    again = gather.run(test_db, since="2026-07-01")
    assert again["new_priority_journal"] == 0


# --- guaranteed judge slots ---------------------------------------------------

def _pool(con, uid):
    """size-2 shortlist scenario: seed at x-axis; two near papers fill the
    normal top-2; a priority-journal paper further out plus assorted filler
    define the pool percentiles; one priority paper is a clear stray."""
    _mk_seed(con, uid, _unit([1, 0, 0]).tolist())
    ids = {}
    ids["top1"] = _mk_paper(con, "top1", _unit([1, 0.02, 0]).tolist())
    ids["top2"] = _mk_paper(con, "top2", _unit([1, 0.05, 0]).tolist())
    ids["pj_ok"] = _mk_paper(con, "pj_ok", _unit([1, 0.35, 0]).tolist())
    ids["mid1"] = _mk_paper(con, "mid1", _unit([1, 0.8, 0]).tolist())
    ids["mid2"] = _mk_paper(con, "mid2", _unit([1, 1.2, 0]).tolist())
    ids["far1"] = _mk_paper(con, "far1", _unit([0.2, 1, 0.4]).tolist())
    ids["pj_stray"] = _mk_paper(con, "pj_stray", _unit([0, 0.3, 1]).tolist())
    con.execute("UPDATE papers SET source_id='S10' WHERE id IN (?,?)",
                (ids["pj_ok"], ids["pj_stray"]))
    con.commit()
    return ids


def test_priority_journal_guaranteed_slot_with_percentile_floor(test_db, monkeypatch):
    monkeypatch.setenv("JUDGE_SHORTLIST_PER_USER", "2")
    monkeypatch.setenv("PRIORITY_JOURNAL_MIN_REL_PCTL", "60")
    user = _mk_user(test_db, "slots@example.com")
    ids = _pool(test_db, user["id"])
    # without a priority journal: plain top-2
    got = [pid for pid, _ in shortlist_for_user(test_db, user)]
    assert got == [ids["top1"], ids["top2"]]
    # with it: pj_ok is appended as an ADDITIONAL slot; the stray (bottom of
    # the pool, far below the 60th percentile) is not
    _add_pj(test_db, user["id"], "S10")
    got = [pid for pid, _ in shortlist_for_user(test_db, user)]
    assert got[:2] == [ids["top1"], ids["top2"]]
    assert ids["pj_ok"] in got and ids["pj_stray"] not in got
    assert len(got) == 3


def test_priority_slots_respect_cap(test_db, monkeypatch):
    monkeypatch.setenv("JUDGE_SHORTLIST_PER_USER", "2")
    monkeypatch.setenv("PRIORITY_JOURNAL_MIN_REL_PCTL", "0")
    monkeypatch.setenv("PRIORITY_JOURNAL_MAX_PER_USER", "1")
    user = _mk_user(test_db, "cap@example.com")
    ids = _pool(test_db, user["id"])
    _add_pj(test_db, user["id"], "S10")
    got = [pid for pid, _ in shortlist_for_user(test_db, user)]
    # floor 0 admits both journal papers; the cap keeps only the closer one
    assert len(got) == 3 and ids["pj_ok"] in got and ids["pj_stray"] not in got


def test_percentile_floor_uses_user_pool(test_db, monkeypatch):
    """The floor is a percentile of the USER'S windowed pool relevance —
    verify against numpy on the same pool."""
    monkeypatch.setenv("JUDGE_SHORTLIST_PER_USER", "2")
    monkeypatch.setenv("PRIORITY_JOURNAL_MIN_REL_PCTL", "90")
    user = _mk_user(test_db, "pctl@example.com")
    ids = _pool(test_db, user["id"])
    _add_pj(test_db, user["id"], "S10")
    got = dict(shortlist_for_user(test_db, user))
    # at P90 of a 7-paper pool the floor sits above pj_ok's relevance
    rels = np.array(sorted(got.values()))
    assert ids["pj_ok"] not in got and ids["pj_stray"] not in got


# --- marking on dashboard + email --------------------------------------------

def test_priority_pick_marked_on_dashboard_and_email(client, test_db):
    login(client, "mark@example.com")
    user = appdb.get_user_by_email(test_db, "mark@example.com")
    test_db.execute("UPDATE users SET onboarded_at=?, name='M' WHERE id=?",
                    (appdb.now(), user["id"]))
    appdb.save_profile(test_db, user["id"], {"core_statement": "x", "flavors": []}, "v1")
    _add_pj(test_db, user["id"], "S10", "Journal of Communication")
    pid = _mk_paper(test_db, "pjmark")
    test_db.execute("UPDATE papers SET source_id='S10', title='Priority pick', "
                    "abstract='One sentence.' WHERE id=?", (pid,))
    other = _mk_paper(test_db, "plain")
    for p, fit in ((pid, 9.0), (other, 8.0)):
        test_db.execute(
            "INSERT INTO judgments(user_id, paper_id, profile_version, fit, judged_at) "
            "VALUES(?,?,?,?,?)", (user["id"], p, "v1", fit, appdb.now()))
    test_db.commit()
    user = appdb.get_user(test_db, user["id"])

    rows = briefings.select_items(test_db, user)
    assert [r["id"] for r in rows] == [pid, other]
    assert rows[0]["pj_name"] == "Journal of Communication" and rows[1]["pj_name"] == ""
    html_out = briefings.render_email(user, rows, appdb.today())
    assert "your priority list" in html_out
    assert html_out.count("your priority list") == 1

    briefings.build_briefing(test_db, user, appdb.today())
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "your priority list" in r.text
    assert r.text.count("your priority list") == 1     # only the S10 card
