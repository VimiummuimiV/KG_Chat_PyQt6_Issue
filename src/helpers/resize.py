"""Centralized resize event handling for chat window"""
from PyQt6.QtCore import QTimer


def recalculate_layout(chat_window):
    """
    Force layout recalculation after userlist visibility change.
    Ensures messages recalculate when available width changes.
    """
    current_view = chat_window.stacked_widget.currentWidget()
    
    if current_view == chat_window.messages_widget:
        chat_window.messages_widget._force_recalculate()
        QTimer.singleShot(50, lambda: chat_window.messages_widget._force_recalculate())
    elif current_view == chat_window.chatlog_widget and chat_window.chatlog_widget:
        chat_window.chatlog_widget._force_recalculate()
        QTimer.singleShot(50, lambda: chat_window.chatlog_widget._force_recalculate())


def handle_chat_resize(chat_window, width: int):
    """
    Handle all resize logic for ChatWindow
    
    Args:
        chat_window: ChatWindow instance
        width: Current window width
    """
    # Determine current view and corresponding widgets/settings
    current_view = chat_window.stacked_widget.currentWidget()
    is_chatlog_view = (current_view == chat_window.chatlog_widget)
    
    if is_chatlog_view:
        userlist_widget = chat_window.chatlog_userlist_widget
        config_key = "chatlog_userlist_visible"
        auto_hide_attr = "auto_hide_chatlog_userlist"
    else:
        userlist_widget = chat_window.user_list_widget
        config_key = "messages_userlist_visible"
        auto_hide_attr = "auto_hide_messages_userlist"
    
    # Check compact mode transition (1000px threshold)
    was_compact = chat_window.messages_widget.delegate.compact_mode
    is_compact = width <= 1000
    
    # Re-enable auto-hide when crossing the 1000px threshold
    if was_compact != is_compact:
        setattr(chat_window, auto_hide_attr, True)
    
    # Get userlist visibility config
    userlist_visible_config = chat_window.config.get("ui", config_key)
    if userlist_visible_config is None:
        userlist_visible_config = True
    
    # Apply auto-hide logic for userlists
    auto_hide = getattr(chat_window, auto_hide_attr)
    
    # Handle button panel visibility
    if width < 500:
        if hasattr(chat_window, 'button_panel') and chat_window.button_panel.isVisible():
            if not getattr(chat_window, '_hover_reveal', False):
                chat_window.button_panel.setVisible(False)
    else:
        if hasattr(chat_window, 'button_panel') and not chat_window.button_panel.isVisible():
            chat_window.button_panel.setVisible(True)

    # Hide/show userlist_panel at 1000px threshold (same as compact mode)
    if auto_hide and hasattr(chat_window, 'userlist_panel'):
        if is_compact:
            chat_window.userlist_panel.setVisible(False)
        elif userlist_visible_config:
            chat_window.userlist_panel.setVisible(True)
    
    # Reposition emoticon selector if visible
    if hasattr(chat_window, 'emoticon_selector') and chat_window.emoticon_selector.isVisible():
        QTimer.singleShot(10, chat_window._position_emoticon_selector)
    
    # Update compact mode for all widgets
    if was_compact != is_compact:
        chat_window.messages_widget.set_compact_mode(is_compact)
        if chat_window.chatlog_widget:
            chat_window.chatlog_widget.set_compact_mode(is_compact)
            chat_window.chatlog_widget.set_compact_layout(is_compact)
        QTimer.singleShot(150, chat_window._complete_resize_recalculation)
    else:
        QTimer.singleShot(50, chat_window._complete_resize_recalculation)