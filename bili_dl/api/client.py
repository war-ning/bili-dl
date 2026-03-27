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
