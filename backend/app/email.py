"""Pluggable email sending.

There is no live SMTP infrastructure for this pilot yet, so the default
sender just logs the verification link (ConsoleEmailSender). A real
SMTPEmailSender is fully implemented against Gmail SMTP + a Jinja2 template
and can be selected with EMAIL_BACKEND=smtp once credentials exist.
"""
from __future__ import annotations

import logging
import smtplib
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import settings

logger = logging.getLogger("proctorai.email")

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


class EmailSender(ABC):
    @abstractmethod
    async def send_verification_email(self, *, to_address: str, full_name: str, verification_link: str) -> None:
        raise NotImplementedError


class ConsoleEmailSender(EmailSender):
    """Default sender for Phase 2b: logs the link instead of emailing it."""

    async def send_verification_email(self, *, to_address: str, full_name: str, verification_link: str) -> None:
        logger.info(
            "verification email (console backend) to=%s name=%s link=%s",
            to_address,
            full_name,
            verification_link,
        )


class SMTPEmailSender(EmailSender):
    """Real Gmail SMTP sender, selected via EMAIL_BACKEND=smtp.

    Runs synchronously under the hood (smtplib has no asyncio API); callers
    are expected to await this from an async context where blocking briefly
    on outbound mail is acceptable, matching the small scale of this pilot.
    """

    async def send_verification_email(self, *, to_address: str, full_name: str, verification_link: str) -> None:
        template = _jinja_env.get_template("verify_email.html")
        html_body = template.render(full_name=full_name, verification_link=verification_link)

        message = MIMEMultipart("alternative")
        message["Subject"] = "Verify your ProctorAI account"
        message["From"] = settings.smtp_from_address
        message["To"] = to_address
        message.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
            server.sendmail(settings.smtp_from_address, [to_address], message.as_string())


def get_email_sender() -> EmailSender:
    if settings.email_backend == "smtp":
        return SMTPEmailSender()
    return ConsoleEmailSender()
