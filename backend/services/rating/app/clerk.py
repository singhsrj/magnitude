"""Verifies Clerk session tokens (RS256 JWTs) so a signed-in browser can authenticate as its account.

Clerk signs each session token with a key published at `<issuer>/.well-known/jwks.json`. We never need Clerk's secret
key for this: the token's signature, issuer, expiry and authorized party (the page's origin) are enough.

The issuer is derived from the *publishable* key (a public value): after `pk_test_` / `pk_live_` it is the base64 of the
Clerk frontend domain plus a trailing `$`.
"""
from __future__ import annotations

import base64
import logging
import re
import time
from typing import Awaitable, Callable

import httpx
import jwt

log = logging.getLogger("clerk")


class ClerkAuthError(Exception):
    """The token isn't acceptable. The message is safe to show to the caller."""


def issuer_from_publishable_key(key: str) -> str:
    try:
        encoded = key.split("_", 2)[2]
        domain = base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode("ascii").rstrip("$")
    except Exception as exc:  # noqa: BLE001
        raise ValueError("CLERK_PUBLISHABLE_KEY isn't a valid Clerk publishable key") from exc
    if not domain or "/" in domain or " " in domain:
        raise ValueError("CLERK_PUBLISHABLE_KEY doesn't contain a Clerk domain")
    return f"https://{domain}"


def looks_like_jwt(token: str) -> bool:
    """Our own tokens are url-safe random strings without dots; JWTs are three dot-separated base64url parts."""
    return token.count(".") == 2 and token.startswith("eyJ")


JwksFetcher = Callable[[str], Awaitable[dict]]


async def _fetch_jwks(url: str) -> dict:
    async with httpx.AsyncClient(timeout=5) as client:
        res = await client.get(url)
        res.raise_for_status()
        return res.json()


class ClerkVerifier:
    def __init__(
        self,
        issuer: str,
        *,
        jwks_url: str | None = None,
        origins: list[str] | None = None,
        origin_regex: str | None = None,
        leeway_seconds: int = 10,
        fetch: JwksFetcher | None = None,
        refetch_after_seconds: int = 60,
    ):
        self.issuer = issuer.rstrip("/")
        self.jwks_url = jwks_url or f"{self.issuer}/.well-known/jwks.json"
        self.origins = set(origins or [])
        self.origin_regex = re.compile(origin_regex) if origin_regex else None
        self.leeway = leeway_seconds
        self._fetch = fetch or _fetch_jwks
        self._keys: dict[str, object] = {}
        self._fetched_at = 0.0
        self._refetch_after = refetch_after_seconds

    async def _refresh(self) -> None:
        data = await self._fetch(self.jwks_url)
        self._keys = {k["kid"]: jwt.PyJWK(k).key for k in data.get("keys", []) if k.get("kid") and k.get("kty") == "RSA"}
        self._fetched_at = time.monotonic()

    async def _key_for(self, kid: str):
        if kid not in self._keys and time.monotonic() - self._fetched_at > self._refetch_after:
            # An unknown kid usually means Clerk rotated its keys; refetch, but not on every junk token.
            try:
                await self._refresh()
            except Exception as exc:  # noqa: BLE001
                log.warning("could not fetch Clerk's signing keys: %s", exc)
                raise ClerkAuthError("can't verify the sign-in right now") from None
        key = self._keys.get(kid)
        if key is None:
            raise ClerkAuthError("unknown signing key")
        return key

    def _origin_ok(self, azp: str) -> bool:
        return azp in self.origins or bool(self.origin_regex and self.origin_regex.match(azp))

    async def verify(self, token: str) -> str:
        """Returns the Clerk user id (`sub`), or raises ClerkAuthError."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise ClerkAuthError("malformed token") from None
        if header.get("alg") != "RS256" or not header.get("kid"):
            raise ClerkAuthError("unsupported token")
        key = await self._key_for(header["kid"])
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self.issuer,
                leeway=self.leeway,
                options={"require": ["exp", "iss", "sub"], "verify_aud": False},
            )
        except jwt.ExpiredSignatureError:
            raise ClerkAuthError("token expired") from None
        except jwt.PyJWTError:
            raise ClerkAuthError("invalid token") from None
        # `azp` is the origin the session token was issued to. Without this check a token minted for some other
        # site that also uses this Clerk application would be accepted here.
        azp = claims.get("azp")
        if azp and (self.origins or self.origin_regex) and not self._origin_ok(azp):
            raise ClerkAuthError("token was issued for a different site")
        sub = claims["sub"]
        if not isinstance(sub, str) or not sub:
            raise ClerkAuthError("invalid token")
        return sub
