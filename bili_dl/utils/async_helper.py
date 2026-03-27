"""异步调用辅助：在同步上下文中执行 async 函数"""

from __future__ import annotations

import asyncio
import atexit
from typing import Any, Coroutine

_loop: asyncio.AbstractEventLoop | None = None


def get_loop() -> asyncio.AbstractEventLoop:
    """获取或创建持久化事件循环"""
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


def run_async(coro: Coroutine) -> Any:
    """在同步上下文中运行 async 协程"""
    return get_loop().run_until_complete(coro)


def cleanup() -> None:
    """清理事件循环

    先运行 bilibili-api-python 注册的 atexit 清理（需要事件循环仍打开），
    然后再关闭循环。
    """
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = None
        return

    # 运行 bilibili-api-python 的网络清理
    try:
        from bilibili_api.utils.network import __clean  # type: ignore
        _loop.run_until_complete(__clean())
    except Exception:
        pass

    # 取消注册 bilibili-api 的 atexit 回调（已手动执行过了）
    try:
        from bilibili_api.utils.network import __clean as _bc  # type: ignore
        atexit.unregister(_bc)
    except Exception:
        pass

    try:
        _loop.run_until_complete(_loop.shutdown_asyncgens())
    except Exception:
        pass

    _loop.close()
    _loop = None
