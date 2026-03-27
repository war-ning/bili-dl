# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Project

```bash
# Install dependencies
pip install -r requirements.txt

# Run the tool
python3 main.py
```

No build step. No test suite. Runtime data (config.json, history.json) lives in `data/`.

## Architecture

Four-layer design: **API → Core → UI → Utils**, all orchestrated by `main.py`.

**Async/Sync bridge is the critical pattern**: The UI layer is fully synchronous (questionary doesn't work inside asyncio.run). All async operations (API calls, downloads) go through `utils/async_helper.py`'s `run_async()`, which maintains a persistent event loop. Never use `asyncio.run()` directly — it conflicts with questionary.

### API Layer (`api/`)
Wraps `bilibili-api-python`. Every function calls `client.throttle()` first for rate limiting. Credential is passed via constructor (`User(uid, credential=...)`, `Video(bvid, credential=...)`), never as a method argument — this is a bilibili-api-python convention.

### Core Layer (`core/`)
- **downloader.py**: `BatchDownloader` uses `asyncio.Semaphore` for concurrency + retry logic (2 retries, exponential backoff for network errors). Supports cancellation via `_cancelled` flag.
- **Video download flow**: DASH streams downloaded separately → PyAV remux merge (no re-encoding) → MP4. Temp files in `.tmp/<bvid>/`.
- **Audio flow**: Download audio stream → `convert_to_mp3()` returns actual output Path (may be .m4a if MP3 codec unavailable) → write ID3 tags via mutagen.
- **merger.py / audio_converter.py**: On failure, clean up partial output files before raising.

### UI Layer (`ui/`)
All views are synchronous functions. Use `questionary` for input, `rich` for display. `app.py` wraps each menu action in try-except so errors return to main menu instead of crashing.

### Key Data Structures (`models.py`)
`DownloadTask` tracks a single download's lifecycle (status, progress, speed, file_path). `VideoInfo.cid` is lazily fetched — `_get_cid()` in downloader.py handles the lookup with empty-check protection.

## Important Conventions

- All file operations set mtime to the video's publish timestamp (`set_file_mtime`).
- File paths: `<download_dir>/<UP主名>/<标题>_<BV号>.<ext>`, sanitized by `utils/filename.py`.
- History uses atomic JSON writes (write to .tmp then `os.replace`).
- `bilibili-api-python` registers an atexit callback that needs the event loop alive — `async_helper.cleanup()` handles this before closing the loop.
- Comments/UI strings are in Chinese; code identifiers are in English.
