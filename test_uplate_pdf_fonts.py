"""Izolovani regresioni testovi fontova bez sistemskih fontova."""
import subprocess
import sys
import unittest
from pathlib import Path

class FontTests(unittest.TestCase):
    def check_fonts(self, mode):
        code = '''
import os
from unittest.mock import patch
import pymupdf
import uplate_pdf as pdf
from reportlab.pdfbase import pdfmetrics
base = os.path.join(os.getcwd(), 'assets', 'fonts')
mode = MODE
pdf.FONT_DIR_CANDIDATES = [base] if mode != 'none' else []
exists = os.path.exists
with patch('uplate_pdf.os.path.exists', side_effect=lambda p: exists(p) and not (mode == 'partial' and p.endswith(('BoldItalic.ttf', 'BoldOblique.ttf')))):
    result = pdf.build_uplate_pdf('SAVIC DEJAN', 'Adresa', '10120/26', [], None)
assert result.startswith(b'%PDF')
doc = pymupdf.open(stream=result, filetype='pdf')
assert 'SAVIC DEJAN' in doc[0].get_text()
for name in ('Lib', 'LibB', 'LibI', 'LibBI'):
    pdfmetrics.getFont(name)
'''.replace('MODE', repr(mode))
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).parent,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_bundled_fonts_only(self):
        self.check_fonts('bundled')

    def test_partial_font_family(self):
        self.check_fonts('partial')

    def test_no_ttf_fonts(self):
        self.check_fonts('none')

if __name__ == '__main__':
    unittest.main()
