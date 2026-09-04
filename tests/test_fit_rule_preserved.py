"""A custom (out-of-band) fit_rule survives structured settings edits; only
default-composed rules stay in sync with the core flags. Guards the owner's
imported, calibrated rubric against a settings-save clobber (2026-09-04)."""
from __future__ import annotations

import json

from app import db as appdb
from app.routes_user import _compose_profile_and_finish
from pipeline.build_profile import DEFAULT_FIT_RULE, CORE_FIT_SENTENCE

CUSTOM_RULE = ("Each flavor is already an intersection. Calibration: campaign "
               "effects score 4-6 unless AI or narrative is central.")


def _user(con, email, statement, flavors):
    con.execute(
        "INSERT INTO users(email, created_at, onboarded_at, interest_statement, "
        "interest_flavors_json) VALUES(?,?,?,?,?)",
        (email, appdb.now(), appdb.now(), statement,
         json.dumps(flavors)))
    con.commit()
    return appdb.get_user_by_email(con, email)


def test_custom_fit_rule_survives_structured_edit(test_db):
    user = _user(test_db, "c@x.com", "narratives and AI",
                 [{"name": "ai_persuasion", "description": "AI persuasion",
                   "core": False}])
    prof = {"core_statement": "OLD statement", "flavors":
            [{"key": "ai_persuasion", "description": "AI persuasion",
              "core": False}],
            "fit_rule": CUSTOM_RULE, "negatives": [],
            "positive_exemplar_titles": ["kept exemplar"],
            "negative_exemplar_titles": [], "retrieval_concepts": ["C1"]}
    appdb.save_profile(test_db, user["id"], prof, "v-import")
    _compose_profile_and_finish(test_db, user)     # statement changed -> save
    after = appdb.get_profile(test_db, user["id"])
    assert after["core_statement"] == "narratives and AI"
    assert after["fit_rule"] == CUSTOM_RULE                   # preserved
    assert after["positive_exemplar_titles"] == ["kept exemplar"]
    assert after["version"] != "v-import"


def test_default_fit_rule_tracks_core_flags(test_db):
    user = _user(test_db, "d@x.com", "narratives and AI",
                 [{"name": "ai_persuasion", "description": "AI persuasion",
                   "core": True}])
    prof = {"core_statement": "OLD", "flavors": [],
            "fit_rule": DEFAULT_FIT_RULE, "negatives": [],
            "positive_exemplar_titles": [], "negative_exemplar_titles": [],
            "retrieval_concepts": []}
    appdb.save_profile(test_db, user["id"], prof, "v0")
    _compose_profile_and_finish(test_db, user)
    after = appdb.get_profile(test_db, user["id"])
    assert after["fit_rule"] == DEFAULT_FIT_RULE + CORE_FIT_SENTENCE


def test_unchanged_fields_are_a_noop(test_db):
    user = _user(test_db, "e@x.com", "same statement",
                 [{"name": "topic", "description": "desc", "core": False}])
    from pipeline.build_profile import structured_profile
    prof = structured_profile("same statement",
                              [{"name": "topic", "description": "desc",
                                "core": False}], [])
    prof["fit_rule"] = CUSTOM_RULE          # custom rule, fields unchanged
    appdb.save_profile(test_db, user["id"], prof, "v-stable")
    _compose_profile_and_finish(test_db, user)
    after = appdb.get_profile(test_db, user["id"])
    assert after["version"] == "v-stable"   # no bump, no re-judge
    assert after["fit_rule"] == CUSTOM_RULE
