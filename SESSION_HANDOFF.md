# YT//DOSSIER_ENGINE — Session Handoff & Next Steps

**Date / Timestamp:** 2026-11-02 05:35 PST  
**Status:** Complete & Operational  
**Repository:** [https://github.com/bibbler/youtube-dossier-engine](https://github.com/bibbler/youtube-dossier-engine) (`main`)  
**Active Port:** `http://localhost:8088` (Daemon Task `task-1357`)

---

## 1. Executive Summary

In this session, we resolved the root cause behind why older music videos and songs (e.g. tracks from 2025 or earlier in 2026) returned 0 chart data, implemented an automatic multi-cycle **Debut-Window Sweep**, updated the 5-Layer Dossier engine, synchronized documentation across [`README.md`](file:///Users/bibbler/Downloads/_Projects/Antigravity/Scraper_projects/youtube-dossier-engine/README.md), [`SPECS.md`](file:///Users/bibbler/Downloads/_Projects/Antigravity/Scraper_projects/youtube-dossier-engine/SPECS.md), and [`DESIGN.md`](file:///Users/bibbler/Downloads/_Projects/Antigravity/Scraper_projects/youtube-dossier-engine/DESIGN.md), refreshed all 14 track datasets with their historical chart peaks and #1 champion markets, and pushed all updates to GitHub.

---

## 2. Key Accomplishments & Technical Fixes

### 2.1 InnerTube Protocol Correction for Historical Charts
- **The Bug:** `query_innertube_chart()` previously sent `chart_params_date={target_date}` and hyphenated date formats (`YYYY-MM-DD`). YouTube's InnerTube API silently ignored `chart_params_date`, defaulted to today's active cycle (where older tracks were absent), and threw `HTTP 400` on hyphens. Furthermore, omitting `chart_params_country_code` on global queries defaulted to US domestic data.
- **The Fix:**
  - Query parameter strictly enforced as `chart_params_end_date={YYYYMMDD}` (compact 8-digit string without hyphens).
  - Explicit `chart_params_country_code=global` passed for Worldwide/Global queries.
  - Normalization of `UK` to `GB` in query parameters and client context.
  - Full support for both `period_type="DAILY"` and `period_type="WEEKLY"`.

### 2.2 Automatic Debut-Window Lookup Engine
- Implemented `first_thursday_on_or_after(date_str)` to automatically identify YouTube Charts' official Thursday-ending weekly cycles for any release date.
- When sweeping an older video (`hours_since_release > 72h`), or when `--date release` / `Debut / Release Day` is selected, `sweep_country_charts` automatically evaluates the full **Debut Window**:
  1. **Cycle 1:** `upload_date` (Daily Top Music Videos)
  2. **Cycle 2:** `upload_date + 1 day` (Daily Top Music Videos momentum peak)
  3. **Cycle 3:** First Thursday on or after `upload_date` (Weekly Top Music Videos)
- Videos older than 7 days automatically skip `Overall YouTube Trending` checks, preserving speed and avoiding redundant calls.

### 2.3 Enriched Multi-Cycle Deduplication & Peak Classification
- Rankings are deduplicated and merged non-destructively on `(country_code, chart_type, str(chart_date))`.
- The engine calculates `all_time_best_rank` and `reached_number_one` across all recorded cycles, dynamically identifying Current #1 Champions vs. Past #1 Peaks.

---

## 3. Hydrated Track & Artist Catalog

All 14 track dossiers are populated with real chart data and official 9:16 vertical share cards:

| Track / Video Title | Video ID | Placements | Charting Countries | Key Peak Placements | Official #1 Champions |
| :--- | :---: | :---: | :---: | :--- | :--- |
| **LISA - SaWaDiKa (Official Music Video)** | `FyS5dAywkEo` | **165** | 33 | 33x #1s across TH, US, GB, BR, FR, DE, etc. | 33 Countries |
| **JISOO - ADDICTED (Official MV)** | `Pksr9T8m_aA` | **99** | 2 | HK #1, SG #1, Global #2 | 🇭🇰 Hong Kong, 🇸🇬 Singapore |
| **LISA - Tarantino (Official Music Video)** | `-5ZXrO_lYSA` | **70** | 54 | 54 markets charting, US #12, GB #12, TH #2 | — |
| **JENNIE - FALLEN ANGEL (Official Video)** | `s466YCiHfKw` | **38** | 14 | KR #1 (Daily + Weekly), Global #2, AU #2, CA #2, GB #3, US #5 | 🇰🇷 South Korea |
| **JISOO X ZAYN - EYES CLOSED (OFFICIAL MV)** | `EN1tMeXQii0` | **36** | 12 | Global #1, KR #2, ID #3, CA #3, US #4, GB #4, AU #4 | 🌐 Global / Worldwide |
| **LISA - DREAM feat. Kentaro Sakaguchi** | `FMX98ROVRCE` | **32** | 12 | AU #1, CA #1, Global #2, US #2, ID #4, GB #5, DE #5, KR #6 | 🇦🇺 Australia, 🇨🇦 Canada |
| **ROSÉ - new trick (OFFICIAL MUSIC VIDEO)** | `Lufa9QAFFeY` | **31** | 14 | Global #1, KR #1, AU #1, PH #1, GB #2, CA #2, TH #4, FR #4 | 🌐 Global, 🇰🇷 South Korea, 🇦🇺 Australia, 🇵🇭 Philippines |
| **LISA - SaWaDiKa (Dance Performance)** | `J77i-E_0JWg` | **30** | 14 | TH #2, AU #2, CA #2, Global #5, KR #10, PH #10, GB #16 | — |
| **LISA - BORN AGAIN feat. Doja Cat & RAYE** | `kbEC-AGr9n0` | **23** | 12 | Global #1, GB #1, AU #2, CA #2, KR #3, ID #3, DE #4, US #5 | 🌐 Global / Worldwide, 🇬🇧 United Kingdom |
| **LISA - WHEN I'M WITH YOU feat. Tyla** | `wM--5vGraQQ` | **20** | 9 | AU #4, Global #8, CA #8, US #25, KR #25, GB #29, DE #40 | — |
| **LISA - SaWaDiKa (TukTuk Radio Special)** | `W3mlJNg0pzE` | **15** | 10 | TH #9, AU #12, CA #15, GB #37, Global #44, KR #45 | — |
| **LISA - FUTW (Vixi Solo Version)** | `r5VRqWkFpEQ` | **9** | 9 | Global Weekly #14, AU #12, CA #22, KR #23, GB #28, US #40 | — |
| **LISA - V12 (Lyric Video)** | `mbYFoU3-B7Y` | **6** | 5 | TH #39 (Day 1) → #74 (Day 2), Global #77, AU #91, CA #94 | — |
| **Megan Thee Stallion - Thin Ice** | `9ofUM-_3uQ4` | **3** | 1 | US #1 Champion | 🇺🇸 United States |

---

## 4. Active Infrastructure & Endpoints

- **Live Web Console**: [http://localhost:8088](http://localhost:8088)
- **Standalone Dashboard**: [`youtube_dossier_console.html`](file:///Users/bibbler/Downloads/_Projects/Antigravity/Scraper_projects/youtube-dossier-engine/dashboards/youtube_dossier_console.html)
- **Server Script**: [`youtube_dossier_web_server.py`](file:///Users/bibbler/Downloads/_Projects/Antigravity/Scraper_projects/youtube-dossier-engine/scripts/youtube_dossier_web_server.py)
- **Key CLI Commands**:
  ```bash
  # Start Web Server
  python3 scripts/youtube_dossier_web_server.py --port 8088 --host 0.0.0.0

  # Single Track 5-Layer Dossier with Automatic Debut Window
  python3 scripts/build_youtube_track_dossier.py <VIDEO_ID> --countries US,GB,TH,KR,JP,BR,FR,DE,AU,CA,ID,PH,MX,GLOBAL

  # Zero-Video-ID Artist Sweep
  python3 scripts/sweep_youtube_artist_charts.py "@LISAOfficialVEVO" --artist "LISA"
  ```

---

## 5. Next Session Roadmap

1. **Automated Scheduled Ingestion / Polling**:
   - Set up scheduled cron triggers (via `/schedule`) to check daily finalized YouTube Chart cycles (~24-48h lag) and auto-sync newly debuting tracks.
2. **Channel Catalog Expansion**:
   - Process shortlisted tracks from other official channels (`@BLACKPINK`, `@JENNIE`, `@ROSÉ`, `@JISOO`) directly via the Catalog Lookup Builder.
3. **Advanced Export Formats**:
   - Add automated PDF summary reporting (via `webpage-pdf-exporter`) to generate print-ready executive dossiers.
4. **Remote Access / Cloud Deployment**:
   - Configure Cloud Run or Cloudflare Tunnel routing for secure remote team access beyond local LAN.
