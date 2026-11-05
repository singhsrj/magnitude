"""Turns a Neon (or any Postgres) connection string into what SQLAlchemy + asyncpg need.

Stdlib only on purpose, so it is easy to test. Neon specifics handled here:
  * `postgres://` / `postgresql://` -> `postgresql+asyncpg://`
  * `sslmode=` and `channel_binding=` are libpq options that asyncpg rejects; they are
    stripped and TLS is turned on through connect_args instead.
  * The `-pooler` hostname is PgBouncer in transaction mode, which can't use asyncpg's
    prepared-statement cache, so the cache is disabled and statement names are unique.
"""
from __future__ import annotations

import ssl
import uuid
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_LIBPQ_ONLY = {"sslmode", "channel_binding", "options", "sslrootcert", "sslcert", "sslkey"}
_TLS_MODES = {"require", "verify-ca", "verify-full"}


def prepare_database_url(raw: str) -> tuple[str, dict[str, Any]]:
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]

    parts = urlsplit(raw)
    if parts.scheme not in ("postgresql", "postgresql+asyncpg"):
        return raw, {}  # sqlite (tests) and anything else pass through untouched

    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    sslmode = query.get("sslmode")
    for key in _LIBPQ_ONLY:
        query.pop(key, None)

    host = parts.hostname or ""
    connect_args: dict[str, Any] = {"timeout": 15, "command_timeout": 30}

    # Neon always requires TLS even when the string omits sslmode.
    if sslmode in _TLS_MODES or (sslmode is None and host.endswith(".neon.tech")):
        connect_args["ssl"] = ssl.create_default_context()

    if "-pooler" in host:
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_cache_size"] = 0
        connect_args["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid.uuid4()}__"

    url = urlunsplit(("postgresql+asyncpg", parts.netloc, parts.path, urlencode(query), ""))
    return url, connect_args
