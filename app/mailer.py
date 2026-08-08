"""SMTP abstraction. When SMTP_HOST is unset -> DEV MODE: emails are logged
(never sent) and magic-link URLs surface on the admin dev-links page instead.
Briefing sends silently degrade to dashboard-only.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from email.utils import formatdate

from app.config import cfg, smtp_configured

log = logging.getLogger("papersradar.mail")


def send(to: str, subject: str, html: str, text: str = "") -> bool:
    """Returns True if actually sent. Dev mode logs and returns False."""
    if not smtp_configured():
        log.info("DEV-MODE email (not sent) to=%s subject=%r", to, subject)
        return False
    msg = EmailMessage()
    msg["From"] = cfg("SMTP_FROM")
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(text or "This message is best viewed as HTML.")
    msg.add_alternative(html, subtype="html")
    host, port = cfg("SMTP_HOST"), int(cfg("SMTP_PORT"))
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        user, pw = cfg("SMTP_USER"), cfg("SMTP_PASS")
        if user:
            s.login(user, pw)
        s.send_message(msg)
    log.info("sent email to=%s subject=%r", to, subject)
    return True


def send_magic_link(to: str, url: str) -> bool:
    html = f"""
    <div style="font-family:system-ui,sans-serif;max-width:480px;margin:0 auto">
      <h2 style="color:#1a56db">Research Radar</h2>
      <p>Click to sign in — this link works once and expires in 20 minutes:</p>
      <p><a href="{url}" style="display:inline-block;background:#1a56db;color:#fff;
         padding:12px 22px;border-radius:8px;text-decoration:none">Sign in to Research Radar</a></p>
      <p style="color:#666;font-size:13px">If you didn't request this, ignore this email.</p>
    </div>"""
    return send(to, "Your Research Radar sign-in link", html,
                text=f"Sign in to Research Radar: {url}\n(This link works once and "
                     f"expires in 20 minutes.)")
