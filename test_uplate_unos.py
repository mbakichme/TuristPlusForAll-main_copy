"""Offline unittest testovi za POST /api/uplate (unos uplate).

Bez prave baze — engine je fake (MagicMock-free, čiste zamene), a NBS kurs
servis je blokiran/lažiran preko httpx.get. Nikad se ne radi INSERT u bazu.
Pokretanje:  .venv/bin/python -m unittest test_uplate_unos -v
"""

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import routes
from routes import create_access_token, create_app

RATE = 117.0234  # lažni srednji NBS kurs EUR

DEFAULT_USER = SimpleNamespace(
    id=1, first_name="Marko", last_name="Marković", status="aktivan"
)
DEFAULT_ARANZMAN = SimpleNamespace(
    kljuc="33333/26",
    destinacija="Grčka - Halkidiki",
    mesto="Nea Kallikratia",
    subagent="Subagent d.o.o.",
    organizator="Oktopod",
    poslovnica="Beograd",
)

VALID_BODY = {
    "ugovor": "33333/26",
    "ime": "Petar Petrović",
    "adresa": "Kralja Milana 12, Beograd",
    "nacin": "Gotovina",
    "din": 15000.0,
    "svrha": "Total aranžman",
}


def fake_rate_response(url, **kwargs):
    if "kurs.resenje.org" in url:
        return SimpleNamespace(
            json=lambda: {"exchange_middle": str(RATE)},
            raise_for_status=lambda: None,
        )
    raise AssertionError(f"Neočekivan HTTP poziv: {url}")


class FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def scalar_one(self):
        if self._scalar is None:
            raise AssertionError("scalar_one() bez INSERT ... RETURNING")
        return self._scalar


class _Tx:
    def __init__(self, state, conn):
        self._state = state
        self._conn = conn

    def __enter__(self):
        self._state["conn"] = self._conn
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self._state["rolled_back"] = True
        return False  # ne gutaj izuzetke — propagation vraća transakciju


class FakeConnection:
    def __init__(self, state):
        self._state = state

    def execute(self, query, params=None):
        sql = str(query)
        self._state["sql_calls"].append((sql, params))
        if "FROM users" in sql:
            u = self._state["user"]
            return FakeResult(rows=[u] if u else [])
        if "FROM aranzman" in sql:
            a = self._state["aranzman"]
            return FakeResult(rows=[a] if a else [])
        if "INSERT INTO uplate" in sql:
            self._state["insert"] = dict(params or {})
            return FakeResult(scalar=self._state["new_kljuc"])
        if "UPDATE uplate" in sql:
            self._state["update_broj"] = dict(params or {})
            return FakeResult()
        raise AssertionError(f"Neočekivani SQL: {sql[:120]}")


class FakeEngine:
    def __init__(self, state):
        self._state = state

    def begin(self):
        self._state["begin_calls"] += 1
        return _Tx(self._state, FakeConnection(self._state))


class UplataUnosTest(unittest.TestCase):
    def setUp(self):
        # lažni NBS kurs servis za celu dužinu testa (i create_app i zahteve)
        rate_patch = patch.object(routes, "get_eur_rate", side_effect=lambda engine, datum: (RATE, datum))
        rate_patch.start()
        self.addCleanup(rate_patch.stop)

        self.state = {
            "user": DEFAULT_USER,
            "aranzman": DEFAULT_ARANZMAN,
            "new_kljuc": 55665,
            "insert": None,
            "update_broj": None,
            "begin_calls": 0,
            "rolled_back": False,
            "sql_calls": [],
            "conn": None,
        }
        fake_engine = FakeEngine(self.state)
        with patch.object(routes, "get_engine", return_value=fake_engine), \
             patch.object(routes, "init_db", lambda engine: None):
            self.app = create_app("./dist")
        self.token = create_access_token({"sub": "1"})
        self.hdr = {"Authorization": f"Bearer {self.token}"}
        self.client = TestClient(self.app)

    # ── pomoćne ─────────────────────────────────────────────────────────────
    def post(self, body=None, headers=None):
        return self.client.post(
            "/api/uplate",
            json=body if body is not None else dict(VALID_BODY),
            headers=headers if headers is not None else self.hdr,
        )

    def post_raw(self, body=None, headers=None):
        """JSON telo sa NaN/Infinity literaliima (httpx json= ih odbija)."""
        import json as _json
        payload = _json.dumps(body if body is not None else dict(VALID_BODY))
        hdr = dict(headers if headers is not None else self.hdr)
        hdr.setdefault("Content-Type", "application/json")
        return self.client.post("/api/uplate", content=payload, headers=hdr)

    def assert_no_insert(self):
        self.assertIsNone(self.state["insert"])
        self.assertIsNone(self.state["update_broj"])

    # ── uspešan unos ────────────────────────────────────────────────────────
    def test_uspesan_unos_201(self):
        r = self.post()
        self.assertEqual(r.status_code, 201)
        data = r.json()
        self.assertEqual(data["kljuc"], 55665)
        self.assertIsInstance(data["kljuc"], int)
        self.assertEqual(data["message"], "Uplata je uspešno uneta")

    def test_insert_mapiranje_kolona(self):
        self.post()
        ins = self.state["insert"]
        self.assertIsNotNone(ins)
        self.assertEqual(ins["id"], 33333)                 # broj pre "/"
        self.assertEqual(ins["faktura"], "33333")          # isti numerički string
        self.assertEqual(ins["vrsta"], "UPLATA")
        self.assertEqual(ins["evro"], 0)
        self.assertEqual(ins["din"], 15000.0)
        self.assertEqual(ins["uevro"], round(15000.0 / RATE, 2))
        self.assertEqual(ins["ime"], "Petar Petrović")
        self.assertEqual(ins["adresa"], "Kralja Milana 12, Beograd")
        self.assertEqual(ins["nacin"], "Gotovina")
        self.assertEqual(ins["svrha"], "Total aranžman")
        self.assertEqual(ins["obradio"], "Marko Marković")  # ime+prezime iz users
        # polja sa persistiranog aranžmana — tačni ključevi
        self.assertEqual(ins["destinacija"], DEFAULT_ARANZMAN.destinacija)
        self.assertEqual(ins["mesto"], DEFAULT_ARANZMAN.mesto)
        self.assertEqual(ins["subagent"], DEFAULT_ARANZMAN.subagent)
        self.assertEqual(ins["organizator"], DEFAULT_ARANZMAN.organizator)
        self.assertEqual(ins["poslovnica"], DEFAULT_ARANZMAN.poslovnica)
        # danas = lokalno vreme Europe/Belgrade (naive, UTC+1 ili UTC+2)
        self.assertIsInstance(ins["danas"], datetime)
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        cet = abs((ins["danas"] - (now_utc + timedelta(hours=1))).total_seconds())
        cest = abs((ins["danas"] - (now_utc + timedelta(hours=2))).total_seconds())
        self.assertLess(min(cet, cest), 120)

    def test_broj_je_string_novog_kljuca_u_istoj_transakciji(self):
        self.post()
        upd = self.state["update_broj"]
        self.assertEqual(upd, {"b": "55665", "k": 55665})
        self.assertEqual(self.state["begin_calls"], 1)
        self.assertFalse(self.state["rolled_back"])
        self.assertIsNotNone(self.state["conn"])

    def test_ugovor_bez_kose_crte(self):
        r = self.post(body={**VALID_BODY, "ugovor": "33333"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.state["insert"]["id"], 33333)
        self.assertEqual(self.state["insert"]["faktura"], "33333")

    def test_svi_nacini_i_svrhe_prihvaceni(self):
        for nacin in routes.NACINI_UPLATE:
            r = self.post(body={**VALID_BODY, "nacin": nacin})
            self.assertEqual(r.status_code, 201, nacin)
            self.assertEqual(self.state["insert"]["nacin"], nacin)
        for svrha in routes.SVRHE_UPLATE:
            r = self.post(body={**VALID_BODY, "svrha": svrha})
            self.assertEqual(r.status_code, 201, svrha)
            self.assertEqual(self.state["insert"]["svrha"], svrha)

    # ── autentifikacija i korisnik ──────────────────────────────────────────
    def test_bez_tokena_401(self):
        r = self.post(headers={})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.state["begin_calls"], 0)
        self.assert_no_insert()

    def test_nevalidan_token_401(self):
        r = self.post(headers={"Authorization": "Bearer ne-tok.en"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.state["begin_calls"], 0)
        self.assert_no_insert()

    def test_nepoznat_korisnik_401(self):
        self.state["user"] = None
        r = self.post()
        self.assertEqual(r.status_code, 401)
        self.assert_no_insert()

    def test_neaktivan_korisnik_403(self):
        self.state["user"] = SimpleNamespace(
            id=1, first_name="Marko", last_name="Marković", status="blokiran"
        )
        r = self.post()
        self.assertEqual(r.status_code, 403)
        self.assert_no_insert()

    # ── validacija tela ─────────────────────────────────────────────────────
    def test_prazan_ugovor_400(self):
        r = self.post(body={**VALID_BODY, "ugovor": "  "})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.state["begin_calls"], 0)
        self.assert_no_insert()

    def test_nepoznat_ugovor_404(self):
        self.state["aranzman"] = None
        r = self.post(body={**VALID_BODY, "ugovor": "99999/26"})
        self.assertEqual(r.status_code, 404)
        self.assert_no_insert()

    def test_obavezno_ime_platioca_400(self):
        r = self.post(body={**VALID_BODY, "ime": ""})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.state["begin_calls"], 0)
        self.assert_no_insert()

    def test_neispravan_nacin_400(self):
        r = self.post(body={**VALID_BODY, "nacin": "Cash"})
        self.assertEqual(r.status_code, 400)
        self.assert_no_insert()

    def test_neispravna_svrha_400(self):
        r = self.post(body={**VALID_BODY, "svrha": "Nešto drugo"})
        self.assertEqual(r.status_code, 400)
        self.assert_no_insert()

    def test_iznos_nula_i_negativan_400(self):
        for din in (0, -1, -150.5):
            r = self.post(body={**VALID_BODY, "din": din})
            self.assertEqual(r.status_code, 400, din)
        self.assert_no_insert()

    def test_iznos_tri_decimale_400(self):
        r = self.post(body={**VALID_BODY, "din": 150.999})
        self.assertEqual(r.status_code, 400)
        self.assert_no_insert()

    def test_iznos_nan_400(self):
        r = self.post_raw(body={**VALID_BODY, "din": float("nan")})
        self.assertEqual(r.status_code, 400)
        self.assert_no_insert()

    def test_iznos_beskonačan_400(self):
        r = self.post_raw(body={**VALID_BODY, "din": float("inf")})
        self.assertEqual(r.status_code, 400)
        self.assert_no_insert()

    def test_iznos_dve_decimale_ok(self):
        r = self.post(body={**VALID_BODY, "din": 123.45})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.state["insert"]["din"], 123.45)
        self.assertEqual(self.state["insert"]["uevro"], round(123.45 / RATE, 2))

    # ── kurs ────────────────────────────────────────────────────────────────
    def test_nedostajuci_kurs_503_bez_unosa(self):
        # drugi patch prekriva lažni odgovor iz setUp — servis nedostupan
        with patch.object(routes, "get_eur_rate", return_value=(None, None)):
            r = self.post()
        self.assertEqual(r.status_code, 503)
        self.assertEqual(self.state["begin_calls"], 0)  # fail PRE inserta
        self.assert_no_insert()

    def test_neispravan_kurs_bez_unosa(self):
        for rate in (-117, float('nan'), float('inf')):
            with patch.object(routes, 'get_eur_rate', return_value=(rate, '2026-10-04')):
                r = self.post()
            self.assertEqual(r.status_code, 503)
            self.assert_no_insert()

    def test_predugacko_ime_ili_adresa_bez_unosa(self):
        for column in ('ime', 'adresa'):
            r = self.post(body={**VALID_BODY, column: 'x' * 301})
            self.assertEqual(r.status_code, 400)
            self.assert_no_insert()

    # ── VARCHAR(10) guard ───────────────────────────────────────────────────
    def test_broj_predugacko_500_rollback(self):
        self.state["new_kljuc"] = 12345678901  # 11 cifara > VARCHAR(10)
        r = self.post()
        self.assertEqual(r.status_code, 500)
        self.assertIsNone(self.state["update_broj"])   # broj nikad nije upisan
        self.assertTrue(self.state["rolled_back"])      # INSERT vraćen (rollback)


if __name__ == "__main__":
    unittest.main()
