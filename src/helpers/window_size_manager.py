"""Window size persistence manager with debounced saving"""
from PyQt6.QtCore import QTimer
from helpers.config import Config


class WindowSizeManager:
    """Manages window size persistence with debounced config saving"""
    
    def __init__(self, config: Config, debounce_ms: int = 500, on_save_callback=None):
        """
        Args:
            config: Config instance
            debounce_ms: Milliseconds to wait before saving (default 500ms)
            on_save_callback: Optional callback to run after saving geometry
        """
        self.config = config
        self.on_save_callback = on_save_callback
        self.save_timer = QTimer()
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self._save_geometry)
        self.debounce_ms = debounce_ms
        
        # Pending geometry to save
        self._pending_width = None
        self._pending_height = None
        self._pending_x = None
        self._pending_y = None
    
    def get_saved_size(self) -> tuple[int | None, int | None]:
        """Get saved window size from config
        
        Returns:
            Tuple of (width, height) or (None, None) if not saved
        """
        width = self.config.get("ui", "window", "width")
        height = self.config.get("ui", "window", "height")
        return (width, height)
    
    def get_saved_position(self) -> tuple[int | None, int | None]:
        """Get saved window position from config
        
        Returns:
            Tuple of (x, y) or (None, None) if not saved
        """
        x = self.config.get("ui", "window", "x")
        y = self.config.get("ui", "window", "y")
        return (x, y)
    
    def get_saved_geometry(self) -> tuple[int | None, int | None, int | None, int | None]:
        """Get saved window geometry (size + position) from config
        
        Returns:
            Tuple of (width, height, x, y) or (None, None, None, None) if not saved
        """
        width, height = self.get_saved_size()
        x, y = self.get_saved_position()
        return (width, height, x, y)
    
    def has_saved_size(self) -> bool:
        """Check if a saved geometry exists (size or position)"""
        width, height, x, y = self.get_saved_geometry()
        return any(v is not None for v in [width, height, x, y])
    
    def update_geometry(self, width: int, height: int, x: int, y: int):
        """Update window geometry (size + position) with debounce
        
        Args:
            width: Window width
            height: Window height
            x: Window x position
            y: Window y position
        """
        self._pending_width = width
        self._pending_height = height
        self._pending_x = x
        self._pending_y = y
        
        # Restart timer (debounce)
        self.save_timer.stop()
        self.save_timer.start(self.debounce_ms)
    
    def _save_geometry(self):
        """Internal: Save pending geometry to config"""
        if self._pending_width is not None and self._pending_height is not None:
            self.config.set("ui", "window", "width", value=self._pending_width)
            self.config.set("ui", "window", "height", value=self._pending_height)
        
        if self._pending_x is not None and self._pending_y is not None:
            self.config.set("ui", "window", "x", value=self._pending_x)
            self.config.set("ui", "window", "y", value=self._pending_y)
        
        # Trigger callback after save (if provided)
        if self.on_save_callback:
            self.on_save_callback()
    
    def reset_size(self):
        """Reset saved geometry (clear size and position from config)
        
        Returns:
            bool: True if geometry was reset, False if already at default
        """
        had_saved = self.has_saved_size()
        
        self.config.set("ui", "window", "width", value=None)
        self.config.set("ui", "window", "height", value=None)
        self.config.set("ui", "window", "x", value=None)
        self.config.set("ui", "window", "y", value=None)
        
        # Cancel any pending save
        self.save_timer.stop()
        self._pending_width = None
        self._pending_height = None
        self._pending_x = None
        self._pending_y = None
        
        return had_saved
    
    def cleanup(self):
        """Cleanup resources"""
        # Force immediate save if pending
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_geometry()