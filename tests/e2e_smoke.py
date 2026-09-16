# SPDX-License-Identifier: AGPL-3.0-or-later
"""End-to-end smoke test: boots the real app under uvicorn (dev mode, stubbed
OpenAlex/Zotero, temp DB), registers a user over plain HTTP, completes
onboarding with 3 seed papers, runs the offline-safe pipeline pieces, and
asserts a dashboard renders with briefing cards + working feedback."""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
import urllib.parse
import http.cookiejar

import pytest

from app import db as appdb


@pytest.fixture
def server(test_db, stub_api, monkeypatch):
    port = _free_port()
    monkeypatch.setenv("BASE_URL", f"http://127.0.0.1:{port}")
    import uvicorn
    from app.main import app
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(cfg)
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    assert srv.started, "uvicorn failed to start"
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    t.join(timeout=5)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Browser:
    """Tiny cookie-keeping HTTP client over urllib — real HTTP, no test client."""

    def __init__(self, base: str):
        self.base = base
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            _NoRedirect())

    def get(self, path: str):
        return self._req(urllib.request.Request(self.base + path))

    def post(self, path: str, data: dict):
        body = urllib.parse.urlencode(data, doseq=True).encode()
        return self._req(urllib.request.Request(
            self.base + path, data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"}))

    def _req(self, req):
        try:
            resp = self.opener.open(req, timeout=10)
            return resp.status, dict(resp.headers), resp.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def test_e2e_signup_onboard_pipeline_dashboard(server, test_db):
    b = Browser(server)

    # landing + login page render
    code, _, body = b.get("/")
    assert code == 200 and "research radar" in body
    code, _, body = b.get("/login")
    assert code == 200

    # magic-link signup (dev mode: link comes from the DB / log)
    code, _, body = b.post("/login", data={"email": "pilot@example.edu"})
    assert code == 200 and "development mode" in body
    row = test_db.execute("SELECT dev_link FROM auth_tokens WHERE email=?",
                          ("pilot@example.edu",)).fetchone()
    token = row["dev_link"].split("/auth/")[1]
    code, headers, _ = b.get(f"/auth/{token}")
    assert code == 303 and headers["location"].startswith("/onboarding")

    # onboarding: 6 steps (structured interests)
    code, headers, _ = b.post("/onboarding/about",
                              data={"name": "Pilot Prof", "frequency": "daily"})
    assert code == 303
    code, headers, _ = b.post(
        "/onboarding/interests",
        data={"statement": "I study narrative persuasion and conversational AI in "
                           "online political communication."})
    assert code == 303
    code, headers, _ = b.post(
        "/onboarding/flavors",
        data={"flavor_key": ["narrative persuasion", "AI persuasion"],
              "flavor_desc": ["Stories as persuasion devices in politics.",
                              "Conversational AI that shifts attitudes."],
              "flavor_core": ["1", "0"]})
    assert code == 303
    code, headers, _ = b.post(
        "/onboarding/negatives",
        data={"negative": ["Chatbot UX with no persuasion outcome"]})
    assert code == 303
    code, _, body = b.post(
        "/onboarding/seeds",
        data={"papers": "10.1000/alpha\n10.1000/beta\nBridging divides with dialogue"})
    assert code == 200 and "Added 3 papers" in body
    code, headers, _ = b.post("/onboarding/finish", data={})
    assert code == 303 and headers["location"] == "/dashboard"

    code, _, body = b.get("/dashboard")
    assert code == 200 and "warming up" in body

    # --- offline pipeline: fake embeddings, stub judge, then briefings -------
    user = appdb.get_user_by_email(test_db, "pilot@example.edu")
    prof = appdb.get_profile(test_db, user["id"])
    from pipeline import gather
    from pipeline.embedder import pack
    from pipeline import run_daily

    # gather from the stub OpenAlex (uses the profile's concepts -> give it one)
    prof["retrieval_concepts"] = ["https://openalex.org/C1"]
    appdb.save_profile(test_db, user["id"], prof, prof["version"])
    summary = gather.run(test_db, since="2026-07-01")
    assert summary["new_openalex"] == 3

    # deterministic "embeddings" for seeds and papers (no API)
    import numpy as np
    rng = np.random.default_rng(0)
    for r in test_db.execute("SELECT id FROM seeds WHERE user_id=?",
                             (user["id"],)).fetchall():
        v = rng.normal(size=8)
        test_db.execute(
            "INSERT OR REPLACE INTO seed_embeddings(seed_id, embedder, dim, vector, "
            "created_at) VALUES(?, 'nemotron-3-embed-1b', 8, ?, ?)",
            (r["id"], pack(v / np.linalg.norm(v)), appdb.now()))
    for r in test_db.execute("SELECT id FROM papers").fetchall():
        v = rng.normal(size=8)
        test_db.execute(
            "INSERT OR REPLACE INTO paper_embeddings(paper_id, embedder, dim, vector, "
            "created_at) VALUES(?, 'nemotron-3-embed-1b', 8, ?, ?)",
            (r["id"], pack(v / np.linalg.norm(v)), appdb.now()))
    test_db.commit()

    # judge via a stubbed chat -> everything fits 8/10
    from pipeline import judging

    def fake_chat(system, user_msg, temperature=0.0, **kw):
        n = user_msg.count("PAPER ")
        rows = [{"n": i, "facets": ["my_research_interests"], "fit": 8,
                 "why": "stub verdict"} for i in range(1, n + 1)]
        return json.dumps(rows), "stub"

    import pipeline.run_daily as rd
    original = rd.providers.chat
    rd.providers.chat = fake_chat
    try:
        result = rd.stage_shortlist_judge(test_db)
    finally:
        rd.providers.chat = original
    assert result["users"][0]["judged"] == 3

    # briefings (SMTP unset -> dashboard-only, no exception)
    from pipeline import briefings
    summary = briefings.run(test_db)
    assert summary["users_with_items"] == 1 and summary["emails_sent"] == 0

    # dashboard now renders cards with judge chips
    code, _, body = b.get("/dashboard")
    assert code == 200
    assert "8/10" in body and "stub verdict" in body
    assert "Narrative persuasion in online politics" in body

    # feedback: thumbs-up over HTTP
    pid = test_db.execute("SELECT paper_id FROM briefing_items WHERE user_id=?",
                          (user["id"],)).fetchone()["paper_id"]
    code, _, body = b.post("/feedback", data={"paper_id": pid, "vote": "up"})
    assert code == 200 and json.loads(body)["ok"]
    vote = test_db.execute("SELECT vote FROM feedback WHERE user_id=? AND paper_id=?",
                           (user["id"], pid)).fetchone()["vote"]
    assert vote == "up"

    # click-through logging redirect
    code, headers, _ = b.get(f"/out/{pid}")
    assert code == 302 and "doi.org" in headers["location"]
    assert test_db.execute("SELECT COUNT(*) c FROM clicks WHERE user_id=?",
                           (user["id"],)).fetchone()["c"] == 1

    # admin is denied to non-admins, allowed to admins
    code, headers, _ = b.get("/admin")
    assert code == 303 and headers["location"] == "/dashboard"
    test_db.execute("UPDATE users SET is_admin=1 WHERE id=?", (user["id"],))
    test_db.commit()
    code, _, body = b.get("/admin")
    assert code == 200 and "pilot@example.edu" in body
    code, _, body = b.get("/admin/dev-links")
    assert code == 200
