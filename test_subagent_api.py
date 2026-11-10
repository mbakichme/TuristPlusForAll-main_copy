"""Testovi za API klijente subagenata (subagent_api.py).

Pokretanje (zahteva praznu test bazu):
  TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/test \
  uv run python -m unittest test_subagent_api -v

App2 poziv se mokuje; baza je potrebna za stanja i SQL.
"""
import os
import unittest
from unittest import mock

from sqlalchemy import create_engine, text

import subagent_api as sa

TEST_DB = os.environ.get("TEST_DATABASE_URL", "").strip()
ENV = {
    "SUBAGENT_SECRET_PEPPER": "test-pepper",
    "SUBAGENT_APP_URL": "https://app2.test",
    "SUBAGENT_APP_SERVICE_KEY": "test-service-key",
    "ORGANIZER_CODE": "oktopod",
    "ORGANIZER_NAME": "Oktopod test",
}


class PureFunctionTests(unittest.TestCase):
    def test_provision_payload_carries_full_profile(self):
        sub = {
            "id": 7, "naziv": "RODA", "punnaziv": "RODA TOURS", "adresa": "Ulica 1",
            "mesto": "Nis", "osoba": "Ana", "tel": "018/1", "tel1": "064/2",
            "tel2": "roda1@local.net", "fax": "", "racun": "160-1", "kontakt": "Marko",
            "provizija": 5.5, "provizija1": 1.0, "provizija1a": 0, "provizija2": 2.0,
            "email": "roda@example.com", "pib": "555", "matbroj": "123",
        }
        payload = sa._provision_payload(sub, "oktopod_x", "s" * 32, "oktopod", "Oktopod")
        self.assertEqual(payload["adresa"], "Ulica 1")
        self.assertEqual(payload["tel2"], "roda1@local.net")
        self.assertEqual(payload["provizija"], 5.5)
        self.assertEqual(payload["kontakt"], "Marko")
        self.assertEqual(payload["subagent_key"], "555")

    def test_hash_is_deterministic_and_64_hex(self):
        with mock.patch.dict(os.environ, ENV):
            h1 = sa.hash_secret("abc")
            h2 = sa.hash_secret("abc")
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_pepper_changes_hash(self):
        with mock.patch.dict(os.environ, ENV):
            h1 = sa.hash_secret("abc")
        with mock.patch.dict(os.environ, {**ENV, "SUBAGENT_SECRET_PEPPER": "drugi"}):
            h2 = sa.hash_secret("abc")
        self.assertNotEqual(h1, h2)

    def test_missing_pepper_raises(self):
        with mock.patch.dict(os.environ, {**ENV, "SUBAGENT_SECRET_PEPPER": ""}):
            with self.assertRaises(sa.SyncError):
                sa.hash_secret("abc")

    def test_generate_credentials_unique_and_prefixed(self):
        cid1, s1 = sa.generate_credentials("oktopod")
        cid2, s2 = sa.generate_credentials("oktopod")
        self.assertTrue(cid1.startswith("oktopod_"))
        self.assertNotEqual(cid1, cid2)
        self.assertNotEqual(s1, s2)
        self.assertGreaterEqual(len(s1), 40)

    def test_invalid_organizer_code_rejected(self):
        with mock.patch.dict(os.environ, {**ENV, "ORGANIZER_CODE": "Loš kod!"}):
            with self.assertRaises(sa.SyncError):
                sa._config()

    def test_provision_payload_uses_pib_as_key(self):
        sub = {"id": 7, "naziv": "A", "pib": "123456789"}
        p = sa._provision_payload(sub, "c1", "s1", "oktopod", "Okt")
        self.assertEqual(p["subagent_key"], "123456789")
        self.assertEqual(p["client_secret"], "s1")

    def test_provision_payload_falls_back_without_pib(self):
        sub = {"id": 7, "naziv": "A", "pib": ""}
        p = sa._provision_payload(sub, "c1", "s1", "oktopod", "Okt")
        self.assertEqual(p["subagent_key"], "oktopod:7")


@unittest.skipUnless(TEST_DB, "TEST_DATABASE_URL nije podešen")
class StateMachineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(TEST_DB)

    def setUp(self):
        self.env = mock.patch.dict(os.environ, ENV)
        self.env.start()
        with self.engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS subagent_api_clients"))
            conn.execute(text("DROP TABLE IF EXISTS subagenti"))
            conn.execute(text("""
                CREATE TABLE subagenti (
                    id SERIAL PRIMARY KEY, naziv VARCHAR(200) DEFAULT '',
                    punnaziv VARCHAR(300) DEFAULT '', mesto VARCHAR(100) DEFAULT '',
                    osoba VARCHAR(200) DEFAULT '', tel VARCHAR(100) DEFAULT '',
                    email VARCHAR(200) DEFAULT '', pib VARCHAR(30) DEFAULT '',
                    matbroj VARCHAR(20) DEFAULT '',
                    adresa VARCHAR(200) DEFAULT '', tel1 VARCHAR(200) DEFAULT '',
                    tel2 VARCHAR(200) DEFAULT '', fax VARCHAR(200) DEFAULT '',
                    racun VARCHAR(200) DEFAULT '', kontakt VARCHAR(300) DEFAULT '',
                    provizija DOUBLE PRECISION DEFAULT 0,
                    provizija1 DOUBLE PRECISION DEFAULT 0,
                    provizija1a DOUBLE PRECISION DEFAULT 0,
                    provizija2 DOUBLE PRECISION DEFAULT 0
                )
            """))
        sa.init_subagent_api(self.engine)
        with self.engine.begin() as conn:
            self.sub_id = conn.execute(text(
                "INSERT INTO subagenti (naziv, pib) VALUES ('Test', '999') RETURNING id"
            )).scalar()
        self.calls = []

        def fake_request(method, path, payload):
            self.calls.append((method, path, payload))
            if self.fail_next:
                self.fail_next = False
                raise sa.SyncError("App2 nedostupna (test)")

        self.fail_next = False
        self.req = mock.patch.object(sa, "_app2_request", side_effect=fake_request)
        self.req.start()

    def tearDown(self):
        self.req.stop()
        self.env.stop()

    def _client_rows(self):
        with self.engine.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(text(
                "SELECT client_id, is_active, sync_status, secret_hash "
                "FROM subagent_api_clients WHERE subagent_id = :s ORDER BY created_at"
            ), {"s": self.sub_id}).fetchall()]

    def test_create_provisions_and_marks_synced(self):
        status, err = sa.sinhronizuj_subagenta(self.engine, self.sub_id)
        self.assertEqual((status, err), ("synced", None))
        rows = self._client_rows()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["is_active"])
        self.assertEqual(rows[0]["sync_status"], "synced")
        method, path, payload = self.calls[-1]
        self.assertEqual(path, "/api/internal/provision")
        # Plaintext secret ide samo u payloadu, ne u bazi.
        self.assertNotIn(payload["client_secret"], rows[0]["secret_hash"])
        self.assertEqual(rows[0]["secret_hash"], sa.hash_secret(payload["client_secret"]))

    def test_verify_client_accepts_good_and_rejects_bad_secret(self):
        sa.sinhronizuj_subagenta(self.engine, self.sub_id)
        payload = self.calls[-1][2]
        ok = sa.verify_client(self.engine, payload["client_id"], payload["client_secret"])
        self.assertIsNotNone(ok)
        self.assertEqual(ok["subagent_id"], self.sub_id)
        self.assertIsNone(sa.verify_client(self.engine, payload["client_id"], "pogresan"))

    def _req(self, headers):
        return type("R", (), {"headers": headers})()

    def test_autentifikuj_subagenta_requires_valid_credentials_and_scope(self):
        from fastapi import HTTPException
        sa.sinhronizuj_subagenta(self.engine, self.sub_id)
        payload = self.calls[-1][2]
        good = {"X-Client-Id": payload["client_id"], "X-Client-Secret": payload["client_secret"]}
        self.assertEqual(sa.autentifikuj_subagenta(self.engine, self._req(good))["subagent_id"], self.sub_id)
        with self.assertRaises(HTTPException) as ctx:
            sa.autentifikuj_subagenta(self.engine, self._req({}))
        self.assertEqual(ctx.exception.status_code, 401)
        bad = {"X-Client-Id": payload["client_id"], "X-Client-Secret": "pogresan"}
        with self.assertRaises(HTTPException) as ctx:
            sa.autentifikuj_subagenta(self.engine, self._req(bad))
        self.assertEqual(ctx.exception.status_code, 401)
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE subagent_api_clients SET allowed_scopes = '[]' WHERE client_id = :c"),
                         {"c": payload["client_id"]})
        with self.assertRaises(HTTPException) as ctx:
            sa.autentifikuj_subagenta(self.engine, self._req(good))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_failed_provision_then_retry_rotates(self):
        self.fail_next = True
        status, err = sa.sinhronizuj_subagenta(self.engine, self.sub_id)
        self.assertEqual(status, "failed")
        rows = self._client_rows()
        self.assertFalse(rows[0]["is_active"])
        self.assertEqual(rows[0]["sync_status"], "failed")

        status, _ = sa.sinhronizuj_subagenta(self.engine, self.sub_id)
        self.assertEqual(status, "synced")
        rows = self._client_rows()
        self.assertEqual([r["sync_status"] for r in rows], ["superseded", "synced"])
        self.assertEqual(sum(1 for r in rows if r["is_active"]), 1)

    def test_synced_active_client_is_not_rotated(self):
        sa.sinhronizuj_subagenta(self.engine, self.sub_id)
        sa.sinhronizuj_subagenta(self.engine, self.sub_id)
        self.assertEqual(len(self._client_rows()), 1)
        self.assertEqual(sum(1 for r in self.calls if r[1] == "/api/internal/provision"), 1)

    def test_sinhronizuj_selektovane_endpoint(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        with self.engine.begin() as conn:
            sub2 = conn.execute(text(
                "INSERT INTO subagenti (naziv, pib) VALUES ('Drugi', '888') RETURNING id"
            )).scalar()
        app = FastAPI()
        sa.register_subagent_api(app, self.engine, lambda: {"id": 1})
        client = TestClient(app)

        # prazan seznam → 400
        self.assertEqual(
            client.post("/subagenti/sinhronizuj-selektovane", json={"ids": []}).status_code, 400
        )

        res = client.post("/subagenti/sinhronizuj-selektovane",
                          json={"ids": [self.sub_id, sub2]})
        self.assertEqual(res.status_code, 200)
        rez = res.json()["rezultati"]
        self.assertEqual([r["api_sync"] for r in rez], ["synced", "synced"])
        self.assertEqual([r["naziv"] for r in rez], ["Test", "Drugi"])

        # već sinhronizovan se preskače (bez App2 poziva), nepostojeći se prijavljuje
        poziva_pre = len(self.calls)
        res = client.post("/subagenti/sinhronizuj-selektovane",
                          json={"ids": [self.sub_id, 99999]})
        self.assertEqual(res.status_code, 200)
        rez = res.json()["rezultati"]
        self.assertEqual(rez[0]["api_sync"], "skipped")
        self.assertEqual(rez[1]["api_sync"], "not_found")
        self.assertEqual(len(self.calls), poziva_pre)

        # ASNS subagent se ne sinhronizuje kroz ovu listu (zaštita na backendu)
        with self.engine.begin() as conn:
            asns_id = conn.execute(text(
                "INSERT INTO subagenti (naziv, pib) VALUES ('ASNS proba', '555') RETURNING id"
            )).scalar()
        poziva_pre = len(self.calls)
        res = client.post("/subagenti/sinhronizuj-selektovane", json={"ids": [asns_id]})
        rez = res.json()["rezultati"]
        self.assertEqual(rez[0]["api_sync"], "skipped")
        self.assertIn("ASNS", rez[0]["api_sync_error"])
        self.assertEqual(len(self.calls), poziva_pre)

        # duplikati u selekciji se svedu na jedan rezultat
        res = client.post("/subagenti/sinhronizuj-selektovane", json={"ids": [sub2, sub2]})
        self.assertEqual(len(res.json()["rezultati"]), 1)

        # neuspeh App2 kod jednog ne prekida ostale (ciljano po nazivu, jer je paket paralelan)
        with self.engine.begin() as conn:
            redovi = conn.execute(text(
                "INSERT INTO subagenti (naziv, pib) VALUES ('Treći', '777'), ('Četvrti', '666') "
                "RETURNING id"
            )).fetchall()
        sub3, sub4 = redovi[0][0], redovi[1][0]

        def fail_treci(method, path, payload):
            self.calls.append((method, path, payload))
            if payload.get("naziv") == "Treći":
                raise sa.SyncError("App2 nedostupna (test)")

        with mock.patch.object(sa, "_app2_request", side_effect=fail_treci):
            res = client.post("/subagenti/sinhronizuj-selektovane", json={"ids": [sub3, sub4]})
        rez = res.json()["rezultati"]
        self.assertEqual(rez[0]["api_sync"], "failed")
        self.assertEqual(rez[1]["api_sync"], "synced")

    def test_change_of_pib_deactivates_old_then_provisions_new(self):
        sa.sinhronizuj_subagenta(self.engine, self.sub_id)
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE subagenti SET pib = '555' WHERE id = :s"), {"s": self.sub_id})
        status, err = sa.sinhronizuj_nakon_izmene(self.engine, self.sub_id, kljucna_promena=True)
        self.assertEqual((status, err), ("synced", None))
        # PATCH stare konekcije u App2 mora biti pre novog provisioninga
        self.assertEqual(self.calls[-2][0], "PATCH")
        self.assertEqual(self.calls[-1][1], "/api/internal/provision")
        rows = self._client_rows()
        self.assertEqual([r["sync_status"] for r in rows], ["superseded", "synced"])
        self.assertEqual(sum(1 for r in rows if r["is_active"]), 1)

    def test_profile_change_pushes_profile_without_rotation(self):
        sa.sinhronizuj_subagenta(self.engine, self.sub_id)
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE subagenti SET mesto = 'Nis', provizija = 5.5 WHERE id = :s"),
                         {"s": self.sub_id})
        status, err = sa.sinhronizuj_nakon_izmene(self.engine, self.sub_id, kljucna_promena=False)
        self.assertEqual((status, err), ("synced", None))
        method, path, payload = self.calls[-1]
        self.assertEqual((method, path), ("PUT", "/api/internal/subagent-profile"))
        self.assertEqual(payload["mesto"], "Nis")
        self.assertEqual(payload["provizija"], 5.5)
        self.assertNotIn("client_secret", payload)
        self.assertEqual(len(self._client_rows()), 1)

    def test_change_without_existing_client_does_not_sync(self):
        status, err = sa.sinhronizuj_nakon_izmene(self.engine, self.sub_id, kljucna_promena=True)
        self.assertEqual((status, err), (None, None))
        self.assertEqual(self.calls, [])

    def test_profile_failure_marks_failed_keeps_active_then_retry_pushes(self):
        sa.sinhronizuj_subagenta(self.engine, self.sub_id)
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE subagenti SET mesto = 'Nis' WHERE id = :s"), {"s": self.sub_id})
        self.fail_next = True
        status, err = sa.sinhronizuj_nakon_izmene(self.engine, self.sub_id, kljucna_promena=False)
        self.assertEqual(status, "failed")
        rows = self._client_rows()
        self.assertEqual(rows[0]["sync_status"], "failed")
        self.assertTrue(rows[0]["is_active"])  # App2 veza je i dalje aktivna

        status, _ = sa.sinhronizuj_subagenta(self.engine, self.sub_id)
        self.assertEqual(status, "synced")
        rows = self._client_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sync_status"], "synced")
        self.assertEqual(sum(1 for c in self.calls if c[1] == "/api/internal/provision"), 1)

    def test_delete_prep_deactivates_in_app2_and_blocks_on_failure(self):
        sa.sinhronizuj_subagenta(self.engine, self.sub_id)
        self.fail_next = True
        status, _ = sa.deaktiviraj_pre_brisanja(self.engine, self.sub_id)
        self.assertEqual(status, "deactivate_pending")
        self.assertTrue(self._client_rows()[0]["is_active"] is False)

        status, err = sa.deaktiviraj_pre_brisanja(self.engine, self.sub_id)
        self.assertEqual((status, err), ("deactivated", None))
        rows = self._client_rows()
        self.assertEqual(rows[0]["sync_status"], "deactivated")
        self.assertEqual(self.calls[-1][0], "PATCH")

    def test_delete_prep_without_client_is_allowed(self):
        status, err = sa.deaktiviraj_pre_brisanja(self.engine, self.sub_id)
        self.assertEqual((status, err), ("deactivated", None))
        self.assertEqual(self.calls, [])

    def test_delete_prep_missing_subagent_raises(self):
        with self.assertRaises(LookupError):
            sa.deaktiviraj_pre_brisanja(self.engine, 999999)

    def test_deactivate_patches_app2_and_keeps_row(self):
        sa.sinhronizuj_subagenta(self.engine, self.sub_id)
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE subagenti SET is_active = FALSE WHERE id = :s"),
                         {"s": self.sub_id})
        status, err = sa.sinhronizuj_subagenta(self.engine, self.sub_id)
        self.assertEqual((status, err), ("deactivated", None))
        method, path, payload = self.calls[-1]
        self.assertEqual(method, "PATCH")
        self.assertEqual(payload, {"is_active": False})
        rows = self._client_rows()
        self.assertEqual(len(rows), 1)  # bez brisanja
        self.assertEqual(rows[0]["sync_status"], "deactivated")
        self.assertFalse(rows[0]["is_active"])

    def test_deactivate_failure_stays_pending_and_retry_completes(self):
        sa.sinhronizuj_subagenta(self.engine, self.sub_id)
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE subagenti SET is_active = FALSE WHERE id = :s"),
                         {"s": self.sub_id})
        self.fail_next = True
        status, err = sa.sinhronizuj_subagenta(self.engine, self.sub_id)
        self.assertEqual(status, "deactivate_pending")
        self.assertIsNotNone(err)
        self.assertEqual(self._client_rows()[0]["sync_status"], "deactivate_pending")

        status, _ = sa.sinhronizuj_subagenta(self.engine, self.sub_id)
        self.assertEqual(status, "deactivated")
        self.assertEqual(self._client_rows()[0]["sync_status"], "deactivated")

    def test_deactivated_subagent_fails_verification(self):
        sa.sinhronizuj_subagenta(self.engine, self.sub_id)
        payload = self.calls[-1][2]
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE subagenti SET is_active = FALSE WHERE id = :s"),
                         {"s": self.sub_id})
        self.assertIsNone(sa.verify_client(self.engine, payload["client_id"], payload["client_secret"]))

    def test_reactivate_issues_new_secret(self):
        sa.sinhronizuj_subagenta(self.engine, self.sub_id)
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE subagenti SET is_active = FALSE WHERE id = :s"),
                         {"s": self.sub_id})
        sa.sinhronizuj_subagenta(self.engine, self.sub_id)
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE subagenti SET is_active = TRUE WHERE id = :s"),
                         {"s": self.sub_id})
        status, _ = sa.sinhronizuj_subagenta(self.engine, self.sub_id)
        self.assertEqual(status, "synced")
        rows = self._client_rows()
        self.assertEqual(sum(1 for r in rows if r["is_active"]), 1)
        self.assertEqual(rows[-1]["sync_status"], "synced")


if __name__ == "__main__":
    unittest.main()


