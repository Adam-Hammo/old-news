import uvicorn

from old_news.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "old_news.api.app:create_app",
        factory=True,
        host=settings.api.host,
        port=settings.api.port,
    )


if __name__ == "__main__":
    main()
