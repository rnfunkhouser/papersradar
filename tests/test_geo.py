"""Western-context scope option: the Broad-West constant, the hard venue
filter in the per-user queue, the soft judge-prompt instruction, and the
profile-version bump on toggle (verdict caches must never mix prompts)."""
from app import db as appdb
from app.geo import BROAD_WEST_COUNTRIES, WESTERN_SOFT_PROMPT, is_broad_west
from pipeline.judging import build_prompt
from pipeline.shortlist import shortlist_for_user
from tests.conftest import login
from tests.test_shortlist import _mk_paper, _mk_seed, _mk_user, _unit

PROFILE = {"core_statement": "I study persuasion.",
           "flavors": [{"key": "ai_persuasion", "description": "AI that persuades."}],
           "fit_rule": "rule", "negatives": ["chatbot UX"],
           "positive_exemplar_titles": [], "negative_exemplar_titles": []}


def test_broad_west_definition():
    for cc in ("US", "CA", "GB", "IE", "DE", "FR", "IT", "ES", "SE", "NO",
               "AU", "NZ", "PT", "GR", "DK", "FI", "NL", "AT", "CH", "BE"):
        assert cc in BROAD_WEST_COUNTRIES, cc
    for cc in ("CN", "IN", "BR", "NG", "RU", "JP", "KR", "TR", "IR", "SG",
               "PL", "CZ", "HU", "UA"):                # incl. Eastern Europe
        assert cc not in BROAD_WEST_COUNTRIES, cc
    assert is_broad_west("us") and is_broad_west("") and is_broad_west(None)
    assert not is_broad_west("SG")


def _geo_pool(con, uid):
    _mk_seed(con, uid, _unit([1, 0, 0]).tolist())
    west = _mk_paper(con, "west", _unit([1, 0.02, 0]).tolist())
    east = _mk_paper(con, "east", _unit([1, 0.04, 0]).tolist())
    unknown = _mk_paper(con, "unknown", _unit([1, 0.06, 0]).tolist())
    con.execute("UPDATE papers SET source_id='SW' WHERE id=?", (west,))
    con.execute("UPDATE papers SET source_id='SE1' WHERE id=?", (east,))
    appdb.upsert_source(con, {"id": "SW", "display_name": "West J", "country_code": "US"})
    appdb.upsert_source(con, {"id": "SE1", "display_name": "East J", "country_code": "SG"})
    con.commit()
    return west, east, unknown


def test_hard_filter_excludes_known_nonwest_venues_only(test_db, monkeypatch):
    monkeypatch.setenv("JUDGE_SHORTLIST_PER_USER", "10")
    user = _mk_user(test_db, "geo@example.com")
    west, east, unknown = _geo_pool(test_db, user["id"])
    # option off: everything competes
    assert {p for p, _ in shortlist_for_user(test_db, user)} == {west, east, unknown}
    # option on: the KNOWN non-West venue disappears; unknown venue stays
    test_db.execute("UPDATE users SET western_context=1 WHERE id=?", (user["id"],))
    test_db.commit()
    user = appdb.get_user(test_db, user["id"])
    assert {p for p, _ in shortlist_for_user(test_db, user)} == {west, unknown}


def test_judge_prompt_geo_instruction_is_optional_and_appended():
    plain = build_prompt(PROFILE)
    geo = build_prompt(PROFILE, western_focus=True)
    assert "GEOGRAPHIC SCOPE" not in plain
    assert "GEOGRAPHIC SCOPE" in geo
    assert "still score well" in geo               # strong papers keep a chance
    # the geo variant is the plain prompt plus the block — nothing else moves
    assert geo.replace("\n" + WESTERN_SOFT_PROMPT.strip() + "\n", "") == plain


def test_toggle_bumps_profile_version_and_requeues(client, test_db):
    login(client, "geotoggle@example.com")
    user = appdb.get_user_by_email(test_db, "geotoggle@example.com")
    test_db.execute("UPDATE users SET onboarded_at=?, name='G' WHERE id=?",
                    (appdb.now(), user["id"]))
    test_db.commit()
    appdb.save_profile(test_db, user["id"], dict(PROFILE), "v-before")

    r = client.post("/settings/scope", data={"western_context": "1"})
    assert r.status_code == 200 and "re-judged" in r.text
    prof = appdb.get_profile(test_db, user["id"])
    assert prof["version"] != "v-before"           # cache discarded, same as edits
    user = appdb.get_user(test_db, user["id"])
    assert user["western_context"] == 1

    # saving the same value again does NOT churn the version
    v = prof["version"]
    r = client.post("/settings/scope", data={"western_context": "1"})
    assert appdb.get_profile(test_db, user["id"])["version"] == v

    # toggling off bumps again
    client.post("/settings/scope", data={})
    assert appdb.get_profile(test_db, user["id"])["version"] != v
    assert appdb.get_user(test_db, user["id"])["western_context"] == 0


def test_onboarding_about_saves_scope_and_briefing_size(client, test_db):
    login(client, "geoonb@example.com")
    r = client.post("/onboarding/about",
                    data={"name": "Dr G", "frequency": "daily",
                          "briefing_size": "10", "western_context": "1"})
    assert r.status_code == 303
    user = appdb.get_user_by_email(test_db, "geoonb@example.com")
    assert user["western_context"] == 1 and user["briefing_size"] == 10
    # unchecking + clearing restores defaults
    client.post("/onboarding/about", data={"name": "Dr G", "frequency": "daily"})
    user = appdb.get_user_by_email(test_db, "geoonb@example.com")
    assert user["western_context"] == 0 and user["briefing_size"] is None


def test_stage_judge_passes_geo_flag(test_db, monkeypatch):
    """The per-user judge prompt carries the instruction only for opted-in
    users — verified through the real stage with a capturing chat stub."""
    import json as _json

    import pipeline.run_daily as rd
    monkeypatch.setenv("JUDGE_SHORTLIST_PER_USER", "5")
    seen = {}

    def fake_chat(system, user_msg, temperature=0.0, **kw):
        n = user_msg.count("PAPER ")
        seen["geo" if "GEOGRAPHIC SCOPE" in system else "plain"] = True
        return _json.dumps([{"n": i, "facets": [], "fit": 5, "why": "s"}
                            for i in range(1, n + 1)]), "stub"

    monkeypatch.setattr(rd.providers, "chat", fake_chat)
    u1 = _mk_user(test_db, "flag-on@example.com")
    test_db.execute("UPDATE users SET western_context=1 WHERE id=?", (u1["id"],))
    u2 = _mk_user(test_db, "flag-off@example.com")
    test_db.commit()
    for uid in (u1["id"], u2["id"]):
        _mk_seed(test_db, uid, _unit([1, 0, 0]).tolist())
    _mk_paper(test_db, "geo-p", _unit([1, 0.1, 0]).tolist())
    rd.stage_shortlist_judge(test_db)
    assert seen.get("geo") and seen.get("plain")
