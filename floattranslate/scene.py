"""Stable visual comparisons that ignore tiny caret/antialiasing noise."""
from dataclasses import dataclass
import hashlib

from PIL import Image, ImageChops


@dataclass
class Scene:
    size: tuple[int, int]
    digest: bytes
    preview: Image.Image

    @classmethod
    def capture(cls, image):
        preview = image.convert("L")
        preview.thumbnail((320,320), Image.Resampling.BILINEAR)
        return cls(image.size, hashlib.blake2b(image.tobytes(),digest_size=16).digest(),preview)

    @property
    def fingerprint(self):
        return self.size,self.digest


def changed(previous: Scene | None, current: Scene) -> bool:
    if previous is None or previous.size != current.size:
        return True
    if previous.digest == current.digest:
        return False
    difference = ImageChops.difference(previous.preview,current.preview)
    significant = difference.point(lambda value:255 if value>=20 else 0)
    bounds = significant.getbbox()
    if not bounds or bounds[2]-bounds[0]<3 or bounds[3]-bounds[1]<3:
        return False
    pixels = significant.histogram()[255]
    return pixels >= max(12,round(significant.width*significant.height*0.0003))
