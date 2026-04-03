"""User list management"""
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
from helpers.jid_utils import extract_user_data_from_jid

@dataclass
class ChatUser:
    """Chat user"""
    user_id: str
    login: str
    jid: str
    background: Optional[str] = None
    game_id: Optional[str] = None
    affiliation: str = 'none'
    role: str = 'participant'
    moderator: bool = False
    status: str = 'available'
    last_seen: datetime = None
    
    def __post_init__(self):
        if self.last_seen is None:
            self.last_seen = datetime.now()
    
class UserList:
    """Manage chat users"""
    
    def __init__(self):
        self.users: Dict[str, ChatUser] = {}
    
    def add_or_update(self, jid: str, login: str, user_id: str = None, 
                      background: str = None, game_id: str = None, affiliation: str = 'none',
                      role: str = 'participant', moderator: bool = False) -> ChatUser:
        """Add or update user"""
        
        # Extract user_id from JID if not provided
        if not user_id:
            user_id, _ = extract_user_data_from_jid(jid)
        
        if jid in self.users:
            user = self.users[jid]
            user.login = login
            if user_id:
                user.user_id = user_id
            if background:
                user.background = background
            # Always set/clear game_id based on presence update so UI reflects current state
            user.game_id = game_id
            user.affiliation = affiliation
            user.role = role
            user.moderator = moderator
            user.status = 'available'
            user.last_seen = datetime.now()
        else:
            user = ChatUser(
                user_id=user_id or '',
                login=login,
                jid=jid,
                background=background,
                game_id=game_id,
                affiliation=affiliation,
                role=role,
                moderator=moderator
            )
            self.users[jid] = user
        
        return user
    
    def remove(self, jid: str) -> bool:
        """Remove user"""
        if jid in self.users:
            self.users[jid].status = 'unavailable'
            return True
        return False
    
    def get(self, jid: str) -> Optional[ChatUser]:
        """Get user by JID"""
        return self.users.get(jid)
    
    def get_all(self) -> List[ChatUser]:
        """Get all users"""
        return list(self.users.values())
    
    def get_online(self) -> List[ChatUser]:
        """Get online users"""
        return [u for u in self.users.values() if u.status == 'available']
    
    def format_list(self, online_only: bool = False) -> str:
        """Format user list"""
        users = self.get_online() if online_only else self.get_all()
        
        if not users:
            return "👥 No users"
        
        result = f"👥 Users ({len(users)}):\n" + "═" * 40 + "\n"
        for user in sorted(users, key=lambda u: u.login.lower()):
            emoji = "🟢" if user.status == 'available' else "⚫"
            game = f"\n   └─ 🎮 Game #{user.game_id}" if user.game_id else ""
            bg = f" [{user.background}]" if user.background else ""
            result += f"{emoji} {user.login}{bg}{game}\n"
        result += "═" * 40
        return result
    
    def clear(self):
        """Clear all users"""
        self.users.clear()
