"""Track upcoming availability from successful official feed refreshes."""

from datetime import datetime
from hashlib import sha256

from smartplay.feed import MIN_REFRESH_SECONDS, SOURCE_CLOCK_SKEW_SECONDS, SOURCE_STALE_SECONDS
from smartplay.planner import HKT, plan_slots, venue_label


DEFAULT_WATCH_VENUES = ("BRTC", "HKTC")
MAX_OBSERVATION_GAP_SECONDS = 2 * MIN_REFRESH_SECONDS
MAX_DELIVERY_DELAY_SECONDS = 60


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    return timestamp if timestamp.tzinfo is not None else None


def event_can_notify(event, now):
    """Suppress queued notices once their snapshot or displayed slots age out."""
    fetched_at = _timestamp(event.get("fetched_at"))
    updated_at = _timestamp(event.get("source_updated_at"))
    if not fetched_at or not updated_at:
        return False
    if not 0 <= (now - fetched_at).total_seconds() <= MAX_DELIVERY_DELAY_SECONDS:
        return False
    if not -SOURCE_CLOCK_SKEW_SECONDS <= (now - updated_at).total_seconds() <= SOURCE_STALE_SECONDS:
        return False
    slots = event.get("slots", [])
    try:
        return bool(slots) and all(
            datetime.fromisoformat(f"{row['date']}T{row['start']}").replace(tzinfo=HKT) > now
            for row in slots
        )
    except (KeyError, TypeError, ValueError):
        return False


class AvailabilityWatch:
    def __init__(self, store):
        self.store = store
        saved = store.get("availability_watch", {})
        self.checked_at = saved.get("checked_at")
        self.events = saved.get("events", [])
        for event in self.events:
            venue_id = event.get("venue_id")
            if venue_id:
                name, separator, detail = event["title"].partition(" · ")
                event["title"] = f"{venue_label(venue_id, name)}{separator}{detail}"
                for slot in event.get("slots", []):
                    slot["venue_name"] = venue_label(venue_id, slot.get("venue_name"))
        self.available_slots = 0
        self.covered_venues = []
        self.invalidate_baseline()

    def invalidate_baseline(self):
        self.selection = None
        self.counts = {}
        self.baseline_at = None
        self.baseline_source_at = None

    def inspect(self, feed, config, now):
        """Alert on an observed zero-to-positive change across fresh snapshots."""
        if (not config["monitor_enabled"] or feed["status"] != "live"
                or feed.get("source_freshness") != "verified"):
            self.invalidate_baseline()
            return []
        checked_at = feed.get("fetched_at")
        fetched_at = _timestamp(checked_at)
        updated_at = _timestamp(feed.get("source_updated_at"))
        if not fetched_at or not updated_at:
            self.invalidate_baseline()
            return []
        if checked_at == self.checked_at:
            return []
        selection = config["watch_venue_ids"]
        scope = (tuple(selection), config["play_type"])
        slots = feed.get("slots", [])
        # The watch uses one-hour availability and separate venue selections.
        # Planner weekday, duration, price and venue preferences are independent.
        plan = plan_slots(slots, {"venue_ids": selection, "duration_hours": 1,
                                "play_type": config["play_type"]}, now=now)
        date_min, date_max = plan["window"]["start"], plan["window"]["end"]
        counts = {}
        covered_venues = set()
        for row in slots:
            if row["source"] != "official" or row["venue_id"] not in selection:
                continue
            if not date_min <= row["date"] <= date_max:
                continue
            covered_venues.add(row["venue_id"])
            counts[self.slot_key(row)] = row["available_courts"]
        positive = {}
        for row in plan["candidates"]:
            key = self.slot_key(row)
            if row.get("source") == "official" and counts.get(key, 0) > 0:
                positive[key] = row

        newly_open = []
        if (scope == self.selection and self.baseline_at and self.baseline_source_at
                and 0 < (fetched_at - self.baseline_at).total_seconds() <= MAX_OBSERVATION_GAP_SECONDS
                and updated_at > self.baseline_source_at):
            # A row absent from the immediately preceding snapshot is unknown.
            newly_open = [row for key, row in positive.items() if self.counts.get(key) == 0]

        events = []
        for venue in selection:
            rows = sorted((row for row in newly_open if row["venue_id"] == venue),
                          key=lambda row: (row["date"], row["start"], row["end"]))
            if not rows:
                continue
            first = rows[0]
            times = "、".join(
                f"{r['date'][5:]} {r['start']}–{r['end']}"
                f"（{r['available_courts']} 片{'，只限单打' if 'Single' in r['facility_group'] else ''}）"
                for r in rows[:3]
            )
            more = f"，另有 {len(rows) - 3} 个时段" if len(rows) > 3 else ""
            digest = sha256(f"{venue}|{checked_at}".encode()).hexdigest()[:20]
            events.append({
                "id": f"availability-{digest}",
                "kind": "availability",
                "title": f"{first['venue_name']} · 公开数据观察到 {len(rows)} 个时段出现空位",
                "body": (
                    f"{times}{more}。数据更新 {updated_at.astimezone(HKT):%m-%d %H:%M:%S}，"
                    f"读取 {fetched_at.astimezone(HKT):%m-%d %H:%M:%S}（香港时间）。"
                    "请立即在 My SmartPLAY App 核对。"
                ),
                "created_at": now.astimezone(HKT).isoformat(),
                "fetched_at": checked_at,
                "source_updated_at": feed["source_updated_at"],
                "venue_id": venue,
                "slots": rows[:3],
            })
        recent = (events + self.events)[:40]
        self.store.set("availability_watch", {
            "checked_at": checked_at, "events": recent,
        })
        self.counts = counts
        self.checked_at = checked_at
        self.events = recent
        self.available_slots = len(positive)
        self.covered_venues = sorted(covered_venues)
        self.selection = scope
        self.baseline_at = fetched_at
        self.baseline_source_at = updated_at
        return events

    @staticmethod
    def slot_key(row):
        return "|".join(row[field] for field in
                        ("venue_id", "date", "start", "end", "facility_group"))
