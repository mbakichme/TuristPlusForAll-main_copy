"""Offline prihvatni testovi: stvarni SQLite i stateful PG/HTTP zamene."""

import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from sqlalchemy import create_engine, text

from kurs_service import ensure_kurs_table, get_eur_rate


REQUESTED = "2026-10-04"
ACTUAL = "2026-10-02"
RATE = Decimal("117.12345678")


class OfflineHTTP:
    def __init__(self, payload=None, status=200, error=None):
        self.payload = payload if payload is not None else {
            "exchange_middle": str(RATE), "date_from": ACTUAL,
        }
        self.status = status
        self.error = error
        self.calls = []

    def __call__(self, url, timeout):
        self.calls.append((url, timeout))
        if self.error:
            raise self.error
        return httpx.Response(self.status, json=self.payload, request=httpx.Request("GET", url))


class Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class PGConnection:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, engine, transactional):
        self.engine = engine
        self.transactional = transactional

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.engine.statements.append((sql, params))
        if sql.startswith("SELECT pg_advisory_xact_lock"):
            assert self.transactional
            if self.engine.fill_at_lock:
                self.engine.rows[date.fromisoformat(REQUESTED)] = (RATE, date.fromisoformat(ACTUAL))
            return Result()
        if sql.startswith("SELECT iznos"):
            return Result(self.engine.rows.get(params["datum"]))
        if sql.startswith("INSERT INTO kurs"):
            assert self.transactional
            assert isinstance(params["iznos"], Decimal)
            self.engine.inserts += 1
            if self.engine.conflict_at_insert:
                self.engine.rows[params["datum"]] = (Decimal("118"), params["datum_kursa"])
                return Result()
            self.engine.rows[params["datum"]] = (params["iznos"], params["datum_kursa"])
            return Result(self.engine.rows[params["datum"]])
        raise AssertionError(f"Neočekivan SQL: {sql}")


class PGEngine:
    def __init__(self, fill_at_lock=False, conflict_at_insert=False):
        self.rows = {}
        self.statements = []
        self.inserts = 0
        self.fill_at_lock = fill_at_lock
        self.conflict_at_insert = conflict_at_insert

    def connect(self):
        return PGConnection(self, False)

    def begin(self):
        return PGConnection(self, True)


class KursAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        with self.engine.begin() as conn:
            ensure_kurs_table(conn)
            ensure_kurs_table(conn)
        self.http = OfflineHTTP()
        self.patcher = patch("kurs_service.httpx.get", self.http)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(self.engine.dispose)

    def count(self):
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT count(*) FROM kurs")).scalar_one()

    def test_given_database_hit_when_requested_then_no_http_and_database_edits_are_visible(self):
        with self.engine.begin() as conn:
            conn.execute(text("INSERT INTO kurs (iznos, datum, datum_kursa) VALUES (117, :d, :a)"),
                         {"d": REQUESTED, "a": ACTUAL})
        self.assertEqual(get_eur_rate(self.engine, REQUESTED), (117.0, ACTUAL))
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE kurs SET iznos = 118"))
        self.assertEqual(get_eur_rate(self.engine, REQUESTED), (118.0, ACTUAL))
        self.assertEqual(self.http.calls, [])

    def test_given_miss_when_requested_twice_then_single_fetch_and_weekend_date_preserved(self):
        expected = (float(RATE), ACTUAL)
        self.assertEqual(get_eur_rate(self.engine, REQUESTED), expected)
        self.assertEqual(get_eur_rate(self.engine, REQUESTED), expected)
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.http.calls, [(
            f"https://kurs.resenje.org/api/v1/currencies/EUR/rates/{REQUESTED}", 10,
        )])
        with self.engine.connect() as conn:
            row = conn.execute(text("SELECT datum, datum_kursa FROM kurs")).fetchone()
        self.assertEqual(tuple(row), (REQUESTED, ACTUAL))

    def test_given_date_field_without_date_from_then_valid_actual_date_is_saved(self):
        self.http.payload = {"exchange_middle": "117.2", "date": ACTUAL}
        self.assertEqual(get_eur_rate(self.engine, REQUESTED), (117.2, ACTUAL))

    def test_given_invalid_amount_when_requested_then_no_insert(self):
        for amount in (None, True, {}, [], "bad", "NaN", "Infinity", "-Infinity", "0", "-1", "1e999", "1e-999", float("nan")):
            with self.subTest(amount=amount):
                self.http.payload = {"exchange_middle": amount, "date_from": ACTUAL}
                self.assertEqual(get_eur_rate(self.engine, REQUESTED), (None, None))
                self.assertEqual(self.count(), 0)

    def test_given_invalid_response_date_when_requested_then_no_insert(self):
        for actual in (None, "", "bad", "2026-02-30", "20261002", "2026-10-05", 123, "2026-10-02T00:00:00"):
            with self.subTest(actual=actual):
                self.http.payload = {"exchange_middle": "117", "date_from": actual}
                self.assertEqual(get_eur_rate(self.engine, REQUESTED), (None, None))
                self.assertEqual(self.count(), 0)
        self.http.payload = {"exchange_middle": "117", "date_from": "bad", "date": ACTUAL}
        self.assertEqual(get_eur_rate(self.engine, REQUESTED), (None, None))

    def test_given_invalid_request_date_then_no_database_or_http_calls(self):
        class ForbiddenEngine:
            def connect(self):
                raise AssertionError("Database must not be consulted")
        for requested in (None, "", "bad", "2026-02-30", "20261004", "2026-W40-7", "2026-10-04T00:00:00", date.today(), 123):
            with self.subTest(requested=requested):
                self.assertEqual(get_eur_rate(ForbiddenEngine(), requested), (None, None))
        self.assertEqual(self.http.calls, [])

    def test_given_http_failures_then_no_insert_and_retry_can_succeed(self):
        for status in (404, 429, 500):
            self.http.status = status
            self.assertEqual(get_eur_rate(self.engine, REQUESTED), (None, None))
            self.assertEqual(self.count(), 0)
        self.http.status = 200
        self.http.error = httpx.TimeoutException("offline timeout")
        self.assertEqual(get_eur_rate(self.engine, REQUESTED), (None, None))
        self.assertEqual(self.count(), 0)
        self.http.error = None
        self.assertEqual(get_eur_rate(self.engine, REQUESTED), (float(RATE), ACTUAL))

    def test_given_malformed_payload_then_no_insert(self):
        for payload in ({}, [], {"date_from": ACTUAL}):
            self.http.payload = payload
            self.assertEqual(get_eur_rate(self.engine, REQUESTED), (None, None))
            self.assertEqual(self.count(), 0)

    def test_given_database_failure_then_no_api_or_fallback(self):
        class BrokenEngine:
            def connect(self):
                raise RuntimeError("offline database")
        self.assertEqual(get_eur_rate(BrokenEngine(), REQUESTED), (None, None))
        self.assertEqual(self.http.calls, [])

    def test_given_other_historical_row_and_api_failure_then_no_wrong_fallback(self):
        with self.engine.begin() as conn:
            conn.execute(text("INSERT INTO kurs (iznos, datum, datum_kursa) VALUES (117, '2026-10-01', '2026-10-01')"))
        self.http.status = 500
        self.assertEqual(get_eur_rate(self.engine, REQUESTED), (None, None))
        self.assertEqual(self.count(), 1)

    def test_given_postgres_miss_then_lock_recheck_insert_and_next_call_hits_database(self):
        engine = PGEngine()
        self.assertEqual(get_eur_rate(engine, REQUESTED), (float(RATE), ACTUAL))
        self.assertEqual(get_eur_rate(engine, REQUESTED), (float(RATE), ACTUAL))
        self.assertEqual(len(self.http.calls), 1)
        self.assertEqual(engine.inserts, 1)
        sql = [query for query, _ in engine.statements]
        self.assertTrue(sql[0].startswith("SELECT iznos"))
        self.assertTrue(sql[1].startswith("SELECT pg_advisory_xact_lock"))
        self.assertTrue(sql[2].startswith("SELECT iznos"))
        self.assertEqual(engine.statements[1][1]["date_key"], date.fromisoformat(REQUESTED).toordinal())

    def test_given_concurrent_fill_at_lock_then_recheck_returns_row_without_fetch(self):
        engine = PGEngine(fill_at_lock=True)
        self.assertEqual(get_eur_rate(engine, REQUESTED), (float(RATE), ACTUAL))
        self.assertEqual(engine.inserts, 0)
        self.assertEqual(self.http.calls, [])

    def test_given_insert_conflict_then_existing_database_value_is_returned(self):
        engine = PGEngine(conflict_at_insert=True)
        self.assertEqual(get_eur_rate(engine, REQUESTED), (118.0, ACTUAL))
        self.assertEqual(engine.inserts, 1)


if __name__ == "__main__":
    unittest.main()
