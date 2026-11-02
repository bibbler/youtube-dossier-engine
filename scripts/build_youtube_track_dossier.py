#!/usr/bin/env python3
"""
build_youtube_track_dossier.py
Global Multi-Country YouTube Track & Video Intelligence Dossier Engine

Accepts dynamic input for any given YouTube video (URL or video ID), date-scopes
chart queries, and compiles the standardized 5-layer composable dataset:
  1. video_metadata.json / .csv
  2. video_telemetry_snapshot.json / .csv
  3. country_chart_rankings.json / .csv
  4. top_comments_ranked.json / .csv
  5. share_cards_registry.json / .csv
  + manifest.json & executive Markdown report.

Usage Examples:
    # Full 86-country sweep for a video (comments skipped by default)
    python3 build_youtube_track_dossier.py --video-id FyS5dAywkEo

    # By full URL with historical date scoping
    python3 build_youtube_track_dossier.py --url "https://www.youtube.com/watch?v=9ofUM-_3uQ4" --date 2026-10-30

    # Quick test across select priority countries
    python3 build_youtube_track_dossier.py --video-id 9ofUM-_3uQ4 --countries US,GB,BR,TH,FR

    # Opt-in to top community comments (default: skipped for fast execution)
    python3 build_youtube_track_dossier.py --video-id 9ofUM-_3uQ4 --with-comments
    python3 build_youtube_track_dossier.py --video-id 9ofUM-_3uQ4 --max-comments 50
"""

import os
import sys
import json
import csv
import re
import time
import argparse
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
import zoneinfo

# Canonical 86+ territory catalog supported by YouTube Charts InnerTube API (including Global)
ALL_COUNTRY_CODES = [
    "GLOBAL", "AE", "AR", "AT", "AU", "AZ", "BA", "BE", "BG", "BH", "BO",
    "BR", "BY", "CA", "CH", "CL", "CO", "CR", "CY", "CZ", "DE",
    "DK", "DO", "DZ", "EC", "EG", "ES", "FI", "FR", "GE", "GH",
    "GR", "GT", "HK", "HN", "HR", "HU", "ID", "IE", "IL", "IN",
    "IT", "JO", "JP", "KE", "KR", "KW", "KZ", "LB", "LK", "LT",
    "LY", "MA", "MK", "MX", "MY", "NG", "NI", "NL", "NO", "NP",
    "NZ", "PA", "PE", "PH", "PK", "PL", "PR", "PT", "PY", "QA",
    "RS", "SA", "SE", "SG", "SK", "SV", "TH", "TN", "TR", "TW",
    "UA", "UK", "US", "UY", "VN", "ZA"
]

COUNTRY_NAMES = {
    "GLOBAL": "Global / Worldwide",
    "AE": "United Arab Emirates", "AR": "Argentina", "AT": "Austria", "AU": "Australia",
    "AZ": "Azerbaijan", "BA": "Bosnia and Herzegovina", "BE": "Belgium", "BG": "Bulgaria",
    "BH": "Bahrain", "BO": "Bolivia", "BR": "Brazil", "BY": "Belarus",
    "CA": "Canada", "CH": "Switzerland", "CL": "Chile", "CO": "Colombia",
    "CR": "Costa Rica", "CY": "Cyprus", "CZ": "Czechia", "DE": "Germany",
    "DK": "Denmark", "DO": "Dominican Republic", "DZ": "Algeria", "EC": "Ecuador",
    "EG": "Egypt", "ES": "Spain", "FI": "Finland", "FR": "France",
    "GE": "Georgia", "GH": "Ghana", "GR": "Greece", "GT": "Guatemala",
    "HK": "Hong Kong", "HN": "Honduras", "HR": "Croatia", "HU": "Hungary",
    "ID": "Indonesia", "IE": "Ireland", "IL": "Israel", "IN": "India",
    "IT": "Italy", "JO": "Jordan", "JP": "Japan", "KE": "Kenya",
    "KR": "South Korea", "KW": "Kuwait", "KZ": "Kazakhstan", "LB": "Lebanon",
    "LK": "Sri Lanka", "LT": "Lithuania", "LY": "Libya", "MA": "Morocco",
    "MK": "North Macedonia", "MX": "Mexico", "MY": "Malaysia", "NG": "Nigeria",
    "NI": "Nicaragua", "NL": "Netherlands", "NO": "Norway", "NP": "Nepal",
    "NZ": "New Zealand", "PA": "Panama", "PE": "Peru", "PH": "Philippines",
    "PK": "Pakistan", "PL": "Poland", "PR": "Puerto Rico", "PT": "Portugal",
    "PY": "Paraguay", "QA": "Qatar", "RS": "Serbia", "SA": "Saudi Arabia",
    "SE": "Sweden", "SG": "Singapore", "SK": "Slovakia", "SV": "El Salvador",
    "TH": "Thailand", "TN": "Tunisia", "TR": "Turkey", "TW": "Taiwan",
    "UA": "Ukraine", "UK": "United Kingdom", "GB": "United Kingdom", "US": "United States", "UY": "Uruguay",
    "VN": "Vietnam", "ZA": "South Africa"
}

def get_country_flag(code: str) -> str:
    """Returns a Unicode national flag emoji for an ISO country code."""
    c = (code or "").strip().upper()
    if c in ["GLOBAL", "WORLDWIDE"]:
        return "🌐"
    if c == "UK":
        c = "GB"
    if len(c) == 2 and c.isalpha():
        return chr(ord(c[0]) + 127397) + chr(ord(c[1]) + 127397)
    return "🌍"

def classify_peak_rank(pos) -> str:
    """Returns an executive peak classification label with badges."""
    try:
        p = int(pos)
    except (ValueError, TypeError):
        return f"Rank #{pos}"
    
    if p == 1:
        return "🥇 #1 Champion"
    elif p == 2:
        return "🥈 Top 2 Tier"
    elif p == 3:
        return "🥉 Top 3 Tier"
    elif p <= 5:
        return f"🎖️ Top 5 Tier (#{p})"
    elif p <= 10:
        return f"⭐ Top 10 Entry (#{p})"
    elif p <= 20:
        return f"🔥 Top 20 Entry (#{p})"
    elif p <= 50:
        return f"📈 Top 50 Entry (#{p})"
    else:
        return f"Rank #{p}"

def get_select_top_placements(rankings: list, max_rows: int = 25) -> list:
    """Filters and ranks high-priority highlighted territory placements."""
    key_markets = {"US", "GB", "UK", "TH", "BR", "JP", "KR", "FR", "DE", "AU", "CA", "ID", "PH", "MX", "GLOBAL"}
    
    candidates = []
    for r in rankings:
        try:
            pos = int(r.get("rank_position", 999))
        except (ValueError, TypeError):
            pos = 999
        cc = r.get("country_code", "").upper()
        if pos <= 10 or (cc in key_markets and pos <= 30):
            candidates.append(r)
            
    if not candidates and rankings:
        candidates = sorted(rankings, key=lambda r: int(r.get("rank_position", 999)))[:15]
    else:
        candidates.sort(key=lambda r: (
            int(r.get("rank_position", 999)),
            0 if r.get("country_code", "").upper() in key_markets else 1,
            r.get("country_name", "")
        ))
        
    return candidates[:max_rows]

def extract_video_id(url_or_id: str) -> str:
    """Normalizes input into a clean 11-character YouTube video ID."""
    url_or_id = url_or_id.strip()
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url_or_id):
        return url_or_id
    patterns = [
        r'(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/live\/|\/shorts\/)([a-zA-Z0-9_-]{11})',
        r'video_id=([a-zA-Z0-9_-]{11})'
    ]
    for p in patterns:
        m = re.search(p, url_or_id)
        if m:
            return m.group(1)
    return url_or_id

def sanitize_slug(name: str) -> str:
    """Converts a title or entity name into a filesystem-safe slug."""
    clean = re.sub(r'[^\w\s-]', '', name).strip().lower()
    return re.sub(r'[-\s]+', '_', clean)

def fetch_youtube_metadata_and_comments(video_id: str, max_comments: int = 20) -> dict:
    """Extracts raw telemetry, static metadata, and top-liked root comments via yt-dlp."""
    print(f"[+] Querying yt-dlp for video metadata: {video_id}...")
    cmd = [
        "yt-dlp",
        "--dump-single-json",
        "--skip-download",
        "--no-warnings",
        f"https://www.youtube.com/watch?v={video_id}"
    ]
    if max_comments > 0:
        # Fetch a larger candidate pool of top-sorted root comments (0 replies) so we can strictly rank by like_count descending
        pool_size = max(max_comments * 3, 60)
        cmd.extend([
            "--write-comments",
            "--extractor-args",
            f"youtube:comment_sort=top;max_comments={pool_size},{pool_size},0,0"
        ])

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"yt-dlp failed to fetch video {video_id}: {res.stderr.strip()}")
    
    return json.loads(res.stdout)

def format_chart_date_val(raw_val) -> str:
    """Formats InnerTube endDate (which may be a dict {'year':..., 'month':..., 'day':...} or string) into YYYY-MM-DD."""
    if not raw_val:
        return ""
    if isinstance(raw_val, dict):
        y = raw_val.get("year")
        m = raw_val.get("month")
        d = raw_val.get("day")
        if y and m and d:
            return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    s = str(raw_val).strip()
    if s.startswith("{") and "year" in s:
        import ast
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, dict) and parsed.get("year"):
                return f"{int(parsed['year']):04d}-{int(parsed['month']):02d}-{int(parsed['day']):02d}"
        except Exception:
            pass
    return s

def first_thursday_on_or_after(date_str: str) -> str:
    """Calculates the end date (Thursday) for YouTube Charts Weekly cycle corresponding to a release date."""
    if not date_str or len(date_str) < 8:
        return ""
    try:
        clean_date = date_str.replace("-", "").strip()
        dt = datetime.strptime(clean_date[:8], "%Y%m%d")
        days_ahead = (3 - dt.weekday()) % 7
        if days_ahead == 0 and dt.weekday() == 3:
            target_thursday = dt + timedelta(days=7)
        else:
            target_thursday = dt + timedelta(days=days_ahead)
        return target_thursday.strftime("%Y-%m-%d")
    except Exception:
        return ""

def query_innertube_chart(country_code: str, chart_type: str, period_type: str = None, target_date: str = None) -> tuple:
    """Queries YouTube Charts InnerTube API for a specific country and chart type. Returns (videoViews, endDate)."""
    url = "https://charts.youtube.com/youtubei/v1/browse?alt=json"
    is_global = (country_code or "").strip().upper() in ["GLOBAL", "WORLDWIDE", ""]
    gl_code = "US" if is_global else country_code.strip().upper()
    if gl_code == "UK":
        gl_code = "GB"

    context = {
        "client": {
            "hl": "en",
            "gl": gl_code,
            "clientName": "WEB_MUSIC_ANALYTICS",
            "clientVersion": "2.0",
            "platform": "DESKTOP"
        }
    }
    query_parts = ["perspective=CHART_DETAILS"]
    if is_global:
        query_parts.append("chart_params_country_code=global")
    else:
        c_code = "gb" if country_code.strip().lower() == "uk" else country_code.strip().lower()
        query_parts.append(f"chart_params_country_code={c_code}")
    query_parts.append(f"chart_params_chart_type={chart_type}")
    if period_type:
        query_parts.append(f"chart_params_period_type={period_type}")
    if target_date:
        compact_date = target_date.replace("-", "").strip()
        query_parts.append(f"chart_params_end_date={compact_date}")

    query = "&".join(query_parts)
    payload = {
        "context": context,
        "browseId": "FEmusic_analytics_charts_home",
        "query": query
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            contents = data.get("contents", {}).get("sectionListRenderer", {}).get("contents", [])
            if not contents:
                return [], ""
            content = contents[0].get("musicAnalyticsSectionRenderer", {}).get("content", {})
            videos_list = content.get("videos", [])
            if not videos_list:
                return [], ""
            v0 = videos_list[0]
            return v0.get("videoViews", []), format_chart_date_val(v0.get("endDate", ""))
    except urllib.error.HTTPError as e:
        return [], ""
    except Exception:
        return [], ""

def sweep_country_charts(video_id: str, countries: list, target_date: str = None,
                         upload_date: str = None, hours_since_release: float = None,
                         cancel_check=None, progress_callback=None) -> tuple:
    """
    Sweeps specified countries for chart placements and official share card URLs.
    Supports both latest active cycles and debut-window lookups across Daily and Weekly charts.
    """
    print(f"[+] Sweeping {len(countries)} territories on YouTube Charts InnerTube API...")
    rankings = []
    share_cards = {}
    discovered_daily_date = target_date
    total_c = len(countries)

    # Determine debut window queries (d0, d1, w1)
    debut_cycles = []
    is_older = False
    if upload_date and len(upload_date.replace("-", "")) >= 8:
        try:
            up_clean = upload_date.replace("-", "")[:8]
            dt_up = datetime.strptime(up_clean, "%Y%m%d")
            d0_str = dt_up.strftime("%Y-%m-%d")
            d1_str = (dt_up + timedelta(days=1)).strftime("%Y-%m-%d")
            w1_str = first_thursday_on_or_after(d0_str)

            if hours_since_release is not None and hours_since_release > 72:
                is_older = True
            else:
                now_utc = datetime.now(timezone.utc)
                if (now_utc - dt_up.replace(tzinfo=timezone.utc)).total_seconds() > 72 * 3600:
                    is_older = True

            is_explicit_debut = bool(target_date and target_date.replace("-", "")[:8] == up_clean)

            if is_older or is_explicit_debut or (target_date is None):
                debut_cycles.append(("DAILY", d0_str, "Daily Top Music Videos"))
                if d1_str != d0_str:
                    debut_cycles.append(("DAILY", d1_str, "Daily Top Music Videos"))
                if w1_str:
                    debut_cycles.append(("WEEKLY", w1_str, "Weekly Top Music Videos"))
        except Exception as e:
            print(f"[!] Warning calculating debut window: {e}")

    for idx, cc in enumerate(countries, start=1):
        if cancel_check and cancel_check():
            raise RuntimeError("Sweep cancelled by user.")

        cc_clean = cc.strip().upper()
        if cc_clean == "UK":
            cc_clean = "GB"
        country_name = COUNTRY_NAMES.get(cc_clean, cc_clean)
        if progress_callback:
            progress_callback(idx, total_c, cc_clean, country_name, len(rankings), f"Scanning {country_name} ({cc_clean})...")

        # Build list of queries to run for this country
        query_schedule = []
        if target_date:
            query_schedule.append(("DAILY", target_date, "Daily Top Music Videos"))
        else:
            query_schedule.append(("DAILY", None, "Daily Top Music Videos"))
            # Skip live trending for older releases (>7 days) to eliminate wasted calls
            if not is_older:
                query_schedule.append(("TRENDING_VIDEOS", None, "Overall YouTube Trending"))

        # Merge debut window cycles if active
        for ptype, dval, s_label in debut_cycles:
            if not any(q[0] == ptype and q[1] == dval for q in query_schedule):
                query_schedule.append((ptype, dval, s_label))

        checked_keys = set()
        for ptype, dval, surface_label in query_schedule:
            if cancel_check and cancel_check():
                raise RuntimeError("Sweep cancelled by user.")

            q_key = (ptype, dval)
            if q_key in checked_keys:
                continue
            checked_keys.add(q_key)

            if ptype == "TRENDING_VIDEOS":
                entries, _ = query_innertube_chart(cc_clean, chart_type="TRENDING_VIDEOS")
                c_date_val = "Live Snapshot"
                wk_label = "Live Snapshot"
            else:
                entries, chart_end_date = query_innertube_chart(cc_clean, chart_type="VIDEOS", period_type=ptype, target_date=dval)
                if chart_end_date and not discovered_daily_date:
                    discovered_daily_date = chart_end_date
                c_date_val = dval if dval else (chart_end_date or "Latest Daily")
                wk_label = f"Week Ending {c_date_val}" if ptype == "WEEKLY" else c_date_val

            for rank_idx, item in enumerate(entries, start=1):
                if item.get("id") == video_id:
                    meta = item.get("chartEntryMetadata", {})
                    pos = meta.get("currentPosition") or rank_idx
                    prev_pos = meta.get("previousPosition")
                    share_url = item.get("shareCardUrl", "")

                    status_label = classify_peak_rank(pos)
                    rankings.append({
                        "country_code": cc_clean,
                        "country_name": country_name,
                        "chart_type": surface_label,
                        "rank_position": pos,
                        "previous_position": prev_pos,
                        "status": status_label,
                        "video_id": video_id,
                        "chart_date": c_date_val,
                        "chart_week_label": wk_label,
                        "share_card_url": share_url
                    })
                    if share_url and cc_clean not in share_cards:
                        share_cards[cc_clean] = share_url

                    print(f"  [{idx}/{total_c}] {country_name} ({cc_clean}): #{pos} in {surface_label} ({c_date_val})")
                    if progress_callback:
                        progress_callback(idx, total_c, cc_clean, country_name, len(rankings), f"Hit #{pos} in {country_name} ({cc_clean}) {surface_label} ({c_date_val})")
                    break

        time.sleep(0.06)  # Cooldown guardrail against IP limits

    return rankings, share_cards, discovered_daily_date

def build_dossier(video_input: str, target_date: str = None, country_filter: str = "all",
                  max_comments: int = 0, output_dir: str = None, skip_charts: bool = False,
                  include_comments: bool = False, cancel_check=None, progress_callback=None):
    """Coordinates end-to-end extraction and writes the 5-layer composable dataset."""
    video_id = extract_video_id(video_input)
    if not video_id:
        raise ValueError("Invalid YouTube video ID or URL provided.")

    if cancel_check and cancel_check():
        raise RuntimeError("Sweep cancelled by user.")

    # Timezone standardization (PST/PDT)
    pdt_zone = zoneinfo.ZoneInfo("America/Los_Angeles")
    now_pdt_obj = datetime.now(pdt_zone)
    now_pdt_str = now_pdt_obj.strftime("%Y-%m-%d %H:%M:%S %Z")
    today_pdt_str = now_pdt_obj.strftime("%Y-%m-%d")

    # 1. Extract static metadata, telemetry, and comments (default: skipped for fast sync)
    actual_comments_to_pull = max_comments if max_comments > 0 else (20 if include_comments else 0)
    if progress_callback:
        progress_callback(0, 1, "META", "YouTube Metadata", 0, f"Fetching video metadata{' + top 20 comments' if actual_comments_to_pull else ''} for {video_id}...")
    yt_meta = fetch_youtube_metadata_and_comments(video_id, max_comments=actual_comments_to_pull)

    upload_date_raw = yt_meta.get("upload_date", "")
    upload_date_fmt = f"{upload_date_raw[:4]}-{upload_date_raw[4:6]}-{upload_date_raw[6:]}" if len(upload_date_raw) == 8 else upload_date_raw

    # Resolve date keywords: release, debut, first-day, yesterday, today
    resolved_target_date = target_date
    if target_date:
        td_clean = target_date.strip().lower()
        if td_clean in ["release", "debut", "first-day", "first-24h", "day1"]:
            resolved_target_date = upload_date_fmt
            print(f"[+] Resolved date keyword '{td_clean}' to release date: {resolved_target_date}")
        elif td_clean in ["yesterday", "prev", "previous"]:
            yesterday_obj = now_pdt_obj - timedelta(days=1)
            resolved_target_date = yesterday_obj.strftime("%Y-%m-%d")
            print(f"[+] Resolved date keyword 'yesterday' to: {resolved_target_date}")
        elif td_clean in ["today", "latest", "now"]:
            resolved_target_date = None

    title = yt_meta.get("title", f"video_{video_id}")
    slug = sanitize_slug(title)[:40]
    entity_name = f"{title}"

    # Setup output paths
    if not output_dir:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidate_dir = os.path.join(project_root, "datasets", "youtube")
        base_datasets_dir = candidate_dir if os.path.isdir(candidate_dir) else "/Users/bibbler/Downloads/_Projects/Antigravity/Scraper_projects/blackpink-twitter/data/datasets/youtube"
        output_dir = os.path.join(base_datasets_dir, f"{slug}_{video_id}")
    os.makedirs(output_dir, exist_ok=True)

    # 2. Process Telemetry & Velocities
    views = yt_meta.get("view_count", 0)
    likes = yt_meta.get("like_count", 0)
    comments_count = yt_meta.get("comment_count", 0)
    subscribers = yt_meta.get("channel_follower_count", 0)

    rel_ts = yt_meta.get("release_timestamp") or yt_meta.get("timestamp")
    if rel_ts:
        rel_dt = datetime.fromtimestamp(rel_ts, tz=timezone.utc)
        now_utc = datetime.now(timezone.utc)
        hours_since_release = max(1.0, round((now_utc - rel_dt).total_seconds() / 3600.0, 2))
    else:
        hours_since_release = 24.0

    views_per_hour = round(views / hours_since_release, 2)
    likes_per_hour = round(likes / hours_since_release, 2)
    like_ratio = round((likes / views * 100), 2) if views else 0.0
    comment_ratio = round((comments_count / views * 100), 4) if views else 0.0

    if views >= 50000000 or views_per_hour >= 250000:
        virality_tier = "Mega-Viral"
    elif views >= 10000000 or views_per_hour >= 50000:
        virality_tier = "High-Velocity"
    elif views >= 1000000 or views_per_hour >= 10000:
        virality_tier = "Viral"
    elif views >= 100000 or views_per_hour >= 1000:
        virality_tier = "Moderate"
    else:
        virality_tier = "Emerging"

    # Extract lyrics if in description
    desc = yt_meta.get("description", "")
    lyrics_match = re.search(r"Lyrics:\s*(.*?)(?=\n\n#|$)", desc, re.DOTALL | re.IGNORECASE)
    lyrics = lyrics_match.group(1).strip() if lyrics_match else ""

    # Layer 1: Static Metadata
    upload_date_raw = yt_meta.get("upload_date", "")
    upload_date_fmt = f"{upload_date_raw[:4]}-{upload_date_raw[4:6]}-{upload_date_raw[6:]}" if len(upload_date_raw) == 8 else upload_date_raw

    video_metadata = {
        "video_id": video_id,
        "title": title,
        "full_title": yt_meta.get("fulltitle", title),
        "channel_name": yt_meta.get("channel") or yt_meta.get("uploader", ""),
        "channel_id": yt_meta.get("channel_id", ""),
        "channel_url": yt_meta.get("channel_url", ""),
        "subscribers_count": subscribers,
        "channel_verified": yt_meta.get("channel_is_verified", False),
        "duration_seconds": yt_meta.get("duration", 0),
        "duration_formatted": yt_meta.get("duration_string", ""),
        "upload_date": upload_date_fmt,
        "release_timestamp_utc": datetime.fromtimestamp(rel_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC') if rel_ts else "",
        "category": yt_meta.get("categories", ["Music"])[0] if yt_meta.get("categories") else "Music",
        "tags": yt_meta.get("tags", []),
        "webpage_url": yt_meta.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}",
        "thumbnail_url": yt_meta.get("thumbnail", ""),
        "aspect_ratio": yt_meta.get("aspect_ratio"),
        "resolution": yt_meta.get("resolution", ""),
        "fps": yt_meta.get("fps"),
        "lyrics": lyrics
    }

    with open(os.path.join(output_dir, "video_metadata.json"), "w") as f:
        json.dump(video_metadata, f, indent=2)

    with open(os.path.join(output_dir, "video_metadata.csv"), "w", newline="") as f:
        fields = [k for k in video_metadata.keys() if k not in ["tags", "lyrics"]]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerow({k: v for k, v in video_metadata.items() if k in fields})

    # Layer 2: Telemetry Snapshot
    video_telemetry = {
        "snapshot_timestamp": now_pdt_str,
        "video_id": video_id,
        "title": title,
        "view_count": views,
        "like_count": likes,
        "comment_count": comments_count,
        "channel_subscribers": subscribers,
        "hours_since_release": hours_since_release,
        "views_per_hour": views_per_hour,
        "likes_per_hour": likes_per_hour,
        "like_to_view_ratio_pct": like_ratio,
        "comment_to_view_ratio_pct": comment_ratio,
        "virality_tier": virality_tier
    }

    # Save latest snapshot
    with open(os.path.join(output_dir, "video_telemetry_snapshot.json"), "w") as f:
        json.dump(video_telemetry, f, indent=2)

    with open(os.path.join(output_dir, "video_telemetry_snapshot.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(video_telemetry.keys()))
        writer.writeheader()
        writer.writerow(video_telemetry)

    # Append to longitudinal telemetry history ledger
    telemetry_history_csv = os.path.join(output_dir, "video_telemetry_history.csv")
    history_exists = os.path.exists(telemetry_history_csv)
    with open(telemetry_history_csv, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(video_telemetry.keys()))
        if not history_exists:
            writer.writeheader()
        writer.writerow(video_telemetry)

    # Layer 3: Country Charts & Layer 5: Share Cards
    chart_rankings = []
    share_cards_map = {}
    discovered_daily_date = resolved_target_date
    if not skip_charts:
        if country_filter.lower() == "all":
            countries_to_check = ALL_COUNTRY_CODES
        else:
            countries_to_check = [c.strip().upper() for c in country_filter.split(",") if c.strip()]

        chart_rankings, share_cards_map, discovered_daily_date = sweep_country_charts(
            video_id,
            countries_to_check,
            target_date=resolved_target_date,
            upload_date=upload_date_fmt,
            hours_since_release=hours_since_release,
            cancel_check=cancel_check,
            progress_callback=progress_callback
        )

    # Non-destructive historical chart rank merging
    rankings_json_path = os.path.join(output_dir, "country_chart_rankings.json")
    existing_rankings = []
    if os.path.exists(rankings_json_path):
        try:
            with open(rankings_json_path, "r") as f:
                existing_rankings = json.load(f)
        except Exception:
            existing_rankings = []

    # Deduplicate / merge on (country_code, chart_type, str(chart_date))
    combined_rankings_map = {
        (r.get("country_code"), r.get("chart_type"), str(r.get("chart_date"))): r
        for r in existing_rankings
    }
    for r in chart_rankings:
        combined_rankings_map[(r.get("country_code"), r.get("chart_type"), str(r.get("chart_date")))] = r
    final_rankings = list(combined_rankings_map.values())

    # Calculate all-time best rank and reached_number_one per country across all known cycles
    best_rank_by_country = {}
    for r in final_rankings:
        cc = r.get("country_code")
        pos = r.get("rank_position")
        prev = r.get("previous_position")
        try:
            p_val = int(pos) if pos else 999
        except (ValueError, TypeError):
            p_val = 999
        try:
            prev_val = int(prev) if prev else 999
        except (ValueError, TypeError):
            prev_val = 999
        min_p = min(p_val, prev_val)
        if cc not in best_rank_by_country or min_p < best_rank_by_country[cc]:
            best_rank_by_country[cc] = min_p

    for r in final_rankings:
        cc = r.get("country_code")
        best = best_rank_by_country.get(cc)
        if best and best < 999:
            r["all_time_best_rank"] = best
            r["reached_number_one"] = (best == 1)

    # Sort final rankings: Live Snapshot first, then by date descending, then rank ascending
    def sort_ranking_key(item):
        c_date = str(item.get("chart_date", ""))
        date_score = "9999-99-99" if c_date == "Live Snapshot" else (c_date or "0000-00-00")
        try:
            rank_score = -int(item.get("rank_position", 999))
        except (ValueError, TypeError):
            rank_score = -999
        return (date_score, rank_score)

    final_rankings.sort(key=sort_ranking_key, reverse=True)

    with open(rankings_json_path, "w") as f:
        json.dump(final_rankings, f, indent=2)

    chart_fieldnames = [
        "country_code", "country_name", "chart_type", "rank_position",
        "previous_position", "all_time_best_rank", "reached_number_one",
        "status", "chart_date", "chart_week_label", "video_id", "share_card_url"
    ]
    with open(os.path.join(output_dir, "country_chart_rankings.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=chart_fieldnames, extrasaction="ignore")
        writer.writeheader()
        if final_rankings:
            writer.writerows(final_rankings)

    # Layer 5: Dedicated Share Cards Registry (Non-destructive merge)
    share_cards_json_path = os.path.join(output_dir, "share_cards_registry.json")
    existing_share_cards = []
    if os.path.exists(share_cards_json_path):
        try:
            with open(share_cards_json_path, "r") as f:
                existing_share_cards = json.load(f)
        except Exception:
            existing_share_cards = []

    combined_share_map = {s.get("country_code"): s.get("share_card_url") for s in existing_share_cards if s.get("country_code")}
    combined_share_map.update(share_cards_map)
    share_cards_list = [{"country_code": k, "share_card_url": v} for k, v in sorted(combined_share_map.items())]

    with open(share_cards_json_path, "w") as f:
        json.dump(share_cards_list, f, indent=2)

    with open(os.path.join(output_dir, "share_cards_registry.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["country_code", "share_card_url"])
        writer.writeheader()
        writer.writerows(share_cards_list)

    # Layer 4: Top Ranked Comments (Strictly sorted by like_count descending; preserve existing if skipped)
    comments_json_path = os.path.join(output_dir, "top_comments_ranked.json")
    parsed_comments = []
    raw_comments = yt_meta.get("comments") or []

    # Filter to root comments only and sort strictly by like_count descending
    root_comments = [
        c for c in raw_comments
        if c.get("parent", "root") == "root" and "." not in str(c.get("id", ""))
    ]
    if not root_comments:
        root_comments = list(raw_comments)

    root_comments.sort(
        key=lambda c: (
            1 if c.get("is_pinned") else 0,
            int(c.get("like_count") or 0),
            int(c.get("timestamp") or 0)
        ),
        reverse=True
    )

    target_limit = actual_comments_to_pull if actual_comments_to_pull > 0 else 20
    seen_cids = set()
    deduped_comments = []
    for c in root_comments:
        cid = str(c.get("id", ""))
        if cid and cid in seen_cids:
            continue
        if cid:
            seen_cids.add(cid)
        deduped_comments.append(c)
        if len(deduped_comments) >= target_limit:
            break

    # Re-sort final slice strictly by like_count descending so #1 is always the highest-liked comment
    deduped_comments.sort(key=lambda c: int(c.get("like_count") or 0), reverse=True)

    for idx, c in enumerate(deduped_comments, start=1):
        ts = c.get("timestamp")
        pub_date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d') if ts else ""
        time_text = (c.get("_time_text") or "").strip()
        pub_ts_label = f"{pub_date} ({time_text})" if (pub_date and time_text) else (pub_date or time_text)
        cid = c.get("id", "")
        parsed_comments.append({
            "rank": idx,
            "comment_id": cid,
            "comment_url": f"https://www.youtube.com/watch?v={video_id}&lc={cid}" if cid else f"https://www.youtube.com/watch?v={video_id}",
            "author_handle": c.get("author", ""),
            "author_channel_id": c.get("author_id", ""),
            "author_verified": bool(c.get("author_is_verified", False)),
            "is_pinned": bool(c.get("is_pinned", False)),
            "comment_text": (c.get("text") or "").replace("\n", " ").strip(),
            "publish_date": pub_date,
            "relative_time": time_text,
            "publish_timestamp_pst": pub_ts_label,
            "likes_count": int(c.get("like_count") or 0),
            "reply_count": int(c.get("reply_count") or 0),
            "video_id": video_id
        })

    if not parsed_comments and os.path.exists(comments_json_path):
        try:
            with open(comments_json_path, "r") as f:
                parsed_comments = json.load(f)
        except Exception:
            parsed_comments = []

    with open(comments_json_path, "w") as f:
        json.dump(parsed_comments, f, indent=2)

    with open(os.path.join(output_dir, "top_comments_ranked.csv"), "w", newline="") as f:
        if parsed_comments:
            writer = csv.DictWriter(f, fieldnames=list(parsed_comments[0].keys()), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(parsed_comments)
        else:
            writer = csv.DictWriter(f, fieldnames=["rank", "comment_id", "comment_url", "author_handle", "author_channel_id", "comment_text", "publish_date", "publish_timestamp_pst", "likes_count", "reply_count", "video_id"])
            writer.writeheader()

    # Date Scope & Reporting Analysis
    daily_dates = sorted(list(set(
        str(r.get("chart_date")) for r in final_rankings 
        if r.get("chart_date") and r.get("chart_date") not in ["Live Snapshot", "Latest Daily", "None", ""]
    )))
    has_live_trending = any(r.get("chart_type") == "Overall YouTube Trending" for r in final_rankings)

    # 1. Target scope mode
    if target_date:
        if resolved_target_date and resolved_target_date != target_date:
            scope_mode_str = f"Historical Target (Keyword: '{target_date}' -> Resolved: {resolved_target_date})"
        else:
            scope_mode_str = f"Historical Specific Date ({resolved_target_date})"
    else:
        scope_mode_str = "Latest Active Daily Cycle + Live Trending Snapshot (Default)"

    # 2. Daily Music Chart Cycle
    if discovered_daily_date:
        daily_cycle_str = f"{discovered_daily_date} (Finalized 24h YouTube music chart cycle; ~24-48h calculation lag)"
    elif daily_dates:
        daily_cycle_str = f"{daily_dates[-1]} (Finalized 24h cycle)"
    elif resolved_target_date:
        daily_cycle_str = f"{resolved_target_date} (Targeted query)"
    else:
        daily_cycle_str = "N/A (Charts skipped or not yet indexed by YouTube Charts)"

    # 3. Trending Feed State
    if target_date or resolved_target_date:
        trending_feed_str = "Bypassed (YouTube Trending is ephemeral live real-time only; not queryable for historical dates)"
    elif has_live_trending:
        trending_feed_str = f"Live Snapshot Captured ({now_pdt_str})"
    elif not skip_charts:
        trending_feed_str = f"Live Snapshot Evaluated (No active trending positions in queried territories at {now_pdt_str})"
    else:
        trending_feed_str = "Bypassed (--skip-charts enabled)"

    # 4. Dataset Date Coverage
    all_dates_recorded = []
    if daily_dates:
        if len(daily_dates) == 1:
            all_dates_recorded.append(f"Daily Chart: {daily_dates[0]}")
        else:
            all_dates_recorded.append(f"Daily Charts: {daily_dates[0]} to {daily_dates[-1]} ({len(daily_dates)} cycles)")
    if has_live_trending:
        all_dates_recorded.append(f"Trending: Live Snapshot ({now_pdt_str})")

    if not all_dates_recorded:
        dataset_dates_str = f"Single Snapshot ({now_pdt_str})"
    else:
        dataset_dates_str = " | ".join(all_dates_recorded)

    # Unified Composable Manifest
    manifest = {
        "schema_version": "1.2.0",
        "video_id": video_id,
        "entity_name": entity_name,
        "target_date_scoped": resolved_target_date or "latest",
        "generated_at_pst": now_pdt_str,
        "date_metrics": {
            "scope_mode": scope_mode_str,
            "daily_chart_cycle": daily_cycle_str,
            "trending_feed_state": trending_feed_str,
            "dataset_date_coverage": dataset_dates_str,
            "all_daily_dates": daily_dates,
            "has_live_trending": has_live_trending
        },
        "composable_layers": {
            "metadata": {
                "file_json": "video_metadata.json",
                "file_csv": "video_metadata.csv",
                "description": "Static identity, duration, channel info, lyrics, tags"
            },
            "telemetry": {
                "file_json": "video_telemetry_snapshot.json",
                "file_csv": "video_telemetry_snapshot.csv",
                "description": "Live views, likes, comments, velocity metrics and virality tier"
            },
            "charts": {
                "file_json": "country_chart_rankings.json",
                "file_csv": "country_chart_rankings.csv",
                "records_count": len(final_rankings),
                "description": "Multi-country chart and trending rankings across recorded dates",
                "unique_countries_count": len(set(r["country_code"] for r in final_rankings))
            },
            "audience": {
                "file_json": "top_comments_ranked.json",
                "file_csv": "top_comments_ranked.csv",
                "records_count": len(parsed_comments),
                "description": "Top ranked community comments and reaction sentiment"
            },
            "share_cards": {
                "file_json": "share_cards_registry.json",
                "file_csv": "share_cards_registry.csv",
                "records_count": len(share_cards_list),
                "description": "Official YouTube Charts 1080x1920 9:16 high-res vertical share card image asset URLs"
            }
        },
        "summary_metrics": {
            "view_count": views,
            "like_count": likes,
            "comment_count": comments_count,
            "number_of_countries_charting": len(set(r["country_code"] for r in final_rankings)),
            "number_one_countries": sorted(list(set(r["country_name"] for r in final_rankings if r.get("rank_position") == 1)))
        }
    }

    with open(os.path.join(output_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    # Curated Select Top Territory Placements (Peak Highlights)
    select_top_placements = get_select_top_placements(final_rankings, max_rows=25)
    number_one_champions = [r for r in final_rankings if int(r.get("rank_position", 999)) == 1]

    # Surface groupings
    daily_music_rankings = [r for r in final_rankings if r.get("chart_type") == "Daily Top Music Videos"]
    trending_rankings = [r for r in final_rankings if r.get("chart_type") == "Overall YouTube Trending"]
    other_surfaces_rankings = [r for r in final_rankings if r.get("chart_type") not in ["Daily Top Music Videos", "Overall YouTube Trending"]]

    # Executive Markdown Report
    report_filename = f"{slug}_video_intelligence_report.md"
    report_path = os.path.join(output_dir, report_filename)
    with open(report_path, "w") as f:
        f.write(f"""---
feature: YouTube Video Intelligence Dossier
status: Final
date: {today_pdt_str}
---

# 🚀 {entity_name} — Video Intelligence Report

> **Target Video ID:** `{video_id}`  
> **Official URL:** [https://www.youtube.com/watch?v={video_id}](https://www.youtube.com/watch?v={video_id})  
> **Channel:** **{video_metadata['channel_name']}** ({subscribers:,.0f} Subscribers)  
> **Snapshot Timestamp:** `{now_pdt_str}`  
> **Date Scope Target:** `{scope_mode_str}`  
> **Daily Music Chart Cycle:** `{daily_cycle_str}`  
> **Trending Feed State:** `{trending_feed_str}`  
> **Dataset Date Coverage:** `{dataset_dates_str}`  
> **Dataset Path:** [`{output_dir}`](file://{output_dir})  

---

## 📊 1. Executive Performance & Velocity Profile

| Metric | Measured Value | Velocity / Ratio | Status |
| :--- | :--- | :--- | :--- |
| **Total Views** | **{views:,}** | **{views_per_hour:,.0f} views/hr** | {virality_tier} |
| **Total Likes** | **{likes:,}** | **{likes_per_hour:,.0f} likes/hr** | Active Engagement |
| **Total Comments** | **{comments_count:,}** | **{comments_count / hours_since_release:,.0f} comments/hr** | Community Discussion |
| **Like-to-View Ratio** | **{like_ratio:.2f}%** | Conversion Efficiency | Organic Sentiment |
| **Hours Since Debut** | **~{hours_since_release:.1f} hours** | Released {video_metadata['upload_date']} | Active Velocity |
| **Virality Tier** | **{virality_tier}** | Telemetry Tier | Global Market Footprint |

---

## 🌟 2. Select Top Territory Placements (Peak Highlights)

Curated showcase of peak chart positions, key international markets, and national trending highlights:
""")

        if number_one_champions:
            champ_pills = ", ".join(f"`{COUNTRY_NAMES.get(r['country_code'], r.get('country_name', ''))} {get_country_flag(r['country_code'])}`" for r in number_one_champions)
            f.write(f"\n> 🏆 **#1 Champion Countries ({len(number_one_champions)}):** {champ_pills}\n\n")

        f.write("""| Country | Flag | Code | Surface / Chart Type | Rank Position | Chart Date | Peak Classification | Visual Asset |
| :--- | :---: | :---: | :--- | :---: | :---: | :--- | :---: |
""")
        if select_top_placements:
            for r in select_top_placements:
                flag = get_country_flag(r['country_code'])
                c_name = COUNTRY_NAMES.get(r['country_code'], r.get('country_name', ''))
                pos = r.get('rank_position', '-')
                peak_cls = classify_peak_rank(pos)
                c_date = r.get('chart_date', '-')
                card_link = f"[Open Card]({r['share_card_url']})" if r.get('share_card_url') else "—"
                f.write(f"| **{c_name}** | {flag} | `{r['country_code']}` | {r.get('chart_type', '-')} | **#{pos}** | `{c_date}` | {peak_cls} | {card_link} |\n")
        else:
            f.write("| *No top territory placements recorded* | - | - | - | - | - | - | - |\n")

        f.write(f"""
---

## 🌍 3. Global Country Chart Matrix by Surface ({len(final_rankings)} Total Placements across {manifest['summary_metrics']['number_of_countries_charting']} Countries)
""")

        # 3A. Daily Top Music Videos
        daily_countries_cnt = len(set(r['country_code'] for r in daily_music_rankings))
        f.write(f"""
### 3A. Daily Top Music Videos Chart ({len(daily_music_rankings)} Placements across {daily_countries_cnt} Countries)

> **Chart Surface:** `Daily Top Music Videos` (`CHART_TYPE_VIDEOS` with `CHART_PERIOD_TYPE_DAILY`)  
> **Cycle Coverage:** `{daily_cycle_str}`  
> **Calculation Basis:** Audited 24-hour YouTube music video streams, verified on-demand views, and regional sales metrics.

| Country | Flag | Code | Rank Position | Prev Pos | Chart Date | Peak Classification | Official Share Card |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- | :---: |
""")
        if daily_music_rankings:
            for r in daily_music_rankings:
                flag = get_country_flag(r['country_code'])
                c_name = COUNTRY_NAMES.get(r['country_code'], r.get('country_name', ''))
                pos = r.get('rank_position', '-')
                prev_pos = f"#{r['previous_position']}" if r.get('previous_position') else "—"
                peak_cls = classify_peak_rank(pos)
                c_date = r.get('chart_date', '-')
                card_link = f"[Open Card]({r['share_card_url']})" if r.get('share_card_url') else "—"
                f.write(f"| **{c_name}** | {flag} | `{r['country_code']}` | **#{pos}** | {prev_pos} | `{c_date}` | {peak_cls} | {card_link} |\n")
        else:
            f.write("| *No Daily Music Video placements found in queried territories* | - | - | - | - | - | - | - |\n")

        # 3B. Overall YouTube Trending
        trending_countries_cnt = len(set(r['country_code'] for r in trending_rankings))
        f.write(f"""
### 3B. Overall YouTube Trending ({len(trending_rankings)} Placements across {trending_countries_cnt} Countries)

> **Chart Surface:** `Overall YouTube Trending` (`CHART_TYPE_TRENDING_VIDEOS`)  
> **Snapshot Timestamp:** `{now_pdt_str}`  
> **Calculation Basis:** Live real-time cross-category velocity feed reflecting organic viewer growth in each country.

| Country | Flag | Code | Rank Position | Prev Pos | Snapshot State | Peak Classification | Official Share Card |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- | :---: |
""")
        if trending_rankings:
            for r in trending_rankings:
                flag = get_country_flag(r['country_code'])
                c_name = COUNTRY_NAMES.get(r['country_code'], r.get('country_name', ''))
                pos = r.get('rank_position', '-')
                prev_pos = f"#{r['previous_position']}" if r.get('previous_position') else "—"
                peak_cls = classify_peak_rank(pos)
                c_date = r.get('chart_date', '-')
                card_link = f"[Open Card]({r['share_card_url']})" if r.get('share_card_url') else "—"
                f.write(f"| **{c_name}** | {flag} | `{r['country_code']}` | **#{pos}** | {prev_pos} | `{c_date}` | {peak_cls} | {card_link} |\n")
        else:
            f.write(f"| *Trending feed bypassed or no active placements found ({trending_feed_str})* | - | - | - | - | - | - | - |\n")

        # 3C. Other Surfaces (if any)
        if other_surfaces_rankings:
            f.write(f"""
### 3C. Additional Chart Surfaces ({len(other_surfaces_rankings)} Placements)

| Country | Flag | Code | Surface | Rank Position | Chart Date | Peak Classification | Official Share Card |
| :--- | :---: | :---: | :--- | :---: | :---: | :--- | :---: |
""")
            for r in other_surfaces_rankings:
                flag = get_country_flag(r['country_code'])
                c_name = COUNTRY_NAMES.get(r['country_code'], r.get('country_name', ''))
                pos = r.get('rank_position', '-')
                peak_cls = classify_peak_rank(pos)
                c_date = r.get('chart_date', '-')
                card_link = f"[Open Card]({r['share_card_url']})" if r.get('share_card_url') else "—"
                f.write(f"| **{c_name}** | {flag} | `{r['country_code']}` | {r.get('chart_type', '-')} | **#{pos}** | `{c_date}` | {peak_cls} | {card_link} |\n")

        # 4. Top Community Comments
        f.write(f"""
---

## 💬 4. Top Ranked Audience Comments (Sample)

| Rank | Author | Likes | Comment Snippet |
| :---: | :--- | :---: | :--- |
""")
        if parsed_comments:
            for c in parsed_comments[:10]:
                text_snippet = c['comment_text'][:90].replace("|", "-")
                f.write(f"| **#{c['rank']}** | `{c['author_handle']}` | **{c['likes_count']:,}** | \"{text_snippet}...\" |\n")
        else:
            f.write("| - | *No comments captured (comment extraction skipped by default for fast execution)* | - | - |\n")

        # 5. Official YouTube Charts 9:16 Vertical Share Card Gallery
        f.write(f"""
---

## 🎨 5. Official YouTube Charts 9:16 Vertical Share Card Gallery (Sample)

These are official high-resolution (1080x1920) vertical JPEG image assets generated directly by YouTube's analytics service:

| Country | Flag | Code | Chart Surface | Rank Position | Official 1080x1920 Share Card Direct Link |
| :--- | :---: | :---: | :--- | :---: | :--- |
""")
        sample_cards = [r for r in final_rankings if r.get("share_card_url")]
        key_cards_set = set()
        deduped_sample_cards = []
        for r in sample_cards:
            cc = r.get("country_code")
            if cc not in key_cards_set:
                key_cards_set.add(cc)
                deduped_sample_cards.append(r)

        if deduped_sample_cards:
            for sc in deduped_sample_cards[:15]:
                flag = get_country_flag(sc['country_code'])
                c_name = COUNTRY_NAMES.get(sc['country_code'], sc.get('country_name', ''))
                f.write(f"| **{c_name}** | {flag} | `{sc['country_code']}` | {sc.get('chart_type', 'Chart')} | **#{sc.get('rank_position', '-')}** | [Open 1080x1920 Card]({sc['share_card_url']}) |\n")
        else:
            f.write("| *No share card assets registered* | - | - | - | - | - |\n")

        # 6. Discrete Tracking File Architecture
        f.write(f"""
---

## 🗂️ 6. Discrete Tracking File Architecture

The dataset is compiled into discrete, isolated, and composable JSON/CSV files:

1. **[`manifest.json`](file://{os.path.join(output_dir, "manifest.json")})**: Unified composable descriptor linking all data layers.
2. **[`video_metadata.json`](file://{os.path.join(output_dir, "video_metadata.json")})** & **[`video_metadata.csv`](file://{os.path.join(output_dir, "video_metadata.csv")})**: Static video identity, tags, lyrics, resolution, and format specs.
3. **[`video_telemetry_snapshot.json`](file://{os.path.join(output_dir, "video_telemetry_snapshot.json")})** & **[`video_telemetry_snapshot.csv`](file://{os.path.join(output_dir, "video_telemetry_snapshot.csv")})**: Live view velocity, like velocity, ratios, and virality tier.
4. **[`video_telemetry_history.csv`](file://{os.path.join(output_dir, "video_telemetry_history.csv")})**: Append-only longitudinal telemetry history ledger.
5. **[`country_chart_rankings.json`](file://{os.path.join(output_dir, "country_chart_rankings.json")})** & **[`country_chart_rankings.csv`](file://{os.path.join(output_dir, "country_chart_rankings.csv")})**: Regional chart rankings across international territories with explicit `chart_date`.
6. **[`share_cards_registry.json`](file://{os.path.join(output_dir, "share_cards_registry.json")})** & **[`share_cards_registry.csv`](file://{os.path.join(output_dir, "share_cards_registry.csv")})**: Official 1080x1920 9:16 high-res vertical share card asset URLs.
7. **[`top_comments_ranked.json`](file://{os.path.join(output_dir, "top_comments_ranked.json")})** & **[`top_comments_ranked.csv`](file://{os.path.join(output_dir, "top_comments_ranked.csv")})**: Upvoted community comments.
""")

    print(f"\n[✔] Dossier successfully compiled!")
    print(f"    - Output Directory: {output_dir}")
    print(f"    - Executive Report: {report_path}")
    print(f"    - Chart Placements: {len(chart_rankings)} across {manifest['summary_metrics']['number_of_countries_charting']} countries")
    print(f"    - Share Cards: {len(share_cards_list)} official assets registered")
    return output_dir

def preprocess_args(argv):
    """Normalizes flags and arguments so hyphen-prefixed video IDs don't collide with flags."""
    new_argv = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ["-i", "--video-id"] and i + 1 < len(argv):
            val = argv[i + 1]
            new_argv.append(f"--video-id={val}")
            i += 2
            continue
        elif arg in ["-u", "--url"] and i + 1 < len(argv):
            val = argv[i + 1]
            new_argv.append(f"--url={val}")
            i += 2
            continue
        elif arg.startswith("-") and not arg.startswith("--") and len(arg) == 11 and re.match(r"^-[a-zA-Z0-9_-]{10}$", arg):
            # Positional video ID starting with a hyphen (e.g. -5ZXrO_lYSA) -> convert to --video-id=...
            new_argv.append(f"--video-id={arg}")
            i += 1
            continue
        new_argv.append(arg)
        i += 1
    return new_argv

def main():
    raw_args = preprocess_args(sys.argv[1:])
    parser = argparse.ArgumentParser(
        description="Global Multi-Country YouTube Track & Video Intelligence Dossier Engine"
    )
    parser.add_argument(
        "target", nargs="?", default=None,
        help="YouTube video URL or 11-character video ID (e.g. 'https://www.youtube.com/watch?v=...' or 'FyS5dAywkEo')"
    )
    parser.add_argument("--url", "-u", type=str, help="Full YouTube video URL")
    parser.add_argument("--video-id", "-i", type=str, help="11-character YouTube video ID")
    parser.add_argument("--channel", type=str, default=None,
                        help="Artist YouTube channel URL, handle (@...), or channel ID (UC...)")
    parser.add_argument("--artist", type=str, default=None,
                        help="Artist name or search query (e.g. 'LISA', 'Megan Thee Stallion')")
    parser.add_argument(
        "--date", "-d", type=str, default=None,
        help="Date scope for historical charts (YYYY-MM-DD, or 'release', 'debut', 'yesterday')."
    )
    parser.add_argument(
        "--countries", "-c", type=str, default="all",
        help="Comma-separated country ISO codes (e.g. 'US,TH,BR,FR') or 'all' for complete 86-country sweep (default: all)"
    )
    parser.add_argument(
        "--with-comments", "--include-comments", action="store_true",
        help="Extract top community comments (default: False / skipped for speed)"
    )
    parser.add_argument(
        "--max-comments", "-m", type=int, default=0,
        help="Max top comments to extract if enabled (default: 0 / disabled; passing > 0 enables comments)"
    )
    parser.add_argument(
        "--output-dir", "-o", type=str, default=None,
        help="Custom output directory path"
    )
    parser.add_argument(
        "--skip-charts", action="store_true",
        help="Skip chart scraping (metadata and telemetry only)"
    )
    parser.add_argument(
        "--skip-comments", action="store_true",
        help="Explicitly skip comment extraction (default behavior)"
    )

    args = parser.parse_args(raw_args)
    target_input = args.channel or args.artist or args.target or args.url or args.video_id
    if not target_input:
        parser.error("A YouTube video URL, ID, Channel, or Artist is required.")

    # Check if target is an artist or channel
    is_channel_target = (
        args.channel is not None or
        args.artist is not None or
        (target_input and (
            target_input.startswith("@") or
            (target_input.startswith("UC") and len(target_input) == 24) or
            "/@" in target_input or
            "/channel/" in target_input or
            "/c/" in target_input or
            "/user/" in target_input
        ))
    )

    if is_channel_target:
        print("[+] Channel/Artist target detected -> routing to Artist Chart Sweep Engine...")
        from sweep_youtube_artist_charts import build_artist_catalog_dossier
        build_artist_catalog_dossier(
            target_input=target_input,
            explicit_artist=args.artist,
            countries_input=args.countries if args.countries != "all" else "all",
            target_date=args.date,
            output_dir=args.output_dir,
            run_track_dossiers=False
        )
        return

    # Determine comment count
    if args.skip_comments:
        comments_count = 0
    elif args.max_comments > 0:
        comments_count = args.max_comments
    elif args.with_comments:
        comments_count = 20
    else:
        comments_count = 0

    try:
        build_dossier(
            video_input=target_input,
            target_date=args.date,
            country_filter=args.countries,
            max_comments=comments_count,
            output_dir=args.output_dir,
            skip_charts=args.skip_charts,
            include_comments=(comments_count > 0)
        )
    except Exception as e:
        print(f"[!] Error building dossier: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
