#!/usr/bin/env python3
"""
YouTube Track & Artist Intelligence Dossier — Web Console & API Server
Author: Antigravity Multi-Agent System
Description:
    Serves a Swiss-Industrial High-Density Telemetry Workspace locally and remotely,
    providing live execution of Single-Track 5-Layer Dossiers and Artist/Channel Top 100
    Chart Sweeps, plus preloaded offline inspection of all existing YouTube datasets.
"""

import os
import re
import io
import sys
import csv
import json
import time
import zipfile
import threading
import subprocess
import urllib.parse
import urllib.request
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
import zoneinfo

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.append(SCRIPT_DIR)

from build_youtube_track_dossier import (
    COUNTRY_NAMES,
    ALL_COUNTRY_CODES,
    get_country_flag,
    classify_peak_rank,
    extract_video_id,
    build_dossier
)
from sweep_youtube_artist_charts import (
    DEFAULT_KEY_MARKETS,
    build_artist_catalog_dossier
)

# Live Sweep State & Duplicate Submission Lock
SWEEP_STATE_LOCK = threading.Lock()
SWEEP_STATE = {
    "active": False,
    "cancelled": False,
    "mode": "",
    "target": "",
    "signature": "",
    "started_at": 0.0,
    "current_idx": 0,
    "total_countries": 0,
    "current_country_code": "",
    "current_country_name": "",
    "hits_found": 0,
    "message": "Idle"
}

def update_sweep_progress(idx: int, total: int, cc: str, cname: str, hits: int, msg: str):
    with SWEEP_STATE_LOCK:
        SWEEP_STATE["current_idx"] = idx
        SWEEP_STATE["total_countries"] = total
        SWEEP_STATE["current_country_code"] = cc
        SWEEP_STATE["current_country_name"] = cname
        SWEEP_STATE["hits_found"] = hits
        SWEEP_STATE["message"] = msg

def is_sweep_cancelled() -> bool:
    with SWEEP_STATE_LOCK:
        return bool(SWEEP_STATE["cancelled"])

PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BASE_DATA_DIR = PROJECT_ROOT if os.path.isdir(os.path.join(PROJECT_ROOT, "datasets", "youtube")) else "/Users/bibbler/Downloads/_Projects/Antigravity/Scraper_projects/blackpink-twitter/data"
YOUTUBE_DATASETS_DIR = os.path.join(BASE_DATA_DIR, "datasets", "youtube")
DASHBOARDS_DIR = os.path.join(BASE_DATA_DIR, "dashboards")
HTML_OUTPUT_PATH = os.path.join(DASHBOARDS_DIR, "youtube_dossier_console.html")

def sanitize_filename_part(val: str, max_len: int = 80) -> str:
    clean = re.sub(r'[^\w\s-]', '', str(val or '')).strip()
    return re.sub(r'[-\s]+', '_', clean)[:max_len]

def build_share_card_filename(entity_slug: str, r: dict) -> str:
    cc = sanitize_filename_part(r.get("country_code") or "XX", 8).upper()
    cname = sanitize_filename_part(r.get("country_name") or cc, 28)
    rank = int(r.get("rank_position") or 99)
    prev = r.get("previous_position")
    best = int(r.get("all_time_best_rank") or rank)
    surf_raw = str(r.get("chart_type") or "")
    surf = "DailyTopMV" if "Daily" in surf_raw else "LiveTrending"
    cdate = sanitize_filename_part(r.get("chart_date") or "Latest", 20)
    stat_tag = "Champion" if rank == 1 else ("PastNum1" if (best == 1 or prev == 1) else f"Peak{best}")
    slug = sanitize_filename_part(entity_slug, 28)
    return f"{slug}__{cc}_{cname}__Rank{rank:02d}_{stat_tag}__{surf}__{cdate}_9x16.jpg"

def fetch_or_cache_share_card(folder_path: str, url: str, filename: str) -> tuple:
    """
    Checks local share_cards_cache/ first; if missing, downloads 1080x1920 JPEG from YouTube Charts
    and caches it on disk. Returns (ok: bool, cached_file_path: str, img_bytes: bytes).
    """
    if not url or not filename:
        return (False, "", b"")
    cache_dir = os.path.join(folder_path, "share_cards_cache")
    os.makedirs(cache_dir, exist_ok=True)
    cached_file = os.path.join(cache_dir, os.path.basename(filename))
    if os.path.isfile(cached_file) and os.path.getsize(cached_file) > 500:
        try:
            with open(cached_file, "rb") as fp:
                return (True, cached_file, fp.read())
        except Exception:
            pass
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            img_bytes = resp.read()
        if img_bytes and len(img_bytes) > 500:
            with open(cached_file, "wb") as fp:
                fp.write(img_bytes)
            return (True, cached_file, img_bytes)
    except Exception:
        pass
    return (False, cached_file, b"")

def read_json_safe(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def read_csv_safe(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return list(csv.DictReader(f))
        except Exception:
            return []
    return []

def read_text_safe(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""
    return ""


def normalize_chart_date(raw_val, share_card_url: str = "", chart_type: str = "", fallback_date: str = "") -> tuple:
    """
    Returns (clean_yyyy_mm_dd_or_state, human_share_card_date, iso_week_label)
    by normalizing dict/string dates and decoding the YouTube Share Card Protobuf token (?r=).
    """
    import ast, base64, re
    card_date_human = ""
    if share_card_url and "?r=" in share_card_url:
        try:
            tok = share_card_url.split("?r=")[1].split("&")[0]
            tok += "=" * (-len(tok) % 4)
            decoded = base64.urlsafe_b64decode(tok).decode("utf-8", errors="ignore")
            m = re.search(r"([A-Z][a-z]{2}\s+\d{1,2},\s+20\d{2})", decoded)
            if m:
                card_date_human = m.group(1)
        except Exception:
            pass

    clean_date = ""
    if isinstance(raw_val, dict):
        y, mo, d = raw_val.get("year"), raw_val.get("month"), raw_val.get("day")
        if y and mo and d:
            clean_date = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    elif raw_val:
        s = str(raw_val).strip()
        if s.startswith("{") and "year" in s:
            try:
                parsed = ast.literal_eval(s)
                if isinstance(parsed, dict) and parsed.get("year"):
                    clean_date = f"{int(parsed['year']):04d}-{int(parsed['month']):02d}-{int(parsed['day']):02d}"
            except Exception:
                clean_date = s
        else:
            clean_date = s

    if clean_date in ["", "None", "Latest Daily"] and card_date_human:
        try:
            dt = datetime.strptime(card_date_human, "%b %d, %Y")
            clean_date = dt.strftime("%Y-%m-%d")
        except Exception:
            clean_date = card_date_human

    if not clean_date:
        if "Trending" in str(chart_type):
            clean_date = "Live Snapshot"
        else:
            clean_date = fallback_date or "Latest Daily"

    week_label = ""
    if re.match(r"^\d{4}-\d{2}-\d{2}$", str(clean_date)):
        try:
            dt = datetime.strptime(str(clean_date), "%Y-%m-%d")
            iso_yr, iso_wk, _ = dt.isocalendar()
            week_label = f"{iso_yr}-W{iso_wk:02d} ({dt.strftime('%b %d, %Y')})"
        except Exception:
            week_label = str(clean_date)
    elif card_date_human:
        try:
            dt = datetime.strptime(card_date_human, "%b %d, %Y")
            iso_yr, iso_wk, _ = dt.isocalendar()
            week_label = f"{iso_yr}-W{iso_wk:02d} ({card_date_human})"
        except Exception:
            week_label = card_date_human
    else:
        week_label = str(clean_date)

    return str(clean_date), card_date_human, week_label


def enrich_rankings_with_history(rankings: list, fallback_date: str = "") -> list:
    """
    Enriches each ranking row with normalized chart_date, card_cycle_date, chart_week_label,
    all_time_best_rank, reached_number_one, number_one_dates, and territory_history (all dates/weeks for that country).
    """
    # Pass 1: Normalize dates and individual row flags
    by_country = {}
    for r in rankings:
        cc = (r.get("country_code") or "").upper()
        r["country_code"] = cc
        r["country_name"] = COUNTRY_NAMES.get(cc, r.get("country_name", cc))
        r["flag"] = get_country_flag(cc)
        ctype = r.get("chart_type", "")
        if ctype == "YouTube Music Trending":
            ctype = "Daily Top Music Videos"
            r["chart_type"] = ctype

        clean_d, card_d, wk_lbl = normalize_chart_date(
            r.get("chart_date") or r.get("captured_at"),
            r.get("share_card_url", ""),
            ctype,
            fallback_date
        )
        r["chart_date"] = clean_d
        r["card_cycle_date"] = card_d or clean_d
        r["chart_week_label"] = wk_lbl

        curr_pos = int(r.get("rank_position") or 999)
        prev_pos = int(r["previous_position"]) if r.get("previous_position") not in [None, "", "None"] else None
        r["status"] = classify_peak_rank(curr_pos)
        r["is_current_num1"] = (curr_pos == 1)
        r["is_prev_num1"] = (prev_pos == 1)

        by_country.setdefault(cc, []).append(r)

    # Pass 2: Build per-territory longitudinal history & Past/All-Time #1 tracking
    for cc, rows in by_country.items():
        # Sort chronologically / by surface
        sorted_rows = sorted(rows, key=lambda x: (str(x.get("chart_date", "")), str(x.get("chart_type", ""))), reverse=True)
        best_rank = 999
        num1_Timeline = []
        history_snapshots = []

        for item in sorted_rows:
            c_pos = int(item.get("rank_position") or 999)
            p_pos = int(item["previous_position"]) if item.get("previous_position") not in [None, "", "None"] else None
            if c_pos < best_rank:
                best_rank = c_pos
            if p_pos is not None and p_pos < best_rank:
                best_rank = p_pos

            d_label = item.get("chart_date")
            wk_str = item.get("chart_week_label")
            surf_short = "Daily" if "Daily" in item.get("chart_type", "") else "Trending"

            if c_pos == 1:
                num1_Timeline.append({
                    "type": "Active / Snapshot #1",
                    "rank": 1,
                    "chart_date": d_label,
                    "chart_week": wk_str,
                    "card_cycle_date": item.get("card_cycle_date", ""),
                    "chart_type": item.get("chart_type", ""),
                    "share_card_url": item.get("share_card_url", "")
                })
            if p_pos == 1 and c_pos != 1:
                # Infer prior cycle date if chart_date is YYYY-MM-DD
                prior_date_str = f"Prior Cycle (before {d_label})"
                try:
                    dt_prev = datetime.strptime(str(d_label), "%Y-%m-%d") - timedelta(days=1)
                    iso_y, iso_w, _ = dt_prev.isocalendar()
                    prior_date_str = f"{dt_prev.strftime('%Y-%m-%d')} ({ iso_y }-W{ iso_w:02d })"
                except Exception:
                    pass
                num1_Timeline.append({
                    "type": "Past Cycle #1 (via Previous Rank #1)",
                    "rank": 1,
                    "current_rank": c_pos,
                    "chart_date": prior_date_str,
                    "chart_week": wk_str,
                    "card_cycle_date": item.get("card_cycle_date", ""),
                    "chart_type": item.get("chart_type", ""),
                    "share_card_url": item.get("share_card_url", "")
                })

            history_snapshots.append({
                "chart_date": d_label,
                "chart_week": wk_str,
                "card_cycle_date": item.get("card_cycle_date", ""),
                "chart_type": item.get("chart_type", ""),
                "surface_short": surf_short,
                "rank_position": c_pos,
                "previous_position": p_pos,
                "status": item.get("status", ""),
                "share_card_url": item.get("share_card_url", ""),
                "video_id": item.get("video_id", ""),
                "title": item.get("title", "")
            })

        reached_num1 = (best_rank == 1)
        for item in rows:
            item["all_time_best_rank"] = best_rank
            item["reached_number_one"] = reached_num1
            item["is_past_only_num1"] = (reached_num1 and int(item.get("rank_position") or 999) > 1)
            item["number_one_timeline"] = num1_Timeline
            item["territory_history"] = history_snapshots

    return rankings


def load_all_youtube_datasets() -> dict:
    """Scans blackpink-twitter/data/datasets/youtube/ and loads all track & artist dossiers."""
    os.makedirs(YOUTUBE_DATASETS_DIR, exist_ok=True)
    tracks = []
    artists = []

    for entry in sorted(os.listdir(YOUTUBE_DATASETS_DIR)):
        folder_path = os.path.join(YOUTUBE_DATASETS_DIR, entry)
        if not os.path.isdir(folder_path) or entry.startswith("."):
            continue

        files_in_dir = sorted([f for f in os.listdir(folder_path) if not f.startswith(".")])
        md_files = [f for f in files_in_dir if f.endswith(".md")]
        report_md = read_text_safe(os.path.join(folder_path, md_files[0])) if md_files else ""

        # Case 1: Artist Catalog Sweep Folder
        if entry.startswith("artist_") or os.path.exists(os.path.join(folder_path, "artist_catalog_manifest.json")):
            manifest = read_json_safe(os.path.join(folder_path, "artist_catalog_manifest.json"), {})
            rankings = read_json_safe(os.path.join(folder_path, "artist_chart_rankings.json"), [])
            enrich_rankings_with_history(rankings, fallback_date="2026-10-30")
            artist_name_val = manifest.get("artist_name", entry.replace("artist_", "").replace("_", " ").title())
            cache_dir = os.path.join(folder_path, "share_cards_cache")
            cached_count = 0
            for r in rankings:
                if r.get("share_card_url"):
                    fn = build_share_card_filename(r.get("title") or artist_name_val, r)
                    r["share_card_filename"] = fn
                    is_cached = os.path.isfile(os.path.join(cache_dir, fn))
                    r["share_card_cached"] = is_cached
                    if is_cached:
                        cached_count += 1

            artists.append({
                "id": entry,
                "kind": "artist",
                "folder": entry,
                "folder_path": folder_path,
                "artist_name": artist_name_val,
                "channel_name": manifest.get("channel_name", ""),
                "channel_id": manifest.get("channel_id", ""),
                "channel_url": manifest.get("channel_url", ""),
                "subscribers": manifest.get("subscribers", 0),
                "generated_at_pst": manifest.get("generated_at_pst", ""),
                "date_metrics": manifest.get("date_metrics", {}),
                "summary": manifest.get("summary", {}),
                "tracks": manifest.get("tracks", []),
                "rankings": rankings,
                "cached_cards_count": cached_count,
                "report_markdown": report_md,
                "files": files_in_dir
            })

        # Case 2: Single-Track 5-Layer Dossier Folder
        elif os.path.exists(os.path.join(folder_path, "manifest.json")):
            manifest = read_json_safe(os.path.join(folder_path, "manifest.json"), {})
            metadata = read_json_safe(os.path.join(folder_path, "video_metadata.json"), {})
            telemetry = read_json_safe(os.path.join(folder_path, "video_telemetry_snapshot.json"), {})
            history = read_csv_safe(os.path.join(folder_path, "video_telemetry_history.csv"))
            rankings = read_json_safe(os.path.join(folder_path, "country_chart_rankings.json"), [])
            share_cards = read_json_safe(os.path.join(folder_path, "share_cards_registry.json"), [])
            comments = read_json_safe(os.path.join(folder_path, "top_comments_ranked.json"), [])

            fallback_d = metadata.get("upload_date") or "2026-09-04"
            enrich_rankings_with_history(rankings, fallback_date=fallback_d)
            entity_title_val = manifest.get("entity_name") or metadata.get("title", entry)
            cache_dir = os.path.join(folder_path, "share_cards_cache")
            cached_count = 0
            for r in rankings:
                if r.get("share_card_url"):
                    fn = build_share_card_filename(entity_title_val, r)
                    r["share_card_filename"] = fn
                    is_cached = os.path.isfile(os.path.join(cache_dir, fn))
                    r["share_card_cached"] = is_cached
                    if is_cached:
                        cached_count += 1

            vid_id = manifest.get("video_id") or metadata.get("video_id", "")
            for c_item in comments:
                cid = c_item.get("comment_id", "")
                cvid = c_item.get("video_id") or vid_id
                if not c_item.get("comment_url"):
                    c_item["comment_url"] = f"https://www.youtube.com/watch?v={cvid}&lc={cid}" if (cvid and cid) else (f"https://www.youtube.com/watch?v={cvid}" if cvid else "")
                if not c_item.get("publish_timestamp_pst"):
                    c_item["publish_timestamp_pst"] = c_item.get("publish_date", "")

            # Ensure comments are strictly sorted by likes_count descending and re-indexed 1..N
            comments.sort(key=lambda c: int(c.get("likes_count") or 0), reverse=True)
            for idx_c, c_item in enumerate(comments, start=1):
                c_item["rank"] = idx_c

            gen_ts = manifest.get("generated_at_pst") or telemetry.get("snapshot_timestamp") or ""

            daily_dates_set = set()
            has_live_trending = False
            for r in rankings:
                cdate = r.get("chart_date", "")
                if cdate not in ["Live Snapshot", "Latest Daily", "None", ""]:
                    daily_dates_set.add(str(cdate))
                if r.get("chart_type") == "Overall YouTube Trending":
                    has_live_trending = True

            daily_dates = sorted(list(daily_dates_set))
            raw_dm = manifest.get("date_metrics") or {}
            # Clean any dict string leakage in date_metrics
            clean_daily_cycle, _, _ = normalize_chart_date(raw_dm.get("daily_chart_cycle", ""), fallback_date=daily_dates[-1] if daily_dates else "")
            date_metrics = {
                "scope_mode": raw_dm.get("scope_mode") or "Latest Active Daily Cycle + Live Trending Snapshot",
                "daily_chart_cycle": f"{daily_dates[-1]} (Finalized 24h cycle; ~24-48h lag)" if daily_dates else clean_daily_cycle,
                "trending_feed_state": raw_dm.get("trending_feed_state") or (f"Live Snapshot ({gen_ts})" if has_live_trending else "Evaluated"),
                "dataset_date_coverage": f"Daily: {daily_dates[0]} → {daily_dates[-1]} ({len(daily_dates)} cycles) | Trending: Live" if len(daily_dates) > 1 else (f"Daily: {daily_dates[0]} | Trending: Live" if daily_dates else f"Single Snapshot ({gen_ts})"),
                "all_daily_dates": daily_dates,
                "has_live_trending": has_live_trending
            }

            tracks.append({
                "id": entry,
                "kind": "track",
                "folder": entry,
                "folder_path": folder_path,
                "video_id": vid_id,
                "entity_name": manifest.get("entity_name") or metadata.get("title", entry),
                "generated_at_pst": gen_ts,
                "schema_version": manifest.get("schema_version", "1.2.0"),
                "date_metrics": date_metrics,
                "summary_metrics": manifest.get("summary_metrics", {}),
                "metadata": metadata,
                "telemetry": telemetry,
                "telemetry_history": history,
                "rankings": rankings,
                "share_cards": share_cards,
                "cached_cards_count": cached_count,
                "comments": comments,
                "report_markdown": report_md,
                "files": files_in_dir
            })

    # Sort tracks so most recently generated or highest views appear prominently
    tracks.sort(key=lambda x: x.get("generated_at_pst", ""), reverse=True)
    artists.sort(key=lambda x: x.get("generated_at_pst", ""), reverse=True)

    return {
        "generated_at": datetime.now(zoneinfo.ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "territories_catalog": [
            {"code": c, "name": COUNTRY_NAMES.get(c, c), "flag": get_country_flag(c)}
            for c in ALL_COUNTRY_CODES
        ],
        "key_markets": DEFAULT_KEY_MARKETS,
        "tracks": tracks,
        "artists": artists
    }


def classify_channel_video_type(title: str, duration_sec: int, url: str = "") -> str:
    """Categorizes a channel video into a structured video type for filtering & shortlisting."""
    t_low = (title or "").lower()
    u_low = (url or "").lower()
    dur = int(duration_sec or 0)

    if "/shorts/" in u_low or "#shorts" in t_low or (0 < dur <= 62 and "teaser" not in t_low and "trailer" not in t_low):
        return "Short"
    if any(k in t_low for k in ["behind the scenes", "making of", "making film", "episode", "vlog", "diary", "q&a", "release party", "interview", "reaction", "unboxing", "bts"]):
        return "Behind / Vlog"
    if any(k in t_low for k in ["official music video", "official mv", "official m/v", "m/v)", "[m/v]", "(mv)", "music video)", "music video]"]):
        return "Official MV"
    if any(k in t_low for k in ["lyric video", "lyrics video", "(lyrics)", "official audio", "(audio)", "visualizer", "lyric"]):
        return "Lyric / Audio"
    if any(k in t_low for k in ["dance performance", "performance video", "special stage", "choreography", "dance practice", "live performance", "live at", "live clip", "band live", "vmas", "coachella", "grammy"]):
        return "Performance / Live"
    if any(k in t_low for k in ["teaser", "trailer", "concept film", "highlight medley", "sampler", "intro", "spoiler", "film clip", "track video"]) or (0 < dur < 85):
        return "Teaser / Film"
    if 110 <= dur <= 330:
        return "Music / Track Video"
    return "Channel Video"


def format_duration_mmss(seconds_val) -> str:
    sec = int(seconds_val or 0)
    if sec <= 0:
        return "—"
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def lookup_artist_channel_catalog(query: str, max_items: int = 50) -> dict:
    """
    Resolves an artist name, @handle, channel ID (UC...), or YouTube channel URL,
    fetches up to `max_items` videos from the channel (capped <= 120), categorizes
    each video by type, and cross-references against existing local datasets.
    """
    q_clean = (query or "").strip()
    if not q_clean:
        raise ValueError("Empty artist or channel query.")

    max_items = min(120, max(10, int(max_items or 50)))

    # Build index of existing local datasets by video_id
    existing_datasets = load_all_youtube_datasets()
    added_track_map = {}
    for t in existing_datasets.get("tracks", []):
        vid = t.get("video_id")
        if vid:
            added_track_map[vid] = {
                "dossier_id": t.get("id"),
                "entity_name": t.get("entity_name"),
                "generated_at_pst": t.get("generated_at_pst"),
                "countries_charting": len({r.get("country_code") for r in (t.get("rankings") or []) if r.get("country_code")}),
                "placements_count": len(t.get("rankings") or []),
                "best_rank": min([int(r.get("all_time_best_rank") or r.get("rank_position") or 999) for r in (t.get("rankings") or [])], default=None)
            }

    artist_chart_map = {}
    for a in existing_datasets.get("artists", []):
        for r in (a.get("rankings") or []):
            vid = r.get("video_id")
            if vid:
                cur = artist_chart_map.setdefault(vid, {"artist_id": a.get("id"), "artist_name": a.get("artist_name"), "placements": 0, "best_rank": 999})
                cur["placements"] += 1
                pos = int(r.get("rank_position") or 999)
                if pos < cur["best_rank"]:
                    cur["best_rank"] = pos

    # Determine if query is a direct URL / @handle / UC... ID or a plain artist search
    target_channel_url = None
    discovered_channels = []

    if q_clean.startswith("http://") or q_clean.startswith("https://"):
        if "watch?v=" in q_clean or "youtu.be/" in q_clean:
            # Resolve channel from video URL first
            vid_id = extract_video_id(q_clean)
            cmd_v = ["yt-dlp", "--dump-single-json", "--skip-download", "--playlist-end", "1", f"https://www.youtube.com/watch?v={vid_id}"]
            res_v = subprocess.run(cmd_v, capture_output=True, text=True, timeout=15)
            if res_v.stdout:
                v_info = json.loads(res_v.stdout)
                cid = v_info.get("channel_id")
                if cid:
                    target_channel_url = f"https://www.youtube.com/channel/{cid}/videos"
        else:
            base_u = q_clean.rstrip("/")
            if not any(base_u.endswith(tab) for tab in ["/videos", "/releases", "/shorts", "/streams"]):
                target_channel_url = base_u + "/videos"
            else:
                target_channel_url = base_u
    elif q_clean.startswith("@"):
        target_channel_url = f"https://www.youtube.com/{q_clean}/videos"
    elif q_clean.startswith("UC") and len(q_clean) >= 20 and " " not in q_clean:
        target_channel_url = f"https://www.youtube.com/channel/{q_clean}/videos"

    search_fallback_entries = []
    channel_info = {
        "query": q_clean,
        "channel_name": q_clean,
        "channel_id": "",
        "channel_handle": "",
        "channel_url": "",
        "related_channels": []
    }

    # If plain text artist name (or if @handle needs resolution), run a fast ytsearch8 first to discover official channels
    if not target_channel_url:
        search_cmd = [
            "yt-dlp", "--flat-playlist", "--dump-single-json", "--playlist-end", "10",
            f"ytsearch10:{q_clean} official music video"
        ]
        res_s = subprocess.run(search_cmd, capture_output=True, text=True, timeout=18)
        if res_s.stdout and res_s.stdout.strip() != "null":
            try:
                s_data = json.loads(res_s.stdout)
                s_entries = s_data.get("entries") or []
                search_fallback_entries = s_entries
                channel_counts = {}
                for e in s_entries:
                    cid = e.get("channel_id")
                    cname = e.get("channel") or e.get("uploader") or ""
                    curl = e.get("channel_url") or (f"https://www.youtube.com/channel/{cid}" if cid else "")
                    if cid:
                        info = channel_counts.setdefault(cid, {"channel_id": cid, "channel_name": cname, "channel_url": curl, "hits": 0, "views": 0})
                        info["hits"] += 1
                        info["views"] += int(e.get("view_count") or 0)
                ranked_channels = sorted(channel_counts.values(), key=lambda x: (x["hits"], x["views"]), reverse=True)
                discovered_channels = ranked_channels[:4]
                if ranked_channels:
                    best_ch = ranked_channels[0]
                    target_channel_url = f"https://www.youtube.com/channel/{best_ch['channel_id']}/videos"
                    channel_info["channel_name"] = best_ch["channel_name"]
                    channel_info["channel_id"] = best_ch["channel_id"]
                    channel_info["channel_url"] = best_ch["channel_url"]
                    channel_info["related_channels"] = discovered_channels
            except Exception:
                pass

    raw_entries = []
    if target_channel_url:
        tab_cmd = [
            "yt-dlp", "--flat-playlist", "--dump-single-json",
            "--playlist-end", str(max_items),
            target_channel_url
        ]
        res_t = subprocess.run(tab_cmd, capture_output=True, text=True, timeout=22)
        if res_t.stdout and res_t.stdout.strip() != "null":
            try:
                t_data = json.loads(res_t.stdout)
                channel_info["channel_name"] = t_data.get("channel") or t_data.get("uploader") or t_data.get("title") or channel_info["channel_name"]
                channel_info["channel_id"] = t_data.get("channel_id") or channel_info["channel_id"]
                channel_info["channel_handle"] = t_data.get("uploader_id") or ""
                channel_info["channel_url"] = t_data.get("channel_url") or (f"https://www.youtube.com/channel/{channel_info['channel_id']}" if channel_info["channel_id"] else target_channel_url.replace("/videos", ""))
                raw_entries = t_data.get("entries") or []
            except Exception:
                pass

    # If direct @handle failed (e.g. handle differed from artist name), fall back to ytsearch discovery
    if not raw_entries and not search_fallback_entries:
        search_cmd = [
            "yt-dlp", "--flat-playlist", "--dump-single-json", "--playlist-end", str(min(30, max_items)),
            f"ytsearch{min(30, max_items)}:{q_clean.lstrip('@')} official video"
        ]
        res_s2 = subprocess.run(search_cmd, capture_output=True, text=True, timeout=18)
        if res_s2.stdout and res_s2.stdout.strip() != "null":
            try:
                s2_data = json.loads(res_s2.stdout)
                s2_entries = s2_data.get("entries") or []
                if s2_entries and s2_entries[0].get("channel_id"):
                    cid = s2_entries[0]["channel_id"]
                    channel_info["channel_id"] = cid
                    channel_info["channel_name"] = s2_entries[0].get("channel") or q_clean
                    channel_info["channel_url"] = f"https://www.youtube.com/channel/{cid}"
                    tab_cmd2 = ["yt-dlp", "--flat-playlist", "--dump-single-json", "--playlist-end", str(max_items), f"https://www.youtube.com/channel/{cid}/videos"]
                    res_t2 = subprocess.run(tab_cmd2, capture_output=True, text=True, timeout=20)
                    if res_t2.stdout and res_t2.stdout.strip() != "null":
                        t2_data = json.loads(res_t2.stdout)
                        channel_info["channel_name"] = t2_data.get("channel") or channel_info["channel_name"]
                        channel_info["channel_handle"] = t2_data.get("uploader_id") or ""
                        raw_entries = t2_data.get("entries") or []
                if not raw_entries:
                    raw_entries = s2_entries
            except Exception:
                pass
    elif not raw_entries and search_fallback_entries:
        raw_entries = search_fallback_entries

    seen_ids = set()
    videos = []
    type_counts = {}

    for idx, item in enumerate(raw_entries, start=1):
        vid = item.get("id")
        if not vid or len(vid) != 11 or vid in seen_ids:
            continue
        seen_ids.add(vid)
        title = item.get("title") or f"Video {vid}"
        dur = int(item.get("duration") or 0)
        views = int(item.get("view_count") or 0)
        url = item.get("url") or f"https://www.youtube.com/watch?v={vid}"
        vtype = classify_channel_video_type(title, dur, url)
        type_counts[vtype] = type_counts.get(vtype, 0) + 1

        thumbs = item.get("thumbnails") or []
        thumb_url = thumbs[-1].get("url") if thumbs else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"

        added_info = added_track_map.get(vid)
        artist_chart_info = artist_chart_map.get(vid)

        videos.append({
            "index": len(videos) + 1,
            "video_id": vid,
            "title": title,
            "channel_name": item.get("channel") or channel_info["channel_name"],
            "channel_id": item.get("channel_id") or channel_info["channel_id"],
            "view_count": views,
            "duration_seconds": dur,
            "duration_formatted": item.get("duration_string") or format_duration_mmss(dur),
            "video_type": vtype,
            "thumbnail_url": thumb_url,
            "webpage_url": f"https://www.youtube.com/watch?v={vid}",
            "already_added": bool(added_info),
            "dossier_id": added_info["dossier_id"] if added_info else None,
            "last_fetched_pst": added_info["generated_at_pst"] if added_info else None,
            "countries_charting": added_info["countries_charting"] if added_info else None,
            "best_rank": added_info["best_rank"] if added_info else (artist_chart_info["best_rank"] if artist_chart_info else None),
            "in_artist_sweep": bool(artist_chart_info),
            "artist_sweep_id": artist_chart_info["artist_id"] if artist_chart_info else None
        })

    already_added_count = sum(1 for v in videos if v["already_added"])
    return {
        "status": "ok",
        "fetched_at_pst": datetime.now(zoneinfo.ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "channel": channel_info,
        "summary": {
            "total_videos_returned": len(videos),
            "already_added_count": already_added_count,
            "not_added_count": len(videos) - already_added_count,
            "type_counts": type_counts
        },
        "videos": videos
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>YT//DOSSIER_ENGINE — Global YouTube Chart & Velocity Telemetry Console</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-canvas: #070708;
      --bg-panel: #0E0E11;
      --bg-elevated: #141418;
      --bg-hover: #1A1A20;
      --bg-active: #202028;
      --border-hairline: #1F1F24;
      --border-strong: #2E2E36;
      --text-primary: #F4F4F6;
      --text-secondary: #A0A0AB;
      --text-muted: #686873;
      --accent-orange: #FF5500;
      --accent-orange-dim: rgba(255, 85, 0, 0.14);
      --accent-emerald: #10B981;
      --accent-emerald-dim: rgba(16, 185, 129, 0.14);
      --accent-amber: #F59E0B;
      --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, monospace;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    html, body {
      height: 100%;
      background-color: var(--bg-canvas);
      color: var(--text-primary);
      font-family: var(--font-sans);
      font-size: 13px;
      line-height: 1.45;
      -webkit-font-smoothing: antialiased;
      overflow: hidden;
    }

    /* Mandatory Tabular Numerals for all metrics & ranks */
    .tabular, td, .kpi-value, .mono-metric, .rank-pill, time {
      font-variant-numeric: tabular-nums;
    }

    .mono {
      font-family: var(--font-mono);
    }

    /* Master 3-Pane High-Density Workspace Layout */
    .app-shell {
      display: grid;
      grid-template-columns: 260px minmax(0, 1fr) 360px;
      grid-template-rows: auto 1fr;
      height: 100dvh;
      width: 100vw;
      overflow: hidden;
      position: relative;
    }

    .app-shell.sidebar-collapsed {
      grid-template-columns: 0px minmax(0, 1fr) 360px;
    }

    .app-shell.inspector-collapsed {
      grid-template-columns: 260px minmax(0, 1fr) 0px;
    }

    .app-shell.sidebar-collapsed.inspector-collapsed {
      grid-template-columns: 0px minmax(0, 1fr) 0px;
    }

    .app-shell.sidebar-collapsed .left-rail {
      border-right: none;
      overflow: hidden;
      visibility: hidden;
    }

    .app-shell.inspector-collapsed .inspector-drawer {
      border-left: none;
      overflow: hidden;
      visibility: hidden;
    }

    /* Mobile Drawer Backdrop */
    .drawer-backdrop {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.72);
      backdrop-filter: blur(4px);
      z-index: 60;
    }

    .drawer-backdrop.open {
      display: block;
    }

    /* Top Command & Execution Bar — Precision Single-Row Desktop / Clean Two-Row Tablet */
    .top-bar {
      grid-column: 1 / -1;
      grid-row: 1;
      background: var(--bg-panel);
      border-bottom: 1px solid var(--border-hairline);
      display: grid;
      grid-template-columns: auto minmax(0, 1fr) auto;
      align-items: center;
      padding: 0 12px;
      gap: 10px;
      z-index: 50;
      min-height: 48px;
    }

    .brand-cluster {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
      white-space: nowrap;
      padding-right: 12px;
      border-right: 1px solid var(--border-hairline);
      height: 30px;
    }

    .sidebar-toggle-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 28px;
      height: 28px;
      background: var(--bg-canvas);
      border: 1px solid var(--border-strong);
      color: var(--text-primary);
      cursor: pointer;
      flex-shrink: 0;
      font-family: var(--font-mono);
      font-size: 13px;
      transition: background 0.12s, border-color 0.12s, color 0.12s;
    }

    .sidebar-toggle-btn:hover {
      background: var(--bg-hover);
      border-color: var(--accent-orange);
      color: var(--accent-orange);
    }

    .brand-mark {
      width: 22px;
      height: 22px;
      background: var(--accent-orange);
      color: #070708;
      font-family: var(--font-mono);
      font-weight: 700;
      font-size: 11px;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }

    .brand-title {
      font-family: var(--font-mono);
      font-weight: 700;
      font-size: 12px;
      letter-spacing: -0.02em;
      color: var(--text-primary);
      white-space: nowrap;
    }

    .brand-version {
      font-family: var(--font-mono);
      font-size: 10px;
      color: var(--text-muted);
      padding: 1px 5px;
      border: 1px solid var(--border-hairline);
      background: var(--bg-canvas);
      flex-shrink: 0;
    }

    /* Live Sweep Execution Form — Single-Row Precision Instrument Strip */
    .execution-bar {
      display: flex;
      flex-wrap: nowrap;
      align-items: center;
      gap: 6px;
      min-width: 0;
      width: 100%;
    }

    .mode-segmented {
      display: inline-flex;
      background: var(--bg-canvas);
      border: 1px solid var(--border-hairline);
      padding: 2px;
      flex-shrink: 0;
      height: 28px;
      align-items: center;
    }

    .mode-btn {
      background: transparent;
      border: 1px solid transparent;
      color: var(--text-secondary);
      font-family: var(--font-mono);
      font-size: 10.5px;
      font-weight: 600;
      padding: 0 8px;
      height: 22px;
      cursor: pointer;
      white-space: nowrap;
      flex-shrink: 0;
      transition: background 0.12s, color 0.12s;
    }

    .mode-btn:hover {
      color: var(--text-primary);
    }

    .mode-btn.active {
      background: var(--bg-elevated);
      color: var(--accent-orange);
      border-color: var(--border-strong);
    }

    .input-target-wrap {
      position: relative;
      flex: 1 1 180px;
      min-width: 130px;
    }

    .input-control, .select-control {
      background: var(--bg-canvas);
      border: 1px solid var(--border-hairline);
      color: var(--text-primary);
      font-family: var(--font-mono);
      font-size: 11px;
      height: 28px;
      padding: 0 8px;
      outline: none;
      transition: border-color 0.12s;
      color-scheme: dark;
    }

    .select-control option {
      background-color: var(--bg-panel);
      color: var(--text-primary);
    }

    .input-control {
      width: 100%;
    }

    .input-control:focus-visible, .select-control:focus-visible {
      border-color: var(--accent-orange);
    }

    .select-control {
      flex-shrink: 0;
      cursor: pointer;
    }

    .checkbox-pill {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      height: 28px;
      padding: 0 8px;
      background: var(--bg-canvas);
      border: 1px solid var(--border-hairline);
      color: var(--text-secondary);
      font-family: var(--font-mono);
      font-size: 10.5px;
      cursor: pointer;
      white-space: nowrap;
      flex-shrink: 0;
      user-select: none;
    }

    .checkbox-pill:hover {
      border-color: var(--border-strong);
      color: var(--text-primary);
    }

    .checkbox-pill input {
      accent-color: var(--accent-orange);
      cursor: pointer;
    }

    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      height: 28px;
      padding: 0 10px;
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 600;
      border: 1px solid var(--border-strong);
      background: var(--bg-elevated);
      color: var(--text-primary);
      cursor: pointer;
      white-space: nowrap;
      flex-shrink: 0;
      transition: background 0.12s, border-color 0.12s, transform 0.08s;
      text-decoration: none;
    }

    .btn:hover:not(:disabled) {
      background: var(--bg-hover);
      border-color: var(--text-secondary);
    }

    .btn:active:not(:disabled) {
      transform: translateY(1px);
    }

    .btn:focus-visible {
      outline: 1px solid var(--accent-orange);
      outline-offset: 1px;
    }

    .btn:disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }

    .btn-primary {
      background: var(--accent-orange);
      border-color: var(--accent-orange);
      color: #070708;
      font-weight: 700;
    }

    .btn-danger {
      background: var(--accent-rose);
      border-color: var(--accent-rose);
      color: #ffffff;
      font-weight: 700;
    }

    .btn-danger:hover:not(:disabled) {
      background: #e11d48;
      border-color: #e11d48;
    }

    /* Live Sweep Progress Monitor Banner */
    .sweep-monitor-bar {
      display: none;
      flex-direction: column;
      background: var(--bg-elevated);
      border-bottom: 1px solid var(--accent-orange);
      position: sticky;
      top: 0;
      z-index: 45;
      font-family: var(--font-mono);
    }

    .sweep-monitor-bar.active {
      display: flex;
    }

    .sweep-monitor-track {
      width: 100%;
      height: 3px;
      background: rgba(255, 255, 255, 0.08);
      overflow: hidden;
    }

    .sweep-monitor-fill {
      height: 100%;
      width: 4%;
      background: var(--accent-orange);
      transition: width 0.22s ease;
    }

    .sweep-monitor-content {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 8px 16px;
      gap: 12px;
      font-size: 11px;
      flex-wrap: wrap;
    }

    .sweep-spinner {
      width: 11px;
      height: 11px;
      border: 2px solid rgba(255, 85, 0, 0.25);
      border-top-color: var(--accent-orange);
      border-radius: 50%;
      animation: spinLoader 0.65s linear infinite;
      flex-shrink: 0;
    }

    @keyframes spinLoader {
      to { transform: rotate(360deg); }
    }

    .btn-primary:hover:not(:disabled) {
      background: #ff6a22;
      border-color: #ff6a22;
    }

    .status-cluster {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-shrink: 0;
      padding-left: 10px;
      border-left: 1px solid var(--border-hairline);
      height: 30px;
    }

    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      height: 28px;
      padding: 0 8px;
      font-family: var(--font-mono);
      font-size: 10.5px;
      border: 1px solid var(--border-hairline);
      background: var(--bg-canvas);
      white-space: nowrap;
      flex-shrink: 0;
    }

    .status-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--accent-emerald);
      flex-shrink: 0;
    }

    .status-dot.offline {
      background: var(--accent-amber);
    }

    /* Left Navigation Rail */
    .left-rail {
      grid-column: 1;
      grid-row: 2;
      background: var(--bg-panel);
      border-right: 1px solid var(--border-hairline);
      display: flex;
      flex-direction: column;
      overflow-y: auto;
      user-select: none;
    }

    .rail-section {
      border-bottom: 1px solid var(--border-hairline);
      padding: 12px 10px;
      flex-shrink: 0;
    }

    .rail-heading {
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-family: var(--font-mono);
      font-size: 10px;
      font-weight: 600;
      color: var(--text-muted);
      letter-spacing: 0.06em;
      padding: 0 6px 8px 6px;
      white-space: nowrap;
    }

    .rail-list {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }

    .rail-item {
      display: flex;
      flex-direction: column;
      gap: 3px;
      padding: 8px 8px;
      border: 1px solid transparent;
      background: transparent;
      color: var(--text-secondary);
      text-align: left;
      cursor: pointer;
      width: 100%;
      transition: background 0.1s, border-color 0.1s;
    }

    .rail-item:hover {
      background: var(--bg-elevated);
      color: var(--text-primary);
    }

    .rail-item.active {
      background: var(--bg-active);
      border-color: var(--border-strong);
      border-left: 2px solid var(--accent-orange);
      color: var(--text-primary);
    }

    .rail-item-title {
      font-size: 12px;
      font-weight: 600;
      color: inherit;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .rail-item-meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-family: var(--font-mono);
      font-size: 10.5px;
      color: var(--text-muted);
      white-space: nowrap;
    }

    .rail-pill {
      padding: 1px 5px;
      background: var(--bg-canvas);
      border: 1px solid var(--border-hairline);
      color: var(--text-secondary);
      font-size: 10px;
    }

    .rail-pill.peak-one {
      color: var(--accent-emerald);
      border-color: rgba(16, 185, 129, 0.35);
      background: var(--accent-emerald-dim);
    }

    /* Main Workspace Canvas */
    .main-canvas {
      grid-column: 2;
      grid-row: 2;
      overflow-y: auto;
      overflow-x: hidden;
      overflow-anchor: none;
      background: var(--bg-canvas);
      display: flex;
      flex-direction: column;
      min-width: 0;
    }

    /* Containment optimization per modern-web-guidance: interactions-in-complex-layouts */
    .containment-region {
      content-visibility: auto;
      contain-intrinsic-size: auto 600px auto 420px;
    }
    @supports not (content-visibility: auto) {
      .containment-region {
        contain: layout style paint;
      }
    }

    /* Entity Identity & 4-Line Date Disambiguation Header */
    .entity-header {
      background: var(--bg-panel);
      border-bottom: 1px solid var(--border-hairline);
      padding: 16px 20px;
      display: flex;
      flex-wrap: wrap;
      align-items: flex-start;
      justify-content: space-between;
      gap: 14px 20px;
      flex-shrink: 0;
    }

    .entity-identity {
      display: flex;
      gap: 14px;
      align-items: flex-start;
      flex: 1 1 360px;
      min-width: 0;
    }

    .entity-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
      flex-wrap: wrap;
    }

    .entity-thumb {
      width: 112px;
      height: 63px;
      object-fit: cover;
      border: 1px solid var(--border-strong);
      background: var(--bg-elevated);
      flex-shrink: 0;
    }

    .entity-title-block {
      display: flex;
      flex-direction: column;
      gap: 6px;
      min-width: 0;
      flex: 1;
    }

    .entity-eyebrow {
      display: flex;
      align-items: center;
      gap: 6px 8px;
      flex-wrap: wrap;
      font-family: var(--font-mono);
      font-size: 11px;
      color: var(--text-secondary);
    }

    .entity-h1 {
      font-size: clamp(16px, 2vw, 20px);
      font-weight: 700;
      letter-spacing: -0.025em;
      color: var(--text-primary);
      line-height: 1.25;
      word-break: break-word;
    }

    /* 4-Line Explicit Date Scope Telemetry Box */
    .date-telemetry-grid {
      width: 100%;
      flex: 1 1 100%;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      border: 1px solid var(--border-hairline);
      background: var(--bg-canvas);
    }

    .date-cell {
      padding: 8px 12px;
      border-right: 1px solid var(--border-hairline);
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
    }

    .date-cell:last-child {
      border-right: none;
    }

    .date-cell-label {
      font-family: var(--font-mono);
      font-size: 10px;
      color: var(--text-muted);
      letter-spacing: 0.04em;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .date-cell-val {
      font-family: var(--font-mono);
      font-size: 11.5px;
      color: var(--text-primary);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    /* 6-Column KPI Strip */
    .kpi-strip {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      border-bottom: 1px solid var(--border-hairline);
      background: var(--bg-panel);
      flex-shrink: 0;
    }

    .kpi-cell {
      padding: 12px 14px;
      border-right: 1px solid var(--border-hairline);
      display: flex;
      flex-direction: column;
      gap: 4px;
      min-width: 0;
    }

    .kpi-cell:last-child {
      border-right: none;
    }

    .kpi-label {
      font-family: var(--font-mono);
      font-size: 10px;
      color: var(--text-muted);
      letter-spacing: 0.05em;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .kpi-value {
      font-family: var(--font-mono);
      font-size: clamp(15px, 1.6vw, 19px);
      font-weight: 700;
      letter-spacing: -0.03em;
      color: var(--text-primary);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .kpi-sub {
      font-family: var(--font-mono);
      font-size: 11px;
      color: var(--text-secondary);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .kpi-sub.accent-emerald {
      color: var(--accent-emerald);
    }

    .kpi-sub.accent-orange {
      color: var(--accent-orange);
    }

    /* State-Aware Sticky Tabs & Pinned Filter Controls (per modern-web-guidance: state-aware-sticky-headers) */
    .sticky-tabs-container {
      position: sticky;
      top: 0;
      /* MANDATORY: Always specify a container name to avoid collisions if CQs are nested */
      container-type: scroll-state;
      container-name: workspace-tabs-header;
      z-index: 25;
      flex-shrink: 0;
    }

    .view-tabs-bar {
      display: flex;
      align-items: stretch;
      justify-content: space-between;
      background: var(--bg-panel);
      border-bottom: 1px solid var(--border-hairline);
      padding: 0;
      gap: 0;
      min-width: 0;
      transition: background-color 0.2s, box-shadow 0.2s, border-color 0.2s;
    }

    @container workspace-tabs-header scroll-state(stuck: top) {
      .view-tabs-bar {
        background: rgba(14, 14, 17, 0.96);
        backdrop-filter: blur(8px);
        border-bottom-color: var(--accent-orange);
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.55);
      }
    }

    .sticky-tabs-container.is-stuck .view-tabs-bar {
      background: rgba(14, 14, 17, 0.96);
      backdrop-filter: blur(8px);
      border-bottom-color: var(--accent-orange);
      box-shadow: 0 8px 20px rgba(0, 0, 0, 0.55);
    }

    /* Scrollable Tabs Strip on Left; Fixed Filter Controls on Right */
    .view-tabs-scroll {
      display: flex;
      align-items: center;
      gap: 2px;
      flex: 1 1 auto;
      min-width: 0;
      overflow-x: auto;
      padding: 0 12px;
      scrollbar-width: thin;
      -webkit-overflow-scrolling: touch;
    }

    .view-tabs-scroll::-webkit-scrollbar {
      height: 3px;
    }

    .view-tabs-scroll::-webkit-scrollbar-thumb {
      background: var(--border-strong);
    }

    .tab-btn {
      background: transparent;
      border: none;
      border-bottom: 2px solid transparent;
      color: var(--text-secondary);
      font-family: var(--font-mono);
      font-size: 11.5px;
      font-weight: 600;
      padding: 11px 12px;
      cursor: pointer;
      white-space: nowrap;
      flex-shrink: 0;
      transition: color 0.12s, border-color 0.12s, background 0.12s;
    }

    .tab-btn:hover {
      color: var(--text-primary);
      background: var(--bg-elevated);
    }

    .tab-btn.active {
      color: var(--accent-orange);
      border-bottom-color: var(--accent-orange);
      background: var(--bg-canvas);
    }

    /* Pinned Filter Bar — Always in view regardless of tab scroll position */
    .table-controls {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 14px;
      flex-shrink: 0;
      background: var(--bg-elevated);
      border-left: 1px solid var(--border-hairline);
      z-index: 2;
    }

    /* Section Containers */
    .workspace-body {
      padding: 18px 20px 40px 20px;
      display: flex;
      flex-direction: column;
      gap: 22px;
    }

    .panel-block {
      border: 1px solid var(--border-hairline);
      background: var(--bg-panel);
      display: flex;
      flex-direction: column;
    }

    .panel-header {
      padding: 11px 14px;
      border-bottom: 1px solid var(--border-hairline);
      background: var(--bg-elevated);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }

    .panel-title-group {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .panel-title {
      font-family: var(--font-mono);
      font-size: 12px;
      font-weight: 700;
      color: var(--text-primary);
      letter-spacing: -0.01em;
      white-space: nowrap;
    }

    .panel-subtitle {
      font-family: var(--font-mono);
      font-size: 11px;
      color: var(--text-secondary);
    }

    /* Champion Countries Banner */
    .champions-strip {
      padding: 10px 14px;
      border-bottom: 1px solid var(--border-hairline);
      background: rgba(16, 185, 129, 0.05);
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }

    .champion-tag {
      font-family: var(--font-mono);
      font-size: 11px;
      padding: 2px 7px;
      background: var(--bg-canvas);
      border: 1px solid rgba(16, 185, 129, 0.35);
      color: var(--accent-emerald);
      white-space: nowrap;
      flex-shrink: 0;
      cursor: pointer;
    }

    .champion-tag:hover {
      background: var(--accent-emerald-dim);
    }

    /* Responsive Data Table (Compliant with modern-web-guidance: responsive-table) */
    .table-wrapper {
      overflow: auto;
      max-inline-size: 100%;
      max-block-size: 560px;
      container-type: inline-size;
      width: 100%;
      -webkit-overflow-scrolling: touch;
    }

    .table-wrapper:focus-visible {
      outline: 1px solid var(--accent-orange);
    }

    table.data-table {
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      text-align: left;
    }

    table.data-table caption {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip: rect(0 0 0 0);
      white-space: nowrap;
    }

    table.data-table thead {
      position: sticky;
      inset-block-start: 0;
      z-index: 2;
      background: var(--bg-canvas);
    }

    table.data-table th {
      font-family: var(--font-mono);
      font-size: 10.5px;
      font-weight: 600;
      color: var(--text-muted);
      padding: 9px 12px;
      border-bottom: 1px solid var(--border-hairline);
      white-space: nowrap;
      background: var(--bg-canvas);
    }

    table.data-table tbody th {
      position: sticky;
      inset-inline-start: 0;
      z-index: 1;
      background: var(--bg-panel);
      color: var(--text-primary);
      font-family: var(--font-sans);
      font-size: 12.5px;
      font-weight: 600;
      border-right: 1px solid var(--border-hairline);
    }

    table.data-table tbody tr {
      cursor: pointer;
      transition: background 0.08s;
    }

    table.data-table tbody tr:hover td,
    table.data-table tbody tr:hover th {
      background: var(--bg-hover);
    }

    table.data-table tbody tr.selected-row td,
    table.data-table tbody tr.selected-row th {
      background: var(--bg-active);
      border-bottom-color: var(--accent-orange);
    }

    table.data-table td {
      padding: 8px 12px;
      border-bottom: 1px solid var(--border-hairline);
      color: var(--text-secondary);
      white-space: nowrap;
      font-size: 12.5px;
    }

    /* Container query stacked table fallback for narrow containers (<600px) */
    @container (width < 600px) {
      table.data-table,
      table.data-table thead,
      table.data-table tbody,
      table.data-table tr,
      table.data-table th,
      table.data-table td {
        display: block;
      }
      table.data-table thead {
        display: none;
      }
      table.data-table tbody tr {
        margin-block-end: 10px;
        border: 1px solid var(--border-hairline);
      }
      table.data-table tbody th {
        position: sticky;
        inset-block-start: 0;
        z-index: 2;
        background: var(--bg-elevated);
      }
      table.data-table td:nth-child(2)::before { content: var(--label-2, "Code") ": "; font-family: var(--font-mono); color: var(--text-muted); }
      table.data-table td:nth-child(3)::before { content: var(--label-3, "Surface") ": "; font-family: var(--font-mono); color: var(--text-muted); }
      table.data-table td:nth-child(4)::before { content: var(--label-4, "Rank") ": "; font-family: var(--font-mono); color: var(--text-muted); }
      table.data-table td:nth-child(5)::before { content: var(--label-5, "Date") ": "; font-family: var(--font-mono); color: var(--text-muted); }
      table.data-table td:nth-child(6)::before { content: var(--label-6, "Peak") ": "; font-family: var(--font-mono); color: var(--text-muted); }
    }

    /* Rank & Status Pills */
    .rank-pill {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 34px;
      padding: 2px 7px;
      font-family: var(--font-mono);
      font-size: 12px;
      font-weight: 700;
      border: 1px solid var(--border-strong);
      background: var(--bg-canvas);
      color: var(--text-primary);
    }

    .rank-pill.rank-1 {
      background: var(--accent-emerald-dim);
      border-color: var(--accent-emerald);
      color: var(--accent-emerald);
    }

    .rank-pill.rank-top5 {
      background: var(--accent-orange-dim);
      border-color: var(--accent-orange);
      color: var(--accent-orange);
    }

    .peak-badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 8px;
      font-family: var(--font-mono);
      font-size: 11px;
      border: 1px solid var(--border-hairline);
      background: var(--bg-canvas);
      color: var(--text-secondary);
      white-space: nowrap;
      flex-shrink: 0;
    }

    .peak-badge.tier-1 {
      color: var(--accent-emerald);
      border-color: rgba(16, 185, 129, 0.4);
    }

    .peak-badge.tier-top5 {
      color: var(--accent-orange);
      border-color: rgba(255, 85, 0, 0.4);
    }

    /* Split Surface Comparison Grid */
    .surface-split-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
    }

    /* 9:16 Share Card Studio Grid */
    .share-card-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
      gap: 14px;
      padding: 16px;
    }

    .share-card-tile {
      border: 1px solid var(--border-hairline);
      background: var(--bg-canvas);
      display: flex;
      flex-direction: column;
      cursor: pointer;
      transition: border-color 0.12s, transform 0.12s;
      position: relative;
    }

    .share-card-tile.selected {
      border-color: var(--accent-orange);
      background: var(--bg-elevated);
    }

    .share-card-tile:hover {
      border-color: var(--accent-orange);
      transform: translateY(-2px);
    }

    .share-card-checkbox-overlay {
      position: absolute;
      top: 8px;
      left: 8px;
      z-index: 4;
      background: rgba(7, 7, 8, 0.85);
      border: 1px solid var(--border-strong);
      padding: 4px 7px;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      font-family: var(--font-mono);
      font-size: 10px;
      color: var(--text-primary);
      cursor: pointer;
    }

    .share-card-cache-badge {
      position: absolute;
      top: 8px;
      right: 8px;
      z-index: 4;
      background: rgba(7, 7, 8, 0.85);
      border: 1px solid var(--border-strong);
      padding: 3px 6px;
      font-family: var(--font-mono);
      font-size: 9.5px;
      color: var(--text-secondary);
    }

    .share-card-cache-badge.cached {
      border-color: rgba(16, 185, 129, 0.55);
      color: var(--accent-emerald);
    }

    /* Compare View Side-by-Side Columns Grid */
    .compare-columns-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(235px, 1fr));
      gap: 12px;
      padding: 14px;
      overflow-x: auto;
    }

    .compare-col-card {
      border: 1px solid var(--border-strong);
      background: var(--bg-canvas);
      display: flex;
      flex-direction: column;
      min-width: 225px;
    }

    .compare-col-header {
      padding: 10px 12px;
      background: var(--bg-elevated);
      border-bottom: 1px solid var(--border-hairline);
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .compare-col-kpi {
      padding: 9px 12px;
      border-bottom: 1px solid var(--border-hairline);
      display: flex;
      flex-direction: column;
      gap: 3px;
    }

    .compare-col-kpi:last-child {
      border-bottom: none;
    }

    /* Artist / Channel Catalog Lookup & Shortlist Builder */
    .lookup-cards-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 12px;
      padding: 14px;
    }

    .lookup-choice-card {
      border: 2px solid var(--border-hairline);
      background: var(--bg-canvas);
      display: flex;
      flex-direction: column;
      cursor: pointer;
      position: relative;
      transition: border-color 0.12s, background 0.12s;
    }

    .lookup-choice-card:hover {
      border-color: var(--border-strong);
      background: var(--bg-hover);
    }

    .lookup-choice-card:has(input[type="checkbox"]:checked) {
      border-color: var(--accent-orange);
      background: var(--bg-elevated);
    }

    .lookup-choice-card:has(input[type="checkbox"]:focus-visible) {
      outline: 2px solid var(--accent-orange);
      outline-offset: 2px;
    }

    .lookup-type-pill {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 3px 9px;
      font-family: var(--font-mono);
      font-size: 10.5px;
      border: 1px solid var(--border-strong);
      background: var(--bg-canvas);
      color: var(--text-secondary);
      cursor: pointer;
      transition: border-color 0.12s, color 0.12s, background 0.12s;
    }

    .lookup-type-pill.active {
      border-color: var(--accent-orange);
      background: var(--accent-orange-dim);
      color: var(--text-primary);
      font-weight: 600;
    }

    .status-pill-added {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 7px;
      font-family: var(--font-mono);
      font-size: 10px;
      font-weight: 700;
      border: 1px solid rgba(16, 185, 129, 0.5);
      background: var(--accent-emerald-dim);
      color: var(--accent-emerald);
      white-space: nowrap;
    }

    .status-pill-new {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 7px;
      font-family: var(--font-mono);
      font-size: 10px;
      border: 1px solid var(--border-strong);
      background: var(--bg-canvas);
      color: var(--text-muted);
      white-space: nowrap;
    }

    .share-card-img-wrap {
      aspect-ratio: 9 / 16;
      width: 100%;
      background: #050506;
      overflow: hidden;
      border-bottom: 1px solid var(--border-hairline);
      position: relative;
    }

    .share-card-img-wrap img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }

    .share-card-meta {
      padding: 10px 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-family: var(--font-mono);
      font-size: 11px;
    }

    /* Right-Hand Split-Pane Inspector Drawer */
    .inspector-drawer {
      grid-column: 3;
      grid-row: 2;
      background: var(--bg-panel);
      border-left: 1px solid var(--border-hairline);
      display: flex;
      flex-direction: column;
      overflow-y: auto;
    }

    .inspector-header {
      padding: 12px 14px;
      border-bottom: 1px solid var(--border-hairline);
      background: var(--bg-elevated);
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-shrink: 0;
    }

    .inspector-body {
      padding: 14px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }

    .inspector-card-frame {
      width: 100%;
      aspect-ratio: 9 / 16;
      max-height: 430px;
      background: #040405;
      border: 1px solid var(--border-strong);
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      position: relative;
    }

    .inspector-card-frame img {
      height: 100%;
      width: auto;
      max-width: 100%;
      object-fit: contain;
    }

    .kv-list {
      border: 1px solid var(--border-hairline);
      background: var(--bg-canvas);
    }

    .kv-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 7px 10px;
      border-bottom: 1px solid var(--border-hairline);
      font-family: var(--font-mono);
      font-size: 11px;
      gap: 8px;
    }

    .kv-row:last-child {
      border-bottom: none;
    }

    .kv-key {
      color: var(--text-muted);
      flex-shrink: 0;
    }

    .kv-val {
      color: var(--text-primary);
      text-align: right;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    /* Command Palette Modal (Cmd+K) */
    .cmd-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.72);
      backdrop-filter: blur(6px);
      display: none;
      align-items: flex-start;
      justify-content: center;
      padding-top: 12vh;
      z-index: 100;
    }

    .cmd-backdrop.open {
      display: flex;
    }

    .cmd-dialog {
      width: 100%;
      max-width: 580px;
      background: var(--bg-panel);
      border: 1px solid var(--border-strong);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    .cmd-input {
      width: 100%;
      height: 44px;
      padding: 0 16px;
      background: var(--bg-canvas);
      border: none;
      border-bottom: 1px solid var(--border-hairline);
      color: var(--text-primary);
      font-family: var(--font-mono);
      font-size: 13px;
      outline: none;
    }

    .cmd-results {
      max-height: 340px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
    }

    .cmd-item {
      padding: 10px 16px;
      border-bottom: 1px solid var(--border-hairline);
      display: flex;
      align-items: center;
      justify-content: space-between;
      cursor: pointer;
      font-family: var(--font-mono);
      font-size: 12px;
      color: var(--text-secondary);
      background: transparent;
      border-left: 2px solid transparent;
      text-align: left;
      width: 100%;
    }

    .cmd-item:hover, .cmd-item:focus-visible {
      background: var(--bg-elevated);
      color: var(--text-primary);
      border-left-color: var(--accent-orange);
      outline: none;
    }

    /* Toast Notification */
    .toast-banner {
      position: fixed;
      bottom: 16px;
      right: 16px;
      background: var(--bg-elevated);
      border: 1px solid var(--accent-orange);
      color: var(--text-primary);
      font-family: var(--font-mono);
      font-size: 11.5px;
      padding: 10px 14px;
      z-index: 90;
      display: none;
      align-items: center;
      gap: 10px;
    }

    .toast-banner.visible {
      display: inline-flex;
    }

    /* Responsive Breakpoints: Tablet & Mobile */
    @media (max-width: 1320px) {
      .app-shell {
        grid-template-columns: 240px minmax(0, 1fr) 0px;
      }
      .app-shell.sidebar-collapsed {
        grid-template-columns: 0px minmax(0, 1fr) 0px;
      }
      /* On <=1320px, Inspector acts as a slide-over drawer when opened */
      .inspector-drawer {
        position: fixed;
        top: 0;
        right: 0;
        bottom: 0;
        width: min(370px, 92vw);
        z-index: 75;
        transform: translateX(100%);
        transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        visibility: visible !important;
        border-left: 1px solid var(--border-strong) !important;
        box-shadow: -12px 0 32px rgba(0, 0, 0, 0.65);
      }
      .app-shell:not(.inspector-collapsed) .inspector-drawer {
        transform: translateX(0);
      }
      .kpi-strip {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
      .kpi-cell:nth-child(3) {
        border-right: none;
      }
      .kpi-cell:nth-child(1),
      .kpi-cell:nth-child(2),
      .kpi-cell:nth-child(3) {
        border-bottom: 1px solid var(--border-hairline);
      }
      .date-telemetry-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .date-cell:nth-child(2) {
        border-right: none;
      }
      .date-cell:nth-child(1),
      .date-cell:nth-child(2) {
        border-bottom: 1px solid var(--border-hairline);
      }
      .surface-split-grid {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 1120px) {
      /* Clean 2-deck grid on narrow laptops/tablets — never wraps mid-sentence */
      .top-bar {
        grid-template-columns: 1fr auto;
        grid-template-rows: 42px auto;
        padding: 6px 12px 8px 12px;
        gap: 6px 12px;
      }
      .brand-cluster {
        grid-column: 1;
        grid-row: 1;
        border-right: none;
      }
      .status-cluster {
        grid-column: 2;
        grid-row: 1;
        border-left: none;
      }
      .execution-bar {
        grid-column: 1 / -1;
        grid-row: 2;
        padding-top: 6px;
        border-top: 1px solid var(--border-hairline);
        flex-wrap: wrap;
      }
    }

    @media (max-width: 900px) {
      /* On mobile/tablet, Left Sidebar also becomes an off-canvas slide-over drawer */
      .app-shell,
      .app-shell.sidebar-collapsed,
      .app-shell.inspector-collapsed,
      .app-shell.sidebar-collapsed.inspector-collapsed {
        grid-template-columns: minmax(0, 1fr);
      }
      .main-canvas {
        grid-column: 1 / -1;
      }
      .left-rail {
        position: fixed;
        top: 0;
        left: 0;
        bottom: 0;
        width: min(290px, 86vw);
        z-index: 75;
        transform: translateX(-100%);
        transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        visibility: visible !important;
        border-right: 1px solid var(--border-strong) !important;
        box-shadow: 12px 0 32px rgba(0, 0, 0, 0.65);
      }
      .app-shell:not(.sidebar-collapsed) .left-rail {
        transform: translateX(0);
      }
      /* Keep filter bar visible below tabs on narrow mobile viewports */
      .view-tabs-bar {
        flex-direction: column;
        align-items: stretch;
      }
      .table-controls {
        border-left: none;
        border-top: 1px solid var(--border-hairline);
        width: 100%;
        justify-content: space-between;
        padding: 8px 12px;
        flex-wrap: wrap;
      }
      .table-controls .input-control {
        flex: 1 1 140px;
        width: auto !important;
      }
      .table-controls .select-control {
        flex: 1 1 auto;
      }
    }

    @media (max-width: 640px) {
      .top-bar {
        padding: 6px 10px 8px 10px;
        gap: 6px;
      }
      .brand-version {
        display: none;
      }
      .status-badge span#server-status-text {
        display: none;
      }
      .status-badge {
        padding: 0 6px;
      }
      .execution-bar {
        gap: 6px;
      }
      .mode-segmented {
        width: 100%;
        display: flex;
      }
      .mode-btn {
        flex: 1;
        text-align: center;
      }
      .input-target-wrap {
        flex: 1 1 100%;
        width: 100%;
      }
      .execution-bar .select-control {
        flex: 1 1 calc(50% - 4px);
        min-width: 120px;
      }
      .checkbox-pill {
        flex: 1 1 auto;
        justify-content: center;
      }
      #execute-btn {
        flex: 1 1 auto;
      }
      .entity-header {
        padding: 14px 12px;
      }
      .entity-identity {
        flex-direction: column;
        gap: 10px;
      }
      .entity-thumb {
        width: 100%;
        max-width: 220px;
        height: auto;
        aspect-ratio: 16 / 9;
      }
      .entity-actions {
        width: 100%;
      }
      .entity-actions .btn {
        flex: 1;
      }
      .date-telemetry-grid {
        grid-template-columns: 1fr;
      }
      .date-cell {
        border-right: none !important;
        border-bottom: 1px solid var(--border-hairline);
      }
      .date-cell:last-child {
        border-bottom: none;
      }
      .kpi-strip {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .kpi-cell {
        padding: 10px 12px;
        border-bottom: 1px solid var(--border-hairline);
      }
      .kpi-cell:nth-child(2n) {
        border-right: none;
      }
      .workspace-body {
        padding: 12px 10px 36px 10px;
        gap: 14px;
      }
    }
  </style>
</head>
<body>
  <div class="drawer-backdrop" id="drawer-backdrop" onclick="closeMobileDrawers()"></div>
  <div class="app-shell" id="app-shell">
    <!-- Top Execution & Command Bar -->
    <header class="top-bar">
      <div class="brand-cluster">
        <button
          type="button"
          class="sidebar-toggle-btn"
          id="sidebar-toggle-btn"
          onclick="toggleSidebar()"
          title="Toggle Left Datasets Sidebar ([)"
          aria-label="Toggle Left Datasets Sidebar"
        >☰</button>
        <div class="brand-mark">YT</div>
        <span class="brand-title">YT//DOSSIER_ENGINE</span>
        <span class="brand-version">v1.2.0</span>
      </div>

      <form class="execution-bar" id="sweep-form" onsubmit="handleExecuteSweep(event)">
        <div class="mode-segmented" role="group" aria-label="Execution Mode">
          <button type="button" class="mode-btn active" id="mode-track-btn" onclick="setExecutionMode('track')" title="Single-Track 5-Layer Dossier">TRACK</button>
          <button type="button" class="mode-btn" id="mode-artist-btn" onclick="setExecutionMode('artist')" title="Artist / Channel Top 100 Sweep">ARTIST</button>
        </div>

        <div class="input-target-wrap">
          <input
            type="text"
            id="sweep-target-input"
            class="input-control"
            placeholder="Video URL / ID (-5ZXrO_lYSA) or @Artist..."
            required
          />
        </div>

        <button
          type="button"
          class="btn"
          id="lookup-channel-btn"
          onclick="triggerTopBarChannelLookup()"
          title="Lookup Artist / Channel Videos to Filter & Shortlist before Processing (L)"
          style="border-color: var(--accent-orange); color: var(--accent-orange);"
        >
          <span>🔎 LOOKUP VIDEOS</span>
        </button>

        <select id="sweep-countries-select" class="select-control" aria-label="Territory Scope" title="Territory Scope">
          <option value="US,GB,TH,KR,JP,BR,FR,DE,AU,CA,ID,PH,MX,GLOBAL">14 Key Markets (~2s)</option>
          <option value="all">All 86 Countries (~11s)</option>
          <option value="US,GB,GLOBAL">US + UK + Global (~1s)</option>
          <option value="TH,ID,PH,SG,MY,TW,HK,KR,JP">APAC Priority (9)</option>
        </select>

        <select id="sweep-date-select" class="select-control" aria-label="Date Scope" title="Date Scope" onchange="handleDateScopeChange()">
          <option value="">Latest + Trending</option>
          <option value="release">Debut / Release Day</option>
          <option value="yesterday">Yesterday Cycle</option>
          <option value="custom">Custom Date...</option>
        </select>

        <input
          type="date"
          id="sweep-custom-date"
          class="input-control"
          style="width: 128px; display: none;"
          min="2023-11-06"
        />

        <label class="checkbox-pill" id="option-toggle-label" title="Skip comments by default for fast 2-4s execution">
          <input type="checkbox" id="sweep-extra-toggle" />
          <span id="option-toggle-text">+Comments</span>
        </label>

        <button type="submit" class="btn btn-primary" id="execute-btn">
          <span id="execute-btn-label">RUN SWEEP</span>
        </button>

        <button
          type="button"
          class="btn btn-danger"
          id="cancel-sweep-btn"
          style="display: none;"
          onclick="cancelActiveSweep()"
          title="Stop / Abort Active YouTube Charts Sweep (Esc)"
        >
          <span>■ STOP</span>
        </button>
      </form>

      <div class="status-cluster">
        <button type="button" class="btn" id="lookup-toggle-btn" onclick="openLookupView()" title="Artist / Channel Video Catalog Lookup & Shortlist Builder (L)">
          <span>🔎 CATALOG LOOKUP</span>
        </button>
        <button type="button" class="btn" id="compare-toggle-btn" onclick="openCompareView()" title="Compare & Sort All Track Dossiers (C)">
          <span>⚖ COMPARE</span>
        </button>
        <button type="button" class="btn" onclick="toggleCommandPalette()" title="Open Command Palette (Cmd+K)">
          <span>CMD+K</span>
        </button>
        <button type="button" class="btn" id="inspector-toggle-btn" onclick="toggleInspector()" title="Toggle Right Inspector Drawer (])">
          <span>INSPECTOR</span>
        </button>
        <div class="status-badge" id="server-status-badge" title="Engine Connection State">
          <span class="status-dot" id="server-status-dot"></span>
          <span id="server-status-text">LIVE ENGINE</span>
        </div>
      </div>
    </header>

    <!-- Left Navigation Rail -->
    <aside class="left-rail" id="left-rail" aria-label="Datasets & Catalogs">
      <div class="rail-section" style="display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; background: var(--bg-elevated);">
        <span class="mono" style="font-size: 11px; font-weight: 700; color: var(--text-primary);">DATASETS & CATALOGS</span>
        <button type="button" class="btn" style="height: 22px; padding: 0 7px;" onclick="toggleSidebar()" title="Collapse Sidebar">«</button>
      </div>
      <div class="rail-section">
        <div class="rail-heading">
          <span>00 // BENCHMARK & COMPARE</span>
          <span id="rail-compare-count">ALL</span>
        </div>
        <div class="rail-list" id="rail-compare-list"></div>
      </div>
      <div class="rail-section">
        <div class="rail-heading">
          <span>01 // TRACK DOSSIERS (5-LAYER)</span>
          <span id="rail-tracks-count">0</span>
        </div>
        <div class="rail-list" id="rail-tracks-list"></div>
      </div>

      <div class="rail-section">
        <div class="rail-heading">
          <span>02 // ARTIST TOP 100 SWEEPS</span>
          <span id="rail-artists-count">0</span>
        </div>
        <div class="rail-list" id="rail-artists-list"></div>
      </div>

      <div class="rail-section" style="margin-top: auto;">
        <div class="rail-heading">
          <span>03 // ENGINE TELEMETRY</span>
          <span>OK</span>
        </div>
        <div class="kv-list">
          <div class="kv-row">
            <span class="kv-key">Protocol</span>
            <span class="kv-val">InnerTube v1</span>
          </div>
          <div class="kv-row">
            <span class="kv-key">Browse ID</span>
            <span class="kv-val">FEmusic_analytics</span>
          </div>
          <div class="kv-row">
            <span class="kv-key">Territories</span>
            <span class="kv-val tabular">86 Sovereign + Global</span>
          </div>
          <div class="kv-row">
            <span class="kv-key">Token Cost</span>
            <span class="kv-val" style="color: var(--accent-emerald);">$0.00 (Zero-Token)</span>
          </div>
        </div>
      </div>
    </aside>

    <!-- Main High-Density Workspace Canvas -->
    <main class="main-canvas" id="main-canvas">
      <!-- Real-Time Sweep Progress & Loader Monitor -->
      <div class="sweep-monitor-bar" id="sweep-monitor-bar" role="status" aria-live="polite">
        <div class="sweep-monitor-track">
          <div class="sweep-monitor-fill" id="sweep-monitor-fill"></div>
        </div>
        <div class="sweep-monitor-content">
          <div style="display: flex; align-items: center; gap: 10px;">
            <span class="sweep-spinner"></span>
            <strong id="sweep-monitor-stage" style="color: var(--accent-orange);">SWEEPING YOUTUBE CHARTS...</strong>
            <span id="sweep-monitor-detail" style="color: var(--text-secondary);">Initializing InnerTube v1 session...</span>
          </div>
          <div style="display: flex; align-items: center; gap: 12px;">
            <span class="tabular" id="sweep-monitor-counter" style="color: var(--text-primary); font-weight: 600;">0 / 0 territories</span>
            <span class="rail-pill peak-one tabular" id="sweep-monitor-hits">0 hits</span>
            <span class="tabular" id="sweep-monitor-elapsed" style="color: var(--text-muted);">0.0s</span>
            <button type="button" class="btn btn-danger" style="height: 22px; padding: 0 8px; font-size: 10px;" onclick="cancelActiveSweep()">■ ABORT SWEEP</button>
          </div>
        </div>
      </div>

      <div id="entity-header-mount"></div>
      <div id="kpi-strip-mount"></div>

      <!-- Sticky Tabs + Always-Visible Pinned Filter Controls -->
      <div class="sticky-tabs-container" id="sticky-tabs-container">
        <div class="view-tabs-bar">
          <div class="view-tabs-scroll" id="view-tabs-container" role="tablist"></div>
          <div class="table-controls" role="search" aria-label="Filter Chart Placements">
            <input
              type="text"
              id="country-filter-input"
              class="input-control"
              style="width: 170px; height: 26px;"
              placeholder="Country or code (US, TH)..."
              oninput="renderActiveTab()"
            />
            <select id="cycle-date-filter" class="select-control" style="height: 26px;" onchange="renderActiveTab()" title="Filter by Chart Date / Week">
              <option value="all">All Dates / Weeks</option>
            </select>
            <select id="rank-tier-filter" class="select-control" style="height: 26px;" onchange="renderActiveTab()" title="Filter by Current or Past #1 Rank Tier">
              <option value="all">All Ranks</option>
              <option value="1">Current #1 Champions</option>
              <option value="ever-1">All Current + Past #1s</option>
              <option value="past-1">Past #1s Only (Prev #1 / Historical)</option>
              <option value="5">Top 5 Tier (<= #5)</option>
              <option value="10">Top 10 Entries (<= #10)</option>
              <option value="20">Top 20 Entries (<= #20)</option>
            </select>
          </div>
        </div>
      </div>

      <div class="workspace-body containment-region" id="workspace-body"></div>
    </main>

    <!-- Right-Hand Split-Pane Share Card & Territory Inspector -->
    <aside class="inspector-drawer" id="inspector-drawer" aria-label="Placement & Share Card Inspector">
      <div class="inspector-header">
        <span class="panel-title">TERRITORY & 9:16 CARD INSPECTOR</span>
        <button type="button" class="btn" style="height: 22px; padding: 0 7px;" onclick="toggleInspector()">×</button>
      </div>
      <div class="inspector-body" id="inspector-body"></div>
    </aside>
  </div>

  <!-- Command Palette (Cmd+K) -->
  <div class="cmd-backdrop" id="cmd-backdrop" onclick="if(event.target === this) toggleCommandPalette()">
    <div class="cmd-dialog" role="dialog" aria-modal="true" aria-label="Command Palette">
      <input
        type="text"
        id="cmd-search-input"
        class="cmd-input"
        placeholder="Type a command, track, artist, or country ISO code..."
        oninput="renderCommandPaletteItems()"
      />
      <div class="cmd-results" id="cmd-results"></div>
    </div>
  </div>

  <!-- Toast Banner -->
  <div class="toast-banner" id="toast-banner" role="status" aria-live="polite"></div>

  <!-- Preloaded Telemetry Payload for Instant Zero-Latency & Offline Execution -->
  <script id="preloaded-telemetry" type="application/json">__PRELOADED_JSON_PAYLOAD__</script>

  <script>
    const STATE = {
      data: { tracks: [], artists: [], territories_catalog: [] },
      activeKind: 'track',      // 'track' | 'artist' | 'compare' | 'lookup'
      activeId: null,
      activeTab: 'overview',    // 'overview' | 'daily' | 'trending' | 'cards' | 'audience' | 'layers'
      executionMode: 'track',   // 'track' | 'artist'
      selectedPlacement: null,
      apiOnline: false,
      sidebarOpen: window.innerWidth > 900,
      inspectorOpen: window.innerWidth > 1320,
      compareSortKey: 'views_per_hour',
      compareSortDir: 'desc',
      compareFilterQuery: '',
      compareSelectedIds: new Set(),
      compareCardLayout: 'columns', // 'columns' | 'rows'
      selectedCardKeys: new Set(),  // Set of card keys selected in 9:16 Share Card Studio
      lookupQuery: '@wearelloud',
      lookupMaxItems: 50,
      lookupLoading: false,
      lookupData: null,
      lookupTypeFilter: 'ALL',
      lookupStatusFilter: 'ALL',    // 'ALL' | 'NOT_ADDED' | 'ADDED'
      lookupSearchFilter: '',
      lookupSortKey: 'index',       // 'index' | 'view_count' | 'duration_seconds' | 'title'
      lookupSortDir: 'asc',
      lookupLayout: 'table',        // 'table' | 'cards'
      lookupSelectedIds: new Set()
    };

    function syncUrlState(replace = false) {
      try {
        const params = new URLSearchParams();
        params.set('view', STATE.activeKind);
        if (STATE.activeKind === 'compare') {
          params.set('layout', STATE.compareCardLayout);
          params.set('sort', STATE.compareSortKey);
          params.set('dir', STATE.compareSortDir);
          if (STATE.compareSelectedIds.size > 0) {
            params.set('pins', Array.from(STATE.compareSelectedIds).join(','));
          }
        } else if (STATE.activeKind === 'lookup') {
          if (STATE.lookupQuery) params.set('q', STATE.lookupQuery);
          if (STATE.lookupTypeFilter && STATE.lookupTypeFilter !== 'ALL') params.set('type', STATE.lookupTypeFilter);
          if (STATE.lookupStatusFilter && STATE.lookupStatusFilter !== 'ALL') params.set('status', STATE.lookupStatusFilter);
        } else {
          if (STATE.activeId) params.set('id', STATE.activeId);
          if (STATE.activeTab && STATE.activeTab !== 'overview') params.set('tab', STATE.activeTab);
        }
        const nextUrl = `${window.location.pathname}?${params.toString()}`;
        const currentUrl = `${window.location.pathname}${window.location.search}`;
        if (nextUrl !== currentUrl) {
          if (replace) {
            window.history.replaceState({ view: STATE.activeKind, id: STATE.activeId, tab: STATE.activeTab }, '', nextUrl);
          } else {
            window.history.pushState({ view: STATE.activeKind, id: STATE.activeId, tab: STATE.activeTab }, '', nextUrl);
          }
        }
      } catch (e) {
        console.warn('URL state sync skipped:', e);
      }
    }

    function applyUrlState() {
      try {
        const params = new URLSearchParams(window.location.search);
        const view = params.get('view');
        const id = params.get('id');
        const tab = params.get('tab');
        const layout = params.get('layout');
        const sort = params.get('sort');
        const dir = params.get('dir');
        const pins = params.get('pins');
        const q = params.get('q');
        const vtype = params.get('type');
        const vstatus = params.get('status');

        if (view === 'lookup') {
          STATE.activeKind = 'lookup';
          if (q) STATE.lookupQuery = q;
          if (vtype) STATE.lookupTypeFilter = vtype;
          if (vstatus) STATE.lookupStatusFilter = vstatus;
          return true;
        }

        if (view === 'compare') {
          STATE.activeKind = 'compare';
          if (layout === 'rows' || layout === 'columns') STATE.compareCardLayout = layout;
          if (sort) STATE.compareSortKey = sort;
          if (dir === 'asc' || dir === 'desc') STATE.compareSortDir = dir;
          if (pins) {
            STATE.compareSelectedIds = new Set(pins.split(',').filter(Boolean));
          }
          return true;
        }

        if (view === 'artist' || (id && STATE.data.artists.some(a => a.id === id))) {
          STATE.activeKind = 'artist';
          const match = STATE.data.artists.find(a => a.id === id) || STATE.data.artists[0];
          if (match) STATE.activeId = match.id;
          STATE.activeTab = tab || 'overview';
          STATE.selectedPlacement = null;
          return true;
        }

        if (view === 'track' || id) {
          STATE.activeKind = 'track';
          const match = STATE.data.tracks.find(t => t.id === id || t.video_id === id) || STATE.data.tracks[0];
          if (match) STATE.activeId = match.id;
          STATE.activeTab = tab || 'overview';
          STATE.selectedPlacement = null;
          return true;
        }
      } catch (e) {
        console.warn('URL parse error:', e);
      }
      return false;
    }

    function syncDrawerLayout() {
      const shell = document.getElementById('app-shell');
      const backdrop = document.getElementById('drawer-backdrop');
      if (!shell) return;

      shell.classList.toggle('sidebar-collapsed', !STATE.sidebarOpen);
      shell.classList.toggle('inspector-collapsed', !STATE.inspectorOpen);

      const isMobileSidebar = window.innerWidth <= 900 && STATE.sidebarOpen;
      const isMobileInspector = window.innerWidth <= 1320 && STATE.inspectorOpen;
      if (backdrop) {
        backdrop.classList.toggle('open', isMobileSidebar || isMobileInspector);
      }

      const sbBtn = document.getElementById('sidebar-toggle-btn');
      if (sbBtn) {
        sbBtn.setAttribute('aria-expanded', String(STATE.sidebarOpen));
        sbBtn.style.borderColor = STATE.sidebarOpen ? 'var(--accent-orange)' : 'var(--border-strong)';
        sbBtn.style.color = STATE.sidebarOpen ? 'var(--accent-orange)' : 'var(--text-primary)';
      }

      const inspBtn = document.getElementById('inspector-toggle-btn');
      if (inspBtn) {
        inspBtn.setAttribute('aria-expanded', String(STATE.inspectorOpen));
        inspBtn.style.borderColor = STATE.inspectorOpen ? 'var(--accent-orange)' : 'var(--border-strong)';
      }
    }

    function toggleSidebar() {
      STATE.sidebarOpen = !STATE.sidebarOpen;
      if (window.innerWidth <= 900 && STATE.sidebarOpen) {
        STATE.inspectorOpen = false;
      }
      syncDrawerLayout();
    }

    function closeMobileDrawers() {
      if (window.innerWidth <= 900) {
        STATE.sidebarOpen = false;
      }
      if (window.innerWidth <= 1320) {
        STATE.inspectorOpen = false;
      }
      syncDrawerLayout();
    }

    function initStickyHeaderObserver() {
      const stickyEl = document.getElementById('sticky-tabs-container');
      const scrollRoot = document.getElementById('main-canvas');
      if (!stickyEl || !scrollRoot || !('IntersectionObserver' in window)) return;
      const observer = new IntersectionObserver(
        ([e]) => {
          stickyEl.classList.toggle('is-stuck', e.intersectionRatio < 1);
        },
        {
          root: scrollRoot,
          threshold: [1],
          rootMargin: '-1px 0px 0px 0px'
        }
      );
      observer.observe(stickyEl);
    }

    function formatNumber(n) {
      if (n === null || n === undefined || n === '') return '—';
      const num = Number(n);
      return Number.isNaN(num) ? String(n) : num.toLocaleString('en-US');
    }

    function escapeHtml(str) {
      return String(str ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    function showToast(msg, durationMs = 3400) {
      const el = document.getElementById('toast-banner');
      el.textContent = msg;
      el.classList.add('visible');
      clearTimeout(window.__toastTimer);
      window.__toastTimer = setTimeout(() => el.classList.remove('visible'), durationMs);
    }

    function getRankPillClass(pos) {
      const p = Number(pos);
      if (p === 1) return 'rank-pill rank-1';
      if (p <= 5) return 'rank-pill rank-top5';
      return 'rank-pill';
    }

    function getPeakBadgeClass(pos) {
      const p = Number(pos);
      if (p === 1) return 'peak-badge tier-1';
      if (p <= 5) return 'peak-badge tier-top5';
      return 'peak-badge';
    }

    async function initApp() {
      // 1. Hydrate from embedded JSON immediately
      try {
        const raw = document.getElementById('preloaded-telemetry').textContent;
        if (raw && !raw.startsWith('__PRELOADED')) {
          STATE.data = JSON.parse(raw);
        }
      } catch (e) {
        console.warn('Preloaded JSON parse warning:', e);
      }

      // 2. Check if live local/remote Python API server is reachable
      try {
        const res = await fetch('/api/datasets', { method: 'GET' });
        if (res.ok) {
          STATE.data = await res.json();
          STATE.apiOnline = true;
          updateServerBadge(true);
        } else {
          updateServerBadge(false);
        }
      } catch (_) {
        updateServerBadge(false);
      }

      if (STATE.data.tracks.length > 0) {
        STATE.activeKind = 'track';
        STATE.activeId = STATE.data.tracks[0].id;
      } else if (STATE.data.artists.length > 0) {
        STATE.activeKind = 'artist';
        STATE.activeId = STATE.data.artists[0].id;
      }

      applyUrlState();
      syncDrawerLayout();
      initStickyHeaderObserver();
      renderAll(false);
      syncUrlState(true);
      if (STATE.activeKind === 'lookup' && STATE.lookupQuery && !STATE.lookupData) {
        executeChannelLookup(STATE.lookupQuery, STATE.lookupMaxItems);
      }

      window.addEventListener('popstate', () => {
        applyUrlState();
        renderAll(false);
      });

      window.addEventListener('resize', () => {
        syncDrawerLayout();
      });

      // Keyboard shortcuts: Cmd+K / Ctrl+K, [ (Left Sidebar), ] (Right Inspector), C (Compare), L (Lookup), Escape
      window.addEventListener('keydown', (e) => {
        const tag = (e.target && e.target.tagName) ? e.target.tagName.toLowerCase() : '';
        const isTyping = tag === 'input' || tag === 'textarea' || tag === 'select';
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
          e.preventDefault();
          toggleCommandPalette();
        } else if (!isTyping && e.key === '[') {
          e.preventDefault();
          toggleSidebar();
        } else if (!isTyping && e.key === ']') {
          e.preventDefault();
          toggleInspector();
        } else if (!isTyping && e.key.toLowerCase() === 'c') {
          e.preventDefault();
          openCompareView();
        } else if (!isTyping && e.key.toLowerCase() === 'l') {
          e.preventDefault();
          openLookupView();
        } else if (e.key === 'Escape') {
          document.getElementById('cmd-backdrop').classList.remove('open');
          closeMobileDrawers();
        }
      });
    }

    function updateServerBadge(online) {
      const dot = document.getElementById('server-status-dot');
      const txt = document.getElementById('server-status-text');
      if (online) {
        dot.classList.remove('offline');
        txt.textContent = 'LIVE ENGINE ONLINE';
      } else {
        dot.classList.add('offline');
        txt.textContent = 'STATIC SNAPSHOT MODE';
      }
    }

    function setExecutionMode(mode) {
      STATE.executionMode = mode;
      document.getElementById('mode-track-btn').classList.toggle('active', mode === 'track');
      document.getElementById('mode-artist-btn').classList.toggle('active', mode === 'artist');
      const input = document.getElementById('sweep-target-input');
      const toggleText = document.getElementById('option-toggle-text');
      if (mode === 'track') {
        input.placeholder = 'Video URL or 11-char ID (e.g. -5ZXrO_lYSA, FyS5dAywkEo)...';
        toggleText.textContent = '+Comments';
      } else {
        input.placeholder = 'Channel Handle (@LISAOfficialVEVO), URL, UC... ID, or Artist Name...';
        toggleText.textContent = '+Auto-Dossiers';
      }
    }

    function handleDateScopeChange() {
      const sel = document.getElementById('sweep-date-select').value;
      const customInput = document.getElementById('sweep-custom-date');
      customInput.style.display = sel === 'custom' ? 'inline-block' : 'none';
    }

    let __sweepAbortController = null;
    let __sweepPollTimer = null;

    function startSweepProgressPolling() {
      const monitor = document.getElementById('sweep-monitor-bar');
      const fill = document.getElementById('sweep-monitor-fill');
      const stage = document.getElementById('sweep-monitor-stage');
      const detail = document.getElementById('sweep-monitor-detail');
      const counter = document.getElementById('sweep-monitor-counter');
      const hits = document.getElementById('sweep-monitor-hits');
      const elapsed = document.getElementById('sweep-monitor-elapsed');
      const label = document.getElementById('execute-btn-label');

      if (monitor) monitor.classList.add('active');
      clearInterval(__sweepPollTimer);
      __sweepPollTimer = setInterval(async () => {
        try {
          const res = await fetch('/api/sweep/status');
          if (!res.ok) return;
          const st = await res.json();
          if (!st.active) return;

          const cur = Number(st.current_idx || 0);
          const tot = Number(st.total_countries || 1);
          const pct = tot > 1 ? Math.min(99, Math.max(5, Math.round((cur / tot) * 100))) : 15;
          if (fill) fill.style.width = `${pct}%`;
          if (stage) stage.textContent = `SWEEPING ${String(st.mode || 'TRACK').toUpperCase()}: ${st.target || ''}`;
          if (detail) detail.textContent = st.message || 'Scanning YouTube InnerTube v1...';
          if (counter) counter.textContent = tot > 1 ? `${cur} / ${tot} territories (${pct}%)` : 'Resolving metadata...';
          if (hits) hits.textContent = `${st.hits_found || 0} chart hits`;
          if (elapsed) elapsed.textContent = `${(st.elapsed_sec || 0).toFixed(1)}s`;
          if (label && tot > 1) label.textContent = `SWEEPING (${cur}/${tot})...`;
        } catch (_) {}
      }, 450);
    }

    function stopSweepProgressPolling() {
      clearInterval(__sweepPollTimer);
      __sweepPollTimer = null;
      const monitor = document.getElementById('sweep-monitor-bar');
      if (monitor) monitor.classList.remove('active');
    }

    async function cancelActiveSweep() {
      showToast('Sending abort signal to active YouTube Charts sweep...', 4000);
      try {
        if (STATE.apiOnline) {
          await fetch('/api/sweep/cancel', { method: 'POST' });
        }
      } catch (_) {}
      if (__sweepAbortController) {
        __sweepAbortController.abort();
      }
      stopSweepProgressPolling();
    }

    async function handleExecuteSweep(event) {
      event.preventDefault();
      if (__sweepAbortController) {
        showToast('A sweep is already in progress. Click [■ STOP] to abort first.');
        return;
      }
      const target = document.getElementById('sweep-target-input').value.trim();
      if (!target) return;

      const countries = document.getElementById('sweep-countries-select').value;
      const dateSel = document.getElementById('sweep-date-select').value;
      const customDate = document.getElementById('sweep-custom-date').value;
      const dateParam = dateSel === 'custom' ? customDate : dateSel;
      const extraToggle = document.getElementById('sweep-extra-toggle').checked;

      if (!STATE.apiOnline) {
        const cliCmd = STATE.executionMode === 'track'
          ? `youtube-dossier "${target}" --countries ${countries}${dateParam ? ' --date ' + dateParam : ''}${extraToggle ? ' --with-comments' : ''}`
          : `youtube-artist-charts "${target}" --countries ${countries}${dateParam ? ' --date ' + dateParam : ''}${extraToggle ? ' --dossier' : ''}`;
        navigator.clipboard?.writeText(cliCmd);
        showToast(`Static mode: Copied CLI command -> ${cliCmd}`);
        return;
      }

      const btn = document.getElementById('execute-btn');
      const cancelBtn = document.getElementById('cancel-sweep-btn');
      const label = document.getElementById('execute-btn-label');
      btn.disabled = true;
      if (cancelBtn) cancelBtn.style.display = 'inline-flex';
      label.textContent = 'SWEEPING...';

      __sweepAbortController = new AbortController();
      startSweepProgressPolling();

      try {
        const endpoint = STATE.executionMode === 'track' ? '/api/sweep/track' : '/api/sweep/artist';
        const res = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: __sweepAbortController.signal,
          body: JSON.stringify({
            target,
            countries,
            date: dateParam || null,
            with_comments: STATE.executionMode === 'track' ? extraToggle : false,
            run_track_dossiers: STATE.executionMode === 'artist' ? extraToggle : false
          })
        });
        const payload = await res.json();
        if (!res.ok) {
          throw new Error(payload.error || 'Sweep execution failed');
        }
        STATE.data = payload.datasets;
        STATE.activeKind = STATE.executionMode;
        STATE.activeId = payload.active_id;
        STATE.activeTab = 'overview';
        STATE.selectedPlacement = null;
        renderAll();
        showToast(`Compiled & merged ${payload.active_id} (${payload.elapsed_sec}s)`);
      } catch (err) {
        if (err.name === 'AbortError' || String(err.message).toLowerCase().includes('cancel')) {
          showToast('Sweep cancelled by user.', 4500);
        } else {
          showToast(`Error: ${err.message}`, 6000);
        }
      } finally {
        __sweepAbortController = null;
        stopSweepProgressPolling();
        btn.disabled = false;
        if (cancelBtn) cancelBtn.style.display = 'none';
        label.textContent = 'RUN SWEEP';
      }
    }

    function computeTrackOverviewStats(t) {
      const tel = t.telemetry || {};
      const meta = t.metadata || {};
      const rankings = t.rankings || [];
      const views = Number(tel.view_count ?? t.summary_metrics?.view_count ?? 0);
      const likes = Number(tel.like_count ?? t.summary_metrics?.like_count ?? 0);
      const comments = Number(tel.comment_count ?? t.summary_metrics?.comment_count ?? 0);
      const vph = Number(tel.views_per_hour ?? 0);
      const lph = Number(tel.likes_per_hour ?? 0);
      const likeRatio = Number(tel.like_to_view_ratio_pct ?? (views ? (likes / views * 100) : 0));
      const hours = Number(tel.hours_since_release ?? 0);
      const tier = tel.virality_tier || (views >= 50000000 ? 'Mega-Viral' : views >= 10000000 ? 'High-Velocity' : 'Viral');
      const uniqueCountries = new Set(rankings.map(r => r.country_code)).size || Number(t.summary_metrics?.number_of_countries_charting || 0);
      const totalPlacements = rankings.length;
      const bestRank = rankings.length > 0 ? Math.min(...rankings.map(r => Number(r.all_time_best_rank || r.rank_position) || 999)) : 999;
      const currOnes = new Set(rankings.filter(r => Number(r.rank_position) === 1).map(r => r.country_code)).size;
      const everOnes = new Set(rankings.filter(r => Number(r.rank_position) === 1 || Number(r.previous_position) === 1 || r.reached_number_one).map(r => r.country_code)).size;
      const pastOnlyOnes = Math.max(0, everOnes - currOnes);
      const topComment = (t.comments || [])[0] || null;
      const topCommentLikes = topComment ? Number(topComment.likes_count || 0) : 0;

      return {
        id: t.id,
        video_id: t.video_id,
        title: t.entity_name || meta.title || t.id,
        channel_name: meta.channel_name || 'Official',
        upload_date: meta.upload_date || '—',
        last_fetched: t.generated_at_pst || tel.snapshot_timestamp || '—',
        thumbnail_url: meta.thumbnail_url || `https://i.ytimg.com/vi/${t.video_id}/maxresdefault.jpg`,
        views,
        views_per_hour: vph,
        likes,
        likes_per_hour: lph,
        like_ratio: Number(likeRatio.toFixed(2)),
        comments,
        unique_countries: uniqueCountries,
        total_placements: totalPlacements,
        best_rank: bestRank,
        curr_ones: currOnes,
        ever_ones: everOnes,
        past_only_ones: pastOnlyOnes,
        hours_since_release: hours,
        virality_tier: tier,
        top_comment_likes: topCommentLikes,
        top_comment_author: topComment ? topComment.author_handle : '',
        raw: t
      };
    }

    function openLookupView(initialQuery = '') {
      STATE.activeKind = 'lookup';
      if (initialQuery && initialQuery.trim()) {
        STATE.lookupQuery = initialQuery.trim();
      }
      if (window.innerWidth <= 900) {
        STATE.sidebarOpen = false;
        syncDrawerLayout();
      }
      renderAll(true);
      if (STATE.lookupQuery && (!STATE.lookupData || STATE.lookupData.channel?.query !== STATE.lookupQuery)) {
        executeChannelLookup(STATE.lookupQuery, STATE.lookupMaxItems);
      }
    }

    function triggerTopBarChannelLookup() {
      const val = (document.getElementById('sweep-target-input')?.value || '').trim();
      if (val) {
        openLookupView(val);
      } else {
        openLookupView(STATE.lookupQuery || '@wearelloud');
      }
    }

    async function executeChannelLookup(queryOverride = null, maxItemsOverride = null) {
      const q = (queryOverride !== null ? queryOverride : (document.getElementById('lookup-query-input')?.value || STATE.lookupQuery)).trim();
      const maxIt = Number(maxItemsOverride || document.getElementById('lookup-max-select')?.value || STATE.lookupMaxItems || 50);
      if (!q) {
        showToast('Enter an artist name, @handle, channel ID (UC...), or YouTube URL to lookup.');
        return;
      }
      STATE.lookupQuery = q;
      STATE.lookupMaxItems = maxIt;
      STATE.lookupLoading = true;
      syncUrlState(true);
      renderLookupWorkspace();

      if (!STATE.apiOnline) {
        STATE.lookupLoading = false;
        showToast('Start the local Python server to query live YouTube channel catalogs.');
        renderLookupWorkspace();
        return;
      }

      try {
        const res = await fetch('/api/channel/lookup', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: q, max_items: maxIt })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Channel lookup failed');
        STATE.lookupData = data;
        STATE.lookupTypeFilter = 'ALL';
        STATE.lookupSelectedIds.clear();
        showToast(`Loaded ${data.summary?.total_videos_returned || 0} videos from ${data.channel?.channel_name || q} (${data.elapsed_sec}s)`);
      } catch (e) {
        showToast(`Lookup Error: ${e.message}`, 5000);
      } finally {
        STATE.lookupLoading = false;
        renderLookupWorkspace();
      }
    }

    function getFilteredLookupVideos() {
      const videos = STATE.lookupData?.videos || [];
      const q = (STATE.lookupSearchFilter || '').trim().toLowerCase();
      const tf = STATE.lookupTypeFilter || 'ALL';
      const sf = STATE.lookupStatusFilter || 'ALL';

      const filtered = videos.filter(v => {
        if (tf !== 'ALL' && v.video_type !== tf) return false;
        if (sf === 'NOT_ADDED' && v.already_added) return false;
        if (sf === 'ADDED' && !v.already_added) return false;
        if (q) {
          const hit = (v.title || '').toLowerCase().includes(q) ||
                      (v.video_id || '').toLowerCase().includes(q) ||
                      (v.video_type || '').toLowerCase().includes(q) ||
                      (v.channel_name || '').toLowerCase().includes(q);
          if (!hit) return false;
        }
        return true;
      });

      const sk = STATE.lookupSortKey || 'index';
      const dir = STATE.lookupSortDir === 'asc' ? 1 : -1;
      filtered.sort((a, b) => {
        const va = a[sk];
        const vb = b[sk];
        if (typeof va === 'string' && typeof vb === 'string') {
          return va.localeCompare(vb) * dir;
        }
        return ((Number(va) || 0) - (Number(vb) || 0)) * dir;
      });
      return filtered;
    }

    function toggleLookupVideoSelection(videoId) {
      if (STATE.lookupSelectedIds.has(videoId)) {
        STATE.lookupSelectedIds.delete(videoId);
      } else {
        STATE.lookupSelectedIds.add(videoId);
      }
      renderLookupWorkspace();
    }

    function selectLookupPreset(preset) {
      const visible = getFilteredLookupVideos();
      if (preset === 'ALL_VISIBLE') {
        visible.forEach(v => STATE.lookupSelectedIds.add(v.video_id));
      } else if (preset === 'UNADDED_VISIBLE') {
        STATE.lookupSelectedIds.clear();
        visible.filter(v => !v.already_added).forEach(v => STATE.lookupSelectedIds.add(v.video_id));
      } else if (preset === 'OFFICIAL_MVS') {
        STATE.lookupSelectedIds.clear();
        (STATE.lookupData?.videos || [])
          .filter(v => v.video_type === 'Official MV' || v.video_type === 'Music / Track Video')
          .forEach(v => STATE.lookupSelectedIds.add(v.video_id));
      } else if (preset === 'UNADDED_MVS') {
        STATE.lookupSelectedIds.clear();
        (STATE.lookupData?.videos || [])
          .filter(v => !v.already_added && (v.video_type === 'Official MV' || v.video_type === 'Music / Track Video'))
          .forEach(v => STATE.lookupSelectedIds.add(v.video_id));
      } else if (preset === 'CLEAR') {
        STATE.lookupSelectedIds.clear();
      }
      renderLookupWorkspace();
    }

    function setLookupSort(key) {
      if (STATE.lookupSortKey === key) {
        STATE.lookupSortDir = STATE.lookupSortDir === 'desc' ? 'asc' : 'desc';
      } else {
        STATE.lookupSortKey = key;
        STATE.lookupSortDir = key === 'view_count' ? 'desc' : 'asc';
      }
      renderLookupWorkspace();
    }

    async function processShortlistedVideos() {
      const selectedIds = Array.from(STATE.lookupSelectedIds);
      if (selectedIds.length === 0) {
        showToast('Select at least 1 video from the catalog to process.');
        return;
      }
      if (!STATE.apiOnline) {
        showToast('Start the local Python server to batch-process shortlisted tracks.');
        return;
      }

      const countries = document.getElementById('lookup-batch-countries')?.value || 'US,GB,TH,KR,JP,BR,FR,DE,AU,CA,ID,PH,MX,GLOBAL';
      const dateSel = document.getElementById('lookup-batch-date')?.value || '';
      const withComments = Boolean(document.getElementById('lookup-batch-comments')?.checked);

      const btn = document.getElementById('process-shortlist-btn');
      if (btn) {
        btn.disabled = true;
        btn.textContent = `PROCESSING ${selectedIds.length} TRACKS...`;
      }

      __sweepAbortController = new AbortController();
      startSweepProgressPolling();
      showToast(`Starting batch 5-Layer Dossier compilation for ${selectedIds.length} shortlisted video(s)...`, 5000);

      try {
        const res = await fetch('/api/sweep/batch-tracks', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: __sweepAbortController.signal,
          body: JSON.stringify({
            video_ids: selectedIds,
            countries,
            date: dateSel || null,
            with_comments: withComments
          })
        });
        const payload = await res.json();
        if (!res.ok) throw new Error(payload.error || 'Batch dossier processing failed');

        STATE.data = payload.datasets;
        // Update already_added flags in current lookupData so badges immediately flip to green
        const addedSet = new Set((STATE.data.tracks || []).map(t => t.video_id));
        const trackByVid = new Map((STATE.data.tracks || []).map(t => [t.video_id, t]));
        if (STATE.lookupData && Array.isArray(STATE.lookupData.videos)) {
          STATE.lookupData.videos.forEach(v => {
            if (addedSet.has(v.video_id)) {
              const td = trackByVid.get(v.video_id);
              v.already_added = true;
              v.dossier_id = td?.id || v.dossier_id;
              v.last_fetched_pst = td?.generated_at_pst || 'Just now';
              v.countries_charting = new Set((td?.rankings || []).map(r => r.country_code)).size;
            }
          });
          STATE.lookupData.summary.already_added_count = STATE.lookupData.videos.filter(v => v.already_added).length;
          STATE.lookupData.summary.not_added_count = STATE.lookupData.videos.length - STATE.lookupData.summary.already_added_count;
        }
        STATE.lookupSelectedIds.clear();
        renderAll(false);
        showToast(`Compiled ${payload.compiled_count} track dossier(s) in ${payload.elapsed_sec}s!`);
      } catch (err) {
        if (err.name === 'AbortError' || String(err.message).toLowerCase().includes('cancel')) {
          showToast('Batch processing cancelled by user.', 4500);
        } else {
          showToast(`Batch Error: ${err.message}`, 6000);
        }
      } finally {
        __sweepAbortController = null;
        stopSweepProgressPolling();
        if (btn) {
          btn.disabled = false;
          btn.textContent = `🚀 PROCESS SELECTED (${STATE.lookupSelectedIds.size})`;
        }
      }
    }

    function renderLookupWorkspace() {
      const headerMount = document.getElementById('entity-header-mount');
      const kpiMount = document.getElementById('kpi-strip-mount');
      const stickyTabs = document.getElementById('sticky-tabs-container');
      const body = document.getElementById('workspace-body');

      if (stickyTabs) stickyTabs.style.display = 'none';

      const d = STATE.lookupData;
      const ch = d?.channel || {};
      const sum = d?.summary || { total_videos_returned: 0, already_added_count: 0, not_added_count: 0, type_counts: {} };
      const allVideos = d?.videos || [];
      const filtered = getFilteredLookupVideos();
      const selectedCount = STATE.lookupSelectedIds.size;
      const selectedAlreadyAdded = Array.from(STATE.lookupSelectedIds).filter(id => allVideos.find(v => v.video_id === id && v.already_added)).length;
      const selectedNewCount = selectedCount - selectedAlreadyAdded;

      const relatedCh = ch.related_channels || [];

      headerMount.innerHTML = `
        <section class="entity-header">
          <div class="entity-identity">
            <div class="entity-title-block">
              <div class="entity-eyebrow">
                <span style="color: var(--accent-orange); font-weight: 700;">00 // ARTIST & CHANNEL VIDEO CATALOG LOOKUP & SHORTLIST BUILDER</span>
                <span>·</span>
                <span>Resolve Official MVs, Lyric Videos, Performances & Shorts before running 5-Layer Dossiers</span>
                ${d?.fetched_at_pst ? `<span>·</span><span style="color:var(--accent-emerald);">Fetched: ${escapeHtml(d.fetched_at_pst)}</span>` : ''}
              </div>
              <h1 class="entity-h1">${ch.channel_name ? `${escapeHtml(ch.channel_name)} — Channel Video Catalog` : 'Artist / Account Video Catalog Lookup'}</h1>
            </div>
          </div>

          <form class="entity-actions" style="width:100%; margin-top:4px; display:flex; gap:8px; flex-wrap:wrap;" onsubmit="event.preventDefault(); executeChannelLookup();">
            <input
              type="text"
              id="lookup-query-input"
              class="input-control"
              style="flex: 1 1 280px; min-width: 240px;"
              placeholder="Enter Artist Name (LISA, ROSÉ, JISOO), @Handle (@wearelloud), Channel ID (UC...), or URL..."
              value="${escapeHtml(STATE.lookupQuery)}"
            />
            <select id="lookup-max-select" class="select-control" title="Max channel videos to inspect">
              <option value="30" ${STATE.lookupMaxItems === 30 ? 'selected' : ''}>Fetch Latest 30 Videos</option>
              <option value="50" ${STATE.lookupMaxItems === 50 ? 'selected' : ''}>Fetch Latest 50 Videos</option>
              <option value="80" ${STATE.lookupMaxItems === 80 ? 'selected' : ''}>Fetch Latest 80 Videos</option>
              <option value="120" ${STATE.lookupMaxItems === 120 ? 'selected' : ''}>Fetch Latest 120 Videos</option>
            </select>
            <button type="submit" class="btn btn-primary" ${STATE.lookupLoading ? 'disabled' : ''}>
              <span>${STATE.lookupLoading ? 'SCANNING CHANNEL...' : '🔎 FETCH CHANNEL VIDEOS'}</span>
            </button>
            ${ch.channel_url ? `<a class="btn" href="${escapeHtml(ch.channel_url)}" target="_blank" rel="noopener">OPEN CHANNEL ↗</a>` : ''}
            ${ch.channel_name ? `<button type="button" class="btn" onclick="prefillResweep('artist', '${escapeHtml(ch.channel_url || ch.channel_name)}')" title="Sweep Top 100 Charts for this entire channel">TOP 100 CHART SWEEP</button>` : ''}
          </form>

          <!-- Quick Preset Artist / Channel Chips + Discovered Related Channels -->
          <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin-top:4px;">
            <span class="mono" style="font-size:10.5px; color:var(--text-muted);">QUICK CHANNELS:</span>
            <button type="button" class="lookup-type-pill" onclick="executeChannelLookup('@wearelloud', STATE.lookupMaxItems)">LLOUD Official (@wearelloud)</button>
            <button type="button" class="lookup-type-pill" onclick="executeChannelLookup('UCg3ymxYCmURj5BFtbgMt-Og', STATE.lookupMaxItems)">LISAOfficialVEVO</button>
            <button type="button" class="lookup-type-pill" onclick="executeChannelLookup('ROSÉ Official', STATE.lookupMaxItems)">ROSÉ</button>
            <button type="button" class="lookup-type-pill" onclick="executeChannelLookup('JENNIE Official', STATE.lookupMaxItems)">JENNIE</button>
            <button type="button" class="lookup-type-pill" onclick="executeChannelLookup('JISOO Official', STATE.lookupMaxItems)">JISOO</button>
            <button type="button" class="lookup-type-pill" onclick="executeChannelLookup('@BLACKPINK', STATE.lookupMaxItems)">BLACKPINK</button>
            <button type="button" class="lookup-type-pill" onclick="executeChannelLookup('@MeganTheeStallion', STATE.lookupMaxItems)">Megan Thee Stallion</button>
            ${relatedCh.length > 1 ? `
              <span class="mono" style="font-size:10.5px; color:var(--accent-orange); margin-left:6px;">RELATED CHANNELS:</span>
              ${relatedCh.map(rc => `
                <button type="button" class="lookup-type-pill ${rc.channel_id === ch.channel_id ? 'active' : ''}" onclick="executeChannelLookup('${escapeHtml(rc.channel_id)}', STATE.lookupMaxItems)">
                  ${escapeHtml(rc.channel_name)} (${rc.hits})
                </button>
              `).join('')}
            ` : ''}
          </div>
        </section>
      `;

      const mvCount = (sum.type_counts?.['Official MV'] || 0) + (sum.type_counts?.['Music / Track Video'] || 0);
      const lyricPerfCount = (sum.type_counts?.['Lyric / Audio'] || 0) + (sum.type_counts?.['Performance / Live'] || 0);

      kpiMount.innerHTML = `
        <section class="kpi-strip" aria-label="Channel Catalog Summary">
          <div class="kpi-cell">
            <span class="kpi-label">CHANNEL VIDEOS FETCHED</span>
            <span class="kpi-value tabular">${sum.total_videos_returned}</span>
            <span class="kpi-sub">${escapeHtml(ch.channel_handle || ch.channel_id || 'Ready to filter')}</span>
          </div>
          <div class="kpi-cell">
            <span class="kpi-label">OFFICIAL MVs & TRACKS</span>
            <span class="kpi-value tabular">${mvCount}</span>
            <span class="kpi-sub accent-orange">Primary chart candidates</span>
          </div>
          <div class="kpi-cell">
            <span class="kpi-label">LYRIC & PERFORMANCE</span>
            <span class="kpi-value tabular">${lyricPerfCount}</span>
            <span class="kpi-sub">Audio / Dance / Live stages</span>
          </div>
          <div class="kpi-cell">
            <span class="kpi-label">ALREADY IN DOSSIERS</span>
            <span class="kpi-value tabular" style="color:var(--accent-emerald);">${sum.already_added_count}</span>
            <span class="kpi-sub accent-emerald">✓ Tracked in workspace</span>
          </div>
          <div class="kpi-cell">
            <span class="kpi-label">NOT YET ADDED (NEW)</span>
            <span class="kpi-value tabular">${sum.not_added_count}</span>
            <span class="kpi-sub">Available to shortlist</span>
          </div>
          <div class="kpi-cell">
            <span class="kpi-label">SHORTLISTED TO PROCESS</span>
            <span class="kpi-value tabular" style="color:${selectedCount > 0 ? 'var(--accent-orange)' : 'var(--text-primary)'};">${selectedCount}</span>
            <span class="kpi-sub">${selectedNewCount} new · ${selectedAlreadyAdded} re-sweep</span>
          </div>
        </section>
      `;

      if (STATE.lookupLoading) {
        body.innerHTML = `
          <section class="panel-block" style="padding:36px; text-align:center;">
            <div style="display:inline-flex; align-items:center; gap:12px; font-family:var(--font-mono); color:var(--accent-orange); font-size:13px;">
              <span class="sweep-spinner"></span>
              <span>Querying YouTube channel catalog for <strong>${escapeHtml(STATE.lookupQuery)}</strong> (up to ${STATE.lookupMaxItems} videos)...</span>
            </div>
          </section>
        `;
        return;
      }

      if (!d || allVideos.length === 0) {
        body.innerHTML = `
          <section class="panel-block" style="padding:32px;">
            <div class="mono" style="color:var(--text-secondary); font-size:12.5px;">
              Enter any artist name, <code>@handle</code>, channel ID (<code>UC...</code>), or YouTube URL above and click <strong>[🔎 FETCH CHANNEL VIDEOS]</strong> to inspect their video catalog, filter by video type (Official MV, Lyric/Audio, Performance, Teaser, Behind/Vlog, Short), see which tracks are already added, and batch-build 5-Layer Track Dossiers.
            </div>
          </section>
        `;
        return;
      }

      const typeKeys = ['ALL', 'Official MV', 'Music / Track Video', 'Lyric / Audio', 'Performance / Live', 'Teaser / Film', 'Behind / Vlog', 'Short', 'Channel Video'];
      const activeTypes = typeKeys.filter(tk => tk === 'ALL' || (sum.type_counts && sum.type_counts[tk] > 0));
      const sortArrow = (k) => STATE.lookupSortKey === k ? (STATE.lookupSortDir === 'desc' ? ' ↓' : ' ↑') : '';
      const thStyle = 'cursor:pointer; user-select:none;';

      const allVisibleSelected = filtered.length > 0 && filtered.every(v => STATE.lookupSelectedIds.has(v.video_id));
      const someVisibleSelected = filtered.some(v => STATE.lookupSelectedIds.has(v.video_id));

      body.innerHTML = `
        <!-- Shortlist & Filter Execution Bar -->
        <section class="panel-block">
          <div class="panel-header" style="flex-wrap:wrap; gap:10px;">
            <div class="panel-title-group" style="flex-wrap:wrap; gap:6px;">
              <span class="panel-title">01 // FILTER BY VIDEO TYPE & ADDED STATUS</span>
              ${activeTypes.map(tk => {
                const cnt = tk === 'ALL' ? allVideos.length : (sum.type_counts[tk] || 0);
                return `
                  <button
                    type="button"
                    class="lookup-type-pill ${STATE.lookupTypeFilter === tk ? 'active' : ''}"
                    onclick="STATE.lookupTypeFilter = '${escapeHtml(tk)}'; syncUrlState(true); renderLookupWorkspace();"
                  >${escapeHtml(tk)} (${cnt})</button>
                `;
              }).join('')}
            </div>

            <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
              <input
                type="text"
                class="input-control"
                style="width:190px; height:26px;"
                placeholder="Filter video title or ID..."
                value="${escapeHtml(STATE.lookupSearchFilter)}"
                oninput="STATE.lookupSearchFilter = this.value; renderLookupWorkspace();"
              />
              <select class="select-control" style="height:26px;" onchange="STATE.lookupStatusFilter = this.value; syncUrlState(true); renderLookupWorkspace();">
                <option value="ALL" ${STATE.lookupStatusFilter === 'ALL' ? 'selected' : ''}>Status: All Videos (${allVideos.length})</option>
                <option value="NOT_ADDED" ${STATE.lookupStatusFilter === 'NOT_ADDED' ? 'selected' : ''}>Status: Not Added Only (${sum.not_added_count})</option>
                <option value="ADDED" ${STATE.lookupStatusFilter === 'ADDED' ? 'selected' : ''}>Status: Already Added (${sum.already_added_count})</option>
              </select>
              <div class="mode-segmented" role="group" aria-label="Catalog View Mode">
                <button type="button" class="mode-btn ${STATE.lookupLayout === 'table' ? 'active' : ''}" onclick="STATE.lookupLayout = 'table'; renderLookupWorkspace();">☰ TABLE</button>
                <button type="button" class="mode-btn ${STATE.lookupLayout === 'cards' ? 'active' : ''}" onclick="STATE.lookupLayout = 'cards'; renderLookupWorkspace();">▥ CARDS</button>
              </div>
            </div>
          </div>

          <!-- Shortlist Action & Batch Processing Bar -->
          <div style="display:flex; align-items:center; justify-content:space-between; padding:10px 14px; background:var(--bg-canvas); border-bottom:1px solid var(--border-hairline); gap:10px; flex-wrap:wrap;">
            <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
              <span class="mono" style="font-size:10.5px; color:var(--text-muted); font-weight:700;">SHORTLIST PRESETS:</span>
              <button type="button" class="btn" style="height:24px; padding:0 8px; font-size:10.5px;" onclick="selectLookupPreset('ALL_VISIBLE')">SELECT ALL VISIBLE (${filtered.length})</button>
              <button type="button" class="btn" style="height:24px; padding:0 8px; font-size:10.5px;" onclick="selectLookupPreset('UNADDED_VISIBLE')">SELECT UNADDED VISIBLE (${filtered.filter(v => !v.already_added).length})</button>
              <button type="button" class="btn" style="height:24px; padding:0 8px; font-size:10.5px;" onclick="selectLookupPreset('UNADDED_MVS')">SHORTLIST NEW OFFICIAL MVs</button>
              <button type="button" class="btn" style="height:24px; padding:0 8px; font-size:10.5px;" onclick="selectLookupPreset('OFFICIAL_MVS')">ALL OFFICIAL MVs (${mvCount})</button>
              <button type="button" class="btn" style="height:24px; padding:0 8px; font-size:10.5px;" onclick="selectLookupPreset('CLEAR')" ${selectedCount === 0 ? 'disabled' : ''}>CLEAR (${selectedCount})</button>
            </div>

            <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
              <select id="lookup-batch-countries" class="select-control" style="height:26px;" title="Territory Scope for Batch Processing">
                <option value="US,GB,TH,KR,JP,BR,FR,DE,AU,CA,ID,PH,MX,GLOBAL">14 Key Markets (~2s/track)</option>
                <option value="all">All 86 Countries (~11s/track)</option>
                <option value="US,GB,GLOBAL">US + UK + Global (~1s/track)</option>
                <option value="TH,ID,PH,SG,MY,TW,HK,KR,JP">APAC Priority (9)</option>
              </select>
              <select id="lookup-batch-date" class="select-control" style="height:26px;" title="Chart Date Scope">
                <option value="">Latest + Trending</option>
                <option value="release">Debut / Release Day</option>
                <option value="yesterday">Yesterday Cycle</option>
              </select>
              <label class="checkbox-pill" style="height:26px;" title="Fetch Top 20 Engaged Community Comments for each selected track">
                <input type="checkbox" id="lookup-batch-comments" checked />
                <span>+Top Comments</span>
              </label>
              <button
                type="button"
                class="btn btn-primary"
                id="process-shortlist-btn"
                style="height:26px; padding:0 12px;"
                onclick="processShortlistedVideos()"
                ${selectedCount === 0 ? 'disabled' : ''}
              >
                <span>🚀 PROCESS SELECTED (${selectedCount})</span>
              </button>
            </div>
          </div>

          ${STATE.lookupLayout === 'table' ? `
            <div tabindex="0" role="region" aria-label="Channel Video Catalog Table" class="table-wrapper">
              <table class="data-table">
                <thead>
                  <tr>
                    <th style="width:42px;">
                      <label style="display:inline-flex; align-items:center; justify-content:center; min-width:24px; min-height:24px; cursor:pointer;" title="Select / Deselect All Visible Videos">
                        <input
                          type="checkbox"
                          id="lookup-master-checkbox"
                          ${allVisibleSelected ? 'checked' : ''}
                          onchange="selectLookupPreset(this.checked ? 'ALL_VISIBLE' : 'CLEAR')"
                          style="accent-color:var(--accent-orange); inline-size:1.15em; aspect-ratio:1; cursor:pointer;"
                        />
                      </label>
                    </th>
                    <th style="${thStyle}" onclick="setLookupSort('index')">#${sortArrow('index')}</th>
                    <th style="${thStyle}" onclick="setLookupSort('title')">VIDEO TITLE${sortArrow('title')}</th>
                    <th>VIDEO TYPE</th>
                    <th>WORKSPACE STATUS</th>
                    <th style="${thStyle}" onclick="setLookupSort('view_count')">CHANNEL VIEWS${sortArrow('view_count')}</th>
                    <th style="${thStyle}" onclick="setLookupSort('duration_seconds')">DURATION${sortArrow('duration_seconds')}</th>
                    <th>VIDEO ID</th>
                    <th>ACTIONS</th>
                  </tr>
                </thead>
                <tbody>
                  ${filtered.map(v => {
                    const isSel = STATE.lookupSelectedIds.has(v.video_id);
                    const typeColor = v.video_type === 'Official MV'
                      ? 'var(--accent-orange)'
                      : (v.video_type === 'Lyric / Audio' || v.video_type === 'Performance / Live' ? 'var(--accent-emerald)' : 'var(--text-secondary)');
                    return `
                      <tr class="${isSel ? 'selected-row' : ''}" onclick="toggleLookupVideoSelection('${escapeHtml(v.video_id)}')">
                        <td onclick="event.stopPropagation();">
                          <label style="display:inline-flex; align-items:center; justify-content:center; min-width:28px; min-height:28px; cursor:pointer;">
                            <input
                              type="checkbox"
                              ${isSel ? 'checked' : ''}
                              onchange="toggleLookupVideoSelection('${escapeHtml(v.video_id)}')"
                              style="accent-color:var(--accent-orange); inline-size:1.15em; aspect-ratio:1; cursor:pointer;"
                            />
                          </label>
                        </td>
                        <td class="mono tabular" style="color:var(--text-muted);">#${v.index}</td>
                        <th scope="row">
                          <div style="display:flex; align-items:center; gap:10px;">
                            <img src="${escapeHtml(v.thumbnail_url)}" alt="" style="width:52px; height:29px; object-fit:cover; border:1px solid var(--border-strong); flex-shrink:0;" loading="lazy" />
                            <div>
                              <div style="color:var(--text-primary); font-weight:600; white-space:normal; line-height:1.3;">${escapeHtml(v.title)}</div>
                              <div class="mono" style="font-size:10px; color:var(--text-muted);">${escapeHtml(v.channel_name)}</div>
                            </div>
                          </div>
                        </th>
                        <td>
                          <span class="peak-badge" style="color:${typeColor}; border-color:${v.video_type === 'Official MV' ? 'rgba(255,85,0,0.45)' : 'var(--border-strong)'};">
                            ${escapeHtml(v.video_type)}
                          </span>
                        </td>
                        <td>
                          ${v.already_added ? `
                            <div style="display:flex; flex-direction:column; gap:2px;">
                              <span class="status-pill-added">✓ ALREADY ADDED${v.countries_charting ? ` · ${v.countries_charting} MKTS` : ''}${v.best_rank && v.best_rank < 999 ? ` · PEAK #${v.best_rank}` : ''}</span>
                              ${v.last_fetched_pst ? `<span class="mono" style="font-size:9.5px; color:var(--text-muted);">Synced: ${escapeHtml(v.last_fetched_pst)}</span>` : ''}
                            </div>
                          ` : (v.in_artist_sweep ? `
                            <span class="status-pill-added" style="border-color:rgba(245,158,11,0.5); color:var(--accent-amber); background:rgba(245,158,11,0.12);">
                              ★ IN ARTIST SWEEP (PEAK #${v.best_rank}) · NO DOSSIER YET
                            </span>
                          ` : `
                            <span class="status-pill-new">○ NOT ADDED</span>
                          `)}
                        </td>
                        <td class="mono tabular" style="font-weight:600; color:var(--text-primary);">${v.view_count ? formatNumber(v.view_count) : '—'}</td>
                        <td class="mono tabular">${escapeHtml(v.duration_formatted)}</td>
                        <td class="mono">
                          <a href="${escapeHtml(v.webpage_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation();" style="color:var(--accent-orange); text-decoration:none;">
                            ${escapeHtml(v.video_id)} ↗
                          </a>
                        </td>
                        <td onclick="event.stopPropagation();">
                          <div style="display:flex; align-items:center; gap:6px;">
                            ${v.already_added && v.dossier_id ? `
                              <button type="button" class="btn" style="height:24px; padding:0 8px; font-size:10px; border-color:var(--accent-emerald); color:var(--accent-emerald);" onclick="selectEntity('track', '${escapeHtml(v.dossier_id)}')">OPEN DOSSIER →</button>
                            ` : `
                              <button type="button" class="btn" style="height:24px; padding:0 8px; font-size:10px;" onclick="STATE.lookupSelectedIds.clear(); STATE.lookupSelectedIds.add('${escapeHtml(v.video_id)}'); processShortlistedVideos();">PROCESS NOW</button>
                            `}
                          </div>
                        </td>
                      </tr>
                    `;
                  }).join('')}
                </tbody>
              </table>
            </div>
          ` : `
            <div class="lookup-cards-grid">
              ${filtered.map(v => {
                const isSel = STATE.lookupSelectedIds.has(v.video_id);
                return `
                  <label class="lookup-choice-card">
                    <div style="display:flex; align-items:center; justify-content:space-between; padding:8px 10px; background:var(--bg-elevated); border-bottom:1px solid var(--border-hairline);">
                      <span style="display:inline-flex; align-items:center; gap:6px; font-family:var(--font-mono); font-size:11px; font-weight:600;">
                        <input
                          type="checkbox"
                          ${isSel ? 'checked' : ''}
                          onchange="toggleLookupVideoSelection('${escapeHtml(v.video_id)}')"
                          style="accent-color:var(--accent-orange); inline-size:1.15em; aspect-ratio:1; cursor:pointer;"
                        />
                        <span>#${v.index} · ${escapeHtml(v.video_type)}</span>
                      </span>
                      ${v.already_added
                        ? `<span class="status-pill-added">✓ ADDED</span>`
                        : `<span class="status-pill-new">NEW</span>`
                      }
                    </div>
                    <img src="${escapeHtml(v.thumbnail_url)}" alt="" style="width:100%; aspect-ratio:16/9; object-fit:cover; border-bottom:1px solid var(--border-hairline);" loading="lazy" />
                    <div style="padding:10px 12px; display:flex; flex-direction:column; gap:6px; flex:1;">
                      <strong style="font-size:12.5px; color:var(--text-primary); line-height:1.35;">${escapeHtml(v.title)}</strong>
                      <div class="mono tabular" style="font-size:11px; color:var(--text-secondary); display:flex; justify-content:space-between;">
                        <span>${v.view_count ? formatNumber(v.view_count) + ' views' : '—'}</span>
                        <span>${escapeHtml(v.duration_formatted)}</span>
                      </div>
                      <div style="display:flex; align-items:center; justify-content:space-between; gap:6px; margin-top:auto; padding-top:6px; border-top:1px solid var(--border-hairline);">
                        <a class="mono" href="${escapeHtml(v.webpage_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation();" style="font-size:10.5px; color:var(--accent-orange); text-decoration:none;">${escapeHtml(v.video_id)} ↗</a>
                        ${v.already_added && v.dossier_id
                          ? `<button type="button" class="btn" style="height:22px; padding:0 7px; font-size:10px; border-color:var(--accent-emerald); color:var(--accent-emerald);" onclick="event.preventDefault(); event.stopPropagation(); selectEntity('track', '${escapeHtml(v.dossier_id)}');">OPEN DOSSIER →</button>`
                          : `<button type="button" class="btn" style="height:22px; padding:0 7px; font-size:10px;" onclick="event.preventDefault(); event.stopPropagation(); STATE.lookupSelectedIds.clear(); STATE.lookupSelectedIds.add('${escapeHtml(v.video_id)}'); processShortlistedVideos();">PROCESS</button>`
                        }
                      </div>
                    </div>
                  </label>
                `;
              }).join('')}
            </div>
          `}
        </section>
      `;

      // Set indeterminate state on master checkbox when partially selected
      const masterCb = document.getElementById('lookup-master-checkbox');
      if (masterCb) {
        masterCb.indeterminate = someVisibleSelected && !allVisibleSelected;
      }
    }

    function openCompareView() {
      STATE.activeKind = 'compare';
      if (window.innerWidth <= 900) {
        STATE.sidebarOpen = false;
        syncDrawerLayout();
      }
      renderAll(true);
    }

    function setCompareCardLayout(layoutMode) {
      STATE.compareCardLayout = layoutMode;
      syncUrlState(true);
      renderCompareWorkspace();
    }

    function setCompareSort(key) {
      if (STATE.compareSortKey === key) {
        STATE.compareSortDir = STATE.compareSortDir === 'desc' ? 'asc' : 'desc';
      } else {
        STATE.compareSortKey = key;
        STATE.compareSortDir = key === 'best_rank' ? 'asc' : 'desc';
      }
      syncUrlState(true);
      renderCompareWorkspace();
    }

    function toggleCompareTrackSelection(trackId) {
      if (STATE.compareSelectedIds.has(trackId)) {
        STATE.compareSelectedIds.delete(trackId);
      } else {
        STATE.compareSelectedIds.add(trackId);
      }
      syncUrlState(true);
      renderCompareWorkspace();
    }

    function renderCompareWorkspace() {
      const headerMount = document.getElementById('entity-header-mount');
      const kpiMount = document.getElementById('kpi-strip-mount');
      const stickyTabs = document.getElementById('sticky-tabs-container');
      const body = document.getElementById('workspace-body');

      if (stickyTabs) stickyTabs.style.display = 'none';

      const allStats = (STATE.data.tracks || []).map(computeTrackOverviewStats);
      const q = (STATE.compareFilterQuery || '').trim().toLowerCase();
      let filtered = allStats.filter(s => {
        if (!q) return true;
        return s.title.toLowerCase().includes(q) ||
               s.channel_name.toLowerCase().includes(q) ||
               s.video_id.toLowerCase().includes(q) ||
               s.virality_tier.toLowerCase().includes(q);
      });

      const sortKey = STATE.compareSortKey || 'views_per_hour';
      const dir = STATE.compareSortDir === 'asc' ? 1 : -1;
      filtered.sort((a, b) => {
        const va = a[sortKey];
        const vb = b[sortKey];
        if (typeof va === 'string' && typeof vb === 'string') {
          return va.localeCompare(vb) * dir;
        }
        return ((Number(va) || 0) - (Number(vb) || 0)) * dir;
      });

      const maxViews = Math.max(1, ...allStats.map(s => s.views));
      const maxVph = Math.max(1, ...allStats.map(s => s.views_per_hour));
      const maxLikes = Math.max(1, ...allStats.map(s => s.likes));
      const maxRatio = Math.max(0.1, ...allStats.map(s => s.like_ratio));
      const maxCountries = Math.max(1, ...allStats.map(s => s.unique_countries));
      const maxEverOnes = Math.max(1, ...allStats.map(s => s.ever_ones));

      const topViewsTrack = [...allStats].sort((a, b) => b.views - a.views)[0];
      const topVelocityTrack = [...allStats].sort((a, b) => b.views_per_hour - a.views_per_hour)[0];
      const topConversionTrack = [...allStats].sort((a, b) => b.like_ratio - a.like_ratio)[0];
      const topMarketsTrack = [...allStats].sort((a, b) => b.unique_countries - a.unique_countries)[0];
      const topOnesTrack = [...allStats].sort((a, b) => b.ever_ones - a.ever_ones)[0];
      const totalCombinedViews = allStats.reduce((acc, s) => acc + s.views, 0);

      headerMount.innerHTML = `
        <section class="entity-header">
          <div class="entity-identity">
            <div class="entity-title-block">
              <div class="entity-eyebrow">
                <span style="color: var(--accent-orange); font-weight: 700;">00 // CROSS-TRACK BENCHMARK & OVERVIEW COMPARISON MATRIX</span>
                <span>·</span>
                <span><strong>${allStats.length} Track Dossiers</strong> Indexed</span>
                <span>·</span>
                <span>Combined Views: <strong class="tabular">${formatNumber(totalCombinedViews)}</strong></span>
              </div>
              <h1 class="entity-h1">Track Dossier Overview Highlights Comparison</h1>
            </div>
          </div>
          <div class="entity-actions">
            <input
              type="text"
              class="input-control"
              style="width: 210px;"
              placeholder="Filter track, artist, or ID..."
              value="${escapeHtml(STATE.compareFilterQuery)}"
              oninput="STATE.compareFilterQuery = this.value; renderCompareWorkspace();"
            />
            <select class="select-control" onchange="STATE.compareSortKey = this.value; STATE.compareSortDir = (this.value === 'best_rank' ? 'asc' : 'desc'); renderCompareWorkspace();">
              <option value="views_per_hour" ${sortKey === 'views_per_hour' ? 'selected' : ''}>Sort: Views / Hr Velocity</option>
              <option value="views" ${sortKey === 'views' ? 'selected' : ''}>Sort: Total Views</option>
              <option value="likes" ${sortKey === 'likes' ? 'selected' : ''}>Sort: Total Likes</option>
              <option value="likes_per_hour" ${sortKey === 'likes_per_hour' ? 'selected' : ''}>Sort: Likes / Hr Velocity</option>
              <option value="like_ratio" ${sortKey === 'like_ratio' ? 'selected' : ''}>Sort: Like Conversion %</option>
              <option value="unique_countries" ${sortKey === 'unique_countries' ? 'selected' : ''}>Sort: Territories Charting</option>
              <option value="ever_ones" ${sortKey === 'ever_ones' ? 'selected' : ''}>Sort: Total #1 Markets (Active + Past)</option>
              <option value="best_rank" ${sortKey === 'best_rank' ? 'selected' : ''}>Sort: Peak Chart Position</option>
              <option value="hours_since_release" ${sortKey === 'hours_since_release' ? 'selected' : ''}>Sort: Hours Since Debut</option>
              <option value="top_comment_likes" ${sortKey === 'top_comment_likes' ? 'selected' : ''}>Sort: Top Comment Likes</option>
            </select>
            <button type="button" class="btn" onclick="STATE.compareSortDir = (STATE.compareSortDir === 'desc' ? 'asc' : 'desc'); renderCompareWorkspace();">
              <span>${STATE.compareSortDir === 'desc' ? '↓ DESC' : '↑ ASC'}</span>
            </button>
          </div>
        </section>
      `;

      kpiMount.innerHTML = `
        <section class="kpi-strip" aria-label="Cross-Track Category Leaders">
          <div class="kpi-cell">
            <span class="kpi-label">HIGHEST TOTAL VIEWS</span>
            <span class="kpi-value tabular">${topViewsTrack ? formatNumber(topViewsTrack.views) : '—'}</span>
            <span class="kpi-sub accent-orange">${escapeHtml(topViewsTrack ? topViewsTrack.title.slice(0, 28) : '—')}</span>
          </div>
          <div class="kpi-cell">
            <span class="kpi-label">FASTEST VELOCITY (VIEWS/HR)</span>
            <span class="kpi-value tabular">${topVelocityTrack ? formatNumber(Math.round(topVelocityTrack.views_per_hour)) + '/hr' : '—'}</span>
            <span class="kpi-sub accent-orange">${escapeHtml(topVelocityTrack ? topVelocityTrack.title.slice(0, 28) : '—')}</span>
          </div>
          <div class="kpi-cell">
            <span class="kpi-label">BEST LIKE CONVERSION %</span>
            <span class="kpi-value tabular">${topConversionTrack ? topConversionTrack.like_ratio + '%' : '—'}</span>
            <span class="kpi-sub">${escapeHtml(topConversionTrack ? topConversionTrack.title.slice(0, 28) : '—')}</span>
          </div>
          <div class="kpi-cell">
            <span class="kpi-label">MOST TERRITORIES CHARTING</span>
            <span class="kpi-value tabular">${topMarketsTrack ? topMarketsTrack.unique_countries + ' / 86' : '—'}</span>
            <span class="kpi-sub">${escapeHtml(topMarketsTrack ? topMarketsTrack.title.slice(0, 28) : '—')}</span>
          </div>
          <div class="kpi-cell">
            <span class="kpi-label">MOST #1 CHAMPION MARKETS</span>
            <span class="kpi-value tabular">${topOnesTrack ? topOnesTrack.ever_ones + ' × #1' : '—'}</span>
            <span class="kpi-sub accent-emerald">${escapeHtml(topOnesTrack ? topOnesTrack.title.slice(0, 28) : '—')}</span>
          </div>
          <div class="kpi-cell">
            <span class="kpi-label">CAPTURED TRACK DOSSIERS</span>
            <span class="kpi-value tabular">${allStats.length}</span>
            <span class="kpi-sub">Click any column header to sort</span>
          </div>
        </section>
      `;

      const sortArrow = (k) => STATE.compareSortKey === k ? (STATE.compareSortDir === 'desc' ? ' ↓' : ' ↑') : '';
      const thStyle = 'cursor:pointer; user-select:none;';

      // Selected tracks for side-by-side Overview Highlights cards (defaults to all filtered tracks)
      const cardTracks = STATE.compareSelectedIds.size > 0
        ? filtered.filter(s => STATE.compareSelectedIds.has(s.id))
        : filtered;

      body.innerHTML = `
        <!-- 1. Sortable Master Overview Highlights Table -->
        <section class="panel-block">
          <div class="panel-header">
            <div class="panel-title-group">
              <span class="panel-title">⚖ SORTABLE TRACK OVERVIEW HIGHLIGHTS LEADERBOARD (${filtered.length} TRACKS)</span>
              <span class="rail-pill">Sorted by: ${escapeHtml(sortKey)} (${escapeHtml(STATE.compareSortDir.toUpperCase())})</span>
            </div>
            <span class="panel-subtitle">Click column headers to sort · Check tracks to isolate in side-by-side KPI cards below · Click row title to open dossier</span>
          </div>
          <div tabindex="0" role="region" aria-label="Track Comparison Leaderboard" class="table-wrapper">
            <table class="data-table">
              <thead>
                <tr>
                  <th style="width:36px;">PIN</th>
                  <th>#</th>
                  <th style="${thStyle}" onclick="setCompareSort('title')">TRACK / CHANNEL${sortArrow('title')}</th>
                  <th style="${thStyle}" onclick="setCompareSort('views')">TOTAL VIEWS${sortArrow('views')}</th>
                  <th style="${thStyle}" onclick="setCompareSort('views_per_hour')">VIEWS / HR${sortArrow('views_per_hour')}</th>
                  <th style="${thStyle}" onclick="setCompareSort('likes')">TOTAL LIKES${sortArrow('likes')}</th>
                  <th style="${thStyle}" onclick="setCompareSort('likes_per_hour')">LIKES / HR${sortArrow('likes_per_hour')}</th>
                  <th style="${thStyle}" onclick="setCompareSort('like_ratio')">LIKE CONV %${sortArrow('like_ratio')}</th>
                  <th style="${thStyle}" onclick="setCompareSort('unique_countries')">TERRITORIES${sortArrow('unique_countries')}</th>
                  <th style="${thStyle}" onclick="setCompareSort('best_rank')">PEAK POS${sortArrow('best_rank')}</th>
                  <th style="${thStyle}" onclick="setCompareSort('ever_ones')">#1 MARKETS${sortArrow('ever_ones')}</th>
                  <th style="${thStyle}" onclick="setCompareSort('hours_since_release')">VIRALITY / AGE${sortArrow('hours_since_release')}</th>
                  <th style="${thStyle}" onclick="setCompareSort('top_comment_likes')">TOP COMMENT${sortArrow('top_comment_likes')}</th>
                  <th>LAST UPDATED</th>
                </tr>
              </thead>
              <tbody>
                ${filtered.map((s, idx) => {
                  const isPinned = STATE.compareSelectedIds.has(s.id);
                  const viewsPct = Math.round((s.views / maxViews) * 100);
                  const vphPct = Math.round((s.views_per_hour / maxVph) * 100);
                  const likesPct = Math.round((s.likes / maxLikes) * 100);
                  const ratioPct = Math.round((s.like_ratio / maxRatio) * 100);
                  const mktPct = Math.round((s.unique_countries / 86) * 100);
                  const onesLabel = s.past_only_ones > 0
                    ? `${s.curr_ones} Act · ${s.past_only_ones} Past`
                    : `${s.ever_ones} × #1`;
                  return `
                    <tr class="${isPinned ? 'selected-row' : ''}">
                      <td onclick="event.stopPropagation();">
                        <input type="checkbox" ${isPinned ? 'checked' : ''} onchange="toggleCompareTrackSelection('${escapeHtml(s.id)}')" style="accent-color:var(--accent-orange); cursor:pointer;" title="Pin track for side-by-side card comparison" />
                      </td>
                      <td class="mono" style="color:var(--text-muted); font-weight:700;">#${idx + 1}</td>
                      <th scope="row" style="cursor:pointer;" onclick="selectEntity('track', '${escapeHtml(s.id)}')">
                        <div style="display:flex; align-items:center; gap:10px;">
                          <img src="${escapeHtml(s.thumbnail_url)}" alt="" style="width:48px; height:27px; object-fit:cover; border:1px solid var(--border-strong); flex-shrink:0;" loading="lazy" />
                          <div>
                            <div style="color:var(--text-primary); font-weight:600;">${escapeHtml(s.title)}</div>
                            <div class="mono" style="font-size:10px; color:var(--text-muted);">${escapeHtml(s.channel_name)} · Uploaded ${escapeHtml(s.upload_date)}</div>
                          </div>
                        </div>
                      </th>
                      <td class="mono tabular">
                        <div style="font-weight:700; color:var(--text-primary);">${formatNumber(s.views)}</div>
                        <div style="width:100%; height:3px; background:rgba(255,255,255,0.06); margin-top:4px;">
                          <div style="width:${viewsPct}%; height:100%; background:var(--text-secondary);"></div>
                        </div>
                      </td>
                      <td class="mono tabular">
                        <div style="font-weight:700; color:var(--accent-orange);">${formatNumber(Math.round(s.views_per_hour))}/hr</div>
                        <div style="width:100%; height:3px; background:rgba(255,255,255,0.06); margin-top:4px;">
                          <div style="width:${vphPct}%; height:100%; background:var(--accent-orange);"></div>
                        </div>
                      </td>
                      <td class="mono tabular">
                        <div style="font-weight:600; color:var(--text-primary);">${formatNumber(s.likes)}</div>
                        <div style="width:100%; height:3px; background:rgba(255,255,255,0.06); margin-top:4px;">
                          <div style="width:${likesPct}%; height:100%; background:var(--text-secondary);"></div>
                        </div>
                      </td>
                      <td class="mono tabular">${formatNumber(Math.round(s.likes_per_hour))}/hr</td>
                      <td class="mono tabular">
                        <div style="font-weight:700; color:var(--text-primary);">${s.like_ratio}%</div>
                        <div style="font-size:10px; color:var(--text-muted);">${formatNumber(s.comments)} comments</div>
                        <div style="width:100%; height:3px; background:rgba(255,255,255,0.06); margin-top:3px;">
                          <div style="width:${ratioPct}%; height:100%; background:var(--accent-emerald);"></div>
                        </div>
                      </td>
                      <td class="mono tabular">
                        <div style="font-weight:700; color:var(--text-primary);">${s.unique_countries} <span style="color:var(--text-muted); font-weight:400;">/ 86</span></div>
                        <div style="font-size:10px; color:var(--text-muted);">${s.total_placements} placements</div>
                        <div style="width:100%; height:3px; background:rgba(255,255,255,0.06); margin-top:3px;">
                          <div style="width:${mktPct}%; height:100%; background:var(--accent-orange);"></div>
                        </div>
                      </td>
                      <td class="mono tabular">
                        ${s.best_rank < 999 ? `<span class="${getRankPillClass(s.best_rank)}">#${s.best_rank}</span>` : '<span style="color:var(--text-muted);">#—</span>'}
                      </td>
                      <td class="mono tabular">
                        <span class="rail-pill ${s.ever_ones > 0 ? 'peak-one' : ''}">${escapeHtml(onesLabel)}</span>
                      </td>
                      <td class="mono tabular">
                        <div style="font-weight:600; color:var(--text-primary);">${escapeHtml(s.virality_tier)}</div>
                        <div style="font-size:10px; color:var(--text-muted);">~${s.hours_since_release}h since debut</div>
                      </td>
                      <td class="mono tabular">
                        ${s.top_comment_likes > 0
                          ? `<div style="color:var(--accent-emerald); font-weight:600;">♥ ${formatNumber(s.top_comment_likes)}</div><div style="font-size:10px; color:var(--text-muted);">${escapeHtml(s.top_comment_author)}</div>`
                          : '<span style="color:var(--text-muted);">—</span>'
                        }
                      </td>
                      <td class="mono tabular" style="font-size:10.5px; color:var(--text-muted);">
                        ${escapeHtml(s.last_fetched)}
                      </td>
                    </tr>
                  `;
                }).join('')}
              </tbody>
            </table>
          </div>
        </section>

        <!-- 2. Selected Tracks Overview Stats Highlights (Side-by-Side Columns vs. Stacked Strips Toggle) -->
        <section class="panel-block">
          <div class="panel-header">
            <div class="panel-title-group">
              <span class="panel-title">📊 SELECTED TRACKS OVERVIEW STATS HIGHLIGHTS (${cardTracks.length} TRACKS)</span>
              ${STATE.compareSelectedIds.size > 0
                ? `<button type="button" class="btn" style="height:22px; padding:0 8px; font-size:10px;" onclick="STATE.compareSelectedIds.clear(); syncUrlState(true); renderCompareWorkspace();">SHOW ALL (${filtered.length})</button>`
                : `<span class="rail-pill">Showing all tracks in current sort order</span>`
              }
            </div>
            <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
              <span class="panel-subtitle">Layout:</span>
              <div class="mode-segmented" role="group" aria-label="Comparison Layout Mode">
                <button
                  type="button"
                  class="mode-btn ${STATE.compareCardLayout === 'columns' ? 'active' : ''}"
                  onclick="setCompareCardLayout('columns')"
                  title="Display tracks side-by-side in vertical columns"
                >▥ SIDE-BY-SIDE COLUMNS</button>
                <button
                  type="button"
                  class="mode-btn ${STATE.compareCardLayout === 'rows' ? 'active' : ''}"
                  onclick="setCompareCardLayout('rows')"
                  title="Display tracks as full-width horizontal KPI strips"
                >☰ STACKED STRIPS</button>
              </div>
            </div>
          </div>

          ${STATE.compareCardLayout === 'columns' ? `
            <div class="compare-columns-grid">
              ${cardTracks.map((s, idx) => {
                const onesLabel = s.past_only_ones > 0
                  ? `${s.curr_ones} Active #1 · ${s.past_only_ones} Past #1`
                  : `${s.ever_ones} × #1 Champion Markets`;
                const viewsPct = Math.round((s.views / maxViews) * 100);
                const vphPct = Math.round((s.views_per_hour / maxVph) * 100);
                const ratioPct = Math.round((s.like_ratio / maxRatio) * 100);
                const mktPct = Math.round((s.unique_countries / 86) * 100);
                return `
                  <div class="compare-col-card">
                    <div class="compare-col-header">
                      <div style="display:flex; align-items:center; justify-content:space-between; gap:6px;">
                        <span class="mono" style="font-size:11px; font-weight:700; color:var(--accent-orange);">#${idx + 1} IN SORT</span>
                        <span class="mono" style="font-size:10px; color:var(--text-muted);">ID: ${escapeHtml(s.video_id)}</span>
                      </div>
                      <img src="${escapeHtml(s.thumbnail_url)}" alt="" style="width:100%; aspect-ratio:16/9; object-fit:cover; border:1px solid var(--border-strong); cursor:pointer;" onclick="selectEntity('track', '${escapeHtml(s.id)}')" loading="lazy" />
                      <strong style="font-size:13px; color:var(--text-primary); line-height:1.3; cursor:pointer;" onclick="selectEntity('track', '${escapeHtml(s.id)}')">${escapeHtml(s.title)}</strong>
                      <div class="mono" style="font-size:10px; color:var(--text-muted);">${escapeHtml(s.channel_name)} · Uploaded ${escapeHtml(s.upload_date)}</div>
                      <div style="display:flex; gap:6px; margin-top:2px;">
                        <button type="button" class="btn" style="flex:1; height:24px; padding:0 6px; font-size:10px;" onclick="selectEntity('track', '${escapeHtml(s.id)}')">OPEN DOSSIER →</button>
                        <button type="button" class="btn" style="height:24px; padding:0 6px; font-size:10px;" onclick="selectEntity('track', '${escapeHtml(s.id)}', 'cards')" title="Open 9:16 Share Card Studio">9:16 CARDS</button>
                      </div>
                    </div>

                    <div class="compare-col-kpi">
                      <span class="kpi-label">01 // TOTAL VIEWS & VELOCITY</span>
                      <span class="kpi-value tabular" style="font-size:17px;">${formatNumber(s.views)}</span>
                      <span class="kpi-sub accent-orange tabular">${formatNumber(Math.round(s.views_per_hour))} views/hr</span>
                      <div style="width:100%; height:3px; background:rgba(255,255,255,0.06); margin-top:3px;">
                        <div style="width:${vphPct}%; height:100%; background:var(--accent-orange);"></div>
                      </div>
                    </div>

                    <div class="compare-col-kpi">
                      <span class="kpi-label">02 // TOTAL LIKES & VELOCITY</span>
                      <span class="kpi-value tabular" style="font-size:17px;">${formatNumber(s.likes)}</span>
                      <span class="kpi-sub tabular">${formatNumber(Math.round(s.likes_per_hour))} likes/hr</span>
                      <div style="width:100%; height:3px; background:rgba(255,255,255,0.06); margin-top:3px;">
                        <div style="width:${viewsPct}%; height:100%; background:var(--text-secondary);"></div>
                      </div>
                    </div>

                    <div class="compare-col-kpi">
                      <span class="kpi-label">03 // LIKE CONVERSION</span>
                      <span class="kpi-value tabular" style="font-size:17px;">${s.like_ratio}%</span>
                      <span class="kpi-sub tabular">${formatNumber(s.comments)} comments</span>
                      <div style="width:100%; height:3px; background:rgba(255,255,255,0.06); margin-top:3px;">
                        <div style="width:${ratioPct}%; height:100%; background:var(--accent-emerald);"></div>
                      </div>
                    </div>

                    <div class="compare-col-kpi">
                      <span class="kpi-label">04 // TERRITORIES CHARTING</span>
                      <span class="kpi-value tabular" style="font-size:17px;">${s.unique_countries} <span style="font-size:12px; color:var(--text-muted);">/ 86</span></span>
                      <span class="kpi-sub tabular">${s.total_placements} total placements</span>
                      <div style="width:100%; height:3px; background:rgba(255,255,255,0.06); margin-top:3px;">
                        <div style="width:${mktPct}%; height:100%; background:var(--accent-orange);"></div>
                      </div>
                    </div>

                    <div class="compare-col-kpi">
                      <span class="kpi-label">05 // PEAK POSITION & #1s</span>
                      <span class="kpi-value tabular" style="font-size:17px;">#${s.best_rank < 999 ? s.best_rank : '—'}</span>
                      <span class="kpi-sub accent-emerald tabular">${escapeHtml(onesLabel)}</span>
                    </div>

                    <div class="compare-col-kpi" title="Mega-Viral: >=50M views OR >=250K views/hr | High-Velocity: >=10M views OR >=50K views/hr | Viral: >=1M views OR >=10K views/hr">
                      <span class="kpi-label">06 // VIRALITY TIER & AGE ⓘ</span>
                      <span class="kpi-value" style="font-size:16px;">${escapeHtml(s.virality_tier)}</span>
                      <span class="kpi-sub tabular">~${s.hours_since_release}h since debut</span>
                    </div>

                    <div class="compare-col-kpi">
                      <span class="kpi-label">07 // TOP ENGAGED COMMENT</span>
                      <span class="kpi-value tabular" style="font-size:14px; color:var(--accent-emerald);">${s.top_comment_likes > 0 ? '♥ ' + formatNumber(s.top_comment_likes) : '—'}</span>
                      <span class="kpi-sub">${escapeHtml(s.top_comment_author || 'Click Comments tab')}</span>
                    </div>
                  </div>
                `;
              }).join('')}
            </div>
          ` : `
            <div style="display:flex; flex-direction:column; gap:14px; padding:14px;">
              ${cardTracks.map((s, idx) => {
                const onesLabel = s.past_only_ones > 0
                  ? `${s.curr_ones} Active #1 · ${s.past_only_ones} Past #1`
                  : `${s.ever_ones} × #1 Champion Markets`;
                return `
                  <div style="border:1px solid var(--border-strong); background:var(--bg-canvas);">
                    <div style="display:flex; align-items:center; justify-content:space-between; padding:8px 14px; background:var(--bg-elevated); border-bottom:1px solid var(--border-hairline); gap:12px; flex-wrap:wrap;">
                      <div style="display:flex; align-items:center; gap:10px;">
                        <span class="mono" style="font-size:11px; font-weight:700; color:var(--accent-orange);">#${idx + 1}</span>
                        <img src="${escapeHtml(s.thumbnail_url)}" alt="" style="width:40px; height:22px; object-fit:cover; border:1px solid var(--border-strong);" loading="lazy" />
                        <strong style="font-size:13px; color:var(--text-primary); cursor:pointer;" onclick="selectEntity('track', '${escapeHtml(s.id)}')">${escapeHtml(s.title)}</strong>
                        <span class="mono" style="font-size:11px; color:var(--text-muted);">· ${escapeHtml(s.channel_name)} · Uploaded: ${escapeHtml(s.upload_date)} · Updated: ${escapeHtml(s.last_fetched)}</span>
                      </div>
                      <div style="display:flex; align-items:center; gap:6px;">
                        <button type="button" class="btn" style="height:24px; padding:0 9px; font-size:10.5px;" onclick="selectEntity('track', '${escapeHtml(s.id)}')">OPEN DOSSIER →</button>
                        <button type="button" class="btn" style="height:24px; padding:0 9px; font-size:10.5px;" onclick="selectEntity('track', '${escapeHtml(s.id)}', 'audience')">COMMENTS (${(s.raw.comments || []).length})</button>
                      </div>
                    </div>
                    <div class="kpi-strip" style="border-bottom:none;">
                      <div class="kpi-cell">
                        <span class="kpi-label">TOTAL VIEWS</span>
                        <span class="kpi-value">${formatNumber(s.views)}</span>
                        <span class="kpi-sub accent-orange">${formatNumber(Math.round(s.views_per_hour))} views/hr</span>
                      </div>
                      <div class="kpi-cell">
                        <span class="kpi-label">TOTAL LIKES</span>
                        <span class="kpi-value">${formatNumber(s.likes)}</span>
                        <span class="kpi-sub">${formatNumber(Math.round(s.likes_per_hour))} likes/hr</span>
                      </div>
                      <div class="kpi-cell">
                        <span class="kpi-label">LIKE CONVERSION</span>
                        <span class="kpi-value">${s.like_ratio}%</span>
                        <span class="kpi-sub">${formatNumber(s.comments)} comments</span>
                      </div>
                      <div class="kpi-cell">
                        <span class="kpi-label">TERRITORIES CHARTING</span>
                        <span class="kpi-value">${s.unique_countries} <span style="font-size:13px; color:var(--text-muted);">/ 86</span></span>
                        <span class="kpi-sub">${s.total_placements} total placements</span>
                      </div>
                      <div class="kpi-cell">
                        <span class="kpi-label">PEAK POSITION</span>
                        <span class="kpi-value">#${s.best_rank < 999 ? s.best_rank : '—'}</span>
                        <span class="kpi-sub accent-emerald">${escapeHtml(onesLabel)}</span>
                      </div>
                      <div class="kpi-cell" title="Mega-Viral: >=50M views OR >=250K views/hr | High-Velocity: >=10M views OR >=50K views/hr | Viral: >=1M views OR >=10K views/hr">
                        <span class="kpi-label">VIRALITY TIER ⓘ</span>
                        <span class="kpi-value">${escapeHtml(s.virality_tier)}</span>
                        <span class="kpi-sub">~${s.hours_since_release}h since debut</span>
                      </div>
                    </div>
                  </div>
                `;
              }).join('')}
            </div>
          `}
        </section>
      `;
    }

    function getActiveEntity() {
      const list = STATE.activeKind === 'track' ? STATE.data.tracks : STATE.data.artists;
      return list.find(item => item.id === STATE.activeId) || list[0] || null;
    }

    function selectEntity(kind, id, tab = 'overview') {
      STATE.activeKind = kind;
      STATE.activeId = id;
      STATE.activeTab = tab;
      STATE.selectedPlacement = null;
      STATE.selectedCardKeys.clear();
      if (window.innerWidth <= 900) {
        STATE.sidebarOpen = false;
        syncDrawerLayout();
      }
      renderAll(true);
    }

    function switchTab(tabId) {
      STATE.activeTab = tabId;
      syncUrlState(false);
      const entity = getActiveEntity();
      if (entity) {
        renderTabsBar(entity);
        renderActiveTab();
      }
    }

    function renderAll(pushHistory = false) {
      if (pushHistory) {
        syncUrlState(false);
      }
      renderLeftRail();
      const cmpBtn = document.getElementById('compare-toggle-btn');
      if (cmpBtn) {
        cmpBtn.style.borderColor = STATE.activeKind === 'compare' ? 'var(--accent-orange)' : 'var(--border-strong)';
        cmpBtn.style.color = STATE.activeKind === 'compare' ? 'var(--accent-orange)' : 'var(--text-primary)';
      }
      const lkpBtn = document.getElementById('lookup-toggle-btn');
      if (lkpBtn) {
        lkpBtn.style.borderColor = STATE.activeKind === 'lookup' ? 'var(--accent-orange)' : 'var(--border-strong)';
        lkpBtn.style.color = STATE.activeKind === 'lookup' ? 'var(--accent-orange)' : 'var(--text-primary)';
      }

      if (STATE.activeKind === 'lookup') {
        renderLookupWorkspace();
        return;
      }

      if (STATE.activeKind === 'compare') {
        renderCompareWorkspace();
        return;
      }

      const stickyTabs = document.getElementById('sticky-tabs-container');
      if (stickyTabs) stickyTabs.style.display = '';

      const entity = getActiveEntity();
      if (!entity) return;

      if (!STATE.selectedPlacement && entity.rankings && entity.rankings.length > 0) {
        STATE.selectedPlacement = entity.rankings[0];
      }

      renderEntityHeader(entity);
      renderKpiStrip(entity);
      renderTabsBar(entity);
      renderActiveTab();
      renderInspector(entity);
    }

    function renderLeftRail() {
      document.getElementById('rail-tracks-count').textContent = STATE.data.tracks.length;
      document.getElementById('rail-artists-count').textContent = STATE.data.artists.length;
      const cmpCountEl = document.getElementById('rail-compare-count');
      if (cmpCountEl) cmpCountEl.textContent = `${STATE.data.tracks.length} tracks`;

      const cmpListEl = document.getElementById('rail-compare-list');
      if (cmpListEl) {
        const isCompareActive = STATE.activeKind === 'compare';
        const isLookupActive = STATE.activeKind === 'lookup';
        cmpListEl.innerHTML = `
          <button type="button" class="rail-item ${isLookupActive ? 'active' : ''}" onclick="openLookupView()">
            <div class="rail-item-title">🔎 Channel Video Lookup & Shortlist</div>
            <div class="rail-item-meta">
              <span class="tabular">Filter MVs · Batch Process</span>
              <span class="rail-pill tabular" style="border-color:var(--accent-orange); color:var(--accent-orange);">LOOKUP</span>
            </div>
          </button>
          <button type="button" class="rail-item ${isCompareActive ? 'active' : ''}" onclick="openCompareView()">
            <div class="rail-item-title">⚖ Compare All Track Dossiers</div>
            <div class="rail-item-meta">
              <span class="tabular">Overview KPI Matrix</span>
              <span class="rail-pill peak-one tabular">${STATE.data.tracks.length} tracks</span>
            </div>
          </button>
        `;
      }

      const tracksHtml = STATE.data.tracks.map(t => {
        const isActive = STATE.activeKind === 'track' && STATE.activeId === t.id;
        const views = t.telemetry?.view_count || t.summary_metrics?.view_count || 0;
        const tRanks = t.rankings || [];
        const countriesCnt = new Set(tRanks.map(r => r.country_code)).size || t.summary_metrics?.number_of_countries_charting || 0;
        const everOnes = new Set(tRanks.filter(r => Number(r.rank_position) === 1 || Number(r.previous_position) === 1 || r.reached_number_one).map(r => r.country_code)).size;
        const lastFetched = t.generated_at_pst || t.telemetry?.snapshot_timestamp || '—';
        return `
          <button type="button" class="rail-item ${isActive ? 'active' : ''}" onclick="selectEntity('track', '${escapeHtml(t.id)}')" title="Last Fetched: ${escapeHtml(lastFetched)}">
            <div class="rail-item-title">${escapeHtml(t.entity_name)}</div>
            <div class="rail-item-meta">
              <span class="tabular">${formatNumber(views)} views</span>
              <span class="rail-pill ${everOnes > 0 ? 'peak-one' : ''} tabular">${countriesCnt} mkts${everOnes > 0 ? ' · ' + everOnes + '×#1' : ''}</span>
            </div>
            <div class="rail-item-meta" style="margin-top:2px; font-size:9.5px; color:var(--text-muted);">
              <span>Updated: ${escapeHtml(lastFetched)}</span>
            </div>
          </button>
        `;
      }).join('');
      document.getElementById('rail-tracks-list').innerHTML = tracksHtml;

      const artistsHtml = STATE.data.artists.map(a => {
        const isActive = STATE.activeKind === 'artist' && STATE.activeId === a.id;
        const trackCnt = a.summary?.unique_tracks_charting || (a.tracks || []).length;
        const placementsCnt = a.summary?.total_placements_captured || (a.rankings || []).length;
        const lastFetched = a.generated_at_pst || '—';
        return `
          <button type="button" class="rail-item ${isActive ? 'active' : ''}" onclick="selectEntity('artist', '${escapeHtml(a.id)}')" title="Last Fetched: ${escapeHtml(lastFetched)}">
            <div class="rail-item-title">${escapeHtml(a.artist_name)}</div>
            <div class="rail-item-meta">
              <span class="tabular">${trackCnt} active tracks</span>
              <span class="rail-pill tabular">${placementsCnt} ranks</span>
            </div>
            <div class="rail-item-meta" style="margin-top:2px; font-size:9.5px; color:var(--text-muted);">
              <span>Updated: ${escapeHtml(lastFetched)}</span>
            </div>
          </button>
        `;
      }).join('');
      document.getElementById('rail-artists-list').innerHTML = artistsHtml;
    }

    function renderEntityHeader(entity) {
      const mount = document.getElementById('entity-header-mount');
      const dm = entity.date_metrics || {};
      const lastFetched = entity.generated_at_pst || entity.telemetry?.snapshot_timestamp || '—';

      if (entity.kind === 'track') {
        const meta = entity.metadata || {};
        const thumb = meta.thumbnail_url || `https://i.ytimg.com/vi/${entity.video_id}/maxresdefault.jpg`;
        const histCount = (entity.telemetry_history || []).length || 1;
        mount.innerHTML = `
          <section class="entity-header">
            <div class="entity-identity">
              <img class="entity-thumb" src="${escapeHtml(thumb)}" alt="" loading="lazy" />
              <div class="entity-title-block">
                <div class="entity-eyebrow">
                  <span style="color: var(--accent-orange); font-weight: 700;">5-LAYER TRACK DOSSIER</span>
                  <span>·</span>
                  <span>ID: <code>${escapeHtml(entity.video_id)}</code></span>
                  <span>·</span>
                  <span>Channel: <strong>${escapeHtml(meta.channel_name || 'Official')}</strong> (${formatNumber(meta.subscribers_count)} subs)</span>
                  <span>·</span>
                  <span>Uploaded: ${escapeHtml(meta.upload_date || '—')}</span>
                  <span>·</span>
                  <span>${escapeHtml(meta.resolution || '1080p')} @ ${escapeHtml(meta.fps || 24)}fps</span>
                  <span>·</span>
                  <span style="color: var(--accent-emerald);">Last Fetched: <strong>${escapeHtml(lastFetched)}</strong> (${histCount} syncs)</span>
                </div>
                <h1 class="entity-h1">${escapeHtml(entity.entity_name)}</h1>
              </div>
            </div>
            <div class="entity-actions">
              <a class="btn" href="https://www.youtube.com/watch?v=${escapeHtml(entity.video_id)}" target="_blank" rel="noopener">OPEN YOUTUBE ↗</a>
              <button type="button" class="btn" onclick="prefillResweep('track', '${escapeHtml(entity.video_id)}')">RE-SWEEP LIVE</button>
            </div>

            <div class="date-telemetry-grid">
              <div class="date-cell">
                <span class="date-cell-label">01 // LAST FETCHED / UPDATED (PST)</span>
                <span class="date-cell-val" style="color: var(--accent-emerald);" title="Last synced at ${escapeHtml(lastFetched)} · Scope: ${escapeHtml(dm.scope_mode)}">${escapeHtml(lastFetched)} · ${escapeHtml(dm.scope_mode || 'Latest Active + Live')}</span>
              </div>
              <div class="date-cell">
                <span class="date-cell-label">02 // DAILY MUSIC CHART CYCLE</span>
                <span class="date-cell-val" title="${escapeHtml(dm.daily_chart_cycle)}">${escapeHtml(dm.daily_chart_cycle || 'Latest 24h Cycle')}</span>
              </div>
              <div class="date-cell">
                <span class="date-cell-label">03 // TRENDING FEED STATE</span>
                <span class="date-cell-val" title="${escapeHtml(dm.trending_feed_state)}">${escapeHtml(dm.trending_feed_state || 'Live Snapshot')}</span>
              </div>
              <div class="date-cell">
                <span class="date-cell-label">04 // DATASET COVERAGE & DEDUP</span>
                <span class="date-cell-val" title="Merges by (country, surface, date) without duplicates">${escapeHtml(dm.dataset_date_coverage || lastFetched)}</span>
              </div>
            </div>
          </section>
        `;
      } else {
        mount.innerHTML = `
          <section class="entity-header">
            <div class="entity-identity">
              <div class="entity-title-block">
                <div class="entity-eyebrow">
                  <span style="color: var(--accent-emerald); font-weight: 700;">ARTIST / CHANNEL TOP 100 SWEEP</span>
                  <span>·</span>
                  <span>Channel: <strong>${escapeHtml(entity.channel_name)}</strong></span>
                  <span>·</span>
                  <span>Channel ID: <code>${escapeHtml(entity.channel_id || 'Multi-Channel')}</code></span>
                  <span>·</span>
                  <span style="color: var(--accent-emerald);">Last Fetched: <strong>${escapeHtml(lastFetched)}</strong></span>
                </div>
                <h1 class="entity-h1">${escapeHtml(entity.artist_name)} — Active Charting Catalog Matrix</h1>
              </div>
            </div>
            <div class="entity-actions">
              ${entity.channel_url ? `<a class="btn" href="${escapeHtml(entity.channel_url)}" target="_blank" rel="noopener">OPEN CHANNEL ↗</a>` : ''}
              <button type="button" class="btn" onclick="prefillResweep('artist', '${escapeHtml(entity.channel_url || entity.artist_name)}')">RE-SWEEP CATALOG</button>
            </div>

            <div class="date-telemetry-grid">
              <div class="date-cell">
                <span class="date-cell-label">01 // LAST FETCHED / UPDATED (PST)</span>
                <span class="date-cell-val" style="color: var(--accent-emerald);">${escapeHtml(lastFetched)}</span>
              </div>
              <div class="date-cell">
                <span class="date-cell-label">02 // DAILY MUSIC CHART CYCLE</span>
                <span class="date-cell-val">${escapeHtml(dm.daily_chart_cycle || 'Latest 24h Cycle')} (~24-48h lag)</span>
              </div>
              <div class="date-cell">
                <span class="date-cell-label">03 // TRENDING FEED STATE</span>
                <span class="date-cell-val">${escapeHtml(dm.trending_feed_state || 'Live Snapshot')}</span>
              </div>
              <div class="date-cell">
                <span class="date-cell-label">04 // TERRITORIES SWEPT</span>
                <span class="date-cell-val">${formatNumber(entity.summary?.territories_queried_count || 0)} Sovereign Markets</span>
              </div>
            </div>
          </section>
        `;
      }
    }

    function renderKpiStrip(entity) {
      const mount = document.getElementById('kpi-strip-mount');
      const rankings = entity.rankings || [];
      const bestRank = rankings.length > 0 ? Math.min(...rankings.map(r => Number(r.all_time_best_rank || r.rank_position) || 999)) : '—';
      const currOnes = new Set(rankings.filter(r => Number(r.rank_position) === 1).map(r => r.country_code)).size;
      const everOnes = new Set(rankings.filter(r => Number(r.rank_position) === 1 || Number(r.previous_position) === 1 || r.reached_number_one).map(r => r.country_code)).size;
      const pastOnlyOnes = Math.max(0, everOnes - currOnes);
      const uniqueCountries = new Set(rankings.map(r => r.country_code)).size;
      const onesLabel = pastOnlyOnes > 0
        ? `${currOnes} Active #1 · ${pastOnlyOnes} Past #1`
        : `${everOnes} × #1 Champion Markets`;

      if (entity.kind === 'track') {
        const tel = entity.telemetry || {};
        const views = tel.view_count ?? entity.summary_metrics?.view_count ?? 0;
        const likes = tel.like_count ?? entity.summary_metrics?.like_count ?? 0;
        const comments = tel.comment_count ?? entity.summary_metrics?.comment_count ?? 0;
        const vph = tel.views_per_hour ?? 0;
        const lph = tel.likes_per_hour ?? 0;
        const ratio = tel.like_to_view_ratio_pct ?? 0;
        const hours = tel.hours_since_release ?? 0;
        const tier = tel.virality_tier || 'Viral';

        mount.innerHTML = `
          <section class="kpi-strip" aria-label="Key Performance Telemetry">
            <div class="kpi-cell">
              <span class="kpi-label">TOTAL VIEWS</span>
              <span class="kpi-value">${formatNumber(views)}</span>
              <span class="kpi-sub accent-orange">${formatNumber(Math.round(vph))} views/hr</span>
            </div>
            <div class="kpi-cell">
              <span class="kpi-label">TOTAL LIKES</span>
              <span class="kpi-value">${formatNumber(likes)}</span>
              <span class="kpi-sub">${formatNumber(Math.round(lph))} likes/hr</span>
            </div>
            <div class="kpi-cell">
              <span class="kpi-label">LIKE CONVERSION</span>
              <span class="kpi-value">${ratio}%</span>
              <span class="kpi-sub">${formatNumber(comments)} comments</span>
            </div>
            <div class="kpi-cell">
              <span class="kpi-label">TERRITORIES CHARTING</span>
              <span class="kpi-value">${uniqueCountries} <span style="font-size:13px; color:var(--text-muted);">/ 86</span></span>
              <span class="kpi-sub">${rankings.length} total placements</span>
            </div>
            <div class="kpi-cell">
              <span class="kpi-label">PEAK POSITION</span>
              <span class="kpi-value">#${bestRank}</span>
              <span class="kpi-sub accent-emerald">${escapeHtml(onesLabel)}</span>
            </div>
            <div class="kpi-cell" title="Mega-Viral: >=50M views OR >=250K views/hr | High-Velocity: >=10M views OR >=50K views/hr | Viral: >=1M views OR >=10K views/hr">
              <span class="kpi-label">VIRALITY TIER ⓘ</span>
              <span class="kpi-value">${escapeHtml(tier)}</span>
              <span class="kpi-sub">~${hours}h since debut</span>
            </div>
          </section>
        `;
      } else {
        const tracks = entity.tracks || [];
        const dailyCnt = rankings.filter(r => r.chart_type === 'Daily Top Music Videos').length;
        const trendCnt = rankings.filter(r => r.chart_type === 'Overall YouTube Trending').length;
        mount.innerHTML = `
          <section class="kpi-strip" aria-label="Artist Catalog Telemetry">
            <div class="kpi-cell">
              <span class="kpi-label">ACTIVE TRACKS CHARTING</span>
              <span class="kpi-value">${tracks.length}</span>
              <span class="kpi-sub accent-orange">Auto-discovered (0 IDs input)</span>
            </div>
            <div class="kpi-cell">
              <span class="kpi-label">TOTAL PLACEMENTS</span>
              <span class="kpi-value">${rankings.length}</span>
              <span class="kpi-sub">Across ${uniqueCountries} countries</span>
            </div>
            <div class="kpi-cell">
              <span class="kpi-label">PEAK CATALOG RANK</span>
              <span class="kpi-value">#${bestRank}</span>
              <span class="kpi-sub accent-emerald">${escapeHtml(onesLabel)}</span>
            </div>
            <div class="kpi-cell">
              <span class="kpi-label">DAILY MUSIC VIDEOS</span>
              <span class="kpi-value">${dailyCnt}</span>
              <span class="kpi-sub">Finalized 24h placements</span>
            </div>
            <div class="kpi-cell">
              <span class="kpi-label">OVERALL TRENDING</span>
              <span class="kpi-value">${trendCnt}</span>
              <span class="kpi-sub">Live real-time placements</span>
            </div>
            <div class="kpi-cell">
              <span class="kpi-label">OFFICIAL 9:16 CARDS</span>
              <span class="kpi-value">${rankings.filter(r => r.share_card_url).length}</span>
              <span class="kpi-sub">1080×1920 vertical assets</span>
            </div>
          </section>
        `;
      }
    }

    function renderTabsBar(entity) {
      const rankings = entity.rankings || [];
      const dailyCnt = rankings.filter(r => r.chart_type === 'Daily Top Music Videos').length;
      const trendCnt = rankings.filter(r => r.chart_type === 'Overall YouTube Trending').length;
      const cardsCnt = rankings.filter(r => r.share_card_url).length;
      const commentsCnt = (entity.comments || []).length;

      // Populate dynamic Chart Date / Week filter dropdown
      const dateSel = document.getElementById('cycle-date-filter');
      if (dateSel) {
        const prevVal = dateSel.value || 'all';
        const dateMap = new Map();
        rankings.forEach(r => {
          const d = r.chart_date || 'Latest Daily';
          const w = r.chart_week_label || d;
          if (!dateMap.has(d)) dateMap.set(d, w);
        });
        const sortedDates = Array.from(dateMap.keys()).sort().reverse();
        dateSel.innerHTML = `<option value="all">All Dates / Weeks (${sortedDates.length})</option>` +
          sortedDates.map(d => `<option value="${escapeHtml(d)}">${escapeHtml(dateMap.get(d))}</option>`).join('');
        if (sortedDates.includes(prevVal)) {
          dateSel.value = prevVal;
        } else {
          dateSel.value = 'all';
        }
      }

      // Update Rank Tier Filter labels with live counts of Current #1s and Past #1s
      const rankSel = document.getElementById('rank-tier-filter');
      if (rankSel) {
        const prevRankVal = rankSel.value || 'all';
        const currOneCnt = rankings.filter(r => Number(r.rank_position) === 1).length;
        const everOneCnt = rankings.filter(r => Number(r.rank_position) === 1 || Number(r.previous_position) === 1 || r.reached_number_one).length;
        const pastOnlyOneCnt = rankings.filter(r => Number(r.rank_position) > 1 && (Number(r.previous_position) === 1 || r.reached_number_one)).length;
        rankSel.innerHTML = `
          <option value="all">All Ranks (${rankings.length})</option>
          <option value="ever-1">All Current + Past #1s (${everOneCnt})</option>
          <option value="1">Current #1 Champions (${currOneCnt})</option>
          <option value="past-1">Past #1s Only — Prev / Historical (${pastOnlyOneCnt})</option>
          <option value="5">Top 5 Tier <= #5</option>
          <option value="10">Top 10 Entries <= #10</option>
          <option value="20">Top 20 Entries <= #20</option>
        `;
        rankSel.value = prevRankVal;
      }

      const tabs = [
        { id: 'overview', label: `01 // PEAK HIGHLIGHTS & SURFACES (${rankings.length})` },
        { id: 'daily', label: `02 // DAILY MUSIC VIDEOS (${dailyCnt})` },
        { id: 'trending', label: `03 // LIVE TRENDING (${trendCnt})` },
        { id: 'cards', label: `04 // 9:16 SHARE CARD STUDIO (${cardsCnt})` }
      ];

      if (entity.kind === 'track') {
        tabs.push({ id: 'audience', label: `05 // AUDIENCE & LYRICS (${commentsCnt})` });
      }
      tabs.push({ id: 'layers', label: `06 // COMPOSABLE FILES & REPORT (${(entity.files || []).length})` });

      document.getElementById('view-tabs-container').innerHTML = tabs.map(t => `
        <button
          type="button"
          role="tab"
          aria-selected="${STATE.activeTab === t.id}"
          class="tab-btn ${STATE.activeTab === t.id ? 'active' : ''}"
          onclick="switchTab('${t.id}')"
        >${escapeHtml(t.label)}</button>
      `).join('');
    }

    function getFilteredRankings(rankings) {
      const q = (document.getElementById('country-filter-input')?.value || '').trim().toLowerCase();
      const dateFilter = document.getElementById('cycle-date-filter')?.value || 'all';
      const maxRank = document.getElementById('rank-tier-filter')?.value || 'all';

      return rankings.filter(r => {
        if (q) {
          const matchCountry = (r.country_name || '').toLowerCase().includes(q) ||
                               (r.country_code || '').toLowerCase().includes(q) ||
                               (r.title || '').toLowerCase().includes(q) ||
                               (r.chart_date || '').toLowerCase().includes(q) ||
                               (r.chart_week_label || '').toLowerCase().includes(q);
          if (!matchCountry) return false;
        }
        if (dateFilter !== 'all') {
          if (String(r.chart_date) !== String(dateFilter)) return false;
        }
        if (maxRank === '1') {
          if (Number(r.rank_position) !== 1) return false;
        } else if (maxRank === 'ever-1') {
          const hitOne = Number(r.rank_position) === 1 || Number(r.previous_position) === 1 || Boolean(r.reached_number_one);
          if (!hitOne) return false;
        } else if (maxRank === 'past-1') {
          const isPastOne = Number(r.rank_position) > 1 && (Number(r.previous_position) === 1 || Boolean(r.reached_number_one));
          if (!isPastOne) return false;
        } else if (maxRank !== 'all') {
          if (Number(r.rank_position) > Number(maxRank)) return false;
        }
        return true;
      });
    }

    function buildPlacementTableHtml(rows, captionText, includeTrackCol = false) {
      if (!rows || rows.length === 0) {
        return `<div style="padding: 28px; color: var(--text-muted); font-family: var(--font-mono);">No chart placements matching current filter criteria.</div>`;
      }
      const tableId = 'tbl-' + Math.random().toString(36).slice(2, 8);
      return `
        <div tabindex="0" role="region" aria-labelledby="${tableId}" class="table-wrapper">
          <table class="data-table" style="--label-2: 'Code'; --label-3: 'Surface'; --label-4: 'Rank'; --label-5: 'Chart Date / Week'; --label-6: 'Peak Classification';">
            <caption id="${tableId}">${escapeHtml(captionText)}</caption>
            <thead>
              <tr>
                <th>COUNTRY</th>
                ${includeTrackCol ? '<th>TRACK</th>' : ''}
                <th>CODE</th>
                <th>SURFACE / CHART TYPE</th>
                <th>RANK</th>
                <th>PREV</th>
                <th>ALL-TIME BEST</th>
                <th>CHART DATE / WEEK</th>
                <th>PEAK CLASSIFICATION</th>
                <th>9:16 ASSET</th>
              </tr>
            </thead>
            <tbody>
              ${rows.map((r) => {
                const isSelected = STATE.selectedPlacement &&
                  STATE.selectedPlacement.country_code === r.country_code &&
                  STATE.selectedPlacement.chart_type === r.chart_type &&
                  STATE.selectedPlacement.chart_date === r.chart_date &&
                  STATE.selectedPlacement.video_id === r.video_id;
                const rowJson = encodeURIComponent(JSON.stringify(r));
                const isPastOne = Number(r.rank_position) > 1 && (Number(r.previous_position) === 1 || r.reached_number_one);
                const bestPos = r.all_time_best_rank || r.rank_position;
                return `
                  <tr class="${isSelected ? 'selected-row' : ''}" onclick="selectPlacementFromRow('${rowJson}')">
                    <th scope="row">${escapeHtml(r.flag || '')} ${escapeHtml(r.country_name)}</th>
                    ${includeTrackCol ? `<td class="mono" style="color:var(--text-primary);">${escapeHtml((r.title || '').slice(0, 34))}</td>` : ''}
                    <td class="mono">${escapeHtml(r.country_code)}</td>
                    <td>${escapeHtml(r.chart_type)}</td>
                    <td><span class="${getRankPillClass(r.rank_position)}">#${escapeHtml(r.rank_position)}</span></td>
                    <td class="mono">${r.previous_position ? `<span class="${Number(r.previous_position) === 1 ? 'rank-pill rank-1' : ''}">#${escapeHtml(r.previous_position)}</span>` : '—'}</td>
                    <td>
                      <span class="${getRankPillClass(bestPos)}">#${escapeHtml(bestPos)}</span>
                      ${isPastOne ? `<span class="mono" style="font-size:10px; color:var(--accent-amber); margin-left:4px;">★ PAST #1</span>` : ''}
                    </td>
                    <td class="mono" title="${escapeHtml(r.chart_week_label || r.chart_date)}">${escapeHtml(r.chart_week_label || r.chart_date || '—')}</td>
                    <td><span class="${getPeakBadgeClass(r.rank_position)}">${escapeHtml(r.status)}</span></td>
                    <td class="mono">${r.share_card_url ? `<a href="${escapeHtml(r.share_card_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation();" style="color:var(--accent-orange); text-decoration:none;">1080×1920 ↗</a>` : '—'}</td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        </div>
      `;
    }

    function renderActiveTab() {
      const entity = getActiveEntity();
      const body = document.getElementById('workspace-body');
      if (!entity) return;

      const allRankings = getFilteredRankings(entity.rankings || []);
      const isArtist = entity.kind === 'artist';

      if (STATE.activeTab === 'overview') {
        const keyMarkets = new Set(STATE.data.key_markets || ['US','GB','TH','KR','JP','BR','FR','DE','AU','CA','GLOBAL']);
        const selectTop = allRankings
          .filter(r => Number(r.rank_position) <= 10 || (keyMarkets.has(r.country_code) && Number(r.rank_position) <= 30))
          .slice()
          .sort((a, b) => Number(a.rank_position) - Number(b.rank_position))
          .slice(0, 25);

        const champions = allRankings.filter(r => Number(r.rank_position) === 1);
        const pastChampions = allRankings.filter(r => Number(r.rank_position) > 1 && (Number(r.previous_position) === 1 || r.reached_number_one));
        const dailyRows = allRankings.filter(r => r.chart_type === 'Daily Top Music Videos');
        const trendingRows = allRankings.filter(r => r.chart_type === 'Overall YouTube Trending');

        let artistCatalogHtml = '';
        if (isArtist && (entity.tracks || []).length > 0) {
          artistCatalogHtml = `
            <section class="panel-block">
              <div class="panel-header">
                <div class="panel-title-group">
                  <span class="panel-title">00 // ACTIVE CHARTING TRACK CATALOG (${entity.tracks.length} TRACKS DISCOVERED)</span>
                </div>
                <span class="panel-subtitle">Zero Video IDs Provided — Auto-Detected on Top 100 Charts</span>
              </div>
              <div tabindex="0" role="region" aria-label="Discovered Artist Tracks" class="table-wrapper">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th>TRACK TITLE</th>
                      <th>VIDEO ID</th>
                      <th>PEAK GLOBAL RANK</th>
                      <th>PLACEMENTS</th>
                      <th>COUNTRIES</th>
                      <th>PEAK CLASSIFICATION</th>
                      <th>ACTION</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${entity.tracks.map(t => `
                      <tr>
                        <th scope="row">${escapeHtml(t.title)}</th>
                        <td class="mono"><a href="https://www.youtube.com/watch?v=${escapeHtml(t.video_id)}" target="_blank" rel="noopener" style="color:var(--accent-orange);">${escapeHtml(t.video_id)} ↗</a></td>
                        <td><span class="${getRankPillClass(t.best_rank)}">#${escapeHtml(t.best_rank)}</span></td>
                        <td class="mono">${formatNumber(t.total_placements)}</td>
                        <td class="mono">${formatNumber(t.unique_countries_count)}</td>
                        <td><span class="${getPeakBadgeClass(t.best_rank)}">${escapeHtml(t.best_rank_status)}</span></td>
                        <td><button type="button" class="btn" style="height:24px; padding:0 8px;" onclick="prefillResweep('track', '${escapeHtml(t.video_id)}')">BUILD TRACK DOSSIER</button></td>
                      </tr>
                    `).join('')}
                  </tbody>
                </table>
              </div>
            </section>
          `;
        }

        body.innerHTML = `
          ${artistCatalogHtml}

          <!-- Section 2: Select Top Territory Placements (Peak Highlights) -->
          <section class="panel-block">
            <div class="panel-header">
              <div class="panel-title-group">
                <span class="panel-title">🌟 SELECT TOP TERRITORY PLACEMENTS (PEAK HIGHLIGHTS)</span>
                <span class="rail-pill">${selectTop.length} highlighted rows</span>
              </div>
              <span class="panel-subtitle">Click any row to inspect its 1080×1920 vertical YouTube Share Card</span>
            </div>
            ${(champions.length > 0 || pastChampions.length > 0) ? `
              <div class="champions-strip">
                ${champions.length > 0 ? `
                  <span class="mono" style="font-size:11px; font-weight:700; color:var(--accent-emerald);">🏆 CURRENT #1 CHAMPIONS (${champions.length}):</span>
                  ${champions.map(c => {
                    const cj = encodeURIComponent(JSON.stringify(c));
                    return `<span class="champion-tag" onclick="selectPlacementFromRow('${cj}')" title="Cycle: ${escapeHtml(c.chart_week_label || c.chart_date)}">${escapeHtml(c.flag)} ${escapeHtml(c.country_name)} · ${escapeHtml(c.chart_date)}</span>`;
                  }).join('')}
                ` : ''}
                ${pastChampions.length > 0 ? `
                  <span class="mono" style="font-size:11px; font-weight:700; color:var(--accent-amber); margin-left:${champions.length ? '8px' : '0'};">★ PAST #1 PEAKS (${pastChampions.length}):</span>
                  ${pastChampions.map(c => {
                    const cj = encodeURIComponent(JSON.stringify(c));
                    return `<span class="champion-tag" style="border-color:rgba(245,158,11,0.45); color:var(--accent-amber);" onclick="selectPlacementFromRow('${cj}')" title="Reached #1 in prior cycle; currently #${escapeHtml(c.rank_position)} on ${escapeHtml(c.chart_date)}">${escapeHtml(c.flag)} ${escapeHtml(c.country_name)} (Prev #1 → Now #${escapeHtml(c.rank_position)} · ${escapeHtml(c.chart_date)})</span>`;
                  }).join('')}
                ` : ''}
              </div>
            ` : ''}
            ${buildPlacementTableHtml(selectTop.length ? selectTop : allRankings.slice(0, 20), 'Select Top Territory Placements', isArtist)}
          </section>

          <!-- Section 3: Grouped Surface Matrix (3A Daily Top Music Videos vs 3B Overall YouTube Trending) -->
          <div class="surface-split-grid">
            <section class="panel-block">
              <div class="panel-header">
                <div class="panel-title-group">
                  <span class="panel-title">3A // DAILY TOP MUSIC VIDEOS CHART</span>
                  <span class="rail-pill">${dailyRows.length} rows</span>
                </div>
                <span class="panel-subtitle">CHART_TYPE_VIDEOS · Finalized 24h Cycle</span>
              </div>
              ${buildPlacementTableHtml(dailyRows, 'Daily Top Music Videos Chart Placements', isArtist)}
            </section>

            <section class="panel-block">
              <div class="panel-header">
                <div class="panel-title-group">
                  <span class="panel-title">3B // OVERALL YOUTUBE TRENDING</span>
                  <span class="rail-pill">${trendingRows.length} rows</span>
                </div>
                <span class="panel-subtitle">CHART_TYPE_TRENDING_VIDEOS · Live Real-Time Feed</span>
              </div>
              ${buildPlacementTableHtml(trendingRows, 'Overall YouTube Trending Placements', isArtist)}
            </section>
          </div>
        `;
      } else if (STATE.activeTab === 'daily') {
        const dailyRows = allRankings.filter(r => r.chart_type === 'Daily Top Music Videos');
        body.innerHTML = `
          <section class="panel-block">
            <div class="panel-header">
              <div class="panel-title-group">
                <span class="panel-title">3A // DAILY TOP MUSIC VIDEOS CHART (${dailyRows.length} PLACEMENTS)</span>
              </div>
              <span class="panel-subtitle">Cycle: ${escapeHtml(entity.date_metrics?.daily_chart_cycle || 'Latest Active')}</span>
            </div>
            ${buildPlacementTableHtml(dailyRows, 'Daily Top Music Videos Full Matrix', isArtist)}
          </section>
        `;
      } else if (STATE.activeTab === 'trending') {
        const trendingRows = allRankings.filter(r => r.chart_type === 'Overall YouTube Trending');
        body.innerHTML = `
          <section class="panel-block">
            <div class="panel-header">
              <div class="panel-title-group">
                <span class="panel-title">3B // OVERALL YOUTUBE TRENDING (${trendingRows.length} PLACEMENTS)</span>
              </div>
              <span class="panel-subtitle">${escapeHtml(entity.date_metrics?.trending_feed_state || 'Live Real-Time Snapshot')}</span>
            </div>
            ${buildPlacementTableHtml(trendingRows, 'Overall YouTube Trending Full Matrix', isArtist)}
          </section>
        `;
      } else if (STATE.activeTab === 'cards') {
        const cardsRows = allRankings.filter(r => r.share_card_url);
        const cachedCnt = cardsRows.filter(r => r.share_card_cached).length;
        const selectedCnt = cardsRows.filter(r => STATE.selectedCardKeys.has(getShareCardKey(r))).length;
        body.innerHTML = `
          <section class="panel-block">
            <div class="panel-header" style="flex-wrap:wrap; gap:10px;">
              <div class="panel-title-group">
                <span class="panel-title">🎨 OFFICIAL YOUTUBE CHARTS 9:16 VERTICAL SHARE CARD STUDIO (${cardsRows.length} ASSETS)</span>
                <span class="rail-pill ${cachedCnt === cardsRows.length && cardsRows.length > 0 ? 'peak-one' : ''}" title="Images cached locally inside ${escapeHtml(entity.folder)}/share_cards_cache/">
                  Disk Cache: ${cachedCnt} / ${cardsRows.length} cached
                </span>
                ${selectedCnt > 0 ? `<span class="rail-pill" style="border-color:var(--accent-orange); color:var(--accent-orange);">${selectedCnt} selected</span>` : ''}
              </div>
              <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                <button type="button" class="btn" style="height:24px; padding:0 8px; font-size:10.5px;" onclick="selectAllShareCards(true)">SELECT ALL (${cardsRows.length})</button>
                <button type="button" class="btn" style="height:24px; padding:0 8px; font-size:10.5px;" onclick="selectAllShareCards(false)" ${selectedCnt === 0 ? 'disabled' : ''}>CLEAR (${selectedCnt})</button>
                <button type="button" class="btn" id="cache-cards-btn" style="height:24px; padding:0 9px; font-size:10.5px;" onclick="cacheAllShareCards()" title="Download & cache all 1080×1920 JPEGs into ${escapeHtml(entity.folder)}/share_cards_cache/">
                  ⚡ CACHE ALL TO DISK
                </button>
                <button
                  type="button"
                  class="btn"
                  id="export-selected-zip-btn"
                  style="height:24px; padding:0 10px; font-size:10.5px; border-color:${selectedCnt > 0 ? 'var(--accent-orange)' : 'var(--border-strong)'}; color:${selectedCnt > 0 ? 'var(--accent-orange)' : 'var(--text-secondary)'};"
                  onclick="exportShareCardsZip('selected')"
                  ${selectedCnt === 0 ? 'disabled' : ''}
                  title="Bundle selected 1080×1920 JPEGs into a named .zip archive"
                >
                  📦 EXPORT SELECTED TO ZIP (${selectedCnt})
                </button>
                <button
                  type="button"
                  class="btn btn-primary"
                  id="export-all-zip-btn"
                  style="height:24px; padding:0 10px; font-size:10.5px;"
                  onclick="exportShareCardsZip('all')"
                  ${cardsRows.length === 0 ? 'disabled' : ''}
                  title="Bundle all ${cardsRows.length} filtered 1080×1920 JPEGs into a named .zip archive"
                >
                  📦 EXPORT ALL TO ZIP (${cardsRows.length})
                </button>
              </div>
            </div>
            <div class="share-card-grid">
              ${cardsRows.map(r => {
                const rj = encodeURIComponent(JSON.stringify(r));
                const cKey = getShareCardKey(r);
                const isSel = STATE.selectedCardKeys.has(cKey);
                const fn = r.share_card_filename || `${r.country_code}_Rank${r.rank_position}_9x16.jpg`;
                const imgSrc = (STATE.apiOnline && r.share_card_cached)
                  ? `/api/share-card/image?folder=${encodeURIComponent(entity.folder)}&filename=${encodeURIComponent(fn)}&url=${encodeURIComponent(r.share_card_url)}`
                  : r.share_card_url;
                return `
                  <div class="share-card-tile ${isSel ? 'selected' : ''}" onclick="selectPlacementFromRow('${rj}')">
                    <div class="share-card-img-wrap">
                      <label class="share-card-checkbox-overlay" onclick="event.stopPropagation();">
                        <input type="checkbox" ${isSel ? 'checked' : ''} onchange="toggleShareCardSelection('${escapeHtml(cKey)}')" style="accent-color:var(--accent-orange); cursor:pointer;" />
                        <span>SELECT</span>
                      </label>
                      <span class="share-card-cache-badge ${r.share_card_cached ? 'cached' : ''}" title="${escapeHtml(fn)}">
                        ${r.share_card_cached ? '✓ DISK CACHED' : 'LIVE URI'}
                      </span>
                      <img src="${escapeHtml(imgSrc)}" alt="${escapeHtml(r.country_name)} Share Card" loading="lazy" />
                    </div>
                    <div class="share-card-meta">
                      <span><strong>${escapeHtml(r.flag)} ${escapeHtml(r.country_code)}</strong> · ${escapeHtml(r.chart_type.includes('Daily') ? 'Daily' : 'Trending')}</span>
                      <span class="${getRankPillClass(r.rank_position)}">#${escapeHtml(r.rank_position)}</span>
                    </div>
                    <div class="mono" style="padding:0 12px 8px 12px; font-size:9.5px; color:var(--text-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(fn)}">
                      ${escapeHtml(fn)}
                    </div>
                  </div>
                `;
              }).join('')}
            </div>
          </section>
        `;
      } else if (STATE.activeTab === 'audience') {
        const comments = entity.comments || [];
        const lyrics = entity.metadata?.lyrics || '';
        const tags = (entity.metadata?.tags || []).join(', ');
        const vidId = entity.video_id || '';
        body.innerHTML = `
          <div class="surface-split-grid">
            <section class="panel-block">
              <div class="panel-header">
                <div class="panel-title-group">
                  <span class="panel-title">💬 TOP RANKED COMMUNITY COMMENTS (${comments.length})</span>
                </div>
                <span class="panel-subtitle">Sorted by upvote velocity · Click timestamp or link to open comment on YouTube</span>
              </div>
              ${comments.length > 0 ? `
                <div tabindex="0" role="region" aria-label="Top Ranked Comments" class="table-wrapper">
                  <table class="data-table">
                    <thead>
                      <tr>
                        <th>RANK</th>
                        <th>AUTHOR</th>
                        <th>TIMESTAMP / LINK</th>
                        <th>LIKES</th>
                        <th>COMMENT TEXT</th>
                      </tr>
                    </thead>
                    <tbody>
                      ${comments.map(c => {
                        const cid = c.comment_id || '';
                        const cvid = c.video_id || vidId;
                        const commentUrl = c.comment_url || (cvid && cid ? `https://www.youtube.com/watch?v=${cvid}&lc=${cid}` : `https://www.youtube.com/watch?v=${cvid}`);
                        const authorUrl = c.author_channel_id ? `https://www.youtube.com/channel/${c.author_channel_id}` : (c.author_handle ? `https://www.youtube.com/${c.author_handle}` : '');
                        const tsLabel = c.publish_timestamp_pst || c.publish_date || '—';
                        return `
                          <tr>
                            <th scope="row" class="mono">
                              <a href="${escapeHtml(commentUrl)}" target="_blank" rel="noopener" style="color:var(--text-primary); text-decoration:none;" title="Open Comment #${escapeHtml(c.rank)} on YouTube">#${escapeHtml(c.rank)}</a>
                            </th>
                            <td class="mono">
                              ${authorUrl
                                ? `<a href="${escapeHtml(authorUrl)}" target="_blank" rel="noopener" style="color:var(--text-secondary); text-decoration:none;">${escapeHtml(c.author_handle)} ↗</a>`
                                : escapeHtml(c.author_handle)
                              }
                            </td>
                            <td class="mono">
                              <a href="${escapeHtml(commentUrl)}" target="_blank" rel="noopener" style="color:var(--accent-orange); text-decoration:none; font-weight:600;" title="Direct Permalink to Comment (${escapeHtml(cid)})">
                                ${escapeHtml(tsLabel)} ↗
                              </a>
                            </td>
                            <td class="mono" style="color:var(--accent-emerald); font-weight:600;">${formatNumber(c.likes_count)}</td>
                            <td style="white-space:normal; min-width:260px; color:var(--text-primary);">
                              <a href="${escapeHtml(commentUrl)}" target="_blank" rel="noopener" style="color:inherit; text-decoration:none; display:block;" title="Click to view comment thread on YouTube">
                                ${escapeHtml(c.comment_text)}
                              </a>
                            </td>
                          </tr>
                        `;
                      }).join('')}
                    </tbody>
                  </table>
                </div>
              ` : `<div style="padding:24px; font-family:var(--font-mono); color:var(--text-muted);">Comments skipped by default for 2-4s fast execution. Re-run with [+Comments] enabled to populate.</div>`}
            </section>

            <section class="panel-block">
              <div class="panel-header">
                <span class="panel-title">📝 METADATA TAGS & EXTRACTED LYRICS</span>
              </div>
              <div style="padding:14px; display:flex; flex-direction:column; gap:12px;">
                <div>
                  <div class="date-cell-label" style="margin-bottom:4px;">TAGS</div>
                  <div class="mono" style="font-size:11px; color:var(--text-secondary); line-height:1.5;">${escapeHtml(tags || 'No tags listed')}</div>
                </div>
                <div>
                  <div class="date-cell-label" style="margin-bottom:4px;">EXTRACTED LYRICS</div>
                  <pre class="mono" style="font-size:11px; color:var(--text-primary); white-space:pre-wrap; background:var(--bg-canvas); padding:12px; border:1px solid var(--border-hairline); max-height:380px; overflow-y:auto;">${escapeHtml(lyrics || 'No lyrics block detected in video description.')}</pre>
                </div>
              </div>
            </section>
          </div>
        `;
      } else if (STATE.activeTab === 'layers') {
        const files = entity.files || [];
        body.innerHTML = `
          <div class="surface-split-grid">
            <section class="panel-block">
              <div class="panel-header">
                <span class="panel-title">🗂️ DISCRETE COMPOSABLE DATASET FILES (${files.length})</span>
                <span class="panel-subtitle">Folder: ${escapeHtml(entity.folder)}</span>
              </div>
              <div tabindex="0" role="region" aria-label="Dataset Files" class="table-wrapper">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th>FILENAME</th>
                      <th>FORMAT</th>
                      <th>ACTION</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${files.map(fn => {
                      const ext = fn.split('.').pop().toUpperCase();
                      const dlUrl = `/api/export/${encodeURIComponent(entity.folder)}/${encodeURIComponent(fn)}`;
                      return `
                        <tr>
                          <th scope="row" class="mono">${escapeHtml(fn)}</th>
                          <td class="mono">${escapeHtml(ext)}</td>
                          <td>
                            ${STATE.apiOnline
                              ? `<a class="btn" style="height:24px; padding:0 8px;" href="${dlUrl}" target="_blank">DOWNLOAD / VIEW ↗</a>`
                              : `<span class="mono" style="color:var(--text-muted); font-size:11px;">${escapeHtml(entity.folder)}/${escapeHtml(fn)}</span>`
                            }
                          </td>
                        </tr>
                      `;
                    }).join('')}
                  </tbody>
                </table>
              </div>
            </section>

            <section class="panel-block">
              <div class="panel-header">
                <span class="panel-title">📄 EXECUTIVE MARKDOWN REPORT SOURCE</span>
                <button type="button" class="btn" style="height:24px; padding:0 8px;" onclick="copyMarkdownReport()">COPY MARKDOWN</button>
              </div>
              <pre class="mono" style="font-size:11px; color:var(--text-secondary); white-space:pre-wrap; padding:14px; max-height:480px; overflow-y:auto;">${escapeHtml(entity.report_markdown || 'No Markdown report found.')}</pre>
            </section>
          </div>
        `;
      }
    }

    function getShareCardKey(r) {
      return `${r.country_code || ''}::${r.chart_type || ''}::${r.chart_date || ''}::${r.video_id || ''}`;
    }

    function toggleShareCardSelection(cardKey) {
      if (STATE.selectedCardKeys.has(cardKey)) {
        STATE.selectedCardKeys.delete(cardKey);
      } else {
        STATE.selectedCardKeys.add(cardKey);
      }
      renderActiveTab();
    }

    function selectAllShareCards(selectAll) {
      const entity = getActiveEntity();
      if (!entity) return;
      const cardsRows = getFilteredRankings(entity.rankings || []).filter(r => r.share_card_url);
      if (selectAll) {
        cardsRows.forEach(r => STATE.selectedCardKeys.add(getShareCardKey(r)));
      } else {
        STATE.selectedCardKeys.clear();
      }
      renderActiveTab();
    }

    function buildZipArchiveFilename(entity, targetRows, mode) {
      const rawName = (entity.entity_name || entity.artist_name || entity.id || 'YouTube').replace(/[^a-zA-Z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 44);
      const bestPos = targetRows.length > 0 ? Math.min(...targetRows.map(r => Number(r.rank_position) || 999)) : 999;
      const num1Count = targetRows.filter(r => Number(r.rank_position) === 1).length;
      const statSlug = num1Count > 0
        ? `Peak1_${num1Count}xNum1Champions`
        : (bestPos < 999 ? `PeakRank${bestPos}` : 'ChartCards');
      const hasDaily = targetRows.some(r => (r.chart_type || '').includes('Daily'));
      const hasTrend = targetRows.some(r => (r.chart_type || '').includes('Trending'));
      const typeSlug = (hasDaily && hasTrend) ? 'DailyMV_and_Trending' : (hasDaily ? 'DailyTopMV' : 'LiveTrending');
      const scopeSlug = mode === 'selected' ? `Selected_${targetRows.length}cards` : `All_${targetRows.length}cards`;
      return `${rawName}__YouTube_Charts_9x16_ShareCards__${typeSlug}__${statSlug}__${scopeSlug}.zip`;
    }

    async function cacheAllShareCards() {
      const entity = getActiveEntity();
      if (!entity) return;
      if (!STATE.apiOnline) {
        showToast('Start the local Python server to cache 1080×1920 JPEGs to disk.');
        return;
      }
      const cardsRows = getFilteredRankings(entity.rankings || []).filter(r => r.share_card_url);
      if (cardsRows.length === 0) return;

      const btn = document.getElementById('cache-cards-btn');
      if (btn) {
        btn.disabled = true;
        btn.textContent = `CACHING (${cardsRows.length})...`;
      }
      showToast(`Caching ${cardsRows.length} vertical 9:16 share cards to ${entity.folder}/share_cards_cache/...`, 5000);
      try {
        const res = await fetch('/api/share-cards/cache-all', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            folder: entity.folder,
            items: cardsRows.map(r => ({
              url: r.share_card_url,
              filename: r.share_card_filename || `${r.country_code}_Rank${r.rank_position}_9x16.jpg`
            }))
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Disk cache failed');
        STATE.data = data.datasets;
        renderAll(false);
        showToast(`Cached ${data.cached_count}/${data.total_requested} 9:16 Share Cards to disk (${data.elapsed_sec}s)`);
      } catch (e) {
        showToast(`Cache error: ${e.message}`, 5000);
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.textContent = '⚡ CACHE ALL TO DISK';
        }
      }
    }

    async function exportShareCardsZip(mode = 'all') {
      const entity = getActiveEntity();
      if (!entity) return;
      if (!STATE.apiOnline) {
        showToast('Start the local Python server to bundle & export 9:16 Share Cards as ZIP.');
        return;
      }
      const filteredCards = getFilteredRankings(entity.rankings || []).filter(r => r.share_card_url);
      const targetRows = mode === 'selected'
        ? filteredCards.filter(r => STATE.selectedCardKeys.has(getShareCardKey(r)))
        : filteredCards;

      if (targetRows.length === 0) {
        showToast('No 9:16 Share Cards selected to export.');
        return;
      }

      const archiveName = buildZipArchiveFilename(entity, targetRows, mode);
      const btnId = mode === 'selected' ? 'export-selected-zip-btn' : 'export-all-zip-btn';
      const btn = document.getElementById(btnId);
      const prevText = btn ? btn.textContent : '';
      if (btn) {
        btn.disabled = true;
        btn.textContent = `PACKAGING ZIP (${targetRows.length})...`;
      }
      showToast(`Packaging ${targetRows.length} 1080×1920 JPEGs -> ${archiveName}...`, 6000);

      try {
        const res = await fetch('/api/share-cards/export-zip', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            folder: entity.folder,
            archive_name: archiveName,
            items: targetRows.map(r => ({
              url: r.share_card_url,
              filename: r.share_card_filename || `${r.country_code}_Rank${r.rank_position}_9x16.jpg`,
              country_code: r.country_code,
              country_name: r.country_name,
              rank_position: r.rank_position,
              status: r.status,
              chart_type: r.chart_type,
              chart_date: r.chart_date
            }))
          })
        });
        if (!res.ok) {
          const errJson = await res.json().catch(() => ({}));
          throw new Error(errJson.error || 'ZIP export failed');
        }
        const blob = await res.blob();
        const dlUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = dlUrl;
        a.download = archiveName;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(dlUrl), 10000);

        // Refresh dataset state so newly cached badges turn green
        const dsRes = await fetch('/api/datasets');
        if (dsRes.ok) {
          STATE.data = await dsRes.json();
          renderActiveTab();
        }
        showToast(`Exported ${targetRows.length} cards -> ${archiveName}`, 5000);
      } catch (e) {
        showToast(`ZIP Export Error: ${e.message}`, 5000);
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.textContent = prevText;
        }
      }
    }

    function selectPlacementFromRow(encodedJson) {
      try {
        STATE.selectedPlacement = JSON.parse(decodeURIComponent(encodedJson));
        if (window.innerWidth <= 1320 && !STATE.inspectorOpen) {
          STATE.inspectorOpen = true;
          if (window.innerWidth <= 900) STATE.sidebarOpen = false;
          syncDrawerLayout();
        }
        renderActiveTab();
        renderInspector(getActiveEntity());
      } catch (e) {
        console.error(e);
      }
    }

    function switchInspectorCycle(countryCode, chartDate, chartType) {
      const entity = getActiveEntity();
      if (!entity || !entity.rankings) return;
      const found = entity.rankings.find(r =>
        r.country_code === countryCode &&
        String(r.chart_date) === String(chartDate) &&
        String(r.chart_type) === String(chartType)
      );
      if (found) {
        STATE.selectedPlacement = found;
        renderActiveTab();
        renderInspector(entity);
      }
    }

    function renderInspector(entity) {
      const mount = document.getElementById('inspector-body');
      const p = STATE.selectedPlacement;
      if (!p) {
        mount.innerHTML = `<div class="mono" style="color:var(--text-muted);">Select any country placement row to inspect its 1080×1920 vertical YouTube Share Card and metadata.</div>`;
        return;
      }

      const cardUrl = p.share_card_url || '';
      let protoToken = '';
      if (cardUrl.includes('?r=')) {
        protoToken = cardUrl.split('?r=')[1];
      }

      const historyList = Array.isArray(p.territory_history) ? p.territory_history : [];
      const num1List = Array.isArray(p.number_one_timeline) ? p.number_one_timeline : [];
      const bestRank = p.all_time_best_rank || p.rank_position;

      mount.innerHTML = `
        <div class="inspector-card-frame">
          ${cardUrl
            ? `<img src="${escapeHtml(cardUrl)}" alt="${escapeHtml(p.country_name)} Share Card" />`
            : `<span class="mono" style="color:var(--text-muted);">No Share Card URL</span>`
          }
        </div>

        <div style="display:flex; gap:6px;">
          ${cardUrl ? `
            <a class="btn btn-primary" style="flex:1;" href="${escapeHtml(cardUrl)}" target="_blank" rel="noopener">OPEN 1080×1920 JPEG ↗</a>
            <button type="button" class="btn" onclick="navigator.clipboard?.writeText('${escapeHtml(cardUrl)}'); showToast('Copied Share Card URI');">COPY URI</button>
          ` : ''}
        </div>

        <div class="kv-list">
          <div class="kv-row">
            <span class="kv-key">Territory</span>
            <span class="kv-val"><strong>${escapeHtml(p.flag)} ${escapeHtml(p.country_name)} (${escapeHtml(p.country_code)})</strong></span>
          </div>
          <div class="kv-row">
            <span class="kv-key">Chart Surface</span>
            <span class="kv-val">${escapeHtml(p.chart_type)}</span>
          </div>
          <div class="kv-row">
            <span class="kv-key">Selected Cycle Rank</span>
            <span class="kv-val"><span class="${getRankPillClass(p.rank_position)}">#${escapeHtml(p.rank_position)}</span></span>
          </div>
          <div class="kv-row">
            <span class="kv-key">Previous Cycle Rank</span>
            <span class="kv-val">${p.previous_position ? `<span class="${Number(p.previous_position) === 1 ? 'rank-pill rank-1' : ''}">#${escapeHtml(p.previous_position)}</span>` : '—'}</span>
          </div>
          <div class="kv-row">
            <span class="kv-key">All-Time Best Rank</span>
            <span class="kv-val"><span class="${getRankPillClass(bestRank)}">#${escapeHtml(bestRank)}</span></span>
          </div>
          <div class="kv-row">
            <span class="kv-key">Chart Date</span>
            <span class="kv-val" style="color:var(--accent-orange); font-weight:600;">${escapeHtml(p.chart_date || '—')}</span>
          </div>
          <div class="kv-row">
            <span class="kv-key">ISO Week / Window</span>
            <span class="kv-val">${escapeHtml(p.chart_week_label || p.chart_date || '—')}</span>
          </div>
          <div class="kv-row">
            <span class="kv-key">Share Card Date</span>
            <span class="kv-val">${escapeHtml(p.card_cycle_date || p.chart_date || '—')}</span>
          </div>
          <div class="kv-row">
            <span class="kv-key">Video ID</span>
            <span class="kv-val"><code>${escapeHtml(p.video_id || entity?.video_id || '')}</code></span>
          </div>
        </div>

        ${num1List.length > 0 ? `
          <div class="kv-list" style="border-color: rgba(16, 185, 129, 0.45);">
            <div class="kv-row" style="background: rgba(16, 185, 129, 0.1); border-bottom: 1px solid rgba(16, 185, 129, 0.3);">
              <span class="kv-key" style="color: var(--accent-emerald); font-weight: 700;">🏆 #1 PEAK HISTORY (${num1List.length})</span>
              <span class="kv-val" style="color: var(--accent-emerald);">DATE / WEEK</span>
            </div>
            ${num1List.map(n1 => `
              <div class="kv-row" style="align-items: flex-start; flex-direction: column; gap: 3px;">
                <div style="display:flex; justify-content:space-between; width:100%;">
                  <span style="color:var(--text-primary); font-weight:600;">🥇 #1 · ${escapeHtml(n1.chart_type.includes('Daily') ? 'Daily Music Videos' : 'Overall Trending')}</span>
                  <span style="color:var(--accent-emerald); font-weight:600;">${escapeHtml(n1.chart_date)}</span>
                </div>
                <div style="display:flex; justify-content:space-between; width:100%; font-size:10px; color:var(--text-muted);">
                  <span>${escapeHtml(n1.type)}</span>
                  <span>${escapeHtml(n1.chart_week || '')}</span>
                </div>
              </div>
            `).join('')}
          </div>
        ` : ''}

        ${historyList.length > 0 ? `
          <div class="kv-list">
            <div class="kv-row" style="background: var(--bg-elevated);">
              <span class="kv-key" style="color: var(--text-primary); font-weight: 700;">📅 TERRITORY CYCLE TIMELINE (${historyList.length})</span>
              <span class="kv-val" style="font-size:10px; color:var(--text-muted);">Click to switch</span>
            </div>
            ${historyList.map(h => {
              const isCurr = String(h.chart_date) === String(p.chart_date) && String(h.chart_type) === String(p.chart_type);
              return `
                <button
                  type="button"
                  class="kv-row"
                  style="width:100%; background:${isCurr ? 'var(--bg-active)' : 'transparent'}; border-left:${isCurr ? '2px solid var(--accent-orange)' : '2px solid transparent'}; cursor:pointer; text-align:left;"
                  onclick="switchInspectorCycle('${escapeHtml(p.country_code)}', '${escapeHtml(h.chart_date)}', '${escapeHtml(h.chart_type)}')"
                >
                  <span class="kv-key" style="color:var(--text-primary);">
                    <span class="${getRankPillClass(h.rank_position)}" style="min-width:28px; padding:1px 5px; font-size:10.5px;">#${escapeHtml(h.rank_position)}</span>
                    ${h.previous_position ? `<span style="font-size:10px; color:${Number(h.previous_position)===1 ? 'var(--accent-emerald)' : 'var(--text-muted)'}; margin-left:4px;">(Prev #${escapeHtml(h.previous_position)})</span>` : ''}
                  </span>
                  <span class="kv-val" style="font-size:10.5px;">
                    <span style="color:var(--text-secondary);">${escapeHtml(h.surface_short)}</span> ·
                    <strong style="color:var(--text-primary);">${escapeHtml(h.chart_week || h.chart_date)}</strong>
                  </span>
                </button>
              `;
            }).join('')}
          </div>
        ` : ''}

        ${protoToken ? `
          <div>
            <div class="date-cell-label" style="margin-bottom:4px;">PROTOBUF SHARE TOKEN (?r=)</div>
            <div class="mono" style="font-size:10px; color:var(--text-muted); background:var(--bg-canvas); border:1px solid var(--border-hairline); padding:8px; word-break:break-all;">${escapeHtml(protoToken)}</div>
          </div>
        ` : ''}
      `;
    }

    function toggleInspector() {
      STATE.inspectorOpen = !STATE.inspectorOpen;
      if (window.innerWidth <= 900 && STATE.inspectorOpen) {
        STATE.sidebarOpen = false;
      }
      syncDrawerLayout();
    }

    function prefillResweep(mode, target) {
      setExecutionMode(mode);
      const inp = document.getElementById('sweep-target-input');
      inp.value = target;
      inp.focus();
      showToast(`Ready to sweep ${mode.toUpperCase()}: ${target}`);
    }

    function copyMarkdownReport() {
      const entity = getActiveEntity();
      if (entity && entity.report_markdown) {
        navigator.clipboard?.writeText(entity.report_markdown);
        showToast('Copied Executive Markdown Report to clipboard');
      }
    }

    function toggleCommandPalette() {
      const bd = document.getElementById('cmd-backdrop');
      const isOpen = bd.classList.toggle('open');
      if (isOpen) {
        const inp = document.getElementById('cmd-search-input');
        inp.value = '';
        renderCommandPaletteItems();
        setTimeout(() => inp.focus(), 20);
      }
    }

    function renderCommandPaletteItems() {
      const q = (document.getElementById('cmd-search-input')?.value || '').trim().toLowerCase();
      const items = [];

      STATE.data.tracks.forEach(t => {
        items.push({
          title: `Track Dossier: ${t.entity_name}`,
          meta: `${t.video_id} · ${t.summary_metrics?.number_of_countries_charting || 0} countries`,
          action: () => { selectEntity('track', t.id); toggleCommandPalette(); }
        });
      });

      STATE.data.artists.forEach(a => {
        items.push({
          title: `Artist Catalog: ${a.artist_name}`,
          meta: `${a.channel_name} · ${(a.tracks || []).length} active tracks`,
          action: () => { selectEntity('artist', a.id); toggleCommandPalette(); }
        });
      });

      items.push(
        { title: 'Open Artist / Channel Video Catalog Lookup & Shortlist Builder (L)', meta: 'Lookup', action: () => { toggleCommandPalette(); openLookupView(); } },
        { title: 'Open Cross-Track Benchmark & Overview Comparison (C)', meta: 'Compare', action: () => { toggleCommandPalette(); openCompareView(); } },
        { title: 'Toggle Left Datasets Sidebar ([)', meta: 'Layout', action: () => { toggleCommandPalette(); toggleSidebar(); } },
        { title: 'Toggle Right 9:16 Card Inspector (])', meta: 'Layout', action: () => { toggleCommandPalette(); toggleInspector(); } },
        { title: 'Switch View -> 01 // Peak Highlights & Surfaces', meta: 'Tab', action: () => { toggleCommandPalette(); switchTab('overview'); } },
        { title: 'Switch View -> 02 // Daily Top Music Videos', meta: 'Tab', action: () => { toggleCommandPalette(); switchTab('daily'); } },
        { title: 'Switch View -> 03 // Overall YouTube Trending', meta: 'Tab', action: () => { toggleCommandPalette(); switchTab('trending'); } },
        { title: 'Switch View -> 04 // 9:16 Share Card Studio', meta: 'Tab', action: () => { toggleCommandPalette(); switchTab('cards'); } },
        { title: 'Switch View -> 06 // Composable Files & Markdown Report', meta: 'Tab', action: () => { toggleCommandPalette(); switchTab('layers'); } },
        { title: 'Export All 9:16 Share Cards to Named ZIP Archive', meta: 'Export', action: () => { toggleCommandPalette(); switchTab('cards'); exportShareCardsZip('all'); } }
      );

      const filtered = items.filter(it => !q || it.title.toLowerCase().includes(q) || it.meta.toLowerCase().includes(q));
      const container = document.getElementById('cmd-results');
      container.innerHTML = filtered.map((it, i) => `
        <button type="button" class="cmd-item" data-idx="${i}">
          <span>${escapeHtml(it.title)}</span>
          <span style="color:var(--text-muted);">${escapeHtml(it.meta)}</span>
        </button>
      `).join('');

      Array.from(container.querySelectorAll('.cmd-item')).forEach((btn, idx) => {
        btn.onclick = filtered[idx].action;
      });
    }

    window.addEventListener('DOMContentLoaded', initApp);
  </script>
</body>
</html>
"""

def build_standalone_html() -> str:
    """Compiles the standalone HTML file with embedded preloaded JSON telemetry."""
    os.makedirs(DASHBOARDS_DIR, exist_ok=True)
    datasets = load_all_youtube_datasets()
    payload_str = json.dumps(datasets, ensure_ascii=False)
    html_content = HTML_TEMPLATE.replace("__PRELOADED_JSON_PAYLOAD__", payload_str)
    with open(HTML_OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html_content)
    return html_content


class DossierWebHandler(BaseHTTPRequestHandler):
    def _send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ["/", "/index.html"]:
            html_content = build_standalone_html()
            self.send_response(200)
            self._send_cors()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html_content.encode("utf-8"))
            return

        if path == "/api/datasets":
            data = load_all_youtube_datasets()
            self.send_response(200)
            self._send_cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            return

        if path == "/api/sweep/status":
            with SWEEP_STATE_LOCK:
                snapshot = dict(SWEEP_STATE)
                if snapshot.get("active") and snapshot.get("started_at"):
                    snapshot["elapsed_sec"] = round(time.time() - snapshot["started_at"], 2)
                else:
                    snapshot["elapsed_sec"] = 0.0
            self._send_json(200, snapshot)
            return

        if path == "/api/share-card/image":
            qs = urllib.parse.parse_qs(parsed.query)
            folder = (qs.get("folder") or [""])[0]
            filename = (qs.get("filename") or [""])[0]
            card_url = (qs.get("url") or [""])[0]
            safe_folder = os.path.basename(folder)
            safe_fn = os.path.basename(filename)
            folder_path = os.path.join(YOUTUBE_DATASETS_DIR, safe_folder)
            if os.path.isdir(folder_path) and safe_fn and card_url:
                ok, cached_path, raw_bytes = fetch_or_cache_share_card(folder_path, card_url, safe_fn)
                if ok and raw_bytes:
                    self.send_response(200)
                    self._send_cors()
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Cache-Control", "public, max-age=604800")
                    self.end_headers()
                    self.wfile.write(raw_bytes)
                    return
            self.send_response(404)
            self.end_headers()
            return

        if path.startswith("/api/export/"):
            parts = path.replace("/api/export/", "").split("/", 1)
            if len(parts) == 2:
                folder = urllib.parse.unquote(parts[0])
                filename = urllib.parse.unquote(parts[1])
                safe_folder = os.path.basename(folder)
                target_path = os.path.normpath(os.path.join(YOUTUBE_DATASETS_DIR, safe_folder, filename))
                if target_path.startswith(os.path.normpath(os.path.join(YOUTUBE_DATASETS_DIR, safe_folder))) and os.path.isfile(target_path):
                    self.send_response(200)
                    self._send_cors()
                    ctype = (
                        "application/json" if target_path.endswith(".json")
                        else "text/csv" if target_path.endswith(".csv")
                        else "application/zip" if target_path.endswith(".zip")
                        else "image/jpeg" if target_path.endswith(".jpg")
                        else "text/plain; charset=utf-8"
                    )
                    self.send_header("Content-Type", ctype)
                    self.end_headers()
                    with open(target_path, "rb") as fp:
                        self.wfile.write(fp.read())
                    return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"

        if path == "/api/sweep/cancel":
            with SWEEP_STATE_LOCK:
                was_active = SWEEP_STATE["active"]
                SWEEP_STATE["cancelled"] = True
                SWEEP_STATE["message"] = "Abort signal received — stopping sweep..."
            self._send_json(200, {"status": "cancelling" if was_active else "idle"})
            return

        try:
            body = json.loads(raw_body)
        except Exception as e:
            self._send_json(400, {"error": f"Invalid JSON: {e}"})
            return

        t0 = time.time()
        try:
            if path == "/api/channel/lookup":
                query = (body.get("query") or "").strip()
                max_items = int(body.get("max_items") or 50)
                if not query:
                    self._send_json(400, {"error": "Please provide an artist name, @handle, channel ID, or URL."})
                    return
                result = lookup_artist_channel_catalog(query=query, max_items=max_items)
                result["elapsed_sec"] = round(time.time() - t0, 2)
                self._send_json(200, result)
                return

            if path == "/api/sweep/batch-tracks":
                video_ids = body.get("video_ids") or []
                countries = body.get("countries") or "US,GB,TH,KR,JP,BR,FR,DE,AU,CA,ID,PH,MX,GLOBAL"
                target_date = body.get("date") or None
                with_comments = bool(body.get("with_comments", False))

                clean_ids = []
                for v in video_ids:
                    vid = extract_video_id(str(v).strip())
                    if vid and vid not in clean_ids:
                        clean_ids.append(vid)

                if not clean_ids:
                    self._send_json(400, {"error": "No valid 11-character YouTube video IDs selected for batch processing."})
                    return
                if len(clean_ids) > 25:
                    clean_ids = clean_ids[:25]

                with SWEEP_STATE_LOCK:
                    if SWEEP_STATE["active"]:
                        self._send_json(409, {
                            "error": f"A sweep is already running ({SWEEP_STATE['mode'].upper()}: {SWEEP_STATE['target']}). Wait for completion or click [■ STOP] to cancel."
                        })
                        return
                    SWEEP_STATE.update({
                        "active": True,
                        "cancelled": False,
                        "mode": "batch",
                        "target": f"{len(clean_ids)} shortlisted tracks",
                        "signature": f"batch:{','.join(clean_ids)}",
                        "started_at": t0,
                        "current_idx": 0,
                        "total_countries": len(clean_ids),
                        "current_country_code": "",
                        "current_country_name": "",
                        "hits_found": 0,
                        "message": f"Starting batch 5-Layer Dossier compilation for {len(clean_ids)} tracks..."
                    })

                compiled_ids = []
                total_tracks = len(clean_ids)
                try:
                    for idx_t, vid in enumerate(clean_ids, start=1):
                        if is_sweep_cancelled():
                            raise RuntimeError(f"Batch sweep cancelled after {len(compiled_ids)}/{total_tracks} tracks.")

                        def _sub_progress(c_idx, c_tot, cc, cname, hits, msg, _i=idx_t, _v=vid):
                            update_sweep_progress(
                                c_idx,
                                c_tot,
                                cc,
                                cname,
                                hits,
                                f"[Track {_i}/{total_tracks} · {_v}] {msg}"
                            )

                        out_dir = build_dossier(
                            video_input=vid,
                            target_date=target_date,
                            country_filter=countries,
                            max_comments=20 if with_comments else 0,
                            include_comments=with_comments,
                            cancel_check=is_sweep_cancelled,
                            progress_callback=_sub_progress
                        )
                        compiled_ids.append(os.path.basename(out_dir.rstrip("/")))

                    datasets = load_all_youtube_datasets()
                    build_standalone_html()
                    self._send_json(200, {
                        "status": "ok",
                        "compiled_count": len(compiled_ids),
                        "compiled_ids": compiled_ids,
                        "active_id": compiled_ids[0] if compiled_ids else None,
                        "elapsed_sec": round(time.time() - t0, 2),
                        "datasets": datasets
                    })
                finally:
                    with SWEEP_STATE_LOCK:
                        SWEEP_STATE["active"] = False
                        SWEEP_STATE["cancelled"] = False
                        SWEEP_STATE["message"] = "Idle"
                return

            if path == "/api/share-cards/cache-all":
                folder = os.path.basename(body.get("folder") or "")
                items = body.get("items") or []
                folder_path = os.path.join(YOUTUBE_DATASETS_DIR, folder)
                if not os.path.isdir(folder_path):
                    self._send_json(404, {"error": f"Dataset folder not found: {folder}"})
                    return

                def _cache_one(it):
                    url = it.get("url") or ""
                    fn = os.path.basename(it.get("filename") or "")
                    if not url or not fn:
                        return False
                    ok, _, _ = fetch_or_cache_share_card(folder_path, url, fn)
                    return ok

                cached_ok = 0
                with ThreadPoolExecutor(max_workers=8) as pool:
                    for res_ok in pool.map(_cache_one, items):
                        if res_ok:
                            cached_ok += 1

                datasets = load_all_youtube_datasets()
                self._send_json(200, {
                    "status": "ok",
                    "cached_count": cached_ok,
                    "total_requested": len(items),
                    "elapsed_sec": round(time.time() - t0, 2),
                    "datasets": datasets
                })
                return

            if path == "/api/share-cards/export-zip":
                folder = os.path.basename(body.get("folder") or "")
                archive_name = sanitize_filename_part(body.get("archive_name") or f"{folder}_YouTube_Charts_9x16_ShareCards", 120)
                if not archive_name.lower().endswith(".zip"):
                    archive_name += ".zip"
                items = body.get("items") or []
                folder_path = os.path.join(YOUTUBE_DATASETS_DIR, folder)
                if not os.path.isdir(folder_path):
                    self._send_json(404, {"error": f"Dataset folder not found: {folder}"})
                    return

                def _fetch_one(it):
                    url = it.get("url") or ""
                    fn = os.path.basename(it.get("filename") or "")
                    if not url or not fn:
                        return (fn, None, it)
                    ok, _, data_bytes = fetch_or_cache_share_card(folder_path, url, fn)
                    return (fn, data_bytes if ok else None, it)

                results = []
                with ThreadPoolExecutor(max_workers=8) as pool:
                    for r_item in pool.map(_fetch_one, items):
                        results.append(r_item)

                zip_buffer = io.BytesIO()
                manifest_entries = []
                added_files = set()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                    for fn, data_bytes, meta_it in results:
                        if not data_bytes or not fn:
                            continue
                        unique_fn = fn
                        counter = 2
                        while unique_fn in added_files:
                            base, ext = os.path.splitext(fn)
                            unique_fn = f"{base}_{counter}{ext}"
                            counter += 1
                        added_files.add(unique_fn)
                        zf.writestr(unique_fn, data_bytes)
                        manifest_entries.append({
                            "filename": unique_fn,
                            "country_code": meta_it.get("country_code", ""),
                            "country_name": meta_it.get("country_name", ""),
                            "rank_position": meta_it.get("rank_position", ""),
                            "status": meta_it.get("status", ""),
                            "chart_type": meta_it.get("chart_type", ""),
                            "chart_date": meta_it.get("chart_date", ""),
                            "share_card_url": meta_it.get("url", ""),
                            "bytes": len(data_bytes)
                        })

                    manifest_payload = {
                        "archive_name": archive_name,
                        "dataset_folder": folder,
                        "exported_at_pst": datetime.now(zoneinfo.ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d %H:%M:%S %Z"),
                        "total_cards_exported": len(manifest_entries),
                        "cards": manifest_entries
                    }
                    zf.writestr("share_cards_manifest.json", json.dumps(manifest_payload, indent=2, ensure_ascii=False))

                zip_bytes = zip_buffer.getvalue()
                exports_dir = os.path.join(folder_path, "exports")
                os.makedirs(exports_dir, exist_ok=True)
                try:
                    with open(os.path.join(exports_dir, archive_name), "wb") as f_out:
                        f_out.write(zip_bytes)
                except Exception:
                    pass

                self.send_response(200)
                self._send_cors()
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="{archive_name}"')
                self.send_header("Content-Length", str(len(zip_bytes)))
                self.end_headers()
                self.wfile.write(zip_bytes)
                return

            if path in ["/api/sweep/track", "/api/sweep/artist"]:
                target = (body.get("target") or "").strip()
                countries = body.get("countries") or ("US,GB,TH,KR,JP,BR,FR,DE,AU,CA,ID,PH,MX,GLOBAL" if path == "/api/sweep/track" else "default")
                target_date = body.get("date") or None
                with_comments = bool(body.get("with_comments", False))
                run_dossiers = bool(body.get("run_track_dossiers", False))
                mode = "track" if path == "/api/sweep/track" else "artist"
                norm_target = extract_video_id(target) if mode == "track" else target
                sig = f"{mode}:{norm_target}:{countries}:{target_date}:{with_comments}:{run_dossiers}"

                # Server-side Duplicate In-Flight Guard
                with SWEEP_STATE_LOCK:
                    if SWEEP_STATE["active"]:
                        self._send_json(409, {
                            "error": f"A sweep is already running ({SWEEP_STATE['mode'].upper()}: {SWEEP_STATE['target']}). Wait for completion or click [■ STOP] to cancel."
                        })
                        return
                    SWEEP_STATE.update({
                        "active": True,
                        "cancelled": False,
                        "mode": mode,
                        "target": norm_target,
                        "signature": sig,
                        "started_at": t0,
                        "current_idx": 0,
                        "total_countries": 1,
                        "current_country_code": "",
                        "current_country_name": "",
                        "hits_found": 0,
                        "message": f"Starting {mode.upper()} sweep for {norm_target}..."
                    })

                try:
                    if mode == "track":
                        out_dir = build_dossier(
                            video_input=target,
                            target_date=target_date,
                            country_filter=countries,
                            max_comments=20 if with_comments else 0,
                            include_comments=with_comments,
                            cancel_check=is_sweep_cancelled,
                            progress_callback=update_sweep_progress
                        )
                    else:
                        out_dir = build_artist_catalog_dossier(
                            target_input=target,
                            countries_input=countries,
                            target_date=target_date,
                            run_track_dossiers=run_dossiers,
                            cancel_check=is_sweep_cancelled,
                            progress_callback=update_sweep_progress
                        )

                    active_id = os.path.basename(out_dir.rstrip("/"))
                    datasets = load_all_youtube_datasets()
                    build_standalone_html()
                    self._send_json(200, {
                        "status": "ok",
                        "active_id": active_id,
                        "elapsed_sec": round(time.time() - t0, 2),
                        "datasets": datasets
                    })
                finally:
                    with SWEEP_STATE_LOCK:
                        SWEEP_STATE["active"] = False
                        SWEEP_STATE["cancelled"] = False
                        SWEEP_STATE["message"] = "Idle"
                return

            self._send_json(404, {"error": "Unknown endpoint"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _send_json(self, code: int, payload: dict):
        try:
            self.send_response(code)
            self._send_cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        except BrokenPipeError:
            pass


def main():
    parser = argparse.ArgumentParser(description="YouTube Track & Artist Dossier Web Console Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind (default: 0.0.0.0 for local + remote LAN/tunnel access)")
    parser.add_argument("--port", "-p", type=int, default=8088, help="Port to listen on (default: 8088)")
    parser.add_argument("--build-only", action="store_true", help="Compile standalone HTML file and exit without starting server")
    args = parser.parse_args()

    build_standalone_html()
    print(f"[✔] Compiled standalone console HTML -> {HTML_OUTPUT_PATH}")

    if args.build_only:
        return

    server = ThreadingHTTPServer((args.host, args.port), DossierWebHandler)
    print(f"[🚀] YT//DOSSIER_ENGINE Web Console running:")
    print(f"    - Local URL:   http://localhost:{args.port}")
    print(f"    - Network URL: http://{args.host}:{args.port}")
    print(f"    - Standalone:  file://{HTML_OUTPUT_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[+] Shutting down server.")
        server.server_close()

if __name__ == "__main__":
    main()
