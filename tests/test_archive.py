"""Briefing archive: auth gating, per-user isolation, day view, LIKE search
over the user's own archived items, empty state, votes on archived cards."""
import json

from app import db as appdb
from tests.conftest import login


def _onboarded(client, test_db, email, name="A"):
    login(client, email)
    user = appdb.get_user_by_email(test_db, email)
    test_db.execute("UPDATE users SET onboarded_at=?, name=? WHERE id=?",
                    (appdb.now(), name, user["id"]))
    test_db.commit()
    return appdb.get_user(test_db, user["id"])


def _other_user(test_db, email):
    """A second user created directly in the DB — no session switching (the
    dev-link login helper can collide on same-second token timestamps)."""
    test_db.execute("INSERT INTO users(email, name, onboarded_at, created_at) "
                    "VALUES(?,?,?,?)", (email, "B", appdb.now(), appdb.now()))
    test_db.commit()
    return appdb.get_user_by_email(test_db, email)


def _brief_paper(con, uid, date, rank, title, venue="Test Journal",
                 authors=("Ada Author",), abstract="An abstract.", fit=8.0):
    cur = con.execute(
        "INSERT INTO papers(key, title, venue, authors_json, abstract, "
        "first_seen) VALUES(?,?,?,?,?,?)",
        (f"{uid}-{date}-{rank}-{title[:20]}".lower(), title, venue,
         json.dumps(list(authors)), abstract, appdb.today()))
    pid = cur.lastrowid
    con.execute("INSERT INTO judgments(user_id, paper_id, profile_version, fit, "
                "flavors_json, why, judged_at) VALUES(?,?,?,?,?,?,?)",
                (uid, pid, "v1", fit, json.dumps(["a_flavor"]), "fits well",
                 appdb.now()))
    con.execute("INSERT INTO briefing_items(user_id, date, paper_id, rank, fit) "
                "VALUES(?,?,?,?,?)", (uid, date, pid, rank, fit))
    con.commit()
    return pid


def test_archive_requires_login_and_onboarding(client, test_db):
    r = client.get("/archive")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    login(client, "fresh@example.com")             # not onboarded yet
    r = client.get("/archive")
    assert r.status_code == 303 and r.headers["location"] == "/onboarding"


def test_archive_lists_days_and_day_view_shows_only_own_items(client, test_db):
    me = _onboarded(client, test_db, "mine@example.com")
    other = _other_user(test_db, "other@example.com")
    _brief_paper(test_db, other["id"], "2026-08-01", 1,
                 "Someone else's secret paper")
    _brief_paper(test_db, me["id"], "2026-08-01", 1, "Narrative persuasion online")
    _brief_paper(test_db, me["id"], "2026-08-01", 2, "Chatbots that change minds")
    _brief_paper(test_db, me["id"], "2026-07-15", 1, "Bridging divides paper")

    r = client.get("/archive")
    assert r.status_code == 200
    assert "August 2026" in r.text and "July 2026" in r.text
    assert "2026-08-01" in r.text and "2 papers" in r.text
    assert "Someone else" not in r.text

    r = client.get("/archive?date=2026-08-01")
    assert "Narrative persuasion online" in r.text
    assert "Chatbots that change minds" in r.text
    assert "Bridging divides paper" not in r.text          # other day
    assert "Someone else" not in r.text                    # other user
    # cards keep the vote buttons (votes on archived papers feed the judge)
    assert 'class="vote up' in r.text and 'class="vote down' in r.text
    # a foreign date is not selectable
    r = client.get("/archive?date=2099-01-01")
    assert "All briefing days" not in r.text


def test_archive_search_scoped_to_own_archive(client, test_db):
    me = _onboarded(client, test_db, "search@example.com")
    other = _other_user(test_db, "leak@example.com")
    _brief_paper(test_db, other["id"], "2026-08-01", 1,
                 "Narrative theory elsewhere")
    _brief_paper(test_db, me["id"], "2026-08-01", 1, "Narrative persuasion online",
                 venue="Journal of Communication", authors=("Grace Hopper",))
    _brief_paper(test_db, me["id"], "2026-08-02", 1, "Something unrelated",
                 abstract="A study of inoculation interventions.")

    r = client.get("/archive?q=narrative")
    assert "Narrative persuasion online" in r.text
    assert "Something unrelated" not in r.text
    assert "elsewhere" not in r.text                       # other user's item
    assert "in your briefing of 2026-08-01" in r.text      # briefed-date label
    # venue, author, and abstract all searchable
    assert "Narrative persuasion online" in client.get(
        "/archive?q=Journal of Communication").text
    assert "Narrative persuasion online" in client.get("/archive?q=Hopper").text
    assert "Something unrelated" in client.get("/archive?q=inoculation").text
    # no matches -> its own empty message
    r = client.get("/archive?q=zzzznothing")
    assert "No matches" in r.text


def test_archive_empty_state_and_nav_link(client, test_db):
    _onboarded(client, test_db, "empty@example.com")
    r = client.get("/archive")
    assert r.status_code == 200
    assert "No briefings archived yet" in r.text
    assert 'href="/archive"' in client.get("/dashboard").text   # nav link
