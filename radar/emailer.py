"""Render and deliver HOT alerts and the digest (spec section 12)."""
from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Callable, Mapping

from jinja2 import Environment, FileSystemLoader, select_autoescape

from radar.config import BUCKETS
from radar.digest import DigestData
from radar.models import Brief
from radar.text import slugify

log = logging.getLogger(__name__)
_ENV = Environment(loader=FileSystemLoader(str(Path(__file__).resolve().parent / "templates")),
                   autoescape=select_autoescape(["html"]))


class EmailError(RuntimeError):
    pass


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 3].rstrip() + "..."


def hot_subject(brief: Brief) -> str:
    bucket = BUCKETS.get(brief.topic.bucket, "Emerging")
    if brief.headline and brief.headline != brief.topic.name:
        return f"HOT [{bucket}] {brief.topic.name}: {_truncate(brief.headline, 60)} — {brief.urgency}"
    return f"HOT [{bucket}] {brief.topic.name} — {brief.urgency}"


def render_hot(brief: Brief) -> tuple[str, str, str]:
    ctx = {"brief": brief, "bucket": BUCKETS.get(brief.topic.bucket, "Emerging")}
    return hot_subject(brief), _ENV.get_template("hot.txt").render(**ctx), _ENV.get_template("hot.html").render(**ctx)


def render_digest(data: DigestData, angle_names: Mapping[str, str]) -> tuple[str, str, str]:
    subject = f"Radar digest {data.date_label} — {len(data.top)} trends"
    ctx = {"d": data, "angle_names": dict(angle_names)}
    return subject, _ENV.get_template("digest.txt").render(**ctx), _ENV.get_template("digest.html").render(**ctx)


def _credentials(env: Mapping[str, str]) -> tuple[str, str, list[str]]:
    user, password, to = env.get("SMTP_USER"), env.get("SMTP_APP_PASSWORD"), env.get("ALERT_TO")
    if not (user and password and to):
        raise EmailError("SMTP_USER, SMTP_APP_PASSWORD and ALERT_TO must be set (or use --dry-run)")
    return user, password, [a.strip() for a in to.split(",") if a.strip()]


def send(subject: str, text: str, html: str, *, settings: dict, env: Mapping[str, str],
         smtp_factory: Callable[..., smtplib.SMTP] = smtplib.SMTP) -> None:
    """Send one email over STARTTLS, retrying once."""
    user, password, to = _credentials(env)
    cfg = settings["email"]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg["sender_name"], user))
    msg["To"] = ", ".join(to)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    error: Exception | None = None
    for attempt in (1, 2):
        try:
            with smtp_factory(cfg["smtp_host"], cfg["smtp_port"], timeout=30) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(user, password)
                smtp.send_message(msg)
            return
        except (smtplib.SMTPException, OSError) as exc:
            error = exc
            log.warning("email send attempt %d failed: %s", attempt, type(exc).__name__)
    raise EmailError(f"email send failed: {type(error).__name__}") from error


def write_preview(subject: str, html: str, *, out_dir: Path, kind: str, slug: str, now: datetime) -> Path:
    """Dry-run delivery: write the HTML to out/ and print the subject."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{now.strftime('%Y%m%dT%H%M%SZ')}-{kind}-{slugify(slug)}.html"
    path.write_text(html, encoding="utf-8")
    print(f"[dry-run] {subject} -> {path}")
    return path
