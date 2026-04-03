from pathlib import Path
from PyQt6.QtWidgets import QPushButton
from PyQt6.QtGui import QIcon, QPixmap, QPainter
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtSvg import QSvgRenderer
from PyQt6 import sip


# Global state
_icon_registry = []
_is_dark_theme = True

# Theme accent colors
_COLOR_DARK  = "#e28743"
_COLOR_LIGHT = "#154c79"
_COLOR_GRAY  = "#888888"


def set_theme(is_dark: bool):
    """Set current theme state"""
    global _is_dark_theme
    _is_dark_theme = is_dark


def get_user_svg_color(is_known: bool, is_dark: bool) -> str:
    """SVG icon color: theme accent for known users, gray for unknown."""
    return (_COLOR_DARK if is_dark else _COLOR_LIGHT) if is_known else _COLOR_GRAY


def _render_svg_icon(svg_file: Path, icon_size: int, color: str = None):
    """Render SVG file to QIcon with given or current-theme color"""
    if not svg_file.exists():
        return QIcon()
   
    with open(svg_file, 'r') as f:
        svg = f.read()
   
    color = color or (_COLOR_DARK if _is_dark_theme else _COLOR_LIGHT)
    svg = svg.replace('fill="currentColor"', f'fill="{color}"')
   
    renderer = QSvgRenderer()
    renderer.load(svg.encode('utf-8'))

    if isinstance(icon_size, int):
        icon_size = QSize(icon_size, icon_size)

    pixmap = QPixmap(icon_size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
   
    return QIcon(pixmap)

def create_icon_button(
    icons_path: Path,
    icon_name: str,
    tooltip: str = "",
    size_type: str = "large",
    config=None
):
    """Create icon button using sizes from config"""
    button = QPushButton()

    # Defaults from your config.json
    icon_size = 30 if size_type == "large" else 20
    button_size = 48 if size_type == "large" else 32

    # Safely read from config using .get()
    if config and hasattr(config, "get"):
        btn_cfg = config.get("ui", "buttons") or {}
        if isinstance(btn_cfg, dict):
            icon_size = btn_cfg.get("icon_size", icon_size)
            button_size = btn_cfg.get("button_size", button_size)

    # Apply
    button._icon_path = icons_path
    button._icon_name = icon_name
    button._icon_size = icon_size
   
    # Set icon
    button.setIcon(_render_svg_icon(icons_path / icon_name, icon_size))
    button.setIconSize(QSize(icon_size, icon_size))
    button.setFixedSize(button_size, button_size)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if tooltip:
        button.setToolTip(tooltip)

    _icon_registry.append(button)
    return button

class HoverIconButton(QPushButton):
    """Icon button that changes icon on hover"""
   
    def __init__(self, icons_path: Path, normal_icon: str, hover_icon: str,
                 tooltip: str = "", icon_size: int = 30, button_size: int = 48):
        super().__init__()
       
        self._icon_path = icons_path
        self._normal_icon = normal_icon
        self._hover_icon = hover_icon
        self._icon_size = icon_size
        self._hovered = False
       
        self.setIconSize(QSize(icon_size, icon_size))
        self.setFixedSize(button_size, button_size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)
       
        self._update_icon()
        _icon_registry.append(self)
   
    def _update_icon(self):
        """Update icon based on hover state"""
        icon_name = self._hover_icon if self._hovered else self._normal_icon
        self.setIcon(_render_svg_icon(self._icon_path / icon_name, self._icon_size))
   
    def enterEvent(self, event):
        self._hovered = True
        self._update_icon()
        super().enterEvent(event)
   
    def leaveEvent(self, event):
        self._hovered = False
        self._update_icon()
        super().leaveEvent(event)


def update_all_icons():
    """Update all registered icon buttons when theme changes"""
    global _icon_registry
    _icon_registry = [btn for btn in _icon_registry if not sip.isdeleted(btn)]
   
    for button in _icon_registry:
        if isinstance(button, HoverIconButton):
            button._update_icon()
        elif hasattr(button, '_icon_path') and hasattr(button, '_icon_name'):
            icon = _render_svg_icon(button._icon_path / button._icon_name, button._icon_size)
            button.setIcon(icon)