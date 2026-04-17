"""视频列表 + 多选界面"""

from __future__ import annotations

from typing import Optional

import questionary
from rich.console import Console
from rich.table import Table

from ..api.client import BiliClient
from ..api.user import get_all_user_videos
from ..models import UPInfo, VideoInfo
from ..utils.async_helper import run_async
from ..utils.errors import friendly_err
from ..utils.formatter import format_count, format_duration
from ..utils.time_utils import timestamp_to_str

console = Console()

PAGE_SIZE = 50


def load_and_select_videos(
    client: BiliClient,
    up_info: UPInfo,
    charge_only: bool = False,
) -> list[VideoInfo] | str | None:
    """加载视频列表并多选

    Returns:
        list[VideoInfo]: 选中的视频
        "back": 上一步（重新搜索）
        None: 返回主菜单
    """
    label = "充电专属视频" if charge_only else "视频"
    console.print(f"\n[cyan]正在加载 [bold]{up_info.name}[/bold] 的{label}列表...")

    try:
        all_videos = run_async(
            get_all_user_videos(client, up_info.mid)
        )
    except Exception as e:
        console.print(f"[red]加载失败: {friendly_err(e)}")
        return None

    if not all_videos:
        console.print("[yellow]该 UP 主没有视频")
        return None

    charge_count = sum(1 for v in all_videos if v.is_charge_plus)

    if charge_only:
        # 充电模式：只显示充电视频
        display_videos = [v for v in all_videos if v.is_charge_plus]
        if not display_videos:
            console.print("[yellow]该 UP 主没有充电专属视频")
            return None
        console.print(f"\n共 [green]{len(display_videos)}[/green] 个充电专属视频")
    else:
        # 普通模式
        console.print(
            f"\n共 [green]{len(all_videos)}[/green] 个视频"
            + (f"，其中 [yellow]{charge_count}[/yellow] 个充电专属" if charge_count else "")
        )

        hide_charge = False
        if charge_count > 0:
            hide_charge = questionary.confirm(
                "是否隐藏充电专属视频?", default=True
            ).ask()
            if hide_charge is None:
                return None

        display_videos = [
            v for v in all_videos if not (hide_charge and v.is_charge_plus)
        ]

        if not display_videos:
            console.print("[yellow]过滤后没有可选视频")
            return None

    result = paginated_select(display_videos, back_label="<<< 上一步 (重新搜索) <<<")
    return result


def paginated_select(
    display_videos: list[VideoInfo],
    back_label: str = "<<< 上一步 <<<",
) -> list[VideoInfo] | str | None:
    """分页多选视频；外部共用

    Returns:
        list[VideoInfo]: 选中的视频
        "back": 上一步
        None: 用户取消
    """
    selected_map: dict[str, VideoInfo] = {}
    total_pages = (len(display_videos) + PAGE_SIZE - 1) // PAGE_SIZE
    current_page = 0

    while True:
        start = current_page * PAGE_SIZE
        end = min(start + PAGE_SIZE, len(display_videos))
        page_videos = display_videos[start:end]

        selected_hint = f"  已选: {len(selected_map)}" if selected_map else ""
        table = Table(
            title=f"第 {current_page + 1}/{total_pages} 页 "
                  f"(共 {len(display_videos)} 个视频){selected_hint}"
        )
        table.add_column("#", style="dim", width=5)
        table.add_column("标题", min_width=20, max_width=40, overflow="ellipsis")
        table.add_column("时长", justify="right", width=8)
        table.add_column("播放", justify="right", style="green", width=10)
        table.add_column("发布日期", width=12)
        table.add_column("标记", width=6)

        for i, v in enumerate(page_videos, start + 1):
            marks = []
            if v.is_charge_plus:
                marks.append("[yellow]充电[/yellow]")
            if v.bvid in selected_map:
                marks.append("[green]✓[/green]")
            table.add_row(
                str(i),
                v.title,
                format_duration(v.duration),
                format_count(v.play_count),
                timestamp_to_str(v.publish_time),
                " ".join(marks),
            )

        console.print(table)

        choices = []
        for i, v in enumerate(page_videos, start + 1):
            charge_tag = "[充电] " if v.is_charge_plus else ""
            title = (
                f"{i:>3}. {charge_tag}{v.title[:35]:<35} "
                f"{format_duration(v.duration):>7} "
                f"{timestamp_to_str(v.publish_time)}"
            )
            choices.append(questionary.Choice(
                title=title, value=v, checked=(v.bvid in selected_map),
            ))

        choices.append(
            questionary.Choice(title="--- 全选本页 ---", value="select_all")
        )
        if total_pages > 1:
            choices.append(
                questionary.Choice(title="=== 全选所有页 ===", value="select_all_pages")
            )
        if current_page < total_pages - 1:
            choices.append(
                questionary.Choice(title=">>> 下一页 >>>", value="next")
            )
        if current_page > 0:
            choices.append(
                questionary.Choice(title="<<< 上一页 <<<", value="prev")
            )
        choices.append(
            questionary.Choice(title=back_label, value="back")
        )

        prompt = "选择要下载的视频 (空格选择, 回车确认):"
        if selected_map:
            prompt = f"已选 {len(selected_map)} 个, 空格选择, 回车确认:"

        result = questionary.checkbox(prompt, choices=choices).ask()

        if result is None:
            return None

        if "back" in result:
            return "back"

        page_selected = [v for v in result if isinstance(v, VideoInfo)]
        has_select_all = "select_all" in result
        has_select_all_pages = "select_all_pages" in result
        has_next = "next" in result
        has_prev = "prev" in result

        if has_select_all_pages:
            # 全选所有页：把整个列表入 selected_map，立即确认
            for v in display_videos:
                selected_map[v.bvid] = v
            break

        if has_select_all:
            page_selected = list(page_videos)

        page_bvids = {v.bvid for v in page_videos}
        selected_bvids_this_page = {v.bvid for v in page_selected}
        for bvid in page_bvids:
            if bvid not in selected_bvids_this_page:
                selected_map.pop(bvid, None)
        for v in page_selected:
            selected_map[v.bvid] = v

        if has_next and current_page < total_pages - 1:
            current_page += 1
            continue
        elif has_prev and current_page > 0:
            current_page -= 1
            continue

        if not selected_map:
            console.print("[yellow]未选择任何视频")
            retry = questionary.confirm("重新选择?", default=True).ask()
            if retry:
                current_page = 0
                continue
            return None
        break

    unique_videos = list(selected_map.values())
    console.print(f"\n[green]已选择 {len(unique_videos)} 个视频")
    return unique_videos
