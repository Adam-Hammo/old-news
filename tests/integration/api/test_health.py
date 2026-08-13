from litestar.testing import AsyncTestClient


async def test_liveness(client: AsyncTestClient):
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_readiness_queries_through_the_pool(client: AsyncTestClient):
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_openapi_schema_is_served(client: AsyncTestClient):
    response = await client.get("/schema/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "old-news"
