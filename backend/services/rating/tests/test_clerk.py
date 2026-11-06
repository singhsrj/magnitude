"""Clerk sign-in: session tokens authenticate a player, and /v1/players/link joins an account to a device's progress.

Tokens here are real RS256 JWTs signed with a throwaway key; the app is pointed at a fake JWKS (no network)."""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.clerk import ClerkVerifier, issuer_from_publishable_key
from tests.helpers import signup
from tests.test_sync import Browser, assert_profile_matches, sync, ticket

ISSUER = "https://clerk.example.test"
ORIGIN = "https://magnitude.example.test"
KID = "ins_test_key"


def new_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


KEY = new_key()


def jwks_for(key, kid=KID) -> dict:
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    return {"keys": [{**jwk, "kid": kid, "use": "sig", "alg": "RS256"}]}


def mint(sub="user_abc", *, key=None, kid=KID, iss=ISSUER, azp=ORIGIN, exp_in=60, nbf_in=-5, alg="RS256") -> str:
    now = int(time.time())
    claims = {"sub": sub, "iss": iss, "iat": now, "nbf": now + nbf_in, "exp": now + exp_in}
    if azp is not None:
        claims["azp"] = azp
    return jwt.encode(claims, key or KEY, algorithm=alg, headers={"kid": kid})


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def verifier(fetches: list | None = None, key=KEY) -> ClerkVerifier:
    async def fetch(url):
        if fetches is not None:
            fetches.append(url)
        return jwks_for(key)

    return ClerkVerifier(ISSUER, origins=[ORIGIN], fetch=fetch)


@pytest.fixture
async def acct(make_client):
    """A client whose server accepts Clerk tokens for ISSUER."""
    return await make_client(clerk=verifier())


async def link(client, token, **body):
    return await client.post("/v1/players/link", headers=bearer(token), json=body)


# ------------------------------------------------------------------ link
async def test_new_account_gets_a_player_and_can_use_the_api(acct):
    r = await link(acct, mint("user_new"))
    assert r.status_code == 200 and r.json()["status"] == "created"
    p = await acct.get("/v1/profile", headers=bearer(mint("user_new")))
    assert p.status_code == 200 and p.json()["rounds"] == 0


async def test_link_attaches_the_device_player_and_both_credentials_work(acct):
    headers, player_id = await signup(acct)
    b = Browser(await ticket(acct, headers))
    assert (await sync(acct, headers, b.play(12))).status_code == 200

    anon_token = headers["Authorization"].split()[1]
    r = await link(acct, mint("user_a"), anonymousToken=anon_token)
    assert r.json() == {"playerId": player_id, "status": "linked"}

    # signed in: the same progress, through the account
    via_account = (await acct.get("/v1/profile", headers=bearer(mint("user_a")))).json()
    assert_profile_matches(via_account, b)
    # the device token still works (signed-out play, and syncs already queued with it)
    via_device = (await acct.get("/v1/profile", headers=headers)).json()
    assert_profile_matches(via_device, b)


async def test_syncing_through_the_account_updates_the_same_player(acct):
    await link(acct, mint("user_s"))
    h = bearer(mint("user_s"))
    b = Browser(await ticket(acct, h))
    r = await sync(acct, h, b.play(10))
    assert r.status_code == 200 and not r.json()["rejected"]
    assert_profile_matches(r.json()["profile"], b)


async def test_link_is_idempotent_and_never_merges_another_device(acct):
    first = (await link(acct, mint("user_i"))).json()
    assert first["status"] == "created"
    other_headers, _ = await signup(acct)
    again = (await link(acct, mint("user_i"), anonymousToken=other_headers["Authorization"].split()[1])).json()
    assert again == {"playerId": first["playerId"], "status": "existing"}
    # the other device's player was left alone (still anonymous, still usable)
    assert (await acct.get("/v1/profile", headers=other_headers)).status_code == 200


async def test_a_device_player_linked_to_one_account_cannot_be_taken_by_another(acct):
    headers, _ = await signup(acct)
    anon = headers["Authorization"].split()[1]
    assert (await link(acct, mint("user_one"), anonymousToken=anon)).json()["status"] == "linked"
    r = await link(acct, mint("user_two"), anonymousToken=anon)
    assert r.status_code == 409 and r.json()["detail"] == "device_account_linked_elsewhere"
    # without the device token, the second account just gets its own player
    assert (await link(acct, mint("user_two"))).json()["status"] == "created"


async def test_unknown_anonymous_token_falls_back_to_a_new_player(acct):
    r = await link(acct, mint("user_u"), anonymousToken="not-a-real-token")
    assert r.status_code == 200 and r.json()["status"] == "created"


async def test_link_can_seed_a_new_player_with_an_old_profile(acct):
    profile = {
        "rating": 1234.0, "peak": 1300.0, "streak": 2, "bestStreak": 5, "rounds": 0,
        "skills": {"multiplication": 1200.0, "percentages": 1200.0, "fractions": 1200.0, "powers": 1200.0},
        "history": [], "days": {}, "daily": {},
    }
    r = await link(acct, mint("user_imp"), **{"import": profile})
    assert r.status_code == 200 and r.json()["status"] == "created"
    got = (await acct.get("/v1/profile", headers=bearer(mint("user_imp")))).json()
    assert got["rating"] == 1234.0 and got["peak"] == 1300.0


# ------------------------------------------------------------------ rejecting tokens
@pytest.mark.parametrize(
    "token",
    [
        pytest.param(lambda: mint(exp_in=-120), id="expired"),
        pytest.param(lambda: mint(iss="https://evil.example.test"), id="wrong-issuer"),
        pytest.param(lambda: mint(key=new_key()), id="signed-with-another-key"),
        pytest.param(lambda: mint(kid="ins_other"), id="unknown-key-id"),
        pytest.param(lambda: mint(azp="https://evil.example.test"), id="other-site"),
        pytest.param(lambda: mint(nbf_in=3600), id="not-yet-valid"),
        pytest.param(lambda: "eyJhbGciOiJub25lIn0.eyJzdWIiOiJ1c2VyX3gifQ.", id="alg-none"),
        pytest.param(lambda: "eyJ.garbage.garbage", id="garbage"),
    ],
)
async def test_bad_tokens_are_401(acct, token):
    t = token()
    assert (await acct.get("/v1/profile", headers=bearer(t))).status_code == 401
    assert (await link(acct, t)).status_code == 401


async def test_a_token_without_azp_is_accepted(acct):
    # Clerk omits azp for some session types (e.g. server-minted); origin is only enforced when present.
    assert (await link(acct, mint("user_noazp", azp=None))).status_code == 200


async def test_valid_token_for_an_account_that_was_never_linked_is_401(acct):
    r = await acct.get("/v1/profile", headers=bearer(mint("user_nobody")))
    assert r.status_code == 401 and r.json()["detail"] == "account not linked"


async def test_clerk_tokens_are_refused_when_the_server_has_no_clerk_config(client):
    r = await client.get("/v1/profile", headers=bearer(mint()))
    assert r.status_code == 401 and "isn't enabled" in r.json()["detail"]
    # and device tokens are unaffected
    headers, _ = await signup(client)
    assert (await client.get("/v1/profile", headers=headers)).status_code == 200


async def test_device_tokens_never_reach_the_jwt_path(acct):
    headers, _ = await signup(acct)
    assert (await acct.get("/v1/profile", headers=headers)).status_code == 200
    assert (await acct.get("/v1/profile", headers=bearer("nope"))).status_code == 401


# ------------------------------------------------------------------ the verifier itself
async def test_signing_keys_are_cached_and_refetched_after_rotation():
    fetches: list = []
    v = verifier(fetches)
    assert await v.verify(mint("user_c")) == "user_c"
    assert await v.verify(mint("user_c")) == "user_c"
    assert len(fetches) == 1, "keys are cached"

    rotated = new_key()
    v._fetch = lambda url: _async(jwks_for(rotated, "ins_rotated"))  # Clerk published a new key
    v._refetch_after = 0
    assert await v.verify(mint("user_c", key=rotated, kid="ins_rotated")) == "user_c"


async def _async(value):
    return value


async def test_an_unreachable_key_server_is_a_401_not_a_500(make_client):
    async def broken(url):
        raise RuntimeError("down")

    c = await make_client(clerk=ClerkVerifier(ISSUER, origins=[ORIGIN], fetch=broken))
    r = await c.get("/v1/profile", headers=bearer(mint()))
    assert r.status_code == 401


def test_issuer_is_derived_from_the_publishable_key():
    import base64

    key = "pk_test_" + base64.b64encode(b"clerk.example.accounts.dev$").decode().rstrip("=")
    assert issuer_from_publishable_key(key) == "https://clerk.example.accounts.dev"
    with pytest.raises(ValueError):
        issuer_from_publishable_key("pk_test_!!!")
    with pytest.raises(ValueError):
        issuer_from_publishable_key("nonsense")


async def test_settings_build_a_verifier_from_the_publishable_key(make_client):
    import base64

    pk = "pk_test_" + base64.b64encode(b"clerk.example.accounts.dev$").decode().rstrip("=")
    c = await make_client(clerk_publishable_key=pk)
    assert c._transport.app.state.clerk.issuer == "https://clerk.example.accounts.dev"
