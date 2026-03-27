"""全局数据模型定义"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DownloadType(Enum):
    VIDEO = "video"
    AUDIO = "audio"          # MP3 转码，含 ID3 标签
    AUDIO_FAST = "audio_m4a"  # M4A 直接 remux，不转码，极快
    COVER = "cover"
    COVER_SQUARE = "cover_square"


class DownloadStatus(Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class CoverFillMode(Enum):
    SOLID_COLOR = "solid_color"
    BLUR = "blur"


@dataclass
class UPInfo:
    mid: int
    name: str
    face_url: str
    fans: int
    videos: int
    sign: str
    level: int


@dataclass
class VideoInfo:
    bvid: str
    title: str
    pic_url: str
    duration: int  # 秒
    play_count: int
    publish_time: int  # Unix 时间戳
    is_charge_plus: bool
    cid: int = 0
    author_name: str = ""
    author_mid: int = 0


@dataclass
class DownloadTask:
    video_info: VideoInfo
    download_type: DownloadType
    quality: int = 80
    cover_fill_mode: Optional[CoverFillMode] = None
    merge_pages: bool = False  # 多分P时是否合并为一个文件
    status: DownloadStatus = DownloadStatus.PENDING
    progress: float = 0.0
    file_path: str = ""
    file_size: int = 0
    error_msg: str = ""
    speed: float = 0.0


@dataclass
class HistoryRecord:
    id: str
    bvid: str
    title: str
    author: str
    author_mid: int
    download_type: str
    status: str
    file_path: str
    file_size: int
    quality: int
    created_at: str
    video_publish_time: int
    error_msg: Optional[str] = None
    pic_url: str = ""


@dataclass
class AppConfig:
    download_dir: str = "./downloads"
    max_concurrent: int = 3
    preferred_quality: int = 80
    request_interval_ms: int = 300
    cover_fill_mode: str = "solid_color"
    cover_fill_color: list[int] = field(default_factory=lambda: [0, 0, 0])
    cover_blur_radius: int = 40
    filename_template: str = "{title}_{bvid}"
    sessdata: str = ""
    bili_jct: str = ""
    buvid3: str = ""
    dedeuserid: str = ""
    ac_time_value: str = ""
    data_dir: str = "./data"
