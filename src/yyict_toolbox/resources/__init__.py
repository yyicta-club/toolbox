import sys
from pathlib import Path


def logo_path() -> Path:
    """返回 logo 图片路径；冻结打包后从 PyInstaller 解包目录读取。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "resources" / "logo.png"
    return Path(__file__).resolve().parent / "logo.png"


def image_path(name: str) -> Path:
    """返回 resources/images 下指定图片的路径；冻结打包后从 PyInstaller 解包目录读取。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "resources" / "images" / name
    return Path(__file__).resolve().parent / "images" / name
