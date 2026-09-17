# SPDX-License-Identifier: AGPL-3.0-or-later
"""Auth: magic-link token lifecycle, session signing, rate limiting,
secret-at-rest encryption."""
import datetime as dt

import pytest

from app import auth


def test_email_validation():
    assert auth.valid_email("a@b.co")
    assert not auth.valid_email("not-an-email")
    assert not auth.valid_email("")
    assert not auth.valid_email("a b@c.d")


def test_token_roundtrip_single_use(test_db):
    token, url = auth.issue_token(test_db, "X@Example.com")
    assert token in url
    assert auth.redeem_token(test_db, token) == "x@example.com"
    assert auth.redeem_token(test_db, token) is None          # single-use


def test_token_unknown_and_expired(test_db):
    assert auth.redeem_token(test_db, "bogus") is None
    token, _ = auth.issue_token(test_db, "y@example.com")
    past = (dt.datetime.now() - dt.timedelta(minutes=1)).isoformat()
    test_db.execute("UPDATE auth_tokens SET expires_at=?", (past,))
    test_db.commit()
    assert auth.redeem_token(test_db, token) is None


def test_dev_link_stored_only_without_smtp(test_db, monkeypatch):
    auth.issue_token(test_db, "dev@example.com")
    row = test_db.execute("SELECT dev_link FROM auth_tokens WHERE email=?",
                          ("dev@example.com",)).fetchone()
    assert row["dev_link"]                                     # SMTP unset in tests
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    auth.issue_token(test_db, "prod@example.com")
    row = test_db.execute("SELECT dev_link FROM auth_tokens WHERE email=?",
                          ("prod@example.com",)).fetchone()
    assert row["dev_link"] is None


def test_session_sign_verify_tamper():
    cookie = auth.make_session(42)
    assert auth.read_session(cookie) == 42
    uid, exp, sig = cookie.split(".")
    assert auth.read_session(f"43.{exp}.{sig}") is None        # tampered uid
    assert auth.read_session("garbage") is None
    assert auth.read_session(None) is None


def test_session_expiry(monkeypatch):
    cookie = auth.make_session(7)
    uid, exp, _ = cookie.split(".")
    old_exp = str(int(dt.datetime.now().timestamp()) - 10)
    forged = f"{uid}.{old_exp}." + auth._sign(f"{uid}.{old_exp}")
    assert auth.read_session(forged) is None                   # expired but validly signed


def test_rate_limit_per_email(test_db):
    for _ in range(auth.RATE_PER_EMAIL):
        auth.check_rate_limit(test_db, "spam@example.com", "1.2.3.4")
    with pytest.raises(auth.RateLimited):
        auth.check_rate_limit(test_db, "spam@example.com", "5.6.7.8")
    # a different email from a different IP still passes
    auth.check_rate_limit(test_db, "ok@example.com", "9.9.9.9")


def test_rate_limit_per_ip(test_db):
    for i in range(auth.RATE_PER_IP):
        auth.check_rate_limit(test_db, f"u{i}@example.com", "8.8.8.8")
    with pytest.raises(auth.RateLimited):
        auth.check_rate_limit(test_db, "new@example.com", "8.8.8.8")


def test_secret_encryption_roundtrip():
    ct = auth.encrypt_secret("zotero-key-XYZ")
    assert ct and "zotero-key-XYZ" not in ct
    assert auth.decrypt_secret(ct) == "zotero-key-XYZ"
    assert auth.encrypt_secret("") == ""
    assert auth.decrypt_secret("") == ""
    assert auth.decrypt_secret("not-base64!!") == ""


def test_link_get_does_not_consume_token(client, test_db):
    """Email link-scanners GET the URL before the person clicks; the GET must
    only show the confirm page. Only the POST redeems (single-use)."""
    r = client.post("/login", data={"email": "scan@example.com"})
    assert r.status_code == 200
    row = test_db.execute("SELECT dev_link FROM auth_tokens WHERE email=?",
                          ("scan@example.com",)).fetchone()
    token = row["dev_link"].split("/auth/")[1]
    for _ in range(3):                                   # scanner prefetches
        r = client.get(f"/auth/{token}")
        assert r.status_code == 200 and "Confirm sign-in" in r.text
    r = client.post(f"/auth/{token}")                    # the person clicks
    assert r.status_code == 303
    r = client.post(f"/auth/{token}")                    # second use refused
    assert r.status_code == 400
    r = client.get(f"/auth/{token}")                     # and GET now refused too
    assert r.status_code == 400
    assert client.get("/auth/bogus").status_code == 400
