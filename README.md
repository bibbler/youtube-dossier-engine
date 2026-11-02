# YT//DOSSIER_ENGINE — Global YouTube Charts & Velocity Intelligence Engine

**Zero-Token Multi-Country YouTube Track Dossier & Artist Top 100 Chart Sweep Engine with a Swiss-Industrial High-Density Web Console (`v1.2.0`).**

`YT//DOSSIER_ENGINE` queries YouTube's internal **`InnerTube v1` (`FEmusic_analytics`)** endpoint and `yt-dlp` metadata extractors to compile **5-Layer Track Intelligence Dossiers** and **Zero-Video-ID Artist Catalog Sweeps** across **86 sovereign countries + Global**, complete with server-rendered **1080×1920 (9:16) Official YouTube Share Cards**, local disk caching, named ZIP archive exports, and an interactive cross-track comparison workspace.

---

## ✨ Key Capabilities

1. **5-Layer Single-Track Intelligence Dossier (`build_youtube_track_dossier.py`):**
   - **Layer 1 (`video_metadata.json` / `.csv`):** Upload date, UTC release timestamp, resolution, FPS, audio/video codecs, subscriber count, description tags, and regex-extracted lyrics.
   - **Layer 2 (`video_telemetry_snapshot.json` / `.csv` + `video_telemetry_history.csv`):** Cumulative views, likes, comments, `views_per_hour`, `likes_per_hour`, `like_to_view_ratio_pct`, `hours_since_release`, and dual-axis **Virality Tier** (`Mega-Viral`, `High-Velocity`, `Viral`, `Moderate`, `Emerging`).
   - **Layer 3 (`country_chart_rankings.json` / `.csv`):** Multi-country placements separated across **Daily Top Music Videos (`VIDEOS`)** and **Overall YouTube Trending (`TRENDING_VIDEOS`)**, with composite deduplication (`country_code`, `chart_type`, `chart_date`) and historical **`#1` Peak Preservation** (`all_time_best_rank`, `reached_number_one`, `previous_position`).
   - **Layer 4 (`top_comments_ranked.json` / `.csv`):** Top-engaged community comments sorted strictly by upvote count descending (`comment_sort=top;max_comments=60,60,0,0`), complete with `YYYY-MM-DD HH:MM PST` timestamps and direct YouTube comment permalinks (`&lc=`).
   - **Layer 5 (`share_cards_registry.json` / `.csv` + `share_cards_cache/`):** Official **1080×1920 (9:16)** vertical YouTube Charts share card JPEGs decoded from Base64 Protobuf `?r=` tokens, cached locally on disk, and exportable as named `.zip` bundles.

2. **Zero-Video-ID Artist / Channel Top 100 Sweep (`sweep_youtube_artist_charts.py`):**
   - Accepts an artist name (`LISA`), YouTube handle (`@LISAOfficialVEVO`), channel URL, or `UC...` channel ID.
   - Automatically resolves official + VEVO/Label alias identities and sweeps Top 100 charts across 14 priority markets (~2s) or all 86 countries (~11s) **without requiring any video IDs upfront**.

3. **Swiss-Industrial Web Console & Multi-Threaded API Server (`youtube_dossier_web_server.py`):**
   - **URL Query String Routing (`history.pushState` / `popstate`):** Full browser Back/Forward navigation across views (`?view=track|artist|compare`), datasets (`&id=...`), tabs (`&tab=...`), and comparison layouts (`&layout=columns|rows`).
   - **Cross-Track Comparison Matrix (`⚖ COMPARE`):** Sortable leaderboard across all captured tracks plus a **Side-by-Side Columns (`▥`) vs. Stacked Strips (`☰`)** toggle comparing all 6 Overview KPI blocks row-for-row.
   - **9:16 Share Card Studio & Named ZIP Exporter:** Select individual or all 1080×1920 vertical share cards, cache them to disk (`share_cards_cache/`), and export named `.zip` archives (`<Entity>__YouTube_Charts_9x16_ShareCards__<Surface>__<PeakStat>__<Scope>.zip`).
   - **Live Sweep Progress Monitor & Abort Control:** Real-time progress bar (`#sweep-monitor-bar`) polling `/api/sweep/status` every 450ms with instant `■ STOP` / `■ ABORT SWEEP` cancellation and 3-layer duplicate submission prevention.

---

## 📁 Project Structure

```text
youtube-dossier-engine/
├── README.md                              # Project overview, CLI & Web Console guide
├── SPECS.md                               # InnerTube v1 protocol, 5-Layer schema, Virality Tier & URL specs
├── DESIGN.md                              # Swiss-Industrial UI design system, tokens & responsive architecture
├── AGENTS.md                              # Universal Agent Access workspace instructions
├── scripts/
│   ├── build_youtube_track_dossier.py     # Single-Track 5-Layer Dossier CLI & Engine
│   ├── sweep_youtube_artist_charts.py     # Artist / Channel Top 100 Discovery CLI & Engine
│   └── youtube_dossier_web_server.py      # Multi-threaded HTTP API Server & Standalone HTML Compiler
├── dashboards/
│   └── youtube_dossier_console.html       # Compiled zero-dependency standalone console (with preloaded JSON)
└── datasets/
    └── youtube/                           # 5-Layer Track Dossiers & Artist Sweep datasets
        ├── lisa_sawadika_FyS5dAywkEo/
        ├── lisa_tarantino_official_music_video_-5ZXrO_lYSA/
        ├── jisoo_x_zayn_eyes_closed_official_mv_EN1tMeXQii0/
        ├── rosé_new_trick_official_music_video_Lufa9QAFFeY/
        ├── jennie_fallen_angel_official_video_s466YCiHfKw/
        ├── megan_thee_stallion_thin_ice_tina_tuesda_9ofUM-_3uQ4/
        ├── jisoo_addicted_official_mv_Pksr9T8m_aA/
        ├── artist_lisa/
        └── artist_megan_thee_stallion/
```

---

## 🚀 Quick Start

### 1. Launch the Live Web Console & API Server
```bash
python3 scripts/youtube_dossier_web_server.py --port 8088 --host 0.0.0.0
```
- **Local Web Console:** `http://localhost:8088`
- **Compare Tracks Matrix:** `http://localhost:8088/?view=compare&layout=columns`
- **Standalone Offline File:** `dashboards/youtube_dossier_console.html`

### 2. Run a Single-Track 5-Layer Dossier via CLI
```bash
# Fast 14-market priority sweep (~2s, comments skipped by default)
python3 scripts/build_youtube_track_dossier.py "https://www.youtube.com/watch?v=-5ZXrO_lYSA" \
  --countries US,GB,TH,KR,JP,BR,FR,DE,AU,CA,ID,PH,MX,GLOBAL

# Full 86-country + Global sweep with Top 20 Engaged Community Comments
python3 scripts/build_youtube_track_dossier.py FyS5dAywkEo --countries all --with-comments

# Historical debut / release-day chart cycle lookup
python3 scripts/build_youtube_track_dossier.py -5ZXrO_lYSA --date release
```

### 3. Run an Artist / Channel Top 100 Sweep (Zero Video IDs Needed)
```bash
# By artist channel handle or URL across 14 priority markets
python3 scripts/sweep_youtube_artist_charts.py "@LISAOfficialVEVO" --artist "LISA"

# Full 86-country sweep + auto-compile 5-Layer Dossiers for every discovered track
python3 scripts/sweep_youtube_artist_charts.py "https://www.youtube.com/@MeganTheeStallion" \
  --countries all --dossier
```

---

## 📈 How Virality Tier is Calculated

The engine evaluates **both cumulative view scale (`view_count`) and real-time hourly velocity (`views_per_hour = view_count / max(1.0, hours_since_release)`)** so explosive new releases and established blockbusters are accurately classified:

| Virality Tier | Cumulative Views Threshold | **OR** Hourly Velocity Threshold (`views_per_hour`) | Typical Profile |
| :--- | :--- | :--- | :--- |
| **`Mega-Viral`** | `>= 50,000,000 views` | `>= 250,000 views/hr` (~6M+ views/day) | Global tentpole debuts & 50M+ smash hits |
| **`High-Velocity`** | `>= 10,000,000 views` | `>= 50,000 views/hr` (~1.2M+ views/day) | Rapidly breaking global singles & 10M–50M MVs |
| **`Viral`** | `>= 1,000,000 views` | `>= 10,000 views/hr` (~240K+ views/day) | Regional chart entries & 1M–10M tracks |
| **`Moderate`** | `>= 100,000 views` | `>= 1,000 views/hr` | Niche or catalog tracks |
| **`Emerging`** | `< 100,000 views` | `< 1,000 views/hr` | Newly uploaded or developing releases |

---

## 📦 9:16 Share Card Caching & Named ZIP Export

Every YouTube Charts placement includes a Base64-encoded Protobuf `?r=` URL (`https://charts.youtube.com/share?...`) that renders an official **1080×1920 (9:16)** vertical share image.

- **Local Disk Cache (`share_cards_cache/`):** When you click **`⚡ CACHE ALL TO DISK`** or export a ZIP in `04 // 9:16 SHARE CARD STUDIO`, the server fetches all 1080×1920 JPEGs concurrently (8 worker threads) and caches them inside `<dataset_folder>/share_cards_cache/`. Subsequent views serve directly from local disk (`✓ DISK CACHED`).
- **Descriptive Individual Card Filenames:**
  `<EntitySlug>__<CountryCode>_<CountryName>__Rank<NN>_<Champion|PastNum1|PeakN>__<DailyTopMV|LiveTrending>__<ChartDate>_9x16.jpg`
  *(Example: `LISA_SaWaDiKa_Official_M__TH_Thailand__Rank01_Champion__DailyTopMV__2026_09_05_9x16.jpg`)*
- **Descriptive ZIP Archive Filenames:**
  `<EntitySlug>__YouTube_Charts_9x16_ShareCards__<SurfaceType>__<PeakStat>__<All|Selected>_<Count>cards.zip`
  *(Example: `LISA_SaWaDiKa_Official_Music_Video__YouTube_Charts_9x16_ShareCards__DailyMV_and_Trending__Peak1_65xNum1Champions__All_86cards.zip`)*
