from PyQt6.QtCore import QObject, pyqtSignal, QTimer, Qt, QEvent, QPropertyAnimation, QEasingCurve
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QSlider
from PyQt6.QtWidgets import QGraphicsOpacityEffect
from PyQt6.QtGui import QFont


class FontScaler(QObject):
    font_size_changed = pyqtSignal() # Fires immediately on any change (drag/wheel/keyboard)
    font_size_committed = pyqtSignal()  # Fires on release (drag) or after idle (wheel/keyboard)

    TEXT_MIN = 12
    TEXT_MAX = 24

    def __init__(self, config):
        super().__init__()
        self.config = config
        self._text_size = max(
            self.TEXT_MIN,
            min(self.TEXT_MAX, self.config.get("ui", "text_font_size") or 17)
        )

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._do_save)

        self._commit_timer = QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.timeout.connect(self.font_size_committed.emit)

    def get_text_size(self) -> int:
        return self._text_size

    def set_size(self, size: int, is_dragging: bool = False):
        size = max(self.TEXT_MIN, min(self.TEXT_MAX, size))
        if size != self._text_size:
            self._text_size = size
            self._notify(is_dragging)

    def scale_up(self):
        self.set_size(self._text_size + 1)

    def scale_down(self):
        self.set_size(self._text_size - 1)

    def _notify(self, is_dragging: bool = False):
        self.font_size_changed.emit()
        self._save_timer.start(300)
        if not is_dragging:
            self._commit_timer.start(150)

    def _do_save(self):
        self.config.set("ui", "text_font_size", value=self._text_size)


class _SliderWheelFilter(QObject):
    """Intercepts wheel on slider — enforces exactly +1/-1 per notch."""

    def __init__(self, font_scaler: FontScaler, parent=None):
        super().__init__(parent)
        self.font_scaler = font_scaler

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel:
            if event.angleDelta().y() > 0:
                self.font_scaler.scale_up()
            else:
                self.font_scaler.scale_down()
            event.accept()
            return True
        return False


class FontScaleSlider(QWidget):
    """
    Horizontal slider for adjusting text font size. Shows current value in a label.
    Dimmed to 0.5 opacity at rest, smoothly reveals to 1.0 on hover.
    """

    def __init__(self, font_scaler: FontScaler, parent=None):
        super().__init__(parent)
        self.font_scaler = font_scaler
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        layout = QHBoxLayout()
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)
        self.setLayout(layout)

        # Slider
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(FontScaler.TEXT_MIN)
        self.slider.setMaximum(FontScaler.TEXT_MAX)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(1)
        self.slider.setValue(font_scaler.get_text_size())
        self.slider.valueChanged.connect(self._on_slider_changed)
        self.slider.sliderReleased.connect(font_scaler.font_size_committed.emit)
        self._wheel_filter = _SliderWheelFilter(font_scaler, self.slider)
        self.slider.installEventFilter(self._wheel_filter)
        layout.addWidget(self.slider, stretch=1)

        # Value label
        self.value_label = QLabel(str(font_scaler.get_text_size()))
        self.value_label.setFont(QFont("Roboto", 12))
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setFixedWidth(24)
        layout.addWidget(self.value_label)

        font_scaler.font_size_changed.connect(self._sync_from_scaler)

        # Opacity effect
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0)
        self.setGraphicsEffect(self._opacity_effect)

        self._anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

    def _fade_to(self, opacity: float):
        self._anim.stop()
        self._anim.setStartValue(self._opacity_effect.opacity())
        self._anim.setEndValue(opacity)
        self._anim.start()

    def enterEvent(self, event):
        self._fade_to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._fade_to(0)
        super().leaveEvent(event)

    def _on_slider_changed(self, value: int):
        self.value_label.setText(str(value))
        self.font_scaler.set_size(value, is_dragging=self.slider.isSliderDown())

    def _sync_from_scaler(self):
        value = self.font_scaler.get_text_size()
        self.slider.blockSignals(True)
        self.slider.setValue(value)
        self.slider.blockSignals(False)
        self.value_label.setText(str(value))