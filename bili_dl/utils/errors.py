"""错误文案翻译：B 站风控/网络异常 → 中文可读提示"""

from __future__ import annotations


def friendly_err(e: BaseException) -> str:
    """网络/风控错误中文化，避免直接抛 412 HTML 页"""
    msg = str(e)
    if "412" in msg or "风控" in msg:
        return "B 站风控拦截 (412)，建议：稍候 1-2 分钟再试；或更新 Cookie 重登"
    if "-352" in msg:
        return "B 站风控拦截 (-352)，同上，建议更新 Cookie 或稍后再试"
    if "-403" in msg or "403" in msg:
        return "访问受限 (403)，可能需要登录或已充电 (非充电视频即遇此错请重登)"
    if len(msg) > 200:
        msg = msg[:200] + "..."
    return msg
