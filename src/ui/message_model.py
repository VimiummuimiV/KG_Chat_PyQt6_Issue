"""Message data model for virtual scrolling"""
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass
from PyQt6.QtCore import QAbstractListModel, Qt, QModelIndex


@dataclass
class MessageData:
    """Lightweight message data structure"""
    timestamp: datetime
    username: str = ""
    body: str = ""
    background_color: Optional[str] = None
    login: Optional[str] = None
    is_private: bool = False
    is_separator: bool = False
    date_str: Optional[str] = None  # For separators
    is_ban: bool = False
    is_system: bool = False
    is_new_messages_marker: bool = False
   
    def get_time_str(self) -> str:
        return self.timestamp.strftime("%H:%M:%S")


class MessageListModel(QAbstractListModel):
    """Model for storing messages - handles data only, no rendering"""
   
    def __init__(self, max_messages: int = 50000):
        super().__init__()
        self._messages: List[MessageData] = []
        self.max_messages = max_messages
   
    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._messages)
   
    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._messages):
            return None
       
        if role == Qt.ItemDataRole.DisplayRole:
            return self._messages[index.row()]
       
        return None
   
    def add_message(self, msg: MessageData):
        """Add a new message"""
        if len(self._messages) >= self.max_messages:
            self.beginRemoveRows(QModelIndex(), 0, 0)
            self._messages.pop(0)
            self.endRemoveRows()
       
        row = len(self._messages)
        self.beginInsertRows(QModelIndex(), row, row)
        self._messages.append(msg)
        self.endInsertRows()
   
    def clear(self):
        if self._messages:
            self.beginResetModel()
            self._messages.clear()
            self.endResetModel()
   
    def clear_private_messages(self):
        """Remove all private messages from the model"""
        if not self._messages:
            return
       
        # Find indices of private messages
        private_indices = [i for i, msg in enumerate(self._messages) if msg.is_private]
       
        if not private_indices:
            return
       
        # Remove in reverse order to maintain indices
        for index in reversed(private_indices):
            self.beginRemoveRows(QModelIndex(), index, index)
            self._messages.pop(index)
            self.endRemoveRows()

    def remove_messages_by_login(self, login: str, timestamp=None):
        """Remove messages by login. If timestamp provided, removes only that specific message."""
        if not login or not self._messages:
            return
        
        # Find indices of messages matching the login (and timestamp if provided)
        indices = [i for i, m in enumerate(self._messages) 
                  if getattr(m, 'login', None) == login 
                  and (timestamp is None or m.timestamp == timestamp)]
        
        if not indices:
            return
        
        # Remove in reverse order to maintain indices
        for index in reversed(indices):
            self.beginRemoveRows(QModelIndex(), index, index)
            self._messages.pop(index)
            self.endRemoveRows()
   
    def get_all_messages(self) -> List[MessageData]:
        return self._messages.copy()