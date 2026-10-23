import unittest
from datetime import datetime, timedelta, timezone
from grafik_boje import kategorija_grafika


class GrafikBojeTest(unittest.TestCase):
    sada = datetime(2026, 10, 12, 12)

    def kategorija(self, tip="Klasična rezervacija", subagent="", limit=None, saldo=400):
        return kategorija_grafika(tip, subagent, limit, saldo, self.sada)

    def test_saldo(self):
        for saldo, expected in [(-10, "isplacen"), (0, "isplacen"),
                                (399.99, "isplacen"), (400, "saldo_veci"),
                                (400.01, "saldo_veci")]:
            with self.subTest(saldo=saldo):
                self.assertEqual(self.kategorija(saldo=saldo), expected)

    def test_blok_prioritet(self):
        self.assertEqual(self.kategorija(" BLOK ", "Agent", self.sada, 0), "blok")

    def test_subagent_prioritet(self):
        for limit in [None, self.sada, self.sada + timedelta(days=1)]:
            self.assertEqual(self.kategorija("Predrezervacija", " Agent ", limit, 0),
                             "predrezervacija_subagent")

    def test_time_limit(self):
        for limit in [None, self.sada, self.sada - timedelta(seconds=1)]:
            self.assertEqual(self.kategorija("predrezervacija", "  ", limit, 0),
                             "predrezervacija_istekla")
        self.assertEqual(self.kategorija(" Predrezervacija ", "", self.sada + timedelta(seconds=1)),
                         "predrezervacija_aktivna")

    def test_vremenska_zona(self):
        # Oktobar pre prelaska na zimsko vreme: Beograd = UTC+2.
        self.assertEqual(self.kategorija("Predrezervacija", "", datetime(2026, 10, 12, 10, tzinfo=timezone.utc)),
                         "predrezervacija_istekla")
        self.assertEqual(self.kategorija("Predrezervacija", "", datetime(2026, 10, 12, 10, 1, tzinfo=timezone.utc)),
                         "predrezervacija_aktivna")

    def test_nepoznati_tip(self):
        self.assertEqual(self.kategorija(None, None, saldo=0), "isplacen")
        self.assertEqual(self.kategorija("Last minute", "Agent", saldo=400), "saldo_veci")

    def test_api_sacuvane_boje(self):
        from fastapi.testclient import TestClient
        from routes import create_app, create_access_token
        client = TestClient(create_app(static_dir="/nonexistent"))
        headers = {"Authorization": "Bearer " + create_access_token({"sub": "1"})}
        boje_response = client.get("/api/boje-grafik", headers=headers)
        self.assertEqual(boje_response.status_code, 200)
        boje = boje_response.json()
        for smestaj in ["sve", "41"]:
            response = client.get("/api/grafik", params={"grupa_id": 16, "mesto_id": 1, "smestaj_id": smestaj}, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            sekcije = data["sekcije"] if smestaj == "sve" else [data]
            total = 0
            for sekcija in sekcije:
                for ugovor in sekcija["ugovori"]:
                    total += 1
                    self.assertEqual(ugovor["boja"], boje[ugovor["boja_kategorija"]])
                    self.assertIsInstance(ugovor["saldo_rsd"], (float, int))
            self.assertGreater(total, 0)


if __name__ == "__main__":
    unittest.main()
