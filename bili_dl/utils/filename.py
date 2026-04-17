"""文件名清洗与路径构建"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
MAX_FILENAME_LEN = 80

# 默认命名模板
DEFAULT_TEMPLATE = "{title}_{bvid}"


def sanitize_filename(name: str) -> str:
    """清洗文件名：替换非法字符、去首尾空白、截断"""
    name = ILLEGAL_CHARS.sub("_", name).strip()
    name = re.sub(r"_+", "_", name).strip("_. ")
    if not name:
        name = "untitled"
    if len(name) > MAX_FILENAME_LEN:
        name = name[:MAX_FILENAME_LEN].rstrip("_. ")
    return name


def apply_filename_template(
    template: str,
    title: str,
    bvid: str,
    author: str = "",
    date: str = "",
    season: str = "",
    episode: int = 0,
) -> str:
    """根据模板生成文件名

    支持的变量:
        {title}   — 视频标题
        {bvid}    — BV 号
        {author}  — UP 主名
        {date}    — 发布日期 (YYYY-MM-DD)
        {season}  — 合集名 (仅合集下载模式)
        {episode} — 合集内序号，支持格式化 {episode:02d} (仅合集下载模式)
    """
    result = template.format(
        title=title,
        bvid=bvid,
        author=author,
        date=date,
        season=season,
        episode=episode,
    )
    return sanitize_filename(result)


def build_file_path(
    download_dir: Path,
    author_name: str,
    title: str,
    bvid: str,
    ext: str,
    template: str = DEFAULT_TEMPLATE,
    date: str = "",
    season: str = "",
    episode: int = 0,
) -> Path:
    """构建完整文件路径

    普通模式：download_dir/author_name/<template>.ext
    合集模式：download_dir/author_name/<season>/<template>.ext
    """
    safe_author = sanitize_filename(author_name) or "unknown"
    filename_stem = apply_filename_template(
        template, title=title, bvid=bvid, author=author_name, date=date,
        season=season, episode=episode,
    )
    filename = f"{filename_stem}{ext}"

    parent = download_dir / safe_author
    if season:
        parent = parent / sanitize_filename(season)

    full_path = parent / filename

    # Windows 路径长度检查
    if sys.platform == "win32" and len(str(full_path)) > 250:
        # 回退到截断标题 + bvid
        safe_title = sanitize_filename(title)
        max_title = 250 - len(str(parent / f"_{bvid}{ext}"))
        if max_title > 10:
            safe_title = safe_title[:max_title].rstrip("_. ")
        else:
            safe_title = safe_title[:10]
        filename = f"{safe_title}_{bvid}{ext}"
        full_path = parent / filename

    return ensure_unique_path(full_path)


def ensure_unique_path(path: Path) -> Path:
    """如果路径已存在，追加序号"""
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2
    while True:
        new_path = parent / f"{stem}_{counter}{suffix}"
        if not new_path.exists():
            return new_path
        counter += 1
