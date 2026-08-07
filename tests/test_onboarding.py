"""Onboarding: OpenAlex lookup-and-confirm, validation gates, finish flow —
via HTTP against the stubbed OpenAlex."""
from app import db as appdb
from tests.conftest import login


def test_lookup_by_doi_and_title(client):
    from app import openalex
    rec = openalex.lookup("https://doi.org/10.1000/alpha")
    assert rec["title"] == "Narrative persuasion in online politics"
    assert rec["doi"] == "10.1000/alpha"
    assert "stories persuade" in rec["abstract"]
    rec = openalex.lookup("Chatbots that change minds")
    assert rec["doi"] == "10.1000/beta"
    assert openalex.lookup("") is None
    assert openalex.lookup("10.9999/does-not-exist") is None


def test_onboarding_requires_login(client):
    r = client.get("/onboarding")
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_step1_requires_name(client):
    login(client, "new@example.com")
    r = client.post("/onboarding/about", data={"name": "  ", "frequency": "daily"})
    assert r.status_code == 400


def test_step2_requires_substantive_statement(client):
    login(client, "new2@example.com")
    client.post("/onboarding/about", data={"name": "Dr X", "frequency": "weekly"})
    r = client.post("/onboarding/interests", data={"statement": "AI stuff"})
    assert r.status_code == 400
    r = client.post("/onboarding/interests",
                    data={"statement": "I study narrative persuasion in online "
                                       "political communication, with a focus on AI."})
    assert r.status_code == 303


def test_seed_paste_lookup_confirm_remove(client):
    login(client, "seeds@example.com")
    r = client.post("/onboarding/seeds",
                    data={"papers": "10.1000/alpha\nChatbots that change minds\n"
                                    "utter nonsense zzzz qqqq"})
    assert r.status_code == 200
    assert "Added 2 papers" in r.text
    assert "Couldn&#39;t find" in r.text or "Couldn't find" in r.text
    con = appdb.connect()
    user = appdb.get_user_by_email(con, "seeds@example.com")
    seeds = con.execute("SELECT * FROM seeds WHERE user_id=?",
                        (user["id"],)).fetchall()
    assert {s["doi"] for s in seeds} == {"10.1000/alpha", "10.1000/beta"}
    # duplicate paste is a no-op
    client.post("/onboarding/seeds", data={"papers": "10.1000/alpha"})
    n = con.execute("SELECT COUNT(*) c FROM seeds WHERE user_id=?",
                    (user["id"],)).fetchone()["c"]
    assert n == 2
    # remove
    client.post("/onboarding/seeds/remove", data={"seed_id": seeds[0]["id"]})
    n = con.execute("SELECT COUNT(*) c FROM seeds WHERE user_id=?",
                    (user["id"],)).fetchone()["c"]
    assert n == 1
    con.close()


def test_finish_gate_and_profile_creation(client):
    login(client, "finish@example.com")
    client.post("/onboarding/about", data={"name": "Dr F", "frequency": "daily"})
    client.post("/onboarding/interests",
                data={"statement": "I study how conversational AI persuades people "
                                   "and bridges ideological divides online."})
    r = client.post("/onboarding/finish")
    assert r.status_code == 400                    # not enough seeds yet
    client.post("/onboarding/seeds",
                data={"papers": "10.1000/alpha\n10.1000/beta\n10.1000/gamma"})
    r = client.post("/onboarding/finish")
    assert r.status_code == 303 and r.headers["location"] == "/dashboard"
    con = appdb.connect()
    user = appdb.get_user_by_email(con, "finish@example.com")
    assert user["onboarded_at"]
    prof = appdb.get_profile(con, user["id"])
    assert prof["core_statement"].startswith("I study how conversational AI")
    assert prof["flavors"], "fallback flavor must exist without any API"
    con.close()
    # dashboard renders the warming-up state
    r = client.get("/dashboard")
    assert r.status_code == 200 and "warming up" in r.text
