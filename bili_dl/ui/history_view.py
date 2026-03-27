"""下载历史查看 + 重试 + 删除 + 打开目录"""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path
from typing import Optional

import questionary
from rich.console import Console
from rich.table import Table

from ..core.history import DownloadHistory
from ..models import DownloadStatus, DownloadTask
from ..utils.formatter import format_size

console = Console()

HISTORY_PAGE_SIZE = 30

STATUS_STYLE = {
    "completed": "[green]完成[/green]",
    "failed": "[red]失败[/red]",
    "skipped": "[yellow]跳过[/yellow]",
    "pending": "[dim]等待[/dim]",
    "downloading": "[cyan]下载中[/cyan]",
}


def _open_directory(dir_path: str) -> None:
    """跨平台打开文件所在目录 (#11)"""
    p = Path(dir_path)
    if not p.exists():
        console.print(f"[red]路径不存在: {dir_path}")
        return

    target = p if p.is_dir() else p.parent
    try:
        system = platform.system()
        if system == "Darwin":
            subprocess.Popen(["open", str(target)])
        elif system == "Windows":
            subprocess.Popen(["explorer", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
        console.print(f"[green]已打开: {target}")
    except Exception as e:
        console.print(f"[red]无法打开目录: {e}")
        console.print(f"[dim]路径: {target}")


def show_history(history: DownloadHistory) -> Optional[list[DownloadTask]]:
    """显示下载历史，返回需要重新下载的任务列表或 None"""

    records = history.get_all()
    if not records:
        console.print("[yellow]暂无下载历史")
        return None

    # 筛选
    filter_choice = questionary.select(
        "筛选历史记录:",
        choices=[
            questionary.Choice("全部记录", value="all"),
            questionary.Choice("已完成", value="completed"),
            questionary.Choice("失败", value="failed"),
            questionary.Choice("已跳过", value="skipped"),
            questionary.Choice("返回", value="back"),
        ],
    ).ask()

    if filter_choice == "back" or filter_choice is None:
        return None

    if filter_choice != "all":
        records = [r for r in records if r.status == filter_choice]

    if not records:
        console.print("[yellow]没有匹配的记录")
        return None

    # #7: 分页显示
    total_pages = (len(records) + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE
    current_page = 0

    while True:
        start = current_page * HISTORY_PAGE_SIZE
        end = min(start + HISTORY_PAGE_SIZE, len(records))
        page_records = records[start:end]

        table = Table(
            title=f"下载历史 (共 {len(records)} 条, "
                  f"第 {current_page + 1}/{total_pages} 页)"
        )
        table.add_column("#", style="dim", width=4)
        table.add_column("状态", width=6)
        table.add_column("标题", min_width=15, max_width=30, overflow="ellipsis")
        table.add_column("UP 主", width=12)
        table.add_column("类型", width=6)
        table.add_column("大小", justify="right", width=10)
        table.add_column("下载时间", width=12)
        table.add_column("错误信息", max_width=25, overflow="ellipsis")

        for i, r in enumerate(page_records, start + 1):
            status_text = STATUS_STYLE.get(r.status, "[dim]未知[/dim]")
            table.add_row(
                str(i),
                status_text,
                r.title,
                r.author,
                r.download_type,
                format_size(r.file_size) if r.file_size > 0 else "-",
                r.created_at[:16] if r.created_at else "",
                r.error_msg or "",
            )

        console.print(table)

        # 操作菜单
        action_choices = []
        failed_records = [r for r in records if r.status == "failed"]
        completed_records = [r for r in records if r.status == "completed"]

        if failed_records:
            action_choices.append(
                questionary.Choice("重新下载全部失败记录", value="retry_all")
            )
            action_choices.append(
                questionary.Choice("选择性重新下载", value="retry_select")
            )

        # #11: 打开目录
        if completed_records:
            action_choices.append(
                questionary.Choice("打开下载目录", value="open_dir")
            )

        # #9: 删除功能
        action_choices.append(
            questionary.Choice("删除选中记录", value="delete_select")
        )
        action_choices.append(
            questionary.Choice("清空全部历史", value="clear_all")
        )

        # 翻页
        if current_page < total_pages - 1:
            action_choices.append(
                questionary.Choice("下一页 >>>", value="next_page")
            )
        if current_page > 0:
            action_choices.append(
                questionary.Choice("<<< 上一页", value="prev_page")
            )

        action_choices.append(questionary.Choice("返回", value="back"))

        action = questionary.select("选择操作:", choices=action_choices).ask()

        if action == "back" or action is None:
            return None

        # 翻页
        if action == "next_page":
            current_page += 1
            continue
        elif action == "prev_page":
            current_page -= 1
            continue

        # 重试
        if action == "retry_all":
            return [history.record_to_task(r) for r in failed_records]

        if action == "retry_select":
            choices = [
                questionary.Choice(
                    title=f"{r.title[:30]} ({r.download_type}) - {r.error_msg or ''}",
                    value=r,
                )
                for r in failed_records
            ]
            selected = questionary.checkbox("选择要重新下载的记录:", choices=choices).ask()
            if selected:
                return [history.record_to_task(r) for r in selected]
            continue

        # #11: 打开目录
        if action == "open_dir":
            dir_choices = []
            seen_dirs = set()
            for r in completed_records:
                if r.file_path:
                    d = str(Path(r.file_path).parent)
                    if d not in seen_dirs:
                        seen_dirs.add(d)
                        dir_choices.append(questionary.Choice(title=d, value=d))
            if dir_choices:
                dir_choices.append(questionary.Choice(title="返回", value=None))
                selected_dir = questionary.select(
                    "选择要打开的目录:", choices=dir_choices
                ).ask()
                if selected_dir:
                    _open_directory(selected_dir)
            else:
                console.print("[yellow]没有可用的文件路径")
            continue

        # #9: 删除选中
        if action == "delete_select":
            del_choices = [
                questionary.Choice(
                    title=f"{r.title[:30]} ({r.download_type}) [{r.status}]",
                    value=r.id,
                )
                for r in page_records
            ]
            selected_ids = questionary.checkbox(
                "选择要删除的记录:", choices=del_choices
            ).ask()
            if selected_ids:
                confirm = questionary.confirm(
                    f"确认删除 {len(selected_ids)} 条记录?", default=False
                ).ask()
                if confirm:
                    deleted = history.delete_records(selected_ids)
                    console.print(f"[green]已删除 {deleted} 条记录")
                    records = history.get_all()
                    if filter_choice != "all":
                        records = [r for r in records if r.status == filter_choice]
                    total_pages = max(1, (len(records) + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE)
                    current_page = min(current_page, total_pages - 1)
            continue

        # #9: 清空全部
        if action == "clear_all":
            confirm = questionary.confirm(
                "确认清空全部历史记录? 此操作不可撤销!", default=False
            ).ask()
            if confirm:
                count = history.clear_all()
                console.print(f"[green]已清空 {count} 条记录")
            return None

    return None
