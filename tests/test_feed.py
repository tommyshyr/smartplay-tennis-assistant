import copy
import io
import json
import unittest
import urllib.error
from datetime import datetime, timedelta
from email.message import Message
from email.utils import format_datetime
from unittest.mock import patch

from smartplay.feed import FEED_URL, SOURCE_STALE_SECONDS, FeedClient, FeedSchemaError, HKT, parse_feed


def row(**changes):
    result = {
        "District_Name_EN": "Wan Chai ", "District_Name_TC": "灣仔區 ",
        "Venue_Name_EN": "Hong Kong Tennis Centre", "Venue_Name_TC": "香港網球中心",
        "Facility_Type_Name_EN": "Tennis Court (Urban)",
        "Facility_Location_Name_EN": "Tennis Court",
        "Available_Date": "2026-11-08", "Session_Start_Time": "17:00",
        "Session_End_Time": "18:00", "Available_Courts": "2",
    }
    result.update(changes)
    return result


class Response(io.BytesIO):
    headers = {"Last-Modified": "Sat, 07 Nov 2026 03:00:00 GMT"}

    def geturl(self):
        return FEED_URL


class FeedParserTests(unittest.TestCase):
    def test_actual_observed_fields_and_zero(self):
        actual = row(Available_Courts="0")
        actual["Venue_Phone_No."] = "25749122"
        result = parse_feed(json.dumps([actual], ensure_ascii=False))
        self.assertEqual(result["raw_row_count"], 1)
        self.assertEqual(result["slots"][0]["available_courts"], 0)
        self.assertNotIn("court_ids", result["slots"][0])
        self.assertEqual(result["slots"][0]["source"], "official")

    def test_practice_main_court_and_single_do_not_mix(self):
        rows = [
            row(), row(Facility_Location_Name_EN="Tennis Court (Single)"),
            row(Facility_Type_Name_EN="Tennis Practice Court", Facility_Location_Name_EN="Tennis - Practice"),
            row(Venue_Name_EN="Victoria Park", Venue_Name_TC="維多利亞公園", Facility_Type_Name_EN="VP Centre Court", Facility_Location_Name_EN="Tennis-Centre Ct"),
        ]
        self.assertEqual(len(parse_feed(rows)["slots"]), 2)
        self.assertEqual(len(parse_feed(rows, "doubles")["slots"]), 1)
        self.assertEqual(parse_feed(rows)["slots"][0]["facility_group"], "Tennis Court")

    def test_duplicate_counts_are_not_added_and_ids_stable(self):
        result = parse_feed([row(), row(Available_Courts="1"), row()])
        self.assertEqual(len(result["slots"]), 1)
        self.assertEqual(result["slots"][0]["available_courts"], 1)
        self.assertEqual(result["slots"][0]["id"], parse_feed([row()])["slots"][0]["id"])
        self.assertTrue(result["warnings"])

    def test_changed_schema_rejected_instead_of_empty(self):
        with self.assertRaises(FeedSchemaError):
            parse_feed({"data": [row()]})
        changed = row()
        changed["Available_Courts_Renamed"] = changed.pop("Available_Courts")
        with self.assertRaises(FeedSchemaError):
            parse_feed([changed])

    def test_malformed_values_reject_whole_refresh(self):
        for update in [{"Available_Courts": "-1"}, {"Available_Courts": "2.0"},
                       {"Available_Courts": True}, {"Available_Date": "2026-02-30"},
                       {"Session_Start_Time": "7:00"}, {"Session_End_Time": "16:00"}]:
            with self.subTest(update=update), self.assertRaises(FeedSchemaError):
                parse_feed([row(), row(**update)])

    def test_names_trimmed_and_conflict_detected(self):
        self.assertEqual(parse_feed([row(Venue_Name_EN=" Hong Kong Tennis Centre ")])["slots"][0]["venue_id"], "HKTC")
        with self.assertRaises(FeedSchemaError):
            parse_feed([row(Venue_Name_TC="寶雲道網球場")])

    def test_empty_is_valid_without_fabricating_slots(self):
        self.assertEqual(parse_feed([])["slots"], [])
        self.assertTrue(parse_feed([])["warnings"])


class FeedClientTests(unittest.TestCase):
    def setUp(self):
        self.at = datetime(2026, 11, 7, 11, 0, tzinfo=HKT)

    def test_success_and_refresh_cooldown(self):
        calls = []
        def fetch(request, timeout):
            calls.append(request.full_url)
            return Response(json.dumps([row()]).encode())
        client = FeedClient(opener=fetch)
        self.assertEqual(client.refresh(now=self.at)["status"], "live")
        client.refresh(now=self.at + timedelta(seconds=299))
        self.assertEqual(calls, [FEED_URL])
        client.refresh(now=self.at + timedelta(seconds=300))
        self.assertEqual(len(calls), 2)
        self.assertEqual(client.snapshot(now=self.at + timedelta(seconds=1000))["status"], "stale")

    def test_revalidates_same_url_and_records_source_freshness(self):
        def fetch(request, timeout):
            self.assertEqual(request.full_url, FEED_URL)
            self.assertIn("no-cache", request.get_header("Cache-control"))
            self.assertEqual(request.get_header("Pragma"), "no-cache")
            return Response(json.dumps([row()]).encode())

        client = FeedClient(opener=fetch)
        fetched = client.refresh(now=self.at + timedelta(seconds=30))
        self.assertEqual(fetched["status"], "live")
        self.assertEqual(fetched["source_freshness"], "verified")
        self.assertEqual(fetched["source_updated_at"], "2026-11-07T03:00:00+00:00")
        self.assertEqual(fetched["source_age_seconds"], 30)
        self.assertIsNone(fetched["http_age_seconds"])

        at_expiry = self.at + timedelta(seconds=SOURCE_STALE_SECONDS + 1)
        expired = client.snapshot(now=at_expiry)
        self.assertEqual(expired["status"], "stale")
        self.assertEqual(expired["source_freshness"], "stale")
        self.assertEqual(expired["slots"], fetched["slots"])

    def test_missing_or_untrusted_last_modified_is_unknown(self):
        for modified in (None, "not a date", format_datetime(self.at + timedelta(minutes=2))):
            with self.subTest(modified=modified):
                response = Response(json.dumps([row()]).encode())
                response.headers = {"Date": format_datetime(self.at), "Age": "0"}
                if modified is not None:
                    response.headers["Last-Modified"] = modified
                client = FeedClient(opener=lambda *args, **kwargs: response)
                snapshot = client.refresh(now=self.at)

                self.assertEqual(snapshot["status"], "live")
                self.assertEqual(snapshot["source_freshness"], "unknown")
                self.assertIsNone(snapshot["source_updated_at"])
                self.assertIsNone(snapshot["source_age_seconds"])
                self.assertEqual(snapshot["http_age_seconds"], 0)
                self.assertEqual(len(snapshot["slots"]), 1)

    def test_stale_source_cannot_initialize_a_live_snapshot(self):
        client = FeedClient(opener=lambda *args, **kwargs: Response(json.dumps([row()]).encode()))
        snapshot = client.refresh(now=self.at + timedelta(seconds=SOURCE_STALE_SECONDS + 1))
        self.assertEqual(snapshot["status"], "stale")
        self.assertEqual(snapshot["source_freshness"], "stale")
        self.assertIsNone(snapshot["fetched_at"])
        self.assertEqual(snapshot["slots"], [])

    def test_stale_http_cache_rejected_even_with_fresh_last_modified(self):
        recent = self.at + timedelta(minutes=5)
        too_old = Response(json.dumps([row(Available_Courts="0")]).encode())
        too_old.headers = {"Last-Modified": format_datetime(recent),
                           "Age": str(SOURCE_STALE_SECONDS + 1)}
        responses = iter([
            Response(json.dumps([row()]).encode()),
            too_old,
        ])
        client = FeedClient(opener=lambda *args, **kwargs: next(responses))
        first = client.refresh(now=self.at)
        rejected = client.refresh(now=recent)

        self.assertEqual(rejected["status"], "stale")
        self.assertEqual(rejected["source_freshness"], "stale")
        self.assertEqual(rejected["fetched_at"], first["fetched_at"])
        self.assertEqual(rejected["source_updated_at"], first["source_updated_at"])
        self.assertEqual(rejected["slots"], first["slots"])
        self.assertEqual(rejected["next_retry_at"], (recent + timedelta(minutes=5)).isoformat())

    def test_regressed_last_modified_does_not_replace_previous_snapshot(self):
        regressed = Response(json.dumps([row(Available_Courts="0")]).encode())
        regressed.headers = {"Last-Modified": format_datetime(self.at - timedelta(seconds=1))}
        recovered_at = self.at + timedelta(minutes=10)
        recovered = Response(json.dumps([row(Available_Courts="1")]).encode())
        recovered.headers = {"Last-Modified": format_datetime(recovered_at)}
        responses = iter([
            Response(json.dumps([row()]).encode()),
            regressed,
            recovered,
        ])
        client = FeedClient(opener=lambda *args, **kwargs: next(responses))
        first = client.refresh(now=self.at)
        rejected = client.refresh(now=self.at + timedelta(minutes=5))
        self.assertEqual(rejected["source_freshness"], "stale")
        self.assertEqual(rejected["slots"], first["slots"])

        current = client.refresh(now=recovered_at)
        self.assertEqual(current["status"], "live")
        self.assertEqual(current["source_freshness"], "verified")
        self.assertEqual(current["slots"][0]["available_courts"], 1)

    def test_future_timestamp_in_old_cache_cannot_block_new_network_data(self):
        client = FeedClient(opener=lambda *args, **kwargs: Response(json.dumps([row()]).encode()))
        client.restore_payload([row(Available_Courts="0")], fetched_at=self.at,
                               source_updated_at=(self.at + timedelta(days=1)).isoformat(),
                               origin="import")
        snapshot = client.refresh(now=self.at)

        self.assertEqual(snapshot["source_freshness"], "verified")
        self.assertEqual(snapshot["slots"][0]["available_courts"], 2)

    def test_success_timestamp_is_after_download_and_validation(self):
        completed = self.at + timedelta(seconds=15)
        moments = iter([self.at, completed])
        client = FeedClient(opener=lambda *args, **kwargs: Response(json.dumps([row()]).encode()))
        with patch("smartplay.feed._now", side_effect=lambda value=None: next(moments) if value is None else value):
            snapshot = client.refresh()

        self.assertEqual(snapshot["last_attempt_at"], self.at.isoformat())
        self.assertEqual(snapshot["fetched_at"], completed.isoformat())
        self.assertEqual(snapshot["source_age_seconds"], 15)
        self.assertEqual(snapshot["next_retry_at"], (self.at + timedelta(minutes=5)).isoformat())

    def test_forbidden_suspends_thirty_minutes(self):
        calls = []
        def fetch(request, timeout):
            calls.append(True)
            raise urllib.error.HTTPError(FEED_URL, 403, "Forbidden", {}, None)
        client = FeedClient(opener=fetch)
        first = client.refresh(now=self.at)
        self.assertEqual(first["status"], "unavailable")
        self.assertIn("403", first["error"])
        client.refresh(now=self.at + timedelta(seconds=1799))
        self.assertEqual(len(calls), 1)
        client.refresh(now=self.at + timedelta(seconds=1800))
        self.assertEqual(len(calls), 2)

    def test_proxy_tunnel_denial_also_backs_off(self):
        def fetch(request, timeout):
            raise urllib.error.URLError(OSError("Tunnel connection failed: 403 Forbidden"))
        client = FeedClient(opener=fetch)
        failed = client.refresh(now=self.at)
        self.assertEqual(failed["status"], "unavailable")
        self.assertEqual(failed["next_retry_at"],
                         (self.at + timedelta(minutes=30)).isoformat(timespec="seconds"))

    def test_retry_after_and_last_good_snapshot(self):
        calls = 0
        def fetch(request, timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                return Response(json.dumps([row()]).encode())
            headers = Message()
            headers["Retry-After"] = "900"
            raise urllib.error.HTTPError(FEED_URL, 429, "Too many", headers, None)
        client = FeedClient(opener=fetch)
        client.refresh(now=self.at)
        result = client.refresh(now=self.at + timedelta(seconds=300))
        self.assertEqual(result["status"], "stale")
        self.assertEqual(len(result["slots"]), 1)
        self.assertEqual(result["next_retry_at"], (self.at + timedelta(seconds=1200)).isoformat(timespec="seconds"))

    def test_bad_refresh_keeps_last_good_not_fake_empty(self):
        responses = iter([[row()], {"html": "challenge"}])
        def fetch(request, timeout):
            return Response(json.dumps(next(responses)).encode())
        client = FeedClient(opener=fetch)
        client.refresh(now=self.at)
        second = client.refresh(now=self.at + timedelta(seconds=300))
        self.assertEqual(second["status"], "stale")
        self.assertEqual(second["slots"][0]["available_courts"], 2)

    def test_import_is_never_live_and_doubles_refilters(self):
        client = FeedClient()
        client.import_payload([row(), row(Facility_Location_Name_EN="Tennis Court (Single)")], now=self.at)
        state = client.snapshot(now=self.at)
        self.assertEqual(state["status"], "imported")
        self.assertEqual(state["origin"], "import")
        self.assertEqual(len(client.snapshot("doubles", now=self.at)["slots"]), 1)
        self.assertEqual(client.snapshot(now=self.at + timedelta(minutes=11))["status"], "stale")

    def test_official_host_response_only(self):
        class WrongResponse(Response):
            def geturl(self):
                return "https://example.com/data"
        client = FeedClient(opener=lambda *a, **k: WrongResponse(json.dumps([row()]).encode()))
        self.assertEqual(client.refresh(now=self.at)["status"], "unavailable")
        self.assertIsNone(client.payload)


if __name__ == "__main__":
    unittest.main()
