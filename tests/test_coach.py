"""AI profile coach: seed-based autofill (draft prefills, never auto-saves),
draft suggestions (JSON, nothing applied), vote-informed audit (gating,
history, previous-audit context), and the shared per-user daily rate limit.
All LLM calls stubbed at pipeline.providers.chat."""
import json

import pytest

from app import coach
from app import db as appdb
from tests.conftest import login

AUTOFILL_REPLY = json.dumps({
    "core_statement": "I study how conversational AI persuades people online.",
    "flavors": [{"name": "AI persuasion", "description": "LLMs shifting attitudes."},
                {"name": "narrative persuasion", "description": "Stories that persuade."},
                {"name": "bridging divides", "description": "Cross-partisan contact."}],
    "negatives": ["Chatbot UX without persuasion outcomes"],
})

SUGGEST_REPLY = json.dumps({
    "questions": ["Do you care about non-political persuasion?"],
    "suggestions": ["Name the Elaboration Likelihood Model — visible in your seeds."],
    "flags": ["'AI stuff' is too broad to steer a judge."],
})

AUDIT_REPLY = json.dumps({
    "proposals": [{
        "target": "flavor:ai_persuasion",
        "current": "LLMs shifting attitudes.",
        "suggested": "LLMs shifting attitudes, including disclosure-label effects.",
        "rationale": "Two upvoted disclosure papers were judged fit<=2.",
        "motivating_papers": ["Beyond the Assigned Label (up, fit 0)"],
    }],
    "summary": "Under-selection around AI-disclosure work.",
})


def _stub_chat(reply):
    def fake_chat(system, user_msg, temperature=0.0, **kw):
        return reply, "stub"
    return fake_chat


def _onboard_with_seeds(client, email, path="papers"):
    login(client, email)
    client.post("/onboarding/path", data={"path": path})
    client.post("/onboarding/about", data={"name": "Dr C", "frequency": "daily"})
    client.post("/onboarding/seeds",
                data={"papers": "10.1000/alpha\n10.1000/beta\n10.1000/gamma"})
    con = appdb.connect()
    user = appdb.get_user_by_email(con, email)
    con.close()
    return user


# --- parsers (offline) --------------------------------------------------------

def test_parse_autofill_contract():
    ok = coach.parse_autofill("noise " + AUTOFILL_REPLY + " noise")
    assert ok["core_statement"].startswith("I study")
    assert len(ok["flavors"]) == 3 and ok["flavors"][0]["name"] == "AI persuasion"
    assert coach.parse_autofill("not json") is None
    assert coach.parse_autofill('{"core_statement": "x", "flavors": []}') is None


def test_parse_suggestions_and_audit_contract():
    s = coach.parse_suggestions(SUGGEST_REPLY)
    assert s["questions"] and s["suggestions"] and s["flags"]
    assert coach.parse_suggestions('{"questions": []}') is None
    a = coach.parse_audit(AUDIT_REPLY)
    assert a["proposals"][0]["target"] == "flavor:ai_persuasion"
    assert coach.parse_audit('{"proposals": []}') is None


# --- a) autofill --------------------------------------------------------------

def test_autofill_prefills_editor_without_saving(client, test_db, monkeypatch):
    from pipeline import providers
    monkeypatch.setattr(providers, "chat", _stub_chat(AUTOFILL_REPLY))
    user = _onboard_with_seeds(client, "auto@example.com")

    # papers path: the draft offer is the seeds step's continue action (step 1)
    r = client.get("/onboarding?step=1")
    assert "Draft my criteria" in r.text

    r = client.post("/coach/autofill")
    # describe is step 2 on the papers path
    assert r.status_code == 303 and r.headers["location"] == "/onboarding?step=2"
    # draft stored, NOT saved onto the user or profile
    user = appdb.get_user_by_email(test_db, "auto@example.com")
    assert not user["interest_statement"]
    assert json.loads(user["interest_flavors_json"] or "[]") == []
    assert appdb.get_profile(test_db, user["id"]) is None
    # editor steps show the banner + prefilled draft
    r = client.get("/onboarding?step=2")
    assert "AI draft" in r.text and "ai-draft-banner" in r.text
    assert "conversational AI persuades" in r.text
    r = client.get("/onboarding?step=3")
    assert "AI persuasion" in r.text and "narrative persuasion" in r.text
    r = client.get("/onboarding?step=4")
    assert "Chatbot UX without persuasion outcomes" in r.text
    # submitting the steps is the user's confirmation — only then is it saved
    client.post("/onboarding/interests",
                data={"statement": "I study how conversational AI persuades "
                                   "people online (my edit)."})
    user = appdb.get_user_by_email(test_db, "auto@example.com")
    assert "(my edit)" in user["interest_statement"]


def test_autofill_requires_seeds(client, test_db, monkeypatch):
    from pipeline import providers
    monkeypatch.setattr(providers, "chat", _stub_chat(AUTOFILL_REPLY))
    login(client, "noseeds@example.com")
    r = client.post("/coach/autofill")
    assert r.status_code == 400 and "seed" in r.text.lower()


def test_papers_path_end_to_end(client, test_db, monkeypatch):
    """The full auto path: fork -> seeds -> autofill -> prefilled editors ->
    edited saves -> finish -> judge profile composed from the edited fields."""
    from pipeline import providers
    monkeypatch.setattr(providers, "chat", _stub_chat(AUTOFILL_REPLY))
    login(client, "e2e@example.com")
    client.post("/onboarding/path", data={"path": "papers"})

    # step 1: seeds first; the gate hint shows until 3 seeds exist
    r = client.get("/onboarding?step=1")
    assert "Add at least 3 seeds" in r.text
    client.post("/onboarding/seeds",
                data={"papers": "10.1000/alpha\n10.1000/beta\n10.1000/gamma"})
    r = client.get("/onboarding?step=1")
    assert "Draft my criteria" in r.text

    # draft, then walk the same editor steps with the prefills
    r = client.post("/coach/autofill")
    assert r.headers["location"] == "/onboarding?step=2"
    r = client.get("/onboarding?step=2")
    assert "ai-draft-banner" in r.text
    assert "conversational AI persuades" in r.text
    r = client.post("/onboarding/interests",
                    data={"statement": "I study how conversational AI persuades "
                                       "people online (edited)."})
    assert r.headers["location"] == "/onboarding?step=3"
    r = client.post("/onboarding/flavors",
                    data={"flavor_key": ["AI persuasion"],
                          "flavor_desc": ["LLMs shifting attitudes (edited)."],
                          "flavor_core": ["1"]})
    assert r.headers["location"] == "/onboarding?step=4"
    r = client.post("/onboarding/negatives",
                    data={"negative": ["Chatbot UX without persuasion outcomes"]})
    assert r.headers["location"] == "/onboarding?step=5"
    r = client.post("/onboarding/about", data={"name": "Dr E2E",
                                              "frequency": "daily"})
    assert r.headers["location"] == "/onboarding?step=6"
    r = client.post("/onboarding/finish")
    assert r.status_code == 303 and r.headers["location"] == "/dashboard"

    user = appdb.get_user_by_email(test_db, "e2e@example.com")
    prof = appdb.get_profile(test_db, user["id"])
    assert "(edited)" in prof["core_statement"]
    assert prof["flavors"] == [{"key": "ai_persuasion", "core": True,
                                "description": "LLMs shifting attitudes (edited)."}]
    assert prof["negatives"] == ["Chatbot UX without persuasion outcomes"]


def test_manual_path_can_still_draft_from_editor(client, test_db, monkeypatch):
    """Picking manual, then adding seeds, then returning to the describe step
    still offers 'draft from my papers' — and the draft lands back on the
    manual path's describe step (step 1)."""
    from pipeline import providers
    monkeypatch.setattr(providers, "chat", _stub_chat(AUTOFILL_REPLY))
    user = _onboard_with_seeds(client, "late@example.com", path="manual")
    r = client.get("/onboarding?step=1")            # manual: describe
    assert "Draft this from my seed papers" in r.text
    r = client.post("/coach/autofill")
    assert r.status_code == 303 and r.headers["location"] == "/onboarding?step=1"
    r = client.get("/onboarding?step=1")
    assert "ai-draft-banner" in r.text
    assert "conversational AI persuades" in r.text
    # draft prefills only; nothing saved onto the user
    user = appdb.get_user_by_email(test_db, "late@example.com")
    assert not user["interest_statement"]


def test_autofill_survives_provider_outage(client, monkeypatch):
    from pipeline import providers

    def down(*a, **k):
        raise providers.ProvidersUnavailable("no keys")
    monkeypatch.setattr(providers, "chat", down)
    _onboard_with_seeds(client, "down@example.com")
    r = client.post("/coach/autofill")
    assert r.status_code == 503 and "couldn" in r.text.lower()


# --- b) suggestions -----------------------------------------------------------

def test_suggest_returns_json_and_falls_back_to_saved_fields(client, test_db, monkeypatch):
    from pipeline import providers
    captured = {}

    def fake_chat(system, user_msg, temperature=0.0, **kw):
        captured["user"] = user_msg
        return SUGGEST_REPLY, "stub"
    monkeypatch.setattr(providers, "chat", fake_chat)
    user = _onboard_with_seeds(client, "sugg@example.com")
    con = appdb.connect()
    con.execute("UPDATE users SET interest_statement='I study persuasion at scale.' "
                "WHERE id=?", (user["id"],))
    con.commit(); con.close()

    r = client.post("/coach/suggest", data={"flavor_key": ["AI persuasion"],
                                            "flavor_desc": ["LLMs that persuade."]})
    assert r.status_code == 200
    out = r.json()
    assert out["questions"] and out["suggestions"] and out["flags"]
    # saved statement + posted flavors + seed titles all reached the prompt
    assert "persuasion at scale" in captured["user"]
    assert "AI persuasion" in captured["user"]
    assert "Narrative persuasion in online politics" in captured["user"]


def test_suggest_requires_login(client):
    r = client.post("/coach/suggest", data={"statement": "x"})
    assert r.status_code == 401


# --- c) vote-informed audit ---------------------------------------------------

def _mk_votes(con, uid, n_up_low=1, n_down_high=1, pad_to=20):
    """Judged+voted papers: a few boundary cases plus padding votes."""
    from tests.test_shortlist import _mk_paper
    total = 0

    def one(key, vote, fit, why, flavors):
        nonlocal total
        pid = _mk_paper(con, key)
        con.execute("INSERT INTO judgments(user_id, paper_id, profile_version, fit, "
                    "flavors_json, why, judged_at) VALUES(?,?,?,?,?,?,?)",
                    (uid, pid, "v1", fit, json.dumps(flavors), why, appdb.now()))
        con.execute("INSERT INTO feedback(user_id, paper_id, vote, title, ts) "
                    "VALUES(?,?,?,?,?)", (uid, pid, vote, f"Paper {key}", appdb.now()))
        total += 1
    for i in range(n_up_low):
        one(f"uplow{i}", "up", 2.0, "no persuasion angle", ["ai_persuasion"])
    for i in range(n_down_high):
        one(f"downhigh{i}", "down", 9.0, "central persuasion study", ["narrative"])
    while total < pad_to:
        one(f"pad{total}", "up" if total % 2 else "down", 7.0, "fine", ["narrative"])
    con.commit()


def test_audit_gated_until_enough_votes(client, test_db, monkeypatch):
    from pipeline import providers
    monkeypatch.setattr(providers, "chat", _stub_chat(AUDIT_REPLY))
    user = _onboard_with_seeds(client, "gate@example.com")
    appdb.save_profile(test_db, user["id"],
                       {"core_statement": "x", "flavors": [
                           {"key": "ai_persuasion", "description": "d"}]}, "v1")
    # settings shows the disabled explanation
    r = client.get("/settings")
    assert "Profile audit" in r.text and "unlocks" in r.text
    r = client.post("/coach/audit")
    assert r.status_code == 400 and "unlocks at 20" in r.text


def test_audit_runs_stores_history_and_feeds_previous(client, test_db, monkeypatch):
    from pipeline import providers
    captured = []

    def fake_chat(system, user_msg, temperature=0.0, **kw):
        captured.append(user_msg)
        return AUDIT_REPLY, "stub"
    monkeypatch.setattr(providers, "chat", fake_chat)
    user = _onboard_with_seeds(client, "audit@example.com")
    appdb.save_profile(test_db, user["id"],
                       {"core_statement": "I study persuasion.", "flavors": [
                           {"key": "ai_persuasion", "description": "LLMs shifting attitudes."}],
                        "negatives": []}, "v1")
    _mk_votes(test_db, user["id"])

    r = client.post("/coach/audit")
    assert r.status_code == 200 and "Audit complete" in r.text
    # evidence reached the prompt: the fit<=4 upvote with its why, flavor counts
    assert "no persuasion angle" in captured[0]
    assert "PER-FLAVOR VOTES" in captured[0]
    # stored + rendered
    rows = test_db.execute("SELECT * FROM profile_audits WHERE user_id=?",
                           (user["id"],)).fetchall()
    assert len(rows) == 1 and rows[0]["n_votes"] >= 20
    assert "disclosure-label effects" in r.text          # proposal shown
    assert "Selection Criteria editor" in r.text         # apply-manually link

    # second audit sees the previous one
    r = client.post("/coach/audit")
    assert r.status_code == 200
    assert "PREVIOUS AUDIT" in captured[1]
    assert test_db.execute("SELECT COUNT(*) c FROM profile_audits").fetchone()["c"] == 2


# --- shared rate limit --------------------------------------------------------

def test_coach_daily_limit_shared_across_modes(client, test_db, monkeypatch):
    from pipeline import providers
    monkeypatch.setenv("COACH_DAILY_LIMIT", "2")
    monkeypatch.setattr(providers, "chat", _stub_chat(SUGGEST_REPLY))
    _onboard_with_seeds(client, "limit@example.com")
    assert client.post("/coach/suggest", data={"statement": "x"}).status_code == 200
    assert client.post("/coach/suggest", data={"statement": "x"}).status_code == 200
    r = client.post("/coach/suggest", data={"statement": "x"})
    assert r.status_code == 429
    # the budget is shared: autofill is also refused now
    monkeypatch.setattr(providers, "chat", _stub_chat(AUTOFILL_REPLY))
    r = client.post("/coach/autofill")
    assert r.status_code == 429


def test_coach_calls_flow_through_provider_accounting(client, test_db, monkeypatch):
    """Coach traffic must land in the same provider_usage counters as judging
    — stub the transport, not the router."""
    from pipeline import providers
    monkeypatch.setenv("GROQ_API_KEY", "k")
    providers._CON = None
    monkeypatch.setattr(
        providers, "_post_json",
        lambda url, payload, key, timeout, provider=None: {
            "choices": [{"message": {"content": SUGGEST_REPLY}}]})
    _onboard_with_seeds(client, "acct@example.com")
    before = appdb.provider_calls_today(test_db, "groq")
    assert client.post("/coach/suggest", data={"statement": "x"}).status_code == 200
    assert appdb.provider_calls_today(test_db, "groq") == before + 1
