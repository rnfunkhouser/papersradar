"""Shared test fixtures: isolated temp DB per test, a stub OpenAlex+Zotero
HTTP server (tests never hit the network), and a FastAPI TestClient."""
from __future__ import annotations

import json
import os
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

# Environment must be pinned BEFORE any app import.
os.environ.setdefault("ENV_FILE", "/nonexistent-env-file")
os.environ.setdefault("APP_SECRET", "test-secret-not-for-production")
os.environ.setdefault("PROFILE_BUILD", "off")
os.environ["SMTP_HOST"] = ""              # dev mode


# --- stub OpenAlex + Zotero API ---------------------------------------------

def make_work(doi: str, title: str, abstract: str = "",
              concepts=("https://openalex.org/C1",), venue: str = "Test Journal"):
    inv = {}
    for i, w in enumerate(abstract.split()):
        inv.setdefault(w, []).append(i)
    return {
        "id": "https://openalex.org/W" + re.sub(r"\W", "", doi),
        "doi": f"https://doi.org/{doi}",
        "title": title, "display_name": title,
        "primary_location": {"source": {"display_name": venue,
                                        "id": "https://openalex.org/S1",
                                        "type": "journal"}},
        "authorships": [{"author": {"id": "https://openalex.org/A1",
                                    "display_name": "Ada Author"},
                         "institutions": [{"country_code": "us"}]}],
        "publication_date": "2026-08-01", "created_date": "2026-08-01",
        "type": "article", "language": "en",
        "abstract_inverted_index": inv or None,
        "concepts": [{"id": c, "score": 0.6} for c in concepts],
        "cited_by_count": 0,
        "open_access": {"oa_url": f"https://example.org/{doi}"},
    }


WORKS = {
    "10.1000/alpha": make_work("10.1000/alpha", "Narrative persuasion in online politics",
                               "We study how stories persuade people online across "
                               "political divides using experiments."),
    "10.1000/beta": make_work("10.1000/beta", "Chatbots that change minds",
                              "A conversational AI intervention durably reduces "
                              "conspiracy beliefs in a large sample."),
    "10.1000/gamma": make_work("10.1000/gamma", "Bridging divides with dialogue",
                               "Cross partisan conversations reduce animosity in a "
                               "field experiment."),
}

ZOTERO_ITEMS = [
    {"key": "K1", "data": {"itemType": "journalArticle",
                           "title": "Narrative persuasion in online politics",
                           "DOI": "10.1000/alpha"}},
    {"key": "K2", "data": {"itemType": "journalArticle",
                           "title": "Chatbots that change minds",
                           "DOI": "", "extra": "DOI: 10.1000/beta"}},
    {"key": "K3", "data": {"itemType": "journalArticle",
                           "title": "Bridging divides with dialogue", "DOI": ""}},
    {"key": "K4", "data": {"itemType": "note", "title": "just a note"}},
    {"key": "K5", "data": {"itemType": "journalArticle", "title": "short",
                           "DOI": ""}},          # unresolvable: title too sparse
]


class _StubHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):                    # quiet
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.unquote(self.path)
        # OpenAlex: DOI lookup
        m = re.search(r"/works/https://doi\.org/([^?]+)", path)
        if m:
            w = WORKS.get(m.group(1))
            return self._json(w if w else {"error": "404"}, 200 if w else 404)
        # OpenAlex: title search
        if path.startswith("/works?") and "search=" in path:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            term = (q.get("search") or [""])[0].lower()
            hits = [w for w in WORKS.values() if term[:20] in w["title"].lower()]
            return self._json({"results": hits[:1]})
        # OpenAlex: gather filter query
        if path.startswith("/works?") and "filter=" in path:
            return self._json({"results": list(WORKS.values()),
                               "meta": {"next_cursor": None}})
        # Zotero: collections
        if re.search(r"/(users|groups)/\d+/collections", path):
            return self._json([{"key": "COLL1", "data": {"name": "My Papers"}}])
        # Zotero: items
        if re.search(r"/(users|groups)/\d+(/collections/\w+)?/items/top", path):
            return self._json(ZOTERO_ITEMS)
        self._json({"error": "not found"}, 404)


@pytest.fixture(scope="session")
def stub_api():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{server.server_port}"
    os.environ["OPENALEX_BASE"] = base
    os.environ["ZOTERO_BASE"] = base
    os.environ["ARXIV_BASE"] = base      # stub 404s -> sources return empty
    os.environ["OSF_BASE"] = base
    yield base
    server.shutdown()


# --- per-test isolated DB ----------------------------------------------------

@pytest.fixture
def test_db(tmp_path):
    os.environ["DB_PATH"] = str(tmp_path / "test.db")
    os.environ["LOG_DIR"] = str(tmp_path / "logs")
    from pipeline import providers
    providers._CON = None                      # drop cached cross-test connection
    from app import db
    con = db.connect()
    yield con
    con.close()


@pytest.fixture
def client(test_db, stub_api):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, follow_redirects=False) as c:
        yield c


def login(client, email: str):
    """Drive the magic-link flow through HTTP + the dev-link in the DB."""
    from app import db
    r = client.post("/login", data={"email": email})
    assert r.status_code == 200
    con = db.connect()
    row = con.execute(
        "SELECT dev_link FROM auth_tokens WHERE email=? ORDER BY created_at DESC",
        (email,)).fetchone()
    con.close()
    assert row and row["dev_link"]
    token_url = row["dev_link"].split("/auth/")[1]
    r = client.get(f"/auth/{token_url}")
    assert r.status_code == 303
    return r
