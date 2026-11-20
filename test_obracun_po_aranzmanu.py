"""Provere upisa obračuna po ugovoru (bez upisa u bazu).

Pokretanje: uv run python -m unittest test_obracun_po_aranzmanu -v
"""
import unittest
from types import SimpleNamespace

from routes import _obracun_argumenti


def telo(nosilac_uzrast="ADL", saputnici=(), ow=False, rt=False, smestaj_id=5, izbor=None):
    return SimpleNamespace(
        nosilac=SimpleNamespace(uzrast=nosilac_uzrast, ow=ow, rt=rt),
        saputnici=[SimpleNamespace(ime=ime, uzrast=u) for ime, u in saputnici],
        boravak=SimpleNamespace(smestajId=smestaj_id),
        obracunIzbor=izbor,
    )


class ObracunArgumentiTest(unittest.TestCase):
    def test_izabrana_varijanta_menja_soba_i_strukturu_za_obracun(self):
        izbor = SimpleNamespace(broj_sobe="v15-1", struktura="1/3", prevoz=None)
        a = _obracun_argumenti(telo(izbor=izbor), {"kolaranz": 1, "soba": "15", "apartman": "1/4"})
        self.assertEqual(a["soba_broj"], "v15-1")
        self.assertEqual(a["struktura"], "1/3")
        # bez izbora ostaje obračun po formi
        b = _obracun_argumenti(telo(), {"kolaranz": 1, "soba": "15", "apartman": "1/4"})
        self.assertEqual(b["soba_broj"], "15")
        self.assertEqual(b["struktura"], "1/4")

    def test_nosilac_i_saputnici_po_uzrastu(self):
        a = _obracun_argumenti(telo(saputnici=[("A", "ADL"), ("B", "CHD"), ("", "INF")]),
                               {"kolaranz": 2, "soba": "15", "apartman": "1/4", "gde": "1/3"})
        self.assertEqual(a["uzrasti"], ["ADL", "ADL", "CHD"])
        self.assertEqual(a["struktura"], "1/3")  # gde (virtuelna) ima prednost nad apartman
        self.assertEqual(a["soba_broj"], "15")
        self.assertEqual(a["smestaj_id"], 5)

    def test_kolicina_veca_od_putnika_dopunjava_adl(self):
        a = _obracun_argumenti(telo(), {"kolaranz": 3, "apartman": "1/2"})
        self.assertEqual(a["uzrasti"], ["ADL", "ADL", "ADL"])
        self.assertEqual(a["struktura"], "1/2")

    def test_prevoz_autobuski_je_true_sopstveni_false(self):
        self.assertTrue(_obracun_argumenti(telo(ow=True), {})["prevoz"])
        self.assertTrue(_obracun_argumenti(telo(rt=True), {})["prevoz"])
        self.assertFalse(_obracun_argumenti(telo(), {})["prevoz"])

    def test_iznos_je_cena_puta_kolicina(self):
        a = _obracun_argumenti(telo(), {"cenaaranz": 100.0, "kolaranz": 2.0})
        self.assertEqual(a["iznos_eur"], 200.0)
        self.assertIsNone(_obracun_argumenti(telo(), {})["iznos_eur"])

    def test_tabela_cuva_strukturu_varijante(self):
        from obracun_po_aranzmanu import OBRACUN_KOLONE
        self.assertIn("struktura", OBRACUN_KOLONE)

    def test_izabrani_prevoz_nadjacava_formu(self):
        izbor = SimpleNamespace(broj_sobe="15", struktura="1/4", prevoz=False)
        self.assertFalse(_obracun_argumenti(telo(ow=True, izbor=izbor), {})["prevoz"])
        izbor_bez = SimpleNamespace(broj_sobe="15", struktura="1/4", prevoz=None)
        self.assertTrue(_obracun_argumenti(telo(ow=True, izbor=izbor_bez), {})["prevoz"])


from datetime import date  # noqa: E402
from decimal import Decimal  # noqa: E402

from obracun_po_aranzmanu import izracun_ponude, lanac_termina  # noqa: E402

DANAS = date(2026, 6, 1)
PERIODI = [
    {"id": 1, "datum_od": "2026-06-01", "datum_do": "2026-06-08"},
    {"id": 2, "datum_od": "2026-06-08", "datum_do": "2026-06-15"},
]


def _ponuda(cene, sopstveni, adl=2, chd=0, koef="1.5", opcije=None, popusti=None, lanac=None):
    lanac = PERIODI if lanac is None else lanac
    return izracun_ponude(
        lanac=lanac, red_id=7, struktura="1/2", koef=Decimal(koef), izuz_koef=None,
        cene={(7, pid): Decimal(str(c)) for pid, c in cene.items()},
        opcije=opcije or {}, popusti=popusti or {}, adl=adl, chd=chd, inf=0,
        sopstveni=sopstveni, danas=DANAS,
    )


class LancIzracunaTest(unittest.TestCase):
    def test_lanac_pokriva_boravak_ili_je_prazan(self):
        self.assertEqual([p["id"] for p in lanac_termina(PERIODI, date(2026, 6, 1), date(2026, 6, 15))], [1, 2])
        self.assertEqual(lanac_termina(PERIODI, date(2026, 6, 1), date(2026, 6, 20)), [])

    def test_po_osobi_autobuski_bez_umanjenja(self):
        p = _ponuda({1: 100, 2: 120}, sopstveni=False, opcije={(7, 1): {"blokirano": False, "tip_cene": "po_osobi", "popust_sopstveni_prevoz": Decimal("10")}})
        self.assertTrue(p["dostupno"])
        self.assertEqual(p["osnova"], 330.0)          # (100 + 120) × 1.5
        self.assertEqual(p["osnova_cenovnika"], 220.0)  # zbir cena iz tabele, pre koeficijenta
        self.assertEqual(p["korekcija_prevoza"], -15.0)  # autobuski: − 10 × koef 1,5 × (2 − 1) smena
        self.assertEqual(p["cena"], 315.0)               # 330 − 15

    def test_po_osobi_sopstveni_umanjenje_po_smeni(self):
        opc = {(7, 1): {"blokirano": False, "tip_cene": "po_osobi", "popust_sopstveni_prevoz": Decimal("10")}}
        p = _ponuda({1: 100, 2: 120}, sopstveni=True, opcije=opc)
        self.assertEqual(p["korekcija_prevoza"], -30.0)  # 10 × koef 1,5 × 2 smene
        self.assertEqual(p["cena"], 300.0)               # 330 − 30
        # jedinična (za formu): 220 − 10 × 2 smene
        self.assertEqual(p["cena_jedinicna"], 200.0)

    def test_autobuski_jedinicna_je_osnova_cenovnika(self):
        opc = {(7, 1): {"blokirano": False, "tip_cene": "po_osobi", "popust_sopstveni_prevoz": Decimal("10")}}
        p = _ponuda({1: 100, 2: 120}, sopstveni=False, opcije=opc)
        self.assertEqual(p["cena_jedinicna"], 220.0)

    def test_po_sobi_karte_samo_za_autobuski(self):
        opc = {(7, 1): {"blokirano": False, "tip_cene": "po_sobi", "popust_sopstveni_prevoz": None}}
        self.assertEqual(_ponuda({1: 100, 2: 100}, sopstveni=False, adl=2, chd=1, opcije=opc)["cena"], 430.0)  # 200 + 2×80 + 70
        self.assertEqual(_ponuda({1: 100, 2: 100}, sopstveni=True, adl=2, chd=1, opcije=opc)["cena"], 200.0)

    def test_popust_procenat_i_iznos_i_istek(self):
        pop = {(7, 1): [
            {"redni": 1, "tip_popusta": "last_minute", "umanjenje_vrsta": "procenat", "umanjenje": Decimal("10"),
             "vazi_od": None, "vazi_do": None},
            {"redni": 2, "tip_popusta": "first_minute", "umanjenje_vrsta": "iznos", "umanjenje": Decimal("50"),
             "vazi_od": None, "vazi_do": date(2026, 5, 1)},
        ]}
        p = _ponuda({1: 100, 2: 120}, sopstveni=False, popusti=pop)
        self.assertEqual(p["cena"], 330.0)
        self.assertEqual(p["popusti"][0]["cena_snizena"], 297.0)  # 330 − 10%
        self.assertFalse(p["popusti"][1]["vazi"])
        self.assertEqual(p["cena_konacna"], 297.0)

    def test_nema_cene_za_termin_ili_blokirano(self):
        p = _ponuda({1: 100}, sopstveni=False)
        self.assertFalse(p["dostupno"])
        self.assertIn("2026-06-08", p["razlog"])
        opc = {(7, 2): {"blokirano": True, "tip_cene": None, "popust_sopstveni_prevoz": None}}
        self.assertFalse(_ponuda({1: 100, 2: 100}, sopstveni=False, opcije=opc)["dostupno"])


if __name__ == "__main__":
    unittest.main()
