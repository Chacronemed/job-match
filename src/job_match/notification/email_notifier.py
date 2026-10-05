"""SMTP email notifier. Reads credentials from env; never logs them."""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from job_match.notification.digest import DigestData, render_html, render_text

logger = logging.getLogger(__name__)

_REQUIRED = ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "DIGEST_TO")


class SmtpConfigError(ValueError):
    pass


class EmailNotifier:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        recipient: str,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._recipient = recipient

    @classmethod
    def from_env(cls) -> EmailNotifier:
        missing = [k for k in _REQUIRED if not os.environ.get(k)]
        if missing:
            raise SmtpConfigError(f"Missing env vars: {', '.join(missing)}")
        return cls(
            host=os.environ["SMTP_HOST"],
            port=int(os.environ.get("SMTP_PORT", "465")),
            user=os.environ["SMTP_USER"],
            password=os.environ["SMTP_PASSWORD"],
            recipient=os.environ["DIGEST_TO"],
        )

    def send(self, data: DigestData) -> bool:
        total = len(data.strong) + len(data.eligible)
        subject = (
            f"[job-match] {total} new job{'s' if total != 1 else ''} "
            f"({len(data.strong)} strong)"
        )
        if data.leads:
            n_leads = len(data.leads)
            subject += f", {n_leads} funding lead{'s' if n_leads != 1 else ''}"
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._user
        msg["To"] = self._recipient
        msg.attach(MIMEText(render_text(data), "plain", "utf-8"))
        msg.attach(MIMEText(render_html(data), "html", "utf-8"))

        try:
            if self._port == 465:
                with smtplib.SMTP_SSL(self._host, self._port) as smtp:
                    smtp.login(self._user, self._password)
                    smtp.sendmail(self._user, [self._recipient], msg.as_bytes())
            else:
                with smtplib.SMTP(self._host, self._port) as smtp:
                    smtp.starttls()
                    smtp.login(self._user, self._password)
                    smtp.sendmail(self._user, [self._recipient], msg.as_bytes())
            logger.info("digest sent (%d jobs, %d leads)", total, len(data.leads))
            return True
        except Exception as exc:
            logger.error("digest send failed: %s", exc)
            return False
