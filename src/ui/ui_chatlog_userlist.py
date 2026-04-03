"""Chatlog userlist widget - shows users with message counts and filtering"""
from pathlib import Path
from collections import Counter
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QApplication
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QFont, QCursor

from helpers.create import create_icon_button, _render_svg_icon, get_user_svg_color
from helpers.load import make_rounded_pixmap
from helpers.cache import get_cache
from helpers.fonts import get_font, FontType
from helpers.auto_scroll import AutoScroller


class ChatlogUserWidget(QWidget):
    """Single user widget for chatlog"""
    AVATAR_SIZE = 36
    SVG_AVATAR_SIZE = 24

    clicked = pyqtSignal(str, bool)  # username, ctrl_pressed
    
    def __init__(self, username, msg_count, config, icons_path, user_id=None):
        super().__init__()
        self.username = username
        self.user_id = user_id
        self.is_filtered = False
        self._cache = get_cache()
        
        layout = QHBoxLayout()
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(6)
        self.setLayout(layout)
        
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        # Avatar
        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(self.AVATAR_SIZE, self.AVATAR_SIZE)
        self.avatar_label.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
        self.avatar_label.setScaledContents(False)
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        is_dark = config.get("ui", "theme") == "dark"
        svg_color = get_user_svg_color(self._cache.has_user(user_id), is_dark)

        if user_id:
            cached_avatar = self._cache.get_avatar(user_id)
            if cached_avatar:
                self.avatar_label.setPixmap(make_rounded_pixmap(cached_avatar, self.AVATAR_SIZE, 8))
            else:
                self.avatar_label.setPixmap(
                    _render_svg_icon(icons_path / "user.svg", self.SVG_AVATAR_SIZE, svg_color)
                    .pixmap(QSize(self.SVG_AVATAR_SIZE, self.SVG_AVATAR_SIZE))
                )
                self._cache.load_avatar_async(user_id, self._on_avatar_loaded)
        else:
            self.avatar_label.setPixmap(
                _render_svg_icon(icons_path / "user.svg", self.SVG_AVATAR_SIZE, svg_color)
                .pixmap(QSize(self.SVG_AVATAR_SIZE, self.SVG_AVATAR_SIZE))
            )

        layout.addWidget(self.avatar_label)
        
        text_color = self._cache.get_username_color(username, is_dark)
        
        self.username_label = QLabel(username)
        self.username_label.setStyleSheet(f"color: {text_color};")
        self.username_label.setFont(get_font(FontType.TEXT))
        layout.addWidget(self.username_label, stretch=1)
        
        # Message count - use neutral theme color (not username color)
        count_color = "#CCCCCC" if is_dark else "#666666"
        self.count_label = QLabel(f"{msg_count}")
        self.count_label.setFont(get_font(FontType.TEXT))
        self.count_label.setStyleSheet(f"color: {count_color};")
        layout.addWidget(self.count_label)
    
    def update_color(self, color: str):
        """Update count label color (neutral theme color); username re-reads from cache."""
        self.count_label.setStyleSheet(f"color: {color};")

    def _on_avatar_loaded(self, user_id: str, pixmap):
        """Callback fired by load_avatar_async when disk file is found"""
        try:
            if user_id == self.user_id and self.avatar_label:
                self.avatar_label.setPixmap(make_rounded_pixmap(pixmap, self.AVATAR_SIZE, 8))
        except RuntimeError:
            pass
    
    def set_filtered(self, filtered: bool):
        """Update visual state when filtered"""
        self.is_filtered = filtered
        if filtered:
            self.setStyleSheet("background-color: rgba(226, 135, 67, 0.2); border-radius: 4px;")
        else:
            self.setStyleSheet("")
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            ctrl_pressed = event.modifiers() & Qt.KeyboardModifier.ControlModifier
            self.clicked.emit(self.username, bool(ctrl_pressed))
        super().mousePressEvent(event)


class ChatlogUserlistWidget(QWidget):
    """Userlist for chatlog view with message counts and filtering"""
    
    filter_requested = pyqtSignal(set)  # Emit set of usernames to filter
    
    def __init__(self, config, icons_path, ban_manager=None):
        super().__init__()
        self.config = config
        self.icons_path = icons_path
        self.cache = get_cache()
        self.ban_manager = ban_manager
        self.show_banned = False  # Track if we should show banned users
        self.user_widgets = {}  # username -> widget
        self.filtered_usernames = set()
        
        margin = config.get("ui", "margins", "widget") or 5
        spacing = config.get("ui", "spacing", "widget_elements") or 6
        
        layout = QVBoxLayout()
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(spacing)
        self.setLayout(layout)
        
        # Clear filter button (initially hidden)
        button_layout = QHBoxLayout()
        button_layout.setSpacing(config.get("ui", "buttons", "spacing") or 8)
        button_layout.setContentsMargins(0, 5, 0, 0)
        self.clear_filter_btn = create_icon_button(
            icons_path,
            "go-back.svg",
            "Clear filter and show all users",
            size_type="large",
            config=config
        )
        self.clear_filter_btn.clicked.connect(self.clear_filter)
        self.clear_filter_btn.setVisible(False)
        button_layout.addWidget(self.clear_filter_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(scroll)

        self.auto_scroller = AutoScroller(scroll)
        
        container = QWidget()
        self.user_layout = QVBoxLayout()
        self.user_layout.setContentsMargins(5, 5, 5, 5)
        self.user_layout.setSpacing(2)
        container.setLayout(self.user_layout)
        scroll.setWidget(container)
        
        self.user_layout.addStretch()
    
    def set_show_banned(self, show: bool):
        """Control whether banned users are shown (for parse mode)"""
        self.show_banned = show
    
    def _handle_user_click(self, username: str, ctrl_pressed: bool):
        """Handle user click with Ctrl modifier support"""
        if ctrl_pressed:
            # Toggle username in filter
            if username in self.filtered_usernames:
                self.filtered_usernames.remove(username)
            else:
                self.filtered_usernames.add(username)
        else:
            # Replace filter with single username
            if self.filtered_usernames == {username}:
                # If clicking the only filtered user, clear filter
                self.filtered_usernames = set()
            else:
                self.filtered_usernames = {username}
        
        # Update visual state
        for uname, widget in self.user_widgets.items():
            widget.set_filtered(uname in self.filtered_usernames)
        
        # Show/hide clear button
        self.clear_filter_btn.setVisible(bool(self.filtered_usernames))
        
        # Emit filter
        self.filter_requested.emit(self.filtered_usernames.copy())
    
    def clear_filter(self):
        """Clear all filters"""
        self.filtered_usernames = set()
        for widget in self.user_widgets.values():
            widget.set_filtered(False)
        self.clear_filter_btn.setVisible(False)
        self.filter_requested.emit(set())

    def update_filter_state(self, filtered_usernames: set):
        """Update filter state from external signal without emitting to avoid loops"""
        self.filtered_usernames = filtered_usernames.copy()
        for uname, widget in self.user_widgets.items():
            widget.set_filtered(uname in filtered_usernames)
        self.clear_filter_btn.setVisible(bool(filtered_usernames))
    
    def load_from_messages(self, messages):
        """Load users from chatlog messages with ban filtering"""
        self._clear_widgets()
        
        if not messages:
            return
        
        # Count messages per user
        counts = Counter(msg.username for msg in messages)
        
        # FILTER BANNED USERS - completely hide them unless in parse mode
        if self.ban_manager and not self.show_banned:
            # Remove banned users from counts
            filtered_counts = {}
            for username, count in counts.items():
                if not self.ban_manager.is_banned_by_username(username):
                    filtered_counts[username] = count
            counts = filtered_counts

        if not counts:
            # All users were banned or no messages
            empty_label = QLabel("No users to display")
            empty_label.setFont(get_font(FontType.TEXT))
            empty_label.setStyleSheet("color: #888888;")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.user_layout.addWidget(empty_label)
            self.user_layout.addStretch()
            return

        sorted_users = sorted(counts.items(), key=lambda x: (-x[1], x[0].lower()))
        
        # Create widgets - all users shown here are NOT banned (or we're in parse mode)
        for username, count in sorted_users:
            try:
                user_id = self.cache.get_user_id(username)
                widget = ChatlogUserWidget(username, count, self.config, self.icons_path, user_id)
                widget.clicked.connect(self._handle_user_click)
                widget.set_filtered(username in self.filtered_usernames)
                self.user_widgets[username] = widget
                self.user_layout.insertWidget(self.user_layout.count() - 1, widget)
            except Exception as e:
                print(f"Error creating chatlog user widget: {e}")
        
        # Update clear button visibility
        self.clear_filter_btn.setVisible(bool(self.filtered_usernames))
    
    def update_theme(self):
        """Update colors based on theme"""
        is_dark = self.config.get("ui", "theme") == "dark"
        neutral_color = "#CCCCCC" if is_dark else "#666666"
        
        self.setUpdatesEnabled(False)
        for username, widget in list(self.user_widgets.items()):
            try:
                # Username gets its own precomputed color; count gets neutral theme color
                username_color = self.cache.get_username_color(username, is_dark)
                widget.username_label.setStyleSheet(f"color: {username_color};")
                widget.update_color(neutral_color)
            except (RuntimeError, AttributeError):
                pass
        self.setUpdatesEnabled(True)
    
    def clear_cache(self):
        """Clear cache - called when going back to messages"""
        pass

    def reset_filter(self):
        """Reset filter state (called when navigating dates)"""
        # Keep the filter active across date changes
        pass
    
    def _clear_widgets(self):
        """Clear user widgets"""
        self.user_widgets.clear()
        while self.user_layout.count() > 1:
            item = self.user_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        QApplication.processEvents()

    def cleanup(self):
        """Clean up resources"""
        self.auto_scroller.cleanup()