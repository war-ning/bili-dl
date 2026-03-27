"""搜索 UP 主"""

from __future__ import annotations

from bilibili_api import search as bili_search
from bilibili_api.search import SearchObjectType, OrderUser

from ..models import UPInfo
from .client import BiliClient


async def search_users(
    client: BiliClient,
    keyword: str,
    page: int = 1,
    order: OrderUser = OrderUser.FANS,
) -> tuple[list[UPInfo], int]:
    """搜索 UP 主，返回 (结果列表, 总数)"""
    await client.throttle()

    result = await bili_search.search_by_type(
        keyword=keyword,
        search_type=SearchObjectType.USER,
        order_type=order,
        page=page,
    )

    total = result.get("numResults", 0)
    users: list[UPInfo] = []

    for item in result.get("result", []):
        face_url = item.get("upic", "")
        if face_url.startswith("//"):
            face_url = "https:" + face_url

        users.append(UPInfo(
            mid=item.get("mid", 0),
            name=item.get("uname", ""),
            face_url=face_url,
            fans=item.get("fans", 0),
            videos=item.get("videos", 0),
            sign=item.get("usign", ""),
            level=item.get("level", 0),
        ))

    return users, total
