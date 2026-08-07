"""Provider quota accounting: DB counters, daily caps enforced by the router
and the embedder, error counting."""
import datetime as dt

import pytest

from app import db as appdb
from pipeline import providers
from pipeline.embedder import NemotronEmbedder, QuotaExceeded


def test_counters_accumulate(test_db):
    assert appdb.provider_calls_today(test_db, "groq") == 0
    assert appdb.record_provider(test_db, "groq", True, "m1") == 1
    assert appdb.record_provider(test_db, "groq", True, "m2") == 2
    assert appdb.record_provider(test_db, "groq", False, "boom") == 2   # errors don't count ok
    row = test_db.execute("SELECT * FROM provider_usage WHERE provider='groq'").fetchone()
    assert row["ok_count"] == 2 and row["err_count"] == 1
    assert row["last_detail"] == "boom"


def test_counters_roll_over_by_date(test_db):
    appdb.record_provider(test_db, "gemini", True)
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    test_db.execute("UPDATE provider_usage SET date=? WHERE provider='gemini'",
                    (yesterday,))
    test_db.commit()
    assert appdb.provider_calls_today(test_db, "gemini") == 0
    assert appdb.record_provider(test_db, "gemini", True) == 1


def test_router_respects_daily_cap(test_db, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("CEREBRAS_API_KEY", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    providers._CON = None
    cap = next(p["rpd"] for p in providers.PROVIDERS if p["name"] == "groq")
    test_db.execute(
        "INSERT INTO provider_usage(date, provider, ok_count) VALUES(?,?,?)",
        (appdb.today(), "groq", cap))
    test_db.commit()
    with pytest.raises(providers.ProvidersUnavailable) as e:
        providers.chat("s", "u")
    assert "daily cap" in str(e.value)


def test_router_requires_some_key(test_db, monkeypatch):
    for env in ("GROQ_API_KEY", "GEMINI_API_KEY", "CEREBRAS_API_KEY",
                "OPENROUTER_API_KEY"):
        monkeypatch.setenv(env, "")
    with pytest.raises(providers.ProvidersUnavailable):
        providers.require_any_key()


def test_embedder_respects_openrouter_cap(test_db, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    providers._CON = None
    emb = NemotronEmbedder()
    test_db.execute(
        "INSERT INTO provider_usage(date, provider, ok_count) VALUES(?,?,?)",
        (appdb.today(), "openrouter", emb.rpd))
    test_db.commit()
    with pytest.raises(QuotaExceeded):
        emb.embed(["some text"])


def test_batch_judging_call_budget():
    """The 8-per-call batching is the quota saver: verify call math."""
    from pipeline.judging import BATCH_SIZE
    shortlist = 40
    calls_per_user = -(-shortlist // BATCH_SIZE)
    assert calls_per_user == 5
    groq_rpd = next(p["rpd"] for p in providers.PROVIDERS if p["name"] == "groq")
    assert groq_rpd // calls_per_user == 200         # the DESIGN.md user ceiling
