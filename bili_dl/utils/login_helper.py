"""B 站登录辅助：二维码扫描登录

Windows CMD 不原生支持 qrcode_terminal 所用之 ANSI 转义码，
故三管齐下：PNG 弹窗 + 终端渲染 + 链接备用。
"""

from __future__ import annotations

import os
import platform
import tempfile
import time

from rich.console import Console

from bilibili_api.login_v2 import QrCodeLogin, QrCodeLoginEvents

from ..models import AppConfig
from .async_helper import run_async

console = Console()

_POLL_INTERVAL = 2  # 秒
_TIMEOUT = 180  # 3 分钟


def _enable_vt_processing() -> None:
    """Windows 下启用 VT-100 终端处理，使 ANSI 转义码生效"""
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass  # 若启用失败，静默忽略


def _open_image(path: str) -> None:
    """用系统默认程序打开图片"""
    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(path)  # type: ignore
        elif system == "Darwin":
            import subprocess
            subprocess.Popen(["open", path])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass  # 打不开就静默忽略，URL 仍可用


def _render_qr_ascii(qr_link: str) -> str | None:
    """用 qrcode_terminal 渲染 ASCII 二维码，失败返 None

    Windows 下需先启用 VT 处理，否则 ANSI 码乱码。
    """
    try:
        import qrcode_terminal
        return qrcode_terminal.qr_terminal_str(qr_link)
    except Exception:
        return None


def _save_qr_png(qr: QrCodeLogin) -> str | None:
    """保存二维码 PNG 至临时目录，返回路径或 None"""
    try:
        pic = qr.get_qrcode_picture()
        tmp_dir = tempfile.gettempdir()
        path = os.path.join(tmp_dir, "bili_dl_qrcode.png")
        pic.to_file(path)
        return path
    except Exception:
        return None


def qr_login() -> dict | None:
    """二维码登录流程，返回凭据字典或 None（超时/取消）

    Returns:
        dict: 含 sessdata, bili_jct, dedeuserid, ac_time_value, buvid3
        None: 登录失败或超时
    """
    _enable_vt_processing()

    try:
        qr = QrCodeLogin()
    except Exception as e:
        console.print(f"[red]初始化二维码登录失败: {e}")
        return None

    # 生成二维码
    with console.status("[cyan]正在生成二维码..."):
        try:
            run_async(qr.generate_qrcode())
        except Exception as e:
            console.print(f"[red]生成二维码失败: {e}")
            return None

    # 登录 URL（bilibili-api-python 无公开 getter，访问私有属性）
    try:
        qr_link = qr._QrCodeLogin__qr_link
    except AttributeError:
        qr_link = ""

    # 方案 A：存 PNG 并弹窗
    png_path = _save_qr_png(qr)
    if png_path:
        _open_image(png_path)
        console.print("[dim]二维码图片已打开，若未弹出请查看下方链接[/dim]")

    # 方案 B：终端 ASCII 渲染
    qr_ascii = _render_qr_ascii(qr_link)
    if qr_ascii:
        console.print()
        console.print(qr_ascii)

    # 方案 C：提示文字
    console.print("\n[bold cyan]请用 Bilibili 客户端扫描二维码登录[/bold cyan]")
    if qr_link:
        console.print(f"[dim]终端扫描不便？可打开链接: [/dim][underline]{qr_link}")
    console.print("[dim]二维码有效期约 3 分钟[/dim]\n")

    # 轮询状态
    prev_state = None
    deadline = time.monotonic() + _TIMEOUT

    while time.monotonic() < deadline:
        try:
            state = run_async(qr.check_state())
        except Exception as e:
            console.print(f"[red]检查登录状态失败: {e}")
            return None

        if state != prev_state:
            if state == QrCodeLoginEvents.SCAN:
                console.print("[cyan]已扫描，请在手机上确认登录...")
            elif state == QrCodeLoginEvents.CONF:
                console.print("[cyan]已确认，正在获取凭证...")
            elif state == QrCodeLoginEvents.TIMEOUT:
                console.print("[yellow]二维码已过期，请重新生成")
                # 清理临时图片
                if png_path and os.path.exists(png_path):
                    try:
                        os.remove(png_path)
                    except OSError:
                        pass
                return None
            elif state == QrCodeLoginEvents.DONE:
                try:
                    cred = qr.get_credential()
                    result = {
                        "sessdata": cred.sessdata or "",
                        "bili_jct": cred.bili_jct or "",
                        "buvid3": getattr(cred, "buvid3", "") or "",
                        "dedeuserid": cred.dedeuserid or "",
                        "ac_time_value": getattr(cred, "ac_time_value", "") or "",
                    }
                    console.print("[green]登录成功! 凭证已获取")
                    # 清理临时图片
                    if png_path and os.path.exists(png_path):
                        try:
                            os.remove(png_path)
                        except OSError:
                            pass
                    return result
                except Exception as e:
                    console.print(f"[red]获取凭证失败: {e}")
                    return None
            prev_state = state

        time.sleep(_POLL_INTERVAL)

    console.print("[yellow]登录超时，请重试")
    if png_path and os.path.exists(png_path):
        try:
            os.remove(png_path)
        except OSError:
            pass
    return None


def apply_credential(cfg: AppConfig, cred: dict) -> None:
    """将凭据字典写入 AppConfig"""
    cfg.sessdata = cred.get("sessdata", "")
    cfg.bili_jct = cred.get("bili_jct", "")
    cfg.buvid3 = cred.get("buvid3", "")
    cfg.dedeuserid = cred.get("dedeuserid", "")
    cfg.ac_time_value = cred.get("ac_time_value", "")
