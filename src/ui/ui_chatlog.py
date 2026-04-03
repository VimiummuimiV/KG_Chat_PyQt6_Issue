"""Chatlog viewer widget with virtual scrolling, search, and parser"""
from PyQt6.QtWidgets import(
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListView, QCalendarWidget, QLineEdit,
    QStackedWidget, QFileDialog, QMessageBox, QApplication
)
from PyQt6.QtCore import Qt, QDate, QTimer, pyqtSignal, QEvent
from PyQt6.QtGui import QFont
from datetime import datetime, timedelta
import threading
from pathlib import Path

from core.chatlogs import ChatlogsParser, ChatlogNotFoundError
from core.chatlogs_db import ChatMessage
from core.chatlogs_parser import ParseConfig, ChatlogsParserEngine
from helpers.mention_parser import parse_mentions
from helpers.create import create_icon_button, _render_svg_icon
from helpers.emoticons import EmoticonManager
from helpers.scroll import scroll
from helpers.data import get_data_dir
from helpers.fonts import get_font, FontType
from helpers.scroll_button import ScrollToBottomButton
from helpers.auto_scroll import AutoScroller
from helpers.scrollable_buttons import ScrollableButtonContainer
from ui.message_model import MessageListModel, MessageData
from ui.message_delegate import MessageDelegate
from ui.ui_chatlogs_parser import ChatlogsParserConfigWidget, ParserWorker


class ChatlogWidget(QWidget):
    """Chatlog viewer with virtual scrolling, search, and parser"""
    back_requested = pyqtSignal()
    messages_loaded = pyqtSignal(list)
    filter_changed = pyqtSignal(set)
    _error_occurred = pyqtSignal(str)

    def __init__(
        self,
        config,
        emoticon_manager,
        icons_path: Path,
        account=None,
        parent_window=None,
        ban_manager=None
        ):
        super().__init__()
        self.config = config
        self.emoticon_manager = emoticon_manager
        self.icons_path = icons_path
        self.account = account
        self.parent_window = parent_window
        self.ban_manager = ban_manager
        self.parser = ChatlogsParser()
        self.current_date = datetime.now().date()
        self.filtered_usernames = set()
        self.search_text = ""
        self.filter_mentions = False 
        self.all_messages = []
        self.last_parsed_date = None
        self.temp_parsed_messages = [] # Temp storage during parsing
        self.is_parsing = False  # Track if we're in parse mode
        self.exceeded_max_messages = False

        self.search_visible = config.get("ui", "chatlog_search_visible")
        if self.search_visible is None:
            self.search_visible = False

        self.model = MessageListModel(max_messages=50000)
        self.delegate = MessageDelegate(config, self.emoticon_manager)
        
        # Set username for mention highlighting if account is available
        if account and account.get('chat_username'):
            self.delegate.set_my_username(account.get('chat_username'))

        # Parser state
        self.parser_worker = None
        self.parser_visible = False
        self.parser_cancelled = False
        
        # Debounce timer for navigation
        self.load_timer = QTimer()
        self.load_timer.setSingleShot(True)
        self.load_timer.timeout.connect(self.load_current_date)
        
        # Repeat timer for holding mouse buttons
        self.repeat_timer = QTimer()
        self.repeat_timer.setInterval(100)  # Repeat every 100ms
        self.repeat_direction = None
        self.repeat_timer.timeout.connect(self._on_repeat_timer)
        
        # Delay timer before repeat starts
        self.repeat_delay_timer = QTimer()
        self.repeat_delay_timer.setSingleShot(True)
        self.repeat_delay_timer.setInterval(400)  # 400ms delay before repeat starts
        self.repeat_delay_timer.timeout.connect(self.repeat_timer.start)

        self._setup_ui()
    
        # Initialize auto-scroller after UI is set up
        self.auto_scroller = AutoScroller(self.list_view)
        
        # Connect message click handler
        self.delegate.message_clicked.connect(self._on_message_clicked)

    def set_account(self, account):
        """Update account for parser widget"""
        self.account = account
        if self.parser_widget:
            self.parser_widget.set_account(account)
        
        # Update delegate with new username for mention highlighting
        if account and account.get('chat_username'):
            self.delegate.set_my_username(account.get('chat_username'))

    def _scroll_and_highlight(self, target_row: int, scroll_delay: int = 50, highlight_delay: int = 200):
        """Scroll to target row and highlight it after a delay."""
        scroll(self.list_view, mode="middle", target_row=target_row, delay=scroll_delay)
        QTimer.singleShot(highlight_delay, lambda: self.delegate.highlight_row(target_row))

    def _on_message_clicked(self, row: int):
        """Handle message click - reveal all messages and scroll to clicked message"""
        
        # No active filters → simple direct scroll + highlight
        if not (self.filtered_usernames or self.search_text or self.filter_mentions):
            self._scroll_and_highlight(row, scroll_delay=50, highlight_delay=200)
            return

        # Filters are active → clear them and find message in full list
        clicked_msg = self.model.data(self.model.index(row, 0), Qt.ItemDataRole.DisplayRole)
        if not clicked_msg:
            return

        # Find corresponding row in unfiltered messages
        target_row = next((i for i, msg in enumerate(self.all_messages)
                        if not msg.is_separator 
                        and msg.username == clicked_msg.username
                        and msg.body == clicked_msg.body 
                        and msg.timestamp == clicked_msg.timestamp), None)

        if target_row is None:
            return

        # Clear filters
        self.filtered_usernames = set()
        self.search_text = ""
        self.search_field.clear()
    
        # Only update icon if it was actually active
        if self.filter_mentions:
            self.filter_mentions = False
            icon_name = "at-line.svg"
            self.mention_filter_btn._icon_name = icon_name
            icon = _render_svg_icon(self.mention_filter_btn._icon_path / icon_name, self.mention_filter_btn._icon_size)
            self.mention_filter_btn.setIcon(icon)

        self._apply_filter()
        self.filter_changed.emit(self.filtered_usernames)

        # Scroll + highlight after the list has rebuilt
        QTimer.singleShot(100, lambda: self._scroll_and_highlight(
            target_row,
            scroll_delay=100,
            highlight_delay=250
        ))

    def _on_repeat_timer(self):
        """Handle repeated navigation when button/mouse is held"""
        if self.repeat_direction is not None:
            self._navigate(self.repeat_direction)
    
    def _navigate_hold(self, direction=None):
        """Start/stop hold navigation (None to stop, -1/1 to start)"""
        if direction is None:
            self.repeat_delay_timer.stop()
            self.repeat_timer.stop()
            self.repeat_direction = None
        else:
            self._navigate(direction)
            self.repeat_direction = direction
            self.repeat_delay_timer.start()  # Start delay before repeating
    
    def _setup_ui(self):
        margin = self.config.get("ui", "margins", "widget") or 5
        spacing = self.config.get("ui", "spacing", "widget_elements") or 6
    
        layout = QVBoxLayout()
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(spacing)
        self.setLayout(layout)

        # Top bar container for responsive layout
        self.top_bar_container = QWidget()
        self.top_bar_layout = QVBoxLayout()
        self.top_bar_layout.setContentsMargins(0, 0, 0, 0)
        self.top_bar_layout.setSpacing(spacing)
        self.top_bar_container.setLayout(self.top_bar_layout)
        layout.addWidget(self.top_bar_container)

        # Main horizontal bar (for wide screens)
        self.main_bar = QHBoxLayout()
        self.main_bar.setSpacing(spacing)
        self.main_bar.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.top_bar_layout.addLayout(self.main_bar)

        # Left side: Info block (date + status)
        self.info_block = QVBoxLayout()
        self.info_block.setSpacing(spacing)
        self.info_block.setAlignment(Qt.AlignmentFlag.AlignTop)
     
        # Date label
        self.date_label = QLabel()
        self.date_label.setFont(get_font(FontType.HEADER))
        self.date_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.info_block.addWidget(self.date_label)
     
        # Info label
        self.info_label = QLabel("Loading...")
        self.info_label.setStyleSheet("color: #666666;")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.info_block.addWidget(self.info_label)
     
        self.main_bar.addLayout(self.info_block, stretch=1)

        # Right side: Navigation buttons (horizontally scrollable, MMB drag supported)
        self.nav_buttons_container = ScrollableButtonContainer(
            Qt.Orientation.Horizontal, config=self.config
        )


        self.back_btn = create_icon_button(self.icons_path, "go-back.svg", "Back to chat",
                                          size_type="large", config=self.config)
        self.back_btn.clicked.connect(self.back_requested.emit)
        self.nav_buttons_container.add_widget(self.back_btn)

        self.prev_btn = create_icon_button(self.icons_path, "arrow-left.svg", "Previous day (H)",
                                          size_type="large", config=self.config)
        self.prev_btn.pressed.connect(lambda: self._navigate_hold(-1))
        self.prev_btn.released.connect(lambda: self._navigate_hold())
        self.nav_buttons_container.add_widget(self.prev_btn)

        self.next_btn = create_icon_button(self.icons_path, "arrow-right.svg", "Next day (L)",
                                          size_type="large", config=self.config)
        self.next_btn.pressed.connect(lambda: self._navigate_hold(1))
        self.next_btn.released.connect(lambda: self._navigate_hold())
        self.nav_buttons_container.add_widget(self.next_btn)

        self.calendar_btn = create_icon_button(self.icons_path, "calendar.svg", "Select date (D)",
                                              size_type="large", config=self.config)
        self.calendar_btn.clicked.connect(self._show_calendar)
        self.nav_buttons_container.add_widget(self.calendar_btn)

        self.search_toggle_btn = create_icon_button(self.icons_path, "search.svg", "Toggle search (S / Ctrl+F)",
                                                   size_type="large", config=self.config)
        self.search_toggle_btn.clicked.connect(self._toggle_search)
        self.nav_buttons_container.add_widget(self.search_toggle_btn)

        self.mention_filter_btn = create_icon_button(self.icons_path, "at-line.svg", "Filter mentions (M)",
                                                    size_type="large", config=self.config)
        self.mention_filter_btn.clicked.connect(self._toggle_mention_filter)
        self.nav_buttons_container.add_widget(self.mention_filter_btn)

        self.parse_btn = create_icon_button(self.icons_path, "play.svg", "Parse all chatlogs (P | Ctrl+P from anywhere)",
                                           size_type="large", config=self.config)
        self.parse_btn.clicked.connect(self._toggle_parser)
        self.nav_buttons_container.add_widget(self.parse_btn)

        self.main_bar.addWidget(self.nav_buttons_container)
    
        self.compact_layout = False

        # Search bar (initially hidden)
        self.search_container = QWidget()
        search_layout = QHBoxLayout()
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(self.config.get("ui", "buttons", "spacing") or 8)
        self.search_container.setLayout(search_layout)
    
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Search: 'text' or 'U:Bob' or 'U:Bob,Alice' or 'M:hello' or 'U:Bob M:hello'")
        self.search_field.setFont(get_font(FontType.TEXT))
        self.search_field.setFixedHeight(self.config.get("ui", "input_height") or 48)
        self.search_field.textChanged.connect(self._on_search_changed)
        search_layout.addWidget(self.search_field, stretch=1)
    
        self.clear_search_btn = create_icon_button(self.icons_path, "trash.svg", "Clear search",
                                                  size_type="large", config=self.config)
        self.clear_search_btn.clicked.connect(self._clear_search)
        search_layout.addWidget(self.clear_search_btn)
    
        self.search_container.setVisible(False)
        layout.addWidget(self.search_container)
    
        if self.search_visible:
            self.search_container.setVisible(True)

        # Stacked widget: List view OR Parser config
        self.stacked = QStackedWidget()
        layout.addWidget(self.stacked, stretch=1)

        # List view page
        self.list_view = QListView()
        self.list_view.setModel(self.model)
        self.list_view.setItemDelegate(self.delegate)
        self.delegate.set_list_view(self.list_view)
    
        self.list_view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.list_view.setUniformItemSizes(False)
        self.list_view.setSpacing(0)
    
        self.list_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_view.setSelectionMode(QListView.SelectionMode.NoSelection)
        self.list_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list_view.setMouseTracking(True)
        self.list_view.viewport().setMouseTracking(True)
    
        self.stacked.addWidget(self.list_view)
       
        # Add scroll-to-bottom button
        self.scroll_button = ScrollToBottomButton(self.list_view, parent=self)
       
        # Parser config page
        self.parser_widget = ChatlogsParserConfigWidget(self.config, self.icons_path, self.account)
        self.parser_widget.parse_started.connect(self._on_parse_started)
        self.parser_widget.parse_cancelled.connect(self._on_parse_cancelled)
     
        # Connect copy/save buttons
        self.parser_widget.copy_button.clicked.connect(self._on_copy_results)
        self.parser_widget.save_button.clicked.connect(self._on_save_results)
     
        self.stacked.addWidget(self.parser_widget)

        # Show list view by default
        self.stacked.setCurrentWidget(self.list_view)

        self._update_date_display()
        self._error_occurred.connect(self._handle_error)

    def _on_copy_results(self):
        """Copy parsed results to clipboard"""
        if not self.all_messages:
            QMessageBox.information(self, "No Results", "No messages to copy.")
            return
     
        # Build text with separators
        text_lines = []
        current_date = None
        message_count = 0
     
        for msg in self.all_messages:
            if msg.is_separator:
                text_lines.append(f"\n{'='*60}")
                text_lines.append(f" {msg.date_str}")
                text_lines.append(f"{'='*60}\n")
                current_date = msg.date_str
            else:
                timestamp = msg.timestamp.strftime("%H:%M:%S")
                text_lines.append(f"[{timestamp}] {msg.username}: {msg.body}")
                message_count += 1
     
        result = '\n'.join(text_lines)
     
        # Copy to clipboard
        clipboard = QApplication.clipboard()
        clipboard.setText(result)
     
        QMessageBox.information(self, "Copied", f"Copied {message_count} messages to clipboard.")
 
    def _on_save_results(self):
        """Save parsed results to file"""
        if not self.all_messages:
            QMessageBox.information(self, "No Results", "No messages to save.")
            return
     
        # Get default filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_dir = get_data_dir("exports")
        default_filename = default_dir / f"chatlog_export_{timestamp}.txt"
     
        # Show save dialog
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Chat Log",
            str(default_filename),
            "Text Files (*.txt);;All Files (*)"
        )
     
        if not filename:
            return
     
        try:
            # Build text with separators
            text_lines = []
            current_date = None
            message_count = 0
         
            for msg in self.all_messages:
                if msg.is_separator:
                    text_lines.append(f"\n{'='*60}")
                    text_lines.append(f" {msg.date_str}")
                    text_lines.append(f"{'='*60}\n")
                    current_date = msg.date_str
                else:
                    timestamp = msg.timestamp.strftime("%H:%M:%S")
                    text_lines.append(f"[{timestamp}] {msg.username}: {msg.body}")
                    message_count += 1
         
            result = '\n'.join(text_lines)
         
            # Write to file
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(result)
         
            QMessageBox.information(self, "Saved", f"Saved {message_count} messages to:\n{filename}")
     
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save file:\n{e}")

    def _toggle_parser(self):
        """Toggle between normal view and parser config"""
        if self.parser_visible:
            # Hide parser, show list
            self.parser_visible = False
            self.stacked.setCurrentWidget(self.list_view)
            self.parse_btn.setIcon(_render_svg_icon(self.icons_path / "play.svg", self.parse_btn._icon_size))
            self.parse_btn.setToolTip("Parse all chatlogs (P | Ctrl+P from anywhere)")
        else:
            # Show parser, hide list
            self.parser_visible = True
            self.stacked.setCurrentWidget(self.parser_widget)
            self.parse_btn.setIcon(_render_svg_icon(self.icons_path / "list.svg", self.parse_btn._icon_size))
            self.parse_btn.setToolTip("Back to chat logs (P)")

    def _on_parse_started(self, config: ParseConfig):
        """Start parsing with given config"""
        self.is_parsing = True
        self.exceeded_max_messages = False
        
        # Only clear UI for non-sync modes
        if config.mode != 'syncdatabase':
            self.model.clear()
            self.all_messages = []
            self.temp_parsed_messages = []
            self.last_parsed_date = None
        else:
            self.info_label.setText("Syncing database...")

        self.parser_worker = ParserWorker(config)
        self.parser_worker.progress.connect(self.parser_widget.update_progress)
        
        # Only connect messages_found for non-sync modes
        if config.mode != 'syncdatabase':
            self.parser_worker.messages_found.connect(self._on_parsed_messages)
        
        # Connect sync_stats signal
        self.parser_worker.sync_stats.connect(self._on_sync_complete)
        
        self.parser_worker.finished.connect(self._on_parse_finished)
        self.parser_worker.error.connect(self._on_parse_error)

        if self.parent_window:
            self.parser_worker.progress.connect(self.parent_window.update_parse_progress)
            self.parser_worker.finished.connect(lambda m: self.parent_window.on_parse_finished())
            self.parser_worker.error.connect(lambda e: self.parent_window.on_parse_error(e))

        self.parser_worker.start()

    def _on_parse_cancelled(self):
        """Cancel parsing"""
        if self.parser_worker:
            self.parser_worker.stop()
            self.parser_worker = None
        self.parser_cancelled = True
        self.parser_widget._reset_ui()
        
        # Check if in sync mode
        is_sync = hasattr(self.parser_widget, 'is_sync_mode') and self.parser_widget.is_sync_mode
        
        if is_sync:
            self.info_label.setText("Database sync cancelled")
        else:
            # Normal mode - add partial messages if any
            if self.temp_parsed_messages:
                self.list_view.setUpdatesEnabled(False)
                self.all_messages = self.temp_parsed_messages.copy()
                for msg_data in self.temp_parsed_messages:
                    self.model.add_message(msg_data)
                self.temp_parsed_messages = []
                self.list_view.setUpdatesEnabled(True)
                non_separator_messages = [m for m in self.all_messages if not m.is_separator]
                self.messages_loaded.emit(non_separator_messages)
                self.parser_widget.show_copy_save_buttons()
                QTimer.singleShot(100, lambda: scroll(self.list_view, mode="bottom", delay=50))
                message_count = sum(1 for m in self.all_messages if not m.is_separator)
                self.info_label.setText(f"Found {message_count} messages (partial)")
            else:
                self.info_label.setText("Parsing cancelled")
                self.is_parsing = False
        
        if self.parent_window:
            self.parent_window.stop_parse_status()

    def _on_parsed_messages(self, messages, date: str):
        """Handle incrementally parsed messages - ONLY update counter, not layout"""
        # Only add separator and messages if we actually have messages
        if not messages:
            return # Skip empty dates entirely
    
        # ALWAYS add separator when date changes OR when it's the first date
        if self.last_parsed_date is None or date != self.last_parsed_date:
            # Add separator to temp storage
            separator = MessageData(datetime.now(), "", "", is_separator=True, date_str=date)
            self.temp_parsed_messages.append(separator)
            self.last_parsed_date = date

        # Convert ChatMessage to MessageData - msg already has all fields
        for msg in messages:
            try:
                timestamp = datetime.strptime(msg.timestamp, "%H:%M:%S")
                msg_data = MessageData(timestamp, msg.username, msg.message, None, msg.username)
                self.temp_parsed_messages.append(msg_data)
            except Exception as e:
                print(f"Error processing message: {e}")
    
        # Check if exceeded limit
        message_count = sum(1 for m in self.temp_parsed_messages if not m.is_separator)
        if message_count > self.model.max_messages and not self.exceeded_max_messages:
            self.exceeded_max_messages = True
            self.info_label.setText(f"⚠️ Exceeded {self.model.max_messages:,} message limit - rendering disabled. Use Copy/Save buttons.")
        elif not self.exceeded_max_messages:
            self.info_label.setText(f"Found {message_count:,} messages so far...")

    def _on_parse_finished(self, messages):
        """Handle parse completion - NOW add all messages to layout at once"""
        if self.parser_cancelled:
            self.parser_cancelled = False
            return
        
        self.parser_worker = None
        self.parser_widget._reset_ui()
        self.last_parsed_date = None
        
        # Check if this was a sync operation
        is_sync = hasattr(self.parser_widget, 'is_sync_mode') and self.parser_widget.is_sync_mode
        
        if is_sync:
            # Sync mode complete - info already updated in _on_sync_complete
            pass
        elif self.temp_parsed_messages:
            message_count = sum(1 for m in self.temp_parsed_messages if not m.is_separator)
            self.all_messages = self.temp_parsed_messages.copy()
            self.temp_parsed_messages = []
            
            # Skip rendering if exceeded limit
            if self.exceeded_max_messages:
                self.info_label.setText(f"⚠️ {message_count:,} messages found (limit: {self.model.max_messages:,}) - rendering disabled. Use Copy/Save buttons.")
                self.exceeded_max_messages = False
            else:
                # Normal rendering
                self.list_view.setUpdatesEnabled(False)
                for msg_data in self.all_messages:
                    self.model.add_message(msg_data)
                self.list_view.setUpdatesEnabled(True)
                
                non_separator_messages = [m for m in self.all_messages if not m.is_separator]
                self.messages_loaded.emit(non_separator_messages)
                QTimer.singleShot(100, lambda: scroll(self.list_view, mode="bottom", delay=50))
            
            self.parser_widget.show_copy_save_buttons()
        else:
            self.info_label.setText("No messages found")
        
        if self.parent_window:
            self.parent_window.handle_parse_finished()
                
    def _on_sync_complete(self, fetched_count: int, db_stats: dict):
        """Handle sync database completion"""
        if fetched_count == 0:
            self.info_label.setText("✅ Database is already up to date")
        else:
            self.info_label.setText(f"✅ Synced {fetched_count} dates to database")
        
        # Show database stats
        QMessageBox.information(
            self,
            "Database Synced",
            f"Successfully synced database!\n\n"
            f"Fetched: {fetched_count} dates\n"
            f"Total messages: {db_stats['total_messages']:,}\n"
            f"Cached dates: {db_stats['cached_dates']}\n"
            f"Database size: {db_stats['db_size_mb']} MB"
        )

    def _on_parse_error(self, error_msg: str):
        """Handle parse error"""
        if self.parser_cancelled:
            return
        self.parser_worker = None
        self.parser_widget._reset_ui()
        self.temp_parsed_messages = [] # Clear temp on error
        self.info_label.setText(f"❌ Error: {error_msg}")
        if self.parent_window:
            self.parent_window.stop_parse_status()

    def _handle_error(self, error_msg: str):
        self.info_label.setText(error_msg)

    def _toggle_search(self):
        self.search_visible = not self.search_visible
        self.search_container.setVisible(self.search_visible)
        self.config.set("ui", "chatlog_search_visible", value=self.search_visible)
    
        if self.search_visible:
            self.search_field.setFocus()
        else:
            self.search_field.clear()

    def _toggle_mention_filter(self):
        """Toggle mention filter on/off"""
        self.filter_mentions = not self.filter_mentions
        
        # Update icon based on state
        icon_name = "at-fill.svg" if self.filter_mentions else "at-line.svg"
        self.mention_filter_btn._icon_name = icon_name  # Update the attribute for theme consistency
        icon = _render_svg_icon(self.mention_filter_btn._icon_path / icon_name, self.mention_filter_btn._icon_size)
        self.mention_filter_btn.setIcon(icon)
        
        # Reapply filter to show/hide messages
        self._apply_filter()

    def _on_search_changed(self, text: str):
        self.search_text = text.strip()
        self._apply_filter()

    def _parse_search_text(self):
        if not self.search_text:
            return set(), "", False
    
        import re
    
        user_filter = set()
        message_filter = ""
    
        text = self.search_text.strip()
        has_u_prefix = re.search(r'[Uu]:', text)
        has_m_prefix = re.search(r'[Mm]:', text)
        has_prefix = has_u_prefix or has_m_prefix
    
        if not has_prefix:
            return set(), "", False
    
        if has_u_prefix:
            u_pattern = r'[Uu]:\s*(.+?)(?:\s+[Mm]:|$)'
            match = re.search(u_pattern, text)
            if match:
                users_str = match.group(1).strip()
                users = [u.strip() for u in users_str.split(',') if u.strip()]
                user_filter.update(users)
    
        if has_m_prefix:
            m_pattern = r'[Mm]:\s*(.+?)(?:\s+[Uu]:|$)'
            match = re.search(m_pattern, text)
            if match:
                message_filter = match.group(1).strip().lower()
    
        return user_filter, message_filter, True

    def _clear_search(self):
        self.search_field.clear()
        self._apply_filter()

    def _update_date_display(self):
        self.date_label.setText(self.current_date.strftime("%Y-%m-%d (%A)"))
        self.next_btn.setEnabled(self.current_date < datetime.now().date())
        self.prev_btn.setEnabled(self.current_date > self.parser.MIN_DATE)

    def set_compact_layout(self, compact: bool):
        """Handle responsive layout for < 1000px width"""
        if compact == self.compact_layout:
            return
    
        if compact:
            # Remove items from main_bar (widget at index 1, layout at index 0)
            self.main_bar.takeAt(1)  # nav_buttons_container widget item
            self.main_bar.takeAt(0)  # info_block item
            # Remove main_bar from top_bar_layout
            self.top_bar_layout.takeAt(0)
            # Add nav_buttons_container (widget) and info_block (layout) to top_bar_layout
            self.top_bar_layout.addWidget(self.nav_buttons_container)
            self.top_bar_layout.addLayout(self.info_block)
            self.compact_layout = True
        else:
            # Remove items from top_bar_layout
            self.top_bar_layout.takeAt(1)  # info_block item
            self.top_bar_layout.takeAt(0)  # nav_buttons_container widget item
            # Add main_bar back
            self.top_bar_layout.addLayout(self.main_bar)
            # Add sub-items to main_bar
            self.main_bar.addLayout(self.info_block, stretch=1)
            self.main_bar.addWidget(self.nav_buttons_container)

            self.compact_layout = False

    def set_compact_mode(self, compact: bool):
        self.delegate.set_compact_mode(compact)
        self._force_recalculate()

    def update_theme(self):
        self.delegate.update_theme()
        self._force_recalculate()

    def _force_recalculate(self):
        self.list_view.setUpdatesEnabled(False)
        self.list_view.reset()
        self.list_view.clearSelection()
        self.list_view.scheduleDelayedItemsLayout()
        self.model.layoutChanged.emit()
        self.list_view.setUpdatesEnabled(True)
        self.list_view.viewport().update()
        QTimer.singleShot(10, lambda: self.list_view.viewport().update())

    def load_date(self, date_str: str):
        try:
            self.current_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            self._update_date_display()
            self.load_current_date()
        except Exception as e:
            self.info_label.setText(f"Error: {e}")

    def set_username_filter(self, usernames: set):
        self.filtered_usernames = usernames
        self._apply_filter()
        self.filter_changed.emit(self.filtered_usernames)

    def clear_filter(self):
        self.filtered_usernames = set()
        self._apply_filter()
        self.filter_changed.emit(self.filtered_usernames)

    def _apply_filter(self):
        # Batch operations for better performance
        self.list_view.setUpdatesEnabled(False)
        
        self.model.clear()

        if not self.all_messages:
            self.list_view.setUpdatesEnabled(True)
            return

        search_users, search_message, is_prefix_mode = self._parse_search_text()
        messages_to_show = self.all_messages
        
        # APPLY MENTION FILTER FIRST
        if self.filter_mentions and self.account and self.account.get('chat_username'):
            my_username = self.account.get('chat_username')
            messages_to_show = [
                msg for msg in messages_to_show
                if not msg.is_separator and any(
                    is_mention for is_mention, _ in parse_mentions(msg.body, my_username)
                )
            ]

        if is_prefix_mode:
            if search_users:
                search_users_lower = {u.lower() for u in search_users}
                messages_to_show = [msg for msg in messages_to_show
                                if msg.username.lower() in search_users_lower]
            
            if search_message:
                messages_to_show = [msg for msg in messages_to_show
                                if search_message in msg.body.lower()]
        else:
            if self.filtered_usernames:
                messages_to_show = [msg for msg in messages_to_show
                                if msg.username in self.filtered_usernames]
            
            if self.search_text:
                search_lower = self.search_text.lower()
                messages_to_show = [msg for msg in messages_to_show
                                if search_lower in msg.username.lower() or
                                    search_lower in msg.body.lower()]

        # Batch add all filtered messages
        for msg in messages_to_show:
            self.model.add_message(msg)

        self.list_view.setUpdatesEnabled(True)
        
        total = len(self.all_messages)
        shown = len(messages_to_show)

        filters = []
        
        # ADD MENTION FILTER TO INFO DISPLAY:
        if self.filter_mentions:
            filters.append("mentions only")
        
        if is_prefix_mode:
            if search_users:
                filters.append(f"users: {', '.join(sorted(search_users))}")
            if search_message:
                filters.append(f"message: '{search_message}'")
        else:
            if self.filtered_usernames:
                filters.append(f"users: {', '.join(sorted(self.filtered_usernames))}")
            if self.search_text:
                filters.append(f"search: '{self.search_text}'")

        if filters:
            filter_text = " | ".join(filters)
            self.info_label.setText(f"Showing {shown}/{total} messages ({filter_text})")
        else:
            if hasattr(self, '_pending_data'):
                _, size_text, was_truncated, from_cache = self._pending_data
                cache_marker = " 📁" if from_cache else ""
                if was_truncated:
                    self.info_label.setText(f"⚠️ Loaded {total} messages (file truncated at {self.parser.MAX_FILE_SIZE_MB}MB limit) · {size_text}{cache_marker}")
                else:
                    self.info_label.setText(f"Loaded {total} messages · {size_text}{cache_marker}")
            else:
                self.info_label.setText(f"Loaded {total} messages")

        QTimer.singleShot(0, lambda: scroll(self.list_view, mode="bottom", delay=100))

    def load_current_date(self):
        """Load single date chatlog - this is NORMAL viewing"""
        self.is_parsing = False
        self.model.clear()
        self.all_messages = []
        self.info_label.setText("Loading...")
    
        date_str = self.current_date.strftime("%Y-%m-%d")
    
        def _load():
            try:
                messages, was_truncated, from_cache = self.parser.get_messages(date_str)
                
                # Estimate size (no HTML to measure anymore)
                estimated_bytes = len(messages) * 100  # ~100 bytes per message average
                size_kb = estimated_bytes / 1024
                size_text = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
            
                self._pending_data = (messages, size_text, was_truncated, from_cache)
                QTimer.singleShot(0, self._display_messages)
            except ChatlogNotFoundError:
                self._error_occurred.emit(f"No chatlog found for {date_str}")
            except ValueError as e:
                self._error_occurred.emit(str(e))
            except Exception as e:
                self._error_occurred.emit(f"Error: {e}")
    
        threading.Thread(target=_load, daemon=True).start()

    def _display_messages(self):
        """Display messages with ban filtering (except during parse mode)"""
        try:
            messages, size_text, was_truncated, from_cache = getattr(self, '_pending_data', ([], '', False, False))
        
            cache_marker = " 📁" if from_cache else ""
            filtered_ban_count = 0
        
            if not messages:
                self.info_label.setText(f"No messages · {size_text}{cache_marker}")
                self.messages_loaded.emit([])
                self.list_view.setUpdatesEnabled(True)
                return
            
            # FILTER BANNED USERS if NOT in parse mode
            if self.ban_manager and not self.is_parsing:
                filtered_messages = []
                for msg in messages:
                    if not self.ban_manager.is_banned_by_username(msg.username):
                        filtered_messages.append(msg)
                    else:
                        filtered_ban_count += 1
                
                messages = filtered_messages
        
            # Batch operations
            self.list_view.setUpdatesEnabled(False)
          
            self.model.clear()
            self.all_messages = []
        
            if not messages:
                if filtered_ban_count > 0:
                    self.info_label.setText(f"No messages (all {filtered_ban_count} from banned users) · {size_text}{cache_marker}")
                else:
                    self.info_label.setText(f"No messages · {size_text}{cache_marker}")
                self.messages_loaded.emit([])
                self.list_view.setUpdatesEnabled(True)
                return
        
            message_data = []
            for msg in messages:
                try:
                    timestamp = datetime.strptime(msg.timestamp, "%H:%M:%S")
                    msg_data = MessageData(timestamp, msg.username, msg.message, None, msg.username)
                    message_data.append(msg_data)
                except:
                    pass
        
            self.all_messages = message_data
            self._apply_filter()
        
            self.list_view.setUpdatesEnabled(True)
          
            # Update info label with ban filter info
            if was_truncated:
                info_text = f"⚠️ Loaded {len(messages)} messages (file truncated at {self.parser.MAX_FILE_SIZE_MB}MB limit) · {size_text}{cache_marker}"
            else:
                info_text = f"Loaded {len(messages)} messages · {size_text}{cache_marker}"
            
            if filtered_ban_count > 0:
                info_text += f" · {filtered_ban_count} banned messages hidden"
            
            if not (self.filtered_usernames or self.search_text):
                self.info_label.setText(info_text)
        
            self.messages_loaded.emit(message_data)
            QTimer.singleShot(0, lambda: scroll(self.list_view, mode="bottom", delay=100))
        except Exception as e:
            self.info_label.setText(f"❌ Display error: {e}")

    def _navigate(self, days):
        """Navigate by days offset (-1 for previous, +1 for next)"""
        new_date = self.current_date + timedelta(days=days)
        if self.parser.MIN_DATE <= new_date <= datetime.now().date():
            self.current_date = new_date
            self._update_date_display()
            self.load_timer.stop()
            self.load_timer.start(300)

    def _show_calendar(self):
        calendar = QCalendarWidget()
        calendar.setWindowFlags(Qt.WindowType.Popup)
        calendar.setGridVisible(True)
        calendar.setMaximumDate(QDate.currentDate())
    
        min_qdate = QDate(self.parser.MIN_DATE.year, self.parser.MIN_DATE.month, self.parser.MIN_DATE.day)
        calendar.setMinimumDate(min_qdate)
    
        qdate = QDate(self.current_date.year, self.current_date.month, self.current_date.day)
        calendar.setSelectedDate(qdate)
    
        def on_date_selected(date: QDate):
            new_date = date.toPyDate()
            if new_date != self.current_date:
                self.current_date = new_date
                self._update_date_display()
                self.load_current_date()
            calendar.close()
    
        calendar.clicked.connect(on_date_selected)
        btn_pos = self.calendar_btn.mapToGlobal(self.calendar_btn.rect().bottomRight())
        x = btn_pos.x() - calendar.sizeHint().width()
        y = btn_pos.y() + (self.config.get("ui", "spacing", "widget_elements") or 6)
        calendar.move(x, y)
        calendar.show()

    def cleanup(self):
        if self.delegate:
            self.delegate.cleanup()
        if hasattr(self, 'scroll_button'):
            self.scroll_button.cleanup()
        if hasattr(self, 'auto_scroller'):
            self.auto_scroller.cleanup()
        if hasattr(self.parser, 'db'):
            self.parser.db.close()