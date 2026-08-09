"""Outbound link ordering (preprint DOIs are often unregistered — prefer the
hosting page), the email 'Full summary on your dashboard' deep link, and the
sentence-safe email excerpt."""
import json

from app import db as appdb
from app.routes_user import PREPRINT_SOURCES, outbound_url
from pipeline import briefings
from pipeline.briefings import EMAIL_EXCERPT_CHARS, email_excerpt
from tests.conftest import login


def _paper(con, key, doi, oa_url, source):
    cur = con.execute(
        "INSERT INTO papers(key, doi, title, abstract, oa_url, source, first_seen) "
        "VALUES(?,?,?,?,?,?,?)",
        (key, doi, f"Paper {key}", "An abstract.", oa_url, source, appdb.today()))
    con.commit()
    return cur.lastrowid


def test_preprint_sources_match_gather():
    from pipeline import gather
    assert PREPRINT_SOURCES == set(gather.OSF_PROVIDERS) | {"arxiv"}


def test_outbound_url_orderings():
    preprint = {"doi": "10.31234/osf.io/u2pbg",
                "oa_url": "https://osf.io/preprints/psyarxiv/u2pbg_v1/",
                "source": "psyarxiv"}
    assert outbound_url(preprint) == "https://osf.io/preprints/psyarxiv/u2pbg_v1/"
    # preprint without an oa_url still falls back to the DOI
    assert outbound_url({**preprint, "oa_url": ""}) == \
        "https://doi.org/10.31234/osf.io/u2pbg"
    journal = {"doi": "10.1093/joc/qqaa001", "oa_url": "https://example.org/pdf",
               "source": "openalex"}
    assert outbound_url(journal) == "https://doi.org/10.1093/joc/qqaa001"
    assert outbound_url({**journal, "doi": ""}) == "https://example.org/pdf"
    assert outbound_url({"doi": "", "oa_url": "", "source": ""}) == "/dashboard"


def test_out_redirects_preprint_to_hosting_page(client, test_db):
    login(client, "links@example.com")
    pre = _paper(test_db, "pre", "10.31234/osf.io/u2pbg",
                 "https://osf.io/preprints/psyarxiv/u2pbg_v1/", "psyarxiv")
    jour = _paper(test_db, "jour", "10.1093/joc/qqaa001",
                  "https://example.org/pdf", "openalex")
    r = client.get(f"/out/{pre}")
    assert r.status_code == 302
    assert r.headers["location"] == "https://osf.io/preprints/psyarxiv/u2pbg_v1/"
    r = client.get(f"/out/{jour}")
    assert r.headers["location"] == "https://doi.org/10.1093/joc/qqaa001"


def test_more_logs_and_lands_on_card_anchor(client, test_db):
    login(client, "more@example.com")
    user = appdb.get_user_by_email(test_db, "more@example.com")
    pid = _paper(test_db, "m1", "10.1/m1", "", "openalex")
    r = client.get(f"/more/{pid}")
    assert r.status_code == 302
    assert r.headers["location"] == f"/dashboard#paper-{pid}"
    row = test_db.execute("SELECT context FROM clicks WHERE user_id=? AND paper_id=?",
                          (user["id"], pid)).fetchone()
    assert row and row["context"] == "email-more"


def test_dashboard_cards_carry_stable_anchors(client, test_db):
    login(client, "anchor@example.com")
    user = appdb.get_user_by_email(test_db, "anchor@example.com")
    test_db.execute("UPDATE users SET onboarded_at=?, name='A' WHERE id=?",
                    (appdb.now(), user["id"]))
    appdb.save_profile(test_db, user["id"], {"core_statement": "x", "flavors": []}, "v1")
    pid = _paper(test_db, "anch", "10.1/anch", "", "openalex")
    test_db.execute("INSERT INTO briefing_items(user_id, date, paper_id, rank, fit) "
                    "VALUES(?,?,?,1,8.0)", (user["id"], appdb.today(), pid))
    test_db.commit()
    r = client.get("/dashboard")
    assert f'id="paper-{pid}"' in r.text


def test_email_excerpt_never_cuts_mid_sentence():
    s = ("First sentence about persuasion. " * 10          # ~330 chars
         + "Second block that runs long and keeps going. " * 12)
    out = email_excerpt(s, limit=400)
    assert out.endswith(".") and len(out) <= 400
    assert not out.endswith("goin.")                        # no mid-word cuts
    # short abstracts come back untouched
    assert email_excerpt("Short.", limit=400) == "Short."
    # no sentence boundary in range -> word boundary + ellipsis
    out = email_excerpt("word " * 200, limit=100)
    assert out.endswith("…") and len(out) <= 102


def test_email_truncated_abstract_links_full_summary(client, test_db):
    login(client, "fullsum@example.com")
    user = appdb.get_user_by_email(test_db, "fullsum@example.com")
    test_db.execute("UPDATE users SET onboarded_at=?, name='F' WHERE id=?",
                    (appdb.now(), user["id"]))
    appdb.save_profile(test_db, user["id"], {"core_statement": "x", "flavors": []}, "v1")
    long_abs = ("A long abstract sentence that keeps going for a while. "
                * (EMAIL_EXCERPT_CHARS // 40))
    lp = test_db.execute(
        "INSERT INTO papers(key, doi, title, abstract, first_seen) VALUES(?,?,?,?,?)",
        ("long", "10.1/long", "Long paper", long_abs, appdb.today())).lastrowid
    sp = test_db.execute(
        "INSERT INTO papers(key, doi, title, abstract, first_seen) VALUES(?,?,?,?,?)",
        ("short", "10.1/short", "Short paper", "Tiny abstract.", appdb.today())).lastrowid
    for pid in (lp, sp):
        test_db.execute("INSERT INTO judgments(user_id, paper_id, profile_version, "
                        "fit, judged_at) VALUES(?,?,?,8.0,?)",
                        (user["id"], pid, "v1", appdb.now()))
    test_db.commit()
    user = appdb.get_user(test_db, user["id"])
    rows = briefings.select_items(test_db, user)
    html_out = briefings.render_email(user, rows, appdb.today())
    assert f"/more/{lp}" in html_out
    assert "Full summary on your dashboard" in html_out
    assert f"/more/{sp}" not in html_out                   # untruncated: no link


def test_about_page_is_technical_first_with_methods_note(client):
    """/about leads with the pipeline mechanics, points to the full methods
    doc (inert placeholder until SOURCE_URL is configured), and keeps the
    personal section as a compact card at the bottom."""
    r = client.get("/about")
    assert r.status_code == 200
    body = r.text
    for stage in ("Gathering", "Shortlist by meaning", "The AI judge",
                  "Your briefing"):
        assert stage in body
    assert "docs/how-it-works.md" in body
    assert "coming soon" in body            # tests run without SOURCE_URL
    assert "Behind the tool" in body and "admin@papersradar.com" in body
    # the technical section comes before the personal card
    assert body.index("pipe-flow") < body.index("about-me")
