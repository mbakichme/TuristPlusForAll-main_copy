import tempfile
from pathlib import Path
import unittest

from import_dodatne import parse_rows, missing_rows


class DodatneTests(unittest.TestCase):
    def parse(self, content):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'dodatne.sql'
            path.write_text(content, encoding='utf-8')
            return parse_rows(path)

    def test_preserves_duplicates_and_negative_values(self):
        rows = self.parse("INSERT INTO `dodatne` (`usluga`, `eur`, `din`, `id`) VALUES\n('transfer', -12.5, 0, 10),\n('transfer', -12.5, 0, 10);\n")
        self.assertEqual(rows, [('transfer', -12.5, 0.0, 10)] * 2)

    def test_nulls_unicode_and_escaped_comma_quote(self):
        rows = self.parse("INSERT INTO `dodatne` (`usluga`, `eur`, `din`, `id`) VALUES\n('Želja, \\'sedište\\'', NULL, 2000, NULL);\n")
        self.assertEqual(rows, [("Želja, 'sedište'", None, 2000.0, None)])

    def test_multiset_idempotence(self):
        row = ('x', 1.0, 0.0, 12)
        self.assertEqual(missing_rows([row, row], [row]), [row])
        self.assertEqual(missing_rows([row, row], [row, row]), [])
        self.assertEqual(missing_rows([row], [row, row]), [])

    def test_same_contract_different_services(self):
        rows = [('a', 1.0, 0.0, 12), ('b', 2.0, 0.0, 12)]
        self.assertEqual(missing_rows(rows, rows[:1]), rows[1:])

    def test_malformed_and_empty(self):
        for content in ('', 'INSERT INTO `other` (`id`) VALUES\n(1);',
                        "INSERT INTO `dodatne` (`usluga`, `eur`, `din`, `id`) VALUES\n('x', 1, 2);",
                        "INSERT INTO `dodatne` (`usluga`, `eur`, `din`, `id`) VALUES\n('x', NaN, 2, 1);"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.parse(content)


if __name__ == '__main__':
    unittest.main()
