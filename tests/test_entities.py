"""HTML-entity hygiene (owner bug report: email showed "&amp;amp;" in a
title). Entities are decoded at INGEST so the DB holds plain text, legacy
rows are scrubbed by a one-shot tracked data migration, and templates/email
escape exactly once at render."""
import json

from app import db as appdb
from app.openalex import clean_text, parse_work
from tests.conftest import login, make_work


def test_clean_text_decodes_entities():
    assert clean_text("Search &amp; Rescue") == "Search & Rescue"
    assert clean_text("Search &amp;amp; Rescue") == "Search & Rescue"   # double-encoded
    assert clean_text("&lt;i&gt;Nudge&lt;/i&gt;") == "<i>Nudge</i>"
    assert clean_text("Don&#8217;t Panic") == "Don’t Panic"
    assert clean_text("AT&T stays plain & intact") == "AT&T stays plain & intact"
    assert clean_text("") == ""


def test_parse_work_stores_clean_text():
    w = make_work("10.2000/ents", "AI Overviews &amp;amp; Engagement",
                  "Effects of &lt;b&gt;labels&lt;/b&gt; on trust",
                  venue="New Media &amp; Society")
    w["authorships"][0]["author"]["display_name"] = "M. O&#8217;Brien"
    rec = parse_work(w)
    assert rec["title"] == "AI Overviews & Engagement"
    assert rec["venue"] == "New Media & Society"
    assert rec["abstract"] == "Effects of <b>labels</b> on trust"
    assert rec["authors"] == ["M. O’Brien"]
    assert rec["source_id"] == "S1"           # venue source id now captured


def _dirty_paper(con, title="AI Overviews Reduce Engagement &amp;amp; May Influence",
                 venue="Nature &amp; AI", abstract="We test &lt;br&gt; effects &#8212; twice"):
    cur = con.execute(
        "INSERT INTO papers(key, doi, title, venue, abstract, authors_json, "
        "pub_date, first_seen) VALUES(?,?,?,?,?,?,?,?)",
        (title.lower()[:40], "10.3000/dirty", title, venue, abstract,
         json.dumps(["A. O&#8217;Brien"]), "2026-08-01", appdb.today()))
    con.commit()
    return cur.lastrowid


def test_data_migration_scrubs_legacy_rows(test_db):
    user = appdb.ensure_user(test_db, "legacy@example.com")
    pid = _dirty_paper(test_db)
    test_db.execute("INSERT INTO seeds(user_id, title, abstract, added_at) "
                    "VALUES(?, 'Bots &amp; Belief', 'a &amp;amp; b', ?)",
                    (user["id"], appdb.now()))
    # simulate a DB written BEFORE the fix: drop the applied-marker, reconnect
    test_db.execute("DELETE FROM data_migrations WHERE name LIKE 'scrub_html%'")
    test_db.commit()
    con = appdb.connect()
    p = con.execute("SELECT * FROM papers WHERE id=?", (pid,)).fetchone()
    assert p["title"] == "AI Overviews Reduce Engagement & May Influence"
    assert p["venue"] == "Nature & AI"
    assert p["abstract"] == "We test <br> effects — twice"
    assert json.loads(p["authors_json"]) == ["A. O’Brien"]
    s = con.execute("SELECT * FROM seeds").fetchone()
    assert s["title"] == "Bots & Belief" and s["abstract"] == "a & b"
    # marker recorded -> connect again is a no-op (idempotent)
    assert con.execute("SELECT COUNT(*) c FROM data_migrations "
                       "WHERE name LIKE 'scrub_html%'").fetchone()["c"] == 1
    con.close()


def _briefed_user(con, client, title):
    login(client, "ents@example.com")
    user = appdb.get_user_by_email(con, "ents@example.com")
    con.execute("UPDATE users SET onboarded_at=?, name='Dr E' WHERE id=?",
                (appdb.now(), user["id"]))
    appdb.save_profile(con, user["id"], {"core_statement": "x", "flavors": []}, "v1")
    cur = con.execute(
        "INSERT INTO papers(key, doi, title, venue, abstract, authors_json, "
        "pub_date, first_seen) VALUES(?,?,?,?,?,?,?,?)",
        ("k-render", "10.4000/render", title, "Journal of Tests & Trials",
         "Ampersands & angle brackets <matter>.", json.dumps(["Ada A."]),
         "2026-08-01", appdb.today()))
    pid = cur.lastrowid
    con.execute("INSERT INTO judgments(user_id, paper_id, profile_version, fit, "
                "flavors_json, why, judged_at) VALUES(?,?,?,?,?,?,?)",
                (user["id"], pid, "v1", 9.0, "[]", "why & wherefore", appdb.now()))
    con.execute("INSERT INTO briefing_items(user_id, date, paper_id, rank, fit) "
                "VALUES(?,?,?,1,9.0)", (user["id"], appdb.today(), pid))
    con.commit()
    return appdb.get_user(con, user["id"]), pid


def test_dashboard_escapes_clean_title_exactly_once(client, test_db):
    # DB holds CLEAN text (post-fix); the page must show it escaped once
    title = "AI Overviews Reduce Search Result Engagement & May Influence <Users>"
    _briefed_user(test_db, client, title)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "Engagement &amp; May Influence &lt;Users&gt;" in r.text
    assert "&amp;amp;" not in r.text                      # never double-escaped
    assert "Tests &amp; Trials" in r.text


def test_email_escapes_clean_title_exactly_once(client, test_db):
    from pipeline import briefings
    title = "Search Result Engagement & <Influence>"
    user, pid = _briefed_user(test_db, client, title)
    # render straight from the briefing selection query (fresh join, new date)
    test_db.execute("DELETE FROM briefing_items")
    test_db.commit()
    rows = briefings.select_items(test_db, user)
    assert [r["id"] for r in rows] == [pid]
    html_out = briefings.render_email(user, rows, appdb.today())
    assert "Engagement &amp; &lt;Influence&gt;" in html_out
    assert "&amp;amp;" not in html_out and "&amp;lt;" not in html_out
