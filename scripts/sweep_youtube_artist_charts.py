#!/usr/bin/env python3
"""
YouTube Artist & Channel Chart Sweep Engine
Author: Antigravity Multi-Agent System
Description:
    Accepts an artist channel ID, channel URL, handle, or artist name,
    sweeps YouTube Charts Top 100 Daily Music Videos and Overall Trending
    across international territories, and automatically discovers all charting
    tracks and their multi-country positions without requiring specific video IDs.
"""

import sys
import os
import re
import json
import csv
import time
import argparse
import subprocess
import zoneinfo
from datetime import datetime, timezone, timedelta

# Import core definitions from build_youtube_track_dossier
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.append(SCRIPT_DIR)

from build_youtube_track_dossier import (
    COUNTRY_NAMES,
    ALL_COUNTRY_CODES,
    get_country_flag,
    classify_peak_rank,
    query_innertube_chart,
    sanitize_slug,
    build_dossier
)

# Priority top 14 global music markets for fast default sweeps
DEFAULT_KEY_MARKETS = [
    "GLOBAL", "US", "GB", "TH", "KR", "JP", "BR", "FR", "DE", "AU", "CA", "ID", "PH", "MX"
]

def resolve_artist_or_channel(target: str, explicit_artist: str = None) -> dict:
    """Resolves a channel URL, handle, or raw ID via yt-dlp into channel metadata and artist aliases."""
    target_clean = (target or "").strip()
    is_channel = (
        "youtube.com/" in target_clean or
        "youtu.be/" in target_clean or
        target_clean.startswith("@") or
        (target_clean.startswith("UC") and len(target_clean) == 24)
    )

    if not is_channel:
        artist_name = explicit_artist or target_clean
        aliases = {artist_name.lower()}
        return {
            "artist_name": artist_name,
            "channel_name": target_clean,
            "channel_id": "",
            "channel_url": "",
            "subscribers": 0,
            "aliases": list(aliases)
        }

    url = target_clean
    if target_clean.startswith("@"):
        url = f"https://www.youtube.com/{target_clean}"
    elif target_clean.startswith("UC") and len(target_clean) == 24:
        url = f"https://www.youtube.com/channel/{target_clean}"

    print(f"[+] Resolving channel metadata via yt-dlp: {url}...")
    cmd = ["yt-dlp", "--playlist-end", "1", "--dump-single-json", "--no-warnings", url]
    res = subprocess.run(cmd, capture_output=True, text=True)

    if res.returncode != 0:
        clean_name = target_clean.replace("https://www.youtube.com/", "").replace("@", "")
        artist_name = explicit_artist or clean_name
        return {
            "artist_name": artist_name,
            "channel_name": clean_name,
            "channel_id": target_clean if target_clean.startswith("UC") else "",
            "channel_url": url,
            "subscribers": 0,
            "aliases": [clean_name.lower(), artist_name.lower()]
        }

    try:
        data = json.loads(res.stdout)
    except Exception:
        data = {}

    ch_id = data.get("channel_id") or data.get("id") or ""
    ch_name = data.get("channel") or data.get("uploader") or ""
    subs = data.get("channel_follower_count", 0)

    # Derive artist aliases by stripping channel suffixes (Official, VEVO, Topic, Music)
    clean_artist = re.sub(r'(official\s*vevo|vevo|official|topic|music|channel)$', '', ch_name, flags=re.IGNORECASE).strip()
    if explicit_artist:
        primary_artist = explicit_artist
    elif clean_artist:
        primary_artist = clean_artist
    else:
        primary_artist = ch_name

    aliases = {primary_artist.lower(), ch_name.lower()}
    if clean_artist:
        aliases.add(clean_artist.lower())

    handle = data.get("uploader_id") or ""
    if handle:
        aliases.add(handle.lower().replace("@", ""))

    if explicit_artist:
        aliases.add(explicit_artist.lower())

    return {
        "artist_name": primary_artist,
        "channel_name": ch_name or primary_artist,
        "channel_id": ch_id,
        "channel_url": url,
        "subscribers": subs or 0,
        "aliases": [a for a in aliases if len(a) >= 2]
    }

def match_video_to_artist(video: dict, target_info: dict) -> bool:
    """Evaluates whether a chart video item matches the target artist or channel."""
    target_ch_id = target_info.get("channel_id")
    aliases = target_info.get("aliases", [])

    # 1. Exact Channel ID match
    video_ch_id = video.get("externalChannelId", "")
    if target_ch_id and video_ch_id and video_ch_id == target_ch_id:
        return True

    # 2. Artist entity match in YouTube Charts artist list
    chart_artists = [a.get("name", "").lower() for a in video.get("artists", [])]
    for alias in aliases:
        if any(alias == ca or alias in ca for ca in chart_artists):
            return True

    # 3. Channel title match
    v_ch_name = video.get("channelName", "").lower()
    for alias in aliases:
        if alias in v_ch_name:
            return True

    # 4. Video title prefix / feature match (e.g. "LISA - ...", "... ft. LISA")
    v_title = video.get("title", "").lower()
    for alias in aliases:
        # Regex boundary check to avoid partial word collisions (e.g. 'al' in 'ball')
        pattern = r'(?:\b|_)' + re.escape(alias) + r'(?:\b|_)'
        if re.search(pattern, v_title):
            return True

    return False

def sweep_artist_charts(target_info: dict, countries: list, target_date: str = None,
                        cancel_check=None, progress_callback=None) -> tuple:
    """
    Sweeps YouTube Charts across specified territories, identifying all charting tracks
    and their positions for the given artist/channel.
    """
    artist_name = target_info["artist_name"]
    print(f"[+] Sweeping {len(countries)} territories on YouTube Charts for artist: {artist_name}...")
    print(f"    - Target Channel: {target_info['channel_name']} (ID: {target_info['channel_id'] or 'None'})")
    print(f"    - Matching Aliases: {target_info['aliases']}")

    discovered_tracks = {} # video_id -> {metadata, placements: []}
    all_placements = []
    discovered_daily_date = target_date
    total_c = len(countries)

    for idx, cc in enumerate(countries, start=1):
        if cancel_check and cancel_check():
            raise RuntimeError("Sweep cancelled by user.")

        cc_clean = cc.strip().upper()
        country_name = COUNTRY_NAMES.get(cc_clean, cc_clean)
        if progress_callback:
            progress_callback(idx, total_c, cc_clean, country_name, len(all_placements), f"Scanning {country_name} ({cc_clean}) for {artist_name}...")

        # 1. Sweep Daily Top Music Videos
        entries, chart_end_date = query_innertube_chart(cc_clean, chart_type="VIDEOS", period_type="DAILY", target_date=target_date)
        if chart_end_date and not discovered_daily_date:
            discovered_daily_date = chart_end_date

        chart_date_val = target_date if target_date else (chart_end_date or "Latest Daily")

        for rank_idx, item in enumerate(entries, start=1):
            if match_video_to_artist(item, target_info):
                v_id = item.get("id")
                pos = item.get("chartEntryMetadata", {}).get("currentPosition") or rank_idx
                prev_pos = item.get("chartEntryMetadata", {}).get("previousPosition")
                share_url = item.get("shareCardUrl", "")
                v_title = item.get("title", f"Video {v_id}")

                placement = {
                    "video_id": v_id,
                    "title": v_title,
                    "channel_name": item.get("channelName", ""),
                    "channel_id": item.get("externalChannelId", ""),
                    "country_code": cc_clean,
                    "country_name": country_name,
                    "chart_type": "Daily Top Music Videos",
                    "rank_position": pos,
                    "previous_position": prev_pos,
                    "status": classify_peak_rank(pos),
                    "chart_date": chart_date_val,
                    "share_card_url": share_url
                }
                all_placements.append(placement)

                if v_id not in discovered_tracks:
                    discovered_tracks[v_id] = {
                        "video_id": v_id,
                        "title": v_title,
                        "channel_name": item.get("channelName", ""),
                        "channel_id": item.get("externalChannelId", ""),
                        "share_card_url": share_url,
                        "placements": []
                    }
                discovered_tracks[v_id]["placements"].append(placement)
                print(f"  [{idx}/{total_c}] {country_name} ({cc_clean}): #{pos} in Daily Top Music Videos -> '{v_title}' ({v_id})")
                if progress_callback:
                    progress_callback(idx, total_c, cc_clean, country_name, len(all_placements), f"Hit #{pos} in {country_name} ({cc_clean}): {v_title[:28]}")

        # 2. Sweep Overall YouTube Trending (Live only, if no historical date)
        if not target_date:
            if cancel_check and cancel_check():
                raise RuntimeError("Sweep cancelled by user.")
            trending_entries, _ = query_innertube_chart(cc_clean, chart_type="TRENDING_VIDEOS")
            for t_rank, t_item in enumerate(trending_entries, start=1):
                if match_video_to_artist(t_item, target_info):
                    tv_id = t_item.get("id")
                    t_pos = t_item.get("chartEntryMetadata", {}).get("currentPosition") or t_rank
                    t_prev = t_item.get("chartEntryMetadata", {}).get("previousPosition")
                    t_share = t_item.get("shareCardUrl", "")
                    tv_title = t_item.get("title", f"Video {tv_id}")

                    t_placement = {
                        "video_id": tv_id,
                        "title": tv_title,
                        "channel_name": t_item.get("channelName", ""),
                        "channel_id": t_item.get("externalChannelId", ""),
                        "country_code": cc_clean,
                        "country_name": country_name,
                        "chart_type": "Overall YouTube Trending",
                        "rank_position": t_pos,
                        "previous_position": t_prev,
                        "status": classify_peak_rank(t_pos),
                        "chart_date": "Live Snapshot",
                        "share_card_url": t_share
                    }
                    all_placements.append(t_placement)

                    if tv_id not in discovered_tracks:
                        discovered_tracks[tv_id] = {
                            "video_id": tv_id,
                            "title": tv_title,
                            "channel_name": t_item.get("channelName", ""),
                            "channel_id": t_item.get("externalChannelId", ""),
                            "share_card_url": t_share,
                            "placements": []
                        }
                    discovered_tracks[tv_id]["placements"].append(t_placement)
                    print(f"  [{idx}/{total_c}] {country_name} ({cc_clean}): #{t_pos} in Overall Trending -> '{tv_title}' ({tv_id})")
                    if progress_callback:
                        progress_callback(idx, total_c, cc_clean, country_name, len(all_placements), f"Hit #{t_pos} in {country_name} ({cc_clean}) Live Trending")

        time.sleep(0.12)  # Guardrail against IP limits

    return discovered_tracks, all_placements, discovered_daily_date

def build_artist_catalog_dossier(target_input: str, explicit_artist: str = None,
                                  countries_input: str = "default", target_date: str = None,
                                  output_dir: str = None, run_track_dossiers: bool = False,
                                  cancel_check=None, progress_callback=None):
    """Orchestrates artist channel resolution, chart sweep, report compilation, and optional batch dossier runs."""
    pdt_zone = zoneinfo.ZoneInfo("America/Los_Angeles")
    now_pdt_obj = datetime.now(pdt_zone)
    now_pdt_str = now_pdt_obj.strftime("%Y-%m-%d %H:%M:%S %Z")
    today_pdt_str = now_pdt_obj.strftime("%Y-%m-%d")

    if cancel_check and cancel_check():
        raise RuntimeError("Sweep cancelled by user.")
    if progress_callback:
        progress_callback(0, 1, "META", "Channel Resolution", 0, f"Resolving artist channel identity for {target_input}...")

    target_info = resolve_artist_or_channel(target_input, explicit_artist=explicit_artist)
    artist_name = target_info["artist_name"]
    artist_slug = sanitize_slug(artist_name)[:40]

    if not output_dir:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidate_dir = os.path.join(project_root, "datasets", "youtube")
        base_dir = candidate_dir if os.path.isdir(candidate_dir) else "/Users/bibbler/Downloads/_Projects/Antigravity/Scraper_projects/blackpink-twitter/data/datasets/youtube"
        output_dir = os.path.join(base_dir, f"artist_{artist_slug}")
    os.makedirs(output_dir, exist_ok=True)

    # Resolve countries
    if countries_input.lower() in ["default", "key"]:
        countries_to_check = DEFAULT_KEY_MARKETS
    elif countries_input.lower() == "all":
        countries_to_check = ALL_COUNTRY_CODES
    else:
        countries_to_check = [c.strip().upper() for c in countries_input.split(",") if c.strip()]

    # Resolve date keywords
    resolved_target_date = target_date
    if target_date:
        td_clean = target_date.strip().lower()
        if td_clean in ["yesterday", "prev", "previous"]:
            yesterday_obj = now_pdt_obj - timedelta(days=1)
            resolved_target_date = yesterday_obj.strftime("%Y-%m-%d")
        elif td_clean in ["today", "latest", "now"]:
            resolved_target_date = None

    discovered_tracks, new_placements, discovered_daily_date = sweep_artist_charts(
        target_info,
        countries_to_check,
        target_date=resolved_target_date,
        cancel_check=cancel_check,
        progress_callback=progress_callback
    )

    # Non-destructive merge with existing artist_chart_rankings.json
    rankings_csv_path = os.path.join(output_dir, "artist_chart_rankings.csv")
    rankings_json_path = os.path.join(output_dir, "artist_chart_rankings.json")
    existing_placements = []
    if os.path.exists(rankings_json_path):
        try:
            with open(rankings_json_path, "r") as f:
                existing_placements = json.load(f)
        except Exception:
            existing_placements = []

    combined_map = {
        (r.get("video_id"), r.get("country_code"), r.get("chart_type"), str(r.get("chart_date"))): r
        for r in existing_placements
    }
    for r in new_placements:
        combined_map[(r.get("video_id"), r.get("country_code"), r.get("chart_type"), str(r.get("chart_date")))] = r
    all_placements = list(combined_map.values())

    # Rebuild discovered_tracks summary across merged placements
    merged_tracks = {}
    for p in all_placements:
        vid = p.get("video_id")
        if not vid:
            continue
        if vid not in merged_tracks:
            merged_tracks[vid] = {
                "video_id": vid,
                "title": p.get("title", f"Video {vid}"),
                "channel_name": p.get("channel_name", ""),
                "channel_id": p.get("channel_id", ""),
                "share_card_url": p.get("share_card_url", ""),
                "placements": []
            }
        merged_tracks[vid]["placements"].append(p)
    discovered_tracks = merged_tracks

    # Sort placements: Live Snapshot first, then descending dates, then rank ascending
    def sort_ranking_key(item):
        c_date = str(item.get("chart_date", ""))
        date_score = "9999-99-99" if c_date == "Live Snapshot" else (c_date or "0000-00-00")
        try:
            rank_score = -int(item.get("rank_position", 999))
        except (ValueError, TypeError):
            rank_score = -999
        return (date_score, rank_score)

    all_placements.sort(key=sort_ranking_key, reverse=True)

    # Save CSV & JSON
    rankings_csv_path = os.path.join(output_dir, "artist_chart_rankings.csv")
    rankings_json_path = os.path.join(output_dir, "artist_chart_rankings.json")

    with open(rankings_json_path, "w") as f:
        json.dump(all_placements, f, indent=2)

    fieldnames = [
        "video_id", "title", "channel_name", "channel_id", "country_code",
        "country_name", "chart_type", "rank_position", "previous_position",
        "status", "chart_date", "share_card_url"
    ]
    with open(rankings_csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        if all_placements:
            writer.writerows(all_placements)

    # Manifest metadata
    daily_dates = sorted(list(set(
        str(r.get("chart_date")) for r in all_placements
        if r.get("chart_date") and r.get("chart_date") not in ["Live Snapshot", "Latest Daily", "None", ""]
    )))
    has_live_trending = any(r.get("chart_type") == "Overall YouTube Trending" for r in all_placements)

    # Summary metrics per track
    tracks_summary = []
    for vid, tdata in discovered_tracks.items():
        placements = tdata["placements"]
        best_pos = min(int(p.get("rank_position", 999)) for p in placements)
        c_codes = list(set(p.get("country_code") for p in placements))
        daily_cnt = sum(1 for p in placements if p.get("chart_type") == "Daily Top Music Videos")
        trend_cnt = sum(1 for p in placements if p.get("chart_type") == "Overall YouTube Trending")
        tracks_summary.append({
            "video_id": vid,
            "title": tdata["title"],
            "channel_name": tdata["channel_name"],
            "best_rank": best_pos,
            "best_rank_status": classify_peak_rank(best_pos),
            "total_placements": len(placements),
            "unique_countries_count": len(c_codes),
            "daily_music_placements": daily_cnt,
            "trending_placements": trend_cnt,
            "share_card_url": tdata["share_card_url"]
        })

    tracks_summary.sort(key=lambda t: t["best_rank"])

    manifest = {
        "schema_version": "1.0.0",
        "artist_name": artist_name,
        "channel_name": target_info["channel_name"],
        "channel_id": target_info["channel_id"],
        "channel_url": target_info["channel_url"],
        "subscribers": target_info["subscribers"],
        "generated_at_pst": now_pdt_str,
        "target_date_scoped": resolved_target_date or "latest",
        "date_metrics": {
            "daily_chart_cycle": discovered_daily_date or "Latest Daily",
            "trending_feed_state": f"Live Snapshot ({now_pdt_str})" if has_live_trending else "Bypassed",
            "historical_cycles_collected": daily_dates
        },
        "summary": {
            "unique_tracks_charting": len(discovered_tracks),
            "total_placements_captured": len(all_placements),
            "territories_queried_count": len(countries_to_check),
            "number_one_tracks": [t["title"] for t in tracks_summary if t["best_rank"] == 1]
        },
        "tracks": tracks_summary
    }

    with open(os.path.join(output_dir, "artist_catalog_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    # Executive Markdown Report
    report_filename = f"artist_{artist_slug}_chart_intelligence_report.md"
    report_path = os.path.join(output_dir, report_filename)

    with open(report_path, "w") as f:
        f.write(f"""---
feature: YouTube Artist Global Chart Intelligence
status: Final
date: {today_pdt_str}
---

# 🎤 {artist_name} — Global YouTube Chart Intelligence Report

> **Artist / Entity:** **{artist_name}**  
> **Official Channel:** **{target_info['channel_name']}** ({target_info['subscribers']:,} Subscribers)  
> **Channel ID:** `{target_info['channel_id'] or 'Multi-Channel / Distributed'}`  
> **Channel URL:** {f"[{target_info['channel_url']}]({target_info['channel_url']})" if target_info['channel_url'] else "`N/A`"}  
> **Snapshot Timestamp:** `{now_pdt_str}`  
> **Daily Music Chart Cycle:** `{discovered_daily_date or 'Latest Active Daily Cycle'} (~24-48h YouTube calculation lag)`  
> **Trending Feed State:** `{f'Live Snapshot Captured ({now_pdt_str})' if has_live_trending else 'Bypassed'}`  
> **Territories Swept:** `{len(countries_to_check)} countries`  
> **Dataset Path:** [`{output_dir}`](file://{output_dir})  

---

## 📊 1. Artist Charting Catalog Overview ({len(discovered_tracks)} Unique Tracks Active)

| Track Title | Video ID | Peak Global Rank | Total Placements | Countries Charting | Top Status | Official Share Card |
| :--- | :---: | :---: | :---: | :---: | :--- | :---: |
""")
        if tracks_summary:
            for t in tracks_summary:
                card_link = f"[Open Card]({t['share_card_url']})" if t.get("share_card_url") else "—"
                f.write(f"| **{t['title']}** | [`{t['video_id']}`](https://www.youtube.com/watch?v={t['video_id']}) | **#{t['best_rank']}** | {t['total_placements']} | {t['unique_countries_count']} | {t['best_rank_status']} | {card_link} |\n")
        else:
            f.write(f"| *No active charting tracks found across {len(countries_to_check)} territories* | - | - | - | - | - | - |\n")

        # Section 2: Select Top Territory Highlights
        f.write(f"""
---

## 🌟 2. Select Top Territory Placements (Peak Highlights)

Curated highlight of peak placements (#1s, Top 5s, and Top 10s) across all active catalog tracks:

| Track Title | Country | Flag | Code | Surface | Rank | Chart Date | Peak Classification | Visual Asset |
| :--- | :--- | :---: | :---: | :--- | :---: | :---: | :--- | :---: |
""")
        # Filter select highlights (rank <= 10 or key markets <= 30)
        select_highlights = [p for p in all_placements if int(p.get("rank_position", 999)) <= 10 or (p.get("country_code") in DEFAULT_KEY_MARKETS and int(p.get("rank_position", 999)) <= 30)]
        select_highlights.sort(key=lambda p: (int(p.get("rank_position", 999)), p.get("title", "")))

        if select_highlights:
            for sh in select_highlights[:25]:
                flag = get_country_flag(sh['country_code'])
                pos = sh.get('rank_position', '-')
                peak_cls = classify_peak_rank(pos)
                card_link = f"[Open Card]({sh['share_card_url']})" if sh.get('share_card_url') else "—"
                f.write(f"| **{sh['title'][:35]}** | **{sh['country_name']}** | {flag} | `{sh['country_code']}` | {sh['chart_type']} | **#{pos}** | `{sh.get('chart_date', '-')}` | {peak_cls} | {card_link} |\n")
        else:
            f.write("| *No top tier placements found* | - | - | - | - | - | - | - | - |\n")

        # Section 3: Surface Breakdown
        daily_music_placements = [p for p in all_placements if p.get("chart_type") == "Daily Top Music Videos"]
        trending_placements = [p for p in all_placements if p.get("chart_type") == "Overall YouTube Trending"]

        f.write(f"""
---

## 🌍 3. Global Country Chart Matrix by Surface

### 3A. Daily Top Music Videos Chart ({len(daily_music_placements)} Placements across {len(set(p['country_code'] for p in daily_music_placements))} Countries)
> **Cycle Date:** `{discovered_daily_date or 'Latest Active Cycle'}`  
> **Calculation Basis:** Audited 24-hour YouTube music video streams, verified on-demand views, and regional sales metrics.

| Track Title | Country | Flag | Code | Rank Position | Prev Pos | Chart Date | Peak Classification | Visual Asset |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- | :---: |
""")
        if daily_music_placements:
            for dp in daily_music_placements:
                flag = get_country_flag(dp['country_code'])
                pos = dp.get('rank_position', '-')
                prev_pos = f"#{dp['previous_position']}" if dp.get('previous_position') else "—"
                peak_cls = classify_peak_rank(pos)
                card_link = f"[Open Card]({dp['share_card_url']})" if dp.get('share_card_url') else "—"
                f.write(f"| **{dp['title'][:35]}** | **{dp['country_name']}** | {flag} | `{dp['country_code']}` | **#{pos}** | {prev_pos} | `{dp.get('chart_date', '-')}` | {peak_cls} | {card_link} |\n")
        else:
            f.write("| *No Daily Music Video placements found in queried territories* | - | - | - | - | - | - | - | - |\n")

        f.write(f"""
### 3B. Overall YouTube Trending ({len(trending_placements)} Placements across {len(set(p['country_code'] for p in trending_placements))} Countries)
> **Snapshot Timestamp:** `{now_pdt_str}`  
> **Calculation Basis:** Live real-time cross-category velocity feed reflecting organic viewer growth in each country.

| Track Title | Country | Flag | Code | Rank Position | Prev Pos | Snapshot State | Peak Classification | Visual Asset |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- | :---: |
""")
        if trending_placements:
            for tp in trending_placements:
                flag = get_country_flag(tp['country_code'])
                pos = tp.get('rank_position', '-')
                prev_pos = f"#{tp['previous_position']}" if tp.get('previous_position') else "—"
                peak_cls = classify_peak_rank(pos)
                card_link = f"[Open Card]({tp['share_card_url']})" if tp.get('share_card_url') else "—"
                f.write(f"| **{tp['title'][:35]}** | **{tp['country_name']}** | {flag} | `{tp['country_code']}` | **#{pos}** | {prev_pos} | `{tp.get('chart_date', '-')}` | {peak_cls} | {card_link} |\n")
        else:
            f.write("| *Trending feed bypassed or no active placements found* | - | - | - | - | - | - | - | - |\n")

        # Section 4: Visual Asset Gallery
        f.write(f"""
---

## 🎨 4. Official YouTube Charts 9:16 Vertical Share Card Gallery (Sample)

These are official high-resolution (1080x1920) vertical JPEG graphics generated server-side by YouTube Charts analytics infrastructure:

| Track Title | Country | Flag | Code | Chart Surface | Rank Position | Official 1080x1920 Share Card Direct Link |
| :--- | :--- | :---: | :---: | :--- | :---: | :--- |
""")
        sample_cards = [p for p in all_placements if p.get("share_card_url")]
        key_cards_set = set()
        deduped_sample_cards = []
        for p in sample_cards:
            key = (p.get("video_id"), p.get("country_code"))
            if key not in key_cards_set:
                key_cards_set.add(key)
                deduped_sample_cards.append(p)

        if deduped_sample_cards:
            for sc in deduped_sample_cards[:15]:
                flag = get_country_flag(sc['country_code'])
                f.write(f"| **{sc['title'][:35]}** | **{sc['country_name']}** | {flag} | `{sc['country_code']}` | {sc.get('chart_type', 'Chart')} | **#{sc.get('rank_position', '-')}** | [Open 1080x1920 Card]({sc['share_card_url']}) |\n")
        else:
            f.write("| *No share card assets registered* | - | - | - | - | - | - |\n")

        # Section 5: Architecture
        f.write(f"""
---

## 🗂️ 5. Discrete Tracking File Architecture

The artist catalog dataset is organized into isolated and composable files:

1. **[`artist_catalog_manifest.json`](file://{os.path.join(output_dir, "artist_catalog_manifest.json")})**: Root catalog metadata linking all active tracks, peak ranks, and territory coverage.
2. **[`artist_chart_rankings.json`](file://{os.path.join(output_dir, "artist_chart_rankings.json")})** & **[`artist_chart_rankings.csv`](file://{os.path.join(output_dir, "artist_chart_rankings.csv")})**: Multi-track, multi-country placement matrix across Daily Top Music Videos and Trending.
3. **[`{report_filename}`](file://{report_path})**: Formatted executive report with track catalog matrix and high-res share card links.
""")

    print(f"\n[✔] Artist Chart Sweep Complete!")
    print(f"    - Artist Entity: {artist_name}")
    print(f"    - Unique Charting Tracks: {len(discovered_tracks)}")
    print(f"    - Total Chart Placements: {len(all_placements)}")
    print(f"    - Output Directory: {output_dir}")
    print(f"    - Executive Report: {report_path}")

    # Optional Auto-Pilot: Build Full 5-Layer Dossiers for all discovered tracks
    if run_track_dossiers and discovered_tracks:
        print(f"\n[🚀] Auto-Pilot: Generating full 5-layer video intelligence dossiers for {len(discovered_tracks)} discovered tracks...")
        for idx, (vid, tinfo) in enumerate(discovered_tracks.items(), start=1):
            print(f"\n---> [{idx}/{len(discovered_tracks)}] Generating dossier for '{tinfo['title']}' ({vid})...")
            try:
                build_dossier(
                    video_input=vid,
                    country_filter=",".join(countries_to_check) if len(countries_to_check) <= 15 else "all",
                    skip_charts=False,
                    max_comments=0
                )
            except Exception as e:
                print(f"[!] Warning: Dossier generation failed for {vid}: {e}")

    return output_dir

def main():
    parser = argparse.ArgumentParser(
        description="Batch sweep YouTube Top 100 Charts by Artist Channel ID, URL, or Name"
    )
    parser.add_argument("target", nargs="?", default=None,
                        help="Channel URL, handle (@...), Channel ID (UC...), or Artist Name")
    parser.add_argument("-c", "--channel", default=None,
                        help="Explicit Channel URL, handle (@...), or Channel ID (UC...)")
    parser.add_argument("-a", "--artist", default=None,
                        help="Explicit Artist Name or search query (e.g. 'LISA', 'Megan Thee Stallion')")
    parser.add_argument("--countries", default="default",
                        help="Comma-separated country ISO codes (e.g. 'US,GB,TH,GLOBAL') or 'all' (default: 14 key markets)")
    parser.add_argument("-d", "--date", default=None,
                        help="Historical date scope ('YYYY-MM-DD', 'yesterday', or 'latest')")
    parser.add_argument("-o", "--output-dir", default=None,
                        help="Custom output directory")
    parser.add_argument("--dossier", action="store_true",
                        help="Automatically generate full 5-layer video dossiers for all discovered charting tracks")

    args = parser.parse_args()

    target_input = args.channel or args.artist or args.target
    if not target_input:
        parser.print_help()
        sys.exit(1)

    build_artist_catalog_dossier(
        target_input=target_input,
        explicit_artist=args.artist,
        countries_input=args.countries,
        target_date=args.date,
        output_dir=args.output_dir,
        run_track_dossiers=args.dossier
    )

if __name__ == "__main__":
    main()
