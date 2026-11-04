"""Testovi za poslovnice (CRUD + validacija) i vezu korisnik ↔ poslovnica.

CRUD: FastAPI TestClient nad pravom bazom (čisti svoje redove).
Korisnik ↔ poslovnica: HTTP ka živom backendu (BASE), kao test_profil_api.py.
"""
import json
import os
import unittest
import urllib.error
import urllib.request

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

import db_config
from poslovnice_api import init_poslovnice, register_poslovnice
from routes import create_access_token

PREFIX = "TEST-POSL-"
BASE = f"http://127.0.0.1:{int(os.environ.get('APP_PORT', '3062')) + 100}/api"


def _fake_user():
    return {"sub": "1"}


def _req(path, method="GET", body=None):
    tok = create_access_token({"sub": "1"})
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method, headers={
        "Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None


class PoslovniceCrudTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = db_config.get_engine()
        init_poslovnice(cls.engine)
        api = APIRouter()
        register_poslovnice(api, cls.engine, _fake_user)
        app = FastAPI()
        app.include_router(api, prefix="/api")
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        with cls.engine.begin() as conn:
            conn.execute(text("DELETE FROM poslovnice WHERE naziv LIKE :p"), {"p": PREFIX + "%"})

    def body(self, **kw):
        base = {"naziv": PREFIX + "Centar", "adresa": "Trg 1", "grad": "Beograd",
                "opstina_rgz": "1", "opstina_naziv": "Stari grad", "mesto_rgz": "2",
                "mesto_naziv": "Beograd", "ulica_rgz": "3", "ulica_naziv": "Knez Mihailova"}
        base.update(kw)
        return base

    def test_crud(self):
        c = self.client
        r = c.post("/api/poslovnice", json=self.body())
        self.assertEqual(r.status_code, 201, r.text)
        pid = r.json()["id"]

        mine = [p for p in c.get("/api/poslovnice").json()["poslovnice"] if p["id"] == pid]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["grad"], "Beograd")
        self.assertEqual(mine[0]["ulica_naziv"], "Knez Mihailova")

        r = c.put(f"/api/poslovnice/{pid}", json=self.body(naziv=PREFIX + "Novi", grad="Novi Sad"))
        self.assertEqual(r.status_code, 200, r.text)
        mine = [p for p in c.get("/api/poslovnice").json()["poslovnice"] if p["id"] == pid][0]
        self.assertEqual(mine["naziv"], PREFIX + "Novi")
        self.assertEqual(mine["grad"], "Novi Sad")

        self.assertEqual(c.delete(f"/api/poslovnice/{pid}").status_code, 200)
        self.assertEqual(c.delete(f"/api/poslovnice/{pid}").status_code, 404)
        self.assertEqual(c.put(f"/api/poslovnice/{pid}", json=self.body()).status_code, 404)

    def test_validacija(self):
        c = self.client
        self.assertEqual(c.post("/api/poslovnice", json=self.body(naziv="   ")).status_code, 422)
        self.assertEqual(c.post("/api/poslovnice", json=self.body(naziv="x" * 201)).status_code, 422)
        self.assertEqual(c.post("/api/poslovnice", json=self.body(ulica_naziv="y" * 301)).status_code, 422)

    def test_trim_i_prazna_polja(self):
        r = self.client.post("/api/poslovnice", json={"naziv": "  " + PREFIX + "Trim  "})
        self.assertEqual(r.status_code, 201, r.text)
        pid = r.json()["id"]
        row = [p for p in self.client.get("/api/poslovnice").json()["poslovnice"] if p["id"] == pid][0]
        self.assertEqual(row["naziv"], PREFIX + "Trim")
        self.assertEqual(row["adresa"], "")
        self.assertEqual(row["mesto_rgz"], "")
        self.client.delete(f"/api/poslovnice/{pid}")


class KorisnikPoslovnicaTest(unittest.TestCase):
    """Zahteva živi backend na BASE (port 3158)."""

    @classmethod
    def setUpClass(cls):
        cls.engine = db_config.get_engine()
        init_poslovnice(cls.engine)
        try:
            _req("/poslovnice")
        except Exception as e:  # backend nije podignut
            raise unittest.SkipTest(f"Backend nije dostupan: {e}")

    @classmethod
    def tearDownClass(cls):
        with cls.engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE username LIKE 'testposl_%'"))
            conn.execute(text("DELETE FROM poslovnice WHERE naziv LIKE :p"), {"p": PREFIX + "%"})

    def test_korisnik_poslovnica(self):
        st, pos = _req("/poslovnice", "POST", {"naziv": PREFIX + "Korisnik"})
        self.assertEqual(st, 201)
        pid = pos["id"]

        body = {"first_name": "Test", "last_name": "Posl", "email": "testposl_1@example.test",
                "username": "testposl_1", "password": "tajna123", "poslovnica_id": pid}
        st, u = _req("/users", "POST", body)
        self.assertEqual(st, 200)
        uid = u["id"]
        self.assertEqual(u["poslovnica_id"], pid)

        st, lista = _req("/users")
        row = [x for x in lista if x["id"] == uid][0]
        self.assertEqual(row["poslovnica_id"], pid)
        self.assertEqual(row["poslovnica_naziv"], PREFIX + "Korisnik")

        st, _ = _req(f"/users/{uid}", "PUT", {"poslovnica_id": None})
        self.assertEqual(st, 200)
        row = [x for x in _req("/users")[1] if x["id"] == uid][0]
        self.assertIsNone(row["poslovnica_id"])
        self.assertIsNone(row["poslovnica_naziv"])

        _req(f"/users/{uid}", "PUT", {"poslovnica_id": pid})
        _req(f"/poslovnice/{pid}", "DELETE")
        row = [x for x in _req("/users")[1] if x["id"] == uid][0]
        self.assertIsNone(row["poslovnica_id"], "brisanje poslovnice skida vezu kod korisnika")
        _req(f"/users/{uid}", "DELETE")


if __name__ == "__main__":
    unittest.main()
