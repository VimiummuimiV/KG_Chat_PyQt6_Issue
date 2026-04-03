"""Message delegate for rendering with virtual scrolling"""
from typing import Dict, Optional
from pathlib import Path

from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QApplication
from PyQt6.QtCore import Qt, QSize, QRect, QModelIndex, pyqtSignal, QTimer, QEvent
from PyQt6.QtGui import QPainter, QFontMetrics, QColor, QCursor, QMouseEvent

from helpers.color_contrast import optimize_color_contrast
from components.messages_separator import NewMessagesSeparator, ChatlogDateSeparator
from helpers.emoticons import EmoticonManager
from helpers.fonts import get_font, FontType
from helpers.me_action import format_me_action
from helpers.cache import get_cache
from ui.message_renderer import MessageRenderer


class MessageDelegate(QStyledItemDelegate):
    """Delegate for rendering messages with virtual scrolling"""
 
    row_needs_refresh = pyqtSignal(int)
    message_clicked = pyqtSignal(int)
 
    def __init__(
        self,
        config,
        emoticon_manager: EmoticonManager,
        parent=None
        ):
        super().__init__(parent)
        self.config = config
        self.emoticon_manager = emoticon_manager
     
        theme = config.get("ui", "theme") or "dark"
        self.is_dark_theme = (theme == "dark")
        self.bg_hex = "#1E1E1E" if self.is_dark_theme else "#FFFFFF"

        self.body_font = get_font(FontType.TEXT)
        self.timestamp_font = get_font(FontType.TEXT)
     
        self.compact_mode = False
        self.padding = config.get("ui", "message", "padding") or 2
        self.spacing = config.get("ui", "message", "element_spacing") or 4
     
        self.click_rects: Dict[int, Dict] = {}
        self.input_field = None
        self.my_username = None # Store username for mention highlighting
     
        # Animation support for GIF emoticons
        self.list_view = None
        self.animated_rows = set()
        self.animation_frames = {}
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self._update_animations)
        self.animation_timer.start(33) # 30 FPS

        # Highlight support for clicked messages
        self.highlighted_row = None
        self.highlight_opacity = 0.0
        self.highlight_timer = QTimer()
        self.highlight_timer.timeout.connect(self.highlight_row)
        self.highlight_timer.setInterval(50) # 20 FPS

        # Connect signal for refreshing rows when async metadata (like link previews) is loaded
        self.row_needs_refresh.connect(self._do_refresh_row)
        
        # Create message renderer
        self.message_renderer = None
 
    def set_my_username(self, username: str):
        """Set the current user's username for mention highlighting"""
        self.my_username = username
        if self.message_renderer:
            self.message_renderer.set_my_username(username)
 
    def set_list_view(self, list_view):
        self.list_view = list_view
        
        # Initialize message renderer with parent for viewers
        if list_view and not self.message_renderer:
            self.message_renderer = MessageRenderer(
                self.config,
                self.emoticon_manager,
                self.is_dark_theme,
                parent_widget=list_view.window()
            )
            # Set username for mention highlighting
            if self.my_username:
                self.message_renderer.set_my_username(self.my_username)
            # Connect refresh signals
            self.message_renderer.refresh_row.connect(self._refresh_row)
            self.message_renderer.refresh_view.connect(lambda: self.list_view.viewport().update())
 
    def set_input_field(self, input_field):
        self.input_field = input_field
 
    def cleanup(self):
        self.list_view = None
        if self.message_renderer:
            self.message_renderer.cleanup()
 
    def update_theme(self):
        theme = self.config.get("ui", "theme") or "dark"
        self.is_dark_theme = (theme == "dark")
        self.bg_hex = "#1E1E1E" if theme == "dark" else "#FFFFFF"
        if self.message_renderer:
            self.message_renderer.update_theme(self.is_dark_theme)
 
    def set_compact_mode(self, compact: bool):
        if self.compact_mode != compact:
            self.compact_mode = compact

    @staticmethod
    def _get_display_body(msg) -> tuple:
        """Return (display_body, is_system) with /me formatting and type emoji prefix applied."""
        body, is_me = format_me_action(msg.body, msg.username)
        is_system = is_me or bool(getattr(msg, 'is_system', False))
        body = MessageRenderer._emoji_prefix(body, msg.is_private, msg.is_ban, is_system)
        return body, is_system
 
    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        msg = index.data(Qt.ItemDataRole.DisplayRole)
        if not msg:
            return QSize(200, 50)
     
        # Chatlog date separator
        if getattr(msg, 'is_separator', False):
            return QSize(option.rect.width(), ChatlogDateSeparator.get_height())

        # New messages marker
        if getattr(msg, 'is_new_messages_marker', False):
            return QSize(option.rect.width(), NewMessagesSeparator.get_height())

        width = option.rect.width() if option.rect.width() > 0 else 800
        row = index.row()
        height = self._calculate_compact_height(msg, width, row) if self.compact_mode else self._calculate_normal_height(msg, width, row)
        return QSize(width, height)
 
    def _calculate_compact_height(self, msg, width: int, row: Optional[int] = None) -> int:
        if not self.message_renderer:
            return 50
        
        fm = QFontMetrics(self.body_font)
        header_height = max(fm.height(), QFontMetrics(self.timestamp_font).height())
        display_body, _ = self._get_display_body(msg)
        content_height = self.message_renderer.calculate_content_height(display_body, width - 2 * self.padding, row)
        return min(self.padding + header_height + 2 + content_height + self.padding, 500)
 
    def _calculate_normal_height(self, msg, width: int, row: Optional[int] = None) -> int:
        if not self.message_renderer:
            return 50
        
        fm = QFontMetrics(self.body_font)
        fm_ts = QFontMetrics(self.timestamp_font)
     
        time_str = msg.get_time_str()
        timestamp_width = fm_ts.horizontalAdvance(time_str) + self.spacing
        username_width = fm.horizontalAdvance(msg.username) + self.spacing
     
        content_width = max(width - timestamp_width - username_width - 2 * self.padding, 200)
     
        display_body, _ = self._get_display_body(msg)
        content_height = self.message_renderer.calculate_content_height(display_body, content_width, row)
        label_height = max(fm.height(), fm_ts.height())
        return min(max(label_height, content_height) + 2 * self.padding, 500)
 
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        msg = index.data(Qt.ItemDataRole.DisplayRole)
        if not msg:
            return
  
        # Handle chatlog date separator
        if getattr(msg, 'is_separator', False):
            ChatlogDateSeparator.render(
                painter,
                option.rect,
                msg.date_str,
                self.timestamp_font,
                self.is_dark_theme
            )
            return

        # Handle new messages marker
        if getattr(msg, 'is_new_messages_marker', False):
            NewMessagesSeparator.render(
                painter,
                option.rect,
                self.timestamp_font,
                self.is_dark_theme
            )
            return

        row = index.row()

        if self.message_renderer and self.message_renderer.has_animated_emoticons(msg.body):
            self.animated_rows.add(row)
        else:
            self.animated_rows.discard(row)
  
        self.click_rects[row] = {'timestamp': QRect(), 'username': QRect(), 'links': []}
  
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw highlight overlay if this row is highlighted
        if row == self.highlighted_row and self.highlight_opacity > 0:
            highlight_color = QColor("#4DA6FF" if self.is_dark_theme else "#0066CC")
            highlight_color.setAlphaF(self.highlight_opacity * 0.15)
            painter.fillRect(option.rect, highlight_color)
  
        self._paint_message(painter, option.rect, msg, row, self.compact_mode)
  
        painter.restore()
 
    def _paint_message(self, painter: QPainter, rect: QRect, msg, row: int, compact: bool):
        """Paint message in either compact or normal mode"""
        if not self.message_renderer:
            return
        
        x, y = rect.x() + self.padding, rect.y() + self.padding
        width = rect.width() - 2 * self.padding
        time_str = msg.get_time_str()
      
        body_fm = QFontMetrics(self.body_font)
        ts_fm = QFontMetrics(self.timestamp_font)
      
        # Resolve display body and message type once - used for both timestamp color and content
        display_body, is_system = self._get_display_body(msg)
      
        # Paint timestamp - color matches text color for special message types
        painter.setFont(self.timestamp_font)
        ts_color = self.message_renderer.get_timestamp_color(msg.is_ban, msg.is_private, is_system)
        painter.setPen(QColor(ts_color))
        ts_width = ts_fm.horizontalAdvance(time_str)
        ts_rect = QRect(x, y, ts_width, ts_fm.height())
        painter.drawText(
            ts_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            time_str
        )
        self.click_rects[row]['timestamp'] = ts_rect
      
        # Determine content position based on mode and message type
        if not is_system:
            # Normal message - paint username
            username_x = x + ts_width + self.spacing
            color = self._get_username_color(msg.username, msg.background_color)
          
            painter.setFont(self.body_font)
            painter.setPen(QColor(color))
          
            un_width = body_fm.horizontalAdvance(msg.username)
            un_rect = QRect(username_x, y, un_width, body_fm.height())
            painter.drawText(
                un_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                msg.username
            )
            self.click_rects[row]['username'] = un_rect
          
            # Content position after username
            content_x = username_x + un_width + self.spacing
        else:
            # System message - skip username, create empty click rect
            self.click_rects[row]['username'] = QRect()
            # Content position right after timestamp
            content_x = x + ts_width + self.spacing
      
        # Calculate content position and dimensions based on mode
        if compact:
            # Compact mode: content below header
            content_y = y + max(body_fm.height(), ts_fm.height()) + 2
            content_width = width
            link_rects = self.message_renderer.paint_content(
                painter, x, content_y, content_width, display_body, row,
                getattr(msg, 'is_private', False),
                getattr(msg, 'is_ban', False),
                is_system
            )
        else:
            # Normal mode: content on same line after username/timestamp
            content_width = rect.width() - (content_x - rect.x()) - self.padding
            link_rects = self.message_renderer.paint_content(
                painter, content_x, y, content_width, display_body, row,
                getattr(msg, 'is_private', False),
                getattr(msg, 'is_ban', False),
                is_system
            )
        
        self.click_rects[row]['links'] = link_rects
 
    def _refresh_row(self, row: int):
        """Request refresh from background thread - emit signal to main thread"""
        self.row_needs_refresh.emit(row)
  
    def _do_refresh_row(self, row: int):
        """Refresh row when async metadata arrives"""
        if not self.list_view or not self.list_view.model() or not (0 <= row < self.list_view.model().rowCount()):
            return
        try:
            model = self.list_view.model()
            idx = model.index(row, 0)
            try:
                model.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DisplayRole])
            except Exception:
                pass
            for attr in ('updateGeometries', 'doItemsLayout'):
                try:
                    getattr(self.list_view, attr, lambda: None)()
                except Exception:
                    pass
            self.list_view.viewport().update()
        except RuntimeError:
            pass

    def editorEvent(self, event: QEvent, model, option: QStyleOptionViewItem,
                    index: QModelIndex) -> bool:
        msg = index.data(Qt.ItemDataRole.DisplayRole)
      
        # Handle clicking on new messages marker to remove it
        if getattr(msg, 'is_new_messages_marker', False):
            if event.type() == QEvent.Type.MouseButtonRelease:
                NewMessagesSeparator.remove_from_model(model)
                return True
            return False
      
        # Ignore clicks on date separators
        if getattr(msg, 'is_separator', False):
            return False

        if event.type() == QEvent.Type.MouseButtonRelease:
            mouse_event: QMouseEvent = event
            button = mouse_event.button()
            pos = mouse_event.pos()
            row = index.row()
         
            if row not in self.click_rects:
                # Click outside specific elements - treat as message click
                if button == Qt.MouseButton.LeftButton:
                    self.message_clicked.emit(row)
                return super().editorEvent(event, model, option, index)
         
            rects = self.click_rects[row]
         
            # Timestamp/username clicks are handled by the VIEW (ui_messages.py)
            if rects['timestamp'].contains(pos):
                return True

            if rects['username'].contains(pos) and button == Qt.MouseButton.LeftButton:
                return True

            if rects['username'].contains(pos) and button == Qt.MouseButton.RightButton:
                return True
         
            # Link clicks
            if self.message_renderer:
                is_ctrl = QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier
                link_data = MessageRenderer.get_link_at_pos(rects['links'], pos)
                if link_data:
                    url, is_media = link_data
                    if button == Qt.MouseButton.LeftButton:
                        global_pos = self.list_view.viewport().mapToGlobal(pos)
                        self.message_renderer.handle_link_lmb(url, is_media, global_pos, is_ctrl)
                    elif button == Qt.MouseButton.RightButton:
                        self.message_renderer.handle_link_rmb(url)
                    return True
            
            # Click on message content area (not on specific clickable elements)
            if button == Qt.MouseButton.LeftButton:
                self.message_clicked.emit(row)
                return True
     
        elif event.type() == QEvent.Type.MouseButtonDblClick:
            pos = event.pos()
            row = index.row()
         
            if row not in self.click_rects:
                return super().editorEvent(event, model, option, index)
         
            rects = self.click_rects[row]
         
            # Double-click on username handled by view (ui_messages.py)
            if rects['username'].contains(pos):
                return True
     
        elif event.type() == QEvent.Type.MouseMove:
            pos = event.pos()
            row = index.row()
          
            if row in self.click_rects:
                rects = self.click_rects[row]
                is_over_clickable = (
                    rects['timestamp'].contains(pos) or
                    rects['username'].contains(pos) or
                    (self.message_renderer and MessageRenderer.is_over_link(rects['links'], pos))
                )
              
                if self.list_view:
                    cursor = (Qt.CursorShape.PointingHandCursor
                             if is_over_clickable
                             else Qt.CursorShape.ArrowCursor)
                    self.list_view.setCursor(QCursor(cursor))
     
        return super().editorEvent(event, model, option, index)
 
    def _get_username_color(self, username: str, background: Optional[str]) -> str:
        cache = get_cache()
        # Background is stored by ui_userlist/ui_messages which have user_id context.
        # Delegate only reads the precomputed color.
        return cache.get_username_color(username, self.is_dark_theme)
 
    def _update_animations(self):
        if not self.animated_rows or not self.message_renderer:
            return

        # Poll frames for all movies
        has_changes = False
        for key, movie in list(self.message_renderer._movie_cache.items()):
            try:
                current_frame = movie.currentFrameNumber()
            except Exception:
                continue
            if self.animation_frames.get(key, -1) != current_frame:
                self.animation_frames[key] = current_frame
                has_changes = True

        if not has_changes:
            return

        try:
            viewport_visible = bool(self.list_view and self.list_view.isVisible())
        except RuntimeError:
            viewport_visible = False

        if not viewport_visible or not self.list_view or not self.list_view.model():
            return

        visible_rows = self._get_visible_rows()
        if not visible_rows:
            return

        rows_to_update = self.animated_rows & visible_rows
        if not rows_to_update:
            return

        model = self.list_view.model()
        for row in rows_to_update:
            if row < model.rowCount():
                index = model.index(row, 0)
                rect = self.list_view.visualRect(index)
                if rect.isValid():
                    self.list_view.viewport().update(rect)
 
    def _get_visible_rows(self) -> set:
        if not self.list_view:
            return set()
     
        try:
            viewport_rect = self.list_view.viewport().rect()
            first_index = self.list_view.indexAt(viewport_rect.topLeft())
            last_index = self.list_view.indexAt(viewport_rect.bottomLeft())
        except RuntimeError:
            return set()
     
        if not first_index.isValid():
            return set()
     
        start_row = max(0, first_index.row() - 3)
        end_row_base = last_index.row() if last_index.isValid() else start_row + 20
        end_row = end_row_base + 3
     
        return set(range(start_row, end_row + 1))

    def highlight_row(self, row: int = None):
        """Highlight a row with fade-out effect"""
        
        if row is not None:
            # Starting NEW highlight
            self.highlighted_row = row
            self.highlight_opacity = 1.0
            if not self.highlight_timer.isActive():
                self.highlight_timer.start()
        else:
            # Timer callback - continue FADING
            self.highlight_opacity -= 0.05
            if self.highlight_opacity <= 0:
                self.highlight_opacity = 0.0
                self.highlighted_row = None
                self.highlight_timer.stop()
        
        # Repaint the highlighted row
        if self.highlighted_row is not None and self.list_view and self.list_view.model():
            index = self.list_view.model().index(self.highlighted_row, 0)
            self.list_view.viewport().update(self.list_view.visualRect(index))