"""Settings parity: every decision collected during onboarding must be
modifiable later from the settings surface, with equivalent behavior
(interest edits and the geo toggle re-queue judging identically from both).
Also covers the per-user briefing-size override end to end."""
import json

from app import db as appdb
from pipeline import briefings
from tests.conftest import login
from tests.test_shortlist import _mk_paper

# Every field the onboarding wizard collects, and the settings-page form
# fields/endpoints that edit it later. Guards against a new onboarding input
# quietly shipping without a settings equivalent.
ONBOARDING_FIELDS_TO_SETTINGS = {
    # the "About you" step (shared tail of both onboarding paths)
    "name":            ("/settings/account", 'name="name"'),
    "frequency":       ("/settings/account", 'name="frequency"'),
    "briefing_size":   ("/settings/account", 'name="briefing_size"'),
    "western_context": ("/settings/scope", 'name="western_context"'),
    # structured interest editor steps (describe / topics / negatives)
    "statement":       ("/settings/criteria", 'name="core_statement"'),
    "flavor_key":      ("/settings/criteria", 'name="flavor_key"'),
    "flavor_desc":     ("/settings/criteria", 'name="flavor_desc"'),
    "flavor_core":     ("/settings/criteria", 'name="flavor_core"'),
    "negative":        ("/settings/criteria", 'name="negative"'),
    # priority-journals step — same endpoints from both surfaces
    "priority_journal": ("/journals/add", "journal-q"),
    # seeds step (paste + Zotero; position depends on the chosen path)
    "seeds":           ("/settings/seeds/add", 'name="papers"'),
    "zotero":          ("/zotero/connect", "zotero"),
}


def _onboarded(client, test_db, email):
    login(client, email)
    user = appdb.get_user_by_email(test_db, email)
    test_db.execute("UPDATE users SET onboarded_at=?, name='P' WHERE id=?",
                    (appdb.now(), user["id"]))
    test_db.commit()
    appdb.save_profile(test_db, user["id"], {"core_statement": "x" * 60,
                                             "flavors": []}, "v1")
    return appdb.get_user(test_db, user["id"])


def test_every_onboarding_field_is_editable_in_settings(client, test_db):
    from app.main import app
    _onboarded(client, test_db, "parity@example.com")
    routes = {r.path for r in app.routes}
    page = client.get("/settings").text
    for field, (endpoint, marker) in ONBOARDING_FIELDS_TO_SETTINGS.items():
        assert endpoint in routes, f"{field}: no settings endpoint {endpoint}"
        assert marker in page, f"{field}: no {marker} control on the settings page"


def test_onboarding_page_collects_exactly_those_fields(client, test_db):
    """The inverse guard: onboarding's form fields are all in the parity map,
    so adding a new wizard input forces a settings equivalent (or a conscious
    edit of this test). The entry fork's `path` field is a one-time flow
    choice (which order the same steps run in), not a persistent preference —
    it deliberately has no settings equivalent."""
    import re

    def fields_on(step):
        page = client.get(f"/onboarding?step={step}").text
        got = set(re.findall(r'<(?:input|select|textarea)[^>]*?name="([a-z_]+)"',
                             page))
        # aux/back-forms + the Zotero widget's own fields (covered by the
        # "zotero" parity-map entry; the widget is shared with settings)
        return got - {"seed_id", "next", "papers", "zotero_url", "zotero_key",
                      "collection_key", "library_type", "library_id", "api_key"}

    login(client, "parity2@example.com")
    # the entry fork collects only the path choice
    assert fields_on(0) == {"path"}
    known = set(ONBOARDING_FIELDS_TO_SETTINGS)
    # manual path: describe, topics, negatives, seeds, about, journals, review
    client.post("/onboarding/path", data={"path": "manual"})
    step_fields = {
        1: {"statement"},
        2: {"flavor_key", "flavor_desc", "flavor_core"},
        3: {"negative"},
        4: set(),                                       # seeds: aux forms only
        5: {"name", "frequency", "briefing_size", "western_context"},
    }
    for step, expected in step_fields.items():
        got = fields_on(step)
        assert got == expected, f"manual step {step}: {got} != {expected}"
        assert expected <= known
    # papers path: the same steps, seeds first
    client.post("/onboarding/path", data={"path": "papers"})
    assert fields_on(1) == set()                        # seeds step
    assert fields_on(2) == {"statement"}
    assert fields_on(5) == {"name", "frequency", "briefing_size",
                            "western_context"}


def test_settings_account_saves_briefing_size(client, test_db):
    user = _onboarded(client, test_db, "size@example.com")
    r = client.post("/settings/account",
                    data={"name": "P", "frequency": "daily", "briefing_size": "5"})
    assert r.status_code == 200 and "up to 5" in r.text
    assert appdb.get_user(test_db, user["id"])["briefing_size"] == 5
    # out-of-range values are clamped into 5-10; blank restores the default
    client.post("/settings/account",
                data={"name": "P", "frequency": "daily", "briefing_size": "50"})
    assert appdb.get_user(test_db, user["id"])["briefing_size"] == 10
    client.post("/settings/account", data={"name": "P", "frequency": "daily"})
    assert appdb.get_user(test_db, user["id"])["briefing_size"] is None


def test_briefing_size_overrides_email_and_dashboard_selection(client, test_db,
                                                               monkeypatch):
    monkeypatch.setenv("BRIEFING_MAX_ITEMS", "8")
    user = _onboarded(client, test_db, "sized@example.com")
    for i in range(9):
        pid = _mk_paper(test_db, f"sz{i}")
        test_db.execute("INSERT INTO judgments(user_id, paper_id, profile_version, "
                        "fit, judged_at) VALUES(?,?,?,8.0,?)",
                        (user["id"], pid, "v1", appdb.now()))
    test_db.commit()
    # global default first
    assert len(briefings.select_items(test_db, user)) == 8
    # per-user override applies to selection (briefing_items feed BOTH the
    # dashboard view and the email digest)
    test_db.execute("UPDATE users SET briefing_size=5 WHERE id=?", (user["id"],))
    test_db.commit()
    user = appdb.get_user(test_db, user["id"])
    rows = briefings.select_items(test_db, user)
    assert len(rows) == 5
    briefings.build_briefing(test_db, user, appdb.today())
    r = client.get("/dashboard")
    assert r.text.count('class="card"') == 5


def test_settings_criteria_requeues_judging_like_onboarding(client, test_db):
    """Editing interest fields from settings bumps the profile version (the
    same cache-discard behavior onboarding edits have)."""
    user = _onboarded(client, test_db, "requeue@example.com")
    v0 = appdb.get_profile(test_db, user["id"])["version"]
    r = client.post("/settings/criteria", data={
        "core_statement": "I study narrative persuasion in political talk online.",
        "flavor_key": ["narrative persuasion"],
        "flavor_desc": ["Stories that shift attitudes."],
        "flavor_core": ["1"], "negative": ["chatbot UX"]})
    assert r.status_code == 200
    assert appdb.get_profile(test_db, user["id"])["version"] != v0
