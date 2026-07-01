from __future__ import annotations

import argparse
import logging
from pathlib import Path

from sqlalchemy import text

from estate_sale_finder.analysis.base import LocalPrefilter, VisionProvider
from estate_sale_finder.analysis.local_prefilter import DisabledPrefilter, OpenClipPrefilter
from estate_sale_finder.analysis.mock import MockVisionProvider
from estate_sale_finder.analysis.openai_vision import OpenAIVisionProvider
from estate_sale_finder.config import Settings, get_settings
from estate_sale_finder.db.migrations import upgrade_to_head
from estate_sale_finder.db.session import make_engine, make_session_factory, session_scope
from estate_sale_finder.images.downloader import ImageDownloader
from estate_sale_finder.locking import ProcessLock
from estate_sale_finder.logging_config import configure_logging
from estate_sale_finder.notifications.smtp import SmtpNotifier
from estate_sale_finder.pipeline import Pipeline, RunOptions
from estate_sale_finder.sources.estatesales_net import EstateSalesNetClient

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="estate-sale-finder")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--reanalyze", action="store_true")
    run.add_argument("--reanalyze-version-mismatch", action="store_true")
    run.add_argument("--sale-id")
    run.add_argument("--dry-run", action="store_true")
    sub.add_parser("doctor")
    sub.add_parser("migrate")
    sub.add_parser("test-email")
    inspect_sale = sub.add_parser("inspect-sale")
    inspect_sale.add_argument("sale_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.ensure_directories()
    if args.command == "migrate":
        upgrade_to_head(settings.resolved_database_url)
        return 0
    if args.command == "doctor":
        return doctor(settings)
    if args.command == "test-email":
        notifier = SmtpNotifier(settings)
        notifier.send_failure("Estate Sale Finder test email", "SMTP configuration works.")
        return 0
    if args.command == "inspect-sale":
        return inspect_sale(settings, args.sale_id)
    if args.command == "run":
        return run_once(settings, args)
    return 2


def run_once(settings: Settings, args: argparse.Namespace) -> int:
    lock_path = settings.locks_dir / "estate-sale-finder.lock"
    with ProcessLock(lock_path) as lock:
        if not lock.acquired:
            logger.info("run_skipped_lock_held", extra={"lock_path": str(lock_path)})
            return 0
        upgrade_to_head(settings.resolved_database_url)
        engine = make_engine(settings.resolved_database_url)
        factory = make_session_factory(engine)
        with session_scope(factory) as session:
            source = EstateSalesNetClient(settings)
            downloader = ImageDownloader(settings)
            pipeline = Pipeline(
                settings=settings,
                session=session,
                source=source,
                downloader=downloader,
                vision_provider=_vision_provider(settings),
                notifier=SmtpNotifier(settings) if settings.email_enabled else None,
                prefilter=_prefilter(settings),
            )
            pipeline.run(
                RunOptions(
                    reanalyze=args.reanalyze,
                    reanalyze_version_mismatch=args.reanalyze_version_mismatch,
                    sale_id=args.sale_id,
                    dry_run=args.dry_run,
                )
            )
    return 0


def doctor(settings: Settings) -> int:
    settings.ensure_directories()
    upgrade_to_head(settings.resolved_database_url)
    engine = make_engine(settings.resolved_database_url)
    with engine.connect() as conn:
        conn.execute(text("select 1"))
    for path in [
        settings.data_dir,
        settings.images_dir,
        settings.thumbnails_dir,
        settings.locks_dir,
    ]:
        _assert_writable(path)
    source = EstateSalesNetClient(settings)
    location = source.resolve_postal_code(settings.postal_code)
    if settings.analysis_provider == "openai" and not settings.vision_api_key:
        raise RuntimeError("OpenAI vision provider is selected but VISION_API_KEY is missing")
    if settings.email_enabled and (
        not settings.smtp_host or not settings.email_from or not settings.email_to
    ):
        raise RuntimeError("Email is enabled but SMTP settings are incomplete")
    logger.info("doctor_ok", extra={"postal_code": location.postal_code})
    return 0


def inspect_sale(settings: Settings, sale_id: str) -> int:
    source = EstateSalesNetClient(settings)
    sales = source.hydrate_sales([sale_id])
    if not sales:
        raise RuntimeError(f"Sale {sale_id} not found")
    sale = sales[0]
    print(f"{sale.title}\n{sale.url}")
    print(f"{sale.city}, {sale.state} {sale.postal_code}")
    print(f"{sale.picture_count} pictures")
    try:
        pictures = source.get_sale_pictures(sale)
    except Exception as exc:
        print(f"Gallery unavailable: {exc}")
    else:
        print(f"Gallery pictures: {len(pictures)}")
        for picture in pictures[:10]:
            print(picture.source_url)
    return 0


def _assert_writable(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    test = path / ".write-test"
    test.write_text("ok", encoding="utf-8")
    test.unlink()


def _vision_provider(settings: Settings) -> VisionProvider:
    if settings.analysis_provider == "openai":
        return OpenAIVisionProvider(settings)
    return MockVisionProvider()


def _prefilter(settings: Settings) -> LocalPrefilter:
    if settings.local_prefilter_enabled:
        return OpenClipPrefilter(settings.local_prefilter_model, settings.local_prefilter_threshold)
    return DisabledPrefilter()
