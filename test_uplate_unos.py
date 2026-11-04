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
    id=1, first_name="Marko", last_name="Marković", status="aktivan",
    poslovnica_naziv="Novi Sad",
)
DEFAULT_ARANZMAN = SimpleNamespace(
    kljuc="33333/26",
    destinacija="Grčka - Halkidiki",
    mesto="Nea Kallikratia",
    subagent="Subagent d.o.o.",
    organizator="Oktopod",
    poslovnica="Beograd",
)

KARTICA_OK = {
    "brojPotvrde": "PT-889",
    "tipKartice": "Visa",
    "brojKartice": "4111 1111 1111 1111",
    "brojOdobrenja": "A1B2C3",
}

# VALID_BODY.din = 15000 → 3 čeka po 5000
CEKOVI_OK = [
    {"redni": r, "datum": d, "iznos": 5000.0, "banka": "Komercijalna banka",
     "brojRacunaBanke": "160-0000000012-34", "brojRacunaKlijenta": "123-456", "serijskiBroj": ""}
    for r, d in ((1, "2026-11-27"), (2, "2026-12-27"), (3, "2027-01-27"))
]

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
        if sql.lstrip().upper().startswith(("CREATE", "ALTER", "DO ")):
            return FakeResult()  # init DDL iz app starta (nije predmet ovog testa)
        self._state["sql_calls"].append((sql, params))
        if "FROM users" in sql:
            u = self._state["user"]
            return FakeResult(rows=[u] if u else [])
        if "FROM aranzman" in sql:
            a = self._state["aranzman"]
            return FakeResult(rows=[a] if a else [])
        if "FROM tipovi_kartica" in sql:
            naz = [SimpleNamespace(naziv=n) for n in self._state["tipovi"]]
            if params and "n" in params:
                naz = [r for r in naz if r.naziv == params["n"]]
            return FakeResult(rows=naz)
        if "FROM uplate WHERE kljuc" in sql:
            s = self._state["uplata_stari"]
            return FakeResult(rows=[s] if s else [])
        if "INSERT INTO uplate" in sql:
            self._state["insert"] = dict(params or {})
            return FakeResult(scalar=self._state["new_kljuc"])
        if "UPDATE uplate" in sql:
            self._state["update_broj"] = dict(params or {})
            return FakeResult()
        if "INSERT INTO rezervacija_log" in sql:
            self._state.setdefault("log", []).append(dict(params or {}))
            return FakeResult()
        if "INSERT INTO cekovi" in sql:
            self._state.setdefault("cekovi", []).append(dict(params or {}))
            return FakeResult()
        if "DELETE FROM cekovi" in sql:
            self._state["cekovi_obrisani"] = True
            return FakeResult()
        if "FROM cekovi" in sql:
            return FakeResult(rows=list(self._state.get("cekovi_stari", [])))
        raise AssertionError(f"Neočekivani SQL: {sql[:120]}")


class FakeEngine:
    def __init__(self, state):
        self._state = state

    def begin(self):
        self._state["begin_calls"] += 1
        return _Tx(self._state, FakeConnection(self._state))

    def connect(self):
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
            "tipovi": ("Visa", "Mastercard", "Dina"),
            "uplata_stari": SimpleNamespace(
                id=7, faktura="33333", nacin="Kartica", broj_potvrde=None,
                tip_kartice="Visa", broj_kartice=None, broj_odobrenja=None,
            ),
            "begin_calls": 0,
            "rolled_back": False,
            "sql_calls": [],
            "conn": None,
        }
        fake_engine = FakeEngine(self.state)
        noop = lambda engine: None
        with patch.object(routes, "get_engine", return_value=fake_engine), \
             patch.object(routes, "init_db", noop), \
             patch.object(routes, "init_cenovnici", noop), \
             patch.object(routes, "init_koeficijenti", noop), \
             patch.object(routes, "init_zaduzenje", noop), \
             patch.object(routes, "init_dobavljaci", noop), \
             patch.object(routes, "init_notifikacije", noop), \
             patch.object(routes, "init_rezervacija_log", noop), \
             patch.object(routes, "init_profil", noop), \
             patch.object(routes, "init_banke", noop):
            self.app = create_app("./dist")
        # brojači iz init DDL-a app starta ne pripadaju testovima zahteva
        self.state["begin_calls"] = 0
        self.state["sql_calls"].clear()
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
        self.assertEqual(ins["poslovnica"], "Novi Sad")  # poslovnica korisnika (users.poslovnica_id)
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
            body = {**VALID_BODY, "nacin": nacin}
            r = self.post(body=body)
            self.assertEqual(r.status_code, 201, nacin)
            self.assertEqual(self.state["insert"]["nacin"], nacin)
        for svrha in routes.SVRHE_UPLATE:
            r = self.post(body={**VALID_BODY, "svrha": svrha})
            self.assertEqual(r.status_code, 201, svrha)
            self.assertEqual(self.state["insert"]["svrha"], svrha)

    # ── kartica: unos uplate ne traži karticu, podaci se dodaju posle (PUT) ─
    def test_kartica_post_bez_podataka_201(self):
        r = self.post(body={**VALID_BODY, "nacin": "Kartica"})
        self.assertEqual(r.status_code, 201)
        ins = self.state["insert"]
        self.assertIsNone(ins["tip_kartice"])
        self.assertIsNone(ins["broj_kartice"])

    def test_kartica_post_ignorise_kartica_polja(self):
        r = self.post(body={**VALID_BODY, "nacin": "Kartica", "kartica": KARTICA_OK})
        self.assertEqual(r.status_code, 201)
        self.assertIsNone(self.state["insert"]["tip_kartice"])

    # ── kartica: izmena posle unosa (PUT) ───────────────────────────────────
    def kartica_put(self, kartica, nacin="Kartica"):
        self.state["uplata_stari"] = SimpleNamespace(
            id=7, faktura="33333", nacin=nacin, broj_potvrde=None,
            tip_kartice=None, broj_kartice=None, broj_odobrenja=None,
        )
        return self.client.put("/api/uplate/7/kartica", json=kartica, headers=self.hdr)

    def test_kartica_put_bez_tipa_400(self):
        r = self.kartica_put({**KARTICA_OK, "tipKartice": ""})
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(self.state["update_broj"])

    def test_kartica_put_nepoznat_tip_400(self):
        r = self.kartica_put({**KARTICA_OK, "tipKartice": "Amex-fake"})
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(self.state["update_broj"])

    def test_kartica_put_broj_bez_ogranicenja_dužine(self):
        for broj in ("1234", "4111 1111 1111 111a", "1" * 40, "ABC-123/9"):
            self.state["update_broj"] = None
            r = self.kartica_put({**KARTICA_OK, "brojKartice": broj})
            self.assertEqual(r.status_code, 200, broj)
            self.assertEqual(self.state["update_broj"]["broj_kartice"], broj)

    def test_kartica_put_ispravna_kolone(self):
        r = self.kartica_put({**KARTICA_OK, "brojKartice": " 4111 1111 1111 1111 "})
        self.assertEqual(r.status_code, 200)
        upd = self.state["update_broj"]
        self.assertEqual(upd["tip_kartice"], "Visa")
        self.assertEqual(upd["broj_kartice"], "4111 1111 1111 1111")
        self.assertEqual(upd["broj_potvrde"], "PT-889")
        self.assertEqual(upd["broj_odobrenja"], "A1B2C3")

    def test_tipovi_kartica_lista(self):
        r = self.client.get("/api/tipovi-kartica", headers=self.hdr)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), ["Visa", "Mastercard", "Dina"])

    # ── čekovi: unos uplate ne traži čekove; čekovi se dodaju posle (PUT) ───
    def test_cek_post_bez_cekova_201(self):
        r = self.post(body={**VALID_BODY, "nacin": "Ček"})
        self.assertEqual(r.status_code, 201)
        self.assertFalse(self.state.get("cekovi"))

    def test_cekovi_uz_drugi_nacin_se_ignorisu(self):
        r = self.post(body={**VALID_BODY, "nacin": "Gotovina", "cekovi": CEKOVI_OK})
        self.assertEqual(r.status_code, 201)
        self.assertFalse(self.state.get("cekovi"))

    # ── čekovi: snimanje (PUT) ──────────────────────────────────────────────
    def cek_put(self, cekovi, din=15000.0):
        self.state["uplata_stari"] = SimpleNamespace(
            id=7, faktura="33333", nacin="Ček", din=din, broj_potvrde=None,
            tip_kartice=None, broj_kartice=None, broj_odobrenja=None,
        )
        return self.client.put("/api/uplate/7/cekovi", json={"cekovi": cekovi}, headers=self.hdr)

    def test_cek_prazna_lista_400(self):
        r = self.cek_put([])
        self.assertEqual(r.status_code, 400)
        self.assertFalse(self.state.get("cekovi"))

    def test_cek_zbir_razlicit_od_iznosa_400(self):
        r = self.cek_put(CEKOVI_OK[:2])  # 10000 ≠ 15000
        self.assertEqual(r.status_code, 400)
        self.assertIn("ne slaže", r.json()["detail"])
        self.assertFalse(self.state.get("cekovi"))

    def test_cek_previse_stavki_400(self):
        lista = [{**CEKOVI_OK[0], "redni": i, "iznos": 1.0} for i in range(1, 62)]
        r = self.cek_put(lista, din=61.0)
        self.assertEqual(r.status_code, 400)

    def test_cek_los_iznos_i_datum_400(self):
        r = self.cek_put([{**CEKOVI_OK[0], "iznos": 7500.123}, {**CEKOVI_OK[1], "iznos": 7499.877}])
        self.assertEqual(r.status_code, 400)
        r = self.cek_put([{**c, "datum": "2026-13-45"} for c in CEKOVI_OK])
        self.assertEqual(r.status_code, 400)
        self.assertFalse(self.state.get("cekovi"))

    def test_cek_ispravan_200_i_renumeracija(self):
        mesano = [CEKOVI_OK[2], CEKOVI_OK[0], CEKOVI_OK[1]]
        r = self.cek_put(mesano)
        self.assertEqual(r.status_code, 200)
        ins = self.state["cekovi"]
        self.assertEqual(len(ins), 3)
        self.assertEqual([c["redni"] for c in ins], [1, 2, 3])
        self.assertEqual([c["datum"].isoformat() for c in ins], ["2026-11-27", "2026-12-27", "2027-01-27"])
        self.assertEqual(sum(c["iznos"] for c in ins), 15000.0)
        self.assertEqual(ins[0]["broj_racuna_klijenta"], "123-456")
        self.assertEqual({c["uplata_kljuc"] for c in ins}, {7})
        self.assertEqual({c["faktura"] for c in ins}, {"33333"})

    def test_cek_put_uz_drugi_nacin_400(self):
        self.state["uplata_stari"] = SimpleNamespace(
            id=7, faktura="33333", nacin="Gotovina", din=15000.0, broj_potvrde=None,
            tip_kartice=None, broj_kartice=None, broj_odobrenja=None,
        )
        r = self.client.put("/api/uplate/7/cekovi", json={"cekovi": CEKOVI_OK}, headers=self.hdr)
        self.assertEqual(r.status_code, 400)
        self.assertFalse(self.state.get("cekovi"))

    def test_izmena_cekova_put(self):
        self.state["uplata_stari"] = SimpleNamespace(
            id=7, faktura="33333", nacin="Ček", din=15000.0, broj_potvrde=None,
            tip_kartice=None, broj_kartice=None, broj_odobrenja=None,
        )
        self.state["cekovi_stari"] = [
            SimpleNamespace(redni=i + 1, datum=SimpleNamespace(isoformat=lambda c=c: c["datum"]),
                            iznos=c["iznos"], serijski_broj="")
            for i, c in enumerate(CEKOVI_OK)
        ]
        izmena = [dict(c) for c in CEKOVI_OK]
        izmena[1]["serijskiBroj"] = "SB-778811"
        izmena[2]["iznos"] = 5500.0
        izmena[0]["iznos"] = 4500.0  # zbir 15000
        r = self.client.put("/api/uplate/7/cekovi", json={"cekovi": izmena}, headers=self.hdr)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["broj_cekova"], 3)
        ins = self.state["cekovi"]
        self.assertEqual(len(ins), 3)
        self.assertEqual(ins[1]["serijski_broj"], "SB-778811")
        self.assertEqual(ins[2]["iznos"], 5500.0)

    def test_izmena_cekova_zbir_400(self):
        self.state["uplata_stari"] = SimpleNamespace(
            id=7, faktura="33333", nacin="Ček", din=15000.0, broj_potvrde=None,
            tip_kartice=None, broj_kartice=None, broj_odobrenja=None,
        )
        izmena = [dict(c) for c in CEKOVI_OK]
        izmena[0]["iznos"] = 4000.0
        r = self.client.put("/api/uplate/7/cekovi", json={"cekovi": izmena}, headers=self.hdr)
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(self.state.get("cekovi"))

    def test_izmena_kartice_put(self):
        r = self.client.put("/api/uplate/7/kartica", json=KARTICA_OK, headers=self.hdr)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.state["update_broj"]["tip_kartice"], "Visa")

    def test_izmena_kartice_nepoznata_uplata_404(self):
        self.state["uplata_stari"] = None
        r = self.client.put("/api/uplate/999/kartica", json=KARTICA_OK, headers=self.hdr)
        self.assertEqual(r.status_code, 404)

    def test_izmena_kartice_nije_kartica_400(self):
        self.state["uplata_stari"] = SimpleNamespace(
            id=8, faktura="33333", nacin="Virman", broj_potvrde=None,
            tip_kartice=None, broj_kartice=None, broj_odobrenja=None,
        )
        r = self.client.put("/api/uplate/8/kartica", json=KARTICA_OK, headers=self.hdr)
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(self.state["update_broj"])

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

    def test_iznos_nula_400_negativan_dozvoljen(self):
        r = self.post(body={**VALID_BODY, "din": 0})
        self.assertEqual(r.status_code, 400)
        self.assert_no_insert()
        r = self.post(body={**VALID_BODY, "din": -10000})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.state["insert"]["din"], -10000.0)

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
