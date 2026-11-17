"""Ugovor PDF: agencija.opis_smestaja_ugovor = 'kratak' prikazuje samo strukturu sobe."""
import copy
import unittest

import pymupdf

import test_ugovor_pdf
from ugovor_pdf import generate_ugovor_pdf


class OpisSmestajaKratakTests(unittest.TestCase):
    def setUp(self):
        self.base = test_ugovor_pdf.UgovorPDFAcceptance()
        self.base.setUp()
        self.contract = copy.deepcopy(self.base.contract)
        self.contract["aranzman"]["soba"] = "16"
        self.contract["aranzman"]["soba_tip"] = "1/2"
        self.contract["aranzman"]["soba_opis"] = "STD"
        self.contract["aranzman"]["soba_opis_dodatno"] = "1.SPR, F+S"
        self.contract["aranzman"]["soba_opis_ugovor"] = "Economy UT"
        self.contract["aranzman"]["apartman"] = "1/2"
        self.contract["aranzman"]["gde"] = "1/3"

    def _text(self, opis_mode, struktura_mode="osnovna"):
        agency = dict(self.base.agency)
        if opis_mode is None:
            agency.pop("opis_smestaja_ugovor", None)
        else:
            agency["opis_smestaja_ugovor"] = opis_mode
        agency["struktura_ugovor"] = struktura_mode
        pdf = generate_ugovor_pdf(self.contract, agency)
        with pymupdf.open(stream=pdf, filetype="pdf") as doc:
            return self.base.text(doc)

    def test_given_osnovna_then_struktura_is_aranzman_apartman(self):
        text = self._text("dugacak", "osnovna")
        self.assertIn("struktura 1/2 STD", text)
        self.assertNotIn("1/3 STD", text)

    def test_given_promenjena_then_struktura_is_aranzman_gde(self):
        text = self._text("dugacak", "promenjena")
        self.assertIn("struktura 1/3 STD", text)
        self.assertNotIn("struktura 1/2 STD", text)

    def test_given_promenjena_without_gde_then_falls_back_to_apartman(self):
        self.contract["aranzman"]["gde"] = None
        text = self._text("kratak", "promenjena")
        self.assertIn("struktura 1/2 STD", text)

    def test_given_kratak_then_only_struktura_is_shown(self):
        text = self._text("kratak")
        self.assertIn("struktura 1/2 STD", text)
        self.assertNotIn("broj 16", text)
        self.assertNotIn("spratnost", text)
        self.assertNotIn("Economy", text)

    def test_given_dugacak_then_full_soba_cell_is_shown(self):
        text = self._text("dugacak")
        self.assertIn("broj 16", text)
        self.assertIn("struktura 1/2 STD", text)
        self.assertIn("spratnost: 1.SPR", text)

    def test_given_no_setting_then_default_is_dugacak(self):
        text = self._text(None)
        self.assertIn("broj 16", text)
        self.assertIn("spratnost: 1.SPR", text)


if __name__ == "__main__":
    unittest.main()
