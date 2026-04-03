"""Chat window with XMPP integration"""
import threading
import re
from pathlib import Path
from datetime import datetime
from PyQt6.QtWidgets import(
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QApplication, QMenu,
    QStackedWidget, QStatusBar, QLabel, QProgressBar, QPushButton, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QEvent
from PyQt6.QtGui import QAction
            

from helpers.config import Config
from helpers.create import create_icon_button, update_all_icons, set_theme, HoverIconButton
from helpers.resize import handle_chat_resize, recalculate_layout
from helpers.color_utils import get_private_message_colors
from helpers.scroll import scroll
from helpers.cache import get_cache
from helpers.username_color_manager import(
    change_username_color,
    reset_username_color,
    update_from_server
)
from helpers.emoticons import EmoticonManager
from helpers.fonts import get_font, FontType, get_userlist_width
from helpers.font_scaler import FontScaleSlider
from helpers.voice_engine import get_voice_engine, play_sound
from helpers.me_action import format_me_action
from helpers.window_size_manager import WindowSizeManager
from helpers.window_presets_dialog import WindowPresetsDialog
from themes.theme import ThemeManager
from core.xmpp import XMPPClient
from core.messages import Message
from ui.ui_messages import MessagesWidget
from ui.ui_userlist import UserListWidget
from ui.ui_chatlog import ChatlogWidget
from ui.ui_chatlog_userlist import ChatlogUserlistWidget
from ui.ui_profile import ProfileWidget
from ui.ui_emoticon_selector import EmoticonSelectorWidget, PANEL_WIDTH
from ui.ui_pronunciation import PronunciationWidget
from ui.ui_banlist import BanListWidget
from helpers.duration_dialog import DurationDialog
from helpers.jid_utils import extract_user_data_from_jid
from ui.ui_buttons import ButtonPanel
from helpers.help import HelpPanel
from components.notification import show_notification, popup_manager
from components.messages_separator import NewMessagesSeparator


class SignalEmitter(QObject):
    message_received = pyqtSignal(object)
    presence_received = pyqtSignal(object)
    bulk_update_complete = pyqtSignal()
    connection_changed = pyqtSignal(str)

class ChatWindow(QWidget):
    _dispatch = pyqtSignal(object)  # thread-safe main-thread callable dispatch

    def __init__(
        self,
        account=None,
        app_controller=None,
        pronunciation_manager=None,
        ban_manager=None
        ):
        super().__init__()
        self._dispatch.connect(lambda f: f())
        self.app_controller = app_controller
        self.pronunciation_manager = pronunciation_manager
        self.ban_manager = ban_manager
        self.tray_mode = False
        self.really_close = False
        self.account = account
        self.xmpp_client = None
        self.signal_emitter = SignalEmitter()
        self.cache = get_cache()
        self.initial_roster_loading = False
        self.auto_hide_messages_userlist = True
        self.auto_hide_chatlog_userlist = True

        # Track window show/reset state to avoid persisting programmatic geometry
        self._showing_window = False
        self._resetting_geometry = False

        # Simple connection state tracking
        self.is_connecting = False # True when attempting to connect
        self.allow_reconnect = True # Disable when switching accounts
        self.reconnect_count = 0 # Incremented each time a reconnect attempt is made
        self.reconnect_timer = None # Timer for delayed reconnect attempts

        # Private messaging state
        self.private_mode = False
        self.private_chat_jid = None
        self.private_chat_username = None
        self.private_chat_user_id = None

        # Track new messages marker
        self.has_new_messages_marker = False

        # Initialize paths and config
        self.config_path = Path(__file__).parent.parent / "settings" / "config.json"
        self.icons_path = Path(__file__).parent.parent / "icons"

        self.config = Config(str(self.config_path))

        # Initialize emoticon manager
        emoticons_path = Path(__file__).parent.parent / "emoticons"
        self.emoticon_manager = EmoticonManager(emoticons_path)
        
        # Initialize window size manager
        self.window_size_manager = WindowSizeManager(
            self.config,
            on_save_callback=self.update_reset_size_button_state
        )
        
        self.theme_manager = ThemeManager(self.config)
        self.theme_manager.apply_theme()
        set_theme(self.theme_manager.is_dark())

        # Initialize voice engine
        self.voice_engine = get_voice_engine()
        # Pass pronunciation manager to voice engine
        if self.pronunciation_manager:
            self.voice_engine.set_pronunciation_manager(self.pronunciation_manager)
        self.mention_sound_path = None
        self.ban_sound_path = None
        self._setup_sounds()

        self._init_ui()

        self.signal_emitter.message_received.connect(self.on_message)
        self.signal_emitter.presence_received.connect(self.on_presence)
        self.signal_emitter.bulk_update_complete.connect(self.on_bulk_update_complete)
        self.signal_emitter.connection_changed.connect(self.set_connection_status)

        if account:
            self.set_connection_status('connecting')
            self.connect_xmpp()

        # Parse status references (created dynamically)
        self.parse_status_widget = None
        self.parse_progress_bar = None
        self.parse_current_label = None

    def set_tray_mode(self, enabled: bool):
        self.tray_mode = enabled

    def on_change_username_color(self):
        """Called from ButtonPanel to change own username color."""
        if not self.app_controller:
            QMessageBox.warning(self, "Unavailable", "This action requires the application controller.")
            return
        self.app_controller._refresh_own_username_color(change_username_color)

    def on_reset_username_color(self):
        """Called from ButtonPanel to reset own username color."""
        if not self.app_controller:
            QMessageBox.warning(self, "Unavailable", "This action requires the application controller.")
            return
        self.app_controller._refresh_own_username_color(reset_username_color)

    def on_update_username_color(self):
        """Called from ButtonPanel to update own username color from server."""
        if not self.app_controller:
            QMessageBox.warning(self, "Unavailable", "This action requires the application controller.")
            return
        self.app_controller._refresh_own_username_color(update_from_server)

    def on_toggle_voice_sound(self):
        """Toggle TTS (Voice Sound) from the panel button."""
        current = self.config.get("sound", "tts_enabled") or False
        new = not current
        
        # Persist centrally via app controller so tray stays in sync
        config = self.app_controller.config if self.app_controller else self.config
        config.set("sound", "tts_enabled", value=new)
        # Also update local config data to keep in sync
        if self.app_controller:
            self.config.data = self.app_controller.config.data
        
        # update tray menu state immediately
        if self.app_controller and hasattr(self.app_controller, 'update_sound_menu'):
            self.app_controller.update_sound_menu()
        
        # Update engine and visual
        self.voice_engine.set_enabled(new)
        self.button_panel.set_button_state(self.button_panel.voice_button, new)

    def update_voice_button_state(self):
        """Sync voice button visual and engine state with config."""
        enabled = self.config.get("sound", "tts_enabled") or False
        self.voice_engine.set_enabled(enabled)
        
        # Defensive: button may not exist yet in some tests
        if getattr(self, 'button_panel', None) and getattr(self.button_panel, 'voice_button', None):
            self.button_panel.set_button_state(self.button_panel.voice_button, enabled)

    def on_toggle_effects_sound(self):
        """Toggle effects sound on/off from the panel button."""
        current = self.config.get("sound", "effects_enabled")
        if current is None:
            current = True
        new = not current

        # Persist centrally via app controller so tray stays in sync
        config = self.app_controller.config if self.app_controller else self.config
        config.set("sound", "effects_enabled", value=new)
        # Also update local config data to keep in sync
        if self.app_controller:
            self.config.data = self.app_controller.config.data

        # update tray menu state immediately
        if self.app_controller and hasattr(self.app_controller, 'update_sound_menu'):
            self.app_controller.update_sound_menu()

        # Update visual and icon
        if getattr(self, 'button_panel', None) and getattr(self.button_panel, 'effects_button', None):
            self.button_panel.set_button_state(self.button_panel.effects_button, new)
            self.button_panel.update_effects_button_icon()

    def update_effects_button_state(self):
        """Sync effects button visual to config state."""
        enabled = self.config.get("sound", "effects_enabled")
        if enabled is None:
            enabled = True
        if getattr(self, 'button_panel', None) and getattr(self.button_panel, 'effects_button', None):
            self.button_panel.set_button_state(self.button_panel.effects_button, enabled)
            self.button_panel.update_effects_button_icon()

    def on_toggle_notification(self):
        """Cycle through notification states: Stack → Replace → Muted → Stack"""
        current_mode = self.config.get("notification", "mode") or "stack"
        current_muted = self.config.get("notification", "muted") or False
        
        # Determine next state in cycle
        if current_muted:
            # Muted → Stack (unmute and reset to stack)
            new_mode = "stack"
            new_muted = False
        elif current_mode == "stack":
            # Stack → Replace
            new_mode = "replace"
            new_muted = False
        else:  # replace
            # Replace → Muted
            new_mode = "replace"  # Keep mode, just mute
            new_muted = True
        
        # Persist centrally via app controller so tray stays in sync
        config = self.app_controller.config if self.app_controller else self.config
        config.set("notification", "mode", value=new_mode)
        config.set("notification", "muted", value=new_muted)
        
        # Update local config data to keep in sync
        if self.app_controller:
            self.config.data = self.app_controller.config.data
        
        # Update tray menu state immediately
        if self.app_controller and hasattr(self.app_controller, 'update_notification_menu'):
            self.app_controller.update_notification_menu()
        
        # Update popup_manager
        popup_manager.set_notification_mode(new_mode)
        popup_manager.set_muted(new_muted)
        
        # Update button visual
        self.button_panel.update_notification_button_icon()
        
        # Log state change
        state_text = "Muted" if new_muted else f"{new_mode.capitalize()} mode"
        print(f"🔔 Notifications: {state_text}")

    def update_notification_button_state(self):
        """Sync notification button visual to config state"""
        if getattr(self, 'button_panel', None) and getattr(self.button_panel, 'notification_button', None):
            self.button_panel.update_notification_button_icon()

    def sync_notification_state(self):
        """Sync notification state from config - updates button and popup_manager"""
        # Update config data first
        if self.app_controller:
            self.config.data = self.app_controller.config.data
        
        # Update button icon to match new state
        self.update_notification_button_state()
        
        # Update popup_manager to match config
        mode = self.config.get("notification", "mode") or "stack"
        muted = self.config.get("notification", "muted") or False
        popup_manager.set_notification_mode(mode)
        popup_manager.set_muted(muted)

    def on_toggle_always_on_top(self):
        """Toggle always on top window flag"""
        current = self.config.get("ui", "always_on_top") or False
        new = not current
        
        # Save to config
        config = self.app_controller.config if self.app_controller else self.config
        config.set("ui", "always_on_top", value=new)
        
        # Update local config data
        if self.app_controller:
            self.config.data = self.app_controller.config.data
        
        # Apply window flag (requires hide/show to take effect properly)
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, new)
        
        # Show window if it was visible before
        if was_visible:
            self.show()
            self.activateWindow()
            self.raise_()
        
        # Update button icon to reflect new state
        if hasattr(self, 'button_panel') and hasattr(self.button_panel, 'update_pin_button_icon'):
            self.button_panel.update_pin_button_icon()
        
        print(f"📌 Always on top: {'Enabled' if new else 'Disabled'}")

    def update_always_on_top_button_state(self):
        """Sync always on top button visual to config state"""
        if getattr(self, 'button_panel', None) and getattr(self.button_panel, 'update_pin_button_icon', None):
            self.button_panel.update_pin_button_icon()

    def on_exit_requested(self):
        """Handle exit request from the button panel."""
        # Prefer the application controller's cleanup exit when available
        if self.app_controller and hasattr(self.app_controller, 'exit_application'):
            self.app_controller.exit_application()
        else:
            QApplication.quit()

    def _setup_sounds(self):
        """Setup mention and ban sound paths"""
        sounds_dir = Path(__file__).parent.parent / "sounds"
        
        # Setup mention sound
        mention_sound_path = sounds_dir / "mention.mp3"
        self.mention_sound_path = str(mention_sound_path) if mention_sound_path.exists() else None
        
        # Setup ban sound
        ban_sound_path = sounds_dir / "banned.mp3"
        self.ban_sound_path = str(ban_sound_path) if ban_sound_path.exists() else None

    def _init_ui(self):
        window_title = f"Chat - {self.account['chat_username']}" if self.account else "Chat"
        self.setWindowTitle(window_title)
        geo = QApplication.primaryScreen().availableGeometry()
      
        # Check for saved window geometry (size + position) first
        saved_width, saved_height, saved_x, saved_y = self.window_size_manager.get_saved_geometry()

        if saved_width and saved_height:
            window_width, window_height = saved_width, saved_height
            window_x = saved_x if saved_x is not None else None
            window_y = saved_y if saved_y is not None else None
        else:
            window_width, window_height, window_x, window_y = self._calculate_default_geometry()

        # Apply window geometry
        self.resize(window_width, window_height)
        if window_x is not None and window_y is not None:
            self.move(window_x, window_y)
        
        # Apply always on top flag from config if enabled
        always_on_top = self.config.get("ui", "always_on_top")
        if always_on_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        # Set minimum window dimensions
        self.setMinimumSize(400, 400)

        # Use config for margins and spacing
        window_margin = self.config.get("ui", "margins", "window") or 10
        window_spacing = self.config.get("ui", "spacing", "window_content") or 10
    
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(window_margin, window_margin, window_margin, window_margin)
        main_layout.setSpacing(window_spacing)
        self.setLayout(main_layout)

        # Create wrapper layout for content + button panel
        content_wrapper = QHBoxLayout()
        content_spacing = self.config.get("ui", "spacing", "widget_content") or 6
        content_wrapper.setSpacing(content_spacing)
        main_layout.addLayout(content_wrapper, stretch=1)

        # Content layout: left (messages/chatlog) + right (userlist)
        self.content_layout = QHBoxLayout()
        self.content_layout.setSpacing(content_spacing)
        content_wrapper.addLayout(self.content_layout, stretch=1)

        # Left side layout
        left_layout = QVBoxLayout()
        left_layout.setSpacing(self.config.get("ui", "spacing", "widget_elements") or 6)
        self.content_layout.addLayout(left_layout, stretch=3)

        # Stacked widget for Messages/Chatlog views
        self.stacked_widget = QStackedWidget()
        left_layout.addWidget(self.stacked_widget, stretch=1)

        my_username = self.account.get('chat_username') if self.account else None
        self.messages_widget = MessagesWidget(self.config, self.emoticon_manager, my_username=my_username)
        self.stacked_widget.addWidget(self.messages_widget)
        self.chatlog_widget = None
        self.chatlog_userlist_widget = None

        # Input area
        self.input_container = QWidget()
        input_main_layout = QVBoxLayout()
        input_main_layout.setContentsMargins(0, 0, 0, 0)
        input_main_layout.setSpacing(self.config.get("ui", "spacing", "widget_elements") or 6)
        self.input_container.setLayout(input_main_layout)
        left_layout.addWidget(self.input_container, alignment=Qt.AlignmentFlag.AlignBottom)
    
        button_spacing = self.config.get("ui", "buttons", "spacing") or 8
    
        self.input_top_layout = QHBoxLayout()
        self.input_top_layout.setSpacing(button_spacing)
        input_main_layout.addLayout(self.input_top_layout)
    
        self.input_bottom_layout = QHBoxLayout()
        self.input_bottom_layout.setSpacing(button_spacing)
        input_main_layout.addLayout(self.input_bottom_layout)
    
        self.input_field = QLineEdit()
        self.input_field.setFont(get_font(FontType.TEXT))
        self.input_field.setFixedHeight(48)
        self.input_field.returnPressed.connect(self.send_message)
        self.input_top_layout.addWidget(self.input_field, stretch=1)
    
        self.messages_widget.set_input_field(self.input_field)
    
        self.send_button = create_icon_button(self.icons_path, "send.svg", "Send Message", config=self.config)
        self.send_button.clicked.connect(self.send_message)
        self.input_top_layout.addWidget(self.send_button)
    
        # Exit private mode button reference (created dynamically when needed)
        self.exit_private_button = None
    
        # Emoticon button with hover icons
        self.emoticon_button = HoverIconButton(
            self.icons_path,
            "emotion-normal.svg",
            "emotion-happy.svg",
            "Toggle Emoticon Selector"
        )
        self.emoticon_button.clicked.connect(self._toggle_emoticon_selector)
        self.input_top_layout.addWidget(self.emoticon_button)
    
        # Messages userlist with private mode callback
        self.user_list_widget = UserListWidget(self.config, self.input_field, self.ban_manager)
        self.user_list_widget.profile_requested.connect(self.show_profile_view)
        self.user_list_widget.private_chat_requested.connect(self.enter_private_mode)

        messages_userlist_visible = self.config.get("ui", "messages_userlist_visible")
        userlist_visible = messages_userlist_visible if messages_userlist_visible is not None else True
        self.user_list_widget.setVisible(userlist_visible)

        # Right column: wrap in QWidget so hiding it collapses the space
        self.userlist_panel = QWidget()
        userlist_panel = QVBoxLayout()
        userlist_panel.setContentsMargins(0, 0, 0, 0)
        userlist_panel.setSpacing(4)
        userlist_panel.addWidget(self.user_list_widget, stretch=1)

        # Font scale slider under userlist — fixed height matches input_container
        # so the slider is vertically centred against the input field row.
        font_scaler = getattr(self.app_controller, 'font_scaler', None)
        if font_scaler is not None:
            self.font_scale_slider = FontScaleSlider(font_scaler)
            self.font_scale_slider.setFixedHeight(self.input_field.minimumHeight())
            userlist_panel.addWidget(self.font_scale_slider)
        else:
            self.font_scale_slider = None

        self.userlist_panel.setLayout(userlist_panel)
        self.userlist_panel.setFixedWidth(get_userlist_width())
        self.userlist_panel.setVisible(userlist_visible)
        if font_scaler is not None:
            font_scaler.font_size_committed.connect(
                lambda: self.userlist_panel.setFixedWidth(get_userlist_width())
            )
        self.content_layout.addWidget(self.userlist_panel)
     
        # Create button panel (right side, vertical scrollable)
        # Add to content_wrapper so it's always on the right
        self.button_panel = ButtonPanel(self.config, self.icons_path, self.theme_manager)

        self.button_panel.toggle_userlist_requested.connect(self.toggle_user_list)
        self.button_panel.switch_account_requested.connect(self._on_switch_account)
        self.button_panel.show_banlist_requested.connect(self.show_ban_list_view)
        self.button_panel.toggle_voice_requested.connect(self.on_toggle_voice_sound)
        self.button_panel.pronunciation_requested.connect(self.show_pronunciation_view)
        self.button_panel.toggle_effects_requested.connect(self.on_toggle_effects_sound)
        self.button_panel.toggle_notification_requested.connect(self.on_toggle_notification)

        # Color management connections (change / reset / update-from-server)
        self.button_panel.change_color_requested.connect(self.on_change_username_color)
        self.button_panel.reset_color_requested.connect(self.on_reset_username_color)
        self.button_panel.update_color_requested.connect(self.on_update_username_color)

        self.button_panel.toggle_theme_requested.connect(self.toggle_theme)
        self.button_panel.reset_window_size_requested.connect(self.reset_window_size)
        self.button_panel.show_window_presets_requested.connect(self.show_window_presets)
        self.button_panel.toggle_always_on_top_requested.connect(self.on_toggle_always_on_top)
        self.button_panel.exit_requested.connect(self.on_exit_requested)
        self.button_panel.reconnect_requested.connect(self.manual_reconnect)

        content_wrapper.addWidget(self.button_panel, stretch=0)

        # Initialize voice, mention and notification button states
        self.update_voice_button_state()
        self.update_effects_button_state()
        self.update_notification_button_state()
        
        # Initialize reset window size button state
        self.update_reset_size_button_state()

        # Initialize always on top button state
        self.update_always_on_top_button_state()

        # Enable mouse tracking for hover-reveal
        self.setMouseTracking(True)
        self._hover_reveal = False
     
        # Initialize userlist button state
        messages_userlist_visible = self.config.get("ui", "messages_userlist_visible")
        if messages_userlist_visible is not None:
            self.button_panel.set_button_state(self.button_panel.toggle_userlist_button, messages_userlist_visible)
        else:
            # Default to visible
            self.button_panel.set_button_state(self.button_panel.toggle_userlist_button, True)
     
        # Emoticon selector widget (overlay - positioned absolutely)
        # Create AFTER userlist so positioning works correctly
        self.emoticon_selector = EmoticonSelectorWidget(
            self.config,
            self.emoticon_manager,
            self.icons_path
        )
        self.emoticon_selector.attach(self, self._on_emoticon_selected)

        # Register shared instance with popup manager so notifications can borrow it
        popup_manager.emoticon_selector = self.emoticon_selector

        # Help panel (context-aware, shared across all views)
        self.help_panel = HelpPanel(self)
     
        # Install a minimal event filter to detect clicks outside selector
        # (install on window and application with a single line to keep it simple)
        self.installEventFilter(self)
        try:
            app = QApplication.instance()
            if app:
                app.installEventFilter(self)
        except Exception:
            pass

        # Set focus policy to ensure we receive key events
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Position will be set in showEvent
        QTimer.singleShot(50, self._position_emoticon_selector)
     
        self.messages_widget.timestamp_clicked.connect(self.show_chatlog_view)
        self.messages_widget.username_left_clicked.connect(self._on_username_left_click)
        self.messages_widget.username_right_clicked.connect(self._on_username_right_click)
        self.messages_widget.username_ctrl_clicked.connect(self._on_username_ctrl_click)
        self.messages_widget.username_shift_clicked.connect(self._on_username_shift_click)
    
        self._update_input_style()

    def _reclaim_emoticon_selector(self):
        """Take back the selector from a popup that borrowed it, cleaning up that popup's layout."""
        self.emoticon_selector.attach(self, self._on_emoticon_selected)

    def _toggle_emoticon_selector(self):
        """Toggle emoticon selector - reclaim from notification if borrowed, then toggle."""
        if not hasattr(self, 'emoticon_selector'):
            return
        if self.emoticon_selector.parent() is not self:
            self._reclaim_emoticon_selector()
        # _position_emoticon_selector resets fixedSize, clearing any height set by a notification
        self.emoticon_selector.toggle_visibility()
        self._position_emoticon_selector()

        # When opening, remove input focus so arrow/hjkl hotkeys work immediately.
        # Explicitly take focus on ChatWindow so the scroll area inside the selector
        # doesn't capture arrow keys before keyPressEvent sees them.
        if self.emoticon_selector.isVisible():
            self.input_field.clearFocus()
            self.setFocus()
 
    def _on_emoticon_selected(self, emoticon_name: str):
        """Handle emoticon selection"""
        # Insert emoticon code at cursor position
        cursor_pos = self.input_field.cursorPosition()
        current_text = self.input_field.text()
        emoticon_code = f":{emoticon_name}: "
     
        new_text = current_text[:cursor_pos] + emoticon_code + current_text[cursor_pos:]
        self.input_field.setText(new_text)
     
        # Move cursor after inserted emoticon
        self.input_field.setCursorPosition(cursor_pos + len(emoticon_code))
     
        # Defer by one event-loop tick so the selector has already hidden
        # (or stayed open on Shift) before we check visibility.
        QTimer.singleShot(0, self._refocus_if_selector_closed)
 
    def _refocus_if_selector_closed(self):
        if not (hasattr(self, 'emoticon_selector') and self.emoticon_selector.isVisible()):
            self.input_field.setFocus()

    def _position_emoticon_selector(self):
        """Place selector aligned to emoticon button (simple, predictable)."""
        if not hasattr(self, 'emoticon_selector'):
            return

        # Don't reposition while the selector is borrowed by a notification popup.
        # Calling setFixedSize/move on it while it lives inside a notification's
        # layout corrupts that layout, causing an empty-space artifact.
        if self.emoticon_selector.parent() is not self:
            return

        # Clamp size to available space
        available = max(200, self.height() - self.input_container.height() - 40)
        h = max(250, min(650, available))
        w = PANEL_WIDTH
        self.emoticon_selector.setFixedSize(w, h)

        # Align selector right edge to emoticon button right edge
        btn_global = self.emoticon_button.mapToGlobal(self.emoticon_button.rect().topRight())
        btn_top_right = self.mapFromGlobal(btn_global)
        x = btn_top_right.x() - w

        # Place above input area with small margin and keep on-screen
        y = max(16, self.height() - self.input_container.height() - h - 16)
        x = max(8, min(x, self.width() - w - 8))

        self.emoticon_selector.move(x, y)
        self.emoticon_selector.raise_()

    def _calculate_default_geometry(self):
        """Calculate default window size and position"""
        geo = QApplication.primaryScreen().availableGeometry()
        width = geo.width() if geo.width() < 1000 else int(geo.width() * 0.7)
        height = geo.height() - 32
        x = geo.x() + (geo.width() - width) // 2
        y = geo.y()
        return width, height, x, y

    def eventFilter(self, obj, event):
        font_scaler = getattr(self.app_controller, 'font_scaler', None)
        if font_scaler is not None:
            # Ctrl + Scroll → font size
            if event.type() == QEvent.Type.Wheel:
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    if event.angleDelta().y() > 0:
                        font_scaler.scale_up()
                    else:
                        font_scaler.scale_down()
                    return True
            # Ctrl + Plus/Minus/Equal → font size
            elif event.type() == QEvent.Type.KeyPress:
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    if event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                        font_scaler.scale_up()
                        return True
                    elif event.key() == Qt.Key.Key_Minus:
                        font_scaler.scale_down()
                        return True

        # Handle Tab key for view switching (or emoticon group cycling when selector is open)
        if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            sel = getattr(self, 'emoticon_selector', None)
            if sel and sel.isVisible():
                # Emoticon selector gets priority: Tab/Shift+Tab cycles through groups
                forward = event.key() != Qt.Key.Key_Backtab and not (
                    event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                )
                sel.cycle_tab(forward=forward)
                return True

            if event.key() == Qt.Key.Key_Tab:
                current_view = self.stacked_widget.currentWidget()
                if current_view == self.messages_widget:
                    self.show_chatlog_view()
                elif current_view == self.chatlog_widget:
                    self.show_messages_view()
                else:
                    self.show_messages_view()
                return True
        
        # Handle clicks outside emoticon selector
        if event.type() == QEvent.Type.MouseButtonPress:
            # Back/Forward mouse buttons navigate chatlog days from anywhere in the window
            cw = getattr(self, 'chatlog_widget', None)
            if cw and self.stacked_widget.currentWidget() == cw and not cw.parser_visible:
                direction = {Qt.MouseButton.BackButton: -1, Qt.MouseButton.ForwardButton: 1}.get(event.button())
                if direction is not None:
                    cw._navigate_hold(direction)
                    return True

            if hasattr(self, 'emoticon_selector') and self.emoticon_selector.isVisible():
                try:
                    gp = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
                    w = QApplication.widgetAt(gp)
                    # Walk up parents to see if click landed inside selector or on the button
                    inside = False
                    while w:
                        if w == self.emoticon_selector or w == self.emoticon_button:
                            inside = True
                            break
                        w = w.parentWidget()
                    if not inside and self.emoticon_selector.parent() is self:
                        self.emoticon_selector.setVisible(False)
                        self.config.set("ui", "emoticon_selector_visible", value=False)
                except Exception:
                    pass

            # Reclaim focus for ChatWindow after any click that doesn't land on a
            # text input — keeps arrow/hotkeys working regardless of what was clicked.
            try:
                gp = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
                clicked = QApplication.widgetAt(gp)
                if clicked and not isinstance(clicked, QLineEdit):
                    self.setFocus()
            except Exception:
                pass

        if event.type() == QEvent.Type.MouseButtonRelease:
            cw = getattr(self, 'chatlog_widget', None)
            if cw and event.button() in (Qt.MouseButton.BackButton, Qt.MouseButton.ForwardButton):
                cw._navigate_hold()
                return True

        return super().eventFilter(obj, event)

    def showEvent(self, event):
        """Handle window show events"""
        super().showEvent(event)

        # Prevent programmatic geometry changes during show from being saved
        self._showing_window = True

        # Reset unread count when window becomes visible
        if self.app_controller:
            self.app_controller.reset_unread()

        # Position emoticon selector when showing
        if hasattr(self, 'emoticon_selector'):
            QTimer.singleShot(50, self._position_emoticon_selector)
            if self.emoticon_selector.isVisible():
                QTimer.singleShot(100, self.emoticon_selector.resume_animations)

        # Restore delegate references and restart animations when showing
        try:
            if self.messages_widget and getattr(self.messages_widget, 'delegate', None):
                delegate = self.messages_widget.delegate
                delegate.set_list_view(self.messages_widget.list_view)
                # Ensure timer is running
                if not delegate.animation_timer.isActive():
                    delegate.animation_timer.start(33)
                # Restart any QMovie instances
                if delegate.message_renderer and hasattr(delegate.message_renderer, '_movie_cache'):
                    for movie in delegate.message_renderer._movie_cache.values():
                        try:
                            movie.start()
                        except Exception:
                            pass
        except Exception as e:
            print(f"ShowEvent resume animations error: {e}")

        # Update notification and always-on-top button state on show
        if hasattr(self, 'button_panel'):
            self.button_panel.update_notification_button_icon()
            # Ensure pin/unpin icon reflects current config
            self.button_panel.update_pin_button_icon()

        # Trigger an initial resize handler so UI elements (userlist, button panel)
        # reflect the current width immediately on first show
        QTimer.singleShot(50, lambda: handle_chat_resize(self, self.width()))

        # Clear the showing flag after a short delay so subsequent user-initiated resize/move
        # events will be persisted normally
        QTimer.singleShot(200, lambda: setattr(self, '_showing_window', False))

    def disable_reconnect(self):
        """Disable auto-reconnect (called when switching accounts)"""
        self.allow_reconnect = False

    def _clear_for_reconnect(self):
        """Clear messages and userlist for fresh reconnection"""
        # Clear all messages to avoid duplicates (server will send last 20 again)
        self.messages_widget.clear()
    
        # Clear userlist completely (will rebuild from fresh roster)
        if hasattr(self.user_list_widget, 'clear_all'):
            self.user_list_widget.clear_all()
    
        # Exit private mode if active
        if self.private_mode:
            self.exit_private_mode()

    def _is_connected(self):
        """Check if XMPP client is connected"""
        return self.xmpp_client and hasattr(self.xmpp_client, 'sid') and self.xmpp_client.sid

    def enter_private_mode(self, jid: str, username: str, user_id: str):
        """Enter private chat mode with a user"""
    
        self.private_mode = True
        # Prefer explicit private recipient JID (user_id#username@domain/web) for private messages
        private_recipient_jid = jid
        if user_id and username:
            domain = None
            # Prefer XMPP client configured domain if available
            if hasattr(self, 'xmpp_client') and self.xmpp_client and getattr(self.xmpp_client, 'domain', None):
                domain = self.xmpp_client.domain
            else:
                # Fallback: try to extract domain from the provided jid
                if '@' in jid:
                    try:
                        domain = jid.split('@', 1)[1].split('/')[0]
                    except Exception:
                        domain = None
            if domain:
                private_recipient_jid = f"{user_id}#{username}@{domain}/web"

        self.private_chat_jid = private_recipient_jid
        self.private_chat_username = username
        self.private_chat_user_id = user_id

        # Clear input field
        self.input_field.clear()
    
        # Create exit button if it doesn't exist
        if self.exit_private_button is None:
            self.exit_private_button = create_icon_button(
                self.icons_path, "close.svg", "Exit Private Chat", config=self.config
            )
            self.exit_private_button.clicked.connect(self.exit_private_mode)
        
            # Insert after emoticon button
            emoticon_button_index = self.input_top_layout.indexOf(self.emoticon_button)
            self.input_top_layout.insertWidget(emoticon_button_index + 1, self.exit_private_button)
        else:
            self.exit_private_button.setVisible(True)
    
        # Update UI
        self._update_input_style()

        # Focus input for immediate typing — deferred so userlist click doesn't steal it back
        QTimer.singleShot(0, self.input_field.setFocus)
    
        # Update window title
        base = f"Chat - {self.account['chat_username']}" if self.account else "Chat"
        status = self.windowTitle().split(' - ')[-1] if ' - ' in self.windowTitle() else ""
        if status in ['Online', 'Offline', 'Connecting']:
            self.setWindowTitle(f"{base} - Private with {username} - {status}")
        else:
            self.setWindowTitle(f"{base} - Private with {username}")
    
        print(f"🔒 Entered private mode with {username}")

    def exit_private_mode(self):
        """Exit private chat mode"""
        # Clear all private messages
        self._clear_private_messages()
    
        self.private_mode = False
        self.private_chat_jid = None
        self.private_chat_username = None
        self.private_chat_user_id = None
    
        # Remove and destroy exit button
        if self.exit_private_button is not None:
            # Remove from layout and destroy
            self.input_top_layout.removeWidget(self.exit_private_button)
            self.exit_private_button.deleteLater()
            self.exit_private_button = None
    
        # Update UI
        self._update_input_style()
    
        # Restore window title
        self.set_connection_status(self.windowTitle().split(' - ')[-1] if ' - ' in self.windowTitle() else 'Online')
    
        print("🔓 Exited private mode")

    def _clear_private_messages(self):
        """Clear all private messages from the messages widget"""
        self.messages_widget.clear_private_messages()

    def _update_input_style(self):
        """Update input field styling based on private mode"""
        is_dark = self.theme_manager.is_dark()
    
        if self.private_mode:
            # Get private message colors from config
            colors = get_private_message_colors(self.config, is_dark)
        
            self.input_field.setStyleSheet(f"""
                QLineEdit {{
                    background-color: {colors["input_bg"]};
                    color: {colors["text"]};
                    border: 2px solid {colors["input_border"]};
                    border-radius: 4px;
                    padding: 8px;
                }}
            """)
            self.input_field.setPlaceholderText(f"Private message to {self.private_chat_username}")
        else:
            # Normal mode - remove custom styling
            self.input_field.setStyleSheet("")
            self.input_field.setPlaceholderText("")

    def show_messages_view(self):
        """Switch back to messages and conditionally destroy chatlog widgets"""
        # Cleanup and destroy chatlog userlist
        if self.chatlog_userlist_widget:
            try:
                self.chatlog_userlist_widget.filter_requested.disconnect()
                self.chatlog_userlist_widget.clear_cache()
            except:
                pass
            self.userlist_panel.layout().removeWidget(self.chatlog_userlist_widget)
            self.chatlog_userlist_widget.deleteLater()
            self.chatlog_userlist_widget = None

        # For chatlog widget, destroy only if not parsing
        if self.chatlog_widget:
            if self.chatlog_widget.parser_widget.is_parsing:
                # Keep alive during parsing, just switch view
                pass
            else:
                try:
                    self.chatlog_widget.back_requested.disconnect()
                    self.chatlog_widget.messages_loaded.disconnect()
                    self.chatlog_widget.filter_changed.disconnect()
                    self.chatlog_widget.cleanup()
                except:
                    pass
                self.stacked_widget.removeWidget(self.chatlog_widget)
                self.chatlog_widget.deleteLater()
                self.chatlog_widget = None

        self.stacked_widget.setCurrentWidget(self.messages_widget)

        # Restore messages userlist based on width
        width = self.width()
        messages_userlist_visible = self.config.get("ui", "messages_userlist_visible")
        if messages_userlist_visible is None:
            messages_userlist_visible = True

        self.user_list_widget.setVisible(messages_userlist_visible)
        if hasattr(self, 'userlist_panel'):
            self.userlist_panel.setVisible(messages_userlist_visible)

        # Sync button state for messages userlist
        if hasattr(self, 'button_panel'):
            self.button_panel.set_button_state(
                self.button_panel.toggle_userlist_button,
                self.user_list_widget.isVisible()
            )

        QTimer.singleShot(50, lambda: scroll(self.messages_widget.scroll_area, mode="bottom"))

        # If parsing ongoing, show status widget
        if self.chatlog_widget and self.chatlog_widget.parser_widget.is_parsing:
            self.start_parse_status()

    def show_chatlog_view(self, timestamp: str = None):
        """Open chatlog for today"""
        # Hide messages userlist when in chatlog view, but keep userlist_panel visible for the chatlog userlist + font slider
        self.user_list_widget.setVisible(False)
       
        if not self.chatlog_widget:
            # Pass parent_window=self for modal dialogs and ban_manager
            self.chatlog_widget = ChatlogWidget(
                self.config,
                self.emoticon_manager,
                self.icons_path, 
                self.account, 
                parent_window=self,
                ban_manager=self.ban_manager
            )
            self.chatlog_widget.back_requested.connect(self.show_messages_view)
            self.chatlog_widget.messages_loaded.connect(self._on_chatlog_messages_loaded)
            self.chatlog_widget.filter_changed.connect(self._on_chatlog_filter_changed)
            self.stacked_widget.addWidget(self.chatlog_widget)
           
            width = self.width()
            self.chatlog_widget.set_compact_mode(width <= 1000)
            self.chatlog_widget.set_compact_layout(width <= 1000)
       
        if not self.chatlog_userlist_widget:
            self.chatlog_userlist_widget = ChatlogUserlistWidget(
                self.config,
                self.icons_path,
                self.ban_manager
            )
            self.chatlog_userlist_widget.filter_requested.connect(self._on_filter_requested)
            # Insert into userlist_panel before the font slider (at index 0)
            self.userlist_panel.layout().insertWidget(0, self.chatlog_userlist_widget, stretch=1)
       
        # Show chatlog userlist based on config and width
        width = self.width()
        chatlog_userlist_visible = self.config.get("ui", "chatlog_userlist_visible")
        if chatlog_userlist_visible is None:
            chatlog_userlist_visible = True
       
        visible = width > 1000 and chatlog_userlist_visible
        self.chatlog_userlist_widget.setVisible(visible)
        self.userlist_panel.setVisible(visible)

        if hasattr(self, 'button_panel'):
            self.button_panel.set_button_state(
                self.button_panel.toggle_userlist_button,
                chatlog_userlist_visible
            )
       
        # Sync userlist ban visibility with chatlog parse mode
        if self.chatlog_widget and self.chatlog_userlist_widget:
            self.chatlog_userlist_widget.set_show_banned(self.chatlog_widget.is_parsing)
       
        # Only load daily chatlog if not in parser mode
        if not self.chatlog_widget.parser_visible:
            self.chatlog_widget.current_date = datetime.now().date()
            self.chatlog_widget._update_date_display()
            self.chatlog_widget.load_current_date()
       
        self.stacked_widget.setCurrentWidget(self.chatlog_widget)

    def show_parser_view(self):
        """Switch to chatlog view and show parser"""
        self.show_chatlog_view()
        if self.chatlog_widget and not self.chatlog_widget.parser_visible:
            self.chatlog_widget._toggle_parser()
        if self.parse_status_widget:
            self.parse_status_widget.setVisible(False)

    def _create_parse_status_widget(self):
        """Create the parse status widget dynamically"""
        parse_status_widget = QWidget()
        parse_status_layout = QHBoxLayout()
        parse_status_widget.setLayout(parse_status_layout)

        parse_progress_bar = QProgressBar()
        parse_status_layout.addWidget(parse_progress_bar, stretch=1)

        parse_current_label = QLabel("")
        parse_status_layout.addWidget(parse_current_label)

        stop_parse_btn = create_icon_button(self.icons_path, "stop.svg", "Stop Parsing", config=self.config)
        stop_parse_btn.setObjectName("stop_parse_btn")
        stop_parse_btn.clicked.connect(lambda: self.chatlog_widget._on_parse_cancelled() if self.chatlog_widget else None)
        parse_status_layout.addWidget(stop_parse_btn)

        view_parser_btn = create_icon_button(self.icons_path, "list.svg", "View Parser", config=self.config)
        view_parser_btn.clicked.connect(self.show_parser_view)
        parse_status_layout.addWidget(view_parser_btn)

        # Add to main layout
        main_layout = self.layout()
        main_layout.addWidget(parse_status_widget)

        return parse_status_widget, parse_progress_bar, parse_current_label

    def start_parse_status(self):
        """Start showing parse status"""
        if self.parse_status_widget is None:
            self.parse_status_widget, self.parse_progress_bar, self.parse_current_label = self._create_parse_status_widget()
        self.parse_status_widget.setVisible(True)
        self.parse_progress_bar.setValue(0)
        self.parse_current_label.setText("")

    def stop_parse_status(self):
        """Stop showing parse status and destroy widget"""
        if self.parse_status_widget:
            main_layout = self.layout()
            main_layout.removeWidget(self.parse_status_widget)
            self.parse_status_widget.deleteLater()
            self.parse_status_widget = None
            self.parse_progress_bar = None
            self.parse_current_label = None

    def update_parse_progress(self, start_date: str, current_date: str, percent: int):
        if self.parse_progress_bar:
            self.parse_progress_bar.setValue(percent)
            self.parse_current_label.setText(f"{start_date} - {current_date}")

    def on_parse_finished(self):
        self.handle_parse_finished()

    def handle_parse_finished(self):
        """Keep parse status visible but update to finished state"""
        if self.parse_status_widget:
            # Hide stop button
            stop_btn = self.parse_status_widget.findChild(QPushButton, "stop_parse_btn")
            if stop_btn:
                stop_btn.setVisible(False)
            # Update label
            self.parse_current_label.setText("Parsing finished")

    def on_parse_error(self, error_msg: str):
        self.stop_parse_status()
        show_notification(
            title="Parse Error",
            message=error_msg,
            config=self.config,
            emoticon_manager=self.emoticon_manager,
            account=self.account
        )

    def _on_chatlog_messages_loaded(self, messages):
        if self.chatlog_userlist_widget and messages:
            # Sync show_banned state with chatlog parse mode
            if self.chatlog_widget:
                self.chatlog_userlist_widget.set_show_banned(self.chatlog_widget.is_parsing)
            
            self.chatlog_userlist_widget.load_from_messages(messages)

    def _on_filter_requested(self, usernames: set):
        """Handle filter request from userlist"""
        if self.chatlog_widget:
            self.chatlog_widget.set_username_filter(usernames)

    def _on_chatlog_filter_changed(self, usernames: set):
        """Handle filter change from chatlog widget - sync to userlist"""
        if self.chatlog_userlist_widget:
            self.chatlog_userlist_widget.update_filter_state(usernames)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        handle_chat_resize(self, self.width())

        self._update_geometry_on_manual_change()

    def moveEvent(self, event):
        """Track window position changes"""
        super().moveEvent(event)

        self._update_geometry_on_manual_change()

    def mouseMoveEvent(self, event):
        """Hover-reveal button panel when mouse near right edge"""
        if self.width() < 500 and hasattr(self, 'button_panel'):
            near_edge = (self.width() - event.pos().x()) <= 40
            over_panel = self.button_panel.geometry().contains(event.pos())
            
            if near_edge and not self.button_panel.isVisible():
                self.button_panel.setVisible(True)
                self._hover_reveal = True
            elif self._hover_reveal and not near_edge and not over_panel:
                def hide_if_away():
                    cursor_pos = self.mapFromGlobal(self.cursor().pos())
                    if self.width() < 500 and not self.button_panel.geometry().contains(cursor_pos):
                        self.button_panel.setVisible(False)
                
                QTimer.singleShot(300, hide_if_away)
                self._hover_reveal = False
        super().mouseMoveEvent(event)

    def reset_window_size(self):
        """Reset window to default calculated size and position"""
        # Stop any pending saves in WindowSizeManager to prevent race condition
        self.window_size_manager.save_timer.stop()
        
        was_reset = self.window_size_manager.reset_size()
        
        if not was_reset:
            return  # Already at default
        
        # Set flag to prevent resize/move events from saving during reset
        self._resetting_geometry = True
        
        # Apply default geometry
        width, height, x, y = self._calculate_default_geometry()
        self.resize(width, height)
        self.move(x, y)
        
        # Clear flag after events have fired
        QTimer.singleShot(100, lambda: setattr(self, '_resetting_geometry', False))
        
        # Update button state immediately
        self.update_reset_size_button_state()
    
    def show_window_presets(self):
        """Show window presets dialog"""
        dialog = WindowPresetsDialog(self.config, self, parent=self)
        dialog.exec()
    
    def update_reset_size_button_state(self):
        """Update reset size button state based on whether geometry is customized"""
        if hasattr(self, 'button_panel') and hasattr(self.button_panel, 'reset_size_button'):
            has_custom = self.window_size_manager.has_saved_size()
            self.button_panel.set_button_state(self.button_panel.reset_size_button, has_custom)

    def _update_geometry_on_manual_change(self):
        """Update saved geometry when the user has manually changed window size/position."""
        if getattr(self, '_showing_window', False) or getattr(self, '_resetting_geometry', False):
            return
        cur = (self.width(), self.height(), self.x(), self.y())
        if self.window_size_manager.has_saved_size() or cur != self._calculate_default_geometry():
            self.window_size_manager.update_geometry(*cur)

    def _complete_resize_recalculation(self):
        """Complete resize with aggressive recalculation"""
        current = self.stacked_widget.currentWidget()
        if current == self.messages_widget:
            self.messages_widget._force_recalculate()
            QTimer.singleShot(50, lambda: scroll(self.messages_widget.scroll_area, mode="bottom"))
        elif current == self.chatlog_widget and self.chatlog_widget:
            self.chatlog_widget._force_recalculate()
            QTimer.singleShot(50, lambda: scroll(self.chatlog_widget.list_view, mode="bottom"))

    def connect_xmpp(self):
        def _worker():
            self.is_connecting = True
            try:
                # Clear old state before reconnecting
                QTimer.singleShot(0, self._clear_for_reconnect)

                # Properly close old session so server doesn't see a duplicate
                if self.xmpp_client:
                    print("🔌 Closing old session before reconnect...")
                    try:
                        self.xmpp_client.disconnect()
                        print("✅ Old session closed")
                    except Exception as ex:
                        print(f"⚠️ Could not close old session: {ex}")
                    self.xmpp_client = None

                self.xmpp_client = XMPPClient(str(self.config_path))
                if not self.xmpp_client.connect(self.account):
                    QTimer.singleShot(0, lambda: show_notification(
                        title="Connection Failed",
                        message="Could not connect to XMPP server",
                        config=self.config,
                        emoticon_manager=self.emoticon_manager,
                        account=self.account
                    ))
                    self.signal_emitter.connection_changed.emit('offline')
                    return

                self.xmpp_client.set_message_callback(self.message_callback)
                self.xmpp_client.set_presence_callback(self.presence_callback)

                self.initial_roster_loading = True
                rooms = self.xmpp_client.account_manager.get_rooms()
                for room in rooms:
                    if room.get('auto_join'):
                        try:
                            self.xmpp_client.join_room(room['jid'])
                        except:
                            pass

                self.initial_roster_loading = False
                QTimer.singleShot(0, lambda: self.signal_emitter.bulk_update_complete.emit())
            
                self.signal_emitter.connection_changed.emit('online')

                listen_thread = threading.Thread(target=self.xmpp_client.listen, daemon=True)
                listen_thread.start()
                listen_thread.join()
            
                # Connection ended - clear sid to allow reconnection
                if self.xmpp_client:
                    self.xmpp_client.sid = None
                    self.xmpp_client.jid = None
                
                self.is_connecting = False  # Must be before emit so reconnect check passes
                self.signal_emitter.connection_changed.emit('offline')
            except Exception as e:
                # Clear sid on error too
                if self.xmpp_client:
                    self.xmpp_client.sid = None
                    self.xmpp_client.jid = None
            
                QTimer.singleShot(0, lambda: show_notification(
                    title="Error",
                    message=f"Connection error: {e}",
                    config=self.config,
                    emoticon_manager=self.emoticon_manager,
                    account=self.account
                ))
                self.is_connecting = False  # Must be before emit so reconnect check passes
                self.signal_emitter.connection_changed.emit('offline')
            finally:
                self.is_connecting = False  # Safety net in case of unexpected exit

        threading.Thread(target=_worker, daemon=True).start()

    def message_callback(self, msg):
        self.signal_emitter.message_received.emit(msg)

    def presence_callback(self, pres):
        self.signal_emitter.presence_received.emit(pres)

    def add_local_message(self, msg):
        self.messages_widget.add_message(msg)

    def _is_ban_message(self, msg):
        """Detect if a message is a ban message from Клавобот"""
        if not msg.body or not msg.login:
            return False
        return msg.login == 'Клавобот' and all(word in msg.body for word in ['Пользователь', 'заблокирован'])
    
    def _is_user_banned(self, user_id: str = None, username: str = None) -> bool:
        """Check if a user is banned by ID or username"""
        if not self.ban_manager:
            return False
        
        # Check by user_id (primary)
        if user_id and self.ban_manager.is_banned_by_id(str(user_id)):
            return True
        
        # Fallback check by username
        if not user_id and username and self.ban_manager.is_banned_by_username(username):
            return True
        
        return False

    def on_message(self, msg):
        # Check if initial load
        is_initial = getattr(msg, 'initial', False)

        # Skip own messages (server echoes groupchat messages back)
        if msg.login == self.account.get('chat_username') and not is_initial:
            return

        # CHECK IF USER IS BANNED - BLOCK IMMEDIATELY
        if msg.login:
            user_id, _ = extract_user_data_from_jid(getattr(msg, 'from_jid', None))
            if self._is_user_banned(user_id, msg.login):
                return  # Silently drop banned user's messages
            # Persist login → user_id mapping automatically
            if user_id:
                self.cache.update_user(user_id, msg.login)

        msg.is_private = (msg.msg_type == 'chat')
        
        # Check if this is a ban message and mark it
        is_ban = self._is_ban_message(msg)
        msg.is_ban = is_ban
        
        # Format message body for display/TTS and detect if it's a /me action
        display_body, is_system = format_me_action(msg.body, msg.login)

        if not is_initial and not self.isVisible() and not self.has_new_messages_marker:
            self.messages_widget.model.add_message(NewMessagesSeparator.create_marker())
            self.has_new_messages_marker = True

        # Add original message to widget (delegate will format it)
        self.messages_widget.add_message(msg)

        # Increment unread count if window is hidden and not initial load
        if not is_initial and not self.isVisible() and self.app_controller:
            self.app_controller.increment_unread()

        # Only speak if not initial load, has login, and window not active
        if not is_initial and msg.login and not self.isActiveWindow():
            tts_enabled = self.config.get("sound", "tts_enabled")
            if tts_enabled:
                # Update voice engine state
                self.voice_engine.set_enabled(True)
                my_username = self.account.get('chat_username', '')
                
                self.voice_engine.speak_message(
                    username=msg.login,
                    message=display_body,
                    my_username=my_username,
                    is_initial=is_initial,
                    is_private=msg.is_private,
                    is_ban=is_ban,
                    is_system=is_system
                )
            else:
                # Ensure voice engine is disabled
                self.voice_engine.set_enabled(False)

        # Only show notifications and play sounds if not initial load and window not active
        if not is_initial and not self.isActiveWindow():
            # Check for ban message first
            if is_ban:
                self._play_ban_sound()
            # Then check for mention
            elif self._message_mentions_me(msg):
                self._play_mention_sound()
        
            # Check if YouTube URLs need time to cache
            from core.youtube import YOUTUBE_URL_PATTERN, get_cached_info, youtube_signals
            uncached = [m.group(0) for m in YOUTUBE_URL_PATTERN.finditer(msg.body) 
                       if not (get_cached_info(m.group(0)) or (None, False))[1]]
            
            if uncached:
                # Wait for signal with timeout
                pending = set(uncached)
                timer = QTimer(self)
                timer.setSingleShot(True)
                
                def show_now():
                    try:
                        youtube_signals.metadata_cached.disconnect(on_ready)
                    except:
                        pass
                    timer.stop()
                    self._show_notification(msg, display_body, is_ban, is_system)
                
                def on_ready(url):
                    pending.discard(url)
                    if not pending:
                        show_now()
                
                youtube_signals.metadata_cached.connect(on_ready)
                timer.timeout.connect(show_now)
                timer.start(2000)
            else:
                self._show_notification(msg, display_body, is_ban, is_system)

    def _show_and_focus_window(self):
        if not self.isVisible():
            self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        self.activateWindow()
        self.raise_()
        if self.stacked_widget.currentWidget() is not self.messages_widget:
            self.show_messages_view()

    def _show_notification(self, msg, display_body, is_ban, is_system):
        """Show notification"""
        try:
            show_notification(
                title=msg.login,
                message=display_body,
                xmpp_client=self.xmpp_client,
                cache=self.cache,
                config=self.config,
                emoticon_manager=self.emoticon_manager,
                local_message_callback=self.add_local_message,
                account=self.account,
                window_show_callback=self._show_and_focus_window,
                is_private=msg.is_private,
                recipient_jid=msg.from_jid if msg.is_private else None,
                is_ban=is_ban,
                is_system=is_system
            )
        except Exception as e:
            print(f"Notification error: {e}")

    def _message_mentions_me(self, msg):
        if not self.account or not msg.body:
            return False
        my_username = self.account.get('chat_username', '').lower()
        if not my_username:
            return False
        pattern = r'\b' + re.escape(my_username) + r'\b'
        return bool(re.search(pattern, msg.body.lower()))

    def _play_mention_sound(self):
        """Play mention sound"""
        if not self.mention_sound_path:
            try:
                QApplication.instance().beep()
            except Exception as e:
                print(f"System beep error: {e}")
            return
        
        def _play():
            try:
                play_sound(self.mention_sound_path, config=self.config)
            except Exception as e:
                print(f"Mention sound playback error: {e}")
        
        threading.Thread(target=_play, daemon=True).start()

    def _play_ban_sound(self):
        """Play ban sound"""
        def _play():
            try:
                play_sound(self.ban_sound_path, config=self.config)
            except Exception as e:
                print(f"Ban sound playback error: {e}")
        
        threading.Thread(target=_play, daemon=True).start()

    def on_presence(self, pres):
        if not self.xmpp_client or self.initial_roster_loading:
            return
    
        # CHECK IF USER IS BANNED - BLOCK PRESENCE UPDATES
        if pres and pres.login:
            if self._is_user_banned(pres.user_id, pres.login):
                return  # Silently drop banned user's presence
    
        if pres and pres.presence_type == 'available':
            if pres.login and pres.user_id:
                self.cache.update_user(pres.user_id, pres.login, pres.background)
            if pres.user_id and pres.avatar:
                self.cache.ensure_avatar(pres.user_id, pres.avatar, self.user_list_widget.on_avatar_updated)
            elif pres.user_id and not pres.avatar:
                self.cache.remove_avatar(pres.user_id)
            self.user_list_widget.add_users(presence=pres)
        elif pres and pres.presence_type == 'unavailable':
            self.user_list_widget.remove_users(presence=pres)

    def on_bulk_update_complete(self):
        if not self.xmpp_client:
            return
        users = self.xmpp_client.user_list.get_online()
        self.user_list_widget.add_users(users=users, bulk=True)

    def on_font_size_changed(self):
        """Handle font size changes from font scaler - refresh all text"""
        # Debounce: restart timer on every call so rapid slider moves only
        # trigger one full rebuild 80 ms after the last movement.
        if not hasattr(self, '_font_size_timer'):
            self._font_size_timer = QTimer(self)
            self._font_size_timer.setSingleShot(True)
            self._font_size_timer.timeout.connect(self._apply_font_size_change)
        self._font_size_timer.start(80)

    def _apply_font_size_change(self):
        """Actually apply font size change after debounce"""
        new_font = get_font(FontType.TEXT)
        
        # Update message delegates AND their renderers
        for widget in [self.messages_widget, self.chatlog_widget]:
            if widget:
                widget.delegate.body_font = new_font          # For username + metrics
                widget.delegate.timestamp_font = new_font      # For timestamp
                # Also update MessageRenderer font
                if widget.delegate.message_renderer:
                    widget.delegate.message_renderer.body_font = new_font  # For message body
                widget._force_recalculate()
        
        # Update message input field
        if self.input_field:
            self.input_field.setFont(new_font)
        
        # Update userlist widgets
        if self.user_list_widget:
            # Update section labels font size
            self.user_list_widget.chat_label.setFont(new_font)
            self.user_list_widget.game_label.setFont(new_font)
            
            # Update user widgets
            for user_widget in self.user_list_widget.user_widgets.values():
                user_widget.username_label.setFont(new_font)
            self.user_list_widget.update()
        
        if self.chatlog_userlist_widget:
            for user_widget in self.chatlog_userlist_widget.user_widgets.values():
                user_widget.username_label.setFont(new_font)
                user_widget.count_label.setFont(new_font)
            self.chatlog_userlist_widget.update()
        
        # Update profile widget
        if hasattr(self, 'profile_widget') and self.profile_widget:
            if self.profile_widget.history_widget:
                [label.setFont(new_font) for label in self.profile_widget.history_widget.findChildren(QLabel)]
                self.profile_widget.history_widget._adjust_height()
            # Rebuild cards so StatCard picks up the new font-scaled min width
            if hasattr(self.profile_widget, '_cards_data'):
                self.profile_widget._rebuild_card_layout(getattr(self.profile_widget, '_last_cols', 3))
            self.profile_widget.update()
        
        # Update pronunciation widget inputs
        if hasattr(self, 'pronunciation_widget') and self.pronunciation_widget:
            for item in self.pronunciation_widget.items:
                item.original_input.setFont(new_font)
                item.pronunciation_input.setFont(new_font)
            self.pronunciation_widget.update()
        
        # Update ban list widget inputs
        if hasattr(self, 'ban_list_widget') and self.ban_list_widget:
            # Iterate over both permanent and temporary ban items
            for item in self.ban_list_widget.perm_items + self.ban_list_widget.temp_items:
                item.username_input.setFont(new_font)
                item.user_id_input.setFont(new_font)
                if hasattr(item, 'duration_button'):
                    item.duration_button.setFont(new_font)
            self.ban_list_widget.update()
        

    def send_message(self):
        text = self.input_field.text().strip()
        if not text or not self.xmpp_client:
            return

        self.input_field.clear()

        # Determine message type and recipient
        if self.private_mode and self.private_chat_jid:
            msg_type = 'chat'
            recipient_jid = self.private_chat_jid
        else:
            msg_type = 'groupchat'
            recipient_jid = None

        # Get own user data
        own_user = None
        for user in self.xmpp_client.user_list.get_all():
            if self.account.get('chat_username') in user.jid or user.login == self.account.get('chat_username'):
                own_user = user
                break

        # Chunk message if over 300 characters
        chunks = self._chunk_message(text, 300)

        # Send each chunk
        for i, chunk in enumerate(chunks):
            # Create and display own message immediately
            own_msg = Message(
                from_jid=self.xmpp_client.jid,
                body=chunk,
                msg_type=msg_type,
                login=self.account.get('chat_username'),
                avatar=None,
                background=own_user.background if own_user else None,
                timestamp=datetime.now(),
                initial=False
            )
            own_msg.is_private = (msg_type == 'chat')
        
            self.messages_widget.add_message(own_msg)
        
            delay = i * 0.8 # 800ms delay between chunks
            threading.Timer(
                delay,
                self.xmpp_client.send_message,
                args=(chunk, recipient_jid, msg_type)
            ).start()

    def _chunk_message(self, text: str, max_len: int) -> list:
        """Break message into chunks, keeping URLs intact"""
        if len(text) <= max_len:
            return [text]
    
        chunks = []
        url_pattern = re.compile(r'https?://[^\s]+')
    
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break
        
            # Find a good break point
            chunk = text[:max_len]
        
            # Check if we're breaking a URL
            urls_in_chunk = list(url_pattern.finditer(chunk))
            if urls_in_chunk:
                last_url = urls_in_chunk[-1]
                # If URL extends beyond chunk, break before it
                if last_url.end() >= max_len - 10: # Give some buffer
                    # Check if there's content before the URL
                    if last_url.start() > 0:
                        chunk = text[:last_url.start()].rstrip()
                    else:
                        # URL at start, must include it even if long
                        chunk = text[:max_len]
            else:
                # Try to break at last space
                last_space = chunk.rfind(' ')
                if last_space > max_len * 0.7: # At least 70% filled
                    chunk = text[:last_space]
        
            chunks.append(chunk)
            text = text[len(chunk):].lstrip()
    
        return chunks

    def set_connection_status(self, status: str):
        status = (status or '').lower()
        text = {'connecting': 'Connecting', 'online': 'Online'}.get(status, 'Offline')
        base = f"Chat - {self.account['chat_username']}" if self.account else "Chat"

        # Preserve private mode in title
        if self.private_mode and self.private_chat_username:
            self.setWindowTitle(f"{base} - Private with {self.private_chat_username} - {text}")
        else:
            self.setWindowTitle(f"{base} - {text}")
        
        # Reset on success
        if status == 'online':
            self.reconnect_count = 0
            if hasattr(self, 'button_panel') and hasattr(self.button_panel, 'reconnect_button'):
                self.button_panel.reconnect_button.setVisible(False)
        
        # Only trigger auto-reconnect on offline status, not on connecting (which is set during auto-reconnect attempts)
        elif status == 'offline':
            if getattr(self, 'really_close', False):
                return
            
            # Show manual reconnect button immediately
            if hasattr(self, 'button_panel') and hasattr(self.button_panel, 'reconnect_button'):
                self.button_panel.reconnect_button.setVisible(True)
            
            print(f"🔍 Offline check: allow_reconnect={self.allow_reconnect}, is_connecting={self.is_connecting}, has_account={bool(self.account)}")
            if self.allow_reconnect and not self.is_connecting and self.account:
                print("🔄 Connection lost - initiating auto-reconnect...")
                QTimer.singleShot(100, self._auto_reconnect)
            else:
                print(f"⛔ Auto-reconnect skipped")

    def _auto_reconnect(self):
        """Auto-reconnect with exponential backoff (max 10 attempts)"""
        print(f"🔍 _auto_reconnect check: allow={self.allow_reconnect}, is_connecting={self.is_connecting}, connected={self._is_connected()}, has_account={bool(self.account)}")
        if not self.allow_reconnect or self.is_connecting or self._is_connected() or not self.account:
            print(f"⛔ _auto_reconnect aborted")
            return
        
        # Max 10 attempts
        if self.reconnect_count >= 10:
            print(f"❌ Max reconnection attempts (10) reached")
            return  # Button already visible
        
        self.reconnect_count += 1
        delay = min(2 ** (self.reconnect_count - 1), 60)
        
        print(f"🔄 Auto-reconnect attempt {self.reconnect_count}/10 in {delay}s...")
        
        # Store timer so we can cancel it if user manually reconnects or app closes
        self.reconnect_timer = QTimer.singleShot(delay * 1000, lambda: (
            self.set_connection_status('connecting'),
            self.connect_xmpp()
        ) if self.allow_reconnect and not self.is_connecting else None)

    def manual_reconnect(self):
        """Manual reconnect - cancels auto-reconnect and resets counter"""
        # Cancel pending auto-reconnect timer
        if self.reconnect_timer is not None:
            try:
                self.reconnect_timer.stop()
            except:
                pass
            self.reconnect_timer = None
        
        self.reconnect_count = 0

        if hasattr(self, 'button_panel') and hasattr(self.button_panel, 'reconnect_button'):
            self.button_panel.reconnect_button.setVisible(False)
        
        print("🔄 Manual reconnection (auto-reconnect cancelled)...")
        self.set_connection_status('connecting')
        self.connect_xmpp()

    def toggle_user_list(self):
        """Toggle userlist based on current view with proper recalculation"""
    
        current_view = self.stacked_widget.currentWidget()
        is_chatlog_view = (current_view == self.chatlog_widget)
        width = self.width()
    
        if is_chatlog_view and self.chatlog_userlist_widget:
            visible = not self.chatlog_userlist_widget.isVisible()
            self.chatlog_userlist_widget.setVisible(visible)
            self.userlist_panel.setVisible(visible)
            self.config.set("ui", "chatlog_userlist_visible", value=visible)
            self.auto_hide_chatlog_userlist = False
        else:
            visible = not self.user_list_widget.isVisible()
            self.user_list_widget.setVisible(visible)
            if hasattr(self, 'userlist_panel'):
                self.userlist_panel.setVisible(visible)
            self.config.set("ui", "messages_userlist_visible", value=visible)
            self.auto_hide_messages_userlist = False
    
        # Update button visual state
        if hasattr(self, 'button_panel'):
            self.button_panel.set_button_state(self.button_panel.toggle_userlist_button, visible)

        # Force resize handler to sync everything
        QTimer.singleShot(10, lambda: handle_chat_resize(self, width))
    
        # Force recalculation after visibility change
        QTimer.singleShot(20, lambda: recalculate_layout(self))
    
    def _on_switch_account(self):
        """Handle switch account request from button panel"""
        if self.app_controller:
            self.app_controller.show_account_switcher()
    
    def show_profile_view(self, jid: str, username: str, user_id: str):
        """Show profile view for a user"""
        if not user_id:
            return

        if not hasattr(self, 'profile_widget') or not self.profile_widget:
            self.profile_widget = ProfileWidget(self.config, self.icons_path)
            self.profile_widget.back_requested.connect(self.show_messages_view)
            self.stacked_widget.addWidget(self.profile_widget)

        self.profile_widget.load_profile(int(user_id), username)
        self.stacked_widget.setCurrentWidget(self.profile_widget)
    
    def show_pronunciation_view(self):
        """Show pronunciation management view"""
        if not hasattr(self, 'pronunciation_widget') or not self.pronunciation_widget:
            self.pronunciation_widget = PronunciationWidget(
                self.config, 
                self.icons_path,
                self.pronunciation_manager
            )
            self.pronunciation_widget.back_requested.connect(self.show_messages_view)
            self.stacked_widget.addWidget(self.pronunciation_widget)
        
        self.stacked_widget.setCurrentWidget(self.pronunciation_widget)
    
    def show_ban_list_view(self):
        """Show ban list management view"""
        if not hasattr(self, 'ban_list_widget') or not self.ban_list_widget:
            self.ban_list_widget = BanListWidget(
                self.config, 
                self.icons_path,
                self.ban_manager
            )
            self.ban_list_widget.back_requested.connect(self.show_messages_view)
            self.stacked_widget.addWidget(self.ban_list_widget)
        
        self.stacked_widget.setCurrentWidget(self.ban_list_widget)
    
    def _on_username_left_click(self, username: str, is_double_click: bool):
        """Handle username left-click - insert into input field"""
        if not hasattr(self, 'input_field') or not self.input_field:
            return
        
        current = (self.input_field.text() or "").strip()
        existing = [u.strip() for u in current.split(',') if u.strip()]
        
        if is_double_click:
            # Double-click: replace all with this username (or clear if already solo)
            if len(existing) == 1 and existing[0] == username:
                self.input_field.clear()
            else:
                self.input_field.setText(username + ", ")
        else:
            # Single-click: add to list if not already there
            if username not in existing:
                if existing:
                    self.input_field.setText(", ".join(existing + [username]) + ", ")
                else:
                    self.input_field.setText(username + ", ")
        
        self.input_field.setFocus()

    def _resolve_user_then(self, username: str, callback):
        """Resolve user_id for username: userlist → cache → API fallback (threaded)."""
        # 1. Userlist (instant, has jid too)
        if hasattr(self, 'user_list_widget') and self.user_list_widget:
            for jid, widget in self.user_list_widget.user_widgets.items():
                user = getattr(widget, 'user', None)
                if user and user.login == username:
                    callback(jid, user.login, user.user_id)
                    return
        # 2. Cache (instant, no jid)
        user_id = self.cache.get_user_id(username)
        if user_id:
            callback('', username, user_id)
            return
        # 3. API fallback (threaded)
        import threading
        from core.api_data import get_exact_user_id_by_name
        def _fetch():
            uid = get_exact_user_id_by_name(username)
            if uid:
                self.cache.update_user(str(uid), username)
                self._dispatch.emit(lambda: callback('', username, str(uid)))
        threading.Thread(target=_fetch, daemon=True).start()

    def _on_username_ctrl_click(self, username: str):
        """Ctrl+LMB on message username → enter private chat"""
        self._resolve_user_then(username, lambda jid, login, uid: self.enter_private_mode(jid, login, uid))

    def _on_username_shift_click(self, username: str):
        """Shift+LMB on message username → open profile"""
        self._resolve_user_then(username, lambda jid, login, uid: self.show_profile_view(jid, login, uid))

    def _on_username_right_click(self, msg, global_pos):
        """Show context menu when username is right-clicked in messages"""
        try:

            menu = QMenu(self)
            
            # Permanent ban action
            perm_act = QAction("Ban permanently", self)
            menu.addAction(perm_act)
            
            # Temporary ban action
            temp_act = QAction("Ban temporarily", self)
            menu.addAction(temp_act)
            
            # Separator
            menu.addSeparator()
            
            # Message removal actions
            remove_msg_act = QAction("Remove this message", self)
            menu.addAction(remove_msg_act)
            
            remove_all_act = QAction("Remove all messages", self)
            menu.addAction(remove_all_act)
            
            act = menu.exec(global_pos)
            if not act:
                return
            
            if act == perm_act:
                # Permanent ban
                self._ban_user_from_msg(msg, permanent=True)
            elif act == temp_act:
                # Show duration dialog
                seconds, ok = DurationDialog.get_duration(self, default_seconds=3600)
                if ok:
                    self._ban_user_from_msg(msg, permanent=False, duration=seconds)
            elif act == remove_msg_act:
                # Remove single message
                self._remove_message(msg, single=True)
            elif act == remove_all_act:
                # Remove all messages from user
                self._remove_message(msg, single=False)
        
        except Exception as e:
            print(f"Context menu error: {e}")
    
    def _ban_user_from_msg(self, msg, permanent: bool = True, duration: int = None):
        """Perform ban: update BanManager, remove messages, remove userlist entry"""
        # Skip separators
        if getattr(msg, 'is_separator', False) or getattr(msg, 'is_new_messages_marker', False):
            return
        
        username = getattr(msg, 'login', None) or getattr(msg, 'username', None)
        jid = getattr(msg, 'from_jid', None)
        
        # Extract user_id from JID using helper
        user_id, _ = extract_user_data_from_jid(jid)
        
        if not user_id and not username:
            return
        
        # Validate username via API to get correct user_id
        if username and not user_id:
            from ui.ui_banlist import validate_username_and_get_id
            user_id = validate_username_and_get_id(username)
        
        if not user_id:
            QMessageBox.warning(self, "Error", f"Could not find user ID for {username}")
            return
        
        # Add to ban manager
        if permanent:
            self.ban_manager.add_user(user_id, username or user_id)
        else:
            self.ban_manager.add_user(user_id, username or user_id, duration=duration)
        
        # Remove messages by login
        if username:
            try:
                self.messages_widget.remove_messages_by_login(username)
            except Exception:
                pass
        
        # Remove from userlist
        if hasattr(self, 'user_list_widget') and self.user_list_widget:
            try:
                if jid:
                    self.user_list_widget.remove_users(jids=[jid])
                # Fallback: remove by username
                if username:
                    for ujid, uw in list(self.user_list_widget.user_widgets.items()):
                        ulogin = getattr(getattr(uw, 'user', None), 'login', None)
                        if ulogin == username:
                            self.user_list_widget.remove_users(jids=[ujid])
            except Exception:
                pass
        
        # Refresh ban list UI if open
        if hasattr(self, 'ban_list_widget') and self.ban_list_widget:
            try:
                self.ban_list_widget._load_bans()
            except Exception:
                pass
    
    def _remove_message(self, msg, single: bool = True):
        """Remove message(s) without banning user"""
        username = getattr(msg, 'login', None) or getattr(msg, 'username', None)
        if not username:
            return
        
        try:
            timestamp = getattr(msg, 'timestamp', None) if single else None
            self.messages_widget.remove_messages_by_login(username, timestamp)
        except Exception as e:
            print(f"Error removing message(s): {e}")

    # Physical key → action, layout-independent via nativeVirtualKey fallback.
    # Qt key values for Latin letters equal their ASCII codes, as does
    # Windows Virtual Key codes — so nativeVirtualKey() works regardless of layout.
    _KEY_ACTION = {
        Qt.Key.Key_F: 'focus',
        Qt.Key.Key_U: 'userlist',
        Qt.Key.Key_B: 'banlist',
        Qt.Key.Key_P: 'pronun',
        Qt.Key.Key_M: 'mute',
        Qt.Key.Key_T: 'top',
        Qt.Key.Key_V: 'voice',
        Qt.Key.Key_R: 'reset_size',
        Qt.Key.Key_C: 'color',
        Qt.Key.Key_N: 'notification',
        Qt.Key.Key_S: 'search',
        Qt.Key.Key_H: 'nav_backward',
        Qt.Key.Key_L: 'nav_forward',
        Qt.Key.Key_Left:  'nav_backward',
        Qt.Key.Key_Right: 'nav_forward',
        Qt.Key.Key_J: 'scroll_down',
        Qt.Key.Key_K: 'scroll_up',
        Qt.Key.Key_Down: 'scroll_down',
        Qt.Key.Key_Up: 'scroll_up',
        Qt.Key.Key_G: 'scroll_gg',   # gg = top, G (Shift+G) = bottom
        Qt.Key.Key_D: 'calendar',
        Qt.Key.Key_Space: 'page_down',
        Qt.Key.Key_X: 'exit_private',
    }

    def keyPressEvent(self, event):
        key, mods = event.key(), event.modifiers()
        ctrl  = mods == Qt.KeyboardModifier.ControlModifier
        shift = mods == Qt.KeyboardModifier.ShiftModifier
        if mods and not ctrl and not shift:
            return super().keyPressEvent(event)
        focused = self.input_field.hasFocus()

        # F1 — context-aware help
        if key == Qt.Key.Key_F1:
            sel = getattr(self, 'emoticon_selector', None)
            if sel and sel.isVisible():
                context = 'emoticon'
            elif (self.chatlog_widget and
                  self.stacked_widget.currentWidget() == self.chatlog_widget):
                context = 'parser' if self.chatlog_widget.parser_visible else 'chatlog'
            else:
                context = 'chat'
            self.help_panel.show_for_context(context)
            return

        # Loose input focus on (Esc) — also closes chatlog search if open
        if key == Qt.Key.Key_Escape and focused:
            self.input_field.clearFocus()
            return
        if key == Qt.Key.Key_Escape:
            sel = getattr(self, 'emoticon_selector', None)
            if sel and sel.isVisible():
                sel.toggle_visibility()
                self.input_field.setFocus()
                return
            cw = self.chatlog_widget
            if cw and self.stacked_widget.currentWidget() == cw and cw.search_visible:
                cw._toggle_search()
                return
        # Ctrl+; toggle emoticon selector (works even when input focused, layout-independent)
        # nativeScanCode 0x27 = physical semicolon key on all standard keyboards
        if ctrl and (key == Qt.Key.Key_Semicolon or event.nativeScanCode() == 0x27):
            self._toggle_emoticon_selector()
            return
        # Ctrl+F toggle search in chatlog (works regardless of input focus)
        if ctrl and (key == Qt.Key.Key_F or event.nativeVirtualKey() == Qt.Key.Key_F):
            cw = self.chatlog_widget
            if cw and self.stacked_widget.currentWidget() == cw:
                cw._toggle_search()
            return
        # Ctrl+C / Ctrl+S in chatlog parser — copy / save results
        if ctrl and self.chatlog_widget and self.stacked_widget.currentWidget() == self.chatlog_widget:
            cw = self.chatlog_widget
            if cw.parser_visible:
                if key == Qt.Key.Key_C or event.nativeVirtualKey() == Qt.Key.Key_C:
                    cw._on_copy_results()
                    return
                if key == Qt.Key.Key_S or event.nativeVirtualKey() == Qt.Key.Key_S:
                    cw._on_save_results()
                    return
        # Ctrl+P open chatlog and parser from anywhere
        if ctrl and (key == Qt.Key.Key_P or event.nativeVirtualKey() == Qt.Key.Key_P):
            if not self.chatlog_widget or self.stacked_widget.currentWidget() != self.chatlog_widget:
                self.show_chatlog_view()
            if self.chatlog_widget and not self.chatlog_widget.parser_visible:
                self.chatlog_widget._toggle_parser()
            return
        # Ctrl+U switch account
        if ctrl and (key == Qt.Key.Key_U or event.nativeVirtualKey() == Qt.Key.Key_U):
            self._on_switch_account()
            return
        # Ctrl+T toggle theme
        if ctrl and (key == Qt.Key.Key_T or event.nativeVirtualKey() == Qt.Key.Key_T):
            self.toggle_theme()
            return
        # Resolve physical key regardless of layout
        vk = self._KEY_ACTION.get(key) or self._KEY_ACTION.get(event.nativeVirtualKey())

        # ── Emoticon selector keyboard navigation ──────────────────────────────
        sel = getattr(self, 'emoticon_selector', None)
        if sel and sel.isVisible() and not focused:
            nk = event.nativeVirtualKey()
            sc = event.nativeScanCode()
            if not ctrl and not shift:
                if key == Qt.Key.Key_Left  or nk == Qt.Key.Key_H: sel.navigate(-1, 0); return
                if key == Qt.Key.Key_Right or nk == Qt.Key.Key_L: sel.navigate(1, 0); return
                if key == Qt.Key.Key_Down  or nk == Qt.Key.Key_J: sel.navigate(0, 1); return
                if key == Qt.Key.Key_Up    or nk == Qt.Key.Key_K: sel.navigate(0, -1); return
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) or nk == Qt.Key.Key_A or sc == 0x27:
                    sel.insert_selected(); return
            if shift and (key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) or nk == Qt.Key.Key_A or sc == 0x27):
                sel.insert_selected(shift=True); return
        # ───────────────────────────────────────────────────────────────────────

        if not vk or focused:
            return super().keyPressEvent(event)
        def _toggle_view(attr, show_fn):
            w = getattr(self, attr, None)
            self.show_messages_view() if w and self.stacked_widget.currentWidget() == w else show_fn()
        def _active_scrollbar():
            current = self.stacked_widget.currentWidget()
            if current == self.messages_widget:
                return self.messages_widget.list_view.verticalScrollBar()
            if self.chatlog_widget and current == self.chatlog_widget:
                return self.chatlog_widget.list_view.verticalScrollBar()
            return None
        # Focus input on (F) key if not focused, for quick access
        if vk == 'focus':
            self.input_field.setFocus()
        # User list toggle (U) — Ctrl+U is handled before the focus guard above
        elif vk == 'userlist':
            self.toggle_user_list()
        # Ban list toggle (B)
        elif vk == 'banlist':
            _toggle_view('ban_list_widget', self.show_ban_list_view)
        # Pronunciation toggle (P) / in chatlog: toggle parser (P)
        elif vk == 'pronun':
            cw = self.chatlog_widget
            if cw and self.stacked_widget.currentWidget() == cw:
                cw._toggle_parser()
            else:
                _toggle_view('pronunciation_widget', self.show_pronunciation_view)
        # Mute effects sound (M) or toggle mention filter in chatlog (M)
        elif vk == 'mute':
            if self.chatlog_widget and self.stacked_widget.currentWidget() == self.chatlog_widget:
                self.chatlog_widget._toggle_mention_filter()
            else:
                self.on_toggle_effects_sound()
        # Toggle search in chatlog (S) / start parsing when parser visible
        elif vk == 'search':
            cw = self.chatlog_widget
            if cw and self.stacked_widget.currentWidget() == cw:
                if cw.parser_visible and not cw.parser_widget.is_parsing:
                    cw.parser_widget._on_parse_clicked()
                elif not cw.parser_visible and not cw.search_field.hasFocus():
                    cw._toggle_search()
        # Navigate chatlog days — H backward, L forward, supports hold
        elif vk in ('nav_backward', 'nav_forward'):
            cw = self.chatlog_widget
            if cw and self.stacked_widget.currentWidget() == cw and not event.isAutoRepeat():
                cw._navigate_hold(-1 if vk == 'nav_backward' else 1)
        # Vim-style scroll — J down, K up, works in chat and chatlog
        elif vk in ('scroll_down', 'scroll_up'):
            sb = _active_scrollbar()
            if sb:
                step = sb.singleStep() * 5
                sb.setValue(sb.value() + (step if vk == 'scroll_down' else -step))
        # Vim-style G = bottom, gg = top
        elif vk == 'scroll_gg':
            sb = _active_scrollbar()
            if sb:
                if shift:
                    sb.setValue(sb.maximum())
                else:
                    if not hasattr(self, '_gg_timer'):
                        self._gg_timer = QTimer(self)
                        self._gg_timer.setSingleShot(True)
                    if self._gg_timer.isActive():
                        self._gg_timer.stop()
                        sb.setValue(sb.minimum())
                    else:
                        self._gg_timer.start(300)
        # Space — scroll down one page
        elif vk == 'page_down':
            sb = _active_scrollbar()
            if sb:
                sb.setValue(sb.value() + (-sb.pageStep() if shift else sb.pageStep()))
        # Always on top toggle (T)
        elif vk == 'top':
            self.on_toggle_always_on_top()
        # Voice sound toggle (V)
        elif vk == 'voice':
            self.on_toggle_voice_sound()
        # Reset window size (R)
        elif vk == 'reset_size':
            self.reset_window_size()
        # Change username color (C) / Ctrl+C reset / Shift+C update from server
        # In chatlog when parser visible: C cancels if parsing, Ctrl+C copies
        elif vk == 'color':
            cw = self.chatlog_widget
            if cw and self.stacked_widget.currentWidget() == cw and cw.parser_visible:
                if ctrl:
                    cw._on_copy_results()
                elif cw.parser_widget.is_parsing:
                    cw.parser_widget._on_parse_clicked()  # Cancel
            elif ctrl:
                self.on_reset_username_color()
            elif shift:
                self.on_update_username_color()
            else:
                self.on_change_username_color()
        # Toggle notifications cycle (N)
        elif vk == 'notification':
            self.on_toggle_notification()
        # Open calendar date picker in chatlog (D)
        elif vk == 'calendar':
            cw = self.chatlog_widget
            if cw and self.stacked_widget.currentWidget() == cw:
                cw._show_calendar()
        # Exit private mode / clear private messages / clear new messages marker (X)
        elif vk == 'exit_private':
            if self.private_mode:
                self.exit_private_mode()
            else:
                self._clear_private_messages()
            if self.has_new_messages_marker:
                NewMessagesSeparator.remove_from_model(self.messages_widget.model)
                self.has_new_messages_marker = False

    def keyReleaseEvent(self, event):
        if event.isAutoRepeat():
            return
        key = event.key()
        vk = self._KEY_ACTION.get(key) or self._KEY_ACTION.get(event.nativeVirtualKey())
        if vk in ('nav_backward', 'nav_forward'):
            cw = self.chatlog_widget
            if cw and self.stacked_widget.currentWidget() == cw:
                cw._navigate_hold()  # Stop hold
                return
        super().keyReleaseEvent(event)

    def toggle_theme(self):
        try:
            self.theme_manager.toggle_theme()
            is_dark = self.theme_manager.is_dark()
            set_theme(is_dark)
         
            # Update theme button icon via button panel
            self.button_panel.update_theme_button_icon()
         
            # Update input styling for theme
            self._update_input_style()
         
            update_all_icons()
            
            # Update shared emoticon manager theme
            self.emoticon_manager.set_theme(is_dark)
            
            # Update widgets
            self.messages_widget.update_theme()
            self.user_list_widget.update_theme()
            
            if self.chatlog_widget:
                self.chatlog_widget.update_theme()
         
            if self.chatlog_userlist_widget:
                self.chatlog_userlist_widget.update_theme()
         
            if hasattr(self, 'profile_widget') and self.profile_widget:
                self.profile_widget.update_theme()
         
            # Update emoticon selector theme
            if hasattr(self, 'emoticon_selector'):
                self.emoticon_selector.update_theme()
         
            # Update button panel theme
            if hasattr(self, 'button_panel'):
                self.button_panel.update_theme()
         
            self.messages_widget.rebuild_messages()
         
            if self.chatlog_widget and self.stacked_widget.currentWidget() == self.chatlog_widget:
                self.chatlog_widget._force_recalculate()
         
            QApplication.processEvents()
        except Exception as e:
            print(f"Theme toggle error: {e}")

    def closeEvent(self, event):
        # Cleanup emoticon selector
        if hasattr(self, 'emoticon_selector'):
            self.emoticon_selector.cleanup()

        # Remove new messages marker when closing
        if self.has_new_messages_marker:
            NewMessagesSeparator.remove_from_model(self.messages_widget.model)
            self.has_new_messages_marker = False
    
        # If hiding to tray, do not perform full cleanup so animations and
        # delegate state remain intact. Full cleanup happens only when the
        # app is actually closing.
        if self.tray_mode and not self.really_close:
            event.ignore()
            self.hide()
            return

        # Reset unread when actually closing
        if self.app_controller:
            self.app_controller.reset_unread()

        # Cleanup window size manager
        if hasattr(self, 'window_size_manager'):
            self.window_size_manager.cleanup()

        # Proceed with full cleanup when actually closing
        if self.messages_widget:
            if hasattr(self.messages_widget, 'auto_scroller'):
                try:
                    self.messages_widget.auto_scroller.cleanup()
                except:
                    pass
            self.messages_widget.cleanup()
        if self.chatlog_widget:
            self.chatlog_widget.cleanup()

        if self.xmpp_client:
            try:
                self.xmpp_client.disconnect()
            except:
                pass
        self.set_connection_status('offline')

        # Shutdown voice engine
        if hasattr(self, 'voice_engine'):
            self.voice_engine.shutdown()
        event.accept()