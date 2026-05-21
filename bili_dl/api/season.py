"""UP 主合集 (season/series) 接口封装"""

from __future__ import annotations

from typing import Callable, Optional, Awaitable

from bilibili_api.user import User
from bilibili_api.channel_series import ChannelOrder

from ..models import SectionInfo, SeasonInfo, VideoInfo
from .client import BiliClient, with_risk_retry
from .video import get_video_info


# B站合集名常以"合集·"或"系列·"作 UP 端前缀，去之以免进落盘目录
_SEASON_PREFIXES = ("合集·", "系列·")


def _clean_season_title(raw: str) -> str:
    t = (raw or "").strip()
    for pre in _SEASON_PREFIXES:
        if t.startswith(pre):
            return t[len(pre):].strip()
    return t


_with_retry = with_risk_retry  # 兼容旧名


async def get_user_seasons(
    client: BiliClient,
    mid: int,
) -> list[SeasonInfo]:
    """拉取 UP 主所有合集 (season + series)，合并返回

    返回顺序：season 在前、series 在后；各自按 API 原序。
    """
    u = User(uid=mid, credential=client.credential)
    seasons: list[SeasonInfo] = []

    page = 1
    page_size = 20
    while True:
        await client.throttle()
        result = await _with_retry(
            lambda: u.get_channel_list(pn=page, ps=page_size),
            op_name="合集列表",
        )

        items = result.get("items_lists", {})
        season_list = items.get("seasons_list") or []
        series_list = items.get("series_list") or []

        for s in season_list:
            meta = s.get("meta") or {}
            seasons.append(SeasonInfo(
                sid=int(meta.get("season_id", 0)),
                mid=int(meta.get("mid", mid)),
                title=_clean_season_title(meta.get("name", "")),
                cover=meta.get("cover", ""),
                total=int(meta.get("total", 0)),
                type="season",
            ))

        for s in series_list:
            meta = s.get("meta") or {}
            seasons.append(SeasonInfo(
                sid=int(meta.get("series_id", 0)),
                mid=int(meta.get("mid", mid)),
                title=_clean_season_title(meta.get("name", "")),
                cover=meta.get("cover", ""),
                total=int(meta.get("total", 0)),
                type="series",
            ))

        page_info = items.get("page") or {}
        total = int(page_info.get("total", len(seasons)))
        if page * page_size >= total or (not season_list and not series_list):
            break
        page += 1

    return seasons


async def get_all_season_videos(
    client: BiliClient,
    season: SeasonInfo,
    on_progress: Optional[Callable[[int, int], Awaitable[None] | None]] = None,
) -> list[VideoInfo]:
    """拉取某合集下全部视频，按合集升序编号 (episode_index 从 1 起)

    ChannelOrder 在两种 API 下语义不同，故此分类调用：
      season:  sort_reverse=False (DEFAULT → False) 得升序
      series:  sort="asc"        (CHANGE  → "asc") 得升序
    """
    u = User(uid=season.mid, credential=client.credential)

    videos: list[VideoInfo] = []
    page = 1
    page_size = 100
    while True:
        await client.throttle()
        if season.type == "season":
            result = await _with_retry(
                lambda: u.get_channel_videos_season(
                    sid=season.sid, sort=ChannelOrder.DEFAULT,
                    pn=page, ps=page_size,
                ),
                op_name="合集视频",
            )
        else:
            result = await _with_retry(
                lambda: u.get_channel_videos_series(
                    sid=season.sid, sort=ChannelOrder.CHANGE,
                    pn=page, ps=page_size,
                ),
                op_name="列表视频",
            )

        archives = result.get("archives") or []
        if not archives:
            break

        for item in archives:
            pic_url = item.get("pic", "")
            if pic_url.startswith("//"):
                pic_url = "https:" + pic_url

            stat = item.get("stat") or {}
            play = stat.get("view", 0) if isinstance(stat, dict) else 0

            videos.append(VideoInfo(
                bvid=item.get("bvid", ""),
                title=item.get("title", ""),
                pic_url=pic_url,
                duration=int(item.get("duration", 0) or 0),
                play_count=int(play or 0),
                publish_time=int(item.get("pubdate", 0) or 0),
                is_charge_plus=bool(item.get("ugc_pay", 0)),
                author_name="",  # 合集 archives 不含 up 名，由调用方补
                author_mid=season.mid,
                season_title=season.title,
                episode_index=len(videos) + 1,
            ))

        page_info = result.get("page") or {}
        total = int(page_info.get("total", 0) or 0)
        if on_progress:
            r = on_progress(len(videos), total)
            if hasattr(r, "__await__"):
                await r

        if total and len(videos) >= total:
            break
        if len(archives) < page_size:
            break
        page += 1

    return videos


async def get_first_season_bvid(
    client: BiliClient,
    season: SeasonInfo,
) -> Optional[str]:
    """取合集首视频 bvid，以驱动后续分节探测"""
    await client.throttle()
    u = User(uid=season.mid, credential=client.credential)
    if season.type == "season":
        r = await _with_retry(
            lambda: u.get_channel_videos_season(
                sid=season.sid, sort=ChannelOrder.DEFAULT, pn=1, ps=1,
            ),
            op_name="首视频探测",
        )
    else:
        r = await _with_retry(
            lambda: u.get_channel_videos_series(
                sid=season.sid, sort=ChannelOrder.CHANGE, pn=1, ps=1,
            ),
            op_name="首视频探测",
        )
    arc = r.get("archives") or []
    return arc[0].get("bvid") if arc else None


async def get_season_sections_by_bvid(
    client: BiliClient,
    bvid: str,
) -> tuple[str, list[tuple[SectionInfo, list[VideoInfo]]]]:
    """以合集内任一视频 bvid，取整个合集的分节与全部视频

    数据源：/x/web-interface/view → data.ugc_season.sections[*]

    Returns:
        (season_title, [(SectionInfo, [VideoInfo, ...]), ...])
        一次请求即取全；若视频不属任何合集，返回 ("", [])
    """
    await client.throttle()
    info = await _with_retry(
        lambda: get_video_info(client, bvid), op_name="视频详情",
    )
    ugc = info.get("ugc_season") or {}
    if not ugc:
        return "", []

    season_title = _clean_season_title(ugc.get("title", ""))
    sections_raw = ugc.get("sections") or []

    result: list[tuple[SectionInfo, list[VideoInfo]]] = []
    for sec in sections_raw:
        episodes = sec.get("episodes") or []
        section = SectionInfo(
            section_id=int(sec.get("id", 0)),
            title=(sec.get("title") or "").strip(),
            episode_count=len(episodes),
        )
        videos: list[VideoInfo] = []
        for idx, ep in enumerate(episodes, 1):
            arc = ep.get("arc") or {}
            pic_url = arc.get("pic", "")
            if pic_url.startswith("//"):
                pic_url = "https:" + pic_url
            stat = arc.get("stat") or {}
            author = arc.get("author") or {}
            rights = arc.get("rights") or {}
            # ep.attribute 是位图；实测 bit 3 (值 8) 标"充电专属"
            # 合集级 is_chargeable_season 与 rights.* 亦兼看以免漏
            is_charge = (
                bool(int(ep.get("attribute", 0)) & 8)
                or bool(arc.get("is_chargeable_season"))
                or bool(rights.get("pay"))
                or bool(rights.get("ugc_pay"))
                or bool(rights.get("arc_pay"))
            )
            videos.append(VideoInfo(
                bvid=ep.get("bvid", ""),
                title=(ep.get("title") or arc.get("title") or "").strip(),
                pic_url=pic_url,
                duration=int(arc.get("duration") or 0),
                play_count=int(stat.get("view") or 0),
                publish_time=int(arc.get("pubdate") or 0),
                is_charge_plus=is_charge,
                cid=int(ep.get("cid", 0)),
                author_name=author.get("name", ""),
                author_mid=int(author.get("mid", 0)),
                season_title=season_title,
                section_title=section.title,
                episode_index=idx,
            ))
        result.append((section, videos))

    return season_title, result


async def get_all_season_videos_with_sections(
    client: BiliClient,
    season: SeasonInfo,
) -> list[VideoInfo]:
    """获取合集全部视频，若为 SEASON 类型且有多分节则填 section_title

    SERIES (旧版列表) 无分节概念，直接扁平返回。
    SEASON 且 sections>=2：各视频 section_title 已填，按原节序拼接。
    SEASON 且 sections<=1：section_title 为空，扁平。
    """
    if season.type == "series":
        return await get_all_season_videos(client, season)

    first = await get_first_season_bvid(client, season)
    if not first:
        return []
    _, sections = await get_season_sections_by_bvid(client, first)

    videos: list[VideoInfo] = []
    single_section = len(sections) <= 1
    for _section, vs in sections:
        for v in vs:
            if single_section:
                v.section_title = ""  # 单节不分子目录
            videos.append(v)
    return videos
