from pydantic import BaseModel, Field, field_validator
import yaml

import os
from pathlib import Path

WORKSPACE = r"C:\Users\jche774\Majar\Projects\jason-2026-differential-phase-contrast\workspace"
CONFIG_PATH = os.path.join(WORKSPACE, "config.yaml")
CONFIG_TEMPLATE_PATH = os.path.join(WORKSPACE, "config.template.yaml")
    
class CameraConfig(BaseModel):
    acquisition_frame_rate: float = Field(alias="AcquisitionFrameRate")
    exposure_time: float = Field(alias="ExposureTime")
    offset_x: int = Field(alias="OffsetX")
    offset_y: int = Field(alias="OffsetY")
    width: int = Field(alias="Width")
    height: int = Field(alias="Height")
    pixel_format: str = Field(alias="PixelFormat")

    @field_validator("pixel_format", mode="after")
    def validate_pixel_format(cls, format: str):
        if format in ['Mono8', 'Mono16']:
            return format
        raise ValueError("Pixel format has to be either 'Mono8' or 'Mono16'")
    
class ImageAcquisitionConfig(BaseModel):
    image_save_dir: Path
    camera: CameraConfig

    @field_validator("image_save_dir", mode="after")
    def resolve_image_save_dir(cls, p: Path):
        if not p.is_absolute():
            p = WORKSPACE / p
        p.mkdir(parents=True, exist_ok=True)

        return p

class AppConfig(BaseModel):
    """Root configuration model"""
    version: str
    image_acquisition: ImageAcquisitionConfig

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
