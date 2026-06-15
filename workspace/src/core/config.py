from pydantic import BaseModel, field_validator
import yaml

import os
from typing import Any
from pathlib import Path

WORKSPACE = "/workspace"
CONFIG_PATH = os.path.join(WORKSPACE, "config.yaml")
CONFIG_TEMPLATE_PATH = os.path.join(WORKSPACE, "config.template.yaml")

class CameraConfig(BaseModel):
    image_save_dir: Path
    attributes: dict[str, int]

    @field_validator("image_save_dir", mode="after")
    def resolve_image_save_dir(cls, p: Path):
        if not p.is_absolute():
            p = WORKSPACE / p
        p.mkdir(parents=True, exist_ok=True)

        return p

class AppConfig(BaseModel):
    """Root configuration model"""
    version: str
    camera: CameraConfig

    @classmethod
    def load(cls, path: str | Path) -> "AppConfig":
        path = Path(path)

        if not path.is_file():
            path = Path(CONFIG_TEMPLATE_PATH)
        if not path.is_file():
            raise FileNotFoundError(f"Config not found: {path}")

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(data)


class AppConfigManager():
    config: AppConfig
    default_config: AppConfig = AppConfig.load(CONFIG_TEMPLATE_PATH)

    @classmethod
    def load_config(cls):
        cls.config = AppConfig.load(CONFIG_PATH)


AppConfigManager.load_config()
