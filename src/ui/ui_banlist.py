"""Ban List Management UI Widget"""
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QScrollArea, QGridLayout, QMessageBox, QPushButton
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtGui import QPixmap, QPainter, QFontMetrics
import time

from helpers.create import create_icon_button
from helpers.fonts import get_font, FontType
from helpers.ban_manager import BanManager
from helpers.duration_dialog import DurationDialog
from core.api_data import get_exact_user_id_by_name


def format_time_remaining(seconds: int) -> str:
    """Format remaining seconds into full format display
    
    Shows all relevant units based on magnitude:
    - >= 1 week: shows weeks, days, hours, minutes (e.g., "2w 0d 0h 0m")
    - >= 1 day: shows days, hours, minutes (e.g., "2d 5h 30m")
    - >= 1 hour: shows hours, minutes (e.g., "3h 45m")
    - >= 1 minute: shows minutes (e.g., "25m")
    - < 1 minute: shows seconds (e.g., "45s")
    """
    if seconds <= 0:
        return "Expired"
    
    w = seconds // 604800
    d = (seconds % 604800) // 86400
    h = (seconds % 86400) // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    
    # Show all units from highest non-zero down to minutes
    if w > 0:
        return f"{w}w {d}d {h}h {m}m"
    elif d > 0:
        return f"{d}d {h}h {m}m"
    elif h > 0:
        return f"{h}h {m}m"
    elif m > 0:
        return f"{m}m"
    else:
        return f"{s}s"


def validate_username_and_get_id(username: str):
    """Validate username via API and return user_id (or None if not found)"""
    if not username or not isinstance(username, str):
        return None
    username = username.strip()
    if not username:
        return None
    try:
        user_id = get_exact_user_id_by_name(username)
        return str(user_id) if user_id else None
    except Exception:
        return None


class BanItemWidget(QWidget):
    """Single ban item (shared by both permanent and temporary sections)"""
    remove_requested = pyqtSignal(object)
    expired = pyqtSignal(object)  # Signal when temporary ban expires
    
    def __init__(self, config, icons_path: Path, username="", user_id="", expires_at=None, is_temporary=False):
        super().__init__()
        self.config = config
        self.icons_path = icons_path
        self.user_id = user_id
        self.expires_at = expires_at
        self.is_temporary = is_temporary
        self.parent_widget = None
        self.username_valid = True
        
        spacing = config.get("ui", "spacing", "widget_elements") or 6
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(spacing)
        self.setLayout(layout)
        
        # Username
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username")
        self.username_input.setText(username)
        self.username_input.setFont(get_font(FontType.TEXT))
        input_height = config.get("ui", "input_height") or 44
        self.username_input.setFixedHeight(input_height)
        self.username_input.setFixedWidth(220)
        self.username_input.editingFinished.connect(self._validate)
        layout.addWidget(self.username_input)
        
        # Arrow icon
        arrow_label = QLabel()
        arrow_svg = icons_path / "arrow-right.svg"
        if arrow_svg.exists():
            with open(arrow_svg, 'r') as f:
                svg_content = f.read().replace('fill="currentColor"', 'fill="#888888"')
            renderer = QSvgRenderer()
            renderer.load(svg_content.encode('utf-8'))
            pixmap = QPixmap(26, 26)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            arrow_label.setPixmap(pixmap)
            arrow_label.setFixedSize(26, 26)
        layout.addWidget(arrow_label)
        
        # User ID (read-only)
        self.user_id_input = QLineEdit()
        self.user_id_input.setPlaceholderText("User ID")
        self.user_id_input.setText(user_id)
        self.user_id_input.setFont(get_font(FontType.TEXT))
        self.user_id_input.setFixedHeight(input_height)
        self.user_id_input.setFixedWidth(125)
        self.user_id_input.setReadOnly(True)
        self.user_id_input.setStyleSheet("QLineEdit { background-color: rgba(128, 128, 128, 0.1); }")
        layout.addWidget(self.user_id_input)
        
        # Duration button (only for temporary section) - clickable to change duration
        if self.is_temporary:
            self.duration_button = QPushButton()
            self.duration_button.setFont(get_font(FontType.TEXT))
            self.duration_button.setFixedHeight(input_height)
            self.duration_button.setMinimumWidth(110)  # Minimum width
            self.duration_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.duration_button.clicked.connect(self._change_duration)
            self._update_duration_text()  # This will set initial width
            layout.addWidget(self.duration_button)
            
            # Timer for countdown
            self.update_timer = QTimer()
            self.update_timer.timeout.connect(self._update_duration_text)
            self.update_timer.start(1000)
        
        # Remove button
        self.remove_button = create_icon_button(
            icons_path, "trash.svg", "Remove", 
            size_type="large", config=config
        )
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self))
        layout.addWidget(self.remove_button)
        
        # Set fixed width - will be updated by _update_duration_text for temp items
        spacing = config.get("ui", "spacing", "widget_elements") or 6
        if self.is_temporary:
            # Initial width using minimum button size
            button_width = 110
            total_width = 220 + 26 + 125 + button_width + 48 + (spacing * 4)
        else:
            total_width = 220 + 26 + 125 + 48 + (spacing * 3)
        self.setFixedWidth(total_width)
        
        # Validate if username but no ID
        if username and not user_id:
            self._validate()
    
    def _validate(self):
        """Validate username and fetch ID"""
        username = self.username_input.text().strip()
        
        if not username:
            self.username_valid = True
            self.user_id = ""
            self.user_id_input.clear()
            self._update_input_style()
            if self.parent_widget:
                self.parent_widget._save_bans()
            return
        
        user_id = validate_username_and_get_id(username)
        self.username_valid = (user_id is not None)
        if self.username_valid:
            self.user_id = user_id
            self.user_id_input.setText(self.user_id)
        else:
            self.user_id = ""
            self.user_id_input.clear()
        
        self._update_input_style()
        
        if self.parent_widget:
            self.parent_widget._save_bans()
    
    def _update_widths(self):
        """Update button and item widths based on duration text"""
        if not self.is_temporary or not hasattr(self, 'duration_button'):
            return
        
        # Calculate button width based on text
        metrics = QFontMetrics(self.duration_button.font())
        text_width = metrics.horizontalAdvance(self.duration_button.text())
        button_width = max(110, text_width + 40)
        self.duration_button.setFixedWidth(button_width)
        
        # Update item total width
        spacing = self.config.get("ui", "spacing", "widget_elements") or 6
        total_width = 220 + 26 + 125 + button_width + 48 + (spacing * 4)
        self.setFixedWidth(total_width)
    
    def _update_input_style(self, highlight_empty=False):
        """Update input styling based on validation"""
        if highlight_empty and not self.username_input.text().strip():
            self.username_input.setStyleSheet("QLineEdit { border: 2px solid #ffb84d; }")
            self.username_input.setToolTip("Fill username before adding new item")
        elif not self.username_valid:
            self.username_input.setStyleSheet("QLineEdit { border: 2px solid #ff4444; }")
            self.username_input.setToolTip("User not found")
        else:
            self.username_input.setStyleSheet("")
            self.username_input.setToolTip("")
    
    def _update_duration_text(self):
        """Update duration button for temporary bans"""
        if not self.is_temporary or not hasattr(self, 'duration_button'):
            return
        
        if self.expires_at:
            remaining = max(0, self.expires_at - int(time.time()))
            if remaining == 0:
                # Expired - emit signal to remove
                self.update_timer.stop()
                self.expired.emit(self)
            else:
                self.duration_button.setText(format_time_remaining(remaining))
                self._update_widths()
    
    def _change_duration(self):
        """Show dialog to change duration for temporary ban"""
        if not self.is_temporary:
            return
        
        # Calculate current remaining time
        current_remaining = max(60, self.expires_at - int(time.time())) if self.expires_at else 3600
        
        # Show dialog with current remaining time (will preserve the unit if possible)
        seconds, ok = DurationDialog.get_duration(self, current_remaining)
        if ok and seconds > 0:
            # Update duration
            self.expires_at = int(time.time()) + seconds
            self._update_duration_text()
            if self.parent_widget:
                self.parent_widget._save_bans()
    
    def get_values(self):
        """Get username, user_id, and expires_at"""
        return self.username_input.text().strip(), self.user_id, self.expires_at
    
    def is_empty(self):
        """Check if item is empty"""
        username, user_id, _ = self.get_values()
        return not username and not user_id
    
    def is_valid(self):
        """Check if item is valid"""
        return self.username_valid
    
    def cleanup(self):
        """Cleanup timers"""
        if hasattr(self, 'update_timer'):
            self.update_timer.stop()


class BanListWidget(QWidget):
    """Widget for managing banned users with separate permanent/temporary sections"""
    
    back_requested = pyqtSignal()
    
    def __init__(self, config, icons_path: Path, ban_manager: BanManager):
        super().__init__()
        self.config = config
        self.icons_path = icons_path
        self.ban_manager = ban_manager
        self.perm_items = []  # Permanent ban items
        self.temp_items = []  # Temporary ban items
        
        self._setup_ui()
        self._load_bans()
    
    def _create_section(self, title: str, is_temporary: bool):
        """Helper to create a section (avoid code duplication)"""
        section = QWidget()
        section_layout = QVBoxLayout()
        section_layout.setContentsMargins(4, 4, 4, 4)
        section_layout.setSpacing(6)
        section.setLayout(section_layout)
        
        # Header with title and add button
        header = QHBoxLayout()
        label = QLabel(title)
        label.setFont(get_font(FontType.HEADER))
        header.addWidget(label, stretch=1)
        
        add_btn = create_icon_button(self.icons_path, "add.svg", f"Add to {title}", config=self.config)
        add_btn.clicked.connect(lambda: self._add_new_item(is_temporary))
        header.addWidget(add_btn)
        section_layout.addLayout(header)
        
        # Grid layout for items
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(self.config.get("ui", "spacing", "list_items") or 2)
        grid.setVerticalSpacing((self.config.get("ui", "spacing", "list_items") or 2) * 2)
        grid.setHorizontalSpacing((self.config.get("ui", "spacing", "list_items") or 2) * 4)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        section_layout.addLayout(grid)
        
        return section, grid, add_btn
    
    def _setup_ui(self):
        """Setup UI with separate sections"""
        window_margin = self.config.get("ui", "margins", "window") or 10
        window_spacing = self.config.get("ui", "spacing", "window_content") or 10
        
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(window_margin, window_margin, window_margin, window_margin)
        main_layout.setSpacing(window_spacing)
        self.setLayout(main_layout)
        
        # Header
        header_layout = QHBoxLayout()
        header_layout.setSpacing(self.config.get("ui", "spacing", "widget_elements") or 6)
        main_layout.addLayout(header_layout)
        
        self.back_button = create_icon_button(
            self.icons_path, "go-back.svg", "Back to Messages", config=self.config
        )
        self.back_button.clicked.connect(self.back_requested.emit)
        header_layout.addWidget(self.back_button)
        
        title_label = QLabel("Ban List")
        title_label.setFont(get_font(FontType.HEADER))
        header_layout.addWidget(title_label, stretch=1)
        
        self.clear_all_button = create_icon_button(
            self.icons_path, "trash.svg", "Clear All", config=self.config
        )
        self.clear_all_button.clicked.connect(self._clear_all)
        header_layout.addWidget(self.clear_all_button)
        
        # Scroll area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        main_layout.addWidget(self.scroll, stretch=1)
        
        # Container with sections
        self.items_container = QWidget()
        sections_layout = QVBoxLayout()
        sections_layout.setContentsMargins(0, 0, 0, 0)
        sections_layout.setSpacing(self.config.get("ui", "spacing", "list_items") or 6)
        sections_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.items_container.setLayout(sections_layout)
        
        # Create permanent section
        perm_section, self.perm_layout, _ = self._create_section("Permanent", is_temporary=False)
        sections_layout.addWidget(perm_section)
        
        # Create temporary section
        temp_section, self.temp_layout, _ = self._create_section("Temporary", is_temporary=True)
        sections_layout.addWidget(temp_section)
        
        self.scroll.setWidget(self.items_container)
    
    def _load_bans(self):
        """Load existing bans into appropriate sections"""
        # Only clear if items already exist
        if self.perm_items:
            for item in list(self.perm_items):
                self.perm_layout.removeWidget(item)
                item.cleanup()
                item.deleteLater()
            self.perm_items.clear()
        
        if self.temp_items:
            for item in list(self.temp_items):
                self.temp_layout.removeWidget(item)
                item.cleanup()
                item.deleteLater()
            self.temp_items.clear()
        
        # Load bans from manager
        all_bans = self.ban_manager.get_all_bans()
        for user_id, ban_data in all_bans.items():
            is_temporary = ban_data.get('is_temporary', False)
            self._add_item(
                ban_data['username'], 
                user_id, 
                ban_data.get('expires_at'),
                is_temporary=is_temporary
            )
        
        # Don't create empty items - users can click [+] button to add
        if all_bans:  # Only recalculate if we loaded something
            QTimer.singleShot(100, self._recalculate_layout)
    
    def _add_item(self, username="", user_id="", expires_at=None, is_temporary=False):
        """Add ban item to appropriate section"""
        item = BanItemWidget(
            self.config, 
            self.icons_path, 
            username, 
            user_id, 
            expires_at,
            is_temporary=is_temporary
        )
        item.parent_widget = self
        item.remove_requested.connect(self._remove_item)
        
        if is_temporary:
            item.expired.connect(self._on_expired)
            self.temp_items.append(item)
        else:
            self.perm_items.append(item)
        
        self._recalculate_layout()
    
    def _add_new_item(self, is_temporary: bool):
        """Add new empty item to specified section"""
        # Check for empty items in the target section
        items_to_check = self.temp_items if is_temporary else self.perm_items
        for item in items_to_check:
            if item.is_empty():
                item._update_input_style(highlight_empty=True)
                item.username_input.setFocus()
                return
        
        # Show duration dialog for temporary bans
        if is_temporary:
            seconds, ok = DurationDialog.get_duration(self, default_seconds=3600)
            if not ok:
                return
            expires_at = int(time.time()) + seconds
            self._add_item("", "", expires_at, is_temporary=True)
        else:
            self._add_item("", "", None, is_temporary=False)
    
    def _remove_item(self, item: BanItemWidget):
        """Remove item from appropriate section"""
        if item in self.perm_items:
            self.perm_items.remove(item)
            self.perm_layout.removeWidget(item)
        elif item in self.temp_items:
            self.temp_items.remove(item)
            self.temp_layout.removeWidget(item)
        
        item.cleanup()
        item.deleteLater()
        self._save_bans()
        self._recalculate_layout()
    
    def _on_expired(self, item: BanItemWidget):
        """Handle expired temporary ban - remove it completely"""
        if item in self.temp_items:
            print(f"⏱️ Temporary ban expired for {item.username_input.text()}")
            self._remove_item(item)
    
    def _save_bans(self):
        """Save all bans"""
        self.ban_manager.clear_all()
        
        # Save permanent bans
        for item in self.perm_items:
            username, user_id, _ = item.get_values()
            if username and user_id and item.is_valid():
                self.ban_manager.add_user(user_id, username, duration=None)
        
        # Save temporary bans
        for item in self.temp_items:
            username, user_id, expires_at = item.get_values()
            if username and user_id and item.is_valid() and expires_at:
                duration = max(0, expires_at - int(time.time()))
                if duration > 0:  # Only save if not expired
                    self.ban_manager.add_user(user_id, username, duration=duration)
    
    def _clear_all(self):
        """Clear all bans from both sections"""
        if not any(not item.is_empty() for item in self.perm_items + self.temp_items):
            QMessageBox.information(self, "Empty", "Ban list is already empty")
            return
        
        reply = QMessageBox.question(
            self, "Confirm Clear All",
            "Remove all users from ban list?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Clear permanent items
            for item in list(self.perm_items):
                self.perm_layout.removeWidget(item)
                item.cleanup()
                item.deleteLater()
            self.perm_items.clear()
            
            # Clear temporary items
            for item in list(self.temp_items):
                self.temp_layout.removeWidget(item)
                item.cleanup()
                item.deleteLater()
            self.temp_items.clear()
            
            self.ban_manager.clear_all()
            # Don't create empty item - users can click [+] to add
    
    def _recalculate_layout(self):
        """Recalculate grid layout for both sections"""
        def _layout_section(grid_layout, items_list):
            if not items_list:
                return
            
            available_width = self.scroll.viewport().width()
            h_spacing = grid_layout.horizontalSpacing()
            if h_spacing == -1:
                h_spacing = grid_layout.spacing()
            
            available_for_items = available_width - (grid_layout.contentsMargins().left() + 
                                                     grid_layout.contentsMargins().right())
            
            # Find max item width (temp items may have different widths due to duration)
            max_item_width = max(item.width() for item in items_list)
            
            columns = max(1, (available_for_items + h_spacing) // (max_item_width + h_spacing))
            
            # Clear layout
            for i in reversed(range(grid_layout.count())):
                widget = grid_layout.itemAt(i).widget()
                if widget:
                    grid_layout.removeWidget(widget)
            
            # Re-add items in grid
            for idx, item in enumerate(items_list):
                row = idx // columns
                col = idx % columns
                grid_layout.addWidget(item, row, col)
        
        # Layout both sections independently
        _layout_section(self.perm_layout, self.perm_items)
        _layout_section(self.temp_layout, self.temp_items)
    
    def resizeEvent(self, event):
        """Handle resize"""
        super().resizeEvent(event)
        QTimer.singleShot(50, self._recalculate_layout)
    
    def cleanup(self):
        """Cleanup all items"""
        for item in self.perm_items + self.temp_items:
            item.cleanup()