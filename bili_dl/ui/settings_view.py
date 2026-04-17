"""配置修改界面"""

from __future__ import annotations

import os
from pathlib import Path

import questionary
from rich.console import Console
from rich.table import Table

from ..config import ConfigManager
from ..models import AppConfig

console = Console()


def _validate_download_dir(dir_path: str) -> tuple[bool, str]:
    """验证下载目录是否可用 (#8)"""
    try:
        p = Path(dir_path)
        if p.exists():
            if not p.is_dir():
                return False, "路径存在但不是目录"
            if not os.access(str(p), os.W_OK):
                return False, "目录没有写入权限"
        else:
            # 尝试创建
            p.mkdir(parents=True, exist_ok=True)
            p.rmdir()  # 清理测试创建的目录
        return True, "OK"
    except OSError as e:
        return False, f"无法使用该路径: {e}"


def show_settings(config_mgr: ConfigManager) -> None:
    """显示并修改配置"""

    while True:
        cfg = config_mgr.config

        table = Table(title="当前配置")
        table.add_column("配置项", style="cyan", width=20)
        table.add_column("当前值", width=40)

        table.add_row("下载目录", cfg.download_dir)
        table.add_row("最大并发数", str(cfg.max_concurrent))
        table.add_row("画质偏好", _quality_name(cfg.preferred_quality))
        table.add_row("请求间隔", f"{cfg.request_interval_ms}ms")
        table.add_row("封面填充模式", cfg.cover_fill_mode)
        table.add_row("封面填充颜色", str(cfg.cover_fill_color))
        table.add_row("模糊半径", str(cfg.cover_blur_radius))
        table.add_row("多分P处理", "合并为一个文件" if cfg.merge_pages else "每P单独保存")
        table.add_row("文件命名模板", cfg.filename_template)
        table.add_row("合集命名模板", cfg.season_filename_template)
        table.add_row(
            "Cookie (SESSDATA)",
            f"{cfg.sessdata[:20]}..." if cfg.sessdata else "[red]未设置[/red]",
        )

        console.print(table)

        action = questionary.select(
            "选择要修改的配置:",
            choices=[
                questionary.Choice("下载目录", value="download_dir"),
                questionary.Choice("最大并发数", value="max_concurrent"),
                questionary.Choice("画质偏好", value="quality"),
                questionary.Choice("封面填充模式", value="cover_mode"),
                questionary.Choice("封面填充颜色 (RGB)", value="cover_color"),
                questionary.Choice("多分P处理", value="merge_pages"),
                questionary.Choice("文件命名模板", value="filename_template"),
                questionary.Choice("合集命名模板", value="season_template"),
                questionary.Choice("Cookie 设置", value="cookie"),
                questionary.Choice("返回主菜单", value="back"),
            ],
        ).ask()

        if action == "back" or action is None:
            break

        if action == "download_dir":
            new_dir = questionary.text(
                "新的下载目录:", default=cfg.download_dir
            ).ask()
            if new_dir:
                # #8: 验证目录
                valid, msg = _validate_download_dir(new_dir)
                if valid:
                    cfg.download_dir = new_dir
                    config_mgr.save(cfg)
                    console.print("[green]已更新下载目录")
                else:
                    console.print(f"[red]无法使用该目录: {msg}")

        elif action == "max_concurrent":
            val = questionary.text(
                "最大并发数 (1-10):", default=str(cfg.max_concurrent)
            ).ask()
            try:
                n = int(val)
                if 1 <= n <= 10:
                    cfg.max_concurrent = n
                    config_mgr.save(cfg)
                    console.print("[green]已更新并发数")
                else:
                    console.print("[red]请输入 1-10 之间的数字")
            except (ValueError, TypeError):
                console.print("[red]请输入有效数字")

        elif action == "quality":
            q = questionary.select(
                "选择画质偏好:",
                choices=[
                    questionary.Choice("360P", value=16),
                    questionary.Choice("480P", value=32),
                    questionary.Choice("720P", value=64),
                    questionary.Choice("1080P (需登录)", value=80),
                    questionary.Choice("1080P+ (需大会员)", value=112),
                    questionary.Choice("4K (需大会员)", value=120),
                ],
            ).ask()
            if q is not None:
                cfg.preferred_quality = q
                config_mgr.save(cfg)
                console.print("[green]已更新画质偏好")

        elif action == "cover_mode":
            mode = questionary.select(
                "封面填充模式:",
                choices=[
                    questionary.Choice("纯色填充", value="solid_color"),
                    questionary.Choice("模糊背景填充", value="blur"),
                ],
            ).ask()
            if mode:
                cfg.cover_fill_mode = mode
                config_mgr.save(cfg)
                console.print("[green]已更新封面填充模式")

        elif action == "cover_color":
            color_str = questionary.text(
                "输入 RGB 颜色 (如 0,0,0 为黑色, 255,255,255 为白色):",
                default=",".join(str(c) for c in cfg.cover_fill_color),
            ).ask()
            try:
                parts = [int(x.strip()) for x in color_str.split(",")]
                if len(parts) == 3 and all(0 <= x <= 255 for x in parts):
                    cfg.cover_fill_color = parts
                    config_mgr.save(cfg)
                    console.print("[green]已更新填充颜色")
                else:
                    console.print("[red]请输入 3 个 0-255 的数字，用逗号分隔")
            except (ValueError, TypeError, AttributeError):
                console.print("[red]格式错误")

        elif action == "merge_pages":
            mp = questionary.select(
                "多分P视频处理方式:",
                choices=[
                    questionary.Choice("每P单独保存", value=False),
                    questionary.Choice("合并为一个文件", value=True),
                ],
            ).ask()
            if mp is not None:
                cfg.merge_pages = mp
                config_mgr.save(cfg)
                console.print("[green]已更新多分P处理方式")

        elif action == "filename_template":
            console.print(
                "\n[cyan]可用变量:[/cyan]\n"
                "  {title}  — 视频标题\n"
                "  {bvid}   — BV 号\n"
                "  {author} — UP 主名\n"
                "  {date}   — 发布日期 (YYYY-MM-DD)\n"
                "\n[dim]示例: {title}_{bvid}, {date}_{title}, {author}_{title}[/dim]\n"
            )
            tpl = questionary.text(
                "文件命名模板:",
                default=cfg.filename_template,
            ).ask()
            if tpl and tpl.strip():
                # 验证模板是否合法
                try:
                    tpl.strip().format(
                        title="test", bvid="BV1xxx", author="UP",
                        date="2026-01-01", season="s", episode=1,
                    )
                    cfg.filename_template = tpl.strip()
                    config_mgr.save(cfg)
                    console.print("[green]已更新文件命名模板")
                except (KeyError, ValueError) as e:
                    console.print(f"[red]模板格式错误: {e}")

        elif action == "season_template":
            console.print(
                "\n[cyan]合集模式下的文件命名模板。可用变量:[/cyan]\n"
                "  {title}   — 视频标题\n"
                "  {bvid}    — BV 号\n"
                "  {author}  — UP 主名\n"
                "  {date}    — 发布日期 (YYYY-MM-DD)\n"
                "  {season}  — 合集名 (子目录已自动用此名)\n"
                "  {episode} — 合集内序号，可格式化如 {episode:02d}\n"
                "\n[dim]示例: {episode:02d}_{title}_{bvid}, "
                "{episode:03d}_{title}[/dim]\n"
            )
            tpl = questionary.text(
                "合集命名模板:",
                default=cfg.season_filename_template,
            ).ask()
            if tpl and tpl.strip():
                try:
                    tpl.strip().format(
                        title="test", bvid="BV1xxx", author="UP",
                        date="2026-01-01", season="s", episode=1,
                    )
                    cfg.season_filename_template = tpl.strip()
                    config_mgr.save(cfg)
                    console.print("[green]已更新合集命名模板")
                except (KeyError, ValueError) as e:
                    console.print(f"[red]模板格式错误: {e}")

        elif action == "cookie":
            _configure_cookie(config_mgr, cfg)


def _configure_cookie(config_mgr: ConfigManager, cfg: AppConfig) -> None:
    """配置 Cookie"""
    console.print(
        "\n[cyan]请从浏览器中获取以下 Cookie 值[/cyan]\n"
        "  方法: 登录 bilibili.com → F12 开发者工具 → Application → Cookies\n"
    )

    sessdata = questionary.text(
        "SESSDATA:", default=cfg.sessdata
    ).ask()
    if sessdata is not None:
        cfg.sessdata = sessdata.strip()

    bili_jct = questionary.text(
        "bili_jct:", default=cfg.bili_jct
    ).ask()
    if bili_jct is not None:
        cfg.bili_jct = bili_jct.strip()

    buvid3 = questionary.text(
        "buvid3:", default=cfg.buvid3
    ).ask()
    if buvid3 is not None:
        cfg.buvid3 = buvid3.strip()

    dedeuserid = questionary.text(
        "DedeUserID:", default=cfg.dedeuserid
    ).ask()
    if dedeuserid is not None:
        cfg.dedeuserid = dedeuserid.strip()

    # #10: 补上 ac_time_value
    ac_time = questionary.text(
        "ac_time_value (可选):", default=cfg.ac_time_value
    ).ask()
    if ac_time is not None:
        cfg.ac_time_value = ac_time.strip()

    config_mgr.save(cfg)
    console.print("[green]Cookie 已保存")


def _quality_name(qn: int) -> str:
    names = {
        16: "360P",
        32: "480P",
        64: "720P",
        80: "1080P",
        112: "1080P+",
        116: "1080P60",
        120: "4K",
        125: "HDR",
        126: "Dolby Vision",
        127: "8K",
    }
    return names.get(qn, f"qn={qn}")
