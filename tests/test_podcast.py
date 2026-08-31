"""Podcast stage + feed: script register, episode assembly (WAV fallback path
— no ffmpeg dependency in tests), stage idempotency, deferred email with
status footer, token-authenticated RSS feed. Fully offline: the writer LLM
and TTS are stubbed."""
from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET

import pytest


@pytest.fixture
def podcast_env(monkeypatch):
    monkeypatch.setenv("PODCAST_ENGINES", "anchor")
    # force the WAV path so tests never need ffmpeg
    from pipeline import tts
    monkeypatch.setattr(tts.shutil, "which", lambda name: None)
    # deterministic fake TTS: 1 second of silence per call
    monkeypatch.setattr(tts, "synthesize",
                        lambda text, voice=None: b"\x00" * tts.BYTES_PER_SEC)
    # deterministic fake writer
    from pipeline import providers

    def fake_chat(system, user, **kw):
        assert "REGISTER" in system            # the locked register travels
        return ("The next paper today comes from a team examining things. "
                "Findings were reported.", "stub")
    monkeypatch.setattr(providers, "chat", fake_chat)
    yield


def _seed_user_with_briefing(con, email="owner@x.com", n_papers=2,
                             date="2026-08-31", insert_items=True):
    from app import db as appdb
    con.execute(
        "INSERT INTO users(email, created_at, onboarded_at, frequency) "
        "VALUES(?,?,?, 'daily')", (email, appdb.now(), appdb.now()))
    user = appdb.get_user_by_email(con, email)
    appdb.save_profile(con, user["id"], {"criteria": "x"}, "v1")
    for i in range(n_papers):
        cur = con.execute(
            "INSERT INTO papers(key, title, venue, authors_json, pub_date, "
            "abstract, first_seen) VALUES(?,?,?,?,?,?,?)",
            (f"k{i}", f"Paper {i} title", "Journal of Tests",
             json.dumps(["Ada Author", "Bo Coauthor"]), "2026-08-28",
             "An abstract about methods.", appdb.now()))
        pid = cur.lastrowid
        con.execute(
            "INSERT INTO judgments(user_id, paper_id, profile_version, fit, "
            "flavors_json, why, provider, judged_at) VALUES(?,?,?,?,?,?,?,?)",
            (user["id"], pid, "v1", 8.0, "[]", "fits the criteria", "stub",
             appdb.now()))
        if insert_items:
            con.execute(
                "INSERT INTO briefing_items(user_id, date, paper_id, rank, fit) "
                "VALUES(?,?,?,?,8)", (user["id"], date, pid, i + 1))
    con.commit()
    return appdb.get_user_by_email(con, email)


def _enable(con, email):
    from pipeline import podcast
    podcast.enable_user(con, email)
    from app import db as appdb
    return appdb.get_user_by_email(con, email)


# --- script -------------------------------------------------------------------

def test_dateline_and_close_wording():
    from pipeline import podcast_script
    d = podcast_script.dateline("2026-08-31", 5, 3)
    assert d.startswith("Papers Radar for Monday, August 31: five papers")
    assert "3 with full text" in d
    assert "Full citations are in the show notes" in podcast_script.closing(5)


def test_segment_prompt_two_tier():
    from pipeline import podcast_script
    assert str(podcast_script.FULLTEXT_WORDS[0]) in podcast_script.FULLTEXT_INSTRUCTIONS
    assert "ONLY the abstract" in podcast_script.ABSTRACT_INSTRUCTIONS
    for banned in ("fascinating", "amazing", "second person"):
        assert banned in podcast_script.REGISTER


def test_nlm_steering_prompt_lists_papers(test_db, podcast_env):
    from pipeline import podcast_script
    rows = [{"title": "Full A"}, {"title": "Abs B"}]
    p = podcast_script.nlm_steering_prompt(rows, ["text", ""], "2026-08-31")
    assert '"Full A"' in p and '"Abs B"' in p
    assert "PhD-level" in p and "abstract-only" in p.lower()


# --- stage --------------------------------------------------------------------

def test_stage_builds_episode_and_defers_email(test_db, podcast_env, monkeypatch):
    from pipeline import briefings, podcast
    from app import mailer
    sent = []
    monkeypatch.setattr(mailer, "send", lambda to, subj, html, text="":
                        sent.append((to, subj, html)) or True)
    user = _seed_user_with_briefing(test_db, insert_items=False)
    _enable(test_db, user["email"])
    # briefings stage builds the items but defers the podcast user's email
    out = briefings.run(test_db, "2026-08-31")
    assert out["emails_deferred_to_podcast"] == 1 and out["emails_sent"] == 0
    assert not sent
    # podcast stage: episode + the deferred email with a status footer
    out = podcast.run(test_db, "2026-08-31")
    u = out["users"][0]
    assert u["engines"]["anchor"] == "ok" and u["email_sent"]
    assert len(sent) == 1
    assert "Podcast" in sent[0][2] and "episode published" in sent[0][2]
    ep = test_db.execute("SELECT * FROM podcast_episodes").fetchone()
    assert ep["status"] == "ok" and ep["mime"] == "audio/wav"
    assert ep["duration_sec"] == 4          # intro + 2 papers + close, 1s each
    chapters = json.loads(ep["chapters_json"])
    assert [c["title"] for c in chapters] == \
        ["Introduction", "Paper 0 title", "Paper 1 title", "Close"]
    from app.config import db_path
    assert (db_path().parent / ep["audio_path"]).exists()


def test_stage_idempotent_and_no_double_email(test_db, podcast_env, monkeypatch):
    from pipeline import podcast
    from app import mailer
    sent = []
    monkeypatch.setattr(mailer, "send", lambda *a, **k: sent.append(a) or True)
    user = _seed_user_with_briefing(test_db)
    _enable(test_db, user["email"])
    podcast.run(test_db, "2026-08-31")
    first = test_db.execute("SELECT created_at FROM podcast_episodes").fetchone()
    out = podcast.run(test_db, "2026-08-31")     # the 4:30 retry re-run
    assert out["users"][0]["engines"]["anchor"] == "ok (cached)"
    assert len(sent) == 1                        # email once per (user, date)
    again = test_db.execute("SELECT created_at FROM podcast_episodes").fetchone()
    assert again["created_at"] == first["created_at"]


def test_engine_failure_recorded_and_emailed(test_db, podcast_env, monkeypatch):
    from pipeline import podcast, tts
    from app import mailer
    sent = []
    monkeypatch.setattr(mailer, "send", lambda to, subj, html, text="":
                        sent.append(html) or True)
    monkeypatch.setattr(tts, "synthesize",
                        lambda *a, **k: (_ for _ in ()).throw(
                            tts.TTSError("free-tier quota exhausted")))
    monkeypatch.setattr(podcast.tts, "synthesize", tts.synthesize)
    user = _seed_user_with_briefing(test_db)
    _enable(test_db, user["email"])
    out = podcast.run(test_db, "2026-08-31")
    assert out["users"][0]["engines"]["anchor"].startswith("error")
    ep = test_db.execute("SELECT * FROM podcast_episodes").fetchone()
    assert ep["status"] == "error" and "quota" in ep["detail"]
    # the email still goes, carrying the failure cause
    assert len(sent) == 1 and "FAILED" in sent[0] and "quota" in sent[0]


def test_disabled_feature_is_noop(test_db, monkeypatch):
    monkeypatch.delenv("PODCAST_ENGINES", raising=False)
    from pipeline import podcast
    out = podcast.run(test_db, "2026-08-31")
    assert "skipped" in out


# --- feed ---------------------------------------------------------------------

def test_feed_requires_token_and_serves_rss(client, test_db, podcast_env):
    from pipeline import podcast
    user = _seed_user_with_briefing(test_db)
    user = _enable(test_db, user["email"])
    podcast.run(test_db, "2026-08-31")
    token = test_db.execute("SELECT podcast_token FROM users WHERE id=?",
                            (user["id"],)).fetchone()["podcast_token"]
    assert client.get("/podcast/not-a-real-token-here/feed.xml").status_code == 404
    r = client.get(f"/podcast/{token}/feed.xml")
    assert r.status_code == 200
    assert "rss+xml" in r.headers["content-type"]
    root = ET.fromstring(r.text)                 # well-formed XML
    ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
    item = root.find("channel/item")
    assert item is not None
    assert item.find("title").text.startswith("[Anchor]")
    enc = item.find("enclosure")
    assert enc.get("type") == "audio/wav" and int(enc.get("length")) > 0
    assert root.find("channel/itunes:block", ns).text == "Yes"
    # the enclosure URL serves the audio through the same token
    ep_path = enc.get("url").split("papersradar.com")[-1] \
        if "papersradar.com" in enc.get("url") else enc.get("url")
    ep_path = "/" + ep_path.split("://", 1)[-1].split("/", 1)[1] \
        if "://" in ep_path else ep_path
    r2 = client.get(ep_path)
    assert r2.status_code == 200
    assert r2.content[:4] == b"RIFF"


def test_episode_denied_across_users(client, test_db, podcast_env):
    from pipeline import podcast
    from app import db as appdb
    u1 = _seed_user_with_briefing(test_db, "one@x.com")
    _enable(test_db, "one@x.com")
    podcast.run(test_db, "2026-08-31")
    test_db.execute("INSERT INTO users(email, created_at) VALUES('two@x.com', ?)",
                    (appdb.now(),))
    test_db.commit()
    podcast.enable_user(test_db, "two@x.com")
    tok2 = appdb.get_user_by_email(test_db, "two@x.com")["podcast_token"]
    ep = test_db.execute("SELECT id FROM podcast_episodes").fetchone()
    assert client.get(f"/podcast/{tok2}/ep/{ep['id']}.wav").status_code == 404


def test_enable_cli_mints_stable_token(test_db, capsys):
    from pipeline import podcast
    from app import db as appdb
    test_db.execute("INSERT INTO users(email, created_at) VALUES('t@x.com', ?)",
                    (appdb.now(),))
    test_db.commit()
    podcast.enable_user(test_db, "t@x.com")
    tok1 = appdb.get_user_by_email(test_db, "t@x.com")["podcast_token"]
    assert len(tok1) >= 24
    assert f"/podcast/{tok1}/feed.xml" in capsys.readouterr().out
    podcast.disable_user(test_db, "t@x.com")
    podcast.enable_user(test_db, "t@x.com")       # re-enable keeps the token
    assert appdb.get_user_by_email(test_db, "t@x.com")["podcast_token"] == tok1
