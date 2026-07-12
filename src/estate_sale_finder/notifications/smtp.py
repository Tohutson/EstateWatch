from __future__ import annotations

import mimetypes
import smtplib
from collections import defaultdict
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from estate_sale_finder.config import Settings
from estate_sale_finder.db.models import DetectionORM, SaleORM
from estate_sale_finder.domain.models import CAMERA_TARGET_CATEGORIES
from estate_sale_finder.watchlists import WatchlistProfile


@dataclass(frozen=True)
class RenderedDigest:
    subject: str
    html: str
    text: str
    cid_paths: dict[str, Path]


class SmtpNotifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.env = Environment(
            loader=PackageLoader("estate_sale_finder.notifications", "templates"),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def send_digest(
        self,
        profile: WatchlistProfile,
        recipient: str,
        detections: list[DetectionORM],
    ) -> None:
        rendered = render_digest(self.env, profile, detections)
        self._send(recipient, rendered.subject, rendered.text, rendered.html, rendered.cid_paths)

    def send_failure(self, subject: str, body: str) -> None:
        if not self.settings.email_to:
            raise ValueError("EMAIL_TO is required for failure notifications")
        for recipient in self.settings.email_to:
            self._send(recipient, subject, body, f"<pre>{body}</pre>", {})

    def send_test(self, recipient: str) -> None:
        self._send(
            recipient,
            "EstateWatch test email",
            "SMTP configuration works.",
            "<pre>SMTP configuration works.</pre>",
            {},
        )

    def _send(
        self,
        recipient: str,
        subject: str,
        text: str,
        html: str,
        cid_paths: dict[str, Path],
    ) -> None:
        if not self.settings.email_from or not self.settings.smtp_host:
            raise ValueError("SMTP settings are incomplete")
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.settings.email_from
        message["To"] = recipient
        message.set_content(text)
        message.add_alternative(html, subtype="html")
        payload = message.get_payload()
        if not isinstance(payload, list):
            raise TypeError("Expected multipart email payload")
        html_part: Any = payload[-1]
        for cid, path in cid_paths.items():
            mime, _ = mimetypes.guess_type(path)
            maintype, subtype = (mime or "image/jpeg").split("/", 1)
            html_part.add_related(
                path.read_bytes(), maintype=maintype, subtype=subtype, cid=f"<{cid}>"
            )
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=30) as smtp:
            if self.settings.smtp_use_tls:
                smtp.starttls()
            if self.settings.smtp_username:
                smtp.login(self.settings.smtp_username, self.settings.smtp_password or "")
            smtp.send_message(message)


def render_digest(
    env: Environment,
    profile: WatchlistProfile,
    detections: list[DetectionORM],
) -> RenderedDigest:
    grouped: dict[SaleORM, list[tuple[DetectionORM, str | None]]] = defaultdict(list)
    cid_paths: dict[str, Path] = {}
    for detection in detections:
        sale = detection.image.sale
        cid: str | None = None
        if detection.image.local_thumbnail_path:
            path = Path(detection.image.local_thumbnail_path)
            if path.is_file():
                cid = make_msgid(domain="estate-sale-finder.local")[1:-1]
                cid_paths[cid] = path
        grouped[sale].append((detection, cid))
    context = {
        "camera_categories": CAMERA_TARGET_CATEGORIES,
        "groups": list(grouped.items()),
        "count": len(detections),
        "watchlist": profile,
        "target_categories": sorted(profile.targets),
    }
    if detections:
        subject = (
            f"EstateWatch: {profile.name} - {len(detections)} "
            f"new match{'es' if len(detections) != 1 else ''}"
        )
    else:
        subject = f"EstateWatch: {profile.name} - no new matches"
    html = env.get_template("digest.html.j2").render(**context)
    text = env.get_template("digest.txt.j2").render(**context)
    return RenderedDigest(subject=subject, html=html, text=text, cid_paths=cid_paths)
