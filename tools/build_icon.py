"""Render the app's vector mark into a multi-resolution Windows icon."""

from pathlib import Path

from PIL import Image
from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer

assets = Path(__file__).resolve().parents[1] / 'ui' / 'assets'
image = QImage(256, 256, QImage.Format.Format_RGBA8888)
image.fill(0)
painter = QPainter(image)
QSvgRenderer(str(assets / 'app.svg')).render(painter, QRectF(0, 0, 256, 256))
painter.end()
bitmap = Image.frombytes('RGBA', (256, 256), image.bits().asstring(image.sizeInBytes()))
bitmap.save(assets / 'app.ico', sizes=[(size, size) for size in (16, 24, 32, 48, 64, 128, 256)])
