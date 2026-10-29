"""Real Vision smoke tests, including the default UI language and worker path."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != "darwin", reason="Requires real Apple Vision")
def test_default_and_explicit_ocr_in_worker():
    script = r'''
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtWidgets import QApplication
from floattranslate.ocr import create_ocr
application = QApplication([])
engine = create_ocr()
image = Image.new('RGB', (1100,220), 'white')
font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 64)
ImageDraw.Draw(image).text((40,60), 'FloatTranslate test 123', fill='black', font=font)
with ThreadPoolExecutor(max_workers=1) as pool:
    for language in ('en-US', '', ''):
        regions = pool.submit(engine.regions, image, language).result(timeout=40)
        text = ' '.join(item.text for item in regions)
        assert 'test 123' in text.lower(), (language, text)
        print('worker OCR success:', repr(language), flush=True)
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
                            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"), capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
