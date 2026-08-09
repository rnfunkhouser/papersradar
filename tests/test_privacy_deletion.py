"""Privacy surface, self-serve account deletion (cascade), and the signed
no-login unsubscribe endpoint + briefing-email footer."""
import json

from app import auth, db as appdb
from tests.conftest import login


def test_privacy_page_renders_with_key_claims(client):
    r = client.get("/privacy")
    assert r.status_code == 200
    for claim in ("hashed", "90", "encrypted at rest", "Groq", "Gemini",
                  "never sell", "Delete", "unsubscribe"):
        assert claim in r.text, claim


def test_login_page_carries_privacy_and_session_notes(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert "signed in on this device for 90 days" in r.text
    assert "/privacy" in r.text


def _populate_full_account(client, email):
    """A user with rows in every per-user table."""
    login(client, email)
    client.post("/onboarding/about", data={"name": "Dr D", "frequency": "daily"})
    client.post("/onboarding/interests",
                data={"statement": "I study persuasion dynamics in online "
                                   "political communication and AI dialogue."})
    client.post("/onboarding/flavors",
                data={"flavor_key": ["ai persuasion"],
                      "flavor_desc": ["Conversational AI shifting attitudes."],
                      "flavor_core": ["1"]})
    client.post("/onboarding/negatives", data={"negative": ["Chatbot UX only"]})
    client.post("/onboarding/seeds",
                data={"papers": "10.1000/alpha\n10.1000/beta\n10.1000/gamma"})
    client.post("/onboarding/finish")
    client.post("/zotero/connect",
                data={"library_type": "group", "library_id": "999",
                      "api_key": "grouply", "next": "/settings"})
    con = appdb.connect()
    user = appdb.get_user_by_email(con, email)
    uid = user["id"]
    pid = con.execute(
        "INSERT INTO papers(key, title, first_seen) VALUES('k-del', 'P', ?)",
        (appdb.now(),)).lastrowid
    con.execute("INSERT INTO judgments(user_id, paper_id, profile_version, fit, "
                "judged_at) VALUES(?,?,?,?,?)", (uid, pid, "v", 8.0, appdb.now()))
    con.execute("INSERT INTO briefing_items(user_id, date, paper_id, rank, fit) "
                "VALUES(?,?,?,?,?)", (uid, appdb.today(), pid, 1, 8.0))
    con.execute("INSERT INTO feedback(user_id, paper_id, vote, title, ts) "
                "VALUES(?,?,?,?,?)", (uid, pid, "up", "P", appdb.now()))
    con.execute("INSERT INTO clicks(user_id, paper_id, ts) VALUES(?,?,?)",
                (uid, pid, appdb.now()))
    con.commit()
    con.close()
    return uid, pid


PER_USER_TABLES = ("seeds", "seed_embeddings", "profiles", "judgments",
                   "briefing_items", "feedback", "clicks", "zotero_links")


def test_delete_account_requires_confirmation(client):
    uid, _ = _populate_full_account(client, "keep@example.com")
    r = client.post("/settings/delete-account", data={"confirm": "nope"})
    assert r.status_code == 400
    con = appdb.connect()
    assert appdb.get_user(con, uid) is not None
    con.close()


def test_delete_account_cascades_everything(client):
    uid, pid = _populate_full_account(client, "gone@example.com")
    r = client.post("/settings/delete-account", data={"confirm": "delete"})
    assert r.status_code == 200 and "deleted" in r.text.lower()
    con = appdb.connect()
    assert appdb.get_user(con, uid) is None
    for table in ("seeds", "profiles", "judgments", "briefing_items",
                  "feedback", "clicks", "zotero_links"):
        n = con.execute(f"SELECT COUNT(*) c FROM {table} WHERE user_id=?",
                        (uid,)).fetchone()["c"]
        assert n == 0, table
    n = con.execute("SELECT COUNT(*) c FROM seed_embeddings WHERE seed_id IN "
                    "(SELECT id FROM seeds WHERE user_id=?)", (uid,)).fetchone()["c"]
    assert n == 0
    n = con.execute("SELECT COUNT(*) c FROM auth_tokens WHERE email=?",
                    ("gone@example.com",)).fetchone()["c"]
    assert n == 0
    # the shared corpus paper survives — it is not personal data
    assert con.execute("SELECT COUNT(*) c FROM papers WHERE id=?",
                       (pid,)).fetchone()["c"] == 1
    con.close()
    # the session cookie was cleared: settings now bounces to login
    r = client.get("/settings")
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_unsubscribe_token_roundtrip():
    tok = auth.make_unsubscribe_token(42)
    assert auth.read_unsubscribe_token(tok) == 42
    uid, sig = tok.split(".")
    assert auth.read_unsubscribe_token(f"43.{sig}") is None      # tampered uid
    assert auth.read_unsubscribe_token("junk") is None
    assert auth.read_unsubscribe_token("") is None


def test_unsubscribe_endpoint_no_login(client, test_db):
    user = appdb.ensure_user(test_db, "sub@example.com")
    test_db.execute("UPDATE users SET frequency='daily' WHERE id=?", (user["id"],))
    test_db.commit()
    tok = auth.make_unsubscribe_token(user["id"])
    # no session cookie involved — fresh client state is fine
    r = client.get(f"/unsubscribe/{tok}")
    assert r.status_code == 200 and "unsubscribed" in r.text.lower()
    row = appdb.get_user(test_db, user["id"])
    assert row["frequency"] == "none"
    # idempotent; bad tokens rejected
    assert client.get(f"/unsubscribe/{tok}").status_code == 200
    assert client.get("/unsubscribe/9999.badsig").status_code == 400


def test_briefing_email_footer_has_unsubscribe_and_manage(test_db):
    from pipeline.briefings import render_email
    user = appdb.ensure_user(test_db, "mail@example.com")
    test_db.execute("UPDATE users SET name='M', frequency='weekly' WHERE id=?",
                    (user["id"],))
    test_db.commit()
    user = appdb.get_user(test_db, user["id"])
    pid = test_db.execute(
        "INSERT INTO papers(key, title, first_seen, abstract) "
        "VALUES('k-mail', 'A Paper', ?, 'An abstract.')", (appdb.now(),)).lastrowid
    test_db.commit()
    rows = test_db.execute(
        "SELECT p.*, 8.0 AS fit, '[]' AS flavors_json, 'why' AS why "
        "FROM papers p WHERE p.id=?", (pid,)).fetchall()
    html = render_email(user, rows, appdb.today())
    assert "Research Radar" in html and "Papers Radar" not in html
    tok = auth.make_unsubscribe_token(user["id"])
    assert f"/unsubscribe/{tok}" in html
    assert "/settings" in html
    assert "1-per-week" in html                      # frequency phrasing
    assert "You're receiving this because you chose" in html
