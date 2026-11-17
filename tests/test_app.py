"""Local HTTP integration tests: no network beyond an ephemeral loopback server."""

import copy
import http.client
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from app import Application, Server
from smartplay.feed import FeedClient, HKT


def official_rows():
    # Synthetic test values in the exact observed public-feed schema, not an
    # assertion of real availability. Dates stay within the seven-day window.
    day = (datetime.now(HKT).date() + timedelta(days=1)).isoformat()
    rows = []
    for hour in (9, 10, 11):
        rows.append({
            'District_Name_EN': 'Wan Chai ', 'District_Name_TC': '灣仔區 ',
            'Venue_Name_EN': 'Hong Kong Tennis Centre', 'Venue_Name_TC': '香港網球中心',
            'Facility_Type_Name_EN': 'Tennis Court (Urban)',
            'Facility_Location_Name_EN': 'Tennis Court',
            'Available_Date': day,
            'Session_Start_Time': f'{hour:02d}:00',
            'Session_End_Time': f'{hour + 1:02d}:00',
            'Available_Courts': '2',
        })
    return rows


class ApplicationHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='smartplay-http-tests-')
        self.upstream_calls = []

        def disallowed_network(request, timeout):
            self.upstream_calls.append(request.full_url)
            raise AssertionError('This test must not request the public network')

        self.app = Application(self.temp.name, client=FeedClient(opener=disallowed_network))
        self.server = Server(0, self.app)
        self.port = self.server.server_port
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.token = self.app.csrf_token

    def tearDown(self):
        self.app.stop_event.set()
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=2)
        self.temp.cleanup()

    def request(self, method='GET', path='/api/state', payload=None, headers=None, authorized=True):
        supplied = {'Content-Type': 'application/json'}
        if authorized:
            supplied['X-CSRF-Token'] = self.token
            supplied['Origin'] = f'http://127.0.0.1:{self.port}'
        supplied.update(headers or {})
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=supplied)
            response = connection.getresponse()
            raw = response.read()
            parsed = json.loads(raw) if response.getheader('Content-Type', '').startswith('application/json') else raw.decode('utf-8')
            return response.status, parsed, dict(response.getheaders())
        finally:
            connection.close()

    def imported_state(self):
        code, state, _ = self.request('POST', '/api/import', {'data': official_rows()})
        self.assertEqual(code, 200)
        self.assertTrue(state['candidates'])
        return state

    def record(self, candidate_id, reference='TEST-RECEIPT-1', amount=114):
        return self.request('POST', '/api/bookings', {
            'candidate_id': candidate_id,
            'reference': reference,
            'amount_hkd': amount,
            'attested_paid': True,
        })

    def test_state_is_read_only_and_no_upstream_calls(self):
        for _ in range(3):
            code, state, headers = self.request(authorized=False)
            self.assertEqual(code, 200)
            self.assertEqual(state['feed']['status'], 'unavailable')
            self.assertEqual(state['candidates'], [])
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertIn("connect-src 'self'", headers['Content-Security-Policy'])
        self.assertEqual(self.upstream_calls, [])

    def test_csrf_origin_and_host_are_enforced(self):
        attacks = [
            ({}, False),
            ({'X-CSRF-Token': 'wrong'}, True),
            ({'Origin': 'https://untrusted.example'}, True),
            ({'Origin': 'null'}, True),
            ({'Host': 'untrusted.example'}, True),
        ]
        for headers, authorized in attacks:
            with self.subTest(headers=headers, authorized=authorized):
                code, _, _ = self.request('POST', '/api/mode', {'mode': 'demo'}, headers, authorized)
                self.assertEqual(code, 403)
        self.assertEqual(self.app.mode, 'live')
        code, _, _ = self.request(headers={'Host': 'untrusted.example'})
        self.assertEqual(code, 403)

    def test_config_validation_does_not_persist_invalid_values(self):
        initial = copy.deepcopy(self.app.config)
        cases = [
            {'venue_ids': []}, {'venue_ids': ['UNKNOWN']},
            {'weekdays': [True]}, {'weekdays': []},
            {'start_time': '22:00', 'end_time': '08:00'},
            {'duration_hours': 3}, {'duration_hours': True},
            {'max_hourly_hkd': -1}, {'max_hourly_hkd': 'NaN'},
            {'play_type': 'unknown'}, {'monitor_enabled': 'true'},
            {'excluded_dates': ['2026-02-30']},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                code, _, _ = self.request('POST', '/api/config', payload)
                self.assertEqual(code, 400)
                self.assertEqual(self.app.config, initial)

    def test_valid_preferences_persist_after_restart(self):
        code, state, _ = self.request('POST', '/api/config', {
            'venue_ids': ['BRTC'], 'venue_priority': ['BRTC'],
            'start_time': '08:00', 'end_time': '17:00',
            'monitor_enabled': False,
        })
        self.assertEqual(code, 200)
        restored = Application(self.temp.name, client=FeedClient())
        self.assertEqual(restored.config['venue_ids'], ['BRTC'])
        self.assertFalse(restored.config['monitor_enabled'])

    def test_simplified_labels_for_legacy_records_and_official_feed(self):
        state = self.imported_state()
        self.assertEqual(state['candidates'][0]['venue_name'], '香港网球中心')
        day = official_rows()[0]['Available_Date']
        self.app.store.add_booking({
            'id': 'legacy-booking', 'reference': 'TEST-LEGACY', 'venue_id': 'HKTC',
            'venue_name': '香港網球中心', 'date': day, 'start': '13:00', 'end': '14:00',
        })
        self.app.store.set('availability_watch', {'events': [{
            'id': 'legacy-alert', 'kind': 'availability', 'venue_id': 'BRTC',
            'created_at': datetime.now(HKT).isoformat(),
            'title': '寶雲道網球場 · 1 个时段有空位',
            'slots': [{'venue_name': '寶雲道網球場'}],
        }]})
        restored = Application(self.temp.name, client=FeedClient())
        result = restored.snapshot()
        self.assertEqual(result['bookings'][0]['venue_name'], '香港网球中心')
        self.assertEqual(result['alerts'][0]['title'], '宝云道网球场 · 1 个时段有空位')
        self.assertEqual(result['alerts'][0]['slots'][0]['venue_name'], '宝云道网球场')
        status, calendar, _ = self.request(path='/api/bookings.ics')
        self.assertEqual(status, 200)
        self.assertIn('SUMMARY:香港网球中心', calendar)

    def test_only_a_completed_refresh_changes_the_watch_baseline(self):
        now = datetime.now(HKT)
        baseline = self.app.client.snapshot(now=now)
        first_attempt = (now - timedelta(minutes=5)).isoformat(timespec='seconds')
        new_attempt = now.isoformat(timespec='seconds')
        aged = {**baseline, 'status': 'stale', 'last_attempt_at': first_attempt}
        self.app.last_watch_attempt = first_attempt
        with patch.object(self.app.client, 'refresh'), patch.object(self.app.watch, 'inspect') as inspect:
            with patch.object(self.app.client, 'snapshot', return_value=aged):
                self.app.refresh()
            inspect.assert_not_called()
            with patch.object(self.app.client, 'snapshot', return_value={
                **aged, 'last_attempt_at': new_attempt, 'refreshing': True,
            }):
                self.app.refresh()
            inspect.assert_not_called()
            failed = {**aged, 'last_attempt_at': new_attempt}
            with patch.object(self.app.client, 'snapshot', return_value=failed):
                self.app.refresh()
                self.app.refresh()
            inspect.assert_called_once()
            self.assertEqual(inspect.call_args.args[0], failed)

    def test_availability_dispatch_skips_expired_and_superseded_events(self):
        now = datetime.now(HKT)
        fetched_at = (now - timedelta(seconds=3)).isoformat(timespec='seconds')
        source_at = (now - timedelta(minutes=2)).isoformat(timespec='seconds')
        slots = [{'date': official_rows()[0]['Available_Date'], 'start': '09:00'}]
        fresh = {'id': 'test-availability', 'kind': 'availability', 'venue_id': 'HKTC',
                 'title': '测试空位', 'body': '测试正文', 'created_at': fetched_at,
                 'fetched_at': fetched_at, 'source_updated_at': source_at, 'slots': slots}
        expired = {**fresh, 'id': 'test-expired',
                   'fetched_at': (now - timedelta(minutes=2)).isoformat(timespec='seconds')}
        self.app.watch.selection = (tuple(self.app.config['watch_venue_ids']), self.app.config['play_type'])
        self.app.watch.events = [fresh, expired]
        feed = {**self.app.client.snapshot(now=now), 'status': 'live',
                'source_freshness': 'verified', 'fetched_at': fetched_at}
        delivered = []
        self.app.notifier = lambda title, body: delivered.append((title, body))
        with patch.object(self.app.client, 'snapshot', return_value=feed):
            _, state, _ = self.request()
            flags = {alert['id']: alert['notify'] for alert in state['alerts']}
            self.assertEqual(flags, {'test-availability': True, 'test-expired': False})
            self.app.deliver_events([fresh, expired])
        self.assertEqual(delivered, [(fresh['title'], fresh['body'])])

        feed = {**feed, 'fetched_at': now.isoformat(timespec='seconds')}
        with patch.object(self.app.client, 'snapshot', return_value=feed):
            self.app.deliver_events([fresh])
        self.assertEqual(len(delivered), 1)

    def test_demo_cannot_create_real_booking_or_calendar_event(self):
        code, state, _ = self.request('POST', '/api/mode', {'mode': 'demo'})
        self.assertEqual(code, 200)
        self.assertEqual(state['feed']['status'], 'demo')
        candidate = state['candidates'][0]
        code, _, _ = self.record(candidate['id'])
        self.assertEqual(code, 400)
        self.assertEqual(self.app.store.bookings(), [])
        code, calendar, _ = self.request(path='/api/bookings.ics')
        self.assertEqual(code, 200)
        self.assertNotIn('BEGIN:VEVENT', calendar)
        self.assertEqual(self.upstream_calls, [])

    def test_import_stays_snapshot_after_restart_and_does_not_fetch(self):
        state = self.imported_state()
        self.assertEqual(state['feed']['status'], 'imported')
        self.assertEqual(state['feed']['origin'], 'import')
        self.assertTrue(all(c['source'] == 'official' for c in state['candidates']))
        code, next_state, _ = self.request()
        self.assertEqual(code, 200)
        self.assertEqual(next_state['feed']['status'], 'imported')
        restored = Application(self.temp.name, client=FeedClient())
        self.assertEqual(restored.snapshot()['feed']['status'], 'imported')
        self.assertEqual(self.upstream_calls, [])

    def test_missing_paid_attestation_cannot_record(self):
        state = self.imported_state()
        code, _, _ = self.request('POST', '/api/bookings', {
            'candidate_id': state['candidates'][0]['id'],
            'reference': 'UNPAID-TEST', 'amount_hkd': 114,
        })
        self.assertEqual(code, 400)
        self.assertEqual(self.app.store.bookings(), [])

    def test_user_reported_paid_idempotent_and_overlap_rejected(self):
        state = self.imported_state()
        candidate = next(c for c in state['candidates'] if c['duration_hours'] == 2)
        overlapping = next(c for c in state['candidates'] if c['id'] != candidate['id'] and c['start'] < candidate['end'] and c['end'] > candidate['start'])
        code, after, _ = self.record(candidate['id'])
        self.assertEqual(code, 200)
        self.assertEqual(len(after['bookings']), 1)
        self.assertEqual(after['bookings'][0]['verification'], 'user_reported_paid')
        self.assertFalse(any(c['date'] == candidate['date'] and c['start'] < candidate['end'] and c['end'] > candidate['start'] for c in after['candidates']))
        code, duplicate, _ = self.record(candidate['id'])
        self.assertEqual(code, 200)
        self.assertEqual(len(duplicate['bookings']), 1)
        code, _, _ = self.record(overlapping['id'], reference='TEST-RECEIPT-2')
        self.assertEqual(code, 400)
        self.assertEqual(len(self.app.store.bookings()), 1)

    def test_booking_calendar_uses_utc_and_escapes_receipt(self):
        state = self.imported_state()
        candidate = state['candidates'][0]
        reference = 'TEST,REF;\\special'
        code, _, _ = self.record(candidate['id'], reference=reference)
        self.assertEqual(code, 200)
        code, calendar, headers = self.request(path='/api/bookings.ics')
        self.assertEqual(code, 200)
        self.assertIn('text/calendar', headers['Content-Type'])
        unfolded = calendar.replace('\r\n ', '')
        expected = datetime.fromisoformat(candidate['date'] + 'T' + candidate['start']).replace(tzinfo=HKT).astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        self.assertIn('DTSTART:' + expected, unfolded)
        self.assertIn('TEST\\,REF\\;\\\\special', unfolded)
        self.assertEqual(unfolded.count('BEGIN:VEVENT'), 1)
        self.assertNotIn('TZID=', unfolded)
        for line in calendar.split('\r\n'):
            self.assertLessEqual(len(line.encode('utf-8')), 75)

    def test_reminder_calendar_utc_channels_and_no_receipts(self):
        code, calendar, _ = self.request(path='/api/calendar.ics')
        self.assertEqual(code, 200)
        self.assertIn('BEGIN:VALARM', calendar)
        starts = re.findall(r'DTSTART:(\d{8}T\d{6}Z)', calendar)
        self.assertTrue(starts)
        self.assertTrue(all(t.endswith(('T230000Z', 'T231500Z')) for t in starts))
        self.assertNotIn('TEST-RECEIPT', calendar)

    def test_booking_delete_only_removes_local_record(self):
        state = self.imported_state()
        code, after, _ = self.record(state['candidates'][0]['id'])
        self.assertEqual(code, 200)
        booking_id = after['bookings'][0]['id']
        code, after, _ = self.request('DELETE', '/api/bookings/' + booking_id)
        self.assertEqual(code, 200)
        self.assertEqual(after['bookings'], [])
        self.assertEqual(self.upstream_calls, [])

    def test_malformed_import_preserves_previous_snapshot(self):
        state = self.imported_state()
        ids = {c['id'] for c in state['candidates']}
        code, _, _ = self.request('POST', '/api/import', {'data': [{'wrong_schema': True}]})
        self.assertEqual(code, 400)
        self.assertEqual({c['id'] for c in self.app.snapshot()['candidates']}, ids)


if __name__ == '__main__':
    unittest.main()
