"""UP 主信息与视频列表"""

from __future__ import annotations

from typing import Callable, Optional, Awaitable

from bilibili_api.user import User, VideoOrder

from ..models import UPInfo, VideoInfo
from ..utils.formatter import parse_duration_str
from .client import BiliClient, with_risk_retry


async def get_user_videos(
    client: BiliClient,
    mid: int,
    page: int = 1,
    page_size: int = 30,
    order: VideoOrder = VideoOrder.PUBDATE,
) -> tuple[list[VideoInfo], int]:
    """获取 UP 主视频列表（单页），返回 (视频列表, 总视频数)"""
    await client.throttle()

    u = User(uid=mid, credential=client.credential)
    result = await with_risk_retry(
        lambda: u.get_videos(pn=page, ps=page_size, order=order),
        op_name="视频列表",
    )

    total = result.get("page", {}).get("count", 0)
    videos: list[VideoInfo] = []

    for item in result.get("list", {}).get("vlist", []):
        pic_url = item.get("pic", "")
        if pic_url.startswith("//"):
            pic_url = "https:" + pic_url

        play = item.get("play", 0)
        if not isinstance(play, int):
            play = 0

        videos.append(VideoInfo(
            bvid=item.get("bvid", ""),
            title=item.get("title", ""),
            pic_url=pic_url,
            duration=parse_duration_str(item.get("length", "0:00")),
            play_count=play,
            publish_time=item.get("created", 0),
            is_charge_plus=(
                item.get("is_charging_arc", 0) == 1
                or item.get("is_charge_plus", 0) == 1
            ),
            author_name=item.get("author", ""),
            author_mid=item.get("mid", mid),
        ))

    return videos, total


async def get_all_user_videos(
    client: BiliClient,
    mid: int,
    order: VideoOrder = VideoOrder.PUBDATE,
    on_progress: Optional[Callable[[int, int], Awaitable[None] | None]] = None,
) -> list[VideoInfo]:
    """分页获取 UP 主全部视频"""
    all_videos: list[VideoInfo] = []
    page = 1
    page_size = 30

    while True:
        videos, total = await get_user_videos(client, mid, page, page_size, order)
        all_videos.extend(videos)

        if on_progress:
            result = on_progress(len(all_videos), total)
            if hasattr(result, "__await__"):
                await result

        if page * page_size >= total or not videos:
            break
        page += 1

    return all_videos
