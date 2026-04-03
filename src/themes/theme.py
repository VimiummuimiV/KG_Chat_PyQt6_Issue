import qdarktheme
from PyQt6.QtWidgets import QApplication


class ThemeManager:
    DARK = "dark"
    LIGHT = "light"
    
    def __init__(self, config):
        self.config = config
        self.current_theme = self.config.get("ui", "theme") or self.DARK
    
    def apply_theme(self, theme=None):
        if theme is None:
            theme = self.current_theme
        
        app = QApplication.instance()
        if app:
            stylesheet = qdarktheme.load_stylesheet(theme)
            
            # Custom overrides - make container borders transparent only
            stylesheet += """
                QListView,
                QScrollArea,
                QFrame {
                    border: 1px solid transparent !important;
                }
            """
            
            app.setStyleSheet(stylesheet)
            self.current_theme = theme
            self.config.set("ui", "theme", value=theme)
    
    def toggle_theme(self):
        """Toggle between dark and light theme"""
        new_theme = self.LIGHT if self.current_theme == self.DARK else self.DARK
        self.apply_theme(new_theme)
        return new_theme
    
    def is_dark(self):
        """Check if current theme is dark"""
        return self.current_theme == self.DARK
    
    def get_current_theme(self):
        """Get current theme name"""
        return self.current_theme