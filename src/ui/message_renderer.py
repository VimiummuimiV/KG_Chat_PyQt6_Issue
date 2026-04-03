"""Reusable message body renderer for delegates and notifications"""
from typing import Dict, Optional, List, Tuple
from pathlib import Path
import re

from PyQt6.QtCore import Qt, QRect, QSize, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QPainter, QFontMetrics, QColor, QPixmap, QMovie
from PyQt6.QtWidgets import QApplication

from helpers.color_utils import get_private_message_colors, get_ban_message_colors, get_system_message_colors, get_mention_color
from helpers.fonts import get_font, FontType
from helpers.mention_parser import parse_mentions
from core.youtube import is_youtube_url, get_cached_info, fetch_async
from helpers.image_viewer import ImageHoverView
from helpers.video_player import VideoPlayer


class MessageRenderer(QObject):
    """Renders message body content with links, emoticons, and mentions"""
    
    # Signal emitted when content needs refresh (e.g., YouTube metadata loaded)
    refresh_row = pyqtSignal(int) # row index to refresh
    refresh_view = pyqtSignal() # general refresh (link rmb highlight)
    
    def __init__(self, config, emoticon_manager, is_dark_theme: bool, parent_widget=None):
        super().__init__()
        self.config = config
        self.emoticon_manager = emoticon_manager
        self.is_dark_theme = is_dark_theme
        self.bg_hex = "#1E1E1E" if is_dark_theme else "#FFFFFF"
        
        # Track own username for mention highlighting
        self.my_username = None
        self.mention_color = get_mention_color(is_dark_theme)
        
        # Load message colors from config
        self.private_colors = get_private_message_colors(config, is_dark_theme)
        self.ban_colors = get_ban_message_colors(config, is_dark_theme)
        self.system_colors = get_system_message_colors(config, is_dark_theme)
        
        # Font setup
        self.body_font = get_font(FontType.TEXT)
        
        # Emoticon settings
        self.emoticon_max_size = int(config.get("ui", "emoticon_max_size") or 140)
        
        # Caches
        self._emoticon_cache: Dict[str, QPixmap] = {}
        self._movie_cache: Dict[str, QMovie] = {}
        
        # Copy highlight state
        self._copied_url: Optional[str] = None
        
        # YouTube support
        self.youtube_enabled = config.get("ui", "youtube", "enabled") or True
        
        # Create viewer instances
        self.image_viewer = None
        self.video_player = None
        if parent_widget:
            self._init_viewers(parent_widget)
    
    def _init_viewers(self, parent_widget):
        """Initialize image and video viewers"""
        self.image_viewer = ImageHoverView(parent=parent_widget)
        icons_path = Path(__file__).parent.parent / "icons"
        self.video_player = VideoPlayer(
            parent=parent_widget,
            icons_path=icons_path,
            config=self.config
        )
    
    def handle_link_lmb(self, url: str, is_media: bool, global_pos, is_ctrl: bool = False):
        """Handle link click - opens in viewer or browser"""
        if is_media and not is_ctrl:
            # Media link without Ctrl: open in viewer
            if VideoPlayer.is_video_url(url) and self.video_player:
                self.video_player.show_video(url, global_pos)
            elif ImageHoverView.is_image_url(url) and self.image_viewer:
                self.image_viewer.show_preview(url, global_pos)
        else:
            # Normal link OR media link with Ctrl: open in browser
            import webbrowser
            try:
                webbrowser.open(url)
            except Exception as e:
                print(f"Failed to open URL: {e}")
    
    def handle_link_rmb(self, url: str):
        """Copy URL to clipboard and briefly highlight it"""
        QApplication.clipboard().setText(url)
        self._copied_url = url
        self.refresh_view.emit()
        QTimer.singleShot(700, self._clear_copy_highlight)

    def _clear_copy_highlight(self):
        self._copied_url = None
        self.refresh_view.emit()

    @staticmethod
    def get_link_at_pos(link_rects: List[Tuple[QRect, str, bool]], pos) -> Optional[Tuple[str, bool]]:
        """Find link at given position"""
        for rect, url, is_media in link_rects:
            if rect.contains(pos):
                return (url, is_media)
        return None
    
    @staticmethod
    def is_over_link(link_rects: List[Tuple[QRect, str, bool]], pos) -> bool:
        """Check if position is over any link"""
        return any(rect.contains(pos) for rect, _, _ in link_rects)
    
    def get_timestamp_color(self, is_ban: bool, is_private: bool, is_system: bool) -> str:
        """Return the appropriate timestamp color for the message type"""
        if is_ban:
            return self.ban_colors["text"]
        if is_private:
            return self.private_colors["text"]
        if is_system:
            return self.system_colors["text"]
        return "#999999"

    def set_my_username(self, username: str):
        """Set the current user's username for mention highlighting"""
        self.my_username = username.lower() if username else None
    
    def update_theme(self, is_dark_theme: bool):
        """Update theme and reload colors"""
        self.is_dark_theme = is_dark_theme
        self.bg_hex = "#1E1E1E" if is_dark_theme else "#FFFFFF"
        self.mention_color = get_mention_color(is_dark_theme)
        self.private_colors = get_private_message_colors(self.config, is_dark_theme)
        self.ban_colors = get_ban_message_colors(self.config, is_dark_theme)
        self.system_colors = get_system_message_colors(self.config, is_dark_theme)
        self._emoticon_cache.clear()
    
    @staticmethod
    def _emoji_prefix(text: str, is_private: bool, is_ban: bool, is_system: bool) -> str:
        """Prepend type emoji for special message types."""
        if is_ban:
            return "🔹 " + text
        if is_private:
            return "🔸 " + text
        if is_system:
            return "◽️ " + text
        return text

    def calculate_content_height(self, text: str, width: int, row: Optional[int] = None) -> int:
        """Calculate height needed for message content"""
        text = ' '.join(text.split())
        
        url_pattern = re.compile(r'https?://[^\s<>"]+')
        def repl(m):
            url = m.group(0)
            cached = get_cached_info(url, use_emojis=True)
            if cached and cached[1]:
                return cached[0] + ' '
            if row is not None and cached:
                try:
                    fetch_async(url, lambda _, r=row: self.refresh_row.emit(r))
                except Exception:
                    pass
            return url + ' '
        
        processed_text = url_pattern.sub(repl, text)
        segments = self.emoticon_manager.parse_emoticons(processed_text)
        
        fm = QFontMetrics(self.body_font)
        current_line_height = fm.height()
        total_height = 0
        current_width = 0
        
        for seg_type, content in segments:
            if seg_type == 'text':
                lines = self._wrap_text(content, width - current_width, fm)
                for i, line in enumerate(lines):
                    if i == 0 and current_width > 0:
                        line_width = fm.horizontalAdvance(line)
                        if current_width + line_width <= width:
                            current_width += line_width
                            continue
                    
                    if current_width > 0:
                        total_height += current_line_height
                        current_line_height = fm.height()
                        current_width = 0
                    current_width = fm.horizontalAdvance(line)
            else:
                pixmap = self._get_emoticon_pixmap(content)
                if pixmap:
                    w, h = pixmap.width(), pixmap.height()
                    if current_width + w > width:
                        total_height += current_line_height
                        current_line_height = h
                        current_width = w
                    else:
                        current_width += w
                        current_line_height = max(current_line_height, h)
        
        if current_width > 0:
            total_height += current_line_height
        
        return max(total_height, fm.height())
    
    def paint_content(
        self, 
        painter: QPainter, 
        x: int, 
        y: int, 
        width: int,
        text: str, 
        row: Optional[int] = None, 
        is_private: bool = False, 
        is_ban: bool = False, 
        is_system: bool = False
    ) -> List[Tuple[QRect, str, bool]]:
        """
        Paint message body content with links, emoticons, and mentions.
        Returns list of (QRect, url, is_media) tuples for clickable links.
        """
        link_rects = []
        
        # Replace newlines with spaces
        text = ' '.join(text.split())
        
        # Extract URLs and replace with placeholders
        url_pattern = re.compile(r'https?://[^\s<>"]+')
        urls = []
        def replace_url(match):
            url = match.group(0)
            urls.append(url)
            return f"[URL{len(urls)-1}] "
        
        processed_text = url_pattern.sub(replace_url, text)
        segments = self.emoticon_manager.parse_emoticons(processed_text)
        
        painter.setFont(self.body_font)
        fm = QFontMetrics(self.body_font)
        
        current_x, current_y = x, y
        line_height = fm.height()
        
        # Determine text color based on message type
        if is_system:
            text_color = self.system_colors["text"]
        elif is_private:
            text_color = self.private_colors["text"]
        elif is_ban:
            text_color = self.ban_colors["text"]
        else:
            text_color = "#FFFFFF" if self.is_dark_theme else "#000000"
        
        # Link colors
        normal_link_color = "#4DA6FF" if self.is_dark_theme else "#0066CC"
        media_link_color = "#4DFF88" if self.is_dark_theme else "#00AA44"
        
        def new_line():
            nonlocal current_x, current_y, line_height
            current_y += line_height
            current_x = x
            line_height = fm.height()
        
        def draw_text_chunk(content: str, color: str):
            """Draw text chunk with mention highlighting"""
            nonlocal current_x
            
            # Only apply mention highlighting for normal messages
            if not is_system and not is_private and not is_ban:
                mention_segments = parse_mentions(content, self.my_username)
            else:
                mention_segments = [(False, content)]
            
            for is_mention, segment_text in mention_segments:
                if not segment_text:
                    continue
                
                # Use mention color AND bold font for mentions
                if is_mention:
                    draw_color = self.mention_color
                    painter.setFont(get_font(FontType.TEXT))
                    bold_font = painter.font()
                    bold_font.setBold(True)
                    painter.setFont(bold_font)
                    fm_local = QFontMetrics(bold_font)
                else:
                    draw_color = color
                    painter.setFont(self.body_font)
                    fm_local = QFontMetrics(self.body_font)
                
                lines = self._wrap_text(segment_text, width - (current_x - x), fm_local)
                for line in lines:
                    if not line:
                        new_line()
                        continue
                    
                    line_width = fm_local.horizontalAdvance(line)
                    if current_x > x and current_x + line_width > x + width:
                        new_line()
                    
                    painter.setPen(QColor(draw_color))
                    painter.drawText(current_x, current_y + fm_local.ascent(), line)
                    current_x += line_width
                
                # Reset to normal font after mention
                if is_mention:
                    painter.setFont(self.body_font)
        
        def draw_link(url: str, is_media: bool = False):
            nonlocal current_x, line_height
            link_text = self._get_link_text(url, row)
            
            # Choose color based on whether it's a media link
            link_color = media_link_color if is_media else normal_link_color
            painter.setPen(QColor(link_color))
            
            remaining = link_text
            while remaining:
                avail = x + width - current_x
                if avail <= 0:
                    new_line()
                    avail = width
                
                chunk = self._fit(remaining, avail, fm) or remaining[0]
                chunk_width = fm.horizontalAdvance(chunk)
                
                if current_x > x and current_x + chunk_width > x + width:
                    new_line()
                    continue
                
                painter.drawText(current_x, current_y + fm.ascent(), chunk)
                link_rect = QRect(current_x, current_y, chunk_width, fm.height())
                if self._copied_url == url:
                    highlight = QColor(link_color)
                    highlight.setAlphaF(0.35)
                    painter.save()
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(highlight)
                    painter.drawRoundedRect(link_rect.adjusted(-2, 0, 2, 0), 3, 3)
                    painter.restore()
                    painter.setPen(QColor(link_color))
                    painter.drawText(current_x, current_y + fm.ascent(), chunk)
                link_rects.append((link_rect, url, is_media))
                current_x += chunk_width
                remaining = remaining[len(chunk):]
        
        placeholder_pattern = re.compile(r'\[URL(\d+)\]')
        
        for seg_type, content in segments:
            if seg_type == 'text':
                last_pos = 0
                for match in placeholder_pattern.finditer(content):
                    if match.start() > last_pos:
                        draw_text_chunk(content[last_pos:match.start()], text_color)
                    url_index = int(match.group(1))
                    url = urls[url_index]
                    is_media = self._is_media_url(url)
                    draw_link(url, is_media)
                    last_pos = match.end()
                
                if last_pos < len(content):
                    draw_text_chunk(content[last_pos:], text_color)
            
            else:  # emoticon
                pixmap = self._get_emoticon_pixmap(content)
                if pixmap:
                    w, h = pixmap.width(), pixmap.height()
                    if current_x > x and current_x + w > x + width:
                        new_line()
                        line_height = h
                    
                    painter.drawPixmap(current_x, current_y, pixmap)
                    current_x += w
                    line_height = max(line_height, h)
        
        return link_rects
    
    def has_animated_emoticons(self, text: str) -> bool:
        """Check if text contains animated emoticons"""
        for seg_type, content in self.emoticon_manager.parse_emoticons(text):
            if seg_type == 'emoticon':
                path = self.emoticon_manager.get_emoticon_path(content)
                if path and path.suffix.lower() == '.gif':
                    return True
        return False
    
    def _is_media_url(self, url: str) -> bool:
        """Check if URL is a media link"""
        return ImageHoverView.is_image_url(url) or VideoPlayer.is_video_url(url)
    
    def _get_link_text(self, url: str, row: Optional[int]) -> str:
        """Get display text for link (process YouTube if applicable)"""
        if not self.youtube_enabled or not is_youtube_url(url):
            return url
        
        cached = get_cached_info(url, use_emojis=True)
        if cached:
            formatted_text, is_cached = cached
            if is_cached:
                return formatted_text
            if row is not None:
                fetch_async(url, lambda result: self.refresh_row.emit(row))
        
        return url
    
    def _wrap_text(self, text: str, width: int, fm: QFontMetrics) -> List[str]:
        """Wrap text to fit within width"""
        if not text or width <= 0:
            return [text] if text else []
        
        lines = []
        for para in text.split('\n'):
            if not para:
                lines.append('')
                continue
            
            current_line, current_width = [], 0
            for word in para.split(' '):
                word_width = fm.horizontalAdvance(word + ' ')
                
                if current_width + word_width <= width:
                    current_line.append(word)
                    current_width += word_width
                elif fm.horizontalAdvance(word) > width:
                    if current_line:
                        lines.append(' '.join(current_line))
                        current_line, current_width = [], 0
                    
                    # Split long word across lines
                    while word:
                        chunk = self._fit(word, width, fm)
                        lines.append(chunk)
                        word = word[len(chunk):]
                else:
                    if current_line:
                        lines.append(' '.join(current_line))
                    current_line = [word]
                    current_width = word_width
            
            if current_line:
                lines.append(' '.join(current_line))
        
        return lines
    
    def _fit(self, text: str, max_pixels: int, fm: QFontMetrics) -> str:
        """Binary search to fit maximum characters within pixel width"""
        if not text or max_pixels <= 0:
            return text[:1] if text else ''
        
        lo, hi, best = 1, len(text), 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if fm.horizontalAdvance(text[:mid]) <= max_pixels:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return text[:best]
    
    def _get_emoticon_pixmap(self, name: str) -> Optional[QPixmap]:
        """Get emoticon pixmap (static or animated)"""
        path = self.emoticon_manager.get_emoticon_path(name)
        if not path:
            return None
        
        # Animated GIF
        if path.suffix.lower() == '.gif':
            key = str(path)
            if key not in self._movie_cache:
                movie = QMovie(str(path))
                try:
                    movie.setParent(QApplication.instance())
                except Exception:
                    pass
                movie.setCacheMode(QMovie.CacheMode.CacheAll)
                first_frame = movie.currentPixmap()
                if not first_frame.isNull():
                    w, h = first_frame.width(), first_frame.height()
                    if w > self.emoticon_max_size or h > self.emoticon_max_size:
                        scale = self.emoticon_max_size / max(w, h)
                        movie.setScaledSize(QSize(int(w * scale), int(h * scale)))
                movie.setSpeed(100)
                movie.start()
                self._movie_cache[key] = movie
            
            return self._movie_cache[key].currentPixmap()
        
        # Static image
        if name in self._emoticon_cache:
            return self._emoticon_cache[name]
        
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            w, h = pixmap.width(), pixmap.height()
            if w > self.emoticon_max_size or h > self.emoticon_max_size:
                scale = self.emoticon_max_size / max(w, h)
                pixmap = pixmap.scaled(
                    int(w * scale), int(h * scale),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
            self._emoticon_cache[name] = pixmap
        
        return pixmap
    
    def cleanup(self):
        """Cleanup caches and resources"""
        self._emoticon_cache.clear()
        for movie in self._movie_cache.values():
            try:
                movie.stop()
            except Exception:
                pass
        self._movie_cache.clear()
        
        if self.image_viewer:
            self.image_viewer.cleanup()
            self.image_viewer.deleteLater()
            self.image_viewer = None
        if self.video_player:
            self.video_player.cleanup()
            self.video_player.deleteLater()
            self.video_player = None