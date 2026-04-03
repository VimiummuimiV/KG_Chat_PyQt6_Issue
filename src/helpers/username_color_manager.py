"""Unified username color management for username"""
import sqlite3
from typing import Tuple, Dict, Optional

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QColorDialog, QMessageBox

from core.accounts import AccountManager
from core.auth import authenticate


def get_effective_background(account: Dict) -> str:
    """Get the effective background color (custom if set, else server)."""
    return account.get('custom_background') or account.get('background') or '#808080'


def set_color(account_manager: AccountManager, chat_username: str, color: Optional[str] = None, 
              mode: str = 'custom') -> Tuple[bool, str]:
    """
    Unified function for all color operations.
    
    Args:
        account_manager: AccountManager instance
        chat_username: Account chat username
        color: Color hex code (required for 'custom' mode)
        mode: Operation mode - 'custom', 'reset', or 'update_server'
    
    Returns:
        Tuple of (success, message)
    """
    account = account_manager.get_account_by_chat_username(chat_username)
    if not account:
        return False, "Account not found"
    
    try:
        conn = sqlite3.connect(account_manager.db_path)
        cursor = conn.cursor()
        
        if mode == 'custom':
            if not color:
                return False, "Color is required for custom mode"
            cursor.execute('UPDATE accounts SET custom_background = ? WHERE chat_username = ?', 
                          (color, chat_username))
            msg = f"Custom color set to {color}"
            
        elif mode == 'reset':
            cursor.execute('UPDATE accounts SET custom_background = NULL WHERE chat_username = ?', 
                          (chat_username,))
            msg = "Reset to original server color"
            
        elif mode == 'update_server':
            # Use profile credentials for web authentication
            profile_user = account.get('profile_username')
            profile_pass = account.get('profile_password')
            
            if not profile_user or not profile_pass:
                return False, "Profile credentials not found in account. Please re-add this account."
            
            new_data = authenticate(profile_user, profile_pass)
            if not new_data:
                return False, f"Authentication failed for user '{profile_user}'. Please verify your profile password is correct."
            
            new_bg = new_data.get('background', '#808080')
            new_avatar = new_data.get('avatar')
            
            update_fields = {}
            if new_bg != account['background']:
                update_fields['background'] = new_bg
            if new_avatar != account['avatar']:
                update_fields['avatar'] = new_avatar
            
            if not update_fields:
                return False, "No changes - data matches server"
            
            set_clause = ', '.join(f"{k}=?" for k in update_fields)
            params = list(update_fields.values()) + [chat_username]
            cursor.execute(f'UPDATE accounts SET {set_clause} WHERE chat_username=?', params)
            changed_items = ', '.join(update_fields.keys())
            msg = f"Updated {changed_items} from server"
        
        else:
            return False, f"Invalid mode: {mode}"
        
        updated = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return updated, msg if updated else "No changes made"
        
    except Exception as e:
        return False, f"Operation failed: {str(e)}"


def _refresh_cache(account_manager: AccountManager, account: Dict, cache) -> None:
    """Refresh account data and update own color in cache after any color change."""
    updated_account = account_manager.get_account_by_chat_username(account['chat_username'])
    if updated_account:
        account.update(updated_account)
    if cache:
        effective_bg = get_effective_background(account)
        cache.update_user(account['user_id'], account['chat_username'], effective_bg)


def change_username_color(parent, account_manager: AccountManager, account: Dict, cache) -> bool:
    """Change username color via color dialog."""
    if not account or not account.get('chat_username'):
        QMessageBox.warning(parent, "No Account", "No account selected.")
        return False
    
    current_color = get_effective_background(account)
    color = QColorDialog.getColor(QColor(current_color), parent, "Choose Username Color")
    
    if not color.isValid():
        return False
    
    hex_color = color.name()
    success, message = set_color(account_manager, account['chat_username'], hex_color, 'custom')
    
    if success:
        _refresh_cache(account_manager, account, cache)
        QMessageBox.information(parent, "Success", message)
        return True
    else:
        QMessageBox.critical(parent, "Error", message)
        return False


def reset_username_color(parent, account_manager: AccountManager, account: Dict, cache) -> bool:
    """Reset username color to original."""
    if not account or not account.get('chat_username'):
        QMessageBox.warning(parent, "No Account", "No account selected.")
        return False
    
    if not account.get('custom_background'):
        QMessageBox.information(parent, "Info", "Nothing to reset - using original color.")
        return True
    
    success, message = set_color(account_manager, account['chat_username'], None, 'reset')
    
    if success:
        _refresh_cache(account_manager, account, cache)
        QMessageBox.information(parent, "Success", message)
        return True
    else:
        QMessageBox.critical(parent, "Error", message)
        return False


def update_from_server(parent, account_manager: AccountManager, account: Dict, cache) -> bool:
    """Update username color from server."""
    if not account or not account.get('chat_username'):
        QMessageBox.warning(parent, "No Account", "No account selected.")
        return False
    
    success, message = set_color(account_manager, account['chat_username'], None, 'update_server')
    
    if success:
        _refresh_cache(account_manager, account, cache)
    
    QMessageBox.information(parent, "Success" if success else "Info", message)
    return success