# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Project

```bash
# Install dependencies
pip install -r requirements.txt

# Run the tool
python3 main.py

# Build standalone executable
pip install pyinstaller
python3 build.py
```

No test suite. Runtime data (config.json, history.json) lives in `data/`.

## Architecture

Four-layer design: **API → Core → UI → Utils**, all orchestrated by `main.py`.

**Async/Sync bridge is the critical pattern**: The UI layer is fully synchronous (questionary doesn't work inside asyncio.run). All async operations (API calls, downloads) go through `utils/async_helper.py`'s `run_async()`, which maintains a persistent event loop. Never use `asyncio.run()` directly — it conflicts with questionary.

### API Layer (`api/`)
Wraps `bilibili-api-python`. Every function calls `client.throttle()` first for rate limiting. Credential is passed via constructor (`User(uid, credential=...)`, `Video(bvid, credential=...)`), never as a method argument — this is a bilibili-api-python convention.

`get_audio_stream()` has a durl fallback: when DASH audio is unavailable (some older videos), it returns the durl (FLV/MP4 merged) URL with `type="durl"` marker for downstream extraction.

### Core Layer (`core/`)
- **downloader.py**: `BatchDownloader` uses `asyncio.Semaphore` for concurrency + retry logic (2 retries, exponential backoff). Supports cancellation via `_cancelled` flag.
- **Multi-page videos**: `_download_video`/`_download_audio` call `_get_pages()` to detect page count. Single P → direct download. Multi P → loop through pages, each saved as `标题_P1_分P名_BV号.ext`. The `is_single` parameter controls whether `_download_single_video`/`_download_single_audio` sets task completion status (only in single P mode; multi P sets it after the loop).
- **Video download flow**: DASH streams downloaded separately → PyAV remux merge → MP4. Fallback: durl (FLV) direct download.
- **Audio flow**: DASH audio → convert_to_mp3() or remux_to_m4a(). durl fallback → extract_audio() first, then convert/remux. `convert_to_mp3()` returns actual Path (may be .m4a if MP3 codec unavailable).
- **Duration check**: After download, `_check_duration()` compares actual vs expected duration. Only runs for single P (multi P would false-positive since each P is shorter than total).
- **CPU-bound ops in thread pool**: `merger.merge()`, `convert_to_mp3()`, `cover_proc.process()`, `write_id3_tags()` all use `asyncio.to_thread()` to avoid blocking the event loop.
- **merger.py / audio_converter.py**: PyAV 17+ compatible — uses `add_stream(codec_name)` + manual parameter copy instead of deprecated `template=`. On failure, clean up partial output files before raising.

### UI Layer (`ui/`)
All views are synchronous functions. Use `questionary` for input, `rich` for display. Navigation supports "back" at every step — functions return `"back"` string to signal going to previous step, `None` for main menu. `app.py` orchestrates via `_handle_search` → `_handle_up_download` → `_handle_download` chain.

Download progress view has built-in retry: failed tasks can be retried immediately without going to history. Uses `record_history` flag to prevent duplicate history entries on retry.

### Key Data Structures (`models.py`)
`DownloadTask` tracks a single download's lifecycle (status, progress, speed, file_path). For multi-page downloads, file_path contains semicolon-separated paths of all pages.

## Important Conventions

- All file operations set mtime to the video's publish timestamp (`set_file_mtime`).
- File paths: `<download_dir>/<UP主名>/<template>.<ext>`, sanitized by `utils/filename.py`. Template configurable via `AppConfig.filename_template`.
- History uses atomic JSON writes (write to .tmp then `os.replace`).
- `bilibili-api-python` registers an atexit callback that needs the event loop alive — `async_helper.cleanup()` handles this before closing the loop.
- Charge video detection uses `is_charging_arc` and `is_charge_plus` fields from API (not `is_pay` which is too broad).
- Comments/UI strings are in Chinese; code identifiers are in English.
