import requests
from pathlib import Path
from typing import Optional
from PyQt6.QtGui import QPixmap, QPainter, QPainterPath
from PyQt6.QtCore import Qt, QRectF

def fetch_avatar_bytes(user_id: str, timeout: int = 3):
    try:
        r = requests.get(f"https://klavogonki.ru/storage/avatars/{user_id}_big.png", timeout=timeout)
        return r.content if r.status_code == 200 else None
    except: return None

def load_avatar_from_disk(path) -> Optional[QPixmap]:
    try:
        px = QPixmap(); px.load(str(path))
        return px if not px.isNull() else None
    except: return None

def make_rounded_pixmap(pixmap: QPixmap, size: int, radius: int = 10) -> QPixmap:
    # Create rounded rectangle pixmap with smooth scaling
    scaled = pixmap.scaled(
        size, size, 
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation
    )
    
    output = QPixmap(size, size)
    output.fill(Qt.GlobalColor.transparent)
    
    painter = QPainter(output)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    
    # Rounded rectangle clipping path
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    painter.setClipPath(path)
    
    # Center and draw
    x = (size - scaled.width()) // 2
    y = (size - scaled.height()) // 2
    painter.drawPixmap(x, y, scaled)
    painter.end()
    
    return output
