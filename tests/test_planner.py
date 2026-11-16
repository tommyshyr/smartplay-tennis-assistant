import unittest
from datetime import datetime, timezone, timedelta

from smartplay.planner import HKT, plan_slots, release_day_for, release_schedule


def slot(day="2026-11-08", start="10:00", end="11:00", venue="BRTC", n=2, **extra):
    return {"id": f"{day}-{start}", "venue_id": venue, "venue_name": venue, "date": day, "start": start, "end": end, "available_courts": n, "source": "official", **extra}


class PlannerTests(unittest.TestCase):
    def plan(self, slots, config=None, bookings=None, now="2026-11-07T12:00:00+08:00"):
        return plan_slots(slots, config or {}, bookings, now)

    def test_window_includes_day_six_excludes_seven(self):
        result = self.plan([slot("2026-11-13"), slot("2026-11-14")], {"duration_hours": 1})
        self.assertEqual([c["date"] for c in result["candidates"]], ["2026-11-13"])
        self.assertEqual(release_day_for("2026-11-13"), "2026-11-07")

    def test_latest_day_not_released_until_seven(self):
        slots = [slot("2026-11-12"), slot("2026-11-13")]
        before = self.plan(slots, {"duration_hours": 1}, now="2026-11-07T06:59:00+08:00")
        self.assertEqual([c["date"] for c in before["candidates"]], ["2026-11-12"])
        self.assertEqual(before["window"]["end"], "2026-11-12")
        after = self.plan(slots, {"duration_hours": 1}, now="2026-11-07T07:00:00+08:00")
        self.assertEqual({c["date"] for c in after["candidates"]}, {"2026-11-12", "2026-11-13"})

    def test_hong_kong_midnight_uses_hk_date(self):
        result = self.plan([slot("2026-11-07"), slot("2026-11-08")], {"duration_hours": 1}, now="2026-11-07T16:01:00+00:00")
        self.assertEqual(result["window"]["start"], "2026-11-08")
        self.assertEqual([c["date"] for c in result["candidates"]], ["2026-11-08"])

    def test_venue_counts_do_not_prove_same_court(self):
        result = self.plan([slot(), slot(start="11:00", end="12:00")])
        pair = next(c for c in result["candidates"] if c["duration_hours"] == 2)
        self.assertEqual(pair["continuity"], "unverified")
        self.assertEqual(pair["available_courts"], 2)

    def test_different_courts_do_not_form_two_hour_booking(self):
        result = self.plan([slot(court_ids=["1"]), slot(start="11:00", end="12:00", court_ids=["2"])], {"allow_one_hour_fallback": False})
        self.assertEqual(result["candidates"], [])

    def test_common_court_is_preserved(self):
        result = self.plan([slot(court_ids=["1", "2"]), slot(start="11:00", end="12:00", court_ids=["2", "3"])])
        pair = next(c for c in result["candidates"] if c["duration_hours"] == 2)
        self.assertEqual(pair["court_ids"], ["2"])
        self.assertEqual(pair["available_courts"], 1)

    def test_confirmed_booking_excludes_overlap_across_venues(self):
        bookings = [{"date": "2026-11-08", "start": "10:30", "end": "11:30", "venue_id": "HKTC", "status": "confirmed"}]
        self.assertEqual(self.plan([slot()], bookings=bookings)["candidates"], [])

    def test_cancelled_booking_does_not_block(self):
        bookings = [{"date": "2026-11-08", "start": "10:00", "end": "11:00", "status": "cancelled"}]
        self.assertEqual(len(self.plan([slot()], bookings=bookings)["candidates"]), 1)

    def test_never_fabricates_supply_from_empty_or_zero(self):
        self.assertEqual(self.plan([])["candidates"], [])
        self.assertEqual(self.plan([slot(n=0)])["candidates"], [])

    def test_bowen_winter_cutoff(self):
        self.assertEqual(self.plan([slot(start="18:00", end="19:00")])["candidates"], [])
        self.assertTrue(self.plan([slot(start="17:00", end="18:00")])["candidates"])

    def test_past_session_excluded(self):
        self.assertEqual(self.plan([slot("2026-11-07")])["candidates"], [])

    def test_doubles_filters_single_only_courts(self):
        result = self.plan([slot(venue="HKTC", court_ids=["8", "10", "11"])], {"play_type": "doubles"})
        self.assertEqual(result["candidates"], [])

    def test_duplicates_do_not_inflate_supply(self):
        result = self.plan([slot(n=2), slot(n=1)], {"duration_hours": 1})
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["available_courts"], 1)

    def test_unknown_price_does_not_pass_budget(self):
        self.assertEqual(self.plan([slot()], {"max_hourly_hkd": 60})["candidates"], [])
        self.assertTrue(self.plan([slot(hourly_rate_hkd=57)], {"max_hourly_hkd": 60})["candidates"])

    def test_demo_and_real_never_combine(self):
        self.assertEqual(self.plan([slot(), slot(start="11:00", end="12:00", source="demo")], {"allow_one_hour_fallback": False})["candidates"], [])

    def test_different_facility_groups_never_combine(self):
        slots = [slot(venue="HKTC", facility_group="Tennis Court"), slot(venue="HKTC", start="11:00", end="12:00", facility_group="Tennis Court (Single)")]
        self.assertEqual(self.plan(slots, {"allow_one_hour_fallback": False})["candidates"], [])

    def test_known_single_group_excluded_for_doubles_without_ids(self):
        self.assertEqual(self.plan([slot(venue="HKTC", facility_group="Tennis Court (Single)")], {"play_type": "doubles"})["candidates"], [])

    def test_practice_and_centre_court_not_treated_as_standard(self):
        self.assertEqual(self.plan([slot(facility_group="Tennis - Practice"), slot(facility_group="Centre Court")])["candidates"], [])

    def test_release_schedule_channel_boundaries(self):
        schedule = release_schedule("2026-11-07T07:05:00+08:00")
        self.assertEqual(schedule["play_date"], "2026-11-13")
        self.assertEqual(schedule["web_seconds"], 600)
        self.assertEqual(release_schedule("2026-11-07T07:15:00+08:00")["play_date"], "2026-11-14")

    def test_invalid_slot_is_not_available(self):
        result = self.plan([slot(start="99:00"), slot(n="bad")])
        self.assertEqual(result["candidates"], [])
        self.assertTrue(any("2 条" in w for w in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
