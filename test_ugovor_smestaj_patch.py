"""Offline unittest testovi za PATCH /api/ugovori/{kljuc}/smestaj.

Bez prave baze — engine je fake (čiste zamene, bez pisanja u bazu). Sadržaj
upita (zauzeće, join lanac sobe→smestaj→mesto→destinacija) simuliran je u
Pythonu po istoj semantici kao SQL. Nikad se ne radi INSERT/UPDATE u bazu.
Pokretanje:  .venv/bin/python -m unittest test_ugovor_smestaj_patch -v
"""

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import routes
from routes import create_access_token, create_app

KLJUC = "33333/26"
Soba = SimpleNamespace(
    id=101, broj_sobe=" 12 ", tip="1/3+1",
    smestaj_id=7, smestaj_naziv="DIMITRA",
    mesto_id=33, mesto_naziv="Hanioti",
    destinacija_naziv="Kassandra",
)
VALID_BODY = {"soba_id": Soba.id, "datum_od": "2026-07-01", "datum_do": "2026-07-10"}

# postojeće rezervacije (aranzman redovi) za simulaciju zauzeća — nijedna
# ne preklapa podrazumevani period [2026-07-01, 2026-07-10) sobe "12"
OD = lambda d: date.fromisoformat(d)
ZAUZECA = [
    # dodiruje granicu (datumdo == novi datumod) — ne preklapa
    {"id": 502, "kljuc": "77778/26", "naziv": "DIMITRA", "soba": "12",
     "datumod": OD("2026-06-25"), "datumdo": OD("2026-07-01")},
    # dodiruje granicu (datumod == novi datumdo) — ne preklapa
    {"id": 503, "kljuc": "77779/26", "naziv": "DIMITRA", "soba": "12",
     "datumod": OD("2026-07-10"), "datumdo": OD("2026-07-20")},
    # druga soba / drugi smeštaj — preklapa ali ne smeta
    {"id": 504, "kljuc": "77780/26", "naziv": "DIMITRA", "soba": "13",
     "datumod": OD("2026-07-05"), "datumdo": OD("2026-07-12")},
    {"id": 505, "kljuc": "77781/26", "naziv": "ELENI 2", "soba": "12",
     "datumod": OD("2026-07-05"), "datumdo": OD("2026-07-12")},
]
# preklapajuća rezervacija — dodaje se u testovima zauzeća
PREKLAPANJE = {"id": 501, "kljuc": "77777/26", "naziv": "DIMITRA", "soba": "12",
               "datumod": OD("2026-07-05"), "datumdo": OD("2026-07-12")}

UPDATE_COLS = {"smestaj_id", "naziv", "mesto", "destinacija", "soba", "apartman",
               "datumod", "datumdo", "datumoddo"}


class FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


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
        else:
            self._state["committed"] = True
        return False  # ne gutaj izuzetke — HTTPException prolazi ka klijentu


class FakeConnection:
    """Simulira samo upite koje PATCH /ugovori/{kljuc}/smestaj koristi."""

    def __init__(self, state):
        self._state = state

    def execute(self, query, params=None):
        sql = str(query)
        if not self._state.get("armed", True):
            return FakeResult()
        self._state["sql_calls"].append((sql, dict(params or {})))

        if "FROM users u" in sql:
            if self._state["user_missing"]:
                return FakeResult()
            return FakeResult([SimpleNamespace(
                id=params["id"], status=self._state["user_status"])])

        if "pg_advisory_xact_lock" in sql:
            self._state["advisory_keys"].append(params["key"])
            return FakeResult()

        if "FROM sobe b" in sql:
            soba = self._state["sobe"].get(params["id"])
            if soba is None or soba.smestaj_id is None:  # JOIN smestaj
                return FakeResult()
            # SELECT izrazi: COALESCE(TRIM(b.broj_sobe),''), COALESCE(TRIM(b.tip),'')
            out = SimpleNamespace(**{**soba.__dict__,
                                     "broj_sobe": (soba.broj_sobe or "").strip(),
                                     "tip": (soba.tip or "").strip()})
            return FakeResult([out])

        if "FOR UPDATE" in sql:
            if self._state["aranzman_missing"]:
                return FakeResult()
            return FakeResult([SimpleNamespace(id=self._state["aranzman_id"])])

        if "a.id <> :cur_id" in sql:
            # ista semantika kao SQL: naziv =, TRIM(soba) =, datumod < d_do,
            # datumdo > d_od, id <> cur_id
            p = params
            soba = (p["soba"] or "").strip()
            for z in self._state["zauzeca"]:
                if z["id"] == p["cur_id"]:
                    continue
                if z["naziv"] != p["naziv"]:
                    continue
                if (z["soba"] or "").strip() != soba:
                    continue
                if not (z["datumod"] < p["d_do"] and z["datumdo"] > p["d_od"]):
                    continue
                return FakeResult([SimpleNamespace(kljuc=z["kljuc"])])
            return FakeResult()

        if "UPDATE aranzman" in sql:
            self._state["update"] = dict(params or {})
            return FakeResult()

        raise AssertionError(f"Neočekivani SQL: {sql[:120]}")


class FakeEngine:
    def __init__(self, state):
        self._state = state

    def begin(self):
        self._state["begin_calls"] += 1
        return _Tx(self._state, FakeConnection(self._state))


class UgovorSmestajPatchTest(unittest.TestCase):
    def setUp(self):
        self.state = {
            "user_status": "aktivan",
            "user_missing": False,
            "sobe": {Soba.id: Soba},
            "aranzman_id": 900,
            "aranzman_missing": False,
            "zauzeca": [dict(z) for z in ZAUZECA],
            "update": None,
            "begin_calls": 0,
            "rolled_back": False,
            "committed": False,
            "advisory_keys": [],
            "sql_calls": [],
            "conn": None,
        }
        fake_engine = FakeEngine(self.state)
        self.state["armed"] = False  # init šema (create_app) ide kroz lažnu konekciju — ignoriši
        with patch.object(routes, "get_engine", return_value=fake_engine), \
             patch.object(routes, "init_db", lambda engine: None):
            self.app = create_app("./dist")
        self.state["armed"] = True
        self.token = create_access_token({"sub": "1"})
        self.hdr = {"Authorization": f"Bearer {self.token}"}
        self.client = TestClient(self.app)

    # ── pomoćne ─────────────────────────────────────────────────────────────
    def patch(self, body=None, headers=None, kljuc=KLJUC):
        return self.client.patch(
            f"/api/ugovori/{kljuc}/smestaj",
            json=body if body is not None else dict(VALID_BODY),
            headers=headers if headers is not None else self.hdr,
        )

    def assert_no_update(self):
        self.assertIsNone(self.state["update"])

    def assert_rolled_back(self):
        self.assertTrue(self.state["rolled_back"])

    # ── uspeh + mapiranje ───────────────────────────────────────────────────
    def test_uspesna_promena_200(self):
        r = self.patch()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"message": "Smeštaj je uspešno promenjen"})
        self.assertTrue(self.state["committed"])
        self.assertFalse(self.state["rolled_back"])
        self.assertEqual(self.state["begin_calls"], 1)

    def test_mapiranje_izvedenih_vrednosti(self):
        self.patch()
        u = self.state["update"]
        self.assertEqual(u["id"], 900)
        self.assertEqual(u["naziv"], "DIMITRA")          # smestaj.naziv
        self.assertEqual(u["mesto"], "Hanioti")          # mesto.naziv
        self.assertEqual(u["destinacija"], "Kassandra")  # destinacija.naziv
        self.assertEqual(u["soba"], "12")                # TRIM(broj_sobe)
        self.assertEqual(u["apartman"], "1/3+1")         # sobe.tip
        self.assertEqual(u["datumod"], date(2026, 7, 1))
        self.assertEqual(u["datumdo"], date(2026, 7, 10))
        # format postojećih podataka: 'DD.MM.YYYY-DD.MM.YYYY'
        self.assertEqual(u["datumoddo"], "01.07.2026-10.07.2026")
        # samo dozvoljene kolone — finansije/dopune se ne diraju
        self.assertEqual(set(u) - {"id"}, UPDATE_COLS)

    def test_whitespace_u_broj_sobe_se_trimuje(self):
        # Soba.broj_sobe = " 12 " → upisuje se "12" (TRIM konvencija)
        self.patch()
        self.assertEqual(self.state["update"]["soba"], "12")

    def test_jedna_transakcija_sa_advisory_lockom_pre_for_update(self):
        self.patch()
        calls = self.state["sql_calls"]
        advisory = next(i for i, (s, _) in enumerate(calls)
                        if "pg_advisory_xact_lock" in s)
        for_update = next(i for i, (s, _) in enumerate(calls) if "FOR UPDATE" in s)
        update = next(i for i, (s, _) in enumerate(calls) if "UPDATE aranzman" in s)
        self.assertLess(advisory, for_update)
        self.assertLess(for_update, update)
        self.assertEqual(self.state["advisory_keys"],
                         [routes.SMESTAJ_ADVISORY_LOCK_BASE + Soba.id])

    # ── zauzeće ─────────────────────────────────────────────────────────────
    def test_preklapanje_409(self):
        self.state["zauzeca"].append(dict(PREKLAPANJE))
        r = self.patch()
        self.assertEqual(r.status_code, 409)
        self.assertIn("77777/26", r.json()["detail"])
        self.assert_no_update()
        self.assert_rolled_back()

    def test_granica_dodirivanje_datuma_ok(self):
        # dodirivanje nije preklapanje: datumdo rezervacije == datum_od zahteva
        # (502: [25.06→01.07)) i datumod rezervacije == datum_do zahteva
        # (503: [10.07→20.07)) — podrazumevani period [01.07→10.07) prolazi,
        # a susedni periodi sa spoljne strane granica takođe
        r = self.patch(body={**VALID_BODY, "datum_od": "2026-06-20",
                             "datum_do": "2026-06-25"})  # dodiruje 502 odozgo
        self.assertEqual(r.status_code, 200)
        r = self.patch(body={**VALID_BODY, "datum_od": "2026-07-20",
                             "datum_do": "2026-07-25"})  # dodiruje 503 odozdo
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.state["begin_calls"], 2)

    def test_trenutni_ugovor_iskljucen_iz_zauzeca(self):
        # rezervacija 501 je zapravo trenutni ugovor (isti aranzman.id) —
        # preklapa sam sebe pa mora biti ignorisana
        self.state["zauzeca"] = [{"id": 900, "kljuc": KLJUC,
                                  "naziv": "DIMITRA", "soba": "12",
                                  "datumod": OD("2026-07-05"),
                                  "datumdo": OD("2026-07-12")}]
        r = self.patch()
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(self.state["update"])

    def test_druga_soba_ili_drugi_smestaj_nije_zauzece(self):
        # zauzeća 504 (druga soba) i 505 (drugi smeštaj) ne blokiraju
        self.state["zauzeca"] = [z for z in ZAUZECA if z["id"] in (504, 505)]
        r = self.patch()
        self.assertEqual(r.status_code, 200)

    def test_trim_sobe_se_koristi_u_proveri_zauzeca(self):
        # rezervacija sa sobom " 12 " (razmaci) mora se poklopiti sa "12"
        self.state["zauzeca"] = [{"id": 501, "kljuc": "77777/26",
                                  "naziv": "DIMITRA", "soba": " 12 ",
                                  "datumod": OD("2026-07-05"),
                                  "datumdo": OD("2026-07-12")}]
        r = self.patch()
        self.assertEqual(r.status_code, 409)

    # ── validacija datuma ───────────────────────────────────────────────────
    def test_neispravan_format_datuma_400(self):
        for od, do in [("01.07.2026", "2026-07-10"), ("2026-07-01", "10.07.2026"),
                       ("2026/07/01", "2026-07-10"), ("", "2026-07-10"),
                       ("2026-13-01", "2026-07-10"), ("2026-02-30", "2026-07-10")]:
            r = self.patch(body={"soba_id": Soba.id, "datum_od": od, "datum_do": do})
            self.assertEqual(r.status_code, 400, (od, do))
        self.assertEqual(self.state["begin_calls"], 0)
        self.assert_no_update()

    def test_datum_do_pre_ili_jednako_datum_od_400(self):
        for od, do in [("2026-07-10", "2026-07-01"), ("2026-07-01", "2026-07-01")]:
            r = self.patch(body={"soba_id": Soba.id, "datum_od": od, "datum_do": do})
            self.assertEqual(r.status_code, 400, (od, do))
        self.assertEqual(self.state["begin_calls"], 0)
        self.assert_no_update()

    # ── nepostojeći podaci ──────────────────────────────────────────────────
    def test_nepostojeca_soba_404(self):
        r = self.patch(body={"soba_id": 99999, "datum_od": "2026-07-01",
                             "datum_do": "2026-07-10"})
        self.assertEqual(r.status_code, 404)
        self.assert_no_update()
        self.assert_rolled_back()

    def test_soba_bez_smestaja_404(self):
        self.state["sobe"][Soba.id] = SimpleNamespace(
            **{**Soba.__dict__, "smestaj_id": None})
        r = self.patch()
        self.assertEqual(r.status_code, 404)
        self.assert_no_update()
        self.assert_rolled_back()

    def test_smestaj_bez_mesta_404(self):
        self.state["sobe"][Soba.id] = SimpleNamespace(
            **{**Soba.__dict__, "mesto_id": None, "mesto_naziv": None})
        r = self.patch()
        self.assertEqual(r.status_code, 404)
        self.assert_no_update()
        self.assert_rolled_back()

    def test_nepostojeci_ugovor_404(self):
        self.state["aranzman_missing"] = True
        r = self.patch()
        self.assertEqual(r.status_code, 404)
        self.assert_no_update()
        self.assert_rolled_back()

    # ── autentifikacija / autorizacija ──────────────────────────────────────
    def test_bez_tokena_401(self):
        r = self.patch(headers={})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.state["begin_calls"], 0)

    def test_neispravan_token_401(self):
        r = self.patch(headers={"Authorization": "Bearer neki.loss.token"})
        self.assertEqual(r.status_code, 401)

    def test_neaktivan_korisnik_403(self):
        self.state["user_status"] = "neaktivan"
        r = self.patch()
        self.assertEqual(r.status_code, 403)
        self.assert_no_update()
        self.assert_rolled_back()

    def test_nepostojeci_korisnik_401(self):
        self.state["user_missing"] = True
        r = self.patch()
        self.assertEqual(r.status_code, 401)
        self.assert_no_update()
        self.assert_rolled_back()

    # ── telo zahteva ────────────────────────────────────────────────────────
    def test_nepotpuno_telo_422(self):
        for body in ({}, {"soba_id": Soba.id}, {"datum_od": "2026-07-01"},
                     {"soba_id": "nije-broj", "datum_od": "2026-07-01",
                      "datum_do": "2026-07-10"}):
            r = self.patch(body=body)
            self.assertEqual(r.status_code, 422, body)
        self.assertEqual(self.state["begin_calls"], 0)

    def test_prazan_kljuc_400(self):
        r = self.patch(kljuc="")
        self.assertEqual(r.status_code, 400)
        self.assert_no_update()


if __name__ == "__main__":
    unittest.main()
