#!/usr/bin/env python3
"""Bili-DL: Bilibili 视频/音频/封面下载工具"""

import os
import sys
from pathlib import Path

from rich.console import Console

from bili_dl import __version__
from bili_dl.config import ConfigManager
from bili_dl.ui.app import main_loop
from bili_dl.utils.async_helper import cleanup
from bili_dl.utils.file_checker import check_video_file

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
            p.mkdir(parents=True, exist_ok=True)
            p.rmdir()
        return True, "OK"
    except OSError as e:
        return False, f"无法使用该路径: {e}"


def first_run_setup(config_mgr: ConfigManager) -> None:
    """首次运行引导"""
    import questionary

    console.print(f"\n[bold cyan]欢迎使用 Bili-DL![/bold cyan] [dim]v{__version__}[/dim]\n")
    console.print("首次运行，需要进行基本配置。\n")

    cfg = config_mgr.config

    # #8: 下载目录验证
    while True:
        download_dir = questionary.text(
            "下载目录:",
            default=cfg.download_dir,
        ).ask()
        if download_dir:
            valid, msg = _validate_download_dir(download_dir)
            if valid:
                cfg.download_dir = download_dir
                break
            else:
                console.print(f"[red]无法使用该目录: {msg}，请重新输入")
        else:
            break

    setup_cookie = questionary.select(
        "是否现在配置 B 站 Cookie? (影响画质上限，可稍后在设置中配置)",
        choices=[
            questionary.Choice("扫码登录 (推荐)", value="qr"),
            questionary.Choice("手动输入 Cookie", value="manual"),
            questionary.Choice("跳过，稍后配置", value="skip"),
        ],
    ).ask()

    if setup_cookie == "qr":
        from bili_dl.utils.login_helper import qr_login, apply_credential

        console.print(
            "\n[cyan]即将生成二维码，请确保已安装 Bilibili 客户端[/cyan]"
        )
        cred = qr_login()
        if cred:
            apply_credential(cfg, cred)

    elif setup_cookie == "manual":
        console.print(
            "\n[cyan]请从浏览器中获取 Cookie[/cyan]\n"
            "  方法: 登录 bilibili.com → F12 → Application → Cookies\n"
        )
        sessdata = questionary.text("SESSDATA (留空跳过):").ask()
        if sessdata and sessdata.strip():
            cfg.sessdata = sessdata.strip()
            bili_jct = questionary.text("bili_jct:").ask()
            if bili_jct:
                cfg.bili_jct = bili_jct.strip()
            buvid3 = questionary.text("buvid3:").ask()
            if buvid3:
                cfg.buvid3 = buvid3.strip()
            dedeuserid = questionary.text("DedeUserID:").ask()
            if dedeuserid:
                cfg.dedeuserid = dedeuserid.strip()
            # #10: 补上 ac_time_value
            ac_time = questionary.text("ac_time_value (可选):").ask()
            if ac_time:
                cfg.ac_time_value = ac_time.strip()

    config_mgr.save(cfg)
    console.print("\n[green]配置已保存! 开始使用吧~\n")


def _get_data_dir() -> Path:
    """获取 data 目录路径

    PyInstaller 打包后 __file__ 指向临时解压目录，配置会丢失。
    因此冻结模式下改用 exe 所在目录。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "data"
    return Path(__file__).resolve().parent / "data"


def main() -> None:
    """主入口（同步）"""
    data_dir = _get_data_dir()
    config_mgr = ConfigManager(str(data_dir))
    cfg = config_mgr.load()

    config_file = data_dir / "config.json"
    if not config_file.exists() or not cfg.download_dir:
        first_run_setup(config_mgr)

    try:
        main_loop(config_mgr)
    except KeyboardInterrupt:
        console.print("\n[dim]已退出")
    finally:
        cleanup()


if __name__ == "__main__":
    if "--version" in sys.argv or "-V" in sys.argv:
        print(f"bili-dl v{__version__}")
        sys.exit(0)

    if "--check-video" in sys.argv:
        idx = sys.argv.index("--check-video")
        if idx + 1 < len(sys.argv):
            check_video_file(sys.argv[idx + 1])
        else:
            print("用法: bili-dl --check-video <文件路径>")
        sys.exit(0)

    try:
        main()
    except Exception as e:
        import traceback
        print(f"\n程序出错: {e}")
        traceback.print_exc()
        input("\n按回车键退出...")  # 防止 exe 闪退
