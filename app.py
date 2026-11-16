#!/usr/bin/env python3
"""Local-only SmartPLAY assisted planner. Python 3.11+, no third-party packages."""
from __future__ import annotations

import argparse
from collections import deque
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import secrets
import threading
from urllib.parse import urlsplit
import uuid

from smartplay.planner import DEFAULT_CONFIG, HKT, VENUES, plan_slots, release_schedule
from smartplay.feed import FeedClient
from smartplay.storage import Store
from smartplay.calendar_export import release_calendar, booking_calendar
from smartplay.availability_watch import AvailabilityWatch, DEFAULT_WATCH_VENUES
from smartplay.desktop_notifications import desktop_channel, notify_desktop

ROOT = Path(__file__).resolve().parent


def validate_config(payload):
    if not isinstance(payload, dict):
        raise ValueError('设置必须是 JSON 对象。')
    cfg = {**DEFAULT_CONFIG, 'monitor_enabled': True,
           'watch_venue_ids': list(DEFAULT_WATCH_VENUES), **payload}
    ids = {v['id'] for v in VENUES}
    for key in ('venue_ids', 'venue_priority', 'watch_venue_ids'):
        if (not isinstance(cfg[key], list)
                or any(not isinstance(venue, str) for venue in cfg[key])
                or len(cfg[key]) != len(set(cfg[key])) or not set(cfg[key]) <= ids):
            raise ValueError('场地列表无效。')
    if not cfg['venue_ids']:
        raise ValueError('请至少选择一个场地。')
    if not isinstance(cfg['weekdays'], list) or any(type(d) is not int or d not in range(7) for d in cfg['weekdays']) or not cfg['weekdays']:
        raise ValueError('请至少选择一天。')
    for key in ('holiday_dates', 'excluded_dates'):
        if not isinstance(cfg[key], list) or len(cfg[key]) > 500:
            raise ValueError('日期列表无效。')
        for d in cfg[key]:
            date.fromisoformat(d)
    for key in ('monitor_enabled', 'allow_one_hour_fallback'):
        if type(cfg[key]) is not bool:
            raise ValueError('开关值必须为 true 或 false。')
    if cfg['play_type'] not in ('singles', 'doubles'):
        raise ValueError('请选择单打或双打。')
    if isinstance(cfg['duration_hours'], bool) or cfg['duration_hours'] not in (1, 2):
        raise ValueError('时长只支持一或两小时。')
    if isinstance(cfg['max_hourly_hkd'], bool):
        raise ValueError('价格上限无效。')
    budget = float(cfg['max_hourly_hkd'])
    if not math.isfinite(budget) or not 0 <= budget <= 10000:
        raise ValueError('价格上限无效。')
    cfg['max_hourly_hkd'] = budget
    plan_slots([], cfg)
    return {k: cfg[k] for k in [*DEFAULT_CONFIG, 'monitor_enabled', 'watch_venue_ids']}


def demo_slots(now):
    """Synthetic rows always remain explicitly demo, and cannot create receipts."""
    result = []
    for offset in range(1, 7):
        day = (now.date() + timedelta(days=offset)).isoformat()
        for i, venue in enumerate(VENUES):
            for h in range(8 + i, 12 + i):
                result.append({'id': f'demo-{venue["id"]}-{day}-{h}', 'venue_id': venue['id'], 'venue_name': venue['name'], 'date': day, 'start': f'{h:02d}:00', 'end': f'{h + 1:02d}:00', 'available_courts': 1 + (i % 3), 'source': 'demo', 'facility_group': 'Tennis Court'})
    return result


class Application:
    def __init__(self, data_dir, client=None, notifier=notify_desktop):
        self.store = Store(Path(data_dir) / 'assistant.sqlite3')
        self.config = validate_config(self.store.get('config', {}))
        self.mode = self.store.get('mode', 'live')
        self.client = client or FeedClient()
        self.csrf_token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.alerts = deque(maxlen=60)
        self.alert_ids = set()
        self.watch = AvailabilityWatch(self.store)
        self.notifier = notifier
        self.native_delivery = desktop_channel()
        self.history = {}
        self.last_tick = datetime.now(HKT)
        cached = self.store.get('public_feed')
        if cached:
            # Restore its original timestamp. Restoring a snapshot never makes it live.
            try:
                original_time = datetime.fromisoformat(cached['fetched_at'])
                self.client.restore_payload(cached['payload'], fetched_at=original_time, source_updated_at=cached.get('source_updated_at'), origin='import')
            except (ValueError, TypeError, KeyError):
                pass

    def add_alert(self, key, title, body):
        if key in self.alert_ids:
            return
        self.alert_ids.add(key)
        self.alerts.appendleft({'id': key, 'kind': 'release' if key.startswith('release-') else 'status',
                                'title': title, 'body': body, 'created_at': datetime.now(HKT).isoformat()})
        if len(self.alert_ids) > 5000:
            self.alert_ids = {a['id'] for a in self.alerts}

    def snapshot(self):
        with self.lock:
            now = datetime.now(HKT)
            config = dict(self.config)
            mode = self.mode
            feed = self.client.snapshot(play_type=config['play_type'], now=now)
            watch_ready = (config['monitor_enabled'] and feed['status'] == 'live'
                           and self.watch.checked_at == feed.get('fetched_at')
                           and self.watch.selection == (tuple(config['watch_venue_ids']), config['play_type'])
                           and bool(self.watch.covered_venues))
            alerts = sorted([*self.watch.events, *self.alerts],
                            key=lambda alert: alert['created_at'], reverse=True)[:60]
            monitor = {
                'venue_ids': config['watch_venue_ids'],
                'ready': watch_ready,
                'available_slots': self.watch.available_slots if watch_ready else None,
                'covered_venue_ids': self.watch.covered_venues if watch_ready else [],
                'last_checked_at': self.watch.checked_at,
                'native_delivery': self.native_delivery,
                'last_notice_at': self.watch.events[0]['created_at'] if self.watch.events else None,
            }
            rows = demo_slots(now) if mode == 'demo' else feed.get('slots', [])
            if mode == 'demo':
                feed = {**feed, 'status': 'demo', 'row_count': len(rows), 'error': None}
            bookings = self.store.bookings()
            plan = plan_slots(rows, config, bookings, now)
            candidates = plan['candidates']
            for c in candidates:
                self.history[c['id']] = {**c, '_seen_at': now.isoformat()}
            cutoff = (now - timedelta(days=1)).isoformat()
            self.history = {k: c for k, c in self.history.items() if c['_seen_at'] > cutoff}
            release = release_schedule(now)
            release.update({'app_at': release['app_iam_smart'], 'web_at': release['web'], 'new_play_date': release['play_date']})
            warnings = list(plan['warnings'])
            warnings.extend(feed.get('warnings', []))
            if mode == 'demo':
                warnings.insert(0, '正在显示人工生成的演示数据，不能据此订场或登记真实预订。')
            if feed['status'] in ('unavailable', 'stale', 'imported') and mode != 'demo':
                warnings.insert(0, '当前为空场快照或数据连接待恢复；不是实时锁场，请到官方 App 核对。')
            return {'now': now.isoformat(), 'mode': mode, 'config': config, 'venues': VENUES, 'feed': {k: v for k, v in feed.items() if k != 'slots'}, 'candidates': candidates, 'warnings': warnings, 'bookings': bookings, 'release': release, 'alerts': alerts, 'monitor': monitor, 'csrf_token': self.csrf_token}

    def refresh(self):
        with self.lock:
            play_type = self.config['play_type']
        # Network waits do not hold the application lock or block the dashboard.
        self.client.refresh(play_type=play_type)
        with self.client.lock:
            refreshed = self.client.snapshot(play_type=play_type)
            if refreshed['status'] == 'live' and refreshed.get('fetched_at') != self.store.get('cached_feed_timestamp'):
                self.store.set('public_feed', {'payload': self.client.payload, 'fetched_at': refreshed['fetched_at'], 'source_updated_at': refreshed.get('source_updated_at')})
                self.store.set('cached_feed_timestamp', refreshed['fetched_at'])
        with self.lock:
            feed = self.client.snapshot(play_type=self.config['play_type'])
            events = self.watch.inspect(feed, self.config, datetime.now(HKT))
        if events and self.native_delivery == 'windows':
            threading.Thread(target=self.deliver_events, args=(events,), daemon=True).start()
        return self.snapshot()

    def deliver_events(self, events):
        for event in events:
            self.notifier(event['title'], event['body'])

    def import_feed(self, payload):
        with self.lock:
            self.client.import_payload(payload)
            self.store.set('public_feed', {'payload': payload, 'fetched_at': datetime.now(HKT).isoformat()})
            self.mode = 'live'
            self.store.set('mode', 'live')
            return self.snapshot()

    def record_booking(self, payload):
        with self.lock:
            if self.mode == 'demo':
                raise ValueError('演示数据不能登记为真实预订。')
            if payload.get('attested_paid') is not True:
                raise ValueError('请先确认你已在官方渠道付款成功。')
            self.snapshot()
            candidate = self.history.get(payload.get('candidate_id'))
            if not candidate or candidate.get('source') == 'demo':
                raise ValueError('候选记录已过期，请刷新后重新选择；不会替你提交交易。')
            reference = str(payload.get('reference', '')).strip()
            if not 3 <= len(reference) <= 120 or any(ord(c) < 32 for c in reference):
                raise ValueError('请输入有效的官方收据／订单编号（3–120 字符）。')
            amount = float(payload.get('amount_hkd', 0))
            if not math.isfinite(amount) or not 0 <= amount <= 10000:
                raise ValueError('付款金额无效。')
            # This is an attestation, never a claim that the assistant verified LCSD.
            booking = {k: candidate[k] for k in ('venue_id', 'venue_name', 'date', 'start', 'end', 'duration_hours')}
            booking.update({'id': str(uuid.uuid4()), 'reference': reference, 'amount_hkd': amount, 'status': 'confirmed', 'verification': 'user_reported_paid', 'created_at': datetime.now(HKT).isoformat()})
            self.store.add_booking(booking)
            return self.snapshot()

    def tick(self, now=None):
        now = now or datetime.now(HKT)
        previous = self.last_tick
        self.last_tick = now
        # Sleep recovery emits one catch-up notice; never replays missed transactions.
        for h, m, label in [(6, 55, '五分钟后 App 放位'), (7, 0, 'App + 智方便可以订场'), (7, 15, '网页／普通登录开放')]:
            at = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if previous < at <= now:
                late = (now - at).total_seconds() > 120
                self.add_alert(f'release-{at.date()}-{h}-{m}', ('错过提醒：' if late else '') + label, '香港时间。新放位最远使用日：' + str(at.date() + timedelta(days=6)) + '；请本人登录官方渠道并完成付款。')

    def run_monitor(self):
        while not self.stop_event.is_set():
            try:
                with self.lock:
                    self.tick()
                    enabled = self.config['monitor_enabled']
                if enabled:
                    self.refresh()
            except Exception:
                # A failing network must not terminate reminder scheduling.
                with self.lock:
                    self.add_alert('monitor-error', '数据更新暂时失败', '请查看数据状态，或从官方公开数据文件手动导入。')
            self.stop_event.wait(15)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port, application):
        super().__init__(('127.0.0.1', port), Handler)
        self.app = application


class Handler(BaseHTTPRequestHandler):
    server_version = 'SmartPLAYAssistant/1.0'

    def log_message(self, *_):
        pass  # Do not log receipts or imported data.

    def valid_host(self):
        expected = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        return self.headers.get('Host', '') in expected

    def send(self, status, payload, mime='application/json; charset=utf-8', filename=None):
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8') if mime.startswith('application/json') else payload if isinstance(payload, bytes) else payload.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if filename:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self.valid_host():
            return self.send(403, {'error': 'Invalid host'})
        path = urlsplit(self.path).path
        if path == '/api/state':
            return self.send(200, self.server.app.snapshot())
        if path == '/api/calendar.ics':
            return self.send(200, release_calendar(), 'text/calendar; charset=utf-8', 'smartplay-reminders.ics')
        if path == '/api/bookings.ics':
            return self.send(200, booking_calendar(self.server.app.store.bookings()), 'text/calendar; charset=utf-8', 'smartplay-bookings.ics')
        files = {'/': ('web/index.html', 'text/html; charset=utf-8'), '/app.js': ('web/app.js', 'application/javascript; charset=utf-8'), '/style.css': ('web/style.css', 'text/css; charset=utf-8'), '/research.css': ('web/research.css', 'text/css; charset=utf-8'), '/research.html': ('docs/research.html', 'text/html; charset=utf-8')}
        if path not in files:
            return self.send(404, {'error': 'Not found'})
        name, mime = files[path]
        target = ROOT / name
        if not target.is_file():
            return self.send(404, {'error': 'File unavailable'})
        return self.send(200, target.read_bytes(), mime)

    def do_POST(self):
        self.mutate()

    def do_DELETE(self):
        self.mutate()

    def mutate(self):
        app = self.server.app
        # Consume a bounded body before rejecting authentication. On Windows,
        # closing with unread POST bytes can reset the socket before the client
        # receives the 403 response.
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return self.send(400, {'error': 'Invalid content length'})
        if length < 0 or length > 8 * 1024 * 1024:
            return self.send(413, {'error': '文件过大。最多 8 MB。'})
        self.connection.settimeout(5)
        try:
            raw_body = self.rfile.read(length)
        except TimeoutError:
            return self.send(408, {'error': 'Request body timed out'})
        origin = self.headers.get('Origin')
        allowed = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
        if not self.valid_host() or (origin and origin not in allowed) or not secrets.compare_digest(self.headers.get('X-CSRF-Token', ''), app.csrf_token):
            return self.send(403, {'error': '请从本机助手页面操作。'})
        try:
            if length and self.headers.get_content_type() != 'application/json':
                return self.send(415, {'error': '仅支持 JSON。'})
            payload = json.loads(raw_body.decode('utf-8')) if length else {}
            if not isinstance(payload, dict):
                raise ValueError('请输入 JSON 对象。')
            path = urlsplit(self.path).path
            if path == '/api/config' and self.command == 'POST':
                config = validate_config(payload)
                with app.lock:
                    app.config = config
                    app.store.set('config', config)
                result = app.snapshot()
            elif path == '/api/refresh' and self.command == 'POST':
                result = app.refresh()
            elif path == '/api/mode' and self.command == 'POST':
                if payload.get('mode') not in ('live', 'demo'):
                    raise ValueError('模式无效。')
                with app.lock:
                    app.mode = payload['mode']
                    app.store.set('mode', app.mode)
                result = app.snapshot()
            elif path == '/api/import' and self.command == 'POST':
                imported = payload.get('data')
                if isinstance(imported, str):
                    imported = json.loads(imported)
                result = app.import_feed(imported)
            elif path == '/api/bookings' and self.command == 'POST':
                result = app.record_booking(payload)
            elif path.startswith('/api/bookings/') and self.command == 'DELETE':
                booking_id = path.removeprefix('/api/bookings/')
                uuid.UUID(booking_id)
                app.store.remove_booking(booking_id)
                result = app.snapshot()
            else:
                return self.send(404, {'error': 'Not found'})
            self.send(200, result)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            self.send(400, {'error': str(exc)[:220]})
        except Exception:
            self.send(500, {'error': '操作未完成，请重试。未向官方提交任何预订。'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--data-dir', default=str(ROOT / 'data'))
    args = parser.parse_args()
    application = Application(args.data_dir)
    try:
        server = Server(args.port, application)
    except OSError:
        print('Port unavailable. Is another assistant already running? http://127.0.0.1:' + str(args.port))
        return 1
    monitor = threading.Thread(target=application.run_monitor, name='public-data-monitor', daemon=True)
    monitor.start()
    print('SmartPLAY Assistant: http://127.0.0.1:' + str(args.port), flush=True)
    print('Keep this program running and your computer awake for monitoring. Ctrl+C to stop.', flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        application.stop_event.set()
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
