"""Contract tests for failure handling and source validation (no model calls)."""
import io
import json
import socket
import unittest
import urllib.error
from unittest.mock import patch
from qa_core import AppError, validate, messages, generate, complete, export_csv

TEXT = 'Квантизація зменшує точність зберігання ваг нейромережі.'
CARD = {'question': 'Що робить квантизація?', 'answer': 'Зменшує точність зберігання ваг.', 'evidence': TEXT}


class ContractTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate(json.dumps({'cards': [CARD]}), TEXT, 1), [CARD])

    def test_empty_and_large_input(self):
        for text in ['', 'коротко', 'a' * 3001]:
            with self.assertRaises(AppError):
                messages(text, 4)

    def test_bad_json_and_schema(self):
        for content in ['not json', '[]', '{"cards":[{}]}', '{"cards":null}']:
            with self.assertRaises(AppError):
                validate(content, TEXT, 2)

    def test_fake_evidence(self):
        card = dict(CARD, evidence='Цього немає в тексті')
        with self.assertRaisesRegex(AppError, 'відсутня'):
            validate(json.dumps({'cards': [card]}), TEXT, 1)

    def test_duplicate(self):
        with self.assertRaisesRegex(AppError, 'повторні'):
            validate(json.dumps({'cards': [CARD, CARD]}), TEXT, 2)

    def test_limit(self):
        with self.assertRaises(AppError):
            validate(json.dumps({'cards': [CARD, CARD]}), TEXT, 1)

    def test_no_facts(self):
        self.assertEqual(validate('{"cards":[]}', TEXT, 3), [])

    def test_csv_round_trip(self):
        import csv
        card = dict(CARD, answer='Рядок 1, "цитата"\nРядок 2')
        self.assertEqual(list(csv.DictReader(io.StringIO(export_csv([card])))), [card])

    def test_connection_error(self):
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError('refused')):
            with self.assertRaisesRegex(AppError, 'зв’язку'):
                complete({})

    def test_timeout(self):
        with patch('urllib.request.urlopen', side_effect=socket.timeout()):
            with self.assertRaisesRegex(AppError, 'очікування'):
                complete({})

    def test_truncation(self):
        response = {'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]}
        with patch('qa_core.complete', return_value=(response, 1.0)):
            with self.assertRaisesRegex(AppError, 'ліміту'):
                generate(TEXT)

    def test_http_error(self):
        error = urllib.error.HTTPError('local', 404, 'missing', {}, io.BytesIO(b'model not found'))
        with patch('urllib.request.urlopen', side_effect=error):
            with self.assertRaisesRegex(AppError, 'HTTP 404'):
                complete({})


if __name__ == '__main__':
    unittest.main(verbosity=2)
