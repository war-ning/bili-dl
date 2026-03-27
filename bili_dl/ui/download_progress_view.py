"""下载进度展示"""

from __future__ import annotations

import questionary
from rich.console import Console, Group
from rich.live import Live
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
)

from ..core.downloader import BatchDownloader
from ..models import DownloadStatus, DownloadTask
from ..utils.async_helper import run_async
from ..utils.formatter import format_size

console = Console()


def run_download(
    downloader: BatchDownloader,
    tasks: list[DownloadTask],
) -> list[DownloadTask]:
    """执行下载并显示进度，失败项可直接重试"""
    if not tasks:
        console.print("[yellow]没有需要下载的任务")
        return []

    # 支持重试循环
    current_tasks = tasks
    is_retry = False

    while True:
        results = _execute_and_show(downloader, current_tasks, record_history=not is_retry)

        # 汇总
        success = [t for t in results if t.status == DownloadStatus.COMPLETED]
        failed = [t for t in results if t.status == DownloadStatus.FAILED]
        skipped = [t for t in results if t.status == DownloadStatus.SKIPPED]

        console.print()
        console.print(
            f"[bold]下载完成![/bold] "
            f"[green]成功: {len(success)}[/green] "
            f"[red]失败: {len(failed)}[/red] "
            f"[yellow]跳过: {len(skipped)}[/yellow]"
        )

        if success:
            total_size = sum(t.file_size for t in success)
            console.print(f"\n[green]总下载大小: {format_size(total_size)}")
            console.print("[green]下载文件:")
            for t in success[:10]:
                suffix = ""
                if t.file_path.endswith(".m4a") and t.download_type.value == "audio":
                    suffix = " [dim](M4A 格式)[/dim]"
                console.print(f"  [dim]→[/dim] {t.file_path}{suffix}")
            if len(success) > 10:
                console.print(f"  [dim]... 等共 {len(success)} 个文件[/dim]")

            from pathlib import Path
            dirs = set(str(Path(t.file_path).parent) for t in success if t.file_path)
            if dirs:
                console.print(f"\n[cyan]文件目录: {', '.join(dirs)}")

        if failed:
            console.print("\n[red]失败列表:")
            for t in failed:
                console.print(
                    f"  [red]✗[/red] {t.video_info.title[:40]} "
                    f"({t.download_type.value}) - {t.error_msg}"
                )

            # 提供重试选项
            action = questionary.select(
                f"有 {len(failed)} 个任务失败，如何处理?",
                choices=[
                    questionary.Choice("重试全部失败项", value="retry_all"),
                    questionary.Choice("选择性重试", value="retry_select"),
                    questionary.Choice("跳过，返回", value="skip"),
                ],
            ).ask()

            if action == "retry_all":
                current_tasks = _reset_tasks(failed)
                is_retry = True
                continue
            elif action == "retry_select":
                choices = [
                    questionary.Choice(
                        title=f"{t.video_info.title[:30]} ({t.download_type.value})",
                        value=t,
                    )
                    for t in failed
                ]
                selected = questionary.checkbox(
                    "选择要重试的任务:", choices=choices
                ).ask()
                if selected:
                    current_tasks = _reset_tasks(selected)
                    is_retry = True
                    continue

        # 重试完成后，补记历史（仅重试的任务）
        if is_retry:
            for t in results:
                downloader._history.add_record(t)

        return results


def _reset_tasks(tasks: list[DownloadTask]) -> list[DownloadTask]:
    """重置任务状态用于重试"""
    for t in tasks:
        t.status = DownloadStatus.PENDING
        t.progress = 0.0
        t.error_msg = ""
        t.speed = 0.0
        t.file_path = ""
        t.file_size = 0
    return tasks


def _execute_and_show(
    downloader: BatchDownloader,
    tasks: list[DownloadTask],
    record_history: bool = True,
) -> list[DownloadTask]:
    """执行下载并显示进度条"""
    console.print(f"\n[cyan]开始下载 {len(tasks)} 个任务...\n")

    overall_progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]总进度"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("·"),
        TimeRemainingColumn(),
        console=console,
    )

    task_progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}", justify="left"),
        BarColumn(bar_width=30),
        TextColumn("{task.percentage:>5.1f}%"),
        console=console,
    )

    overall_task_id = overall_progress.add_task("总进度", total=len(tasks))
    active_tasks: dict[str, TaskID] = {}

    def on_task_update(task: DownloadTask, completed: int, total: int) -> None:
        key = f"{task.video_info.bvid}_{task.download_type.value}"
        overall_progress.update(overall_task_id, completed=completed)

        if task.status == DownloadStatus.DOWNLOADING:
            desc = f"{task.video_info.title[:25]} ({task.download_type.value})"
            if key not in active_tasks:
                tid = task_progress.add_task(desc, total=100)
                active_tasks[key] = tid
            task_progress.update(
                active_tasks[key],
                completed=task.progress * 100,
                description=desc,
            )
        elif task.status in (
            DownloadStatus.COMPLETED,
            DownloadStatus.FAILED,
            DownloadStatus.SKIPPED,
        ):
            if key in active_tasks:
                task_progress.update(active_tasks[key], completed=100, visible=False)

    try:
        with Live(Group(overall_progress, task_progress), console=console, refresh_per_second=4):
            results = run_async(
                downloader.execute_batch(tasks, on_task_update=on_task_update, record_history=record_history)
            )
    except KeyboardInterrupt:
        console.print("\n[yellow]正在取消下载...")
        downloader.cancel()
        results = tasks
        for t in results:
            if t.status in (DownloadStatus.PENDING, DownloadStatus.DOWNLOADING):
                t.status = DownloadStatus.SKIPPED
                t.error_msg = "用户取消"

    return results
