"""Chatlog parser configuration UI"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QProgressBar, QTextEdit,
    QCheckBox, QFileDialog, QApplication, QMessageBox, QCalendarWidget
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QDate
from PyQt6.QtGui import QFont
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional
import threading
from functools import partial

from core.api_data import get_exact_user_id_by_name, get_usernames_history, get_registration_date
from core.chatlogs_parser import ParseConfig, ChatlogsParserEngine
from helpers.create import create_icon_button, _render_svg_icon
from helpers.data import get_data_dir
from helpers.fonts import get_font, FontType


class ParserWorker(QThread):
    """Worker thread for parsing"""
    progress = pyqtSignal(str, str, int) # start_date, current_date, percent
    messages_found = pyqtSignal(list, str) # messages, date
    finished = pyqtSignal(list) # all messages
    error = pyqtSignal(str)
    sync_stats = pyqtSignal(int, dict) # fetched_count, db_stats
   
    def __init__(self, config: ParseConfig):
        super().__init__()
        self.config = config
        self.engine = ChatlogsParserEngine()
   
    def run(self):
        try:
            # Get missing dates count before fetching
            missing_dates = self.engine.parser.db.get_missing_dates(
                self.config.from_date,
                self.config.to_date
            )
            total_missing = len(missing_dates)
            
            # Run parse
            messages = self.engine.parse(
                self.config,
                progress_callback=self.progress.emit,
                message_callback=self.messages_found.emit if self.config.mode != 'syncdatabase' else None
            )
            
            # For sync mode, emit stats
            if self.config.mode == 'syncdatabase':
                db_stats = self.engine.parser.db.get_database_stats()
                self.sync_stats.emit(total_missing, db_stats)
            
            self.finished.emit(messages)
        except Exception as e:
            self.error.emit(str(e))
   
    def stop(self):
        self.engine.stop()


class ChatlogsParserConfigWidget(QWidget):
    """Configuration widget for chatlog parser"""
   
    parse_started = pyqtSignal(object) # ParseConfig
    parse_cancelled = pyqtSignal()
   
    def __init__(self, config, icons_path: Path, account=None):
        super().__init__()
        self.config = config
        self.icons_path = icons_path
        self.account = account
        self.is_parsing = False
        self.is_fetching_username = False
        self.is_fetching_search = False
        self.original_usernames = []
        self.is_sync_mode = False
       
        self._setup_ui()
   
    def set_account(self, account):
        """Set account for auto-populating mention usernames"""
        self.account = account
        self._update_mention_label()
   
    def _create_label(self, text: str) -> QLabel:
        """Create a label with consistent height and alignment"""
        label = QLabel(text)
        label.setFixedHeight(self.input_height)
        label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        return label
   
    def _create_input(self, placeholder: str = "", object_name: str = "") -> QLineEdit:
        """Create an input field with consistent height"""
        input_field = QLineEdit()
        if placeholder:
            input_field.setPlaceholderText(placeholder)
        if object_name:
            input_field.setObjectName(object_name)
        input_field.setFixedHeight(self.input_height)
        input_field.setFont(get_font(FontType.UI))
        return input_field
   
    def _create_combo(self, items: list) -> QComboBox:
        """Create a combo box with consistent height"""
        combo = QComboBox()
        combo.addItems(items)
        combo.setFixedHeight(self.input_height)
        combo.setFont(get_font(FontType.UI))
        return combo
   
    def _create_input_row(self, label_text: str, placeholder: str = "", object_name: str = "", as_widget: bool = False):
        """Create a complete input row with label and input field"""
        layout = QHBoxLayout()
        layout.setSpacing(self.spacing)
       
        label = self._create_label(label_text)
        layout.addWidget(label)
       
        input_field = self._create_input(placeholder, object_name)
        layout.addWidget(input_field, stretch=1)
       
        if as_widget:
            container = QWidget()
            container.setLayout(layout)
            return container, input_field
       
        return layout, input_field
   
    def _parse_short_date(self, date_str: str):
        """Convert YYMMDD to YYYY-MM-DD"""
        clean = date_str.replace('-', '').replace('/', '').replace('.', '').strip()
        if len(clean) == 6 and clean.isdigit():
            try:
                yy, mm, dd = int(clean[0:2]), int(clean[2:4]), int(clean[4:6])
                return datetime(2000 + yy, mm, dd).strftime('%Y-%m-%d')
            except ValueError:
                pass
        return date_str

    def _auto_format_date(self, input_field):
        """Auto-format dates on blur"""
        text = input_field.text().strip()
        if not text:
            return
        parts = [self._parse_short_date(p) for p in text.split()]
        if parts:
            input_field.setText(' '.join(parts))

    def _show_date_picker(self, input_field, calendar_btn):
        """Show calendar picker"""
        calendar = QCalendarWidget()
        calendar.setWindowFlags(Qt.WindowType.Popup)
        calendar.setGridVisible(True)
        calendar.setMaximumDate(QDate.currentDate())
        calendar.setMinimumDate(QDate(2012, 12, 2))
        
        try:
            date_str = input_field.text().split()[0]
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
            calendar.setSelectedDate(QDate(date.year, date.month, date.day))
        except:
            calendar.setSelectedDate(QDate.currentDate())
        
        calendar.clicked.connect(lambda d: (
            input_field.setText(d.toPyDate().strftime('%Y-%m-%d')),
            calendar.close()
        ))
        
        # Position calendar relative to button
        btn_pos = calendar_btn.mapToGlobal(calendar_btn.rect().bottomRight())
        x = btn_pos.x() - calendar.sizeHint().width()
        y = btn_pos.y() + (self.config.get("ui", "spacing", "widget_elements") or 6)
        calendar.move(x, y)
        calendar.show()
   
    def _setup_ui(self):
        margin = self.config.get("ui", "margins", "widget") or 5
        spacing = self.config.get("ui", "spacing", "widget_elements") or 6
        self.spacing = spacing
        self.input_height = self.config.get("ui", "input_height") or 48
       
        layout = QVBoxLayout()
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(self.spacing)
        self.setLayout(layout)
       
        # Title
        title = QLabel("Parse Chat Logs")
        title.setFont(get_font(FontType.HEADER))
        layout.addWidget(title)
       
        # Mode selection
        mode_container = QWidget()
        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(self.spacing)
        mode_label = self._create_label("Mode:")
        mode_layout.addWidget(mode_label)
       
        self.mode_combo = self._create_combo([
            "Single Date",
            "From Date",
            "Date Range",
            "From Start",
            "From Registered",
            "Personal Mentions",
            "Sync Database"
        ])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_layout.addWidget(self.mode_combo, stretch=1)
        mode_container.setLayout(mode_layout)
        layout.addWidget(mode_container)
       
        # Date inputs (dynamic based on mode)
        self.date_container = QWidget()
        self.date_layout = QVBoxLayout()
        self.date_layout.setContentsMargins(0, 0, 0, 0)
        self.date_layout.setSpacing(self.spacing)
        self.date_container.setLayout(self.date_layout)
        layout.addWidget(self.date_container)
       
        # Username input with fetch history button (label changes in Personal Mentions mode)
        username_container = QWidget()
        username_layout, self.username_input = self._create_input_row(
            "Usernames:",
            "comma-separated (leave empty for all users)"
        )
        
        # Get reference to the label that was created
        self.username_label = username_layout.itemAt(0).widget()
       
        # Connect to enable/disable fetch button based on input
        self.username_input.textChanged.connect(self._update_fetch_button_state)
        self.username_input.textChanged.connect(self._update_mention_label)
       
        # Fetch history button
        self.fetch_history_button = create_icon_button(
            self.icons_path, "user-received.svg", "Fetch username history",
            size_type="large", config=self.config
        )
        self.fetch_history_button.clicked.connect(lambda: self._fetch_username_history(self.username_input))
        self.fetch_history_button.setEnabled(False)
        username_layout.addWidget(self.fetch_history_button)
       
        username_container.setLayout(username_layout)
        self.username_container_widget = username_container
        layout.addWidget(username_container)
       
        # Search terms input (label changes in Personal Mentions mode)
        search_container = QWidget()
        search_layout, self.search_input = self._create_input_row(
            "Search:",
            "comma-separated search terms (leave empty for all messages)"
        )
        
        # Get reference to the label that was created
        self.search_label = search_layout.itemAt(0).widget()
        
        # Connect to update mention label and fetch button state
        self.search_input.textChanged.connect(self._update_mention_label)
        self.search_input.textChanged.connect(self._update_fetch_button_state)
        
        # Fetch history button for search/mentions field
        self.search_fetch_history_button = create_icon_button(
            self.icons_path, "user-received.svg", "Fetch username history",
            size_type="large", config=self.config
        )
        self.search_fetch_history_button.clicked.connect(lambda: self._fetch_username_history(self.search_input))
        self.search_fetch_history_button.setEnabled(False)
        search_layout.addWidget(self.search_fetch_history_button)
        
        search_container.setLayout(search_layout)
        self.search_container_widget = search_container
        layout.addWidget(search_container)
       
        # Mention label (only for personal mentions mode)
        self.mention_label_widget = QLabel()
        self.mention_label_widget.setWordWrap(True)
        self.mention_label_widget.setStyleSheet("color: #888; padding: 4px;")
        self.mention_label_widget.setVisible(False)
        layout.addWidget(self.mention_label_widget)
       
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
       
        # Progress label
        self.progress_label = QLabel("")
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)
       
        # Buttons row
        button_layout = QHBoxLayout()
        button_layout.setSpacing(self.config.get("ui", "buttons", "spacing") or 8)
       
        self.parse_button = create_icon_button(
            self.icons_path, "play.svg", "Start parsing (S)",
            size_type="large", config=self.config
        )
        self.parse_button.clicked.connect(self._on_parse_clicked)
        button_layout.addWidget(self.parse_button)
       
        # Copy button (initially hidden)
        self.copy_button = create_icon_button(
            self.icons_path, "clipboard.svg", "Copy results to clipboard (Ctrl+C)",
            size_type="large", config=self.config
        )
        self.copy_button.clicked.connect(self._on_copy_clicked)
        self.copy_button.setVisible(False)
        button_layout.addWidget(self.copy_button)
       
        # Save button (initially hidden)
        self.save_button = create_icon_button(
            self.icons_path, "save.svg", "Save results to file (Ctrl+S)",
            size_type="large", config=self.config
        )
        self.save_button.clicked.connect(self._on_save_clicked)
        self.save_button.setVisible(False)
        button_layout.addWidget(self.save_button)
       
        button_layout.addStretch()
        layout.addLayout(button_layout)
       
        # Add stretch to push everything to the top
        layout.addStretch()
       
        # Initialize with first mode
        self._on_mode_changed(0)
   
    def _update_fetch_button_state(self):
        """Enable/disable both fetch buttons based on inputs"""
        has_username = bool(self.username_input.text().strip())
        has_search = bool(self.search_input.text().strip())
        self.fetch_history_button.setEnabled(has_username and not self.is_fetching_username)
        self.search_fetch_history_button.setEnabled(has_search and not self.is_fetching_search)
   
    def _set_username_fetch_loading(self, is_loading: bool):
        """Change username fetch button icon to loader or back to normal"""
        icon_name = "loader.svg" if is_loading else "user-received.svg"
        tooltip = "Fetching..." if is_loading else "Fetch username history"
        icon_size = self.fetch_history_button._icon_size
        self.fetch_history_button.setIcon(_render_svg_icon(self.icons_path / icon_name, icon_size))
        self.fetch_history_button.setToolTip(tooltip)
   
    def _set_search_fetch_loading(self, is_loading: bool):
        """Change search fetch button icon to loader or back to normal"""
        icon_name = "loader.svg" if is_loading else "user-received.svg"
        tooltip = "Fetching..." if is_loading else "Fetch username history"
        icon_size = self.search_fetch_history_button._icon_size
        self.search_fetch_history_button.setIcon(_render_svg_icon(self.icons_path / icon_name, icon_size))
        self.search_fetch_history_button.setToolTip(tooltip)
   
    def _fetch_username_history(self, input_field: QLineEdit):
        """Generic fetch username history for any input field"""
        text = input_field.text().strip()
        if not text:
            return
       
        usernames = [u.strip() for u in text.split(',') if u.strip()]
        if not usernames:
            return

        # Store original usernames before expansion
        self.original_usernames = usernames.copy()
       
        # Set loading state for specific field
        if input_field == self.username_input:
            self.is_fetching_username = True
            self._set_username_fetch_loading(True)
        elif input_field == self.search_input:
            self.is_fetching_search = True
            self._set_search_fetch_loading(True)
       
        self._update_fetch_button_state()
       
        def _fetch():
            expanded = set()
            not_found = []
           
            try:
                for username in usernames:
                    # Check if user exists first
                    user_id = get_exact_user_id_by_name(username)
                   
                    if not user_id:
                        # User doesn't exist
                        not_found.append(username)
                        continue
                   
                    # User exists, add original username
                    expanded.add(username)
                   
                    # Try to get username history
                    history = get_usernames_history(username)
                   
                    # If we got history, add it
                    if history and isinstance(history, list):
                        expanded.update(history)
               
                # Convert to sorted list for consistent ordering
                expanded_list = sorted(expanded)
               
                # Update UI on main thread - using partial to avoid closure issues
                QTimer.singleShot(0, partial(self._on_fetch_complete, input_field, expanded_list, not_found))
           
            except Exception as e:
                error_msg = str(e)
                QTimer.singleShot(0, partial(self._on_fetch_error, input_field, error_msg))
       
        threading.Thread(target=_fetch, daemon=True).start()
   
    def _on_fetch_complete(self, input_field: QLineEdit, usernames: list, not_found: list):
        """Handle fetch completion"""
        # Reset loading state
        if input_field == self.username_input:
            self.is_fetching_username = False
            self._set_username_fetch_loading(False)
        elif input_field == self.search_input:
            self.is_fetching_search = False
            self._set_search_fetch_loading(False)
       
        self._update_fetch_button_state()
       
        # Always update username field with valid usernames (even if empty)
        if usernames:
            input_field.setText(', '.join(usernames))
        else:
            # All users not found - clear the field
            input_field.clear()
       
        # Show errors if any users weren't found
        if not_found:
            QMessageBox.warning(
                self,
                "Users Not Found",
                f"The following users were not found:\n{', '.join(not_found)}"
            )
        elif usernames:
            # Only show success message if we found users and had no errors
            QMessageBox.information(
                self,
                "History Fetched",
                f"Retrieved {len(usernames)} usernames including history."
            )
        else:
            # No users found at all
            QMessageBox.warning(
                self,
                "No Users Found",
                "None of the entered usernames were found."
            )
   
    def _on_fetch_error(self, input_field: QLineEdit, error: str):
        """Handle fetch error"""
        # Reset loading state
        if input_field == self.username_input:
            self.is_fetching_username = False
            self._set_username_fetch_loading(False)
        elif input_field == self.search_input:
            self.is_fetching_search = False
            self._set_search_fetch_loading(False)
       
        self._update_fetch_button_state()
       
        QMessageBox.critical(self, "Error", f"Failed to fetch username history:\n{error}")
   
    def _get_current_username(self):
        """Get current username from account - try chat_username first, fall back to login"""
        if not self.account:
            return None
        return self.account.get('chat_username') or self.account.get('login')
   
    def _update_mention_label(self):
        """Update the mention label based on current mode and inputs"""
        mode = self.mode_combo.currentText()
        
        if mode != "Personal Mentions":
            self.mention_label_widget.setVisible(False)
            return
        
        self.mention_label_widget.setVisible(True)
       
        # Get current username
        current_username = self._get_current_username()
       
        # Get search terms (mentions to search for)
        search_text = self.search_input.text().strip()
        search_terms = [k.strip() for k in search_text.split(',') if k.strip()] if search_text else []
       
        # Add current username if available and not already in list
        all_mentions = []
        if current_username:
            all_mentions.append(current_username)
        for term in search_terms:
            if not current_username or term.lower() != current_username.lower():
                all_mentions.append(term)
       
        # Get username filter (which users' messages to search in)
        username_text = self.username_input.text().strip()
        username_filter = [u.strip() for u in username_text.split(',') if u.strip()] if username_text else []
       
        # Build label text
        if all_mentions and username_filter:
            mentions_str = ', '.join(all_mentions)
            users_str = ', '.join(username_filter)
            self.mention_label_widget.setText(f"🔍 Searching mentions of: {mentions_str} in messages from: {users_str}")
        elif all_mentions:
            mentions_str = ', '.join(all_mentions)
            self.mention_label_widget.setText(f"🔍 Searching mentions of: {mentions_str} in messages from: all users")
        elif username_filter:
            users_str = ', '.join(username_filter)
            self.mention_label_widget.setText(f"⚠️ No mentions specified. Please add keywords in the Mentions field.")
        else:
            self.mention_label_widget.setText("⚠️ No mentions specified. Please log in or add keywords in the Mentions field.")
   
    def _on_mode_changed(self, index: int):
        """Update UI based on selected mode"""
        # Clear existing date inputs
        while self.date_layout.count():
            item = self.date_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
       
        mode = self.mode_combo.currentText()
        self.is_sync_mode = (mode == "Sync Database")
        is_mention_mode = (mode == "Personal Mentions")
       
        # Update field labels based on mode
        if is_mention_mode:
            self.username_label.setText("From Users:")
            self.username_input.setPlaceholderText("comma-separated (leave empty for all users)")
            self.search_label.setText("Mentions:")
            self.search_input.setPlaceholderText("keywords or usernames to search for (comma-separated)")
            
            # Prefill current username in Mentions field
            if not self.search_input.text().strip():
                current_username = self._get_current_username()
                if current_username:
                    self.search_input.setText(current_username)
        else:
            self.username_label.setText("Usernames:")
            self.username_input.setPlaceholderText("comma-separated (leave empty for all users)")
            self.search_label.setText("Search:")
            self.search_input.setPlaceholderText("comma-separated search terms (leave empty for all messages)")
            
            # Clear search input when switching away from Personal Mentions
            if hasattr(self, '_previous_mode') and self._previous_mode == "Personal Mentions":
                self.search_input.clear()
        
        self._previous_mode = mode
        
        # Update mention label
        self._update_mention_label()
        
        # Hide username and search inputs for sync mode
        self.username_container_widget.setVisible(not self.is_sync_mode)
        self.search_container_widget.setVisible(not self.is_sync_mode)
       
        if mode == "Single Date":
            self._add_date_input("Date:", "single_date", "YYYY-MM-DD")
       
        elif mode == "From Date":
            self._add_date_input("From:", "from_date", "YYYY-MM-DD")
            info = QLabel("(to today)")
            info.setStyleSheet("color: #888;")
            self.date_layout.addWidget(info)
       
        elif mode == "Date Range":
            self._add_date_input("Range:", "range_dates", "YYYY-MM-DD YYYY-MM-DD")
       
        elif mode == "From Start":
            info = QLabel("Will parse from 2012-12-02 to today")
            info.setStyleSheet("color: #888;")
            self.date_layout.addWidget(info)
       
        elif mode == "From Registered":
            info = QLabel("Will use registration date of entered user(s)")
            info.setStyleSheet("color: #888;")
            self.date_layout.addWidget(info)
       
        elif mode == "Sync Database":
            info = QLabel("📁 Sync all missing chatlogs to database")
            info.setStyleSheet("color: #4CAF50; font-weight: bold; padding: 8px;")
            self.date_layout.addWidget(info)
            
            desc = QLabel("This will fetch all chatlogs from 2012-12-02 to today that are not yet in the database. "
                         "No messages will be displayed - only database synchronization.")
            desc.setWordWrap(True)
            desc.setStyleSheet("color: #888; padding: 4px;")
            self.date_layout.addWidget(desc)
       
        elif mode == "Personal Mentions":
            sub_mode_layout = QHBoxLayout()
            sub_mode_layout.setSpacing(self.spacing)
            sub_mode_label = self._create_label("Date Mode:")
            sub_mode_layout.addWidget(sub_mode_label)
           
            self.mention_date_combo = self._create_combo([
                "Single Date",
                "From Date",
                "Date Range",
                "From Start",
                "Last N Days"
            ])
            self.mention_date_combo.currentIndexChanged.connect(self._on_mention_date_mode_changed)
            sub_mode_layout.addWidget(self.mention_date_combo, stretch=1)
           
            container = QWidget()
            container.setLayout(sub_mode_layout)
            self.date_layout.addWidget(container)
           
            # Initialize with first sub-mode
            self._on_mention_date_mode_changed(0)
   
    def _on_mention_date_mode_changed(self, index: int):
        """Update date inputs for personal mentions sub-mode"""
        # Remove existing inputs (except the sub-mode selector)
        while self.date_layout.count() > 1:
            item = self.date_layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
       
        sub_mode = self.mention_date_combo.currentText()
       
        if sub_mode == "Single Date":
            self._add_date_input("Date:", "mention_single_date", "YYYY-MM-DD")
        elif sub_mode == "From Date":
            self._add_date_input("From:", "mention_from_date", "YYYY-MM-DD")
        elif sub_mode == "Date Range":
            self._add_date_input("Range:", "mention_range_dates", "YYYY-MM-DD YYYY-MM-DD")
        elif sub_mode == "From Start":
            pass # No input needed
        elif sub_mode == "Last N Days":
            days_layout, self.days_input = self._create_input_row("Days:", "7")
            self.days_input.setText("7")
           
            container = QWidget()
            container.setLayout(days_layout)
            self.date_layout.addWidget(container)
   
    def _add_date_input(self, label_text: str, obj_name: str, placeholder: str = "YYYY-MM-DD"):
        """Add a date input field with calendar picker"""
        layout, line_edit = self._create_input_row(label_text, placeholder, obj_name)
        
        # Add auto-format on blur
        line_edit.editingFinished.connect(lambda: self._auto_format_date(line_edit))
        
        # Add calendar button
        calendar_btn = create_icon_button(
            self.icons_path, "calendar.svg", "Select date",
            size_type="large", config=self.config
        )
        calendar_btn.clicked.connect(lambda: self._show_date_picker(line_edit, calendar_btn))
        layout.addWidget(calendar_btn)
        
        container = QWidget()
        container.setLayout(layout)
        self.date_layout.addWidget(container)
   
    def _on_parse_clicked(self):
        """Handle parse button click"""
        if self.is_parsing:
            # Stop parsing
            self._cancel_parsing()
        else:
            # Start parsing
            self._start_parsing()
   
    def _on_copy_clicked(self):
        """Copy results to clipboard"""
        pass
   
    def _on_save_clicked(self):
        """Save results to file"""
        pass
   
    def _start_parsing(self):
        """Validate inputs and start parsing"""
        try:
            config = self._build_parse_config()
            if not config:
                return
           
            # Update UI for parsing state
            self.is_parsing = True
            self.parse_button.setIcon(_render_svg_icon(self.icons_path / "stop.svg", self.parse_button._icon_size))
            self.parse_button.setToolTip("Stop parsing (C)")
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            self.progress_label.setVisible(True)
            
            if config.mode == 'syncdatabase':
                self.progress_label.setText("Syncing database...")
            else:
                self.progress_label.setText(f"{config.from_date} - {config.from_date}")
           
            # Hide copy/save buttons during parsing
            self.copy_button.setVisible(False)
            self.save_button.setVisible(False)
           
            # Emit signal
            self.parse_started.emit(config)
           
        except Exception as e:
            print(f"Error starting parse: {e}")
            self._reset_ui()
   
    def _cancel_parsing(self):
        """Cancel parsing"""
        self.parse_cancelled.emit()
        self._reset_ui()
   
    def _reset_ui(self):
        """Reset UI to non-parsing state"""
        self.is_parsing = False
        self.parse_button.setIcon(_render_svg_icon(self.icons_path / "play.svg", self.parse_button._icon_size))
        self.parse_button.setToolTip("Start parsing (S)")
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self.progress_label.setText("")
   
    def show_copy_save_buttons(self):
        """Show copy and save buttons after successful parse"""
        self.copy_button.setVisible(True)
        self.save_button.setVisible(True)
   
    def update_progress(self, start_date: str, current_date: str, percent: int):
        """Update progress display"""
        self.progress_bar.setValue(percent)
        if self.is_sync_mode:
            self.progress_label.setText(f"Syncing: {current_date} ({percent}%)")
        else:
            self.progress_label.setText(f"{start_date} - {current_date}")
   
    def _build_parse_config(self) -> Optional[ParseConfig]:
        """Build ParseConfig from UI inputs"""
        mode = self.mode_combo.currentText()
       
        # Earliest allowed date
        EARLIEST_ALLOWED_DATE = "2012-12-02"
       
        # Get dates based on mode
        from_date = None
        to_date = None
       
        if mode == "Sync Database":
            from_date = EARLIEST_ALLOWED_DATE
            to_date = datetime.now().strftime('%Y-%m-%d')
       
        elif mode == "Single Date":
            date_input = self.findChild(QLineEdit, "single_date")
            if not date_input or not date_input.text().strip():
                QMessageBox.warning(self, "Missing Date", "Please enter a date")
                return None
            from_date = to_date = date_input.text().strip()
       
        elif mode == "From Date":
            date_input = self.findChild(QLineEdit, "from_date")
            if not date_input or not date_input.text().strip():
                QMessageBox.warning(self, "Missing Date", "Please enter from date")
                return None
            from_date = date_input.text().strip()
            to_date = datetime.now().strftime('%Y-%m-%d')
       
        elif mode == "Date Range":
            range_input = self.findChild(QLineEdit, "range_dates")
            if not range_input or not range_input.text().strip():
                QMessageBox.warning(self, "Missing Dates", "Please enter date range in format YYYY-MM-DD YYYY-MM-DD")
                return None
            dates = range_input.text().strip().split()
            if len(dates) != 2:
                QMessageBox.warning(self, "Invalid Format", "Invalid range format - use YYYY-MM-DD YYYY-MM-DD")
                return None
            from_date, to_date = dates
       
        elif mode == "From Start":
            from_date = EARLIEST_ALLOWED_DATE
            to_date = datetime.now().strftime('%Y-%m-%d')
       
        elif mode == "From Registered":
            # Use original typed usernames if fetch history was used, otherwise parse from field
            if self.original_usernames:
                # Use stored original usernames (before fetch history expanded them)
                usernames_to_check = self.original_usernames
            else:
                # Parse directly from field (fetch history was not used)
                original_usernames_text = self.username_input.text().strip()
                if not original_usernames_text:
                    QMessageBox.warning(self, "Missing Username", "Please enter at least one username")
                    return None
                usernames_to_check = [u.strip() for u in original_usernames_text.split(',') if u.strip()]
           
            if not usernames_to_check:
                QMessageBox.warning(self, "Missing Username", "Please enter at least one username")
                return None
           
            # Fetch registration dates only for originally typed usernames
            reg_dates = []
            for username in usernames_to_check:
                reg_date = get_registration_date(username)
                if reg_date:
                    reg_dates.append(reg_date)
           
            if not reg_dates:
                QMessageBox.warning(self, "Error", "Could not get registration date for specified username(s)")
                return None
           
            # Get earliest registration date, but clamp to earliest allowed date
            earliest_reg = min(reg_dates)
            from_date = max(earliest_reg, EARLIEST_ALLOWED_DATE)
            to_date = datetime.now().strftime('%Y-%m-%d')
           
            # Optionally inform user if date was clamped
            if earliest_reg < EARLIEST_ALLOWED_DATE:
                QMessageBox.information(
                    self,
                    "Date Adjusted",
                    f"Registration date ({earliest_reg}) is before earliest available logs.\n"
                    f"Starting from {EARLIEST_ALLOWED_DATE} instead."
                )
       
        elif mode == "Personal Mentions":
            sub_mode = self.mention_date_combo.currentText()
           
            if sub_mode == "Single Date":
                date_input = self.findChild(QLineEdit, "mention_single_date")
                if not date_input or not date_input.text().strip():
                    QMessageBox.warning(self, "Missing Date", "Please enter a date")
                    return None
                from_date = to_date = date_input.text().strip()
           
            elif sub_mode == "From Date":
                date_input = self.findChild(QLineEdit, "mention_from_date")
                if not date_input or not date_input.text().strip():
                    QMessageBox.warning(self, "Missing Date", "Please enter from date")
                    return None
                from_date = date_input.text().strip()
                to_date = datetime.now().strftime('%Y-%m-%d')
           
            elif sub_mode == "Date Range":
                range_input = self.findChild(QLineEdit, "mention_range_dates")
                if not range_input or not range_input.text().strip():
                    QMessageBox.warning(self, "Missing Dates", "Please enter date range in format YYYY-MM-DD YYYY-MM-DD")
                    return None
                dates = range_input.text().strip().split()
                if len(dates) != 2:
                    QMessageBox.warning(self, "Invalid Format", "Invalid range format - use YYYY-MM-DD YYYY-MM-DD")
                    return None
                from_date, to_date = dates
           
            elif sub_mode == "From Start":
                from_date = EARLIEST_ALLOWED_DATE
                to_date = datetime.now().strftime('%Y-%m-%d')
           
            elif sub_mode == "Last N Days":
                if not hasattr(self, 'days_input') or not self.days_input.text().strip():
                    QMessageBox.warning(self, "Missing Days", "Please enter number of days")
                    return None
                try:
                    days = int(self.days_input.text().strip())
                    if days <= 0:
                        QMessageBox.warning(self, "Invalid Days", "Days must be positive")
                        return None
                    to_date = datetime.now().date()
                    from_date = to_date - timedelta(days=days-1)
                    from_date = from_date.strftime('%Y-%m-%d')
                    to_date = to_date.strftime('%Y-%m-%d')
                except ValueError:
                    QMessageBox.warning(self, "Invalid Days", "Invalid number of days")
                    return None
        
        # Get usernames and search terms (skip for sync mode)
        usernames = [] if mode == "Sync Database" else self._get_usernames()
        search_terms = [] if mode == "Sync Database" else self._get_search_terms()
        mention_keywords = []
        
        # Override for Personal Mentions mode
        if mode == "Personal Mentions":
            # For Personal Mentions mode:
            # - usernames = filter which users' messages to search in
            # - mention_keywords = what to search for in those messages (usernames OR any keywords)
            usernames = self._get_usernames()
            
            # Build mention keywords from current username + search field
            mention_keywords = []
            current_username = self._get_current_username()
            if current_username:
                mention_keywords.append(current_username)
            
            # Add search terms (excluding duplicates)
            # These can be usernames OR any keywords the user wants to search for
            search_text = self.search_input.text().strip()
            if search_text:
                additional = [kw.strip() for kw in search_text.split(',') if kw.strip()]
                for kw in additional:
                    if not current_username or kw.lower() != current_username.lower():
                        mention_keywords.append(kw)
            
            search_terms = [] # In Personal Mentions mode, search_terms are moved to mention_keywords
        
        # Build config
        config = ParseConfig(
            mode=mode.lower().replace(' ', ''),
            from_date=from_date,
            to_date=to_date,
            usernames=usernames,
            search_terms=search_terms,
            mention_keywords=mention_keywords
        )
        
        return config
    
    def _get_usernames(self) -> List[str]:
        """Get usernames from field"""
        text = self.username_input.text().strip()
        if not text:
            return []
        return [u.strip() for u in text.split(',') if u.strip()]
    
    def _get_search_terms(self) -> List[str]:
        """Get search terms"""
        text = self.search_input.text().strip()
        if not text:
            return []
        return [term.strip() for term in text.split(',') if term.strip()]