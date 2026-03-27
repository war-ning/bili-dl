"""下载引擎：流式下载 + 并发调度 + 任务分发"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Callable, Optional

import httpx

from ..api.client import BiliClient
from ..api.video import get_audio_stream, get_best_streams, get_video_pages
from ..exceptions import BiliDLError
from ..models import (
    AppConfig,
    CoverFillMode,
    DownloadStatus,
    DownloadTask,
    DownloadType,
)
from ..utils.filename import build_file_path
from ..utils.time_utils import set_file_mtime, timestamp_to_str
from .audio_converter import AudioConverter
from .cover_processor import CoverProcessor
from .history import DownloadHistory
from .merger import VideoMerger

DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com",
}

RETRYABLE_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
    ConnectionError,
    OSError,
)

MAX_RETRIES = 2
RETRY_DELAYS = [2, 4]


async def stream_download(
    url: str,
    output_path: Path,
    on_progress: Optional[Callable[[int, int, float], None]] = None,
    headers: Optional[dict] = None,
) -> int:
    """流式下载单个文件，返回文件大小"""
    dl_headers = {**DOWNLOAD_HEADERS, **(headers or {})}
    output_path.parent.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    start_time = time.monotonic()

    async with httpx.AsyncClient(
        headers=dl_headers,
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, read=120.0),
    ) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))

            with open(output_path, "wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    f.write(chunk)
                    downloaded += len(chunk)
                    elapsed = time.monotonic() - start_time
                    speed = downloaded / elapsed if elapsed > 0 else 0
                    if on_progress:
                        on_progress(downloaded, total, speed)

    return downloaded


async def _get_pages(client: BiliClient, bvid: str) -> list[dict]:
    """获取视频所有分P信息"""
    pages = await get_video_pages(client, bvid)
    if not pages:
        raise BiliDLError(f"无法获取视频分P信息: {bvid}")
    return pages


def _check_duration(file_path: Path, expected_seconds: int) -> str | None:
    """校验下载文件的实际时长与预期时长，返回警告信息或 None"""
    if expected_seconds <= 0:
        return None
    try:
        import av as _av
        with _av.open(str(file_path)) as container:
            actual = container.duration / 1_000_000 if container.duration else 0
        if actual <= 0:
            return None
        if actual < expected_seconds * 0.6:
            from ..utils.formatter import format_duration
            return (
                f"实际时长 {format_duration(int(actual))} 远短于预期 "
                f"{format_duration(expected_seconds)}，可能是充电视频的免费预览"
            )
    except Exception:
        pass
    return None


class BatchDownloader:
    """批量下载调度器"""

    def __init__(
        self,
        config: AppConfig,
        client: BiliClient,
        history: DownloadHistory,
    ):
        self._config = config
        self._client = client
        self._history = history
        self._semaphore = asyncio.Semaphore(config.max_concurrent)
        self._merger = VideoMerger()
        self._audio_conv = AudioConverter()
        self._cover_proc = CoverProcessor()
        self._download_dir = Path(config.download_dir)
        self._filename_template = config.filename_template or "{title}_{bvid}"
        self._cancelled = False

    def _build_path(self, vi, ext: str, suffix: str = "") -> Path:
        """统一构建输出路径"""
        date = timestamp_to_str(vi.publish_time, "%Y-%m-%d") if vi.publish_time else ""
        title = vi.title
        if suffix:
            title = f"{vi.title}_{suffix}"
        return build_file_path(
            self._download_dir, vi.author_name, title, vi.bvid, ext,
            template=self._filename_template, date=date,
        )

    def cancel(self) -> None:
        self._cancelled = True

    async def execute_task(
        self,
        task: DownloadTask,
        on_progress: Optional[Callable[[DownloadTask], None]] = None,
        record_history: bool = True,
    ) -> DownloadTask:
        """执行单个下载任务，带重试逻辑"""
        async with self._semaphore:
            if self._cancelled:
                task.status = DownloadStatus.SKIPPED
                task.error_msg = "用户取消"
                if record_history:
                    self._history.add_record(task)
                if on_progress:
                    on_progress(task)
                return task

            for attempt in range(MAX_RETRIES + 1):
                try:
                    task.status = DownloadStatus.DOWNLOADING
                    task.progress = 0.0
                    task.error_msg = ""
                    if on_progress:
                        on_progress(task)

                    match task.download_type:
                        case DownloadType.VIDEO:
                            await self._download_video(task, on_progress)
                        case DownloadType.AUDIO:
                            await self._download_audio(task, on_progress, convert_mp3=True)
                        case DownloadType.AUDIO_FAST:
                            await self._download_audio(task, on_progress, convert_mp3=False)
                        case DownloadType.COVER | DownloadType.COVER_SQUARE:
                            await self._download_cover(task, on_progress)

                    break

                except RETRYABLE_EXCEPTIONS as e:
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(RETRY_DELAYS[attempt])
                        continue
                    task.status = DownloadStatus.FAILED
                    task.error_msg = f"{type(e).__name__}: {e} (重试{MAX_RETRIES}次后失败)"

                except Exception as e:
                    task.status = DownloadStatus.FAILED
                    task.error_msg = f"{type(e).__name__}: {e}"
                    break

            if record_history:
                self._history.add_record(task)
            if on_progress:
                on_progress(task)
            return task

    async def execute_batch(
        self,
        tasks: list[DownloadTask],
        on_task_update: Optional[Callable[[DownloadTask, int, int], None]] = None,
        record_history: bool = True,
    ) -> list[DownloadTask]:
        """批量执行下载任务"""
        if not tasks:
            return []

        total = len(tasks)
        completed_count = 0
        self._cancelled = False

        async def run_one(task: DownloadTask) -> DownloadTask:
            nonlocal completed_count

            def progress_cb(t: DownloadTask) -> None:
                if on_task_update:
                    on_task_update(t, completed_count, total)

            result = await self.execute_task(task, on_progress=progress_cb, record_history=record_history)
            completed_count += 1
            if on_task_update:
                on_task_update(result, completed_count, total)
            return result

        results = await asyncio.gather(
            *(run_one(t) for t in tasks),
            return_exceptions=False,
        )

        return list(results)

    # ─── 视频下载 ───

    async def _download_video(
        self,
        task: DownloadTask,
        on_progress: Optional[Callable[[DownloadTask], None]],
    ) -> None:
        """下载视频，支持多分P"""
        vi = task.video_info

        pages = await _get_pages(self._client, vi.bvid)

        if len(pages) == 1:
            # 单P：直接下载
            cid = pages[0]["cid"]
            output_path = self._build_path(vi, ".mp4")
            await self._download_single_video(task, vi, cid, output_path, on_progress, 0.0, 1.0, is_single=True)
        else:
            # 多P：逐P下载，分别保存
            output_paths = []
            try:
                for idx, page in enumerate(pages):
                    cid = page["cid"]
                    part_name = page.get("part", f"P{page['page']}")
                    suffix = f"P{page['page']}_{part_name}"
                    output_path = self._build_path(vi, ".mp4", suffix=suffix)

                    p_start = idx / len(pages)
                    p_end = (idx + 1) / len(pages)
                    await self._download_single_video(task, vi, cid, output_path, on_progress, p_start, p_end, is_single=False)
                    output_paths.append(str(output_path))
            except Exception:
                # 部分分P已下载，记录已完成的路径
                if output_paths:
                    task.file_path = "; ".join(output_paths)
                    task.error_msg = f"分P {len(output_paths)+1}/{len(pages)} 下载失败，已完成 {len(output_paths)} 个"
                raise

            task.status = DownloadStatus.COMPLETED
            task.file_path = "; ".join(output_paths)
            task.file_size = sum(Path(p).stat().st_size for p in output_paths if Path(p).exists())
            task.progress = 1.0
            task.error_msg = f"共 {len(pages)} 个分P"

    async def _download_single_video(
        self,
        task: DownloadTask,
        vi,
        cid: int,
        output_path: Path,
        on_progress: Optional[Callable[[DownloadTask], None]],
        progress_start: float,
        progress_end: float,
        is_single: bool = True,
    ) -> None:
        """下载单个分P的视频"""
        video_stream, audio_stream = await get_best_streams(
            self._client, vi.bvid, cid
        )

        if not video_stream:
            raise BiliDLError(f"无法获取视频流 (cid={cid})")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_dir = self._download_dir / ".tmp" / f"{vi.bvid}_{cid}_video"
        temp_dir.mkdir(parents=True, exist_ok=True)

        video_tmp = temp_dir / f"{vi.bvid}_v.m4s"
        audio_tmp = temp_dir / f"{vi.bvid}_a.m4s"

        progress_range = progress_end - progress_start

        try:
            if video_stream.get("type") == "flv":
                def flv_progress(downloaded: int, total: int, speed: float) -> None:
                    p = (downloaded / total) if total > 0 else 0
                    task.progress = progress_start + p * progress_range
                    task.speed = speed
                    if on_progress:
                        on_progress(task)

                await stream_download(video_stream["url"], output_path, flv_progress)
            else:
                async def dl_video() -> None:
                    def vp(downloaded: int, total: int, speed: float) -> None:
                        p = (downloaded / total * 0.45) if total > 0 else 0
                        task.progress = progress_start + p * progress_range
                        task.speed = speed
                        if on_progress:
                            on_progress(task)

                    await stream_download(video_stream["url"], video_tmp, vp)

                async def dl_audio() -> None:
                    if not audio_stream:
                        return

                    def ap(downloaded: int, total: int, speed: float) -> None:
                        p = (downloaded / total * 0.45) if total > 0 else 0
                        task.progress = progress_start + (0.45 + p) * progress_range
                        if on_progress:
                            on_progress(task)

                    await stream_download(audio_stream["url"], audio_tmp, ap)

                await asyncio.gather(dl_video(), dl_audio())

                task.progress = progress_start + 0.9 * progress_range
                if on_progress:
                    on_progress(task)

                if audio_stream and audio_tmp.exists():
                    await asyncio.to_thread(
                        self._merger.merge, video_tmp, audio_tmp, output_path
                    )
                else:
                    video_tmp.rename(output_path)

            set_file_mtime(output_path, vi.publish_time)

            # 单P：设置完成状态 + 校验时长
            # 多P：由外层统一设置，不校验（每P时长 != 总时长）
            if is_single:
                warn = await asyncio.to_thread(_check_duration, output_path, vi.duration)
                task.status = DownloadStatus.COMPLETED
                task.file_path = str(output_path)
                task.file_size = output_path.stat().st_size
                task.progress = 1.0
                if warn:
                    task.error_msg = warn

        except Exception:
            if output_path.exists() and task.status != DownloadStatus.COMPLETED:
                output_path.unlink(missing_ok=True)
            raise
        finally:
            for f in [video_tmp, audio_tmp]:
                if f.exists():
                    f.unlink(missing_ok=True)
            if temp_dir.exists():
                try:
                    temp_dir.rmdir()
                except OSError:
                    pass

    # ─── 音频下载 ───

    async def _download_audio(
        self,
        task: DownloadTask,
        on_progress: Optional[Callable[[DownloadTask], None]],
        convert_mp3: bool = True,
    ) -> None:
        """下载音频，支持多分P"""
        vi = task.video_info

        pages = await _get_pages(self._client, vi.bvid)

        if len(pages) == 1:
            cid = pages[0]["cid"]
            target_ext = ".mp3" if convert_mp3 else ".m4a"
            output_path = self._build_path(vi, target_ext)
            await self._download_single_audio(task, vi, cid, output_path, on_progress, convert_mp3, 0.0, 1.0, is_single=True)
        else:
            output_paths = []
            try:
                for idx, page in enumerate(pages):
                    cid = page["cid"]
                    part_name = page.get("part", f"P{page['page']}")
                    suffix = f"P{page['page']}_{part_name}"
                    target_ext = ".mp3" if convert_mp3 else ".m4a"
                    output_path = self._build_path(vi, target_ext, suffix=suffix)

                    p_start = idx / len(pages)
                    p_end = (idx + 1) / len(pages)
                    await self._download_single_audio(task, vi, cid, output_path, on_progress, convert_mp3, p_start, p_end, is_single=False)
                    output_paths.append(str(output_path))
            except Exception:
                if output_paths:
                    task.file_path = "; ".join(output_paths)
                    task.error_msg = f"分P {len(output_paths)+1}/{len(pages)} 下载失败，已完成 {len(output_paths)} 个"
                raise

            task.status = DownloadStatus.COMPLETED
            task.file_path = "; ".join(output_paths)
            task.file_size = sum(Path(p).stat().st_size for p in output_paths if Path(p).exists())
            task.progress = 1.0
            task.error_msg = f"共 {len(pages)} 个分P"

    async def _download_single_audio(
        self,
        task: DownloadTask,
        vi,
        cid: int,
        output_path: Path,
        on_progress: Optional[Callable[[DownloadTask], None]],
        convert_mp3: bool,
        progress_start: float,
        progress_end: float,
        is_single: bool = True,
    ) -> None:
        """下载单个分P的音频"""
        audio_stream = await get_audio_stream(self._client, vi.bvid, cid)
        if not audio_stream:
            raise BiliDLError(f"无法获取音频流 (cid={cid})")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_dir = self._download_dir / ".tmp" / f"{vi.bvid}_{cid}_audio"
        temp_dir.mkdir(parents=True, exist_ok=True)
        audio_tmp = temp_dir / f"{vi.bvid}_a.m4s"
        temp_files = [audio_tmp]

        is_durl = audio_stream.get("type") == "durl"
        progress_range = progress_end - progress_start

        try:
            dl_weight = 0.7 if convert_mp3 else 0.85

            def ap(downloaded: int, total: int, speed: float) -> None:
                p = (downloaded / total * dl_weight) if total > 0 else 0
                task.progress = progress_start + p * progress_range
                task.speed = speed
                if on_progress:
                    on_progress(task)

            await stream_download(audio_stream["url"], audio_tmp, ap)

            task.progress = progress_start + 0.8 * progress_range
            if on_progress:
                on_progress(task)

            # durl 格式：先提取音频轨
            if is_durl:
                extracted = temp_dir / f"{vi.bvid}_extracted.m4a"
                temp_files.append(extracted)
                await asyncio.to_thread(
                    self._audio_conv.extract_audio, audio_tmp, extracted
                )
                audio_tmp = extracted

            if convert_mp3:
                actual_output = await asyncio.to_thread(
                    self._audio_conv.convert_to_mp3, audio_tmp, output_path
                )
            else:
                actual_output = await asyncio.to_thread(
                    self._audio_conv.remux_to_m4a, audio_tmp, output_path
                )

            # 下载封面用于标签
            task.progress = progress_start + 0.95 * progress_range
            if on_progress:
                on_progress(task)

            cover_data = None
            if vi.pic_url:
                try:
                    async with httpx.AsyncClient(
                        headers=DOWNLOAD_HEADERS,
                        follow_redirects=True,
                        timeout=15.0,
                    ) as http_client:
                        resp = await http_client.get(vi.pic_url)
                        resp.raise_for_status()
                        cover_data = resp.content
                except Exception:
                    pass

            await asyncio.to_thread(
                self._audio_conv.write_id3_tags,
                actual_output,
                title=vi.title,
                artist=vi.author_name,
                cover_data=cover_data,
            )

            set_file_mtime(actual_output, vi.publish_time)

            if is_single:
                warn = await asyncio.to_thread(_check_duration, actual_output, vi.duration)
                task.status = DownloadStatus.COMPLETED
                task.file_path = str(actual_output)
                task.file_size = actual_output.stat().st_size
                task.progress = 1.0
                if warn:
                    task.error_msg = warn

        except Exception:
            for p in [output_path, output_path.with_suffix(".m4a")]:
                if p.exists() and task.status != DownloadStatus.COMPLETED:
                    p.unlink(missing_ok=True)
            raise
        finally:
            for f in temp_files:
                if f.exists():
                    f.unlink(missing_ok=True)
            if temp_dir.exists():
                try:
                    temp_dir.rmdir()
                except OSError:
                    pass

    # ─── 封面下载 ───

    async def _download_cover(
        self,
        task: DownloadTask,
        on_progress: Optional[Callable[[DownloadTask], None]],
    ) -> None:
        """下载封面（可选正方形填充）"""
        vi = task.video_info
        if not vi.pic_url:
            raise BiliDLError("封面 URL 为空，无法下载")
        is_square = task.download_type == DownloadType.COVER_SQUARE

        ext = "_square.jpg" if is_square else ".jpg"
        output_path = self._build_path(vi, ext)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        def cp(downloaded: int, total: int, speed: float) -> None:
            task.progress = (downloaded / total * 0.8) if total > 0 else 0
            task.speed = speed
            if on_progress:
                on_progress(task)

        if is_square:
            original_path = output_path.parent / f"{output_path.stem}_orig.jpg"
        else:
            original_path = output_path

        try:
            await stream_download(vi.pic_url, original_path, cp)

            if is_square:
                task.progress = 0.9
                if on_progress:
                    on_progress(task)

                fill_mode = task.cover_fill_mode or CoverFillMode(
                    self._config.cover_fill_mode
                )
                await asyncio.to_thread(
                    self._cover_proc.process,
                    input_path=original_path,
                    output_path=output_path,
                    mode=fill_mode,
                    fill_color=tuple(self._config.cover_fill_color),  # type: ignore
                    blur_radius=self._config.cover_blur_radius,
                )
                if original_path != output_path and original_path.exists():
                    original_path.unlink(missing_ok=True)

            set_file_mtime(output_path, vi.publish_time)

            task.status = DownloadStatus.COMPLETED
            task.file_path = str(output_path)
            task.file_size = output_path.stat().st_size
            task.progress = 1.0

        except Exception:
            if is_square and original_path != output_path and original_path.exists():
                original_path.unlink(missing_ok=True)
            if output_path.exists() and task.status != DownloadStatus.COMPLETED:
                output_path.unlink(missing_ok=True)
            raise
