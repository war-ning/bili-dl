"""主菜单 + 导航控制器"""

from __future__ import annotations

import questionary
from rich.console import Console
from rich.panel import Panel

from ..api.client import BiliClient
from ..config import ConfigManager
from ..core.downloader import BatchDownloader
from ..core.history import DownloadHistory
from . import (
    download_options_view,
    download_progress_view,
    history_view,
    search_view,
    season_view,
    settings_view,
    video_list_view,
)

console = Console()


def main_loop(config_mgr: ConfigManager) -> None:
    """主交互循环（同步）"""
    cfg = config_mgr.config
    client = BiliClient(cfg)
    history = DownloadHistory(config_mgr.get_history_path())

    while True:
        auth_status = (
            "[green]已登录[/green]" if client.has_credential
            else "[yellow]未登录 (最高 480P)[/yellow]"
        )

        console.print(
            Panel(
                f"[bold cyan]Bili-DL[/bold cyan] - Bilibili 下载工具\n"
                f"认证状态: {auth_status}  "
                f"下载目录: [dim]{cfg.download_dir}[/dim]",
                border_style="cyan",
            )
        )

        menu_choices = [
            questionary.Choice("搜索 UP 主并下载", value="search"),
        ]
        if client.has_credential:
            menu_choices.append(
                questionary.Choice("下载充电专属视频", value="charge")
            )
        menu_choices.extend([
            questionary.Choice("查看下载历史", value="history"),
            questionary.Choice("设置", value="settings"),
            questionary.Choice("退出", value="exit"),
        ])

        action = questionary.select(
            "请选择操作:",
            choices=menu_choices,
        ).ask()

        if action == "exit" or action is None:
            console.print("[dim]再见!")
            break

        try:
            if action == "search":
                _handle_search(client, config_mgr, history)

            elif action == "charge":
                _handle_search(client, config_mgr, history, charge_only=True)

            elif action == "history":
                retry_tasks = history_view.show_history(history)
                if retry_tasks:
                    downloader = BatchDownloader(cfg, client, history)
                    download_progress_view.run_download(downloader, retry_tasks)

            elif action == "settings":
                settings_view.show_settings(config_mgr)
                cfg = config_mgr.load()
                client = BiliClient(cfg)

        except KeyboardInterrupt:
            console.print("\n[dim]已返回主菜单")
        except Exception as e:
            console.print(f"\n[red]操作失败: {type(e).__name__}: {e}")
            console.print("[dim]已返回主菜单")


def _handle_search(
    client: BiliClient,
    config_mgr: ConfigManager,
    history: DownloadHistory,
    charge_only: bool = False,
) -> None:
    """处理搜索 → 选择视频 → 配置下载 → 执行下载

    每一步都支持"上一步"回退。
    """
    cfg = config_mgr.config

    while True:
        # Step 1: 搜索 UP 主
        up_info = search_view.run_search(client)
        if up_info is None:
            return  # 返回主菜单

        # Step 2+3+4 循环（支持上一步回退到搜索）
        result = _handle_up_download(client, cfg, history, up_info, charge_only)
        if result == "back_to_search":
            continue  # 回到搜索
        return  # 返回主菜单


def _handle_up_download(
    client: BiliClient,
    cfg,
    history: DownloadHistory,
    up_info,
    charge_only: bool,
) -> str | None:
    """处理选中 UP 主后的流程，返回 "back_to_search" 表示回到搜索

    非充电模式维持 mode 状态：下载后"继续"或"back_to_videos"回退时，
    不再反复询问模式，直接复用上次选择；仅当视频选择界面点"上一步"时
    才回到模式选择层。
    """
    mode: str | None = None  # None 表示需询问模式

    while True:
        # Step 2a: (非充电) 若无模式，询问
        if not charge_only and mode is None:
            mode = questionary.select(
                f"下载 {up_info.name} 的:",
                choices=[
                    questionary.Choice("全部视频", value="all"),
                    questionary.Choice("按合集下载", value="season"),
                    questionary.Choice("<<< 上一步 (返回搜索) <<<", value="back"),
                ],
            ).ask()
            if mode is None:
                return None
            if mode == "back":
                return "back_to_search"

        # Step 2b: 按 mode 分流
        if charge_only:
            selected = video_list_view.load_and_select_videos(
                client, up_info, charge_only=True,
            )
            if selected == "back":
                return "back_to_search"
        elif mode == "season":
            selected = season_view.load_and_select_season_videos(
                client, up_info,
            )
            if selected == "back":
                mode = None  # 回到模式选择
                continue
        else:  # mode == "all"
            selected = video_list_view.load_and_select_videos(
                client, up_info, charge_only=False,
            )
            if selected == "back":
                mode = None  # 回到模式选择
                continue

        if selected is None or not selected:
            return None

        # Step 3+4 循环（下载配置 & 执行）
        result = _handle_download(cfg, history, client, selected, charge_only, up_info)
        if result == "back_to_videos":
            continue  # 回到视频选择 (保持 mode)
        if result == "continue":
            continue  # 继续下载该 UP 主 (保持 mode)
        return None  # 返回主菜单


def _handle_download(
    cfg,
    history: DownloadHistory,
    client: BiliClient,
    selected: list,
    charge_only: bool,
    up_info,
) -> str | None:
    """处理下载配置和执行，返回控制信号"""

    while True:
        # Step 3: 配置下载选项
        tasks = download_options_view.configure_download(
            selected, cfg, history, allow_charge=charge_only
        )
        if tasks == "back":
            return "back_to_videos"
        if tasks is None or not tasks:
            return None

        # Step 4: 执行下载
        downloader = BatchDownloader(cfg, client, history)
        download_progress_view.run_download(downloader, tasks)

        # 下载完成后
        action = questionary.select(
            "下一步:",
            choices=[
                questionary.Choice(
                    f"继续下载 {up_info.name} 的其他视频", value="continue"
                ),
                questionary.Choice("返回主菜单", value="menu"),
            ],
        ).ask()

        if action == "continue":
            return "continue"
        return None
