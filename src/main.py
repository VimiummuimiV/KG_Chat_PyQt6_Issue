import sys
import ctypes
import time
import keyboard
from pathlib import Path
from PyQt6.QtWidgets import(
    QWidget, QApplication, QSystemTrayIcon,
    QMenu, QMessageBox
)
from PyQt6.QtGui import QFont, QIcon, QAction, QPixmap, QPainter, QColor
from PyQt6.QtCore import Qt, QLockFile, QDir, pyqtSignal, QObject, pyqtSlot, QMetaObject, QTimer
from PyQt6.QtSvg import QSvgRenderer

# Add src directory to path
src_path = Path(__file__).parent
sys.path.insert(0, str(src_path if src_path.name == 'src' else src_path / 'src'))

from ui.ui_accounts import AccountWindow
from ui.ui_chat import ChatWindow
from helpers.fonts import load_fonts, set_application_font, set_font_scaler
from helpers.config import Config
from helpers.username_color_manager import(
    change_username_color,
    reset_username_color,
    update_from_server
)
from helpers.pronunciation_manager import PronunciationManager
from helpers.ban_manager import BanManager
from helpers.font_scaler import FontScaler
from core.accounts import AccountManager
from components.tray_badge import TrayIconWithBadge
from components.notification import popup_manager


class Application(QObject):
    toggle_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.app = QApplication(sys.argv)
        self.toggle_signal.connect(self.toggle_chat_visibility)
        self.hotkey = None
        self.last_hotkey_time = 0  # Add debounce tracking

        # Set Windows taskbar icon (must be done before any windows are created)
        if sys.platform == 'win32':
            try:
                # Set App User Model ID for Windows taskbar grouping
                myappid = 'kgchat.messenger.app.1.0'
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            except Exception as e:
                print(f"⚠️ Failed to set Windows App ID: {e}")

        # Single instance lock
        self.lock_file = QLockFile(QDir.tempPath() + "/xmpp_chat.lock")
        if not self.lock_file.tryLock(100):
            QMessageBox.warning(
                None,
                "Already Running",
                "KG Chat is already running.\nCheck your system tray."
            )
            sys.exit(0)

        load_fonts()
        set_application_font(self.app)

        # Initialize icons path FIRST
        self.icons_path = Path(__file__).parent / "icons"
        
        # Set global application icon EARLY - before any windows are created
        # Uses chat.ico for taskbar/dock on all platforms
        app_icon = self._get_app_icon()
        self.app.setWindowIcon(app_icon)
        
        # Initialize tray badge manager
        self.tray_badge = TrayIconWithBadge(self.icons_path)
        self.unread_count = 0

        # Initialize settings path
        self.settings_path = Path(__file__).parent / "settings"
        
        # Initialize account manager and config
        self.config_path = self.settings_path / "config.json"
        self.account_manager = AccountManager(str(self.config_path))
        self.config = Config(str(self.config_path))
        
        # Initialize font scaler
        self.font_scaler = FontScaler(self.config)
        set_font_scaler(self.font_scaler)
        
        # Initialize pronunciation manager
        self.pronunciation_manager = PronunciationManager(self.settings_path)
        
        # Initialize ban manager
        self.ban_manager = BanManager(self.settings_path)

        self.account_window = None
        self.chat_window = None
        self.tray_icon = None

        self.color_menu = None
        self.reset_color_action = None

        self.sound_menu = None
        self.voice_sound_action = None
        self.effects_sound_action = None
        self.pronunciation_action = None

        self.notification_menu = None
        self.notification_mode_action = None
        self.notification_muted_action = None

        self.ban_list_action = None
        
        self.setup_system_tray()

    def setup_system_tray(self):
        """Setup system tray icon and menu"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("⚠️ System tray not available")
            return

        self.tray_icon = QSystemTrayIcon(self._get_icon(self.unread_count), self.app)
        self.tray_icon.setToolTip("KG Chat")
        self.tray_icon.activated.connect(lambda r: self.toggle_chat_visibility(ignore_active=True) if r == QSystemTrayIcon.ActivationReason.Trigger else None)

        # Create the main menu
        menu = QMenu()
       
        # Add menu items
        menu.addAction(QAction("Switch Account", self.app, triggered=self.show_account_switcher))
        menu.addSeparator()
       
        # Create Color Management submenu
        self._setup_color_menu(menu)
       
        menu.addSeparator()
        
        # Create Sound Management submenu
        self._setup_sound_menu(menu)
        
        menu.addSeparator()
        
        # Create Notification Management submenu
        self._setup_notification_menu(menu)
        
        menu.addSeparator()
        
        # Add Ban List Management
        self.ban_list_action = QAction("Ban List", self.app)
        self.ban_list_action.triggered.connect(self.handle_ban_list)
        menu.addAction(self.ban_list_action)
        
        menu.addSeparator()
        menu.addAction(QAction("Exit", self.app, triggered=self.exit_application))

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.show()

    def _setup_color_menu(self, parent_menu: QMenu):
        """Setup color management submenu"""
        self.color_menu = parent_menu.addMenu("Color")
       
        # Create actions for the submenu
        change_color_action = QAction("Change Username Color", self.app)
        change_color_action.triggered.connect(self.handle_change_username_color)
        self.color_menu.addAction(change_color_action)
       
        # Reset action - will be shown/hidden dynamically
        self.reset_color_action = QAction("Reset to Original", self.app)
        self.reset_color_action.triggered.connect(self.handle_reset_username_color)
        self.color_menu.addAction(self.reset_color_action)
       
        update_color_action = QAction("Update from Server", self.app)
        update_color_action.triggered.connect(self.handle_update_from_server)
        self.color_menu.addAction(update_color_action)
       
        # Connect to aboutToShow to update menu visibility
        self.color_menu.aboutToShow.connect(self.update_color_menu)

    def _setup_sound_menu(self, parent_menu: QMenu):
        """Setup sound management submenu"""
        self.sound_menu = parent_menu.addMenu("Sound")
        
        # Add separator at the top
        self.sound_menu.addSeparator()
        
        # Voice sound (TTS) toggle action
        self.voice_sound_action = QAction("Voice Sound", self.app, checkable=True)
        self.voice_sound_action.triggered.connect(
            lambda: self._on_sound_toggled("tts_enabled", self.voice_sound_action)
        )
        self.sound_menu.addAction(self.voice_sound_action)
        
        # Effects sound toggle action
        self.effects_sound_action = QAction("Effects Sound", self.app, checkable=True)
        self.effects_sound_action.triggered.connect(
            lambda: self._on_sound_toggled("effects_enabled", self.effects_sound_action)
        )
        self.sound_menu.addAction(self.effects_sound_action)
        
        # Add separator before pronunciation
        self.sound_menu.addSeparator()
        
        # Username Pronunciation action
        self.pronunciation_action = QAction("Username Pronunciation", self.app)
        self.pronunciation_action.triggered.connect(self.handle_pronunciation_manager)
        self.sound_menu.addAction(self.pronunciation_action)
        
        # Connect to aboutToShow to update menu state
        self.sound_menu.aboutToShow.connect(self.update_sound_menu)
        
        # Load initial states
        self.update_sound_menu()

    def _setup_notification_menu(self, parent_menu: QMenu):
        """Setup notification management submenu"""
        self.notification_menu = parent_menu.addMenu("Notification")
        
        # Add separator at the top
        self.notification_menu.addSeparator()
        
        # Mode toggle action (changes text based on current mode)
        self.notification_mode_action = QAction("", self.app)
        self.notification_mode_action.triggered.connect(self._on_notification_mode_toggled)
        self.notification_menu.addAction(self.notification_mode_action)
        
        # Add separator
        self.notification_menu.addSeparator()
        
        # Muted action
        self.notification_muted_action = QAction("Muted", self.app, checkable=True)
        self.notification_muted_action.triggered.connect(self._on_notification_muted_toggled)
        self.notification_menu.addAction(self.notification_muted_action)
        
        # Connect to aboutToShow to update menu state
        self.notification_menu.aboutToShow.connect(self.update_notification_menu)
        
        # Load initial state
        self.update_notification_menu()

    def update_color_menu(self):
        """Update the color menu to show/hide Reset option based on custom_background"""
        if not self.chat_window or not self.chat_window.account:
            # No account connected - hide reset option
            self.reset_color_action.setVisible(False)
            return
       
        # Show reset only if custom_background exists
        has_custom_bg = bool(self.chat_window.account.get('custom_background'))
        self.reset_color_action.setVisible(has_custom_bg)

    def update_sound_menu(self):
        """Update sound menu to reflect current config state"""
        # Update voice sound (TTS) state
        voice_enabled = self.config.get("sound", "tts_enabled")
        if voice_enabled is None:
            voice_enabled = False
        self.voice_sound_action.setChecked(voice_enabled)
       
        # Update effects sound state
        effects_enabled = self.config.get("sound", "effects_enabled")
        if effects_enabled is None:
            effects_enabled = True
        self.effects_sound_action.setChecked(effects_enabled)

    def update_notification_menu(self):
        """Update notification menu to reflect current state"""
        # Get current mode from config (default is "stack")
        current_mode = self.config.get("notification", "mode")
        if current_mode is None:
            current_mode = "stack"
        
        # Update mode text
        if current_mode == "stack":
            self.notification_mode_action.setText("Mode: Stack")
        else:
            self.notification_mode_action.setText("Mode: Replace")
        
        # Get muted state from config (default is False)
        muted = self.config.get("notification", "muted")
        if muted is None:
            muted = False
        self.notification_muted_action.setChecked(muted)

    def _on_sound_toggled(self, config_key: str, action: QAction):
        """Handle sound toggle from tray menu"""
        enabled = action.isChecked()
        
        # Save to config
        self.config.set("sound", config_key, value=enabled)
        
        # Update chat window's config instance directly if it exists
        if self.chat_window:
            self.chat_window.config.data = self.config.data
            # Ensure chat window reflects the new sound-related state immediately
            if config_key == 'tts_enabled' and hasattr(self.chat_window, 'update_voice_button_state'):
                self.chat_window.update_voice_button_state()
            if config_key == 'effects_enabled' and hasattr(self.chat_window, 'update_effects_button_state'):
                self.chat_window.update_effects_button_state()

    def _on_notification_mode_toggled(self):
        """Handle notification mode toggle from tray menu"""
        # Get current mode and toggle it
        current_mode = self.config.get("notification", "mode")
        if current_mode is None:
            current_mode = "stack"
        
        # Toggle between modes
        new_mode = "replace" if current_mode == "stack" else "stack"
        
        # Save to config
        self.config.set("notification", "mode", value=new_mode)
        
        # Update chat window's config instance directly if it exists
        if self.chat_window:
            self.chat_window.config.data = self.config.data
            # Sync chat window notification state
            if hasattr(self.chat_window, 'sync_notification_state'):
                self.chat_window.sync_notification_state()
        
        # Update the popup_manager's mode immediately
        popup_manager.set_notification_mode(new_mode)
        
        # Update menu text
        self.update_notification_menu()

    def _on_notification_muted_toggled(self):
        """Handle notification muted toggle from tray menu"""
        muted = self.notification_muted_action.isChecked()
        
        # Save to config
        self.config.set("notification", "muted", value=muted)
        
        # Update chat window's config instance directly if it exists
        if self.chat_window:
            self.chat_window.config.data = self.config.data
            # Sync chat window notification state
            if hasattr(self.chat_window, 'sync_notification_state'):
                self.chat_window.sync_notification_state()
        
        # Update the popup_manager's muted state immediately
        popup_manager.set_muted(muted)

    def _get_app_icon(self):
        """Get the main application icon - chat.ico for taskbar/dock"""
        ico_path = self.icons_path / "chat.ico"
        return QIcon(str(ico_path))

    def _get_icon(self, count: int = 0):
        """Get chat icon with optional message count badge"""
        return self.tray_badge.create_icon(count)

    def increment_unread(self):
        """Increment unread message count and update tray icon"""
        self.unread_count += 1
        if self.tray_icon:
            self.tray_icon.setIcon(self._get_icon(self.unread_count))
    
    def reset_unread(self):
        """Reset unread message count and update tray icon"""
        self.unread_count = 0
        if self.tray_icon:
            self.tray_icon.setIcon(self._get_icon(0))

    def _force_window_to_foreground(self, window):
        """Force window to foreground with platform-specific handling"""
        window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        window.activateWindow()
        window.raise_()
        
        # Windows: Force window to foreground
        if sys.platform == 'win32':
            try:
                hwnd = int(window.winId())
                user32 = ctypes.windll.user32
                foreground_hwnd = user32.GetForegroundWindow()
                
                if foreground_hwnd != hwnd:
                    foreground_thread = user32.GetWindowThreadProcessId(foreground_hwnd, None)
                    this_thread = ctypes.windll.kernel32.GetCurrentThreadId()
                    
                    if foreground_thread != this_thread:
                        user32.AttachThreadInput(foreground_thread, this_thread, True)
                    
                    user32.BringWindowToTop(hwnd)
                    user32.SetForegroundWindow(hwnd)
                    
                    if foreground_thread != this_thread:
                        user32.AttachThreadInput(foreground_thread, this_thread, False)
            except Exception as e:
                print(f"⚠️ Could not force window to foreground: {e}")

    def show_window(self):
        """Show the active window"""
        window = self.chat_window if self.chat_window and not self.chat_window.isVisible() else self.account_window
        if window and not window.isVisible():
            window.show()
            self._force_window_to_foreground(window)
            
            if window == self.chat_window:
                self.reset_unread()

    def show_account_switcher(self):
        """Show account switcher window"""
        # Close chat window if open
        if self.chat_window:
            try:
                # Disable auto-reconnect before closing
                self.chat_window.disable_reconnect()

                if self.chat_window.xmpp_client:
                    self.chat_window.xmpp_client.disconnect()
            except Exception:
                pass
            self.chat_window.close()
            self.chat_window.deleteLater()
            self.chat_window = None

        # Show account window
        self.show_account_window()

    def exit_application(self):
        """Exit the application completely"""
        # Unhook keyboard listener
        try:
            keyboard.unhook_all()
        except Exception:
            pass

        # Mark chat window as really closing immediately to avoid auto-reconnect races
        if self.chat_window:
            try:
                self.chat_window.really_close = True
            except Exception:
                pass

        # Ensure auto-reconnect is disabled so closing doesn't trigger reconnection
        if self.chat_window:
            try:
                self.chat_window.disable_reconnect()
            except Exception:
                pass

        if self.chat_window and self.chat_window.xmpp_client:
            try:
                self.chat_window.xmpp_client.disconnect()
            except Exception:
                pass
        if self.chat_window:
            self.chat_window.close()
        if self.tray_icon:
            self.tray_icon.hide()

        # Release lock file
        if hasattr(self, 'lock_file'):
            self.lock_file.unlock()

        self.app.quit()

    def run(self):
        """Run the application - check auto-login or show account window"""
        # Setup global hotkey after Qt is fully initialized
        self.setup_global_hotkey()
        
        # Check if auto-login is enabled
        auto_login = self.config.get("startup", "auto_login")
        
        if auto_login:
            # Get active account and connect directly
            active_account = self.account_manager.get_active_account()
            
            if active_account:
                print(f"🔑 Auto-login enabled, connecting to {active_account['chat_username']}")
                self.show_chat_window(active_account)
            else:
                # No active account, show account window
                print("⚠️ Auto-login enabled but no active account found")
                self.show_account_window()
        else:
            # Normal flow - show account window
            self.show_account_window()
        
        return self.app.exec()

    def show_account_window(self):
        """Show account selection window"""
        self.account_window = AccountWindow()
        self.account_window.account_connected.connect(self.on_account_connected)
        self.account_window.show()

    def on_account_connected(self, account):
        """Close account window and open chat"""
        if self.account_window:
            self.account_window.close()
            self.account_window = None
        self.show_chat_window(account)

    def show_chat_window(self, account):
        """Open chat window with tray support"""
        self.chat_window = ChatWindow(
            account=account, 
            app_controller=self,
            pronunciation_manager=self.pronunciation_manager,
            ban_manager=self.ban_manager
        )
        self.chat_window.set_tray_mode(True)
        
        # Connect font size changes to refresh UI
        self.font_scaler.font_size_changed.connect(self.chat_window.on_font_size_changed)
        
        # Initialize popup_manager mode and muted state from config
        notification_mode = self.config.get("notification", "mode")
        if notification_mode:
            popup_manager.set_notification_mode(notification_mode)
        
        notification_muted = self.config.get("notification", "muted")
        if notification_muted:
            popup_manager.set_muted(notification_muted)
        
        # Initialize notification button icon to match config state
        if hasattr(self.chat_window, 'button_panel') and hasattr(self.chat_window.button_panel, 'update_notification_button_icon'):
            self.chat_window.button_panel.update_notification_button_icon()
        
        # Check if start minimized is enabled
        start_minimized = self.config.get("startup", "start_minimized")
        
        if start_minimized:
            # Don't show the window, just let it stay hidden (tray mode)
            print("🪟 Starting minimized to tray")
            # The window exists but is not shown - user can access it via tray icon
        else:
            # Normal behavior - show the window
            self.chat_window.show()

    def _refresh_own_username_color(self, operation_func):
        """Execute operation and refresh own username color in UI if successful."""
        if not self.chat_window or not self.chat_window.account:
            QMessageBox.warning(None, "No Account", "Please connect to an account first.")
            return
       
        success = operation_func(
            self.chat_window,
            self.account_manager,
            self.chat_window.account,
            self.chat_window.cache
        )
       
        if not success:
            return
       
        # Refresh account data to update custom_background/avatar state
        updated_account = self.account_manager.get_account_by_chat_username(
            self.chat_window.account['chat_username']
        )
       
        if not updated_account:
            return
       
        previous_avatar = self.chat_window.account.get('avatar')
        self.chat_window.account.update(updated_account)
       
        effective_bg = updated_account.get('custom_background') or updated_account.get('background')
        own_login = updated_account['chat_username']
        own_id = updated_account['user_id']
       
        # Update own color in cache
        self.chat_window.cache.update_user(own_id, own_login, effective_bg)
       
        # Clear avatar cache if changed
        if updated_account.get('avatar') != previous_avatar:
            self.chat_window.cache.remove_avatar(own_id)
       
        # Update userlist own user
        own_user = next(
            (u for u in self.chat_window.xmpp_client.user_list.users.values()
            if u.login == own_login),
            None
        )
        if own_user:
            own_user.background = effective_bg
            self.chat_window.user_list_widget.add_users(users=[own_user])
       
        # Update messages
        own_messages_updated = False
        for msg_data in self.chat_window.messages_widget.model._messages:
            if msg_data.username == own_login:
                msg_data.background_color = effective_bg
                own_messages_updated = True
       
        if own_messages_updated:
            self.chat_window.messages_widget._force_recalculate()

    def handle_change_username_color(self):
        """Handle Change Username Color from tray menu."""
        self._refresh_own_username_color(change_username_color)

    def handle_reset_username_color(self):
        """Handle Reset to Original from tray menu."""
        self._refresh_own_username_color(reset_username_color)

    def handle_update_from_server(self):
        """Handle Update from Server from tray menu."""
        self._refresh_own_username_color(update_from_server)
    
    def check_chat_ready(self, feature_description):
        """Check if chat window and account are ready; show error if not."""
        if not self.chat_window or not self.chat_window.account:
            QMessageBox.information(
                None,
                "Chat Not Open",
                f"Please connect to an account first to manage {feature_description}."
            )
            return False
        return True

    def focus_chat_window(self):
        """Show and focus the chat window if hidden."""
        if not self.chat_window.isVisible():
            self.chat_window.show()
            self.chat_window.activateWindow()
            self.chat_window.raise_()

    def handle_pronunciation_manager(self):
        """Handle Username Pronunciation from tray menu"""
        if not self.check_chat_ready("username pronunciations"):
            return
        self.focus_chat_window()
        self.chat_window.show_pronunciation_view()

    def handle_ban_list(self):
        """Handle Ban List Management from tray menu"""
        if not self.check_chat_ready("the ban list"):
            return
        self.focus_chat_window()
        self.chat_window.show_ban_list_view()

    def setup_global_hotkey(self):
        """Register cross-platform global hotkey (Super/Win/Cmd + C)"""
        try:
            keyboard.on_press(self._on_key_press)
            print(f"✅ Global hotkey registered: Win/Cmd + C")
            return True
        except Exception as e:
            print(f"⚠️ Failed to register global hotkey: {e}")
            return False

    def _on_key_press(self, event):
        """Handle Win/Cmd + C hotkey"""
        if event.name.lower() != 'c':
            return
            
        try:
            # Platform-specific modifier check with Windows API for reliability
            if sys.platform == 'win32':
                if not keyboard.is_pressed('windows') or any((ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000) for vk in [0x12, 0x11, 0x10]):
                    return
            else:
                mod = 'command' if sys.platform == 'darwin' else 'super'
                if not keyboard.is_pressed(mod) or any(keyboard.is_pressed(k) for k in ['alt', 'ctrl', 'shift']):
                    return
            
            # Debounce (150ms)
            current_time = time.time()
            if current_time - self.last_hotkey_time < 0.15:
                return
            self.last_hotkey_time = current_time
            
            # Thread-safe toggle
            QMetaObject.invokeMethod(self, "toggle_chat_visibility", Qt.ConnectionType.QueuedConnection)
        except Exception as e:
            print(f"⚠️ Hotkey error: {e}")

    @pyqtSlot()
    def toggle_chat_visibility(self, ignore_active=False):
        """Toggle visibility of the active window"""
        window = self.chat_window or self.account_window
        if not window:
            return
        
        # Cache the active state BEFORE any window operations to avoid race conditions
        is_visible = window.isVisible()
        is_active = window.isActiveWindow()
        
        # Determine if we should hide the window
        should_hide = is_visible and (ignore_active or is_active)
        
        if should_hide:
            window.hide()
        else:
            # Show and bring to foreground
            window.show()
            self._force_window_to_foreground(window)
            if window == self.chat_window:
                self.reset_unread()
                # Clear input field to remove any stray characters from hotkey
                if hasattr(window, 'input_field') and window.input_field:
                    QTimer.singleShot(50, window.input_field.clear)


def main():
    """Application entry point"""
    application = Application()
    sys.exit(application.run())


if __name__ == "__main__":
    main()