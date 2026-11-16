"""Regression tests for notifications, including restarts and partial snapshots."""

from datetime import datetime, timedelta
import tempfile
import unittest

from app import Application
from smartplay.availability_watch import AvailabilityWatch
from smartplay.feed import parse_feed
from smartplay.planner import HKT
from smartplay.storage import Store


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(directory.name + "/test.sqlite3")
        self.watch = AvailabilityWatch(self.store)
        self.config = {"monitor_enabled": True, "watch_venue_ids": ["BRTC", "HKTC"],
                       "play_type": "singles", "venue_ids": ["VPTC"], "duration_hours": 2}
        self.now = datetime(2026, 11, 15, 10, 0, tzinfo=HKT)

    def row(self, venue="Bowen Road Tennis Court", count=1, day="2026-11-16", group="Tennis Court"):
        return {"Venue_Name_EN": venue, "Facility_Type_Name_EN": "Tennis Court (Urban)",
                "Facility_Location_Name_EN": group, "Available_Date": day,
                "Session_Start_Time": "13:00", "Session_End_Time": "14:00",
                "Available_Courts": str(count)}

    def poll(self, rows, status="live"):
        self.now += timedelta(minutes=5)
        feed = {"fetched_at": self.now.isoformat(), "status": status,
                "slots": parse_feed(rows, self.config["play_type"])["slots"]}
        return self.watch.inspect(feed, self.config, self.now)

    def test_independent_scope_and_positive_first_snapshot(self):
        events = self.poll([self.row(), self.row("Hong Kong Tennis Centre"), self.row("Victoria Park")])
        self.assertEqual([event["venue_id"] for event in events], ["BRTC", "HKTC"])
        self.assertEqual(self.watch.available_slots, 2)
        self.assertIn("13:00–14:00", events[0]["body"])

    def test_unchanged_missing_and_restart_do_not_duplicate(self):
        self.assertEqual(len(self.poll([self.row()])), 1)
        self.assertEqual(self.poll([self.row(count=2)]), [])
        self.assertEqual(self.poll([]), [])
        self.watch = AvailabilityWatch(self.store)
        self.assertEqual(self.poll([self.row()]), [])
        self.assertEqual(len(self.watch.events), 1)

    def test_zero_then_positive_alerts_again(self):
        first = self.poll([self.row()])[0]
        self.assertEqual(self.poll([self.row(count=0)]), [])
        reopened = self.poll([self.row()])[0]
        self.assertNotEqual(first["id"], reopened["id"])

    def test_stale_import_and_demo_never_generate_alerts(self):
        for status in ("stale", "imported", "demo", "unavailable"):
            self.assertEqual(self.poll([self.row()], status), [])
        self.assertIsNone(self.watch.checked_at)
        self.assertEqual(len(self.poll([self.row()])), 1)

    def test_unreleased_and_single_only_slots_excluded_for_doubles(self):
        self.config["play_type"] = "doubles"
        self.assertEqual(self.poll([
            self.row(day="2026-11-22"),
            self.row("Hong Kong Tennis Centre", group="Tennis Court (Single)")
        ]), [])

    def test_native_delivery_uses_event_text(self):
        event = self.poll([self.row()])[0]
        outputs = []
        app = Application(self.store.path.parent, notifier=lambda title, body: outputs.append((title, body)))
        app.deliver_events([event])
        self.assertEqual(outputs, [(event["title"], event["body"])])
