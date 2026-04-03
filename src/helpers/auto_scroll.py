"""Firefox-style middle-click auto-scrolling for PyQt6"""
from PyQt6.QtCore import Qt, QTimer, QPoint, QEvent, QObject
from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtGui import QPainter, QColor, QPen, QMouseEvent
import math

class ScrollIndicator(QWidget):
    """Visual indicator shown during auto-scrolling"""
   
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(60, 80)
        self.scroll_direction = 0 # -1 = up, 0 = none, 1 = down
       
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
       
        # Draw circle in center
        center_x = self.width() // 2
        center_y = self.height() // 2
       
        # Circle
        painter.setPen(QPen(QColor(255, 255, 255, 200), 2))
        painter.setBrush(QColor(0, 0, 0, 128))
        painter.drawEllipse(center_x - 10, center_y - 10, 20, 20)
       
        # Draw arrows using helper function
        self._draw_arrow(painter, center_x, center_y, direction='up',
                        is_active=(self.scroll_direction == -1))
        self._draw_arrow(painter, center_x, center_y, direction='down',
                        is_active=(self.scroll_direction == 1))
   
    def _draw_arrow(self, painter, center_x, center_y, direction, is_active):
        """Helper function to draw an arrow
       
        Args:
            painter: QPainter instance
            center_x: Center X coordinate
            center_y: Center Y coordinate
            direction: 'up' or 'down'
            is_active: Whether this arrow should be highlighted
        """
        opacity = 255 if is_active else 80
        painter.setPen(QPen(QColor(100, 100, 100, opacity), 2))
        painter.setBrush(QColor(100, 100, 100, opacity))
       
        if direction == 'up':
            arrow = [
                QPoint(center_x, center_y - 25),
                QPoint(center_x - 6, center_y - 17),
                QPoint(center_x + 6, center_y - 17)
            ]
        else: # down
            arrow = [
                QPoint(center_x, center_y + 25),
                QPoint(center_x - 6, center_y + 17),
                QPoint(center_x + 6, center_y + 17)
            ]
       
        painter.drawPolygon(arrow)
       
    def set_direction(self, direction):
        """Set scroll direction: -1 (up), 0 (none), 1 (down)"""
        self.scroll_direction = direction
        self.update()

class AutoScroller(QObject):
    """
    Implements Firefox-style auto-scrolling for PyQt6 widgets.
   
    Works with any widget that has a vertical scrollbar:
    - QListView
    - QScrollArea
    - QTextEdit
    - QPlainTextEdit
    - Any QAbstractScrollArea subclass
    """
   
    def __init__(self, widget, scroll_speed=20.0, max_scroll_speed=200, dead_zone=50):
        """
        Initialize auto-scroller.
       
        Args:
            widget: The widget to enable auto-scrolling on (must have a vertical scrollbar)
            scroll_speed: Scrolling sensitivity multiplier
            max_scroll_speed: Maximum scroll speed (pixels per timer tick)
            dead_zone: Dead zone radius in pixels where no scrolling occurs
        """
        super().__init__(parent=widget) # Initialize QObject with widget as parent
        self.widget = widget
        self.scroll_speed = scroll_speed
        self.max_scroll_speed = max_scroll_speed
        self.dead_zone = dead_zone
       
        self.is_scrolling = False
        self.start_pos = QPoint()
        self.current_pos = QPoint()
        self.center_y = 0 # Center Y position for scrolling reference
        self.start_scroll_value = 0
       
        # Scroll indicator
        self.indicator = None
       
        # Timer for smooth scrolling
        self.scroll_timer = QTimer(self) # Parent timer to this QObject
        self.scroll_timer.timeout.connect(self._perform_scroll)
        self.scroll_timer.setInterval(16) # ~60 FPS
       
        # Install event filter on viewport (for QListView) or widget itself
        if hasattr(self.widget, 'viewport'):
            self.widget.viewport().installEventFilter(self)
        else:
            self.widget.installEventFilter(self)
       
        # Store original cursor
        self.original_cursor = None
       
    def eventFilter(self, obj, event):
        """Filter mouse events to handle middle-click scrolling"""
        # Handle events on viewport or widget
        try:
            viewport = self.widget.viewport() if hasattr(self.widget, 'viewport') else None
        except RuntimeError:
            return False
            
        if obj != self.widget and obj != viewport:
            return False
            
        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.MiddleButton:
                # Convert to global position
                if obj == viewport:
                    global_pos = viewport.mapToGlobal(event.pos())
                else:
                    global_pos = event.globalPosition().toPoint()
                self._start_scrolling(global_pos)
                return True
                
        elif event.type() == QEvent.Type.MouseMove:
            if self.is_scrolling:
                # Convert to global position
                if obj == viewport:
                    global_pos = viewport.mapToGlobal(event.pos())
                else:
                    global_pos = event.globalPosition().toPoint()
                self.current_pos = global_pos
                return True
                
        elif event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.MiddleButton and self.is_scrolling:
                self._stop_scrolling()
                return True
                    
        return False
       
    def _get_scrollbar(self):
        """Get the vertical scrollbar from the widget"""
        # Try different widget types
        if hasattr(self.widget, 'verticalScrollBar'):
            return self.widget.verticalScrollBar()
        return None
       
    def _start_scrolling(self, pos):
        """Start auto-scrolling from the given position"""
        scrollbar = self._get_scrollbar()
        if not scrollbar:
            return
           
        self.is_scrolling = True
       
        # Use cursor position as the center reference point
        self.center_y = pos.y()
       
        # Store initial mouse position for reference
        self.start_pos = pos
        self.current_pos = pos
        self.start_scroll_value = scrollbar.value()
       
        # Create and show indicator at cursor position
        self._create_indicator(pos)
       
        # Change cursor
        self.original_cursor = self.widget.cursor()
        self.widget.setCursor(Qt.CursorShape.SizeVerCursor)
       
        # Start timer
        self.scroll_timer.start()
       
    def _stop_scrolling(self):
        """Stop auto-scrolling"""
        self.is_scrolling = False
       
        # Stop timer
        self.scroll_timer.stop()
       
        # Remove indicator
        if self.indicator:
            self.indicator.hide()
            self.indicator.deleteLater()
            self.indicator = None
           
        # Restore cursor
        if self.original_cursor:
            self.widget.setCursor(self.original_cursor)
        else:
            self.widget.unsetCursor()
           
    def _create_indicator(self, pos):
        """Create the scroll indicator widget"""
        if self.indicator:
            self.indicator.deleteLater()
           
        self.indicator = ScrollIndicator()
       
        # Position indicator at click point
        indicator_pos = QPoint(
            pos.x() - self.indicator.width() // 2,
            pos.y() - self.indicator.height() // 2
        )
        self.indicator.move(indicator_pos)
        self.indicator.show()
       
    def _perform_scroll(self):
        """Perform the actual scrolling based on mouse position relative to center"""
        if not self.is_scrolling:
            return
           
        scrollbar = self._get_scrollbar()
        if not scrollbar:
            return
           
        # Calculate delta from cursor click position
        delta_y = self.current_pos.y() - self.center_y
       
        # Check if within dead zone
        if abs(delta_y) <= self.dead_zone:
            if self.indicator:
                self.indicator.set_direction(0)
            return
           
        val = delta_y / self.dead_zone
       
        if abs(val) <= 1:
            if self.indicator:
                self.indicator.set_direction(0)
            return
           
        if val > 0:
            accel = val * math.sqrt(val) - 1
        else:
            accel = val * math.sqrt(-val) + 1
       
        scroll_amount = accel * self.scroll_speed
       
        # Clamp to max speed
        scroll_amount = max(-self.max_scroll_speed,
                            min(self.max_scroll_speed, scroll_amount))
       
        # Update indicator direction
        if self.indicator:
            if delta_y < 0:
                self.indicator.set_direction(-1) # Up
            else:
                self.indicator.set_direction(1) # Down
               
        # Apply scroll
        new_value = scrollbar.value() + int(scroll_amount)
        scrollbar.setValue(new_value)
       
    def cleanup(self):
        """Clean up the auto-scroller"""
        self._stop_scrolling()
       
        # Remove event filter from viewport or widget
        if hasattr(self.widget, 'viewport'):
            self.widget.viewport().removeEventFilter(self)
        else:
            self.widget.removeEventFilter(self)
