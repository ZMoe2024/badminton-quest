import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from badminton_reservation.loader_templates import extract_templates, read_string
from badminton_reservation.ecn_bootstrap import BootstrapError
from badminton_reservation.ecn_bootstrap_loader import generate_bootstrap_source

ASSETS = Path(__file__).resolve().parents[1] / 'assets'


class LoaderTemplateTests(unittest.TestCase):
    def test_unknown_hash_and_changed_variable_name_need_no_registration(self):
        pairs = [('loader-literals.json', 189168), ('loader-literals-db58ba62.json', 290841)]
        for file, expected_length in pairs:
            reference = [v for v in json.loads((ASSETS / file).read_text(encoding='utf-8')) if v['left'] == '_$el']
            source = ';'.join('renamedVariable=' + json.dumps(v['value']) for v in reference)
            actual, first_hash = extract_templates(source.encode())
            changed, second_hash = extract_templates(('/* new session script */\n' + source).encode())
            self.assertNotEqual(first_hash, second_hash)
            self.assertEqual(actual, reference)
            self.assertEqual(changed, reference)
            self.assertEqual(len(generate_bootstrap_source(1, literals=actual)), expected_length)

    def test_escapes_and_utf16(self):
        value, _ = read_string(r'"\x41\u0042\101\n\v"', 0)
        self.assertEqual(value, 'ABA\n\v')
        value, _ = read_string('"😀"', 0)
        self.assertEqual([ord(c) for c in value], [0xD83D, 0xDE00])

    def test_comments_strings_and_regex_are_not_assignments(self):
        source = '/* x="' + 'a' * 12000 + '";x="' + 'b' * 300 + '" */'
        source += '''var example="x='not an assignment'"; var re=/['\"]/;'''
        with self.assertRaises(BootstrapError): extract_templates(source.encode())

    def test_ambiguous_or_broken_data_rejected(self):
        source = ';'.join(f'{name}=' + json.dumps(value) for name in ('a', 'b') for value in ('a' * 12000, 'b' * 300))
        for text in [source, 'x="broken', '/* broken', 'x=`unsupported`']:
            with self.assertRaises(BootstrapError): extract_templates(text.encode())


if __name__ == '__main__': unittest.main()
