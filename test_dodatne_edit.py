"""Offline acceptance tests; SQL is exercised against an in-memory fake engine only."""

import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import routes


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def mappings(self):
        return self

    def first(self):
        return self.fetchone()

    def one(self):
        assert len(self.rows) == 1
        return self.rows[0]


class Transaction:
    def __init__(self, engine):
        self.engine = engine

    def __enter__(self):
        self.snapshot = copy.deepcopy(self.engine.rows)
        self.engine.transactions += 1
        return self.engine

    def __exit__(self, kind, value, traceback):
        if kind:
            self.engine.rows = self.snapshot
            self.engine.rollbacks += 1
        return False


class Engine:
    def __init__(self):
        self.user = SimpleNamespace(id=1, status="aktivan")
        self.contracts = {"33333/26", "44444/26"}
        self.rows = {
            1: {"stavka_id": 1, "id": 33333, "usluga": None, "eur": None, "din": None},
            2: {"stavka_id": 2, "id": 44444, "usluga": "Tuđa", "eur": 10., "din": 0.},
            3: {"stavka_id": 3, "id": 33333, "usluga": "Prevoz", "eur": 12.34, "din": -5.},
        }
        self.calls = []
        self.transactions = 0
        self.rollbacks = 0

    def begin(self):
        return Transaction(self)

    def execute(self, query, params=None):
        sql = str(query)
        params = params or {}
        self.calls.append((sql, dict(params)))
        if "FROM users" in sql:
            return Result([self.user] if self.user and params["id"] == self.user.id else [])
        if "FROM aranzman" in sql:
            assert "WHERE kljuc = :k" in sql
            key = params["k"]
            return Result([SimpleNamespace(kljuc=key)] if key in self.contracts else [])
        if "INSERT INTO dodatne" in sql:
            assert "RETURNING stavka_id, usluga, eur, din" in sql
            key = max(self.rows) + 1
            row = {"stavka_id": key, **params}
            self.rows[key] = row
            return Result([self.flat(row)])
        if "UPDATE dodatne" in sql:
            assert "WHERE stavka_id = :stavka_id AND id = :id" in sql
            for field in ("usluga", "eur", "din"):
                assert f"{field} IS NOT DISTINCT FROM :original_{field}" in sql
            row = self.rows.get(params["stavka_id"])
            if not row or row["id"] != params["id"]:
                return Result()
            if any(row[field] != params[f"original_{field}"] for field in ("usluga", "eur", "din")):
                return Result()
            row.update({field: params[field] for field in ("usluga", "eur", "din")})
            return Result([self.flat(row)])
        if "SELECT stavka_id FROM dodatne" in sql:
            assert "WHERE stavka_id = :stavka_id AND id = :id" in sql
            row = self.rows.get(params["stavka_id"])
            return Result([self.flat(row)] if row and row["id"] == params["id"] else [])
        raise AssertionError(f"Unexpected SQL: {sql}")

    @staticmethod
    def flat(row):
        return {key: row[key] for key in ("stavka_id", "usluga", "eur", "din")}


class DodatneAcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.engine = Engine()
        with patch.object(routes, "get_engine", return_value=self.engine), \
             patch.object(routes, "init_db", lambda engine: None):
            self.app = routes.create_app("./dist")
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.headers = {"Authorization": f"Bearer {routes.create_access_token({'sub': '1'})}"}
        self.body = {"usluga": "  Transfer  ", "eur": -12.34, "din": None}
        self.original = {"usluga": None, "eur": None, "din": None}

    def request(self, method="POST", body=None, contract="33333/26", item=1, headers=None):
        url = f"/api/ugovori/{contract}/dodatne"
        if method == "PATCH":
            url += f"/{item}"
        if body is None:
            body = dict(self.body)
            if method == "PATCH":
                body["original"] = dict(self.original)
        return self.client.request(method, url, content=json.dumps(body), headers={
            **(self.headers if headers is None else headers), "Content-Type": "application/json",
        })

    def assert_no_mutation(self):
        self.assertFalse(any("INSERT" in sql or "UPDATE" in sql for sql, _ in self.engine.calls))

    def test_add_service_returns_flat_row_and_scopes_contract(self):
        response = self.request()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json(), {"stavka_id": 4, "usluga": "Transfer", "eur": -12.34, "din": None})
        self.assertEqual(self.engine.rows[4]["id"], 33333)
        self.assertEqual(self.engine.transactions, 1)
        self.assertEqual(self.engine.rows[3]["eur"], 12.34)

    def test_edit_legacy_null_row(self):
        response = self.request("PATCH")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"stavka_id": 1, "usluga": "Transfer", "eur": -12.34, "din": None})
        self.assertEqual(self.engine.transactions, 1)

    def test_edit_with_exact_original_preserves_original_whitespace(self):
        self.engine.rows[3]["usluga"] = " Prevoz "
        body = {**self.body, "original": {"usluga": " Prevoz ", "eur": 12.34, "din": -5}}
        response = self.request("PATCH", body, item=3)
        self.assertEqual(response.status_code, 200, response.text)

    def test_concurrent_changes_in_each_field_return_conflict(self):
        for field, value in (("usluga", "Changed"), ("eur", 1), ("din", -1)):
            with self.subTest(field=field):
                self.engine.rows[1][field] = value
                before = copy.deepcopy(self.engine.rows)
                response = self.request("PATCH")
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(self.engine.rows, before)
                self.engine.rows[1][field] = None
        self.assertEqual(self.engine.rollbacks, 3)

    def test_missing_and_foreign_rows_return_404_not_conflict(self):
        for item in (2, 999):
            with self.subTest(item=item):
                before = copy.deepcopy(self.engine.rows)
                response = self.request("PATCH", item=item)
                self.assertEqual(response.status_code, 404, response.text)
                self.assertEqual(self.engine.rows, before)

    def test_original_is_required_including_nullable_fields(self):
        for original in ("missing", None, {}, {"usluga": None, "eur": None}):
            with self.subTest(original=original):
                body = dict(self.body)
                if original != "missing":
                    body["original"] = original
                response = self.request("PATCH", body)
                self.assertEqual(response.status_code, 422, response.text)
        self.assert_no_mutation()

    def test_nonempty_trimmed_service_max_150(self):
        for method in ("POST", "PATCH"):
            for value in ("", " \t\n ", "a" * 151):
                with self.subTest(method=method, value=value):
                    body = {**self.body, "usluga": value, "original": self.original}
                    self.assertEqual(self.request(method, body).status_code, 400)
            body = {**self.body, "usluga": " " + "a" * 150 + " ", "original": self.original}
            self.assertIn(self.request(method, body).status_code, (200, 201))

    def test_signed_zero_nullable_and_two_decimal_amounts(self):
        for value in (None, 0, -1, 12.34, -0.01, 123456.78):
            with self.subTest(value=value):
                response = self.request(body={**self.body, "eur": value, "din": value})
                self.assertEqual(response.status_code, 201, response.text)
                self.assertEqual(response.json()["eur"], value)
                self.assertEqual(response.json()["din"], value)

    def test_invalid_amounts_rejected_without_writes(self):
        for method in ("POST", "PATCH"):
            for field in ("eur", "din"):
                for value in (float("nan"), float("inf"), -float("inf"), 1.001, -0.001, 0.010000001):
                    with self.subTest(method=method, field=field, value=value):
                        body = {**self.body, field: value, "original": self.original}
                        self.assertEqual(self.request(method, body).status_code, 400)
                for value in (True, "not a number", {}):
                    with self.subTest(method=method, field=field, value=value):
                        body = {**self.body, field: value, "original": self.original}
                        self.assertEqual(self.request(method, body).status_code, 422)
        self.assert_no_mutation()

    def test_nonfinite_original_rejected(self):
        for field in ("eur", "din"):
            body = {**self.body, "original": {**self.original, field: float("inf")}}
            self.assertEqual(self.request("PATCH", body).status_code, 400)
        self.assert_no_mutation()

    def test_authentication_required_for_both_operations(self):
        for method in ("POST", "PATCH"):
            for headers in ({}, {"Authorization": "Bearer invalid"}):
                self.assertEqual(self.request(method, headers=headers).status_code, 401)
        self.assertEqual(self.engine.transactions, 0)
        self.assert_no_mutation()

    def test_user_must_exist_and_be_active(self):
        for method in ("POST", "PATCH"):
            self.engine.user = None
            self.assertEqual(self.request(method).status_code, 401)
            self.engine.user = SimpleNamespace(id=1, status="blokiran")
            self.assertEqual(self.request(method).status_code, 403)
        self.assert_no_mutation()

    def test_bad_user_subject_rejected(self):
        headers = {"Authorization": f"Bearer {routes.create_access_token({'sub': 'bad'})}"}
        self.assertEqual(self.request(headers=headers).status_code, 401)
        self.assert_no_mutation()

    def test_exact_contract_required_no_prefix_fallback(self):
        for method in ("POST", "PATCH"):
            for contract in ("33333", "33333/25", "99999/26"):
                self.assertEqual(self.request(method, contract=contract).status_code, 404)
        self.assert_no_mutation()

    def test_prefix_must_be_numeric_int32(self):
        for method in ("POST", "PATCH"):
            for prefix in ("abc", "1.2", "2147483648", "-2147483649"):
                contract = prefix + "/26"
                self.engine.contracts.add(contract)
                self.assertEqual(self.request(method, contract=contract).status_code, 400)
        self.assert_no_mutation()

    def test_int32_boundaries(self):
        for prefix in ("2147483647", "-2147483648"):
            contract = prefix + "/26"
            self.engine.contracts.add(contract)
            response = self.request(contract=contract)
            self.assertEqual(response.status_code, 201)
            self.assertEqual(self.engine.rows[response.json()["stavka_id"]]["id"], int(prefix))

    def test_migration_adds_serial_and_unique_index_after_table_creation(self):
        class SchemaEngine:
            def __init__(self):
                self.sql = []
                self.dialect = SimpleNamespace(name="postgresql")

            def begin(self):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, query, params=None):
                self.sql.append(str(query))
                return SimpleNamespace(scalar=lambda: 1, fetchone=lambda: SimpleNamespace(id=1))

        engine = SchemaEngine()
        routes.init_db(engine)
        create = next(i for i, sql in enumerate(engine.sql) if "CREATE TABLE IF NOT EXISTS dodatne" in sql)
        alter = next(i for i, sql in enumerate(engine.sql) if "ALTER TABLE dodatne ADD COLUMN IF NOT EXISTS stavka_id SERIAL" in sql)
        unique = next(i for i, sql in enumerate(engine.sql) if "CREATE UNIQUE INDEX IF NOT EXISTS idx_dodatne_stavka_id" in sql)
        self.assertLess(create, alter)
        self.assertLess(alter, unique)

    def test_detail_query_includes_row_identity(self):
        import inspect
        source = inspect.getsource(routes.create_app)
        self.assertIn("SELECT stavka_id, usluga, eur, din FROM dodatne WHERE id = :broj", source)


if __name__ == "__main__":
    unittest.main()
