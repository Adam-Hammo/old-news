"""Mailing a built issue to Send to Kindle, which is the only way in that a Kindle has."""

import asyncio
import datetime
import smtplib
import ssl
from email.message import EmailMessage

from old_news.config import KindleSettings

MAINTYPE, SUBTYPE = "application", "epub+zip"

# Amazon names the document from the filename and rejects anything it does not read
# as a book, so the suffix is load-bearing.
SUFFIX = ".epub"

# Implicit TLS. Everything else negotiates up from plaintext.
IMPLICIT_TLS_PORT = 465


class NotDelivered(RuntimeError):
    """The book did not reach Amazon. A bounce, if there is one, arrives separately."""


def filename(at: datetime.datetime) -> str:
    return f"old-news-{at.date().isoformat()}{SUFFIX}"


def _message(body: bytes, *, subject: str, name: str, settings: KindleSettings) -> EmailMessage:
    message = EmailMessage()
    message["From"] = settings.sender
    message["To"] = settings.address
    message["Subject"] = subject
    message.set_content("Built by old-news.")
    message.add_attachment(body, maintype=MAINTYPE, subtype=SUBTYPE, filename=name)
    return message


def _post(message: EmailMessage, settings: KindleSettings) -> None:
    context = ssl.create_default_context()
    timeout = settings.smtp_timeout_seconds
    if settings.smtp_port == IMPLICIT_TLS_PORT:
        server = smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=timeout, context=context
        )
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=timeout)
        server.starttls(context=context)
    with server:
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password.get_secret_value())
        server.send_message(message)


async def send(
    body: bytes, *, subject: str, at: datetime.datetime, settings: KindleSettings
) -> None:
    """Post one book. Blocking, so it runs off the loop the worker is serving on."""
    message = _message(body, subject=subject, name=filename(at), settings=settings)
    try:
        await asyncio.to_thread(_post, message, settings)
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        raise NotDelivered(str(exc)) from exc
