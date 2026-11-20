"""Ugovor PDF: plaćanje mesec dana pre datumod, naziv agencije iz podešavanja, opis za ugovor uz sobu."""
import copy
import unittest
from datetime import date

import pymupdf

import test_ugovor_pdf
from ugovor_pdf import _mesec_pre, _rok_placanja, generate_ugovor_pdf, legal_clauses


class MesecPreTests(unittest.TestCase):
    def test_given_datumod_when_one_month_earlier_then_same_day_or_last_day(self):
        self.assertEqual(_mesec_pre(date(2026, 8, 30)), date(2026, 7, 30))
        self.assertEqual(_mesec_pre("2026-07-02"), date(2026, 6, 2))
        self.assertEqual(_mesec_pre(date(2026, 1, 15)), date(2025, 12, 15))
        self.assertEqual(_mesec_pre(date(2026, 3, 31)), date(2026, 2, 28))
        self.assertEqual(_mesec_pre(date(2024, 3, 31)), date(2024, 2, 29))

    def test_given_missing_datumod_then_none(self):
        self.assertIsNone(_mesec_pre(None))
        self.assertIsNone(_mesec_pre(""))


class LegalClausesTests(unittest.TestCase):
    def test_given_agency_and_date_then_clauses_use_them(self):
        clauses = legal_clauses("TEST AGENCIJA DOO", date(2026, 7, 30))
        joined = " ".join(clauses)
        self.assertIn('"TEST AGENCIJA DOO"', joined)
        self.assertNotIn("ASTRA TRAVEL", joined)
        self.assertTrue(any("PLAĆANJE 100.00% DO 30.07.2026." in c for c in clauses))


class OpisZaUgovorTests(unittest.TestCase):
    def setUp(self):
        self.base = test_ugovor_pdf.UgovorPDFAcceptance()
        self.base.setUp()

    def _text_for(self, soba_opis_ugovor):
        contract = copy.deepcopy(self.base.contract)
        if soba_opis_ugovor is None:
            contract["aranzman"].pop("soba_opis_ugovor", None)
        else:
            contract["aranzman"]["soba_opis_ugovor"] = soba_opis_ugovor
        pdf = generate_ugovor_pdf(contract, self.base.agency)
        with pymupdf.open(stream=pdf, filetype="pdf") as doc:
            return self.base.text(doc)

    def test_given_opis_za_ugovor_then_it_follows_soba_cell(self):
        text = self._text_for("Economy UT")
        self.assertIn("spratnost: 1.SPR | Economy UT", text)

    def test_given_no_opis_za_ugovor_then_soba_cell_has_no_economy(self):
        self.assertNotIn("Economy", self._text_for(None))
        self.assertNotIn("Economy", self._text_for(""))

    def test_given_datumod_and_agency_then_payment_line_and_agency_name_are_rendered(self):
        text = self._text_for(None)
        # datumod 02.07.2026 → plaćanje do 02.06.2026.; naziv agencije iz podešavanja (agency dict)
        self.assertIn("PLAĆANJE 40.00% ODMAH, OSTATAK DO 02.06.2026.", text)
        self.assertIn('"Agencija Čačak"', text)


    def test_given_ulogovan_then_name_is_in_parentheses_in_sluzbenik_label_and_mp_follows(self):
        contract = copy.deepcopy(self.base.contract)
        contract["ulogovan"] = "Marko Markovic"
        with pymupdf.open(stream=generate_ugovor_pdf(contract, self.base.agency), filetype="pdf") as doc:
            text = self.base.text(doc)
            page_text = doc[0].get_text()
        self.assertIn("Potpis službenika (Marko Markovic):", text)
        self.assertIn("M. P.", text)
        self.assertLess(text.index("Potpis službenika (Marko Markovic):"), text.index("M. P."))
        self.assertIn("Potpis stranke:", page_text)

    def test_given_no_ulogovan_then_label_has_no_parentheses(self):
        contract = copy.deepcopy(self.base.contract)
        contract.pop("ulogovan", None)
        with pymupdf.open(stream=generate_ugovor_pdf(contract, self.base.agency), filetype="pdf") as doc:
            text = self.base.text(doc)
        self.assertIn("Potpis službenika:", text)
        self.assertNotIn("Potpis službenika (", text)


    def test_given_contract_then_smer_and_ulazak_row_are_gone_and_subagent_fields_share_rows(self):
        contract = copy.deepcopy(self.base.contract)
        with pymupdf.open(stream=generate_ugovor_pdf(contract, self.base.agency), filetype="pdf") as doc:
            text = self.base.text(doc)
        self.assertNotIn("Smer:", text)
        self.assertNotIn("Ulazak / mesto polaska", text)
        self.assertIn("Naziv: ZETA TOURS | PIB: 123456789 | MB: 987654321", text)
        self.assertIn("E-mail: sub@example.test | Telefon: 0641234567", text)


class RokPlacanjaTests(unittest.TestCase):
    def test_given_u_celosti_then_deadline_is_created_date_plus_two_days(self):
        self.assertEqual(_rok_placanja({"danas": "2026-11-03", "datumod": "2027-06-10", "nacin_placanja": "u_celosti"}),
                         date(2026, 11, 5))

    def test_given_u_celosti_across_month_end_then_deadline_rolls_over(self):
        self.assertEqual(_rok_placanja({"danas": "2026-10-31", "datumod": "2027-06-10", "nacin_placanja": "u_celosti"}),
                         date(2026, 11, 2))

    def test_given_u_celosti_then_datumod_does_not_matter(self):
        self.assertEqual(_rok_placanja({"danas": "2026-11-03", "datumod": "2027-05-24", "nacin_placanja": "u_celosti"}),
                         date(2026, 11, 5))

    def test_given_delimicno_then_deadline_is_month_before_datumod(self):
        self.assertEqual(_rok_placanja({"danas": "2026-11-03", "datumod": "2027-06-24", "nacin_placanja": "delimicno"}),
                         date(2027, 5, 24))

    def test_given_nacin_not_chosen_then_deadline_is_month_before_datumod(self):
        self.assertEqual(_rok_placanja({"datumod": "2027-06-24", "nacin_placanja": None}), date(2027, 5, 24))

    def test_given_u_celosti_then_pdf_shows_created_date_plus_two_days(self):
        base = test_ugovor_pdf.UgovorPDFAcceptance()
        base.setUp()
        contract = copy.deepcopy(base.contract)
        contract["aranzman"] = dict(contract.get("aranzman") or {}, danas="2026-11-03",
                                    datumod="2027-05-24", nacin_placanja="u_celosti")
        with pymupdf.open(stream=generate_ugovor_pdf(contract, base.agency), filetype="pdf") as doc:
            text = base.text(doc)
        self.assertIn("PLAĆANJE 100.00% DO 05.11.2026.", text)


if __name__ == "__main__":
    unittest.main()
