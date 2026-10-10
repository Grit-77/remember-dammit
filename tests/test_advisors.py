"""Synthetic protocol fixtures, never claims of live provider compatibility."""

import copy
import importlib.util
import http.client
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from remember_dammit import retrieval
from remember_dammit.errors import VaultError
from test_retrieval import Corpus, record


class AdvisorTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('remember_dammit.advisors'), 'advisor core is missing')
        from remember_dammit import advisors
        self.api = advisors
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Corpus([record('email', 'email tercih Türkçe')], self.temp.name)
        self.requests = []

    def server(self, reply=None, status=200, mutate=None, delay=0, raw=None, drip=False,
               framing='eof'):
        requests = self.requests
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1' if framing in ('chunked', 'length-keepalive', 'length-close') else 'HTTP/1.0'
            def do_POST(handler):
                requests.append((handler.path, dict(handler.headers),
                                 json.loads(handler.rfile.read(int(handler.headers['Content-Length'])))))
                if mutate:
                    mutate()
                if delay:
                    time.sleep(delay)
                response = reply() if callable(reply) else reply
                payload = raw if raw is not None else json.dumps(response if response is not None else {
                    'model': 'laya-rl-agent', 'routing': {'model': 'multilingual'},
                    'answers': {'relevance': {'type': 'choice', 'choice': 'relevant',
                       'confidence': 0.8, 'probabilities': {'relevant': 0.8, 'irrelevant': 0.1, 'uncertain': 0.1}}},
                    'usage': {'input_tokens': 20, 'output_tokens': 0, 'truncated': False, 'state_tokens': 20,
                              'state_tokens_dropped': 0, 'truncated_questions': []}}).encode()
                handler.send_response(status)
                handler.send_header('Location', 'https://example.invalid/stolen')
                if framing in ('length', 'length-keepalive', 'length-close', 'truncated'):
                    handler.send_header('Content-Length', str(len(payload) + (100 if framing == 'truncated' else 0)))
                elif framing == 'chunked':
                    handler.send_header('Transfer-Encoding', 'chunked')
                if framing == 'length-close':
                    handler.send_header('Connection', 'close')
                handler.end_headers()
                try:
                    if framing == 'chunked':
                        for offset in range(0, len(payload), 19):
                            chunk = payload[offset:offset + 19]
                            handler.wfile.write(f'{len(chunk):x}\r\n'.encode() + chunk + b'\r\n')
                        handler.wfile.write(b'0\r\n\r\n')
                    elif drip:
                        for byte in payload:
                            handler.wfile.write(bytes([byte]))
                            handler.wfile.flush()
                            time.sleep(0.02)
                    else:
                        handler.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return {'schema': 1, 'provider': 'laya', 'mode': 'shadow',
                'endpoint': f'http://127.0.0.1:{server.server_port}/v1/systemone',
                'model': 'multilingual', 'timeout_seconds': 1, 'max_candidates': 5}

    def assess(self, **kwargs):
        return self.api.assess(self.vault, 'email', project='atlas', **kwargs)

    def jev(self):
        return {'schema': 1, 'provider': 'jev', 'mode': 'shadow',
                'endpoint': 'https://api.typesafe.ai/v1/systemone',
                'model': 'explicit-model', 'api_key_env': 'TEST_ADVISOR_KEY'}

    def test_off_preserves_baseline_and_never_reads_environment_or_connects(self):
        baseline = retrieval.search(self.vault, 'email', project='atlas', limit=5)
        with patch('os.environ.get', side_effect=AssertionError('env read')), \
             patch('http.client.HTTPConnection.connect', side_effect=AssertionError('network')):
            for config in (None, {'schema': 1, 'provider': 'off', 'mode': 'off'},
                           dict(self.jev(), mode='off')):
                result = self.assess(config=config)
                self.assertEqual(retrieval.encode_packet(result['context']), retrieval.encode_packet(baseline))
                self.assertEqual(result['assessments'], [])
                self.assertEqual(result['advisor']['status'], 'off')

    def test_real_loopback_success_keeps_baseline_and_sends_minimal_unicode_payload(self):
        config = self.server()
        baseline = retrieval.search(self.vault, 'email', project='atlas', limit=5)
        before = list(Path(self.temp.name).rglob('*'))
        with patch.dict(os.environ, {'HTTP_PROXY': 'http://example.invalid:9'}):
            result = self.assess(config=config)
        self.assertEqual(result['context'], baseline)
        self.assertEqual(result['advisor']['status'], 'ok')
        self.assertEqual(result['assessments'][0]['record_id'], 'email')
        self.assertEqual(result['assessments'][0]['choice'], 'relevant')
        self.assertEqual(before, list(Path(self.temp.name).rglob('*')))
        path, headers, payload = self.requests[0]
        self.assertEqual(path, '/v1/systemone')
        self.assertNotIn('Authorization', headers)
        self.assertEqual(set(payload), {'model', 'state', 'questions'})
        self.assertEqual(set(payload['state']['candidate']), {'id', 'title', 'body'})
        self.assertEqual(payload['state']['candidate']['body'], 'email tercih Türkçe')
        self.assertNotIn('Notes/', json.dumps(payload))

    def test_preview_does_not_read_credentials_or_connect_and_matches_send_payload(self):
        config = self.server()
        with patch('os.environ.get', side_effect=AssertionError('env read')):
            preview = self.assess(config=dict(config, api_key_env='TEST_ADVISOR_KEY'), preview=True)
        self.assertEqual(self.requests, [])
        self.assertEqual(preview['advisor']['status'], 'preview')
        self.assess(config=config)
        self.assertEqual(preview['advisor']['requests'][0]['payload'], self.requests[0][2])

    def test_jev_requires_query_opt_in_before_credentials_or_network(self):
        self.vault.records[0].update(disclosure='public', remote_allowed=True)
        with patch('os.environ.get', side_effect=AssertionError('env read')), \
             patch('http.client.HTTPSConnection.connect', side_effect=AssertionError('network')):
            result = self.assess(config=self.jev())
        self.assertEqual(result['advisor']['reason'], 'remote_query_not_allowed')

    def test_remote_preview_excludes_private_remote_disabled_and_transitive_dependents(self):
        self.vault.records = [record('private', 'email private', remote_allowed=True),
            record('blocked', 'hidden title', disclosure='public'),
            record('middle', 'middle', disclosure='public', remote_allowed=True, sources=['blocked']),
            record('derived', 'email derived', disclosure='public', remote_allowed=True, sources=['middle']),
            record('safe', 'email public', disclosure='public', remote_allowed=True)]
        with patch('os.environ.get', side_effect=AssertionError('env read')):
            result = self.assess(config=self.jev(), preview=True)
        payloads = json.dumps(result['advisor']['requests'])
        self.assertIn('email public', payloads)
        for forbidden in ('email private', 'hidden title', 'email derived', 'middle'):
            self.assertNotIn(forbidden, payloads)
        self.assertTrue(result['advisor']['egress_approval_required'])

    def test_missing_remote_key_is_sanitized_without_network(self):
        self.vault.records[0].update(disclosure='shared', remote_allowed=True)
        with patch('os.environ.get', return_value=None), \
             patch('http.client.HTTPSConnection.connect', side_effect=AssertionError('network')):
            result = self.assess(config=self.jev(), allow_remote_query=True)
        self.assertEqual(result['advisor']['reason'], 'missing_credentials')
        self.assertNotIn('TEST_ADVISOR_KEY', json.dumps(result))

    def test_source_change_during_http_discards_advice_and_refreshes_baseline(self):
        config = self.server(mutate=lambda: self.vault.records[0].update(body='new current email'))
        result = self.assess(config=config)
        self.assertEqual(result['assessments'], [])
        self.assertEqual(result['advisor']['reason'], 'source_changed')
        self.assertEqual(result['context'], retrieval.search(self.vault, 'email', project='atlas', limit=5))
        self.assertIn('new current email', json.dumps(result))

    def test_malformed_choice_nan_wrong_model_and_truncation_are_rejected(self):
        good = {'model': 'laya-rl-agent', 'routing': {'model': 'multilingual'},
            'answers': {'relevance': {'type': 'choice', 'choice': 'relevant', 'confidence': 0.8,
              'probabilities': {'relevant': 0.8, 'irrelevant': 0.1, 'uncertain': 0.1}}},
            'usage': {'input_tokens': 20, 'output_tokens': 0, 'truncated': False, 'state_tokens': 20, 'state_tokens_dropped': 0,
                      'truncated_questions': []}}
        mutations = [lambda p: p['answers']['relevance'].update(choice='invented'),
            lambda p: p['answers']['relevance'].update(confidence=float('nan')),
            lambda p: p['answers']['relevance'].update(confidence=True),
            lambda p: p['answers']['relevance']['probabilities'].update(invented=0),
            lambda p: p['routing'].update(model='wrong'),
            lambda p: p['usage'].update(truncated=True),
            lambda p: p.update(candidate_id='unknown')]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                response = copy.deepcopy(good)
                mutate(response)
                result = self.assess(config=self.server(reply=response))
                self.assertEqual(result['assessments'], [])
                self.assertEqual(result['advisor']['reason'], 'invalid_response')

    def test_http_error_redirect_oversize_and_timeout_preserve_baseline(self):
        for args in ({'status': 302}, {'status': 401, 'raw': b'secret provider body'},
                     {'raw': b'x' * 70000}, {'raw': b'not JSON'}, {'delay': 0.3}):
            with self.subTest(args=args):
                config = self.server(**args)
                if 'delay' in args:
                    config['timeout_seconds'] = 0.05
                result = self.assess(config=config)
                self.assertEqual(result['advisor']['status'], 'degraded')
                self.assertEqual(result['assessments'], [])
                self.assertEqual(result['context']['records'][0]['id'], 'email')
                self.assertNotIn('secret provider body', json.dumps(result))

    def test_config_rejects_remote_local_endpoints_unknown_keys_and_boolean_numbers(self):
        config = self.server()
        invalid = [dict(config, endpoint=e) for e in (
            'http://localhost:9000/v1/systemone', 'https://127.0.0.1/v1/systemone',
            'http://127.0.0.1.evil:9/v1/systemone', 'http://user@127.0.0.1:9/v1/systemone',
            'http://127.0.0.1:9/v1/systemone?q=x', 'http://example.org/v1/systemone')]
        invalid.extend([dict(config, timeout_seconds=True), dict(config, timeout_seconds=16),
            dict(config, max_candidates=True), dict(config, max_candidates=6),
            dict(config, api_key='secret'), dict(config, mode='assist'),
            dict(config, api_key_env='BAD NAME'), dict(config, model=''),
            dict(self.jev(), endpoint='https://example.org/v1/systemone')])
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(VaultError):
                self.api.validate_config(candidate)

    def test_external_config_load_is_bounded_and_never_loads_inside_vault(self):
        vault_root = Path(self.temp.name) / 'vault'
        vault_root.mkdir()
        inside = vault_root / 'config.json'
        inside.write_text('{"schema":1,"provider":"off","mode":"off"}')
        with self.assertRaises(VaultError):
            self.api.load_config(inside, vault_root)
        outside = Path(self.temp.name) / 'config.json'
        outside.write_text(inside.read_text())
        self.assertEqual(self.api.load_config(outside, vault_root)['provider'], 'off')
        outside.write_text(' ' * 20000)
        with self.assertRaises(VaultError):
            self.api.load_config(outside, vault_root)

    def test_invalid_numeric_unicode_and_null_configs_have_safe_errors(self):
        config = self.server()
        for change in ({'timeout_seconds': 10 ** 1000}, {'timeout_seconds': float('nan')},
                       {'model': '\ud800'}, {'schema': True}):
            with self.subTest(change=change), self.assertRaises(VaultError):
                self.api.validate_config(dict(config, **change))
        outside = Path(self.temp.name) / 'null.json'
        outside.write_text('null')
        with self.assertRaises(VaultError):
            self.api.load_config(outside, Path(self.temp.name) / 'vault')

    def test_real_vault_bytes_remain_unchanged_and_optional_auth_stays_in_header(self):
        from remember_dammit.storage import Vault
        vault = Vault.initialize(Path(self.temp.name) / 'vault')
        vault.put(title='email', body='email private owner preference', scope='project:atlas')
        before = {p.relative_to(vault.root): p.read_bytes() for p in vault.root.rglob('*') if p.is_file()}
        config = dict(self.server(), api_key_env='SYNTHETIC_LAYA_TEST_KEY')
        with patch.dict(os.environ, {'SYNTHETIC_LAYA_TEST_KEY': 'synthetic-test-token'}):
            result = self.api.assess(vault, 'email', project='atlas', config=config)
        self.assertEqual(result['advisor']['status'], 'ok')
        after = {p.relative_to(vault.root): p.read_bytes() for p in vault.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(self.requests[0][1]['Authorization'], 'Bearer synthetic-test-token')
        self.assertNotIn('synthetic-test-token', json.dumps(result))

    def test_request_count_is_bounded_and_later_failure_discards_partial_advice(self):
        self.vault.records = [record(f'n{n}', 'email preference') for n in range(8)]
        config = dict(self.server(), max_candidates=2)
        result = self.assess(config=config)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(len(result['assessments']), 2)
        self.requests.clear()
        config = self.server(reply=lambda: None if len(self.requests) == 1 else {'model': 'invalid'})
        result = self.assess(config=config)
        self.assertEqual(result['assessments'], [])
        self.assertEqual(result['advisor']['reason'], 'invalid_response')
        self.assertEqual(len(self.requests), 2)

    def test_local_dependency_scope_is_transitive_and_payload_oversize_never_connects(self):
        self.vault.records = [record('secret', 'hidden', scope='project:other'),
            record('middle', 'email middle', sources=['secret']),
            record('claim', 'email claim', sources=['middle'])]
        config = self.server()
        result = self.assess(config=config)
        self.assertEqual(result['context']['records'], [])
        self.assertEqual(self.requests, [])
        self.vault.records = [record('large', 'email ' + '\u754c' * 3000)]
        result = self.assess(config=config)
        self.assertEqual(result['advisor']['reason'], 'request_too_large')
        self.assertEqual(self.requests, [])

    def test_duplicate_response_keys_and_missing_usage_truncation_are_rejected(self):
        result = self.assess(config=self.server(raw=b'{"model":"a","model":"b"}'))
        self.assertEqual(result['advisor']['reason'], 'invalid_response')
        response = {'model': 'laya-rl-agent', 'routing': {'model': 'multilingual'},
            'answers': {'relevance': {'type': 'choice', 'choice': 'uncertain', 'confidence': 0.2,
            'probabilities': {'relevant': 0.1, 'irrelevant': 0.1, 'uncertain': 0.8}}},
            'usage': {'input_tokens': 20, 'output_tokens': 0}}
        result = self.assess(config=self.server(reply=response))
        self.assertEqual(result['advisor']['reason'], 'invalid_response')

    def test_slow_dns_and_slow_drip_obey_absolute_call_deadline_without_late_send(self):
        config = dict(self.server(), timeout_seconds=0.05)
        original = socket.getaddrinfo
        def slow_lookup(*args, **kwargs):
            time.sleep(0.25)
            return original(*args, **kwargs)
        with patch('socket.getaddrinfo', side_effect=slow_lookup):
            start = time.monotonic()
            result = self.assess(config=config)
            elapsed = time.monotonic() - start
        self.assertEqual(result['advisor']['reason'], 'timeout')
        self.assertLess(elapsed, 0.2)
        time.sleep(0.3)
        self.assertEqual(self.requests, [])
        config = dict(self.server(drip=True), timeout_seconds=0.08)
        start = time.monotonic()
        result = self.assess(config=config)
        self.assertEqual(result['advisor']['reason'], 'timeout')
        self.assertLess(time.monotonic() - start, 0.3)

    def test_batch_deadline_discards_partial_results_and_deep_json_config_is_safe(self):
        self.vault.records = [record('a', 'email one'), record('b', 'email two')]
        config = self.server(delay=0.075)
        with patch.object(self.api, 'MAX_BATCH_SECONDS', 0.1):
            result = self.assess(config=config)
        self.assertEqual(result['assessments'], [])
        self.assertEqual(result['advisor']['status'], 'degraded')
        outside = Path(self.temp.name) / 'deep.json'
        outside.write_text('[' * 1200 + '0' + ']' * 1200)
        with self.assertRaises(VaultError):
            self.api.load_config(outside, Path(self.temp.name) / 'vault')

    def test_cancelled_request_boundary_cannot_reconnect_or_send_authorization(self):
        config = dict(self.server(), timeout_seconds=0.05, api_key_env='SYNTHETIC_LAYA_TEST_KEY')
        original = http.client.HTTPConnection.request
        def delayed_request(connection, *args, **kwargs):
            time.sleep(0.12)
            return original(connection, *args, **kwargs)
        with patch.dict(os.environ, {'SYNTHETIC_LAYA_TEST_KEY': 'synthetic-test-token'}), \
             patch('http.client.HTTPConnection.request', new=delayed_request):
            result = self.assess(config=config)
        self.assertEqual(result['advisor']['reason'], 'timeout')
        self.assertEqual(result['assessments'], [])
        self.assertEqual(self.requests, [], 'timeout must prevent implicit reconnect and all late POSTs')

    def test_late_watchdog_cannot_send_authorization_after_absolute_deadline(self):
        received = threading.Event()
        config = dict(self.server(mutate=received.set), timeout_seconds=0.05,
                      api_key_env='SYNTHETIC_LAYA_TEST_KEY')
        watchdog_due, release_watchdog = threading.Event(), threading.Event()
        original_timer = threading.Timer
        original_request = http.client.HTTPConnection.request

        def delayed_timer(interval, callback):
            def scheduled_late():
                watchdog_due.set()
                if release_watchdog.wait(5):
                    callback()
            return original_timer(interval, scheduled_late)

        def request_after_deadline(connection, *args, **kwargs):
            # Reach the deadline without relying on the watchdog thread having
            # executed cancellation. The actual loopback send remains real.
            self.assertTrue(watchdog_due.wait(5), 'fixture watchdog did not reach its deadline')
            return original_request(connection, *args, **kwargs)

        try:
            with patch.dict(os.environ, {'SYNTHETIC_LAYA_TEST_KEY': 'synthetic-test-token'}), \
                 patch('remember_dammit.advisors.threading.Timer', new=delayed_timer), \
                 patch('http.client.HTTPConnection.request', new=request_after_deadline):
                result = self.assess(config=config)
            received.wait(0.1)
            self.assertEqual(result['advisor']['reason'], 'timeout')
            self.assertEqual(result['assessments'], [])
            self.assertEqual(self.requests, [], 'a late watchdog must not permit an expired authorized POST')
        finally:
            release_watchdog.set()

    def test_complete_content_length_and_chunked_responses_are_valid_advice(self):
        for framing in ('length', 'length-keepalive', 'length-close', 'chunked', 'eof'):
            with self.subTest(framing=framing):
                result = self.assess(config=self.server(framing=framing))
                self.assertEqual(result['advisor']['status'], 'ok')
                self.assertEqual(result['assessments'][0]['choice'], 'relevant')

    def test_truncated_content_length_rejects_even_a_valid_json_prefix(self):
        result = self.assess(config=self.server(framing='truncated'))
        self.assertEqual(result['advisor']['status'], 'degraded')
        self.assertEqual(result['assessments'], [])
        self.assertEqual(result['context']['records'][0]['id'], 'email')


if __name__ == '__main__':
    unittest.main()
