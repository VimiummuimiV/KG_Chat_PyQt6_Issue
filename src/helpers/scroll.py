from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QScrollArea, QListView, QAbstractItemView

def scroll(widget, mode="bottom", pos=0.0, delay=10, target_row=None):
    def _scroll():
        # Check if widget is still valid (not deleted)
        try:
            if widget is None or not hasattr(widget, 'isVisible'):
                return
            # This call will raise RuntimeError if widget has been deleted
            widget.isVisible()
        except RuntimeError:
            return  # Widget has been deleted, skip scroll
        
        # Get scrollbar - works for both widget types
        try:
            sb = getattr(widget, "verticalScrollBar", lambda: None)()
            if not sb:
                return
        except RuntimeError:
            return  # Widget deleted during access
        
        # QListView - use model-based scrolling when possible
        if isinstance(widget, QListView):
            try:
                m = widget.model()
                if not m or not m.rowCount():
                    return
                
                if mode == "middle" and target_row is not None:
                    # Scroll specific row to center
                    if 0 <= target_row < m.rowCount():
                        widget.scrollTo(m.index(target_row, 0), QAbstractItemView.ScrollHint.PositionAtCenter)
                    return
                elif mode in ("top", "bottom"):
                    # Scroll to first or last item
                    i = 0 if mode == "top" else m.rowCount() - 1
                    hint = QAbstractItemView.ScrollHint.PositionAtTop if mode == "top" else QAbstractItemView.ScrollHint.PositionAtBottom
                    widget.scrollTo(m.index(i, 0), hint)
                    return
            except RuntimeError:
                return  # Widget or model deleted during access
        
        # QScrollArea - refresh geometry
        if isinstance(widget, QScrollArea):
            try:
                if widget.widget():
                    widget.widget().updateGeometry()
                    widget.updateGeometry()
            except RuntimeError:
                return  # Widget deleted during access
        
        # Common scrollbar-based scrolling for both types
        try:
            if mode == "top":
                sb.setValue(0)
            elif mode == "bottom":
                sb.setValue(sb.maximum())
            elif mode == "middle":
                sb.setValue(sb.maximum() // 2)
            else:  # relative
                sb.setValue(int(sb.maximum() * max(0.0, min(1.0, pos))))
        except RuntimeError:
            return  # Scrollbar deleted during access
    
    if delay > 0:
        QTimer.singleShot(delay, _scroll)
        if mode == "bottom" and delay < 50:
            QTimer.singleShot(50, _scroll)
    else:
        _scroll()