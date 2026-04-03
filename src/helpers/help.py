"""Context-aware help panel - displays keyboard shortcuts for the currently active component"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea, QApplication
from PyQt6.QtCore import Qt
from pathlib import Path
import json


# ─────────────────────────────────────────────────────────────────────────────
# Hotkey data tables
# Each entry: (key_label, description)
# ─────────────────────────────────────────────────────────────────────────────

CHAT_GENERAL_KB = [
    ("F",           "Focus input field"),
    ("Tab",         "Switch Messages / Chatlog"),
    ("U",           "Toggle user list"),
    ("B",           "Toggle ban list"),
    ("V",           "Toggle voice / TTS"),
    ("M",           "Toggle effects sound"),
    ("N",           "Cycle notification mode"),
    ("T",           "Toggle always on top"),
    ("R",           "Reset window size"),
    ("C",           "Change username color"),
    ("Shift+C",     "Update color from server"),
    ("X",           "Exit private mode / clear markers"),
    ("Esc",         "Clear input focus"),
]

CHAT_CTRL_KB = [
    ("Ctrl+;",      "Toggle emoticon selector"),
    ("Ctrl+T",      "Toggle theme"),
    ("Ctrl+U",      "Switch account"),
    ("Ctrl+P",      "Open chatlog parser"),
    ("Ctrl+C",      "Reset username color"),
    ("Ctrl + / -",  "Font size up / down"),
    ("Ctrl+Scroll", "Font size up / down"),
]

CHAT_SCROLL_KB = [
    ("J / ↓",       "Scroll down"),
    ("K / ↑",       "Scroll up"),
    ("G G",         "Scroll to top"),
    ("Shift+G",     "Scroll to bottom"),
    ("Space",       "Page down"),
    ("Shift+Space", "Page up"),
]

USERLIST_MOUSE = [
    ("Left click",       "View user profile"),
    ("Ctrl+Click",       "Start private chat"),
]

MSG_USERNAME_MOUSE = [
    ("Left click",       "Add username to input"),
    ("Double click",     "Replace input / clear if solo"),
    ("Ctrl+Click",       "Start private chat"),
    ("Shift+Click",      "View user profile"),
    ("Right click",      "Ban / remove message menu"),
]

CHATLOG_KB = [
    ("H / ←",           "Previous day (hold to fast-seek)"),
    ("L / →",           "Next day (hold to fast-seek)"),
    ("D",               "Open calendar date picker"),
    ("S",               "Toggle search bar"),
    ("P",               "Toggle chatlog parser"),
    ("M",               "Toggle mention-only filter"),
]

CHATLOG_USERLIST_MOUSE = [
    ("Left click",      "Filter messages by user (click again to clear)"),
    ("Ctrl+Click",      "Add / remove user from filter"),
]

CHATLOG_MOUSE = [
    ("Back button",     "Navigate to previous day"),
    ("Forward button",  "Navigate to next day"),
]

EMOTICON_KB = [
    ("H / ←",           "Move cursor left"),
    ("L / →",           "Move cursor right"),
    ("J / ↓",           "Move cursor down"),
    ("K / ↑",           "Move cursor up"),
    ("Tab",             "Next emoticon group"),
    ("Shift+Tab",       "Previous emoticon group"),
    ("Enter / ;",       "Insert emoticon & close"),
    ("Shift+Enter",     "Insert emoticon & stay open"),
    ("Esc",             "Close selector"),
]

EMOTICON_MOUSE = [
    ("Scroll on group tabs",    "Navigate groups prev / next"),
]

CHATLOG_PARSER_ACTIVE_KB = [
    ("P",               "Toggle chatlog parser"),
    ("S",               "Start parsing"),
    ("C",               "Cancel parsing"),
    ("Ctrl+C",          "Copy results"),
    ("Ctrl+S",          "Save results to file"),
    ("Ctrl+F",          "Toggle search"),
]

ACCOUNTS_CONNECT_KB = [
    ("Enter / E",   "Connect to chat"),
    ("Tab",         "Cycle account selection"),
    ("C",           "Change username color"),
    ("Ctrl+C",      "Reset username color"),
    ("Shift+C",     "Update color from server"),
    ("D",           "Remove selected account"),
    ("A",           "Go to Create account page"),
    ("1",           "Toggle Auto-login"),
    ("2",           "Toggle Start minimized"),
    ("3",           "Toggle Start with system"),
]

ACCOUNTS_CONNECT_MOUSE = [
    ("Left click",   "Change username color"),
    ("Ctrl+Click",   "Reset username color"),
    ("Shift+Click",  "Update color from server"),
]

ACCOUNTS_CREATE_KB = [
    ("Ctrl+S",      "Save / create account"),
    ("Enter",       "Save / create account"),
    ("Tab",         "Cycle focus username / password"),
    ("Esc",         "Back to Connect page"),
]

IMAGE_KB = [
    ("Esc / Space / Q", "Close image viewer"),
]

IMAGE_MOUSE = [
    ("Left drag",           "Pan / move image"),
    ("Ctrl + Left drag",    "Scale image (up / down)"),
    ("Wheel",               "Zoom in / out"),
    ("Right click",         "Close image viewer"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Context definitions
# Each context lists one or more sections to render.
# A section: (title, kb_rows, mouse_rows)
#   kb_rows    – list of (key, desc)  shown with blue badges
#   mouse_rows – list of (action, desc) shown with amber badges, or None
# ─────────────────────────────────────────────────────────────────────────────

CONTEXTS = {
    "chat": {
        "title": "Chat — Keyboard Shortcuts",
        "sections": [
            ("General",                 CHAT_GENERAL_KB,    None),
            ("Ctrl Shortcuts",          CHAT_CTRL_KB,       None),
            ("Scrolling",               CHAT_SCROLL_KB,     None),
            ("User List Clicks",        None,               USERLIST_MOUSE),
            ("Message Username Clicks", None,               MSG_USERNAME_MOUSE),
        ],
    },
    "chatlog": {
        "title": "Chatlog — Keyboard Shortcuts",
        "sections": [
            ("Navigation",      CHATLOG_KB,             CHATLOG_MOUSE),
            ("Scrolling",       CHAT_SCROLL_KB,         None),
            ("User List",       None,                   CHATLOG_USERLIST_MOUSE),
        ],
    },
    "parser": {
        "title": "Chatlog Parser — Keyboard Shortcuts",
        "sections": [
            ("Parser Controls", CHATLOG_PARSER_ACTIVE_KB, None),
        ],
    },
    "accounts_connect": {
        "title": "Accounts — Connect Page",
        "sections": [
            ("Keyboard Shortcuts",  ACCOUNTS_CONNECT_KB,    None),
            ("Color Button Clicks", None,                   ACCOUNTS_CONNECT_MOUSE),
        ],
    },
    "accounts_create": {
        "title": "Accounts — Create Page",
        "sections": [
            ("Keyboard Shortcuts",  ACCOUNTS_CREATE_KB, None),
        ],
    },
    "emoticon": {
        "title": "Emoticon Selector — Controls",
        "sections": [
            ("Keyboard", EMOTICON_KB,    None),
            ("Mouse",    None,           EMOTICON_MOUSE),
        ],
    },
    "image": {
        "title": "Image Viewer — Controls",
        "sections": [
            ("Keyboard Shortcuts",  IMAGE_KB,   None),
            ("Mouse Controls",      None,       IMAGE_MOUSE),
        ],
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# HelpPanel widget
# ─────────────────────────────────────────────────────────────────────────────

class HelpPanel(QWidget):
    """
    Context-aware help panel. Call show_for_context(context_key) to display
    shortcuts relevant to the currently active component.

    Valid context keys: 'chat', 'chatlog', 'emoticon', 'image'
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self._config_path = Path(__file__).parent.parent / "settings" / "config.json"
        self._current_context = None

        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowTitle("Help")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

    # ── Public API ─────────────────────────────────────────────────────────

    def show_for_context(self, context_key: str):
        """
        Rebuild the panel for the given context and show it centered on screen.
        Calling with the same context while visible toggles the panel off.
        """
        if self.isVisible() and self._current_context == context_key:
            self.hide()
            return

        self._current_context = context_key
        try:
            theme = json.loads(self._config_path.read_text(encoding="utf-8")).get("ui", {}).get("theme", "dark")
        except Exception:
            theme = "dark"
        geo = QApplication.primaryScreen().availableGeometry()
        self._build(context_key, theme)
        self.show()
        self.raise_()
        # Measure the real content height + chrome (title + footer + margins + spacing)
        content_h = self._scroll_content.sizeHint().height()
        chrome_h = self.height() - (self.findChild(QScrollArea).height())
        desired_h = content_h + chrome_h + 48  # buffer for layout spacing + window frame
        h = min(desired_h, geo.height())
        self.resize(self.width(), h)
        self._center_on_screen()
        QApplication.instance().installEventFilter(self)

    def hideEvent(self, event):
        super().hideEvent(event)
        try:
            QApplication.instance().removeEventFilter(self)
        except Exception:
            pass

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.MouseButtonPress:
            try:
                gp = event.globalPosition().toPoint()
            except AttributeError:
                gp = event.globalPos()
            if not self.geometry().contains(gp):
                self.hide()
        return super().eventFilter(obj, event)

    # ── Internal ───────────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)

    def _center_on_screen(self):
        geo = QApplication.primaryScreen().availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + (geo.height() - self.height()) // 2
        self.move(x, y)

    def _build(self, context_key: str, theme: str = "dark"):
        """Rebuild UI for the given context with current theme."""
        # ── Clear existing layout ─────────────────────────────────────────
        old_layout = self.layout()
        if old_layout:
            while old_layout.count():
                child = old_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
                elif child.layout():
                    _clear_layout(child.layout())
            QWidget().setLayout(old_layout)

        # ── Theme colors ──────────────────────────────────────────────────
        is_dark = (theme == "dark")

        if is_dark:
            bg = "#1e1e1e"
            title_color = "#6bb6d6"
            section_color = "#6ba885"
            text_color = "#c8c8c8"
            sep_color = "#404040"
            kb_bg = "#5a8fb4"
            kb_text = "#1a1a1a"
            mouse_bg = "#c9954d"
            mouse_text = "#1a1a1a"
        else:
            bg = "#f0f0f0"
            title_color = "#3a8fb0"
            section_color = "#4a9570"
            text_color = "#4a4a4a"
            sep_color = "#d0d0d0"
            kb_bg = "#7ba8c7"
            kb_text = "#1a1a1a"
            mouse_bg = "#d9a866"
            mouse_text = "#1a1a1a"

        self.setStyleSheet(f"QWidget {{ background-color: {bg}; }}")

        # ── Context definition ────────────────────────────────────────────
        ctx = CONTEXTS.get(context_key, CONTEXTS["chat"])

        # ── Outer layout: title (pinned) + scroll area + footer (pinned) ──
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(6)

        # Title — always visible, outside scroll
        title_lbl = QLabel(ctx["title"])
        title_lbl.setStyleSheet(
            f"color: {title_color}; font-size: 14px; font-weight: bold; padding-bottom: 6px;"
        )
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(title_lbl)

        # ── Scroll area wrapping all sections ─────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{ background-color: {bg}; border: none; }}")

        content = QWidget()
        content.setStyleSheet(f"background-color: {bg};")
        sections_layout = QVBoxLayout(content)
        sections_layout.setContentsMargins(0, 0, 8, 0)
        sections_layout.setSpacing(6)

        for section_title, kb_rows, mouse_rows in ctx["sections"]:
            if not kb_rows and not mouse_rows:
                continue

            sec_lbl = QLabel(section_title)
            sec_lbl.setStyleSheet(
                f"color: {section_color}; font-size: 12px; font-weight: bold; "
                f"padding: 6px 0 2px 0;"
            )
            sections_layout.addWidget(sec_lbl)

            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet(f"color: {sep_color}; margin: 2px 0;")
            sections_layout.addWidget(sep)

            if kb_rows:
                for key_text, desc_text in kb_rows:
                    sections_layout.addLayout(
                        _badge_row(key_text, desc_text, kb_bg, kb_text, 130, text_color)
                    )

            if mouse_rows:
                for action_text, desc_text in mouse_rows:
                    sections_layout.addLayout(
                        _badge_row(action_text, desc_text, mouse_bg, mouse_text, 130, text_color)
                    )

        sections_layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        self._scroll_content = content  # store ref to measure after show

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_F1, Qt.Key.Key_Escape):
            self.hide()
        else:
            super().keyPressEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _badge_row(key_text, desc_text, badge_bg, badge_text, min_width, desc_color):
    row = QHBoxLayout()
    row.setSpacing(10)

    key = QLabel(key_text)
    key.setStyleSheet(
        f"background-color: {badge_bg}; color: {badge_text}; "
        f"border-radius: 4px; padding: 3px 8px; font-weight: bold;"
    )
    key.setMinimumWidth(min_width)
    key.setAlignment(Qt.AlignmentFlag.AlignCenter)

    desc = QLabel(desc_text)
    desc.setStyleSheet(f"color: {desc_color}; font-size: 12px; padding: 3px 8px;")

    row.addWidget(key)
    row.addWidget(desc, 1)
    return row


def _clear_layout(layout):
    while layout.count():
        child = layout.takeAt(0)
        if child.widget():
            child.widget().deleteLater()
        elif child.layout():
            _clear_layout(child.layout())