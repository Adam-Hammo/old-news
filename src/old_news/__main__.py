import argparse
import asyncio
import sys
from pathlib import Path

from old_news.config import Settings, get_settings


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
    """The worker owns its engine, exactly as the API owns one in its lifespan.

    `procrastinate worker` on its own never calls db.configure(), so every task
    that touches Postgres would raise on its first statement.
    """
    from old_news import db, observability
    from old_news.tasks import app as queue_app

    observability.configure(
        settings.telemetry, environment=settings.environment, component="worker"
    )
    db.configure(settings.database)
    try:
        async with queue_app.open_async():
            await queue_app.run_worker_async()
    finally:
        await db.dispose()


def serve(settings: Settings) -> None:
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
    from old_news import db
    from old_news.fetch import Fetcher
    from old_news.subscriptions import service

    db.configure(settings.database)
    fetcher = Fetcher(settings.http)
    try:
        result = await service.import_opml(data, fetcher)
    finally:
        await fetcher.aclose()
        await db.dispose()

    print(f"added {result.added}, already subscribed {result.already_present}")
    for url in result.undiscoverable:
        print(f"  no feed found: {url}", file=sys.stderr)
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

    args = parser.parse_args()
    settings = get_settings()

    if args.command == "admin-password":
        print(_hash_admin_password())
        return

    if args.command == "worker":
        asyncio.run(_worker(settings))
        return

    if args.command in (None, "serve"):
        serve(settings)
        return

    if args.opml_command == "import":
        # Read before the loop starts: blocking I/O inside it stalls everything.
        # "-" is how the file reaches a read-only container over ssh.
        data = sys.stdin.buffer.read() if args.path == "-" else Path(args.path).read_bytes()
        raise SystemExit(asyncio.run(_import_opml(data, settings)))
    raise SystemExit(asyncio.run(_export_opml(settings)))


if __name__ == "__main__":
    main()
