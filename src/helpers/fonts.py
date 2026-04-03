"""Unified font manager for text and emoji rendering"""
from pathlib import Path
from PyQt6.QtGui import QFontDatabase, QFont
from PyQt6.QtWidgets import QApplication
from enum import Enum


class FontType(Enum):
    """Font type categories"""
    UI = "ui"           # Buttons, inputs, small UI elements
    TEXT = "text"       # Messages, content, body text
    HEADER = "header"   # Titles, section headers


class FontManager:
    """Centralized font manager with unified API"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        
        self.fonts_dir = Path(__file__).parent.parent / "fonts"
        self.config_path = Path(__file__).parent.parent / "settings" / "config.json"
        self.config = None
        self.loaded = False
        self.font_scaler = None
        self._font_cache: dict = {}  # (FontType, size, weight_value, italic) -> QFont
        self._initialized = True
    
    def _invalidate_cache(self):
        """Clear font cache — called when font size changes"""
        self._font_cache.clear()

    def set_font_scaler(self, font_scaler):
        """Set the font scaler instance for dynamic sizing"""
        self.font_scaler = font_scaler
        font_scaler.font_size_changed.connect(self._invalidate_cache)
    
    def _load_config(self):
        """Load config if not already loaded"""
        if self.config is None:
            try:
                from helpers.config import Config
                self.config = Config(str(self.config_path))
            except ImportError:
                print("⚠️ Could not load config")
                self.config = type('SimpleConfig', (), {
                    'get': lambda self, *args: None
                })()
    
    def _load_font_family(self, family_name: str) -> bool:
        """Load a font family by name from fonts directory"""
        family_dir = self.fonts_dir / family_name
        if not family_dir.exists():
            return False
        
        variable_fonts = list(family_dir.glob("*-VariableFont*.ttf"))
        
        static_dir = family_dir / "static"
        static_fonts = []
        if static_dir.exists():
            static_fonts = [
                static_dir / f"{family_name}-Regular.ttf",
                static_dir / f"{family_name}-Medium.ttf",
                static_dir / f"{family_name}-Bold.ttf",
            ]
        
        font_files = variable_fonts + static_fonts
        
        loaded_any = False
        for font_file in font_files:
            if font_file.exists():
                font_id = QFontDatabase.addApplicationFont(str(font_file))
                if font_id != -1:
                    loaded_any = True
        
        return loaded_any
    
    def load_fonts(self):
        """Load custom fonts from fonts directory"""
        if self.loaded:
            return True
        
        self._load_config()
        
        text_family = self.config.get("ui", "text_font_family") or "Roboto"
        emoji_family = self.config.get("ui", "emoji_font_family") or "Noto Color Emoji"
        
        if not self.fonts_dir.exists():
            print(f"⚠️ Fonts directory not found: {self.fonts_dir}")
            self.loaded = True
            return False
        
        if self._load_font_family(text_family):
            print(f"✅ Loaded text font: {text_family}")
        else:
            print(f"⚠️ Could not load text font: {text_family}")
        
        emoji_file = self.fonts_dir / "Noto_Color_Emoji" / "NotoColorEmoji-Regular.ttf"
        if emoji_file.exists():
            font_id = QFontDatabase.addApplicationFont(str(emoji_file))
            if font_id != -1:
                print(f"✅ Loaded emoji font: {emoji_family}")
        else:
            print(f"⚠️ Could not load emoji font: {emoji_family}")
        
        self.loaded = True
        return True
    
    def get_font(self, font_type: FontType = FontType.TEXT, 
                  size: int = None, 
                  weight: QFont.Weight = QFont.Weight.Normal,
                  italic: bool = False) -> QFont:
        """
        Unified font getter with type-based defaults.
        Results are cached — cache is invalidated on font size change.
        """
        if not self.loaded:
            self._load_config()
        
        text_family = self.config.get("ui", "text_font_family") or "Roboto"
        emoji_family = self.config.get("ui", "emoji_font_family") or "Noto Color Emoji"
        
        # Resolve size
        if size is None:
            if font_type == FontType.UI:
                size = self.config.get("ui", "ui_font_size") or 12
            elif font_type == FontType.TEXT:
                size = self.font_scaler.get_text_size() if self.font_scaler else (
                    self.config.get("ui", "text_font_size") or 16
                )
            elif font_type == FontType.HEADER:
                size = self.config.get("ui", "header_font_size") or 18
                if weight == QFont.Weight.Normal:
                    weight = QFont.Weight.Bold
            else:
                size = 12
        
        # Cache lookup — use int(weight) so the key is hashable across Qt versions
        key = (font_type, size, int(weight), italic)
        cached = self._font_cache.get(key)
        if cached is not None:
            return cached
        
        font = QFont(text_family, size, weight)
        font.setItalic(italic)
        font.setFamilies([text_family, emoji_family])
        self._font_cache[key] = font
        return font
    
    def set_application_font(self, app: QApplication):
        """Set application-wide default font (uses UI size)"""
        if not self.loaded:
            self._load_config()
        
        default_font = self.get_font(FontType.UI)
        app.setFont(default_font)
        
        text_family = self.config.get("ui", "text_font_family") or "Roboto"
        emoji_family = self.config.get("ui", "emoji_font_family") or "Noto Color Emoji"
        ui_font_size = self.config.get("ui", "ui_font_size") or 12
        
        print(f"✅ Application font set: {text_family} {ui_font_size}pt with {emoji_family} for emoji")


# Global instance
_font_manager = FontManager()


# Public API
def load_fonts() -> bool:
    return _font_manager.load_fonts()


def get_font(font_type: FontType = FontType.TEXT, 
             size: int = None,
             weight: QFont.Weight = QFont.Weight.Normal,
             italic: bool = False) -> QFont:
    return _font_manager.get_font(font_type, size, weight, italic)


def set_application_font(app: QApplication):
    _font_manager.set_application_font(app)


def set_font_scaler(font_scaler):
    _font_manager.set_font_scaler(font_scaler)


def get_userlist_width() -> int:
    """Calculate appropriate userlist width based on current text font size"""
    current_size = _font_manager.font_scaler.get_text_size() if _font_manager.font_scaler else (
        (_font_manager.config.get("ui", "text_font_size") if _font_manager.config else None) or 16
    )
    base_size = 16
    base_width = 380
    scaled_width = int(base_width * (current_size / base_size))
    return max(200, min(500, scaled_width))