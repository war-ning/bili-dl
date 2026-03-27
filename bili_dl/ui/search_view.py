"""搜索 UP 主界面"""

from __future__ import annotations

import re
from typing import Optional, Union

import questionary
from rich.console import Console
from rich.table import Table

from ..api.client import BiliClient
from ..api.search import search_users
from ..models import UPInfo
from ..utils.async_helper import run_async
from ..utils.formatter import format_count

_HTML_TAG_RE = re.compile(r"<[^>]+>")

console = Console()


def run_search(client: BiliClient) -> Optional[UPInfo]:
    """搜索 UP 主并选择，返回选中的 UPInfo 或 None（返回主菜单）"""

    while True:
        keyword = questionary.text(
            "请输入 UP 主关键词 (输入 q 返回):"
        ).ask()

        if not keyword or keyword.strip().lower() == "q":
            return None

        keyword = keyword.strip()

        with console.status("[cyan]搜索中..."):
            try:
                users, total = run_async(search_users(client, keyword))
            except Exception as e:
                console.print(f"[red]搜索失败: {e}")
                continue

        if not users:
            console.print("[yellow]未找到相关 UP 主，请重新搜索")
            continue

        # 显示搜索结果
        table = Table(title=f"搜索结果 (共 {total} 条)")
        table.add_column("#", style="dim", width=4)
        table.add_column("UP 主", style="cyan", min_width=12)
        table.add_column("粉丝", justify="right", style="green", width=10)
        table.add_column("视频数", justify="right", width=8)
        table.add_column("等级", justify="center", width=6)
        table.add_column("简介", max_width=30, overflow="ellipsis")

        for i, u in enumerate(users, 1):
            table.add_row(
                str(i),
                u.name,
                format_count(u.fans),
                str(u.videos),
                f"Lv{u.level}",
                _HTML_TAG_RE.sub("", u.sign)[:30] if u.sign else "",
            )

        console.print(table)

        # 构建选择列表
        choices = [
            questionary.Choice(
                title=f"{u.name} (粉丝:{format_count(u.fans)} 视频:{u.videos})",
                value=u,
            )
            for u in users
        ]
        choices.append(questionary.Choice(title="重新搜索", value="retry"))
        choices.append(questionary.Choice(title="返回主菜单", value=None))

        selected = questionary.select(
            "选择 UP 主:",
            choices=choices,
        ).ask()

        if selected == "retry":
            continue
        return selected
