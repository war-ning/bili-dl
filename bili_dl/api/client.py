"""bilibili-api-python 统一封装"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from bilibili_api import Credential

from ..models import AppConfig


class BiliClient:
    """封装 Credential 管理、请求节流、错误重试"""

    def __init__(self, config: AppConfig):
        self._config = config
        self._credential: Optional[Credential] = None
        self._interval = config.request_interval_ms / 1000.0
        self._last_request_time: float = 0

        if config.sessdata:
            self._credential = Credential(
                sessdata=config.sessdata,
                bili_jct=config.bili_jct,
                buvid3=config.buvid3,
                dedeuserid=config.dedeuserid,
                ac_time_value=config.ac_time_value,
            )

    async def throttle(self) -> None:
        """请求节流：确保两次 API 调用间隔不小于 _interval"""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self._interval:
            await asyncio.sleep(self._interval - elapsed)
        self._last_request_time = time.monotonic()

    @property
    def credential(self) -> Optional[Credential]:
        return self._credential

    @property
    def has_credential(self) -> bool:
        return self._credential is not None

    def max_quality(self) -> int:
        """根据是否有 Cookie 返回最高可用画质"""
        if not self._credential:
            return 32  # 480P
        return self._config.preferred_quality or 80  # 默认 1080P


# B站风控常见错误码；触发则退避重试
_RISK_HINTS = ("412", "-352", "-403", "风控")
_RETRY_DELAYS = (3, 6, 12)  # 秒


def is_risk_error(e: BaseException) -> bool:
    msg = str(e)
    return any(h in msg for h in _RISK_HINTS)


async def with_risk_retry(coro_factory, op_name: str = "接口"):
    """对 B站风控错误 (412/-352) 指数退避重试；其他异常立即抛"""
    last_err: BaseException | None = None
    for delay in (*_RETRY_DELAYS, None):
        try:
            return await coro_factory()
        except Exception as e:
            last_err = e
            if not is_risk_error(e) or delay is None:
                raise
            await asyncio.sleep(delay)
    if last_err:
        raise last_err
