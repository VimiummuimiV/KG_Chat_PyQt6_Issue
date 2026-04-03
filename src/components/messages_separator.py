"""Message Separator Components"""
from PyQt6.QtGui import QPainter, QColor, QFontMetrics, QPen
from PyQt6.QtCore import Qt, QRect, QModelIndex
from datetime import datetime


SEPARATOR_HEIGHT = 40

# Color palette constants
_COLORS_DARK = {
    'emphasis_line': "#FF6B6B",
    'normal_line': "#444444",
    'bg': "#2A2A2A",
    'emphasis_text': "#FFB4B4",
    'normal_text': "#AAAAAA"
}

_COLORS_LIGHT = {
    'emphasis_line': "#FF4444",
    'normal_line': "#BBBBBB",
    'bg': "#E8E8E8",
    'emphasis_text': "#CC0000",
    'normal_text': "#444444"
}


def _get_separator_colors(is_dark_theme: bool, is_emphasis: bool = False):
    """Get theme-adaptive colors: (line_color, bg_color, text_color)"""
    palette = _COLORS_DARK if is_dark_theme else _COLORS_LIGHT
    line_key = 'emphasis_line' if is_emphasis else 'normal_line'
    text_key = 'emphasis_text' if is_emphasis else 'normal_text'
    return QColor(palette[line_key]), QColor(palette['bg']), QColor(palette[text_key])


def _render_separator(
    painter: QPainter,
    rect: QRect,
    text: str,
    font,
    line_color: QColor,
    bg_color: QColor,
    text_color: QColor,
    line_width: int = 2,
    line_end_offset: int = 20,
    text_h_padding: int = 20,
    text_v_padding: int = 6,
    box_radius: int = 4,
    text_position: str = "center"
):
    """Render separator with configurable styling"""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    
    mid_y = rect.y() + rect.height() // 2
    
    # Draw horizontal line
    painter.setPen(QPen(line_color, line_width))
    painter.drawLine(rect.x() + 20, mid_y, rect.x() + rect.width() - line_end_offset, mid_y)
    
    # Calculate text dimensions
    painter.setFont(font)
    fm = QFontMetrics(font)
    text_width = fm.horizontalAdvance(text) + text_h_padding
    text_height = fm.height() + text_v_padding
    
    # Position text box
    if text_position == "right":
        text_x = rect.x() + rect.width() - text_width - 20
    else:
        text_x = rect.x() + (rect.width() - text_width) // 2
    text_y = mid_y - text_height // 2
    
    # Draw background box
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(bg_color)
    painter.drawRoundedRect(text_x, text_y, text_width, text_height, box_radius, box_radius)
    
    # Draw text
    painter.setPen(text_color)
    painter.drawText(
        QRect(text_x, text_y, text_width, text_height),
        Qt.AlignmentFlag.AlignCenter,
        text
    )
    
    painter.restore()


class NewMessagesSeparator:
    """Separator for marking new messages with 🔥 emoji"""
    
    @staticmethod
    def create_marker():
        from ui.message_model import MessageData
        return MessageData(timestamp=datetime.now(), is_new_messages_marker=True)
    
    @staticmethod
    def render(painter: QPainter, rect: QRect, font, is_dark_theme: bool):
        line_color, bg_color, text_color = _get_separator_colors(is_dark_theme, is_emphasis=True)
        _render_separator(
            painter,
            rect,
            "🔥",
            font,
            line_color,
            bg_color,
            text_color,
            line_end_offset=80,
            text_position="right"
        )
    
    @staticmethod
    def get_height() -> int:
        return SEPARATOR_HEIGHT
    
    @staticmethod
    def remove_from_model(model):
        if not hasattr(model, '_messages') or not model._messages:
            return
        
        marker_indices = [i for i, msg in enumerate(model._messages) 
                         if getattr(msg, 'is_new_messages_marker', False)]
        
        for index in reversed(marker_indices):
            model.beginRemoveRows(QModelIndex(), index, index)
            model._messages.pop(index)
            model.endRemoveRows()


class ChatlogDateSeparator:
    """Separator for displaying dates in chatlog"""
    
    @staticmethod
    def render(painter: QPainter, rect: QRect, date_str: str, font, is_dark_theme: bool):
        line_color, bg_color, text_color = _get_separator_colors(is_dark_theme, is_emphasis=False)
        _render_separator(
            painter,
            rect,
            date_str,
            font,
            line_color,
            bg_color,
            text_color
        )
    
    @staticmethod
    def get_height() -> int:
        return SEPARATOR_HEIGHT
