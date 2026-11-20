# SPDX-License-Identifier: AGPL-3.0-or-later
"""MIME structure of outgoing mail."""
from __future__ import annotations

from app import mailer


def test_html_only_when_no_text():
    msg = mailer.build_message("a@example.com", "S", "<p>Hi</p>")
    assert msg.get_content_type() == "text/html"
    assert "best viewed as HTML" not in msg.as_string()


def test_alternative_when_text_given():
    msg = mailer.build_message("a@example.com", "S", "<p>Hi</p>", text="Hi")
    assert msg.get_content_type() == "multipart/alternative"
    assert msg.get_body(("plain",)).get_content().strip() == "Hi"
    assert "<p>Hi</p>" in msg.get_body(("html",)).get_content()
