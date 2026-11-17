"""Testovi App2 sinhronizacije (app2_sync.py).

Pokretanje:
  uv run python -m unittest test_app2_sync -v
"""
import os
import unittest
from unittest import mock

import app2_sync as s


class KoloneZaUpis(unittest.TestCase):
    def test_izbacuje_app1_only_kolone(self):
        red = {"id": 5, "kljuc": "1/2026", "subagent_id": 7, "subagent": "X"}
        self.assertEqual(s.kolone_za_upis(red), {"id": 5, "kljuc": "1/2026", "subagent": "X"})


class BezKonfiguracije(unittest.TestCase):
    def test_bez_env_nema_app2_konekcije(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(s.APP2_SYNC_URL_ENV, None)
            self.assertIsNone(s._app2())

    def test_posle_izmene_bez_env_ne_radi_nista(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(s.APP2_SYNC_URL_ENV, None)
            with mock.patch.object(s, "sinhronizuj_kljuc") as kljuc:
                s.sinhronizuj_posle_izmene(mock.Mock(), "1/2026")
                kljuc.assert_not_called()


class BestEffort(unittest.TestCase):
    def test_greska_se_guta_i_loguje(self):
        with mock.patch.object(s, "_app2", return_value=object()), \
             mock.patch.object(s, "sinhronizuj_kljuc", side_effect=RuntimeError("baza nedostupna")), \
             self.assertLogs(s.log, level="ERROR"):
            s.sinhronizuj_posle_izmene(mock.Mock(), "1/2026")  # ne sme da baci

    def test_nepovezan_tenant_se_loguje_kao_upozorenje(self):
        with mock.patch.object(s, "_app2", return_value=object()), \
             mock.patch.object(s, "sinhronizuj_kljuc", return_value="tenant_nije_povezan"), \
             self.assertLogs(s.log, level="WARNING"):
            s.sinhronizuj_posle_izmene(mock.Mock(), "1/2026")


class PunoOsvezavanjeEndpoint(unittest.TestCase):
    def setUp(self):
        from fastapi import APIRouter, FastAPI
        from fastapi.testclient import TestClient

        api = APIRouter()
        s.register_app2_sync(api, mock.Mock())
        app = FastAPI()
        app.include_router(api)
        self.client = TestClient(app)

    def test_bez_kljuca_503(self):
        with mock.patch.dict(os.environ, {s.APP2_SYNC_KEY_ENV: ""}):
            self.assertEqual(self.client.post("/sync/puna").status_code, 503)

    def test_pogresan_kljuc_401(self):
        with mock.patch.dict(os.environ, {s.APP2_SYNC_KEY_ENV: "tajna"}):
            res = self.client.post("/sync/puna", headers={"X-Sync-Key": "pogresna"})
        self.assertEqual(res.status_code, 401)

    def test_ispravan_kljuc_pokrece_sync(self):
        env = {s.APP2_SYNC_KEY_ENV: "tajna", s.APP2_SYNC_URL_ENV: "postgresql://x"}
        with mock.patch.dict(os.environ, env), \
             mock.patch.object(s, "_app2", return_value=object()), \
             mock.patch.object(s, "sinhronizuj_sve", return_value={"synced": 3}) as sve:
            res = self.client.post("/sync/puna", headers={"X-Sync-Key": "tajna"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["rezultat"], {"synced": 3})
        sve.assert_called_once()

    def test_subagent_klijent_nema_pristup(self):
        # Subagent headeri (X-Client-Id/Secret) ne otključavaju rutu.
        with mock.patch.dict(os.environ, {s.APP2_SYNC_KEY_ENV: "tajna"}):
            res = self.client.post("/sync/puna", headers={"X-Client-Id": "x", "X-Client-Secret": "y"})
        self.assertEqual(res.status_code, 401)


if __name__ == "__main__":
    unittest.main()
