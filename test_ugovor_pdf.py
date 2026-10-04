"""Offline acceptance checks using real PDF extraction and ZXing QR decoding."""
import base64
import copy
import io
import unittest
from datetime import date, datetime

import pymupdf
import zxingcpp
from PIL import Image

from ugovor_pdf import LEGAL_CLAUSES, QR_WARNING, build_ugovor_ips_qr, generate_ugovor_pdf


class UgovorPDFAcceptance(unittest.TestCase):
    def setUp(self):
        self.agency = {
            "naziv": "Agencija Čačak", "ulica": "Trg oslobođenja", "broj": "5",
            "post_broj": "32000", "mesto": "Čačak", "telefon1": "032/123456",
            "email1": "info@example.test", "pib": "100000000", "mb": "20000000",
            "racun": "265-3710310000481-09", "banka": "Banka Intesa",
        }
        self.contract = {
            "aranzman": {
                "kljuc": "2424/26", "danas": datetime(2025, 12, 15, 18, 30),
                "putnik": "RAKIĆ MARINA", "rodjen": date(1970, 4, 5), "pasos": "P123456",
                "adresa": "Dubljanska 22", "telefon": "062229121", "email": "marina@example.test",
                "destinacija": "Grčka", "mesto": "VRASNA PARALIA", "naziv": "DAFNI",
                "apartman": "1/4", "opis": "MEZ", "soba": "Soba 7", "obrok": "RR",
                "datumod": date(2026, 7, 2), "datumdo": "2026-07-12",
                "prevozow": 0, "prevozrt": 1, "viza": 0, "ulazak": "Beograd", "smer": "Povratak",
                "napomena": "Javna napomena š č ć ž đ <bezbedno>", "napomena1": "TAJNA INTERNA BELEŠKA",
                "keptp": 1759, "organizator": "Organizator Travel", "poslovnica": "Stadion 3",
                "osiguranje": 0,
            },
            "putnici_detalji": [{"saputnik": "KOVAČEVIĆ DINA", "rodjen": date(1980, 2, 25),
                "pasos": "P987654", "uzrast": "ADULT", "prevozow": 1, "prevozrt": 0,
                "viza": 1, "ulazak": "Niš", "smer": "Odlazak", "telefon": "063302968"}],
            "obracun": {"smestaj": 860, "prevoz": 0, "viza": 0, "popust": 172,
                "naplata": 620, "provizija": 68},
            "ukupno_eur": 688, "ukupno_rsd": 80544.16,
            "kurs": 117.07, "kurs_datum": "2025-12-15",
            "datum_izdavanja": date(2025, 12, 15),
            "dodatne": [{"usluga": "Doplata pogled more", "eur": 10, "din": 500}],
        }

    def document(self, contract=None, agency=None):
        return pymupdf.open(stream=generate_ugovor_pdf(contract or self.contract, agency or self.agency), filetype="pdf")

    def text(self, doc):
        return " ".join(" ".join(page.get_text() for page in doc).split())

    def test_given_raw_data_when_rendered_then_all_sections_and_exact_totals_are_present(self):
        with self.document() as doc:
            text = self.text(doc)
            for expected in (
                "UGOVOR / PRIJAVA BROJ 2424/26", "NOSILAC ARANŽMANA", "SAPUTNICI",
                "PUTOVANJE I SMEŠTAJ", "OBRAČUN ZA NAPLATU", "DODATNE USLUGE / OSTALO",
                "PLAĆANJE — NBS IPS QR", "IZJAVE I USLOVI PUTOVANJA",
                "RAKIĆ MARINA", "05.04.1970", "P123456", "Dubljanska 22", "062229121",
                "marina@example.test", "KOVAČEVIĆ DINA", "25.02.1980", "P987654", "ADULT",
                "Grčka", "VRASNA PARALIA", "DAFNI", "1/4", "MEZ", "Soba 7", "RR",
                "02.07.2026", "12.07.2026", "Prevoz OW: NE", "Prevoz RT: DA", "Viza: NE",
                "Beograd", "Povratak", "Niš", "Odlazak", "Javna napomena š č ć ž đ <bezbedno>",
                "860,00", "172,00", "620,00", "68,00", "688,00", "80.544,16", "117.07",
                "15.12.2025", "Doplata pogled more — 10,00 EUR / 500,00 RSD",
                "Potpis putnika", "Za Agenciju", "Ugovor je punovažan bez pecata",
            ):
                self.assertIn(expected, text)
            for clause in LEGAL_CLAUSES:
                self.assertIn(clause, text)
            self.assertNotIn("TAJNA INTERNA", text)
            self.assertNotIn("698,00", text)
            self.assertNotIn("81.044,24", text)
            self.assertIn("I:RSD80544,16", build_ugovor_ips_qr(self.contract, self.agency))

    def test_given_many_companions_when_paginated_then_header_repeats_and_no_text_is_clipped(self):
        contract = copy.deepcopy(self.contract)
        contract["putnici_detalji"] = [dict(contract["putnici_detalji"][0], saputnik=f"SAPUTNIK {i:03}", pasos=f"PAS{i:03}") for i in range(65)]
        contract["aranzman"]["napomena"] = "duga_napomena_" * 200
        with self.document(contract) as doc:
            self.assertGreater(len(doc), 5)
            text = self.text(doc)
            for i in range(65):
                self.assertIn(f"SAPUTNIK {i:03}", text)
                self.assertIn(f"PAS{i:03}", text)
            for page in doc:
                for expected in ("Agencija Čačak", "Trg oslobođenja", "32000 Čačak", "032/123456",
                                 "info@example.test", "PIB 100000000", "MB 20000000", "265-3710310000481-09", "Banka Intesa"):
                    self.assertIn(expected, page.get_text())
                for word in page.get_text("words"):
                    self.assertGreaterEqual(word[0], 39)
                    self.assertLessEqual(word[2], page.rect.width - 39)
                    self.assertGreaterEqual(word[1], 20)
                    self.assertLessEqual(word[3], page.rect.height - 15)

    def test_given_qr_when_decoded_from_actual_pdf_then_payload_matches_nbs_fields(self):
        payload = build_ugovor_ips_qr(self.contract, self.agency)
        fields = dict(part.split(":", 1) for part in payload.split("|"))
        self.assertEqual(fields["R"], "265371031000048109")
        self.assertEqual(fields["N"], "Agencija Čačak")
        self.assertEqual(fields["I"], "RSD80544,16")
        self.assertEqual(fields["SF"], "221")
        self.assertEqual(fields["S"], "Ugovor br 2424/26")
        self.assertEqual(fields["RO"], "002424-26")
        self.assertEqual(fields["P"], "RAKIĆ MARINA")
        with self.document() as doc:
            decoded = []
            for page in doc:
                for image in page.get_images(full=True):
                    content = doc.extract_image(image[0])["image"]
                    result = zxingcpp.read_barcode(Image.open(io.BytesIO(content)).convert("RGB"))
                    if result:
                        decoded.append(result.text)
            self.assertIn(payload, decoded)

    def test_given_invalid_payment_data_then_no_false_valid_qr_and_visible_warning(self):
        for account in ("123", "x265-3710310000481-09", "26512345678901234567", "", "265-1-9"):
            agency = dict(self.agency, racun=account)
            self.assertIsNone(build_ugovor_ips_qr(self.contract, agency))
            with self.document(agency=agency) as doc:
                self.assertIn(QR_WARNING, self.text(doc))
        for amount in (0, -1, "NaN", "Infinity", "bad", 0.001):
            contract = dict(self.contract, ukupno_rsd=amount, kurs=None)
            self.assertIsNone(build_ugovor_ips_qr(contract, self.agency))
        self.assertIsNone(build_ugovor_ips_qr(self.contract, dict(self.agency, naziv="")))

    def test_given_long_fields_then_qr_limits_and_no_injected_fields(self):
        contract = copy.deepcopy(self.contract)
        contract["aranzman"].update(kljuc="123456789/" * 20, putnik="Ž" * 100 + "|R:injected")
        payload = build_ugovor_ips_qr(contract, dict(self.agency, naziv="Č" * 100 + "|P:injected"))
        fields = dict(part.split(":", 1) for part in payload.split("|"))
        self.assertLessEqual(len(fields["S"]), 35)
        self.assertLessEqual(len(fields["RO"]), 25)
        self.assertLessEqual(len(fields["P"]), 70)
        self.assertLessEqual(len(fields["N"]), 70)
        self.assertRegex(fields["R"], r"^[0-9]{18}$")
        self.assertEqual(payload.count("|R:"), 1)
        self.assertNotRegex(payload, r"^\||\|$|\|\|")

    def test_given_only_calculation_and_historical_rate_then_totals_are_not_recomputed_from_extras(self):
        contract = copy.deepcopy(self.contract)
        del contract["ukupno_eur"]
        del contract["ukupno_rsd"]
        del contract["datum_izdavanja"]
        self.assertIn("I:RSD80544,16", build_ugovor_ips_qr(contract, self.agency))
        with self.document(contract) as doc:
            text = self.text(doc)
            self.assertIn("688,00", text)
            self.assertIn("80.544,16", text)
            self.assertIn("Datum izdavanja: 15.12.2025", text)

    def test_given_optional_logo_data_url_then_logo_renders(self):
        buffer = io.BytesIO()
        Image.new("RGB", (80, 30), "navy").save(buffer, format="PNG")
        agency = dict(self.agency, logo_data_url="data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode())
        with self.document(agency=agency) as doc:
            self.assertGreaterEqual(len(doc[0].get_images()), 1)
        with self.document(agency=dict(self.agency, logo_data_url="data:image/png;base64,invalid")) as doc:
            self.assertIn("UGOVOR", self.text(doc))


if __name__ == "__main__":
    unittest.main()
