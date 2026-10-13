"""Offline regresija: svaka uplata koristi kurs svog datuma."""
import unittest
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
import routes


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class Engine:
    def __init__(self, rows):
        self.rows = rows

    @contextmanager
    def connect(self):
        yield self

    def execute(self, sql, params):
        assert "FROM uplate" in str(sql)
        return Result([SimpleNamespace(_mapping=row) for row in self.rows])


class HistoricalPaymentRateTest(unittest.TestCase):
    def test_each_payment_uses_own_date_including_zero_and_storno(self):
        rows = [
            {"danas": datetime(2024, 1, 5), "din": 12000},
            {"danas": datetime(2024, 1, 6), "din": -1100},
            {"danas": datetime(2024, 1, 6), "din": 0},
            {"danas": None, "din": 500},
        ]
        rates = {"2024-01-05": (120, "2024-01-05"),
                 "2024-01-06": (110, "2024-01-05")}
        with patch.object(routes, "get_engine", return_value=Engine(rows)), \
             patch.object(routes, "init_db"), \
             patch.object(routes, "get_eur_rate", side_effect=lambda engine, day: rates[day]) as rate:
            app = routes.create_app("./dist")
            app.dependency_overrides[routes.get_current_user] = lambda: {"sub": "1"}
            with TestClient(app) as client:
                response = client.get("/api/ugovori/33333/26/uplate")
            self.assertEqual(response.status_code, 200)
            values = response.json()["rows"]
            self.assertEqual([v["suma_eur"] for v in values], [100, -10, 0, None])
            self.assertEqual(values[1]["kurs_datum"], "05.01.2024")
            self.assertEqual(sum(v["suma_eur"] or 0 for v in values), 90)
            self.assertEqual([call.args[1] for call in rate.call_args_list],
                             ["2024-01-05", "2024-01-06", "2024-01-06"])


if __name__ == "__main__":
    unittest.main()
