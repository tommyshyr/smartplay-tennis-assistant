"""Track upcoming availability from successful official feed refreshes."""

from datetime import datetime
from hashlib import sha256

from smartplay.planner import HKT, plan_slots, venue_label


DEFAULT_WATCH_VENUES = ("BRTC", "HKTC")


class AvailabilityWatch:
    def __init__(self, store):
        self.store = store
        saved = store.get("availability_watch", {})
        self.counts = saved.get("counts", {})
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
        self.selection = None

    def inspect(self, feed, config, now):
        """Return new alerts only once for each successful network snapshot."""
        if not config["monitor_enabled"] or feed["status"] != "live":
            return []
        checked_at = feed.get("fetched_at")
        if not checked_at or checked_at == self.checked_at:
            return []
        selection = config["watch_venue_ids"]
        slots = feed.get("slots", [])
        # The watch uses one-hour availability and separate venue selections.
        # Planner weekday, duration, price and venue preferences are independent.
        plan = plan_slots(slots, {"venue_ids": selection, "duration_hours": 1,
                                "play_type": config["play_type"]}, now=now)
        positive = {
            self.slot_key(row): row for row in plan["candidates"]
            if row.get("source") == "official"
        }
        date_min, date_max = plan["window"]["start"], plan["window"]["end"]
        counts = {key: count for key, count in self.counts.items()
                  if key.split("|", 2)[1] >= date_min}
        covered_venues = set()
        for row in slots:
            if row["source"] != "official" or row["venue_id"] not in selection:
                continue
            if not date_min <= row["date"] <= date_max:
                continue
            covered_venues.add(row["venue_id"])
            # Missing rows in a partial feed are unknown. Only an explicit
            # zero can reset a slot we have already announced.
            if row["available_courts"] == 0:
                counts[self.slot_key(row)] = 0
        newly_open = []
        for key, row in positive.items():
            if not counts.get(key, 0):
                newly_open.append(row)
            counts[key] = row["available_courts"]

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
                "title": f"{first['venue_name']} · {len(rows)} 个时段有空位",
                "body": f"{times}{more}。请在 SmartPLAY 核对场号及空位。",
                "created_at": now.astimezone(HKT).isoformat(),
                "venue_id": venue,
                "slots": rows[:3],
            })
        recent = (events + self.events)[:40]
        self.store.set("availability_watch", {
            "counts": counts, "checked_at": checked_at, "events": recent,
        })
        self.counts = counts
        self.checked_at = checked_at
        self.events = recent
        self.available_slots = len(positive)
        self.covered_venues = sorted(covered_venues)
        self.selection = (tuple(selection), config["play_type"])
        return events

    @staticmethod
    def slot_key(row):
        return "|".join(row[field] for field in
                        ("venue_id", "date", "start", "end", "facility_group"))
