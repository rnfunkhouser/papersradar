"""Onboarding: entry fork (papers-first vs write-it-myself), step ordering,
OpenAlex lookup-and-confirm, validation gates, finish flow — via HTTP against
the stubbed OpenAlex."""
from app import db as appdb
from tests.conftest import login


def test_fork_screen_comes_first(client):
    """A fresh user sees the entry fork before any interest fields, with both
    choices and the edit-to-sharpen note; numbered steps are gated on it."""
    login(client, "fork@example.com")
    r = client.get("/onboarding")
    assert r.status_code == 200
    assert "Choose your starting point" in r.text
    assert "Start from my papers" in r.text and "recommended" in r.text
    assert "Write it myself" in r.text
    assert "only as sharp as these descriptions" in r.text
    # asking for a numbered step without a chosen path lands on the fork
    r = client.get("/onboarding?step=3")
    assert "Choose your starting point" in r.text


def test_fork_choice_persists_and_is_changeable(client, test_db):
    login(client, "fork2@example.com")
    r = client.post("/onboarding/path", data={"path": "papers"})
    assert r.status_code == 303 and r.headers["location"] == "/onboarding?step=1"
    user = appdb.get_user_by_email(test_db, "fork2@example.com")
    assert user["onboarding_path"] == "papers"
    # step 1 on the papers path is the seeds step; Back returns to the fork
    r = client.get("/onboarding?step=1")
    assert "Step 1 of 7" in r.text and "Seed papers" in r.text
    assert 'href="/onboarding?step=0"' in r.text
    r = client.get("/onboarding?step=0")
    assert "Choose your starting point" in r.text
    # switching to manual re-orders the remaining steps
    client.post("/onboarding/path", data={"path": "manual"})
    user = appdb.get_user_by_email(test_db, "fork2@example.com")
    assert user["onboarding_path"] == "manual"
    r = client.get("/onboarding?step=1")
    assert "Describe your research" in r.text


def test_step_order_and_progress_by_path(client):
    """Both paths are the same 7 steps; only the seeds position differs, and
    the tail (About you -> Priority journals -> Review) is shared."""
    login(client, "order@example.com")
    client.post("/onboarding/path", data={"path": "papers"})
    papers_labels = ["Seed papers", "Describe your research",
                     "Topics &amp; intersections", "Not interested", "About you",
                     "Priority journals", "Review &amp; launch"]
    for i, label in enumerate(papers_labels, 1):
        page = client.get(f"/onboarding?step={i}").text
        assert f"Step {i} of 7" in page and label in page, (i, label)
        # progress dots: exactly i filled
        assert page.count('<span class="done"></span>') == i
    client.post("/onboarding/path", data={"path": "manual"})
    manual_labels = ["Describe your research", "Topics &amp; intersections",
                     "Not interested", "Seed papers", "About you",
                     "Priority journals", "Review &amp; launch"]
    for i, label in enumerate(manual_labels, 1):
        page = client.get(f"/onboarding?step={i}").text
        assert f"Step {i} of 7" in page and label in page, (i, label)
    # the fork screen fills no progress dots
    page = client.get("/onboarding?step=0").text
    assert page.count('<span class="done"></span>') == 0


def test_onboarding_never_mentions_the_audit(client):
    """The vote-informed profile audit is a settings-only feature — no
    onboarding surface may mention or link it."""
    login(client, "noaudit@example.com")
    for path in ("papers", "manual"):
        client.post("/onboarding/path", data={"path": path})
        for step in range(0, 8):
            page = client.get(f"/onboarding?step={step}").text.lower()
            assert "audit" not in page, (path, step)


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
    assert r.status_code == 400                    # no topics, no seeds yet
    r = client.post("/onboarding/flavors",
                    data={"flavor_key": ["AI persuasion"],
                          "flavor_desc": ["Conversational AI that shifts attitudes."],
                          "flavor_core": ["1"]})
    assert r.status_code == 303
    r = client.post("/onboarding/negatives",
                    data={"negative": ["Chatbot UX with no persuasion outcome"]})
    assert r.status_code == 303
    r = client.post("/onboarding/finish")
    assert r.status_code == 400                    # still not enough seeds
    client.post("/onboarding/seeds",
                data={"papers": "10.1000/alpha\n10.1000/beta\n10.1000/gamma"})
    r = client.post("/onboarding/finish")
    assert r.status_code == 303 and r.headers["location"] == "/dashboard"
    con = appdb.connect()
    user = appdb.get_user_by_email(con, "finish@example.com")
    assert user["onboarded_at"]
    prof = appdb.get_profile(con, user["id"])
    assert prof["core_statement"].startswith("I study how conversational AI")
    assert prof["flavors"] == [{"key": "ai_persuasion", "core": True,
                                "description": "Conversational AI that shifts "
                                               "attitudes."}]
    assert prof["negatives"] == ["Chatbot UX with no persuasion outcome"]
    assert "bullseye" in prof["fit_rule"] and "CORE" in prof["fit_rule"]
    con.close()
    # dashboard renders the warming-up state
    r = client.get("/dashboard")
    assert r.status_code == 200 and "warming up" in r.text


def test_flavors_step_requires_complete_entry(client):
    login(client, "flav@example.com")
    client.post("/onboarding/about", data={"name": "Dr G", "frequency": "daily"})
    r = client.post("/onboarding/flavors",
                    data={"flavor_key": ["name only"], "flavor_desc": [""],
                          "flavor_core": ["0"]})
    assert r.status_code == 400
    # negatives may be skipped entirely (empty list is fine)
    r = client.post("/onboarding/negatives", data={})
    assert r.status_code == 303


def test_onboarding_shows_founder_example(client):
    login(client, "ex@example.com")
    client.post("/onboarding/path", data={"path": "manual"})
    client.post("/onboarding/about", data={"name": "Dr E", "frequency": "daily"})
    client.post("/onboarding/interests",
                data={"statement": "I study collective attention and online "
                                   "discourse dynamics at scale."})
    # manual path: describe=1, topics=2, negatives=3
    r = client.get("/onboarding?step=1")
    assert "Want to see a full example?" in r.text
    assert "political-communication researcher" in r.text
    r = client.get("/onboarding?step=2")
    assert "Want to see a full example?" in r.text
    assert "bridging divides" in r.text          # founder flavor key, prettified
    r = client.get("/onboarding?step=3")
    assert "Want to see a full example?" in r.text
    assert "Public attitudes TOWARD AI" in r.text
