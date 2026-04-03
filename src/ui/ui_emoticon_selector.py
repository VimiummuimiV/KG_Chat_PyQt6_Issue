"""Emoticon selector widget for choosing emoticons"""
from pathlib import Path
from typing import List
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QScrollArea, QGridLayout, QLabel, QStackedWidget, QApplication
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QEvent, QTimer
from PyQt6.QtGui import QMovie, QCursor, QIcon

from helpers.emoticons import EmoticonManager


# ---------------------------------------------------------------------------
# Shared style constants
# ---------------------------------------------------------------------------

RADIUS_PANEL = 10   # outer widget corners
RADIUS_BTN   = 8    # tab buttons + emoticon buttons + keyboard highlight

# Grid / sizing constants — single source of truth
COLS           = 7    # columns in the emoticon grid (must match number of groups)
BTN_SIZE       = 60   # emoticon & tab button size (px)
BTN_SPACING    = 6    # gap between buttons (px)
BTN_BORDER     = 2    # button border width (px)
MARGIN         = 6    # margin for nav area (px)
CONTENT_MARGIN = MARGIN - 3  # margin for content area (px) — compensates for QScrollArea platform chrome
GRID_WIDTH     = COLS * BTN_SIZE + (COLS - 1) * BTN_SPACING
PANEL_WIDTH    = MARGIN + GRID_WIDTH + MARGIN
NAV_HEIGHT     = MARGIN + BTN_SIZE + MARGIN

def _theme_colors(is_dark: bool) -> dict:
    """Return a colour palette dict for the given theme."""
    return dict(
        panel_bg          = "#1b1b1b"  if is_dark else "#EEEEEE",
        panel_border      = "#3D3D3D"  if is_dark else "#CCCCCC",
        btn_active_bg     = "#3C3830"  if is_dark else "#C8D4E0",
        btn_active_border = "#e28743"  if is_dark else "#3a7fc1",
        btn_hover_bg      = "#3A3B3F"  if is_dark else "#D8D8D8",
        btn_hover_border  = "#4d4d4d"  if is_dark else "#BBBBBB",
    )


class EmoticonButton(QPushButton):
    """Button displaying an animated emoticon"""
    emoticon_clicked = pyqtSignal(str, bool)

    def __init__(self, emoticon_path: Path, emoticon_name: str, is_dark: bool):
        super().__init__()
        self.emoticon_name = emoticon_name
        self.emoticon_path = emoticon_path
        self.is_dark = is_dark
        self.movie = None
        self._highlighted = False

        self.setFixedSize(QSize(BTN_SIZE, BTN_SIZE))
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(f":{emoticon_name}:")

        self._update_style()
        self._load_emoticon()

    def _update_style(self):
        c = _theme_colors(self.is_dark)
        base_bg      = c['btn_active_bg']     if self._highlighted else 'transparent'
        base_border  = c['btn_active_border'] if self._highlighted else 'transparent'
        hover_bg     = c['btn_active_bg']     if self._highlighted else c['btn_hover_bg']
        hover_border = c['btn_active_border'] if self._highlighted else c['btn_hover_border']
        self.setStyleSheet(f"""
            QPushButton {{
                background: {base_bg};
                border: {BTN_BORDER}px solid {base_border};
                border-radius: {RADIUS_BTN}px;
                padding: 2px;
            }}
            QPushButton:hover {{
                background: {hover_bg};
                border: {BTN_BORDER}px solid {hover_border};
                border-radius: {RADIUS_BTN}px;
                padding: 2px;
            }}
        """)

    def _load_emoticon(self):
        """Load and animate the emoticon GIF"""
        if not self.emoticon_path.exists():
            return
       
        # Create QMovie and parent to QApplication to prevent garbage collection
        self.movie = QMovie(str(self.emoticon_path))
        try:
            # Parent to QApplication instance to keep alive
            self.movie.setParent(QApplication.instance())
        except:
            # Fallback to button if QApplication not available
            self.movie.setParent(self)
       
        # Set cache mode first for better performance
        self.movie.setCacheMode(QMovie.CacheMode.CacheAll)
       
        # Set speed to 100% (default)
        self.movie.setSpeed(100)
       
        # Get first frame to set icon size
        if self.movie.jumpToFrame(0):
            pixmap = self.movie.currentPixmap()
            if not pixmap.isNull():
                self.setIcon(QIcon(pixmap))
                self.setIconSize(pixmap.size())
       
        # Connect frame updates
        self.movie.frameChanged.connect(self._on_frame_changed)
       
        # Start animation
        self.movie.start()
       
        # Verify it's running
        if self.movie.state() != QMovie.MovieState.Running:
            # Try starting again if it didn't start
            self.movie.jumpToFrame(0)
            self.movie.start()

    def _on_frame_changed(self, frame_number):
        """Update button icon when movie frame changes"""
        if self.movie:
            pixmap = self.movie.currentPixmap()
            if not pixmap.isNull():
                self.setIcon(QIcon(pixmap))

    def mousePressEvent(self, event):
        """Handle click — Shift = insert without closing"""
        if event.button() == Qt.MouseButton.LeftButton:
            shift_pressed = event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            self.emoticon_clicked.emit(self.emoticon_name, bool(shift_pressed))
        super().mousePressEvent(event)

    def resume_animation(self):
        """Resume animation - force restart or recreate if missing"""
        if not self.movie:
            self._load_emoticon()
            return

        self.movie.stop()
        self.movie.jumpToFrame(0)
        self.movie.start()
        if self.movie.state() != QMovie.MovieState.Running:
            self.movie.start()

    def update_theme(self, new_path: Path, is_dark: bool):
        """Update button for new theme"""
        self.is_dark = is_dark
        self._update_style()
        if self.movie:
            self.movie.stop()
            self.movie.deleteLater()
            self.movie = None
        self.emoticon_path = new_path
        self._load_emoticon()

    def cleanup(self):
        """Clean up movie resources"""
        if self.movie:
            self.movie.stop()
            self.movie.deleteLater()
            self.movie = None

class EmoticonGroup(QWidget):
    """Widget for displaying a group of emoticons"""
    emoticon_clicked = pyqtSignal(str, bool)

    def __init__(self, group_name: str, emoticons: List[tuple], is_dark: bool):
        super().__init__()
        self.group_name = group_name
        self.is_dark = is_dark
        self.buttons = []

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setLayout(layout)
       
        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        layout.addWidget(scroll)
       
        # Container with grid
        container = QWidget()
        container_layout = QVBoxLayout()
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        container_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        container.setLayout(container_layout)
        scroll.setWidget(container)

        grid = QGridLayout()
        grid.setSpacing(BTN_SPACING)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        container_layout.addLayout(grid)
        container_layout.addStretch()
       
        # Add emoticons (COLS per row)
        cols = COLS
        for idx, (name, path) in enumerate(emoticons):
            if not self._is_valid(path):
                continue

            row, col = idx // cols, idx % cols
            btn = EmoticonButton(path, name, self.is_dark)
            btn.emoticon_clicked.connect(self.emoticon_clicked.emit)
            self.buttons.append(btn)
            grid.addWidget(btn, row, col, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

    def _is_valid(self, path: Path) -> bool:
        """Quick validation"""
        try:
            return path.exists() and path.stat().st_size > 100
        except:
            return False

    def resume_animations(self):
        """Resume all button animations"""
        for btn in self.buttons:
            btn.resume_animation()

    def update_theme(self, manager: EmoticonManager, is_dark: bool):
        """Update group for new theme"""
        self.is_dark = is_dark
        for btn in self.buttons:
            new_path = manager.get_emoticon_path(btn.emoticon_name)
            btn.update_theme(new_path, is_dark)

    def cleanup(self):
        """Clean up all buttons"""
        for btn in self.buttons:
            btn.cleanup()

class EmoticonSelectorWidget(QWidget):
    """Widget for selecting emoticons with icon-based navigation"""
    emoticon_selected = pyqtSignal(str)

    def __init__(self, config, emoticon_manager: EmoticonManager, icons_path: Path):
        super().__init__()
        self.config = config
        self.emoticon_manager = emoticon_manager
        self.icons_path = icons_path

        self.recent_emoticons = config.get("ui", "recent_emoticons") or []
        self.group_indices = {}
        self.nav_buttons = {}
        self.recent_buttons = []
        self.group_widgets = []
        self._nav_btn = None  # currently keyboard-highlighted EmoticonButton
        self._pos_timer = QTimer(self)
        self._pos_timer.setSingleShot(True)
        self._pos_timer.timeout.connect(self._save_position)

        self._init_ui()
        self.setFixedWidth(PANEL_WIDTH)  # applied after init so nothing can override it
       
        # Restore visibility and state
        visible = config.get("ui", "emoticon_selector_visible")
        if visible if visible is not None else False:
            self.setVisible(True)
            QTimer.singleShot(50, self._restore_state)
        else:
            self.setVisible(False)

    def _init_ui(self):
        """Initialize the UI"""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setLayout(layout)

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        theme = self.config.get("ui", "theme")
        self.is_dark_theme = (theme == "dark")
        c = _theme_colors(self.is_dark_theme)

        self.setStyleSheet(f"""
            EmoticonSelectorWidget {{
                background: {c['panel_bg']};
                border: {BTN_BORDER}px solid {c['panel_border']};
                border-radius: {RADIUS_PANEL}px;
            }}
        """)

        # Navigation bar
        self.nav_container = QWidget()
        self.nav_container.setStyleSheet(f"""
            QWidget {{
                background: {c['panel_bg']};
                border: none;
                border-bottom: 1px solid {c['panel_border']};
                border-top-left-radius: {RADIUS_PANEL}px;
                border-top-right-radius: {RADIUS_PANEL}px;
            }}
        """)
        nav_layout = QHBoxLayout()
        nav_layout.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        nav_layout.setSpacing(BTN_SPACING)
        self.nav_container.setLayout(nav_layout)
        layout.addWidget(self.nav_container)
       
        # Install event filter for wheel navigation
        self.nav_container.installEventFilter(self)
       
        # Create nav buttons
        self._create_nav_button("⭐", "recent", "Recent", nav_layout, active=True)

        for group_name, (emoji, key) in {
            'Army': ('🪖', 'army'),
            'Boys': ('👦', 'boys'),
            'Christmas': ('🎄', 'christmas'),
            'Girls': ('👧', 'girls'),
            'Halloween': ('🎃', 'halloween'),
            'Inlove': ('❤️', 'inlove')
        }.items():
            self._create_nav_button(emoji, key, group_name, nav_layout)

        # Content area
        self.content_container = QWidget()
        self.content_container.setStyleSheet(f"""
            QWidget {{
                background: {c['panel_bg']};
                border: none;
                border-bottom-left-radius: {RADIUS_PANEL}px;
                border-bottom-right-radius: {RADIUS_PANEL}px;
            }}
        """)
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(CONTENT_MARGIN, CONTENT_MARGIN, CONTENT_MARGIN, CONTENT_MARGIN)
        content_layout.setSpacing(0)
        self.content_container.setLayout(content_layout)
        layout.addWidget(self.content_container, stretch=1)
       
        # Stacked widget
        self.stacked_content = QStackedWidget()
        self.stacked_content.setStyleSheet("QStackedWidget { background: transparent; border: none; }")
        content_layout.addWidget(self.stacked_content, stretch=1)
       
        # Add content
        self._create_recent_content()
        self._create_group_contents()

        # Nav height: button size + margins
        self.nav_container.setFixedHeight(NAV_HEIGHT)

    def _create_nav_button(self, emoji: str, key: str, tooltip: str, layout: QHBoxLayout, active: bool = False):
        """Create a navigation button"""
        btn = QPushButton(emoji)
        btn.setFixedSize(BTN_SIZE, BTN_SIZE)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setToolTip(tooltip)

        self._update_nav_button_style(btn, active)
        btn.clicked.connect(lambda: self._switch_to_group(key))
        self.nav_buttons[key] = btn
        layout.addWidget(btn)

    def _update_nav_button_style(self, btn: QPushButton, active: bool):
        c = _theme_colors(self.is_dark_theme)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {c['btn_active_bg'] if active else 'transparent'};
                border: {BTN_BORDER}px solid {c['btn_active_border'] if active else 'transparent'};
                border-radius: {RADIUS_BTN}px;
                font-size: 22px;
            }}
            QPushButton:hover {{
                background: {c['btn_active_bg'] if active else c['btn_hover_bg']};
                border: {BTN_BORDER}px solid {c['btn_active_border'] if active else c['btn_hover_border']};
            }}
        """)

    def _create_recent_content(self):
        """Create recent emoticons content"""
        self.recent_widget = QWidget()
        recent_layout = QVBoxLayout()
        recent_layout.setContentsMargins(0, 0, 0, 0)
        recent_layout.setSpacing(0)
        self.recent_widget.setLayout(recent_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        recent_layout.addWidget(scroll)

        self.recent_container = QWidget()
        self.recent_layout = QVBoxLayout()
        self.recent_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_layout.setSpacing(0)
        self.recent_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.recent_container.setLayout(self.recent_layout)
        scroll.setWidget(self.recent_container)

        self.recent_grid = QGridLayout()
        self.recent_grid.setSpacing(BTN_SPACING)
        self.recent_grid.setContentsMargins(0, 0, 0, 0)
        self.recent_grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.recent_layout.addLayout(self.recent_grid)
        self.recent_layout.addStretch()

        self._populate_recent_emoticons()

        self.group_indices['recent'] = self.stacked_content.count()
        self.stacked_content.addWidget(self.recent_widget)

    def _populate_recent_emoticons(self):
        """Populate recent emoticons grid"""
        # If the keyboard cursor points at a recent button that's about to be
        # deleted, clear it now so _highlight never touches a dead C++ object.
        if self._nav_btn in self.recent_buttons:
            self._nav_btn = None
            self._set_position("recent", 0)

        # Clean up old buttons
        for btn in self.recent_buttons:
            btn.cleanup()
        self.recent_buttons.clear()
       
        # Clear existing widgets
        while self.recent_grid.count():
            item = self.recent_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
       
        # Add recent (COLS per row)
        cols = COLS
        for idx, name in enumerate(self.recent_emoticons):
            path = self.emoticon_manager.get_emoticon_path(name)
            if not path:
                continue

            row, col = idx // cols, idx % cols
            btn = EmoticonButton(path, name, self.is_dark_theme)
            btn.emoticon_clicked.connect(self._on_emoticon_clicked)
            self.recent_buttons.append(btn)
            self.recent_grid.addWidget(btn, row, col, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
       
        # Placeholder if empty
        if not self.recent_emoticons:
            placeholder = QLabel("No recent emoticons yet")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: #888; padding: 20px;")
            self.recent_grid.addWidget(placeholder, 0, 0, 1, COLS)

        # If recent is the active tab, restore highlight to index 0
        if self.recent_buttons and self._current_key() == 'recent':
            self._set_nav(self.recent_buttons, 0)

    def _create_group_contents(self):
        """Create content for each emoticon group"""
        groups = self.emoticon_manager.get_groups()

        for group_name in ['Army', 'Boys', 'Christmas', 'Girls', 'Halloween', 'Inlove']:
            if group_name not in groups:
                continue

            group_widget = EmoticonGroup(group_name, groups[group_name], self.is_dark_theme)
            group_widget.emoticon_clicked.connect(self._on_emoticon_clicked)
            self.group_widgets.append(group_widget)

            key = group_name.lower()
            self.group_indices[key] = self.stacked_content.count()
            self.stacked_content.addWidget(group_widget)

    # ------------------------------------------------------------------
    # Group switching + keyboard navigation
    # ------------------------------------------------------------------

    def _current_key(self):
        idx = self.stacked_content.currentIndex()
        return next((k for k, v in self.group_indices.items() if v == idx), None)

    def _current_buttons(self):
        idx = self.stacked_content.currentIndex()
        if idx == self.group_indices.get('recent', -1):
            return self.recent_buttons
        for gw in self.group_widgets:
            if self.stacked_content.indexOf(gw) == idx:
                return gw.buttons
        return []

    def _highlight(self, btn, active):
        if not btn:
            return
        try:
            btn._highlighted = active
            btn._update_style()
        except RuntimeError:
            pass  # C++ object already deleted — nothing to style

    def _set_nav(self, btns, idx):
        """Unhighlight current, highlight btns[idx], scroll into view, schedule save."""
        self._highlight(self._nav_btn, False)
        self._nav_btn = btns[idx]
        self._highlight(self._nav_btn, True)
        p = self._nav_btn.parent()
        while p:
            if isinstance(p, QScrollArea):
                p.ensureWidgetVisible(self._nav_btn)
                break
            p = p.parent()
        self._pos_timer.start(600)

    def _get_positions(self) -> dict:
        return self.config.get("ui", "emoticon_nav_positions") or {}

    def _set_position(self, key: str, idx: int):
        positions = self._get_positions()
        positions[key] = idx
        self.config.set("ui", "emoticon_nav_positions", value=positions)

    def _restore_idx(self, btns) -> int:
        """Return saved position index for the current group (default 0)."""
        saved = self._get_positions().get(self._current_key(), 0)
        return min(saved, len(btns) - 1)

    def _save_position(self):
        key = self._current_key()
        if not key:
            return
        btns = self._current_buttons()
        self._set_position(key, btns.index(self._nav_btn) if self._nav_btn in btns else 0)

    def _switch_to_group(self, key: str):
        # Flush position save for the group we're leaving
        if self._pos_timer.isActive():
            self._pos_timer.stop()
            self._save_position()
        self._highlight(self._nav_btn, False)
        self._nav_btn = None

        for k, btn in self.nav_buttons.items():
            self._update_nav_button_style(btn, k == key)
        if key in self.group_indices:
            self.stacked_content.setCurrentIndex(self.group_indices[key])

        self.config.set("ui", "emoticon_last_group", value=key)

        # Restore saved cursor position for the new group
        btns = self._current_buttons()
        if btns:
            self._set_nav(btns, self._restore_idx(btns))

    def navigate(self, dx: int, dy: int):
        """Move keyboard cursor. H/L: flat linear wrap. J/K: column-aware wrap."""
        btns = self._current_buttons()
        if not btns:
            return
        total = len(btns)
        if self._nav_btn not in btns:
            return self._set_nav(btns, self._restore_idx(btns))
        cur = btns.index(self._nav_btn)
        if dx:
            new_idx = (cur + dx) % total
        else:
            row, col = divmod(cur, COLS)
            rows = (total - 1) // COLS + 1
            new_idx = min(((row + dy) % rows) * COLS + col, total - 1)
        self._set_nav(btns, new_idx)

    def insert_selected(self, shift=False):
        btns = self._current_buttons()
        if not btns:
            return
        target = self._nav_btn if self._nav_btn in btns else btns[0]
        target.emoticon_clicked.emit(target.emoticon_name, shift)

    def cycle_tab(self, forward: bool = True):
        keys = list(self.group_indices.keys())
        cur  = self._current_key()
        pos  = (keys.index(cur) + (1 if forward else -1)) % len(keys) if cur in keys else 0
        self._switch_to_group(keys[pos])

    def eventFilter(self, obj, event):
        """Handle mouse wheel events on navigation container"""
        if obj == self.nav_container and event.type() == QEvent.Type.Wheel:
            delta = event.angleDelta().y()
            current_idx = self.stacked_content.currentIndex()
            total = self.stacked_content.count()

            new_idx = (current_idx - 1) % total if delta > 0 else (current_idx + 1) % total

            for key, idx in self.group_indices.items():
                if idx == new_idx:
                    self._switch_to_group(key)
                    break

            return True

        return super().eventFilter(obj, event)

    def _on_emoticon_clicked(self, emoticon_name: str, shift_pressed: bool):
        """Handle emoticon button click. shift_pressed = keep selector open."""
        self._add_to_recent(emoticon_name)
        self.emoticon_selected.emit(emoticon_name)

        if not shift_pressed:
            lyt = self.parent().layout() if self.parent() else None
            if lyt and lyt.indexOf(self) >= 0:
                release_selector(self)
            else:
                self.setVisible(False)
            self.config.set("ui", "emoticon_selector_visible", value=False)

    def _add_to_recent(self, emoticon_name: str):
        """Add emoticon to recent list"""
        if emoticon_name in self.recent_emoticons:
            self.recent_emoticons.remove(emoticon_name)

        self.recent_emoticons.insert(0, emoticon_name)
        self.recent_emoticons = self.recent_emoticons[:20]

        self.config.set("ui", "recent_emoticons", value=self.recent_emoticons)
        self._populate_recent_emoticons()

    def update_theme(self):
        """Update theme colors"""
        theme = self.config.get("ui", "theme")
        self.is_dark_theme = (theme == "dark")
        self.emoticon_manager.set_theme(self.is_dark_theme)
        c = _theme_colors(self.is_dark_theme)

        self.setStyleSheet(f"""
            EmoticonSelectorWidget {{
                background: {c['panel_bg']};
                border: {BTN_BORDER}px solid {c['panel_border']};
                border-radius: {RADIUS_PANEL}px;
            }}
        """)

        if hasattr(self, 'nav_container'):
            self.nav_container.setStyleSheet(f"""
                QWidget {{
                    background: {c['panel_bg']};
                    border: none;
                    border-bottom: 1px solid {c['panel_border']};
                    border-top-left-radius: {RADIUS_PANEL}px;
                    border-top-right-radius: {RADIUS_PANEL}px;
                }}
            """)

        if hasattr(self, 'content_container'):
            self.content_container.setStyleSheet(f"""
                QWidget {{
                    background: {c['panel_bg']};
                    border: none;
                    border-bottom-left-radius: {RADIUS_PANEL}px;
                    border-bottom-right-radius: {RADIUS_PANEL}px;
                }}
            """)

        current_idx = self.stacked_content.currentIndex()
        for key, btn in self.nav_buttons.items():
            self._update_nav_button_style(btn, self.group_indices.get(key) == current_idx)

        for group_widget in self.group_widgets:
            group_widget.update_theme(self.emoticon_manager, self.is_dark_theme)

        for btn in self.recent_buttons:
            btn.update_theme(self.emoticon_manager.get_emoticon_path(btn.emoticon_name), self.is_dark_theme)

        if 'recent' in self.group_indices:
            self._switch_to_group('recent')

    def toggle_visibility(self):
        """Toggle visibility and save state"""
        new_visible = not self.isVisible()
        self.setVisible(new_visible)
        self.config.set("ui", "emoticon_selector_visible", value=new_visible)

        if new_visible:
            QTimer.singleShot(50, self._restore_state)
        else:
            if self._pos_timer.isActive():
                self._pos_timer.stop()
                self._save_position()
            self._highlight(self._nav_btn, False)
            self._nav_btn = None

    def _restore_state(self):
        """Restore last group + cursor position; called after the widget is shown."""
        last = self.config.get("ui", "emoticon_last_group") or "recent"
        key  = last if last in self.group_indices else "recent"
        # Switch without triggering a config write for the group we're leaving
        for k, btn in self.nav_buttons.items():
            self._update_nav_button_style(btn, k == key)
        if key in self.group_indices:
            self.stacked_content.setCurrentIndex(self.group_indices[key])
        self.resume_animations()
        btns = self._current_buttons()
        if btns:
            self._set_nav(btns, self._restore_idx(btns))

    def resume_animations(self):
        """Resume all emoticon animations in the selector"""
        for btn in self.recent_buttons:
            btn.resume_animation()
        for group_widget in self.group_widgets:
            group_widget.resume_animations()

    def bind(self, callback):
        """Reconnect emoticon_selected signal to a new callback."""
        try:
            self.emoticon_selected.disconnect()
        except Exception:
            pass
        self.emoticon_selected.connect(callback)

    def attach(self, parent, callback, layout=None, spacing=0):
        """Re-parent the selector and reconnect its signal.

        If *layout* is given the selector is embedded in it (popup mode),
        otherwise it floats as an overlay (chat mode).
        """
        detach_selector_from_layout(self)
        self.setParent(parent)
        self.bind(callback)
        if layout is not None:
            layout.addWidget(self, stretch=0, alignment=Qt.AlignmentFlag.AlignCenter)
            layout.setSpacing(spacing)
            self.setFixedHeight(350)
            sp = self.sizePolicy()
            sp.setRetainSizeWhenHidden(False)
            self.setSizePolicy(sp)
            self.setFixedWidth(PANEL_WIDTH)  # re-apply after setSizePolicy
            self.setVisible(True)
            QTimer.singleShot(50, self.resume_animations)

    def cleanup(self):
        """Clean up all emoticon buttons"""
        for btn in self.recent_buttons:
            btn.cleanup()
        for widget in self.group_widgets:
            widget.cleanup()


# ---------------------------------------------------------------------------
# Shared selector lifecycle utilities
# Used by both ChatWindow and PopupNotification to avoid duplicating the
# layout-detach / release logic.
# ---------------------------------------------------------------------------

def detach_selector_from_layout(sel):
    """Remove *sel* from its current parent's layout and shrink that parent.

    Safe to call when sel is floating (not in any layout) - does nothing in
    that case. Does NOT hide or re-parent sel; callers do that themselves.
    """
    old_parent = sel.parent()
    if old_parent is None:
        return
    old_lyt = old_parent.layout()
    if old_lyt and old_lyt.indexOf(sel) >= 0:
        old_lyt.removeWidget(sel)
        old_lyt.invalidate()
        old_lyt.activate()
        try:
            old_parent.adjustSize()
            if hasattr(old_parent, 'manager'):
                old_parent.manager._position_and_cleanup()
        except Exception:
            pass


def release_selector(sel):
    """Fully release *sel*: detach from layout, hide, and unparent.

    After this call the selector is invisible and owned by no widget.
    The Python reference kept by PopupManager keeps it alive.
    """
    detach_selector_from_layout(sel)
    sel.setVisible(False)
    sel.setParent(None)