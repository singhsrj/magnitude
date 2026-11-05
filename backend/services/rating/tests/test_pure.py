"""Tests for the dependency-free modules. Run with only the standard library:
    PYTHONPATH=services/rating:packages/engine python3 -m unittest discover -s services/rating/tests -p "test_pure.py"
"""
import ssl
import unittest
from datetime import date

from app.dburl import prepare_database_url
from app.rules import LATENCY_SLACK_MS, MIN_TIME_MS, effective_time_ms, local_date_ok, timed_out

NEON_POOLED = "postgresql://neondb_owner:pw@ep-cool-123-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
NEON_DIRECT = "postgresql://neondb_owner:pw@ep-cool-123.us-east-2.aws.neon.tech/neondb?sslmode=require"


class DbUrl(unittest.TestCase):
    def test_pooled_neon_url(self):
        url, args = prepare_database_url(NEON_POOLED)
        self.assertTrue(url.startswith("postgresql+asyncpg://neondb_owner:pw@ep-cool-123-pooler."))
        self.assertNotIn("sslmode", url)
        self.assertNotIn("channel_binding", url)
        self.assertIsInstance(args["ssl"], ssl.SSLContext)
        self.assertEqual(args["statement_cache_size"], 0)
        self.assertEqual(args["prepared_statement_cache_size"], 0)
        self.assertNotEqual(args["prepared_statement_name_func"](), args["prepared_statement_name_func"]())

    def test_direct_neon_url_keeps_prepared_statements(self):
        url, args = prepare_database_url(NEON_DIRECT)
        self.assertIn("ssl", args)
        self.assertNotIn("statement_cache_size", args)

    def test_heroku_style_scheme(self):
        url, _ = prepare_database_url("postgres://u:p@db.example.com:5432/app")
        self.assertTrue(url.startswith("postgresql+asyncpg://"))

    def test_neon_host_gets_tls_even_without_sslmode(self):
        _, args = prepare_database_url("postgresql://u:p@ep-x.eu-central-1.aws.neon.tech/db")
        self.assertIn("ssl", args)

    def test_local_postgres_has_no_tls(self):
        _, args = prepare_database_url("postgresql://postgres:postgres@postgres:5432/magnitude")
        self.assertNotIn("ssl", args)

    def test_other_query_params_survive(self):
        url, _ = prepare_database_url("postgresql://u:p@h/db?sslmode=require&application_name=magnitude")
        self.assertIn("application_name=magnitude", url)

    def test_sqlite_passes_through(self):
        self.assertEqual(prepare_database_url("sqlite+aiosqlite://"), ("sqlite+aiosqlite://", {}))


class Rules(unittest.TestCase):
    def test_client_time_is_used_when_plausible(self):
        self.assertEqual(effective_time_ms(1500, 2500), 1500)
        self.assertEqual(effective_time_ms(1500, None), 1500)

    def test_client_cannot_claim_a_much_faster_time_than_the_server_saw(self):
        self.assertEqual(effective_time_ms(200, 7000), 7000 - LATENCY_SLACK_MS)

    def test_floor_and_ceiling(self):
        self.assertEqual(effective_time_ms(0, None), MIN_TIME_MS)
        self.assertEqual(effective_time_ms(99_999, None), 8000)
        self.assertEqual(effective_time_ms(500, 60_000), 8000)

    def test_timeouts(self):
        self.assertTrue(timed_out(None, 100))
        self.assertTrue(timed_out("left", 8000 + LATENCY_SLACK_MS + 1))
        self.assertFalse(timed_out("left", 5000))
        self.assertFalse(timed_out("right", None))

    def test_local_date_window(self):
        today = date(2026, 10, 28)
        self.assertTrue(local_date_ok(date(2026, 10, 27), today))
        self.assertTrue(local_date_ok(date(2026, 10, 29), today))
        self.assertFalse(local_date_ok(date(2026, 10, 30), today))
        self.assertFalse(local_date_ok(date(2026, 10, 26), today))


if __name__ == "__main__":
    unittest.main()
