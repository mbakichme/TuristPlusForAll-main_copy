"""Naslovna: predrezervacije sa isteklim rokom (GET /predrezervacije-istekle).

Read-only: koristi stvarnu bazu (samo SELECT), ništa ne upisuje.
"""
import unittest
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

import db_config
from dashboard_api import BELGRADE, register_dashboard


class PredrezervacijeIstekleTests(unittest.TestCase):
    def setUp(self):
        self.engine = db_config.get_engine()
        app = FastAPI()
        register_dashboard(app, self.engine, lambda: {"id": 1})
        self.client = TestClient(app)

    def test_given_endpoint_then_rows_match_direct_query_count(self):
        body = self.client.get("/predrezervacije-istekle")
        self.assertEqual(body.status_code, 200)
        sada = datetime.now(BELGRADE).replace(tzinfo=None)
        with self.engine.connect() as c:
            expected = c.execute(text("""
                SELECT COUNT(DISTINCT kljuc) FROM aranzman
                WHERE UPPER(TRIM(COALESCE(tiprezervacije, ''))) IN ('PREDREZERVACIJA', 'LAST MINUTE')
                  AND timelimit IS NOT NULL AND timelimit <= :s AND kljuc IS NOT NULL AND kljuc <> ''
            """), {"s": sada}).scalar()
        self.assertEqual(body.json()["ukupno"], expected)
        self.assertEqual(len(body.json()["rows"]), expected)

    def test_given_rows_then_no_storno_and_all_expired_and_unique_kljuc(self):
        rows = self.client.get("/predrezervacije-istekle").json()["rows"]
        kljucevi = [r["kljuc"] for r in rows]
        self.assertEqual(len(kljucevi), len(set(kljucevi)))
        self.assertTrue(all(r["tiprezervacije"].strip().upper() != "STORNO" for r in rows))
        self.assertTrue(all(r["timelimit"] for r in rows))

    def test_given_rows_then_no_delimicno_placanje(self):
        rows = self.client.get("/predrezervacije-istekle").json()["rows"]
        kljucevi = [r["kljuc"] for r in rows]
        with self.engine.connect() as c:
            if kljucevi:
                n = c.execute(text("SELECT COUNT(*) FROM aranzman WHERE kljuc = ANY(:k) AND TRIM(COALESCE(nacin_placanja,'')) = 'delimicno'"),
                              {"k": kljucevi}).scalar()
            else:
                n = 0
        self.assertEqual(n, 0)

    def test_given_rows_then_sorted_by_timelimit_ascending(self):
        rows = self.client.get("/predrezervacije-istekle").json()["rows"]
        stamps = [datetime.strptime(r["timelimit"], "%d.%m.%Y %H:%M") for r in rows]
        self.assertEqual(stamps, sorted(stamps))


if __name__ == "__main__":
    unittest.main()
