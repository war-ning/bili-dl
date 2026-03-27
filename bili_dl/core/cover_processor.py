"""封面图片处理：正方形填充"""

from pathlib import Path

from PIL import Image, ImageFilter

from ..models import CoverFillMode


class CoverProcessor:
    """封面正方形填充处理"""

    def make_square_solid(
        self,
        input_path: Path,
        output_path: Path,
        fill_color: tuple[int, int, int] = (0, 0, 0),
    ) -> None:
        """纯色填充为正方形"""
        with Image.open(input_path) as img:
            img = img.convert("RGB")
            w, h = img.size
            side = max(w, h)
            canvas = Image.new("RGB", (side, side), fill_color)
            offset = ((side - w) // 2, (side - h) // 2)
            canvas.paste(img, offset)
            canvas.save(output_path, "JPEG", quality=95)

    def make_square_blur(
        self,
        input_path: Path,
        output_path: Path,
        blur_radius: int = 40,
    ) -> None:
        """模糊背景填充为正方形"""
        with Image.open(input_path) as img:
            img = img.convert("RGB")
            w, h = img.size
            side = max(w, h)
            bg = img.resize((side, side), Image.LANCZOS)
            bg = bg.filter(ImageFilter.GaussianBlur(radius=blur_radius))
            offset = ((side - w) // 2, (side - h) // 2)
            bg.paste(img, offset)
            bg.save(output_path, "JPEG", quality=95)

    def process(
        self,
        input_path: Path,
        output_path: Path,
        mode: CoverFillMode = CoverFillMode.SOLID_COLOR,
        fill_color: tuple[int, int, int] = (0, 0, 0),
        blur_radius: int = 40,
    ) -> None:
        """根据模式处理封面"""
        if mode == CoverFillMode.BLUR:
            self.make_square_blur(input_path, output_path, blur_radius)
        else:
            self.make_square_solid(input_path, output_path, fill_color)
