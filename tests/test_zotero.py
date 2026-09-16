# SPDX-License-Identifier: AGPL-3.0-or-later
"""Zotero linking: connect/preview/import over HTTP (stubbed API), ledger
idempotence, removal-safety, key handling."""
import json

from app import auth, db as appdb, zotero
from tests.conftest import login, ZOTERO_ITEMS


def _onboard(client, email):
    login(client, email)
    client.post("/onboarding/about", data={"name": "Dr Z", "frequency": "daily"})


def test_connect_validates_and_encrypts(client):
    _onboard(client, "z1@example.com")
    r = client.post("/zotero/connect",
                    data={"library_type": "user", "library_id": "not-a-number",
                          "api_key": "sekrit", "next": "/settings"})
    assert r.status_code == 303 and "zerr=" in r.headers["location"]
    r = client.post("/zotero/connect",
                    data={"library_type": "user", "library_id": "12345",
                          "api_key": "sekrit", "next": "/settings"})
    assert "znotice=" in r.headers["location"]
    con = appdb.connect()
    user = appdb.get_user_by_email(con, "z1@example.com")
    link = con.execute("SELECT * FROM zotero_links WHERE user_id=?",
                       (user["id"],)).fetchone()
    assert link["api_key_enc"] and "sekrit" not in link["api_key_enc"]
    assert auth.decrypt_secret(link["api_key_enc"]) == "sekrit"
    con.close()
    # the key never appears in any rendered page
    r = client.get("/settings")
    assert "sekrit" not in r.text


def test_preview_and_import_flow(client):
    _onboard(client, "z2@example.com")
    client.post("/zotero/connect",
                data={"library_type": "user", "library_id": "777",
                      "api_key": "", "next": "/settings"})
    r = client.get("/settings?zpreview=1")
    assert r.status_code == 200
    assert "new to import" in r.text and "My Papers" in r.text
    r = client.post("/zotero/import", data={"next": "/settings"})
    assert "Imported+3" in r.headers["location"] or "Imported%203" in r.headers["location"]
    con = appdb.connect()
    user = appdb.get_user_by_email(con, "z2@example.com")
    seeds = con.execute("SELECT * FROM seeds WHERE user_id=?", (user["id"],)).fetchall()
    # K1 (DOI), K2 (DOI in extra), K3 (title-resolved) — note K4/K5 skipped
    assert {s["doi"] for s in seeds} == {"10.1000/alpha", "10.1000/beta", "10.1000/gamma"}
    assert all(s["source"] == "zotero" for s in seeds)
    link = con.execute("SELECT * FROM zotero_links WHERE user_id=?",
                       (user["id"],)).fetchone()
    ledger = json.loads(link["ledger_json"])
    assert set(ledger["keys"]) >= {"K1", "K2", "K3", "K5"}
    assert link["last_sync_at"]

    # resync is idempotent
    client.post("/zotero/resync", data={"next": "/settings"})
    n = con.execute("SELECT COUNT(*) c FROM seeds WHERE user_id=?",
                    (user["id"],)).fetchone()["c"]
    assert n == 3

    # removal-safety: delete a seed, resync must NOT re-add it
    client.post("/onboarding/seeds/remove",
                data={"seed_id": seeds[0]["id"], "next": "/settings"})
    client.post("/zotero/resync", data={"next": "/settings"})
    n = con.execute("SELECT COUNT(*) c FROM seeds WHERE user_id=?",
                    (user["id"],)).fetchone()["c"]
    assert n == 2
    con.close()


def test_disconnect_keeps_seeds(client):
    _onboard(client, "z3@example.com")
    client.post("/zotero/connect",
                data={"library_type": "group", "library_id": "88",
                      "api_key": "", "next": "/onboarding?step=3"})
    client.post("/zotero/import", data={"next": "/onboarding?step=3"})
    r = client.post("/zotero/disconnect", data={"next": "/onboarding?step=3"})
    assert r.status_code == 303
    con = appdb.connect()
    user = appdb.get_user_by_email(con, "z3@example.com")
    assert con.execute("SELECT COUNT(*) c FROM zotero_links WHERE user_id=?",
                       (user["id"],)).fetchone()["c"] == 0
    assert con.execute("SELECT COUNT(*) c FROM seeds WHERE user_id=?",
                       (user["id"],)).fetchone()["c"] == 3
    con.close()


def test_parse_library_ref():
    # pasted group URLs force type 'group' — the recommended keyless path
    assert zotero.parse_library_ref(
        "https://www.zotero.org/groups/1234567/my-seed-papers") == ("group", "1234567")
    assert zotero.parse_library_ref("zotero.org/groups/42") == ("group", "42")
    assert zotero.parse_library_ref(" 987 ".strip()) == ("group", "987")
    assert zotero.parse_library_ref("987", library_type="user") == ("user", "987")
    assert zotero.parse_library_ref("not a ref") is None
    assert zotero.parse_library_ref("") is None


def test_public_group_url_connect_keyless(client):
    """The recommended path: paste a public group URL, no API key at all."""
    _onboard(client, "zg@example.com")
    r = client.post("/zotero/connect",
                    data={"library_type": "group",
                          "library_id": "https://www.zotero.org/groups/555/my-seeds",
                          "api_key": "", "next": "/settings"})
    assert r.status_code == 303 and "znotice=" in r.headers["location"]
    con = appdb.connect()
    user = appdb.get_user_by_email(con, "zg@example.com")
    link = con.execute("SELECT * FROM zotero_links WHERE user_id=?",
                       (user["id"],)).fetchone()
    assert link["library_type"] == "group" and link["library_id"] == "555"
    assert link["api_key_enc"] == ""               # keyless: nothing stored
    con.close()
    # import works keylessly against the (stub) public group API
    r = client.post("/zotero/import", data={"next": "/settings"})
    assert r.status_code == 303 and "znotice=" in r.headers["location"]
    con = appdb.connect()
    n = con.execute("SELECT COUNT(*) c FROM seeds WHERE user_id=? AND source='zotero'",
                    (user["id"],)).fetchone()["c"]
    assert n == 3
    con.close()


def test_scholarly_filter_and_doi_extraction():
    sch = zotero.scholarly_items(ZOTERO_ITEMS)
    assert {it["key"] for it in sch} == {"K1", "K2", "K3", "K5"}   # K4 note excluded
    assert zotero.item_doi(ZOTERO_ITEMS[0]["data"]) == ("10.1000/alpha", "DOI in record")
    doi, how = zotero.item_doi(ZOTERO_ITEMS[1]["data"])
    assert doi == "10.1000/beta" and "record" in how
    assert zotero.item_doi(ZOTERO_ITEMS[2]["data"])[0] == ""
