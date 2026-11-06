"""Tests for the dependency-free modules. Run with only the standard library:
    PYTHONPATH=services/rating:packages/engine python3 -m unittest discover -s services/rating/tests -p "test_pure.py"
"""
import ssl
import unittest
from datetime import date, datetime, timedelta, timezone

from app.dburl import prepare_database_url
from app.rules import (
    TIME_SLACK_PER_ROUND_MS, at_plausible, datetime_to_ms, local_date_matches, ms_to_datetime,
    session_time_plausible, start_skills_plausible,
)

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


class SyncRules(unittest.TestCase):
    NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)

    def test_ms_round_trip_is_exact(self):
        for ms in (0, 1, 1_730_000_000_123, 1_730_000_000_999, 1_762_430_400_001):
            self.assertEqual(datetime_to_ms(ms_to_datetime(ms)), ms)
        self.assertEqual(datetime_to_ms(ms_to_datetime(1_730_000_000_123).replace(tzinfo=None)), 1_730_000_000_123)  # naive = UTC

    def test_answers_cannot_be_from_the_future_or_before_the_ticket(self):
        self.assertTrue(at_plausible(self.NOW, self.NOW))
        self.assertTrue(at_plausible(self.NOW + timedelta(seconds=59), self.NOW))
        self.assertFalse(at_plausible(self.NOW + timedelta(seconds=61), self.NOW))
        issued = self.NOW - timedelta(hours=1)
        self.assertTrue(at_plausible(issued - timedelta(seconds=30), self.NOW, issued))
        self.assertFalse(at_plausible(issued - timedelta(minutes=5), self.NOW, issued))

    def test_local_day_is_within_a_day_of_the_utc_day_of_the_answer(self):
        at = datetime(2026, 11, 6, 0, 30, tzinfo=timezone.utc)
        self.assertTrue(local_date_matches(date(2026, 11, 5), at))
        self.assertTrue(local_date_matches(date(2026, 11, 7), at))
        self.assertFalse(local_date_matches(date(2026, 11, 8), at))
        self.assertFalse(local_date_matches(date(2026, 11, 1), at))

    def test_start_skills_must_be_close_to_the_servers(self):
        server = {"multiplication": 1200, "percentages": 1250, "fractions": 1100, "powers": 1300}
        self.assertTrue(start_skills_plausible(dict(server), server))
        self.assertTrue(start_skills_plausible({**server, "powers": 1590.5}, server))
        self.assertFalse(start_skills_plausible({**server, "powers": 1700}, server))
        self.assertFalse(start_skills_plausible({"multiplication": 1200}, server))  # missing skills
        self.assertFalse(start_skills_plausible({**server, "powers": "x"}, server))

    def test_think_times_cannot_outrun_the_clock(self):
        start = self.NOW
        at = start + timedelta(seconds=10)
        self.assertTrue(session_time_plausible(10_000, start, at, 5))
        self.assertTrue(session_time_plausible(10_000 + 5 * TIME_SLACK_PER_ROUND_MS, start, at, 5))
        self.assertFalse(session_time_plausible(10_001 + 5 * TIME_SLACK_PER_ROUND_MS, start, at, 5))
        self.assertFalse(session_time_plausible(40_000, start, at, 1))
