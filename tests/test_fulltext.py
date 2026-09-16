# SPDX-License-Identifier: AGPL-3.0-or-later
"""Full-text stage: OA fetch routes, sniffing, negative cache, extraction.
Fully offline — a local stub serves fake arXiv/Unpaywall/OA responses."""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

FAKE_PDF = b"%PDF-1.4 fake full text body " + b"x" * 200
FAKE_HTML = b"<html><body><p>Article body</p>" + b"y" * 20_000 + b"</body></html>"
STUB_LANDING = b"<html><body>paywall</body></html>"          # <15 KB stub


class _FTHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body: bytes, ctype: str):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/pdf/"):                      # arXiv
            return self._send(FAKE_PDF, "application/pdf")
        if self.path.startswith("/v2/"):                       # Unpaywall
            base = f"http://{self.headers['Host']}"
            if "10.1000/haspdf" in self.path:
                loc = {"url_for_pdf": f"{base}/oapdf", "url": f"{base}/page"}
            elif "10.1000/htmlonly" in self.path:
                loc = {"url_for_pdf": None, "url": f"{base}/oahtml"}
            else:
                loc = None
            return self._send(json.dumps({"best_oa_location": loc}).encode(),
                              "application/json")
        if self.path == "/oapdf":
            return self._send(FAKE_PDF, "application/pdf")
        if self.path == "/oahtml":
            return self._send(FAKE_HTML, "text/html")
        if self.path == "/landing":
            return self._send(STUB_LANDING, "text/html")
        self.send_response(404)
        self.end_headers()


@pytest.fixture
def ft_stub():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FTHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    os.environ["UNPAYWALL_BASE"] = base
    os.environ["ARXIV_PDF_BASE"] = base
    yield base
    server.shutdown()
    os.environ.pop("UNPAYWALL_BASE", None)
    os.environ.pop("ARXIV_PDF_BASE", None)


def _paper(con, key, **kw):
    from app import db as appdb
    cols = {"key": key, "title": kw.get("title", "T " + key),
            "doi": kw.get("doi", ""), "oa_url": kw.get("oa_url", ""),
            "abstract": "A", "first_seen": appdb.now()}
    cur = con.execute(
        "INSERT INTO papers(key, title, doi, oa_url, abstract, first_seen) "
        "VALUES(:key,:title,:doi,:oa_url,:abstract,:first_seen)", cols)
    con.commit()
    return con.execute("SELECT * FROM papers WHERE id=?",
                       (cur.lastrowid,)).fetchone()


def test_arxiv_route_wins_and_is_idempotent(test_db, ft_stub):
    from pipeline import fetch_fulltext
    p = _paper(test_db, "a1", oa_url="https://arxiv.org/abs/2501.00001")
    assert fetch_fulltext.fetch_one(test_db, p, "2026-08-31") == "ok"
    row = test_db.execute("SELECT * FROM paper_fulltext WHERE paper_id=?",
                          (p["id"],)).fetchone()
    assert row["route"] == "arxiv-pdf" and row["kind"] == "pdf"
    # second call: trusts the existing file, no re-download
    assert fetch_fulltext.fetch_one(test_db, p, "2026-08-31") == "ok"


def test_unpaywall_pdf_route(test_db, ft_stub):
    from pipeline import fetch_fulltext
    p = _paper(test_db, "b1", doi="10.1000/haspdf")
    assert fetch_fulltext.fetch_one(test_db, p, "2026-08-31") == "ok"
    row = test_db.execute("SELECT * FROM paper_fulltext WHERE paper_id=?",
                          (p["id"],)).fetchone()
    assert row["route"] == "unpaywall-pdf"


def test_html_fulltext_accepted_but_stub_rejected(test_db, ft_stub):
    from pipeline import fetch_fulltext
    good = _paper(test_db, "c1", doi="10.1000/htmlonly")
    assert fetch_fulltext.fetch_one(test_db, good, "2026-08-31") == "ok"
    assert test_db.execute("SELECT kind FROM paper_fulltext WHERE paper_id=?",
                           (good["id"],)).fetchone()["kind"] == "html"
    # a small landing page is not full text -> negative cache
    stub = _paper(test_db, "c2", oa_url=f"{ft_stub}/landing")
    assert fetch_fulltext.fetch_one(test_db, stub, "2026-08-31") == "none"
    assert test_db.execute("SELECT status FROM paper_fulltext WHERE paper_id=?",
                           (stub["id"],)).fetchone()["status"] == "none"


def test_negative_cache_prevents_refetch(test_db, ft_stub, monkeypatch):
    from pipeline import fetch_fulltext
    p = _paper(test_db, "d1")            # no routes at all
    assert fetch_fulltext.fetch_one(test_db, p, "2026-08-31") == "none"
    monkeypatch.setattr(fetch_fulltext, "routes_for",
                        lambda paper: pytest.fail("negative cache ignored"))
    assert fetch_fulltext.fetch_one(test_db, p, "2026-08-31") == "none"


def test_run_scopes_to_podcast_users(test_db, ft_stub):
    from app import db as appdb
    from pipeline import fetch_fulltext
    os.environ["PODCAST_ENGINES"] = "anchor"
    try:
        test_db.execute(
            "INSERT INTO users(email, created_at, onboarded_at, podcast_enabled) "
            "VALUES('p@x.com', ?, ?, 1)", (appdb.now(), appdb.now()))
        test_db.execute(
            "INSERT INTO users(email, created_at, onboarded_at, podcast_enabled) "
            "VALUES('n@x.com', ?, ?, 0)", (appdb.now(), appdb.now()))
        u_pod = appdb.get_user_by_email(test_db, "p@x.com")
        u_no = appdb.get_user_by_email(test_db, "n@x.com")
        p1 = _paper(test_db, "e1", oa_url="https://arxiv.org/abs/2501.9")
        p2 = _paper(test_db, "e2", oa_url="https://arxiv.org/abs/2501.10")
        for uid, pid in ((u_pod["id"], p1["id"]), (u_no["id"], p2["id"])):
            test_db.execute(
                "INSERT INTO briefing_items(user_id, date, paper_id, rank, fit) "
                "VALUES(?,?,?,1,8)", (uid, "2026-08-31", pid))
        test_db.commit()
        out = fetch_fulltext.run(test_db, "2026-08-31")
        assert out["papers"] == 1 and out["fetched"] == 1
    finally:
        os.environ.pop("PODCAST_ENGINES", None)


def test_extract_text_html(test_db, ft_stub):
    from pipeline import fetch_fulltext
    p = _paper(test_db, "f1", doi="10.1000/htmlonly")
    assert fetch_fulltext.fetch_one(test_db, p, "2026-08-31") == "ok"
    text = fetch_fulltext.extract_text(test_db, p["id"])
    assert "Article body" in text and "<p>" not in text
