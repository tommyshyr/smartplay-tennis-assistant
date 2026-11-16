"""Deterministic, read-only SmartPLAY slot planning. No booking-site requests."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import math

HKT = timezone(timedelta(hours=8), "HKT")
VENUES = [
    {"id": "BRTC", "venue_id": "BRTC", "name": "寶雲道網球場", "name_en": "Bowen Road Tennis Courts", "district": "灣仔", "courts": 4, "notes": "無泛光燈；4–9月06:00–19:00，10–3月07:00–18:00", "default": True},
    {"id": "HKTC", "venue_id": "HKTC", "name": "香港網球中心", "name_en": "Hong Kong Tennis Centre", "district": "灣仔", "courts": 17, "notes": "07:00–23:00；8、10、11號場僅供單打", "default": True},
    {"id": "CBSPG", "venue_id": "CBSPG", "name": "銅鑼灣運動場", "name_en": "Causeway Bay Sports Ground", "district": "灣仔", "courts": 6, "notes": "07:00–23:00；維修及封場以官方為準", "default": True},
    {"id": "VPTC", "venue_id": "VPTC", "name": "維多利亞公園網球場", "name_en": "Victoria Park Tennis Courts", "district": "灣仔", "courts": 13, "notes": "普通網球場；不含另列的網球主場", "default": True},
]
_VENUE_MAP = {v["id"]: v for v in VENUES}
DEFAULT_CONFIG = {
    "venue_ids": [v["id"] for v in VENUES],
    "venue_priority": [v["id"] for v in VENUES],
    "weekdays": list(range(7)), "start_time": "06:00", "end_time": "23:00",
    "duration_hours": 2, "allow_one_hour_fallback": True,
    "play_type": "singles", "max_hourly_hkd": 0,
    "holiday_dates": [], "excluded_dates": [],
}


def _now(value=None):
    if value is None:
        return datetime.now(HKT)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value.replace(tzinfo=HKT) if value.tzinfo is None else value.astimezone(HKT)


def _date(value):
    if isinstance(value, datetime):
        return value.astimezone(HKT).date() if value.tzinfo else value.date()
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _minutes(value):
    parts = str(value).split(":")
    if len(parts) != 2:
        raise ValueError("time must be HH:MM")
    h, m = map(int, parts)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("time out of range")
    return h * 60 + m


def _hm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def release_day_for(play_date):
    """The seven-day window includes today, so use date minus six days."""
    return (_date(play_date) - timedelta(days=6)).isoformat()


def release_schedule(now=None, play_date=None):
    current = _now(now)
    if play_date is not None:
        day = _date(play_date) - timedelta(days=6)
    else:
        day = current.date()
        if current >= datetime.combine(day, time(7, 15), HKT):
            day += timedelta(days=1)
    app = datetime.combine(day, time(7), HKT)
    web = datetime.combine(day, time(7, 15), HKT)
    return {
        "timezone": "Asia/Hong_Kong", "release_date": day.isoformat(),
        "play_date": (day + timedelta(days=6)).isoformat(),
        "app_iam_smart": app.isoformat(), "web": web.isoformat(),
        "app_time": app.isoformat(), "web_time": web.isoformat(),
        "app_seconds": max(0, int((app - current).total_seconds())),
        "web_seconds": max(0, int((web - current).total_seconds())),
        "note": "07:00僅官方App經智方便；網頁07:15起。七天含預訂當日。",
    }


def _peak(day, start, holidays):
    return day.isoformat() in holidays or day.weekday() == 6 or (
        day.weekday() == 5 and start >= 13 * 60
    ) or (day.weekday() < 5 and start >= 18 * 60)


def plan_slots(slots, config=None, confirmed_bookings=None, now=None):
    """Return ranked candidates from *existing* availability records only.

    Venue-level counts cannot prove that adjacent hours share a court. Such
    proposals are retained with continuity='unverified', never 'confirmed'.
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    current = _now(now)
    today = current.date()
    # Overnight the feed can already list D+6, but those newly published
    # sessions are not released until 07:00 via App + iAM Smart.
    released_offset = 6 if current.time() >= time(7) else 5
    latest = today + timedelta(days=released_offset)
    warnings = [
        "中西區官方目錄未列網球場；本方案涵蓋已選灣仔鄰近場地。",
        "空位資料不代表鎖場；須在官方App或網頁核對並付款，付款後才完成預訂。",
        "繁忙時段同類設施每日合計最多兩小時；非繁忙時段每場地最多兩小時。仍須核對本工具以外的預訂。",
    ]
    duration = float(cfg.get("duration_hours", 2))
    if duration not in (1, 2):
        raise ValueError("duration_hours must be 1 or 2")
    start_limit, end_limit = _minutes(cfg["start_time"]), _minutes(cfg["end_time"])
    if start_limit >= end_limit:
        raise ValueError("start_time must be before end_time")
    budget = float(cfg.get("max_hourly_hkd", 0))
    if not math.isfinite(budget) or budget < 0:
        raise ValueError("max_hourly_hkd must be a nonnegative finite number")
    venue_ids = set(cfg["venue_ids"])
    weekdays, exclusions = set(cfg["weekdays"]), set(cfg["excluded_dates"])
    holidays = set(cfg["holiday_dates"])
    priority = {v: i for i, v in enumerate(cfg.get("venue_priority", cfg["venue_ids"]))}
    booked = defaultdict(list)
    for b in confirmed_bookings or []:
        if b.get("status", "confirmed") != "confirmed":
            continue
        try:
            day = _date(b["date"])
            begin, end = _minutes(b["start"]), _minutes(b["end"])
            if begin < end:
                booked[day.isoformat()].append((begin, end))
        except (ValueError, TypeError, KeyError):
            warnings.append("有一筆已訂記錄格式無效，請檢查以確保防重疊有效。")
    groups = defaultdict(dict)
    invalid, unknown_price = 0, False
    for raw in slots:
        try:
            vid = str(raw["venue_id"])
            if vid not in venue_ids:
                continue
            facility_group = str(raw.get("facility_group", "Tennis Court"))
            if "practice" in facility_group.lower() or "centre court" in facility_group.lower():
                continue
            if cfg["play_type"] == "doubles" and "single" in facility_group.lower():
                continue
            day = _date(raw["date"])
            begin, end = _minutes(raw["start"]), _minutes(raw["end"])
            n = int(raw["available_courts"])
            if n <= 0 or not today <= day <= latest or day.weekday() not in weekdays or day.isoformat() in exclusions:
                continue
            if begin >= end or begin < start_limit or end > end_limit:
                continue
            if datetime.combine(day, time(begin // 60, begin % 60), HKT) <= current:
                continue
            opens, closes = ((6 * 60, 19 * 60) if 4 <= day.month <= 9 else (7 * 60, 18 * 60)) if vid == "BRTC" else (7 * 60, 23 * 60)
            if vid == "VPTC" and 4 <= day.month <= 9:
                opens = 6 * 60
            if begin < opens or end > closes:
                continue
            if any(begin < be and end > bs for bs, be in booked[day.isoformat()]):
                continue
            ids = raw.get("court_ids")
            if ids is not None:
                ids = set(map(str, ids))
                if vid == "HKTC" and cfg["play_type"] == "doubles":
                    ids -= {"8", "10", "11"}
                if not ids:
                    continue
                n = min(n, len(ids))
            rate = raw.get("hourly_rate_hkd")
            if rate is not None:
                rate = float(rate)
                if not math.isfinite(rate) or rate < 0:
                    raise ValueError("invalid rate")
            if budget and (rate is None or rate > budget):
                unknown_price = unknown_price or rate is None
                continue
            item = {**raw, "venue_id": vid, "date": day.isoformat(), "_begin": begin, "_end": end, "_court_ids": ids, "available_courts": n, "_rate": rate}
            # Single-only courts, ordinary courts and practice areas are not
            # interchangeable supplies, even when they share a venue.
            key = (vid, day.isoformat(), str(raw.get("source", "official")), facility_group)
            # Duplicate aggregate observations must not inflate supply.
            previous = groups[key].get((begin, end))
            if previous is None or n < previous["available_courts"]:
                groups[key][(begin, end)] = item
        except (ValueError, TypeError, KeyError, OverflowError):
            invalid += 1

    candidates, seen = [], set()
    durations = [int(duration * 60)]
    if duration == 2 and cfg.get("allow_one_hour_fallback", True):
        durations.append(60)
    for (vid, day_string, source, facility_group), records in groups.items():
        by_start = defaultdict(list)
        for r in records.values():
            by_start[r["_begin"]].append(r)
        for begin in sorted(by_start):
            for minutes in durations:
                goal = begin + minutes
                paths = [(begin, [])]
                while paths:
                    cursor, chain = paths.pop()
                    if cursor == goal:
                        known = all(r["_court_ids"] is not None for r in chain)
                        common = set.intersection(*(r["_court_ids"] for r in chain)) if known else None
                        if known and not common:
                            continue
                        identity = f"{vid}|{day_string}|{begin}|{goal}|{source}|{facility_group}"
                        if identity in seen:
                            continue
                        seen.add(identity)
                        continuity = "verified_from_feed" if known else "unverified"
                        n = min(r["available_courts"] for r in chain)
                        if common is not None:
                            n = min(n, len(common))
                        price = sum(r["_rate"] * (r["_end"] - r["_begin"]) / 60 for r in chain) if all(r["_rate"] is not None for r in chain) else None
                        warning = "同一球場連續時段仍須於官方頁面核對" if not known and minutes > 60 else "請於官方頁面核對空位及費用"
                        if vid == "HKTC" and cfg["play_type"] == "doubles" and not known:
                            warning += "；雙打須排除8、10、11號場"
                        if source == "demo":
                            warning = "演示資料，並非真實可訂場次；" + warning
                        candidates.append({
                            "id": hashlib.sha256(identity.encode()).hexdigest()[:20],
                            "venue_id": vid, "venue_name": chain[0].get("venue_name") or _VENUE_MAP.get(vid, {}).get("name", vid),
                            "date": day_string, "start": _hm(begin), "end": _hm(goal),
                            "duration_hours": minutes / 60, "available_courts": n,
                            "continuity": continuity, "court_ids": sorted(common) if common else [],
                            "estimated_cost_hkd": round(price, 2) if price is not None else None,
                            "warning": warning, "source": source, "facility_group": facility_group,
                            "peak": _peak(_date(day_string), begin, holidays),
                            "score": (10000 if minutes == int(duration * 60) else 0) - priority.get(vid, 99) * 100 + min(n, 20),
                        })
                        continue
                    for r in by_start.get(cursor, []):
                        if cursor < r["_end"] <= goal:
                            paths.append((r["_end"], chain + [r]))
    candidates.sort(key=lambda c: (-c["score"], c["date"], c["start"], c["id"]))
    if invalid:
        warnings.append(f"忽略{invalid}筆格式無效的空位記錄。")
    if unknown_price:
        warnings.append("設定了價格上限；未提供可核實單價的場次已排除，避免超出預算。")
    if not candidates:
        warnings.append("目前沒有符合條件的場次；資料失效或網絡錯誤亦可能影響結果，請查看資料狀態。")
    return {"candidates": candidates, "warnings": list(dict.fromkeys(warnings)), "window": {"start": today.isoformat(), "end": latest.isoformat()}, "release": release_schedule(current)}


plan = plan_slots
build_plan = plan_slots
