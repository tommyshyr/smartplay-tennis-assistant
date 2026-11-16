"""Small local SQLite store; stores preferences and user-reported receipts only."""
import json
import sqlite3
from pathlib import Path
from contextlib import contextmanager


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            con.execute('CREATE TABLE IF NOT EXISTS bookings (id TEXT PRIMARY KEY, reference TEXT UNIQUE NOT NULL, payload TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        con = sqlite3.connect(str(self.path), timeout=10)
        try:
            with con:
                yield con
        finally:
            con.close()

    def get(self, key, default=None):
        with self.connect() as con:
            row = con.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.connect() as con:
            con.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, json.dumps(value, ensure_ascii=False)))

    def bookings(self):
        with self.connect() as con:
            rows = con.execute('SELECT payload FROM bookings ORDER BY id').fetchall()
        return [json.loads(r[0]) for r in rows]

    def add_booking(self, booking):
        try:
            with self.connect() as con:
                existing = con.execute('SELECT payload FROM bookings WHERE reference=?', (booking['reference'],)).fetchone()
                if existing:
                    return json.loads(existing[0])
                # Atomic overlap check protects against two concurrent form submissions.
                con.execute('BEGIN IMMEDIATE')
                for row in con.execute('SELECT payload FROM bookings'):
                    prior = json.loads(row[0])
                    if prior['date'] == booking['date'] and prior['start'] < booking['end'] and booking['start'] < prior['end']:
                        raise ValueError('该时段与你已登记的预订重叠，请核对官方订单。')
                con.execute('INSERT INTO bookings VALUES(?,?,?)', (booking['id'], booking['reference'], json.dumps(booking, ensure_ascii=False)))
        except sqlite3.IntegrityError:
            with self.connect() as con:
                row = con.execute('SELECT payload FROM bookings WHERE reference=?', (booking['reference'],)).fetchone()
            if row:
                return json.loads(row[0])
            raise
        return booking

    def remove_booking(self, booking_id):
        with self.connect() as con:
            con.execute('DELETE FROM bookings WHERE id=?', (booking_id,))
