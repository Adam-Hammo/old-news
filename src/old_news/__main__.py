import argparse
import asyncio
import signal
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from old_news.config import Settings, get_settings

if TYPE_CHECKING:
    from procrastinate import App


def _hash_admin_password() -> str:
    """Prompted, never an argument — a password in argv is a password in `ps`."""
    from getpass import getpass

    from old_news import passwords

    password = getpass("admin password: ")
    if password != getpass("repeat: "):
        raise SystemExit("passwords did not match")
    if not password:
        raise SystemExit("password must not be empty")
    return f"OLD_NEWS_ADMIN__PASSWORD_HASH={passwords.hash_password(password)}"


async def _worker(settings: Settings) -> None:
    """The worker owns its engine, and one worker per queue owns its own slots.

    `procrastinate worker` alone never calls `db.configure()`, so every task touching
    Postgres would raise on its first statement.
    """
    from old_news import db, fetch, observability
    from old_news.tasks import app as queue_app

    observability.configure(
        settings.telemetry, environment=settings.environment, component="worker"
    )
    db.configure(settings.database)
    fetch.configure(settings.http)
    try:
        async with queue_app.open_async():
            await _run_workers(queue_app, settings, _stop_on_signal())
    finally:
        await fetch.dispose()
        await db.dispose()


def _stop_on_signal() -> asyncio.Event:
    """One handler for the whole process: `add_signal_handler` replaces, it does not add."""
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signalled in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signalled, stopping.set)
    return stopping


async def _run_workers(queue_app: App, settings: Settings, stopping: asyncio.Event) -> None:
    """Run one worker per queue until `stopping` is set.

    Cancellation is how procrastinate is asked to wind down, so `CancelledError` is the
    expected reply; anything else is re-raised once every worker has stopped.
    """
    workers = [
        asyncio.create_task(
            queue_app.run_worker_async(
                queues=[queue],
                concurrency=concurrency,
                name=f"worker-{queue}",
                install_signal_handlers=False,
            ),
            name=f"worker-{queue}",
        )
        for queue, concurrency in sorted(settings.worker.concurrency.items())
    ]
    stopped = asyncio.create_task(stopping.wait())
    try:
        await asyncio.wait([*workers, stopped], return_when=asyncio.FIRST_COMPLETED)
    finally:
        stopped.cancel()
        for worker in workers:
            worker.cancel()
        outcomes = await asyncio.gather(*workers, return_exceptions=True)

    for outcome in outcomes:
        if isinstance(outcome, BaseException) and not isinstance(outcome, asyncio.CancelledError):
            raise outcome


def _serve(settings: Settings) -> None:
    import uvicorn

    import old_news

    package = Path(old_news.__file__).resolve().parent

    uvicorn.run(
        "old_news.api.app:create_app",
        factory=True,
        host=settings.api.host,
        port=settings.api.port,
        proxy_headers=True,
        forwarded_allow_ips=settings.api.forwarded_allow_ips,
        reload=settings.api.reload,
        reload_dirs=[str(package.parent)] if settings.api.reload else None,
    )


async def _import_opml(data: bytes, settings: Settings) -> int:
    from old_news import db, fetch
    from old_news.subscriptions import service

    db.configure(settings.database)
    fetch.configure(settings.http)
    try:
        result = await service.import_opml(data, fetch.client())
    finally:
        await fetch.dispose()
        await db.dispose()

    print(f"added {result.added}, already subscribed {result.already_present}")
    for url in result.undiscoverable:
        print(f"  no feed found: {url}", file=sys.stderr)
    for url in result.unfetchable:
        print(f"  not a fetchable URL, skipped: {url}", file=sys.stderr)
    return 1 if result.undiscoverable else 0


async def _export_opml(settings: Settings) -> int:
    from old_news import db
    from old_news.subscriptions import service

    db.configure(settings.database)
    try:
        sys.stdout.buffer.write(await service.export_opml())
    finally:
        await db.dispose()
    return 0


async def _build_issue(settings: Settings) -> int:
    from old_news import db, kindle

    db.configure(settings.database)
    try:
        built = await kindle.build_issue(settings.kindle)
    finally:
        await db.dispose()

    if built.issue_id is None:
        print("nothing due; no issue built")
        return 0
    print(f"issue {built.issue_id}: {built.articles} articles, {built.byte_size} bytes")
    if built.error:
        print(f"  not delivered: {built.error}", file=sys.stderr)
        return 1
    print("  sent" if built.sent else "  built; delivery is not configured")
    return 0


async def _resend_issue(issue_id: str, settings: Settings) -> int:
    from old_news import db, kindle

    db.configure(settings.database)
    try:
        error = await kindle.resend(uuid.UUID(issue_id), settings.kindle)
    finally:
        await db.dispose()

    if error:
        print(f"not delivered: {error}", file=sys.stderr)
        return 1
    print("sent")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="old-news")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve", help="run the API")
    commands.add_parser("worker", help="run the job worker")
    commands.add_parser("admin-password", help="hash a password for the admin UI")

    opml = commands.add_parser("opml", help="import or export subscriptions").add_subparsers(
        dest="opml_command", required=True
    )
    importer = opml.add_parser("import", help="subscribe to everything in an OPML file")
    importer.add_argument("path", help="an OPML file, or - to read stdin")
    opml.add_parser("export", help="write subscriptions as OPML to stdout")

    issues = commands.add_parser("kindle", help="build or resend a periodical").add_subparsers(
        dest="kindle_command", required=True
    )
    issues.add_parser("build", help="build an issue from whatever is due, and send it")
    resend = issues.add_parser("resend", help="post an issue's stored bytes again")
    resend.add_argument("issue_id", help="the id of an issue already built")

    args = parser.parse_args()
    settings = get_settings()

    if args.command == "admin-password":
        print(_hash_admin_password())
        return

    if args.command == "worker":
        asyncio.run(_worker(settings))
        return

    if args.command in (None, "serve"):
        _serve(settings)
        return

    if args.command == "kindle":
        if args.kindle_command == "build":
            raise SystemExit(asyncio.run(_build_issue(settings)))
        raise SystemExit(asyncio.run(_resend_issue(args.issue_id, settings)))

    if args.opml_command == "import":
        # Read before the loop starts: blocking I/O inside it stalls everything.
        data = sys.stdin.buffer.read() if args.path == "-" else Path(args.path).read_bytes()
        raise SystemExit(asyncio.run(_import_opml(data, settings)))
    raise SystemExit(asyncio.run(_export_opml(settings)))


if __name__ == "__main__":
    main()
