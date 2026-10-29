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
from PySide6.QtCore import QEventLoop, QThreadPool, QTimer
from floattranslate.ocr import create_ocr
from floattranslate.tasks import Task
application = QApplication([])
engine = create_ocr()
image = Image.new('RGB', (1100,220), 'white')
font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 64)
ImageDraw.Draw(image).text((40,60), 'FloatTranslate test 123', fill='black', font=font)
pool = QThreadPool()
pool.setMaxThreadCount(1)
for language in ('', 'en-US', ''):
    loop = QEventLoop()
    outcome = []
    def work():
        import traceback
        try:
            return engine.regions(image, language)
        except Exception:
            original_error = traceback.format_exc()
            import io, Vision, Foundation, objc
            with objc.autorelease_pool():
                buffer = io.BytesIO()
                image.save(buffer,format='PNG')
                content = buffer.getvalue()
                data = Foundation.NSData.dataWithBytes_length_(content,len(content))
                import subprocess
                for native_language in ('','en-US'):
                    for flags in (['--fast'],['--cpu'],['--fast','--cpu'],['--revision2']):
                        native = subprocess.run(['native/vision-ocr',native_language]+flags,input=content,capture_output=True)
                        print('native Swift OCR:',repr(native_language),flags,native.returncode,native.stdout.decode(),native.stderr.decode(),flush=True)
                for revision in (3,2):
                    for auto in (False,True):
                        request = Vision.VNRecognizeTextRequest.alloc().init()
                        request.setRevision_(revision)
                        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
                        if auto: request.setAutomaticallyDetectsLanguage_(True)
                        else: request.setRecognitionLanguages_(['en-US'])
                        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data,Foundation.NSDictionary.dictionary())
                        try:
                            ok,error = handler.performRequests_error_([request],None)
                            print('probe',revision,auto,ok,str(error),flush=True)
                        except Exception as error:
                            print('probe exception',revision,auto,str(error),flush=True)
            return original_error
    task = Task(language, work)
    def finished(payload):
        outcome.append(payload)
        loop.quit()
    task.signals.finished.connect(finished)
    QTimer.singleShot(40000, loop.quit)
    pool.start(task)
    loop.exec()
    assert outcome, 'Qt OCR timed out'
    identity, regions, error = outcome[0]
    assert not error and not isinstance(regions,str), (language, error, regions)
    assert 'test 123' in ' '.join(item.text for item in regions).lower()
    print('Qt worker OCR success:', repr(language), flush=True)
pool.waitForDone()
with ThreadPoolExecutor(max_workers=1) as pool:
    for language in ('', 'en-US', ''):
        regions = pool.submit(engine.regions, image, language).result(timeout=40)
        text = ' '.join(item.text for item in regions)
        assert 'test 123' in text.lower(), (language, text)
        print('worker OCR success:', repr(language), flush=True)
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
                            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"), capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
