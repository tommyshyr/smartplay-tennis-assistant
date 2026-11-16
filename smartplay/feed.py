"""Read the LCSD public tennis feed; never access authenticated booking APIs.

The field names and root list were checked against the official JSON on
2026-11-07. Availability is a venue/facility-group count, not a court identity.
Only this public, unauthenticated URL is fetched. A failed refresh retains the
last good snapshot and explicitly labels it stale.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

from smartplay.planner import VENUES, venue_label

HKT = timezone(timedelta(hours=8))
FEED_URL = "https://data.smartplay.lcsd.gov.hk/rest/cms/api/v1/publ/contents/open-data/tennis/file"
MIN_REFRESH_SECONDS = 300
STALE_SECONDS = 600
MAX_BYTES = 20 * 1024 * 1024
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_TIME = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")

# Traditional Chinese strings here match the official Venue_Name_TC field.
VENUE_NAMES = {
    "BRTC": ("寶雲道網球場", "Bowen Road Tennis Court", "Bowen Road Tennis Courts"),
    "HKTC": ("香港網球中心", "Hong Kong Tennis Centre"),
    "CBSPG": ("銅鑼灣運動場", "Causeway Bay Sports Ground"),
    "VPTC": ("維多利亞公園", "維多利亞公園網球場", "Victoria Park"),
}


class FeedSchemaError(ValueError):
    """The public feed cannot safely be interpreted as known availability."""


def _clean(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


_NAME_TO_ID = {
    _clean(name).casefold(): venue_id
    for venue_id, names in VENUE_NAMES.items()
    for name in names
}
_NAME_TO_ID.update({venue["name"]: venue["id"] for venue in VENUES})


def _now(value: datetime | str | None = None) -> datetime:
    if value is None:
        return datetime.now(HKT)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise TypeError("now must be an aware datetime or ISO datetime")
    return value.replace(tzinfo=HKT) if value.tzinfo is None else value.astimezone(HKT)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


def parse_feed(payload: Any, play_type: str = "singles") -> dict:
    """Normalize the official root-list JSON and reject ambiguous records.

    An empty root list is valid. All records must preserve the essential
    schema; malformed records for monitored venues fail the whole snapshot.
    Other facilities are excluded, never converted into a full tennis court.
    Duplicate natural keys use the lowest count, not a sum.
    """
    if play_type not in {"singles", "doubles"}:
        raise ValueError("play_type must be singles or doubles")
    if isinstance(payload, (str, bytes, bytearray)):
        try:
            payload = json.loads(payload)
        except (ValueError, UnicodeError) as exc:
            raise FeedSchemaError("公开数据不是有效 JSON") from exc
    if not isinstance(payload, list):
        raise FeedSchemaError("官方 JSON 根结构应为数组；结构可能已更改")
    if len(payload) > 200_000:
        raise FeedSchemaError("公开数据记录数量异常")

    records: dict[tuple[str, str, str, str, str], dict] = {}
    warnings: list[str] = []
    skipped_types: set[str] = set()
    duplicate_conflicts = 0
    required = {
        "Facility_Type_Name_EN", "Facility_Location_Name_EN",
        "Available_Date", "Session_Start_Time", "Session_End_Time", "Available_Courts",
    }
    for index, row in enumerate(payload):
        if not isinstance(row, dict) or not required.issubset(row):
            raise FeedSchemaError(f"第 {index + 1} 条记录缺少必要字段；停止使用本次数据")
        names = [_clean(row.get("Venue_Name_EN")), _clean(row.get("Venue_Name_TC"))]
        if not any(names):
            raise FeedSchemaError(f"第 {index + 1} 条记录缺少场地名称")
        venue_ids = {_NAME_TO_ID[n.casefold()] for n in names if n.casefold() in _NAME_TO_ID}
        if len(venue_ids) > 1:
            raise FeedSchemaError(f"第 {index + 1} 条记录中英文场地名称冲突")

        # Validate the essential data even for venues not monitored here. A
        # renamed or malformed feed must not silently turn into an empty list.
        date_text = _clean(row["Available_Date"])
        start = _clean(row["Session_Start_Time"])
        end = _clean(row["Session_End_Time"])
        count = row["Available_Courts"]
        count_text = str(count) if isinstance(count, int) and not isinstance(count, bool) else _clean(count)
        try:
            if not _DATE.fullmatch(date_text):
                raise ValueError("date")
            datetime.strptime(date_text, "%Y-%m-%d")
            if not _TIME.fullmatch(start) or not _TIME.fullmatch(end) or end <= start:
                raise ValueError("time")
            if not re.fullmatch(r"[0-9]+", count_text):
                raise ValueError("count")
            quantity = int(count_text)
            if quantity > 1000:
                raise ValueError("count")
        except ValueError as exc:
            raise FeedSchemaError(f"第 {index + 1} 条记录的日期、时间或空场数量无效") from exc
        if not venue_ids:
            continue

        venue_id = next(iter(venue_ids))
        facility_type = _clean(row["Facility_Type_Name_EN"])
        facility_group = _clean(row["Facility_Location_Name_EN"])
        if facility_type in {"Tennis Practice Court", "VP Centre Court"}:
            continue
        if facility_type != "Tennis Court (Urban)":
            skipped_types.add(facility_type or "空白设施类型")
            continue
        allowed_groups = {"Tennis Court"}
        if venue_id == "HKTC" and play_type == "singles":
            allowed_groups.add("Tennis Court (Single)")
        if facility_group == "Tennis Court (Single)" and play_type == "doubles":
            continue
        if facility_group not in allowed_groups:
            skipped_types.add(facility_group or "空白设施分组")
            continue

        key = (venue_id, date_text, start, end, facility_group)
        slot = {
            "id": hashlib.sha256("|".join(key).encode()).hexdigest()[:20],
            "venue_id": venue_id,
            "venue_name": venue_label(venue_id),
            "date": date_text,
            "start": start,
            "end": end,
            "available_courts": quantity,
            "source": "official",
            "facility_group": facility_group,
        }
        previous = records.get(key)
        if previous:
            if previous["available_courts"] != quantity:
                duplicate_conflicts += 1
            previous["available_courts"] = min(previous["available_courts"], quantity)
        else:
            records[key] = slot

    if duplicate_conflicts:
        warnings.append(f"{duplicate_conflicts} 条重复时段数量不一致，已采用较低数量。")
    if skipped_types:
        warnings.append(f"已排除 {len(skipped_types)} 类无法识别的设施。")
    if not records:
        warnings.append("公开数据未提供所选邻近场地的标准网球场记录；请以官方应用为准。")
    return {
        "slots": sorted(records.values(), key=lambda s: (s["date"], s["venue_id"], s["facility_group"], s["start"])),
        "warnings": warnings,
        "raw_row_count": len(payload),
    }


class _OfficialRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        original = urlsplit(FEED_URL)
        if target.scheme != "https" or target.hostname != original.hostname or target.port not in {None, 443}:
            raise urllib.error.URLError("Public-feed redirect outside official host was rejected")
        if target.username is not None or target.password is not None:
            raise urllib.error.URLError("Unexpected credentials in public-feed redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _retry_after(value: str | None, now: datetime) -> int:
    if value:
        try:
            return max(MIN_REFRESH_SECONDS, int(value))
        except (ValueError, TypeError):
            try:
                when = parsedate_to_datetime(value)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                return max(MIN_REFRESH_SECONDS, int((when - now).total_seconds()))
            except (ValueError, TypeError, OverflowError):
                pass
    return MIN_REFRESH_SECONDS


class FeedClient:
    """Thread-safe five-minute public-data client, with no login or cookies.

    ``opener`` may be an opener object with ``open`` or an injected callable
    accepting (Request, timeout=...). ``now`` is injectable for tests. Calls
    during cooldown return a cached snapshot without an outbound request.
    ``snapshot`` never fetches. Imported snapshots are labelled ``imported``
    and become stale after ten minutes; they are never labelled live.
    """

    def __init__(self, opener=None, timeout: int = 20):
        self.opener = opener or urllib.request.build_opener(_OfficialRedirectHandler())
        self.timeout = timeout
        self.lock = threading.RLock()
        self.payload = None
        self.fetched_at: datetime | None = None
        self.last_attempt_at: datetime | None = None
        self.next_retry_at: datetime | None = None
        self.source_updated_at: str | None = None
        self.origin: str | None = None
        self.error: str | None = None
        self.failures = 0
        self.refreshing = False

    def snapshot(self, play_type: str = "singles", now=None) -> dict:
        at = _now(now)
        with self.lock:
            parsed = parse_feed(self.payload, play_type) if self.payload is not None else {"slots": [], "warnings": [], "raw_row_count": 0}
            if self.payload is None:
                status = "unavailable"
            elif self.error or not self.fetched_at or (at - self.fetched_at).total_seconds() > STALE_SECONDS:
                status = "stale"
            else:
                status = "imported" if self.origin == "import" else "live"
            return {
                "status": status,
                "slots": parsed["slots"],
                "warnings": parsed["warnings"],
                "fetched_at": _iso(self.fetched_at),
                "last_attempt_at": _iso(self.last_attempt_at),
                "error": self.error,
                "next_retry_at": _iso(self.next_retry_at),
                "row_count": parsed["raw_row_count"],
                "source_updated_at": self.source_updated_at,
                "origin": self.origin,
                "refreshing": self.refreshing,
            }

    def import_payload(self, payload, now=None) -> dict:
        if isinstance(payload, (str, bytes, bytearray)):
            try:
                payload = json.loads(payload)
            except (ValueError, UnicodeError) as exc:
                raise FeedSchemaError("导入内容不是有效 JSON") from exc
        parse_feed(payload)
        at = _now(now)
        with self.lock:
            self.payload = copy.deepcopy(payload)
            self.fetched_at = at
            self.source_updated_at = None
            self.origin = "import"
            self.error = None
        return self.snapshot(now=at)

    def restore_payload(self, payload, fetched_at, source_updated_at=None, origin="network") -> None:
        """Restore a previously validated cache; retains its original age."""
        parse_feed(payload)
        with self.lock:
            self.payload = copy.deepcopy(payload)
            self.fetched_at = _now(fetched_at)
            self.source_updated_at = source_updated_at
            self.origin = "import" if origin == "import" else "network"

    def refresh(self, play_type: str = "singles", now=None) -> dict:
        at = _now(now)
        with self.lock:
            if self.refreshing or (self.next_retry_at and at < self.next_retry_at):
                return self.snapshot(play_type, now=at)
            self.refreshing = True
            self.last_attempt_at = at
            self.next_retry_at = at + timedelta(seconds=MIN_REFRESH_SECONDS)
        delay = MIN_REFRESH_SECONDS
        error = None
        payload = None
        source_updated_at = None
        try:
            request = urllib.request.Request(FEED_URL, headers={
                "Accept": "application/json",
                "User-Agent": "SmartPLAY-Public-Data-Assistant/1.0 (5-minute-cache)",
            })
            fetch = self.opener.open if hasattr(self.opener, "open") else self.opener
            with fetch(request, timeout=self.timeout) as response:
                final_url = response.geturl() if hasattr(response, "geturl") else FEED_URL
                final = urlsplit(final_url)
                if final.scheme != "https" or final.hostname != urlsplit(FEED_URL).hostname or final.port not in {None, 443}:
                    raise FeedSchemaError("公开数据响应来自非官方地址")
                body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise FeedSchemaError("公开数据文件过大")
                payload = json.loads(body.decode("utf-8-sig"))
                parse_feed(payload, play_type)
                modified = response.headers.get("Last-Modified") if hasattr(response, "headers") else None
                if modified:
                    try:
                        source_updated_at = parsedate_to_datetime(modified).isoformat()
                    except (ValueError, TypeError, OverflowError):
                        pass
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                delay = 1800
                error = f"官方公开数据接口返回 HTTP {exc.code}，已暂停请求 30 分钟；可在浏览器打开官方数据并手动导入。"
            elif exc.code == 429:
                delay = _retry_after(exc.headers.get("Retry-After") if exc.headers else None, at)
                error = "官方公开数据接口限流，已根据接口指定的等待时间暂停重试，至少等待五分钟。"
            else:
                error = f"官方公开数据接口返回 HTTP {exc.code}；保留上次成功快照。"
            exc.close()
        except (FeedSchemaError, json.JSONDecodeError, UnicodeError) as exc:
            error = f"公开数据格式验证失败：{exc}；未替换上次快照。"
        except urllib.error.URLError as exc:
            if re.search(r"Tunnel connection failed: (?:401|403)\b", str(exc.reason)):
                delay = 1800
                error = "当前网络代理拒绝访问官方开放数据，30 分钟后重试。"
            else:
                error = "公开数据连接失败或超时；保留上次快照并稍后重试。"
        except (TimeoutError, OSError):
            error = "公开数据连接失败或超时；保留上次快照并稍后重试。"
        except Exception as exc:
            error = f"公开数据读取失败（{type(exc).__name__}）；保留上次快照。"
        finally:
            with self.lock:
                self.refreshing = False
                if error:
                    self.failures += 1
                    delay = max(delay, min(1800, MIN_REFRESH_SECONDS * 2 ** min(self.failures - 1, 3)))
                    self.error = error
                else:
                    self.payload = payload
                    self.fetched_at = at
                    self.source_updated_at = source_updated_at
                    self.origin = "network"
                    self.error = None
                    self.failures = 0
                self.next_retry_at = at + timedelta(seconds=delay)
        return self.snapshot(play_type, now=at)
