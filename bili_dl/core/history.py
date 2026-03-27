"""下载历史 JSON 管理"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..models import (
    DownloadStatus,
    DownloadTask,
    DownloadType,
    HistoryRecord,
    VideoInfo,
)


class DownloadHistory:
    """JSON 文件管理下载历史记录"""

    def __init__(self, history_path: Path):
        self._path = history_path

    def _load(self) -> dict:
        if not self._path.exists():
            return {"version": 1, "records": []}
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"version": 1, "records": []}

    def _save(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(str(tmp_path), str(self._path))

    def add_record(self, task: DownloadTask) -> HistoryRecord:
        record = HistoryRecord(
            id=str(uuid.uuid4()),
            bvid=task.video_info.bvid,
            title=task.video_info.title,
            author=task.video_info.author_name,
            author_mid=task.video_info.author_mid,
            download_type=task.download_type.value,
            status=task.status.value,
            file_path=task.file_path,
            file_size=task.file_size,
            quality=task.quality,
            created_at=datetime.now().isoformat(timespec="seconds"),
            video_publish_time=task.video_info.publish_time,
            error_msg=task.error_msg or None,
            pic_url=task.video_info.pic_url,
        )

        data = self._load()
        data["records"].append(asdict(record))
        self._save(data)
        return record

    def get_all(self) -> list[HistoryRecord]:
        data = self._load()
        return [HistoryRecord(**r) for r in data.get("records", [])]

    def get_failed(self) -> list[HistoryRecord]:
        return [r for r in self.get_all() if r.status == DownloadStatus.FAILED.value]

    def get_by_status(self, status: DownloadStatus) -> list[HistoryRecord]:
        return [r for r in self.get_all() if r.status == status.value]

    def is_downloaded(self, bvid: str, download_type: str) -> bool:
        for r in self.get_all():
            if (
                r.bvid == bvid
                and r.download_type == download_type
                and r.status == DownloadStatus.COMPLETED.value
            ):
                return True
        return False

    def get_downloaded_path(self, bvid: str, download_type: str) -> Optional[str]:
        for r in reversed(self.get_all()):
            if (
                r.bvid == bvid
                and r.download_type == download_type
                and r.status == DownloadStatus.COMPLETED.value
            ):
                return r.file_path
        return None

    # #9: 新增删除和清空功能
    def delete_record(self, record_id: str) -> bool:
        """删除指定记录，返回是否成功"""
        data = self._load()
        original_len = len(data["records"])
        data["records"] = [r for r in data["records"] if r.get("id") != record_id]
        if len(data["records"]) < original_len:
            self._save(data)
            return True
        return False

    def delete_records(self, record_ids: list[str]) -> int:
        """批量删除记录，返回删除数量"""
        ids_set = set(record_ids)
        data = self._load()
        original_len = len(data["records"])
        data["records"] = [r for r in data["records"] if r.get("id") not in ids_set]
        deleted = original_len - len(data["records"])
        if deleted > 0:
            self._save(data)
        return deleted

    def clear_all(self) -> int:
        """清空全部历史，返回清除的记录数"""
        data = self._load()
        count = len(data["records"])
        if count > 0:
            data["records"] = []
            self._save(data)
        return count

    def record_to_task(self, record: HistoryRecord) -> DownloadTask:
        video_info = VideoInfo(
            bvid=record.bvid,
            title=record.title,
            pic_url=record.pic_url or "",
            duration=0,
            play_count=0,
            publish_time=record.video_publish_time,
            is_charge_plus=False,
            author_name=record.author,
            author_mid=record.author_mid,
        )
        return DownloadTask(
            video_info=video_info,
            download_type=DownloadType(record.download_type),
            quality=record.quality,
        )
