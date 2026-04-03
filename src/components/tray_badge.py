"""Enhanced tray icon with message count badge"""
from pathlib import Path
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtSvg import QSvgRenderer


class TrayIconWithBadge:
    """Manages tray icon with message count badge"""
    
    def __init__(self, icons_path: Path):
        self.icons_path = icons_path
        
    def create_icon(self, count: int = 0) -> QIcon:
        """Create tray icon - full badge when count > 0, normal icon otherwise"""
        
        if count > 0:
            # Show badge instead of chat icon
            return self._create_badge_icon(count)
        else:
            # Show chat icon
            return self._create_normal_icon()
    
    def _create_normal_icon(self) -> QIcon:
        """Create normal chat icon"""
        icon_file = self.icons_path / "chat.svg"
        
        # Load base icon
        with open(icon_file, 'r') as f:
            svg = f.read().replace('fill="currentColor"', 'fill="#e28743"')
        
        renderer = QSvgRenderer()
        renderer.load(svg.encode('utf-8'))
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        
        return QIcon(pixmap)
    
    def _create_badge_icon(self, count: int) -> QIcon:
        """Create full-size badge icon with count - simple square badge"""
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Badge text
        text = str(count) if count < 100 else "99"
        
        # Square badge
        badge_size = 58
        badge_x = 3
        badge_y = 3
        
        # Draw rounded square
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#FF3B30"))
        painter.drawRoundedRect(badge_x, badge_y, badge_size, badge_size, 10, 10)
        
        # Draw count text
        font = QFont("Segoe UI", 32, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF"))
        
        text_rect = QRect(badge_x, badge_y, badge_size, badge_size)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)
        
        painter.end()
        return QIcon(pixmap)
