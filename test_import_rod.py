"""Offline acceptance tests using synthetic SQL only; no database access."""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from import_rod import COLUMNS, merge_rows, parse_rows, stage_rows


HEADER = 'INSERT INTO `rod` (' + ', '.join(f'`{column}`' for column in COLUMNS) + ') VALUES\n'


def row(pk, *pairs):
    """Build an importer tuple with exactly five date/passport pairs."""
    return (pk, *(value for pair in (*pairs, *((None, None),) * (5 - len(pairs))) for value in pair))


class ParseRowsAcceptanceTests(unittest.TestCase):
    def parse_synthetic(self, sql):
        with TemporaryDirectory(prefix='test_rod_', dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / 'synthetic.sql'
            path.write_text(sql, encoding='utf-8')
            return parse_rows(path)

    def test_preserves_leading_zero_passports_and_converts_all_five_dates(self):
        values = ['42']
        expected_pairs = []
        for slot in range(5):
            values.extend((f"'1990-01-0{slot + 1} 13:14:15'", f"' 0000{slot} '"))
            expected_pairs.append((date(1990, 1, slot + 1), f'0000{slot}'))
        parsed = self.parse_synthetic(HEADER + '(' + ', '.join(values) + ');\n')
        self.assertEqual(parsed, [row(42, *expected_pairs)])

    def test_parses_multiple_rows_and_null_fields(self):
        sql = HEADER + '(1, ' + ', '.join(['NULL'] * 10) + '),\n'
        sql += "(2, NULL, '00123', " + ', '.join(['NULL'] * 8) + ');\n'
        self.assertEqual(self.parse_synthetic(sql), [row(1), row(2, (None, '00123'))])

    def test_rejects_bad_column_counts(self):
        for count in (9, 11):
            with self.subTest(field_count=count + 1):
                with self.assertRaisesRegex(ValueError, 'Pogrešan broj polja'):
                    self.parse_synthetic(HEADER + '(1, ' + ', '.join(['NULL'] * count) + ');\n')

    def test_rejects_wrong_header_column_order(self):
        wrong_header = HEADER.replace('`rodjen`, `pasos`', '`pasos`, `rodjen`', 1)
        with self.assertRaisesRegex(ValueError, 'Zaglavlje INSERT-a nije očekivano'):
            self.parse_synthetic(wrong_header + '(1, ' + ', '.join(['NULL'] * 10) + ');\n')

    def test_rejects_invalid_date_and_wrong_date_format(self):
        for born in ('2023-02-29 00:00:00', '1990-01-01', 'not-a-date'):
            with self.subTest(born=born):
                with self.assertRaises(ValueError):
                    self.parse_synthetic(HEADER + f"(1, '{born}', " + ', '.join(['NULL'] * 9) + ');\n')

    def test_rejects_empty_file(self):
        with self.assertRaisesRegex(ValueError, 'SQL izvor je nepotpun ili prazan'):
            self.parse_synthetic('')


class MergeAndStageAcceptanceTests(unittest.TestCase):
    def test_merges_complementary_null_fields_across_all_slots(self):
        birthdays = [date(1990 + slot, 1, 1) for slot in range(5)]
        passports = [f'000{slot}' for slot in range(5)]
        dates_only = row(7, *((born, None) for born in birthdays))
        passports_only = row(7, *((None, passport) for passport in passports))
        merged, conflicts = merge_rows([dates_only, passports_only, row(7)])
        self.assertEqual(conflicts, [])
        self.assertEqual(merged, {7: list(row(7, *zip(birthdays, passports))[1:])})

    def test_conflict_skips_whole_id_and_cannot_be_revived_by_later_repeats(self):
        for field in ('date', 'passport'):
            with self.subTest(field=field):
                original = row(9, (date(1990, 1, 1), '00123'), (None, '00456'))
                changed = (date(1991, 1, 1), '00123') if field == 'date' else (date(1990, 1, 1), '00999')
                conflicting = row(9, changed)
                survivor = row(10, (None, '00010'))
                merged, conflicts = merge_rows([original, survivor, conflicting, original, row(9)])
                self.assertEqual(conflicts, [9])
                self.assertEqual(merged, {10: list(survivor[1:])})
                self.assertEqual({entry['broj'] for entry in stage_rows(merged)}, {'10'})

    def test_conflict_in_last_companion_slot_removes_whole_id(self):
        original = row(8, *((None, '001') for _ in range(5)))
        conflict = row(8, *((None, None) for _ in range(4)), (None, '002'))
        self.assertEqual(merge_rows([original, conflict, original]), ({}, [8]))

    def test_stage_maps_all_slots_including_empty_slots_and_string_contract_ids(self):
        pairs = [(date(1990, 1, 1), '00001'), (None, '00002'),
                 (date(1992, 1, 1), None), (None, None), (date(1994, 1, 1), '00005')]
        merged, conflicts = merge_rows([row(42, *pairs), row(43)])
        self.assertEqual(conflicts, [])
        expected = [{'broj': '42', 'slot': slot, 'rodjen': born, 'pasos': passport}
                    for slot, (born, passport) in enumerate(pairs)]
        expected += [{'broj': '43', 'slot': slot, 'rodjen': None, 'pasos': None}
                     for slot in range(5)]
        self.assertEqual(stage_rows(merged), expected)

    def test_empty_merge_and_stage(self):
        self.assertEqual(merge_rows([]), ({}, []))
        self.assertEqual(stage_rows({}), [])


if __name__ == '__main__':
    unittest.main()
