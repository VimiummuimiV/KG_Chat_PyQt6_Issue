"""Ban List Manager - Centralized user blocking system"""
import json
import time
from pathlib import Path
from typing import Dict, Optional, Set


class BanManager:
    """Manages banned users (permanent + temporary in unified structure)"""
    
    def __init__(self, settings_path: Path):
        self.settings_path = settings_path / "banlist.json"
        self.bans: Dict[str, Dict] = {}  # {user_id: {username, expires_at?}}
        self.load()
    
    def load(self):
        """Load bans from JSON"""
        if self.settings_path.exists():
            try:
                with open(self.settings_path, 'r', encoding='utf-8') as f:
                    self.bans = json.load(f)
                self._purge_expired()
            except Exception as e:
                print(f"Error loading ban list: {e}")
                self.bans = {}
        else:
            self.bans = {}
    
    def save(self):
        """Save bans to JSON"""
        try:
            with open(self.settings_path, 'w', encoding='utf-8') as f:
                json.dump(self.bans, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving ban list: {e}")
    
    def add_user(self, user_id: str, username: str, duration: Optional[int] = None):
        """Add ban. If duration is None = permanent, else temporary (duration in seconds)"""
        if not user_id or not username:
            return False
        
        ban_data = {'username': username}
        if duration:
            ban_data['expires_at'] = int(time.time()) + int(duration)
        
        self.bans[str(user_id)] = ban_data
        self.save()
        return True
    
    def remove_user(self, user_id: str):
        """Remove a ban"""
        if str(user_id) in self.bans:
            del self.bans[str(user_id)]
            self.save()
            return True
        return False
    
    def _purge_expired(self):
        """Remove expired temporary bans"""
        now = int(time.time())
        expired = [uid for uid, data in self.bans.items() 
                   if 'expires_at' in data and data['expires_at'] <= now]
        for uid in expired:
            del self.bans[uid]
        if expired:
            self.save()
    
    def is_banned_by_id(self, user_id: str) -> bool:
        """Check if user is banned by ID"""
        if not user_id:
            return False
        self._purge_expired()
        return str(user_id) in self.bans
    
    def is_banned_by_username(self, username: str) -> bool:
        """Check if user is banned by username (fallback)"""
        if not username:
            return False
        self._purge_expired()
        return any(data.get('username') == username for data in self.bans.values())
    
    def get_banned_user_ids(self) -> Set[str]:
        """Get set of all currently banned user IDs"""
        self._purge_expired()
        return set(self.bans.keys())
    
    def get_all_bans(self):
        """Returns {user_id: {username, expires_at?, is_temporary}}"""
        self._purge_expired()
        result = {}
        for uid, data in self.bans.items():
            result[uid] = {
                'username': data['username'],
                'expires_at': data.get('expires_at'),
                'is_temporary': 'expires_at' in data
            }
        return result
    
    def clear_all(self):
        """Clear all bans"""
        self.bans.clear()
        self.save()
    
    def get_username(self, user_id: str) -> Optional[str]:
        """Get username for a banned user ID"""
        ban_data = self.bans.get(str(user_id))
        return ban_data.get('username') if ban_data else None