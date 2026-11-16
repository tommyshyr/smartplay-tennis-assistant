"""RFC 5545 calendar files with UTC times and folded UTF-8 lines."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256

HKT = timezone(timedelta(hours=8))


def escape(value):
    return str(value).replace('\\', '\\\\').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')


def fold(line):
    parts, part = [], ''
    for ch in line:
        if len((part + ch).encode('utf-8')) > 73:
            parts.append(part)
            part = ' ' + ch
        else:
            part += ch
    return '\r\n'.join(parts + [part])


def stamp(dt):
    return dt.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def calendar(events, now=None):
    now = now or datetime.now(HKT)
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//SmartPLAY Tennis Assistant//Calendar//ZH', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH']
    for event in events:
        lines.extend(['BEGIN:VEVENT', 'UID:' + event['id'] + '@smartplay-assistant.local', 'DTSTAMP:' + stamp(now), 'DTSTART:' + stamp(event['start']), 'DTEND:' + stamp(event['end']), 'SUMMARY:' + escape(event['title']), 'DESCRIPTION:' + escape(event.get('body', '')), 'STATUS:CONFIRMED'])
        if event.get('alarm'):
            lines.extend(['BEGIN:VALARM', 'TRIGGER:-PT5M', 'ACTION:DISPLAY', 'DESCRIPTION:' + escape(event['title']), 'END:VALARM'])
        lines.append('END:VEVENT')
    lines.append('END:VCALENDAR')
    return '\r\n'.join(fold(line) for line in lines) + '\r\n'


def release_calendar(now=None, days=30):
    now = now or datetime.now(HKT)
    events = []
    for offset in range(days):
        day = now.date() + timedelta(days=offset)
        for hour, minute, channel in [(7, 0, 'App + 智方便'), (7, 15, '网页／普通登录')]:
            start = datetime.combine(day, datetime.min.time(), HKT).replace(hour=hour, minute=minute)
            if start <= now:
                continue
            events.append({'id': f'release-{day}-{minute}', 'start': start, 'end': start + timedelta(minutes=5), 'title': f'SmartPLAY 放位：{channel}', 'body': f'今日新放位最远使用日：{day + timedelta(days=6)}。请本人通过官方渠道登录、选场及付款；本助手不替你提交交易。数据仅是快照，连续两小时须核对同一场号。', 'alarm': True})
    return calendar(events, now)


def booking_calendar(bookings, now=None):
    events = []
    for item in bookings:
        start = datetime.fromisoformat(item['date'] + 'T' + item['start']).replace(tzinfo=HKT)
        end = datetime.fromisoformat(item['date'] + 'T' + item['end']).replace(tzinfo=HKT)
        events.append({'id': sha256(item['id'].encode()).hexdigest()[:24], 'start': start, 'end': end, 'title': item['venue_name'] + ' · 网球（本人登记）', 'body': '本人根据付款收据手动登记，助手未向官方验证。请以官方预订记录为准。编号：' + item['reference'], 'alarm': True})
    return calendar(events, now)
