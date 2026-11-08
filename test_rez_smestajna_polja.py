"""Mapiranje stvarne/virtuelne sobe, bez inicijalizacije aplikacije i upisa u bazu.

Pokretanje: uv run python -m unittest test_rez_smestajna_polja -v
Izvršava originalnu ugnježdenu funkciju iz routes.py uz read-only lažnu konekciju.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

import routes


def mapper():
    tree = ast.parse(Path(routes.__file__).read_text())
    factory = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_app")
    node = next(n for n in factory.body if isinstance(n, ast.FunctionDef) and n.name == "rezervacija_vrednosti")
    namespace = dict(vars(routes))
    # Zauzeće termina se proverava odvojeno; ovde testiramo samo mapiranje forme.
    namespace["_rez_proveri_konflikt"] = lambda *args: None
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(routes.__file__), "exec"), namespace)
    return namespace["rezervacija_vrednosti"]


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class ReadOnlyConnection:
    def __init__(self, tip="1/4", opis="STD", koef=("1/3", "1/2"), exists=True):
        self.tip, self.opis, self.koef, self.exists = tip, opis, koef, exists

    def execute(self, statement, params):
        sql = str(statement)
        if sql.startswith("SELECT broj_sobe FROM sobe"):
            rows = [SimpleNamespace(broj_sobe="15")] if self.exists else []
        elif sql.startswith("SELECT TRIM(COALESCE(tip"):
            rows = [SimpleNamespace(tip=(self.tip or "").strip(), opis=(self.opis or "").strip())] if self.exists else []
        elif sql.startswith("SELECT TRIM(struktura) FROM soba_koeficijenti"):
            rows = [(v.strip() if v is not None else None,) for v in self.koef]
        else:
            raise AssertionError(f"Neočekivan SQL (upis nije dozvoljen): {sql}")
        return Result(rows)


class SmestajnaPoljaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.map_values = staticmethod(mapper())

    def values(self, struktura, conn=None, soba_id=750):
        body = routes.RezervacijaIn(
            nosilac={"ime": "TEST", "uzrast": "ADL"},
            boravak={"datumOd": "2027-06-01", "datumDo": "2027-06-10",
                     "sobaId": soba_id, "sobaBroj": "15", "struktura": struktura},
            cene={},
        )
        return self.map_values(conn or ReadOnlyConnection(), body, None)

    def test_virtualna_flora_v15_1(self):
        values = self.values("1/3")
        self.assertEqual({k: values[k] for k in ("apartman", "opis", "gde")},
                         {"apartman": "1/4", "opis": "STD", "gde": "1/3"})

    def test_stvarna_soba_brise_prethodno_gde(self):
        self.assertIsNone(self.values("1/4")["gde"])

    def test_prazna_struktura(self):
        values = self.values("")
        self.assertEqual(values["apartman"], "1/4")
        self.assertIsNone(values["gde"])

    def test_nepostojeci_koeficijent_nije_virtualna_soba(self):
        self.assertIsNone(self.values("1/9")["gde"])

    def test_normalizacija_razmaka_i_velicine_slova(self):
        conn = ReadOnlyConnection(tip=" BASE ", opis=" STD ", koef=(None, " alt "))
        values = self.values(" A L T ", conn)
        self.assertEqual((values["apartman"], values["opis"], values["gde"]), ("BASE", "STD", "alt"))
        self.assertIsNone(self.values(" b a s e ", conn)["gde"])

    def test_prazni_tip_i_opis(self):
        values = self.values("", ReadOnlyConnection(tip=None, opis=None))
        self.assertIsNone(values["apartman"])
        self.assertIsNone(values["opis"])

    def test_duzine_kolona(self):
        values = self.values("", ReadOnlyConnection(tip="a" * 30, opis="b" * 40))
        self.assertEqual(len(values["apartman"]), 10)
        self.assertEqual(len(values["opis"]), 20)

    def test_stara_soba_bez_id_ne_menja_kolone(self):
        values = self.values("1/3", soba_id=None)
        for key in ("apartman", "opis", "gde"):
            self.assertNotIn(key, values)

    def test_soba_koja_vise_ne_postoji_ne_menja_kolone(self):
        values = self.values("1/3", ReadOnlyConnection(exists=False))
        for key in ("apartman", "opis", "gde"):
            self.assertNotIn(key, values)


if __name__ == "__main__":
    unittest.main()
