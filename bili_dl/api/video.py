"""视频详情与下载地址"""

from __future__ import annotations

from typing import Optional

from bilibili_api.video import Video

from ..exceptions import BiliDLError
from .client import BiliClient


async def get_video_pages(
    client: BiliClient,
    bvid: str,
) -> list[dict]:
    """获取视频分P列表"""
    await client.throttle()
    v = Video(bvid=bvid, credential=client.credential)
    return await v.get_pages()


async def get_video_info(
    client: BiliClient,
    bvid: str,
) -> dict:
    """获取视频完整信息"""
    await client.throttle()
    v = Video(bvid=bvid, credential=client.credential)
    return await v.get_info()


async def get_download_url(
    client: BiliClient,
    bvid: str,
    cid: int,
) -> dict:
    """获取视频下载地址（DASH 格式）"""
    await client.throttle()
    v = Video(bvid=bvid, credential=client.credential)
    return await v.get_download_url(cid=cid)


async def get_best_streams(
    client: BiliClient,
    bvid: str,
    cid: int,
) -> tuple[Optional[dict], Optional[dict]]:
    """获取最佳视频流和音频流 URL

    Returns:
        (video_stream, audio_stream) 各包含 url, bandwidth 等信息
    """
    data = await get_download_url(client, bvid, cid)

    dash = data.get("dash")
    if not dash:
        durl = data.get("durl", [])
        if durl:
            return {"url": durl[0]["url"], "type": "flv"}, None
        return None, None

    # 选最高质量视频流
    video_streams = dash.get("video", [])
    best_video = None
    if video_streams:
        sorted_vs = sorted(video_streams, key=lambda x: x.get("bandwidth", 0), reverse=True)
        vs = sorted_vs[0]
        best_video = {
            "url": vs.get("base_url") or vs.get("baseUrl", ""),
            "backup_url": vs.get("backup_url") or vs.get("backupUrl", []),
            "bandwidth": vs.get("bandwidth", 0),
            "codecs": vs.get("codecs", ""),
            "width": vs.get("width", 0),
            "height": vs.get("height", 0),
            "quality": vs.get("id", 0),
        }

    # 选最高质量音频流
    audio_streams = dash.get("audio", [])
    best_audio = None
    if audio_streams:
        sorted_as = sorted(audio_streams, key=lambda x: x.get("bandwidth", 0), reverse=True)
        aus = sorted_as[0]
        best_audio = {
            "url": aus.get("base_url") or aus.get("baseUrl", ""),
            "backup_url": aus.get("backup_url") or aus.get("backupUrl", []),
            "bandwidth": aus.get("bandwidth", 0),
            "codecs": aus.get("codecs", ""),
            "quality": aus.get("id", 0),
        }

    return best_video, best_audio


async def get_audio_stream(
    client: BiliClient,
    bvid: str,
    cid: int,
) -> Optional[dict]:
    """获取最佳音频流

    优先 DASH 独立音频流，不可用时回退到 durl 合流（需后续提取音频）
    """
    data = await get_download_url(client, bvid, cid)

    # 优先 DASH 音频流
    dash = data.get("dash")
    if dash:
        audio_streams = dash.get("audio", [])
        if audio_streams:
            best = max(audio_streams, key=lambda x: x.get("bandwidth", 0))
            return {
                "url": best.get("base_url") or best.get("baseUrl", ""),
                "backup_url": best.get("backup_url") or best.get("backupUrl", []),
                "bandwidth": best.get("bandwidth", 0),
                "codecs": best.get("codecs", ""),
                "quality": best.get("id", 0),
            }

    # 回退 durl 合流（包含视频+音频，需后续提取音频轨道）
    durl = data.get("durl", [])
    if durl:
        return {
            "url": durl[0]["url"],
            "type": "durl",  # 标记为合流格式
        }

    return None
