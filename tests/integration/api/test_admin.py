from litestar.testing import AsyncTestClient

from old_news.config import Settings
from old_news.config.admin import DEVELOPMENT_PASSWORD


async def _login(client: AsyncTestClient, settings: Settings, password: str):
    return await client.post(
        f"{settings.admin.path}/login",
        data={"username": settings.admin.username, "password": password},
        follow_redirects=True,
    )


async def test_admin_requires_authentication(client: AsyncTestClient, settings: Settings):
    response = await client.get(f"{settings.admin.path}/", follow_redirects=False)

    assert response.status_code == 302
    assert "login" in response.headers["location"]


async def test_wrong_credentials_do_not_authenticate(client: AsyncTestClient, settings: Settings):
    await _login(client, settings, "not-the-password")

    listing = await client.get(f"{settings.admin.path}/feed/list", follow_redirects=False)

    assert listing.status_code == 302


async def test_login_reaches_a_model_list(client: AsyncTestClient, settings: Settings):
    await _login(client, settings, DEVELOPMENT_PASSWORD)

    listing = await client.get(f"{settings.admin.path}/feed/list")

    assert listing.status_code == 200
    assert "Feeds" in listing.text


async def test_a_non_ascii_username_is_rejected_not_a_500(
    client: AsyncTestClient, settings: Settings
):
    """compare_digest raises TypeError on non-ASCII str, which would 500 the login."""
    response = await client.post(
        f"{settings.admin.path}/login",
        data={"username": "admín", "password": DEVELOPMENT_PASSWORD},
        follow_redirects=True,
    )

    assert response.status_code < 500

    listing = await client.get(f"{settings.admin.path}/feed/list", follow_redirects=False)
    assert listing.status_code == 302


async def test_static_assets_are_served_through_the_mount(
    client: AsyncTestClient, settings: Settings
):
    """The page renders but has no CSS or JS if the mount gets path/root_path wrong:
    a nested Mount subtracts a prefix that `path` never carried."""
    for asset in ("css/tabler.min.css", "js/main.js"):
        response = await client.get(f"{settings.admin.path}/statics/{asset}")

        assert response.status_code == 200, asset
        assert response.content


async def test_generated_urls_keep_the_mount_prefix(client: AsyncTestClient, settings: Settings):
    response = await client.get(f"{settings.admin.path}/", follow_redirects=False)

    assert response.headers["location"].endswith(f"{settings.admin.path}/login")
