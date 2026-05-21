"""合集浏览与视频选择界面"""

from __future__ import annotations

import questionary
from rich.console import Console
from rich.table import Table

from ..api.client import BiliClient
from ..api.season import (
    get_all_season_videos,
    get_all_season_videos_with_sections,
    get_first_season_bvid,
    get_season_sections_by_bvid,
    get_user_seasons,
)
from ..models import SectionInfo, SeasonInfo, UPInfo, VideoInfo
from ..utils.async_helper import run_async
from ..utils.errors import friendly_err as _friendly_err
from .video_list_view import paginated_select

console = Console()


def _maybe_hide_charge(videos: list[VideoInfo]) -> list[VideoInfo] | None:
    """若列表含充电视频，问用户是否隐藏。返 None 表用户 Ctrl+C"""
    charge_count = sum(1 for v in videos if v.is_charge_plus)
    if charge_count == 0:
        return videos
    hide = questionary.confirm(
        f"列表含 {charge_count} 个充电专属视频，是否隐藏?",
        default=False,
    ).ask()
    if hide is None:
        return None
    if hide:
        return [v for v in videos if not v.is_charge_plus]
    return videos


def load_and_select_season_videos(
    client: BiliClient,
    up_info: UPInfo,
) -> list[VideoInfo] | str | None:
    """合集下载入口

    流程：拉合集列表 → 选合集 (或"全部合集") → 拉视频 →
          单合集进多选、全部合集则一次性下载全部

    Returns:
        list[VideoInfo]: 已填充 season_title / episode_index 的视频
        "back": 上一步 (回上级菜单)
        None: 返回主菜单
    """
    console.print(f"\n[cyan]正在加载 [bold]{up_info.name}[/bold] 的合集列表...")

    try:
        seasons = run_async(get_user_seasons(client, up_info.mid))
    except Exception as e:
        console.print(f"[red]加载合集失败: {_friendly_err(e)}")
        return None

    if not seasons:
        console.print("[yellow]该 UP 主没有合集或列表")
        return "back"

    while True:
        # 展示合集列表
        table = Table(title=f"{up_info.name} 的合集 (共 {len(seasons)} 个)")
        table.add_column("#", style="dim", width=5)
        table.add_column("合集名", min_width=20, max_width=50, overflow="ellipsis")
        table.add_column("类型", width=8)
        table.add_column("视频数", justify="right", width=8)

        for i, s in enumerate(seasons, 1):
            type_label = "合集" if s.type == "season" else "列表"
            table.add_row(str(i), s.title, type_label, str(s.total))

        console.print(table)

        # 选择：单合集 / 全部合集 / 上一步
        choices = []
        for i, s in enumerate(seasons, 1):
            type_label = "合集" if s.type == "season" else "列表"
            choices.append(questionary.Choice(
                title=f"{i:>3}. [{type_label}] {s.title} ({s.total} 个视频)",
                value=s,
            ))
        choices.append(questionary.Choice(
            title="=== 下载全部合集 (直接下载全部视频，按合集分目录) ===",
            value="all",
        ))
        choices.append(questionary.Choice(
            title="<<< 上一步 <<<", value="back",
        ))

        selected = questionary.select("选择要下载的合集:", choices=choices).ask()
        if selected is None:
            return None
        if selected == "back":
            return "back"

        if selected == "all":
            videos = _load_all_seasons_videos(client, seasons, up_info)
            if videos is None:
                return None
            if videos == "retry":
                continue
            filtered = _maybe_hide_charge(videos)
            if filtered is None:
                return None
            if not filtered:
                console.print("[yellow]过滤后无可选视频")
                continue
            confirm = questionary.confirm(
                f"将下载全部 {len(filtered)} 个视频 (按合集分子目录)，继续?",
                default=True,
            ).ask()
            if not confirm:
                continue
            return filtered

        # 单合集
        result = _handle_single_season(client, selected, up_info)
        if result == "back":
            continue  # 回到合集列表
        if result is None or not result:
            return None
        return result


def _handle_single_season(
    client: BiliClient,
    season: SeasonInfo,
    up_info: UPInfo,
) -> list[VideoInfo] | str | None:
    """单合集处理：SEASON 探分节；SERIES 扁平"""
    # SERIES 旧版列表无分节概念，直接扁平
    if season.type == "series":
        return _flat_select(client, season, up_info)

    # SEASON: 探测分节
    console.print(
        f"\n[cyan]正在探测合集 [bold]{season.title}[/bold] 的分节..."
    )
    try:
        first_bvid = run_async(get_first_season_bvid(client, season))
        if not first_bvid:
            console.print("[yellow]该合集内没有视频")
            return "back"
        _, sections = run_async(
            get_season_sections_by_bvid(client, first_bvid)
        )
    except Exception as e:
        console.print(f"[red]探测分节失败: {_friendly_err(e)}")
        return "back"

    # 无分节或仅一节：扁平多选
    if len(sections) <= 1:
        videos = sections[0][1] if sections else []
        for v in videos:
            v.author_name = up_info.name
            v.section_title = ""  # 单节不分子目录
        if not videos:
            console.print("[yellow]该合集内没有视频")
            return "back"
        console.print(f"共 [green]{len(videos)}[/green] 个视频 (无分节)")
        videos = _maybe_hide_charge(videos)
        if videos is None:
            return None
        if not videos:
            console.print("[yellow]过滤后无可选视频")
            return "back"
        return paginated_select(
            videos, back_label="<<< 上一步 (返回合集列表) <<<",
        )

    # 多分节：选节
    return _handle_sections(season, sections, up_info)


def _flat_select(
    client: BiliClient,
    season: SeasonInfo,
    up_info: UPInfo,
) -> list[VideoInfo] | str | None:
    """series (旧版列表) 扁平多选"""
    console.print(
        f"\n[cyan]正在加载 [bold]{season.title}[/bold] 视频..."
    )
    try:
        videos = run_async(get_all_season_videos(client, season))
    except Exception as e:
        console.print(f"[red]加载视频失败: {_friendly_err(e)}")
        return "back"

    if not videos:
        console.print("[yellow]该列表内没有视频")
        return "back"

    for v in videos:
        v.author_name = up_info.name

    console.print(f"共 [green]{len(videos)}[/green] 个视频")
    videos = _maybe_hide_charge(videos)
    if videos is None:
        return None
    if not videos:
        console.print("[yellow]过滤后无可选视频")
        return "back"
    return paginated_select(
        videos, back_label="<<< 上一步 (返回合集列表) <<<",
    )


def _handle_sections(
    season: SeasonInfo,
    sections: list[tuple[SectionInfo, list[VideoInfo]]],
    up_info: UPInfo,
) -> list[VideoInfo] | str | None:
    """多分节选择：禁止跨节多选，容"全部分节"一并下载"""
    while True:
        table = Table(
            title=f"合集 {season.title} 的分节 (共 {len(sections)} 节)"
        )
        table.add_column("#", style="dim", width=5)
        table.add_column("分节名", min_width=10, max_width=30)
        table.add_column("视频数", justify="right", width=8)
        for i, (s, _vs) in enumerate(sections, 1):
            table.add_row(str(i), s.title, str(s.episode_count))
        console.print(table)

        choices = []
        for i, (s, _vs) in enumerate(sections, 1):
            choices.append(questionary.Choice(
                title=f"{i:>3}. {s.title} ({s.episode_count} 个视频)",
                value=("section", i - 1),
            ))
        total = sum(s.episode_count for s, _ in sections)
        choices.append(questionary.Choice(
            title=f"=== 下载全部分节 (共 {total} 个视频，按分节分目录) ===",
            value=("all", 0),
        ))
        choices.append(questionary.Choice(
            title="<<< 上一步 (返回合集列表) <<<", value=("back", 0),
        ))

        sel = questionary.select(
            "选择分节 (禁止跨节多选):", choices=choices,
        ).ask()
        if sel is None:
            return None
        kind, idx = sel
        if kind == "back":
            return "back"

        if kind == "all":
            all_videos: list[VideoInfo] = []
            for _s, vs in sections:
                for v in vs:
                    v.author_name = up_info.name
                    all_videos.append(v)
            filtered = _maybe_hide_charge(all_videos)
            if filtered is None:
                return None
            if not filtered:
                console.print("[yellow]过滤后无可选视频")
                continue
            confirm = questionary.confirm(
                f"将下载全部 {len(filtered)} 个视频 (按分节分子目录)，继续?",
                default=True,
            ).ask()
            if not confirm:
                continue
            return filtered

        # 单节多选
        section, videos = sections[idx]
        for v in videos:
            v.author_name = up_info.name
        console.print(
            f"\n[cyan]分节 [bold]{section.title}[/bold] 共 "
            f"[green]{len(videos)}[/green] 个视频"
        )
        filtered = _maybe_hide_charge(videos)
        if filtered is None:
            return None
        if not filtered:
            console.print("[yellow]过滤后无可选视频")
            continue
        result = paginated_select(
            filtered, back_label="<<< 上一步 (返回分节列表) <<<",
        )
        if result == "back":
            continue
        if result is None or not result:
            return None
        return result


def _load_all_seasons_videos(
    client: BiliClient,
    seasons: list[SeasonInfo],
    up_info: UPInfo,
) -> list[VideoInfo] | str | None:
    """拉取所有合集视频，拼合一张大表返回"""
    all_videos: list[VideoInfo] = []
    failed: list[str] = []

    with console.status("[cyan]正在拉取各合集视频...") as status:
        for i, s in enumerate(seasons, 1):
            status.update(f"[cyan]({i}/{len(seasons)}) {s.title}")
            try:
                # SEASON 类自动带分节；SERIES 扁平
                vs = run_async(get_all_season_videos_with_sections(client, s))
                for v in vs:
                    v.author_name = up_info.name
                all_videos.extend(vs)
            except Exception as e:
                failed.append(f"{s.title}: {_friendly_err(e)}")

    if failed:
        console.print(
            f"[yellow]有 {len(failed)} 个合集拉取失败:"
        )
        for msg in failed[:5]:
            console.print(f"  {msg}")
        if len(failed) > 5:
            console.print(f"  ... 共 {len(failed)} 个")

    if not all_videos:
        console.print("[yellow]未拉取到任何视频")
        return "retry"

    console.print(
        f"共 [green]{len(all_videos)}[/green] 个视频，"
        f"来自 {len(seasons) - len(failed)} 个合集"
    )
    return all_videos
