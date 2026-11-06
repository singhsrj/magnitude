"""Small helpers shared by the test modules."""

# The test database engine, set by an autouse fixture in conftest.py (tickets are backdated through it).
ENGINE: dict = {}


async def signup(client):
    r = await client.post("/v1/players")
    assert r.status_code == 201
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}, body["playerId"]
