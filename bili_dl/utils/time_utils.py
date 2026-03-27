"""时间工具函数"""

import os
from datetime import datetime
from pathlib import Path


def set_file_mtime(path: Path, timestamp: int) -> None:
    """设置文件 mtime 为指定 Unix 时间戳"""
    try:
        os.utime(str(path), (timestamp, timestamp))
    except OSError:
        pass


def timestamp_to_str(ts: int, fmt: str = "%Y-%m-%d") -> str:
    """Unix 时间戳转可读日期"""
    try:
        return datetime.fromtimestamp(ts).strftime(fmt)
    except (OSError, ValueError):
        return "未知"


def timestamp_to_datetime(ts: int) -> datetime:
    """Unix 时间戳转 datetime"""
    try:
        return datetime.fromtimestamp(ts)
    except (OSError, ValueError):
        return datetime.now()
