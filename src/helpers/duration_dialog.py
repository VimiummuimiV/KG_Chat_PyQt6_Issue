"""Reusable duration dialog for ban periods"""
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QComboBox, QDialogButtonBox
from PyQt6.QtCore import Qt


class DurationDialog(QDialog):
    """Unified dialog for selecting ban duration with multiple time units"""
    
    UNITS = {
        'minutes': 60,
        'hours': 3600,
        'days': 86400,
        'weeks': 604800
    }
    
    def __init__(self, parent=None, default_seconds: int = 3600):
        super().__init__(parent)
        self.setWindowTitle("Ban Duration")
        self.setFixedWidth(320)
        
        # Auto-select best unit for default
        self.value, self.unit = self._seconds_to_best_unit(default_seconds)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        
        lbl = QLabel("Select duration:")
        layout.addWidget(lbl)
        
        # Input row
        row = QHBoxLayout()
        row.setSpacing(8)
        
        self.spin = QSpinBox()
        self.spin.setRange(1, 999)
        self.spin.setValue(self.value)
        row.addWidget(self.spin, stretch=1)
        
        self.combo = QComboBox()
        self.combo.addItems(['minutes', 'hours', 'days', 'weeks'])
        self.combo.setCurrentText(self.unit)
        row.addWidget(self.combo, stretch=1)
        
        layout.addLayout(row)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def _seconds_to_best_unit(self, seconds):
        """Convert seconds to most appropriate unit based on magnitude"""
        # Choose unit based on magnitude for better UX
        # Use the largest unit where the value is >= 1 and < 999
        
        weeks = seconds / 604800
        if weeks >= 1:
            return max(1, round(weeks)), 'weeks'
        
        days = seconds / 86400
        if days >= 1:
            return max(1, round(days)), 'days'
        
        hours = seconds / 3600
        if hours >= 1:
            return max(1, round(hours)), 'hours'
        
        # Default to minutes
        return max(1, seconds // 60), 'minutes'
    
    def get_seconds(self) -> int:
        """Get duration in seconds"""
        return self.spin.value() * self.UNITS[self.combo.currentText()]
    
    @staticmethod
    def get_duration(parent=None, default_seconds: int = 3600):
        """Show dialog and return (seconds, accepted)"""
        dlg = DurationDialog(parent, default_seconds)
        ok = dlg.exec() == QDialog.DialogCode.Accepted
        return (dlg.get_seconds() if ok else default_seconds, ok)