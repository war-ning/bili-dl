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

# #6: 可重试的异常类型
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


async def _get_cid(client: BiliClient, bvid: str, cid: int) -> int:
    """获取 cid，防空保护 (#3)"""
    if cid != 0:
        return cid
    pages = await get_video_pages(client, bvid)
    if not pages:
        raise BiliDLError(f"无法获取视频分P信息: {bvid}")
    return pages[0]["cid"]


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
        # 实际时长不到预期的 60%，可能是充电视频的免费预览
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
        # #12: 取消信号
        self._cancelled = False

    def _build_path(self, vi, ext: str) -> Path:
        """统一构建输出路径"""
        date = timestamp_to_str(vi.publish_time, "%Y-%m-%d") if vi.publish_time else ""
        return build_file_path(
            self._download_dir, vi.author_name, vi.title, vi.bvid, ext,
            template=self._filename_template, date=date,
        )

    def cancel(self) -> None:
        """设置取消信号"""
        self._cancelled = True

    async def execute_task(
        self,
        task: DownloadTask,
        on_progress: Optional[Callable[[DownloadTask], None]] = None,
        record_history: bool = True,
    ) -> DownloadTask:
        """执行单个下载任务，带重试逻辑 (#6)"""
        async with self._semaphore:
            # #12: 检查取消
            if self._cancelled:
                task.status = DownloadStatus.SKIPPED
                task.error_msg = "用户取消"
                if record_history:
                    self._history.add_record(task)
                if on_progress:
                    on_progress(task)
                return task

            last_error = None
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

                    # 成功，跳出重试循环
                    break

                except RETRYABLE_EXCEPTIONS as e:
                    last_error = e
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

        # 预获取 cid，避免同一视频的多个任务重复请求 API
        bvids_need_cid = {t.video_info.bvid for t in tasks
                         if t.video_info.cid == 0
                         and t.download_type in (DownloadType.VIDEO, DownloadType.AUDIO, DownloadType.AUDIO_FAST)}
        for bvid in bvids_need_cid:
            try:
                pages = await get_video_pages(self._client, bvid)
                if pages:
                    cid = pages[0]["cid"]
                    for t in tasks:
                        if t.video_info.bvid == bvid:
                            t.video_info.cid = cid
            except Exception:
                pass  # 让后续任务中的 _get_cid 处理

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

    async def _download_video(
        self,
        task: DownloadTask,
        on_progress: Optional[Callable[[DownloadTask], None]],
    ) -> None:
        """下载视频（DASH 视频+音频 -> MP4）"""
        vi = task.video_info

        # #3: 防空保护
        vi.cid = await _get_cid(self._client, vi.bvid, vi.cid)

        video_stream, audio_stream = await get_best_streams(
            self._client, vi.bvid, vi.cid
        )

        if not video_stream:
            raise BiliDLError("无法获取视频流")

        output_path = self._build_path(vi, ".mp4")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_dir = self._download_dir / ".tmp" / f"{vi.bvid}_video"
        temp_dir.mkdir(parents=True, exist_ok=True)

        video_tmp = temp_dir / f"{vi.bvid}_v.m4s"
        audio_tmp = temp_dir / f"{vi.bvid}_a.m4s"

        try:
            if video_stream.get("type") == "flv":
                def flv_progress(downloaded: int, total: int, speed: float) -> None:
                    task.progress = downloaded / total if total > 0 else 0
                    task.speed = speed
                    if on_progress:
                        on_progress(task)

                await stream_download(video_stream["url"], output_path, flv_progress)
            else:
                async def dl_video() -> None:
                    def vp(downloaded: int, total: int, speed: float) -> None:
                        task.progress = (downloaded / total * 0.45) if total > 0 else 0
                        task.speed = speed
                        if on_progress:
                            on_progress(task)

                    await stream_download(video_stream["url"], video_tmp, vp)

                async def dl_audio() -> None:
                    if not audio_stream:
                        return

                    def ap(downloaded: int, total: int, speed: float) -> None:
                        p = (downloaded / total * 0.45) if total > 0 else 0
                        task.progress = 0.45 + p
                        if on_progress:
                            on_progress(task)

                    await stream_download(audio_stream["url"], audio_tmp, ap)

                await asyncio.gather(dl_video(), dl_audio())

                task.progress = 0.9
                if on_progress:
                    on_progress(task)

                if audio_stream and audio_tmp.exists():
                    await asyncio.to_thread(
                        self._merger.merge, video_tmp, audio_tmp, output_path
                    )
                else:
                    video_tmp.rename(output_path)

            set_file_mtime(output_path, vi.publish_time)

            # 校验时长
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

    async def _download_audio(
        self,
        task: DownloadTask,
        on_progress: Optional[Callable[[DownloadTask], None]],
        convert_mp3: bool = True,
    ) -> None:
        """下载音频

        Args:
            convert_mp3: True=转码MP3(慢), False=直接remux M4A(快)
        """
        vi = task.video_info

        # #3: 防空保护
        vi.cid = await _get_cid(self._client, vi.bvid, vi.cid)

        audio_stream = await get_audio_stream(self._client, vi.bvid, vi.cid)
        if not audio_stream:
            raise BiliDLError("无法获取音频流")

        target_ext = ".mp3" if convert_mp3 else ".m4a"
        output_path = self._build_path(vi, target_ext)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_dir = self._download_dir / ".tmp" / f"{vi.bvid}_audio"
        temp_dir.mkdir(parents=True, exist_ok=True)
        audio_tmp = temp_dir / f"{vi.bvid}_a.m4s"
        temp_files = [audio_tmp]  # 追踪所有临时文件

        is_durl = audio_stream.get("type") == "durl"

        try:
            dl_weight = 0.7 if convert_mp3 else 0.85

            def ap(downloaded: int, total: int, speed: float) -> None:
                task.progress = (downloaded / total * dl_weight) if total > 0 else 0
                task.speed = speed
                if on_progress:
                    on_progress(task)

            await stream_download(audio_stream["url"], audio_tmp, ap)

            task.progress = 0.8 if convert_mp3 else 0.9
            if on_progress:
                on_progress(task)

            # durl 格式：先从合流中提取音频轨
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
            task.progress = 0.95
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

            # 校验时长
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
            # 清理残留临时文件
            if is_square and original_path != output_path and original_path.exists():
                original_path.unlink(missing_ok=True)
            if output_path.exists() and task.status != DownloadStatus.COMPLETED:
                output_path.unlink(missing_ok=True)
            raise
