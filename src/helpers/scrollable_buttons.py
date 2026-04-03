"""Reusable scrollable button container with wheel and MMB drag scroll support"""
from PyQt6.QtWidgets import QWidget, QScrollArea, QHBoxLayout, QVBoxLayout
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QWheelEvent, QMouseEvent


class ScrollableButtonContainer(QWidget):
    """
    Orientation-aware scrollable container for icon buttons.

    Supports:
    - Mouse wheel scrolling (hidden scrollbar)
    - Middle-mouse-button drag scrolling

    Usage (vertical - same as ButtonPanel's old scroll area):
        self.btn_bar = ScrollableButtonContainer(Qt.Orientation.Vertical, config=config)
        self.btn_bar.add_widget(some_button)

    Usage (horizontal - chatlog top bar):
        self.nav_bar = ScrollableButtonContainer(Qt.Orientation.Horizontal, config=config)
        self.nav_bar.add_widget(some_button)
    """

    def __init__(self, orientation=Qt.Orientation.Horizontal, config=None, parent=None):
        super().__init__(parent)
        self._orientation = orientation
        self._is_dragging = False
        self._drag_start_pos = None
        self._scroll_start_value = None
        spacing = (config.get("ui", "buttons", "spacing") if config else None) or 8
        self._init_ui(spacing)

    # ------------------------------------------------------------------ setup

    def _init_ui(self, spacing: int):
        is_vertical = self._orientation == Qt.Orientation.Vertical

        # Outer layout that holds only the scroll area
        outer = QVBoxLayout() if is_vertical else QHBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setLayout(outer)

        # Scroll area – both scrollbars hidden; scrolling via events only
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Inner container and its layout
        self.container = QWidget()
        if is_vertical:
            self._layout = QVBoxLayout()
        else:
            self._layout = QHBoxLayout()
            self._layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self._layout.setSpacing(spacing)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addStretch()          # Buttons pushed toward the start; stretch fills remainder
        self.container.setLayout(self._layout)

        self.scroll_area.setWidget(self.container)
        outer.addWidget(self.scroll_area)

        # Install event filter on viewport for wheel + drag
        self.scroll_area.viewport().installEventFilter(self)

    # --------------------------------------------------------------- public API

    def add_widget(self, widget: QWidget):
        """Append a widget before the trailing stretch."""
        # Count - 1 because last item is always the stretch
        self._layout.insertWidget(self._layout.count() - 1, widget)

    def remove_widget(self, widget: QWidget):
        """Remove a widget from the container."""
        self._layout.removeWidget(widget)
        widget.setParent(None)

    def clear_widgets(self):
        """Remove all widgets (keep the stretch)."""
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

    # ---------------------------------------------------------- event handling

    def _scrollbar(self):
        if self._orientation == Qt.Orientation.Vertical:
            return self.scroll_area.verticalScrollBar()
        return self.scroll_area.horizontalScrollBar()

    def eventFilter(self, obj, event):
        if obj != self.scroll_area.viewport():
            return super().eventFilter(obj, event)

        t = event.type()

        # Handle wheel events for scrolling
        if t == QEvent.Type.Wheel:
            sb = self._scrollbar()
            if self._orientation == Qt.Orientation.Horizontal:
                # Prefer horizontal delta; fall back to vertical (for regular mice)
                delta = event.angleDelta().x() or event.angleDelta().y()
            else:
                delta = event.angleDelta().y()
            sb.setValue(sb.value() + (-delta // 2))
            return True

        # Handle middle-mouse-button drag for scrolling
        if t == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.MiddleButton:
            self._is_dragging = True
            self._drag_start_pos = event.pos()
            self._scroll_start_value = self._scrollbar().value()
            self.scroll_area.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return True

        # Handle mouse move for dragging
        if t == QEvent.Type.MouseMove and self._is_dragging and self._drag_start_pos is not None:
            delta = event.pos() - self._drag_start_pos
            offset = delta.y() if self._orientation == Qt.Orientation.Vertical else delta.x()
            self._scrollbar().setValue(self._scroll_start_value - offset)
            return True

        # Handle middle-mouse-button release to stop dragging
        if t == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.MiddleButton and self._is_dragging:
            self._is_dragging = False
            self._drag_start_pos = None
            self._scroll_start_value = None
            self.scroll_area.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            return True

        return super().eventFilter(obj, event)