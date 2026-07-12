from __future__ import annotations

from typing import Protocol

from estate_sale_finder.db.models import DetectionORM
from estate_sale_finder.watchlists import WatchlistProfile


class NotificationProvider(Protocol):
    def send_digest(
        self,
        profile: WatchlistProfile,
        recipient: str,
        detections: list[DetectionORM],
    ) -> None: ...

    def send_failure(self, subject: str, body: str) -> None: ...
