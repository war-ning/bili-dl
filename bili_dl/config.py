"""配置管理"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from bilibili_api import Credential

from .models import AppConfig


class ConfigManager:
    """管理 config.json 的读写"""

    def __init__(self, data_dir: str = "./data"):
        self._data_dir = Path(data_dir)
        self._config_path = self._data_dir / "config.json"
        self._config: Optional[AppConfig] = None

    def load(self) -> AppConfig:
        """加载配置文件，不存在则创建默认配置"""
        if self._config_path.exists():
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._config = AppConfig(**{
                k: v for k, v in data.items()
                if k in AppConfig.__dataclass_fields__
            })
        else:
            self._config = AppConfig(data_dir=str(self._data_dir))
            self.save(self._config)
        return self._config

    def save(self, config: AppConfig) -> None:
        """保存配置到 JSON"""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._config = config
        data = asdict(config)
        data.pop("data_dir", None)  # data_dir 由 ConfigManager 控制，不持久化
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_credential(self) -> Optional[Credential]:
        """从配置构建 Credential 对象，Cookie 为空则返回 None"""
        cfg = self._config or self.load()
        if not cfg.sessdata:
            return None
        return Credential(
            sessdata=cfg.sessdata,
            bili_jct=cfg.bili_jct,
            buvid3=cfg.buvid3,
            dedeuserid=cfg.dedeuserid,
            ac_time_value=cfg.ac_time_value,
        )

    def has_credential(self) -> bool:
        cfg = self._config or self.load()
        return bool(cfg.sessdata)

    def get_download_dir(self) -> Path:
        cfg = self._config or self.load()
        p = Path(cfg.download_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def get_history_path(self) -> Path:
        return self._data_dir / "history.json"

    @property
    def config(self) -> AppConfig:
        if self._config is None:
            self.load()
        return self._config  # type: ignore
