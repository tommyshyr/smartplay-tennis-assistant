"""Regression tests for notifications, including restarts and partial snapshots."""

from datetime import datetime, timedelta, timezone
import tempfile
import unittest

from smartplay.availability_watch import AvailabilityWatch, event_can_notify
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

    def poll(self, rows, status="live", freshness="verified", source_time=None):
        self.now += timedelta(minutes=5)
        updated_at = source_time or self.now - timedelta(seconds=30)
        feed = {"fetched_at": self.now.isoformat(), "status": status,
                "source_updated_at": updated_at.astimezone(timezone.utc).isoformat(),
                "source_freshness": freshness,
                "slots": parse_feed(rows, self.config["play_type"])["slots"]}
        return self.watch.inspect(feed, self.config, self.now)

    def test_first_snapshot_is_silent_and_watch_uses_independent_venue_scope(self):
        venues = ("Bowen Road Tennis Court", "Hong Kong Tennis Centre", "Victoria Park")
        positives = [self.row(venue) for venue in venues]
        self.assertEqual(self.poll(positives), [])
        self.assertEqual(self.watch.available_slots, 2)
        self.poll([self.row(venue, count=0) for venue in venues])
        events = self.poll(positives)
        self.assertEqual([event["venue_id"] for event in events], ["BRTC", "HKTC"])
        self.assertEqual(self.watch.available_slots, 2)
        self.assertIn("13:00–14:00", events[0]["body"])
        self.assertIn("公开数据观察到", events[0]["title"])
        self.assertIn("数据更新 11-15 10:14:30，读取 11-15 10:15:00", events[0]["body"])

    def test_missing_and_restart_discard_prior_zero_and_preserve_notice_history(self):
        self.poll([self.row(count=0)])
        self.assertEqual(self.poll([]), [])
        self.assertEqual(self.poll([self.row()]), [])
        self.poll([self.row(count=0)])
        event = self.poll([self.row()])[0]
        self.assertEqual(self.poll([self.row(count=2)]), [])
        self.poll([self.row(count=0)])
        self.watch = AvailabilityWatch(self.store)
        self.assertEqual(self.poll([self.row()]), [])
        self.assertEqual([row["id"] for row in self.watch.events], [event["id"]])

    def test_zero_then_positive_alerts_again(self):
        self.poll([self.row(count=0)])
        first = self.poll([self.row()])[0]
        self.assertEqual(self.poll([self.row(count=0)]), [])
        reopened = self.poll([self.row()])[0]
        self.assertNotEqual(first["id"], reopened["id"])

    def test_failed_imported_and_unverified_readings_break_continuity(self):
        readings = [("stale", "stale"), ("imported", "unknown"), ("demo", "unknown"),
                    ("unavailable", "unknown"), ("live", "unknown")]
        for status, freshness in readings:
            with self.subTest(status=status, freshness=freshness):
                self.poll([self.row(count=0)])
                checked_at = self.watch.checked_at
                self.assertEqual(self.poll([self.row()], status, freshness), [])
                self.assertEqual(self.watch.checked_at, checked_at)
                self.assertEqual(self.poll([self.row()]), [])
        self.poll([self.row(count=0)])
        self.assertEqual(len(self.poll([self.row()])), 1)

    def test_new_scope_and_long_polling_gap_seed_silently(self):
        self.poll([self.row(count=0)])
        self.config["watch_venue_ids"] = ["BRTC"]
        self.assertEqual(self.poll([self.row()]), [])
        self.poll([self.row(count=0)])
        self.now += timedelta(minutes=6)
        self.assertEqual(self.poll([self.row()]), [])
        self.poll([self.row(count=0)])
        self.config["play_type"] = "doubles"
        self.assertEqual(self.poll([self.row()]), [])

    def test_same_source_version_cannot_establish_a_change(self):
        self.poll([self.row(count=0)])
        self.assertEqual(self.poll([self.row()], source_time=self.now - timedelta(seconds=30)), [])

    def test_unreleased_and_single_only_slots_excluded_for_doubles(self):
        self.config["play_type"] = "doubles"
        self.poll([
            self.row(day="2026-11-22", count=0),
            self.row("Hong Kong Tennis Centre", group="Tennis Court (Single)", count=0),
        ])
        self.assertEqual(self.poll([
            self.row(day="2026-11-22"),
            self.row("Hong Kong Tennis Centre", group="Tennis Court (Single)")
        ]), [])
        self.assertEqual(self.watch.available_slots, 0)

    def test_only_recent_notices_with_verified_source_and_upcoming_slots_can_notify(self):
        self.poll([self.row(count=0)])
        event = self.poll([self.row()])[0]
        self.assertTrue(event_can_notify(event, self.now + timedelta(seconds=60)))
        self.assertFalse(event_can_notify(event, self.now + timedelta(seconds=61)))
        self.assertFalse(event_can_notify({**event, "source_updated_at": None}, self.now))
        source_too_old = self.now - timedelta(minutes=6, seconds=1)
        self.assertFalse(event_can_notify({**event, "source_updated_at": source_too_old.isoformat()}, self.now))
        elapsed_slot = {**event["slots"][0], "date": self.now.date().isoformat(), "start": "09:00"}
        self.assertFalse(event_can_notify({**event, "slots": [elapsed_slot]}, self.now))
        self.assertFalse(event_can_notify({**event, "slots": [{}]}, self.now))
