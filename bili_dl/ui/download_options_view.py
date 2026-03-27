"""下载选项界面"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import questionary
from rich.console import Console

from ..core.history import DownloadHistory
from ..models import (
    AppConfig,
    CoverFillMode,
    DownloadTask,
    DownloadType,
    VideoInfo,
)

console = Console()


def configure_download(
    videos: list[VideoInfo],
    config: AppConfig,
    history: DownloadHistory,
    allow_charge: bool = False,
) -> list[DownloadTask] | str | None:
    """配置下载选项

    Returns:
        list[DownloadTask]: 任务列表
        "back": 上一步（重选视频）
        None: 返回主菜单
    """
    console.print(f"\n[cyan]已选择 [bold]{len(videos)}[/bold] 个视频")

    # 选择下载类型
    type_choices = [
        questionary.Choice("视频 (MP4)", value=DownloadType.VIDEO, checked=True),
        questionary.Choice("音频 (MP3, 转码较慢, 含 ID3 标签)", value=DownloadType.AUDIO),
        questionary.Choice("音频 (M4A, 不转码极快, 含标签)", value=DownloadType.AUDIO_FAST),
        questionary.Choice("封面 (原图)", value=DownloadType.COVER),
        questionary.Choice("封面 (正方形填充)", value=DownloadType.COVER_SQUARE),
        questionary.Choice("<<< 上一步 (重选视频) <<<", value="back"),
    ]

    selected_types = questionary.checkbox(
        "选择下载类型 (空格选择, 回车确认):",
        choices=type_choices,
    ).ask()

    if selected_types is None:
        return None

    if "back" in selected_types:
        return "back"

    selected_types = [t for t in selected_types if isinstance(t, DownloadType)]
    if not selected_types:
        console.print("[yellow]未选择下载类型")
        return "back"

    # 封面填充模式：直接使用配置值
    cover_fill_mode = CoverFillMode(config.cover_fill_mode)

    # 检查重复下载
    duplicate_tasks: list[tuple[VideoInfo, DownloadType, str]] = []
    for video in videos:
        for dt in selected_types:
            existing = history.get_downloaded_path(video.bvid, dt.value)
            if existing and Path(existing).exists():
                duplicate_tasks.append((video, dt, existing))

    skip_duplicates = set()
    if duplicate_tasks:
        console.print(
            f"\n[yellow]检测到 {len(duplicate_tasks)} 个已下载的文件:"
        )
        for video, dt, path in duplicate_tasks[:5]:
            console.print(f"  {video.title[:30]} ({dt.value})")
        if len(duplicate_tasks) > 5:
            console.print(f"  ... 等共 {len(duplicate_tasks)} 个")

        dup_action = questionary.select(
            "如何处理已下载的文件?",
            choices=[
                questionary.Choice("跳过已下载", value="skip"),
                questionary.Choice("覆盖重新下载", value="overwrite"),
            ],
        ).ask()

        if dup_action is None:
            return "back"

        if dup_action == "skip":
            skip_duplicates = {
                (v.bvid, dt.value) for v, dt, _ in duplicate_tasks
            }

    # 多分P处理方式：直接使用配置值
    merge_pages = config.merge_pages

    # 构建任务列表
    tasks: list[DownloadTask] = []
    for video in videos:
        if video.is_charge_plus and not allow_charge:
            continue

        for dt in selected_types:
            if (video.bvid, dt.value) in skip_duplicates:
                continue

            tasks.append(DownloadTask(
                video_info=video,
                download_type=dt,
                quality=config.preferred_quality,
                cover_fill_mode=cover_fill_mode,
                merge_pages=merge_pages,
            ))

    if not tasks:
        console.print("[yellow]没有需要下载的任务")
        return "back"

    # 确认
    video_count = len({t.video_info.bvid for t in tasks})
    type_names = {
        "video": "视频", "audio": "MP3音频", "audio_m4a": "M4A音频",
        "cover": "封面", "cover_square": "正方形封面",
    }
    type_summary = ", ".join(type_names.get(dt.value, dt.value) for dt in selected_types)
    console.print(f"\n[green]{video_count}[/green] 个视频, 共 [green]{len(tasks)}[/green] 个文件 ({type_summary})")
    if merge_pages:
        console.print("[dim]多分P视频将合并为一个文件")
    if not allow_charge:
        charge_skipped = sum(1 for v in videos if v.is_charge_plus)
        if charge_skipped:
            console.print(f"[yellow]已跳过 {charge_skipped} 个充电专属视频")

    confirm = questionary.confirm("确认开始下载?", default=True).ask()
    if not confirm:
        return "back"

    return tasks
