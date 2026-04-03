import sqlite3
import json
import time
from pathlib import Path
from typing import Optional, Dict, List

from helpers.data import get_data_dir


class AccountManager:
    """Manage multiple XMPP accounts using local SQLite database"""
    
    # Schema definition
    SCHEMA = {
        'table_name': 'accounts',
        'columns': [
            ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
            ('profile_username', 'TEXT NOT NULL'),
            ('profile_password', 'TEXT NOT NULL'),
            ('user_id', 'TEXT NOT NULL'),
            ('chat_username', 'TEXT NOT NULL'),
            ('chat_password', 'TEXT NOT NULL'),
            ('avatar', 'TEXT'),
            ('background', 'TEXT'),
            ('custom_background', 'TEXT'),
            ('active', 'INTEGER DEFAULT 0')
        ]
    }

    def __init__(self, config_path: str = 'settings/config.json'):
        self.config_path = config_path
        data_dir = get_data_dir("accounts")
        self.db_path = str(data_dir / "accounts.db")
        self.config = self._load_config()
        self._init_database()

    def _get_create_table_sql(self):
        """Generate CREATE TABLE SQL from schema"""
        table = self.SCHEMA['table_name']
        cols = ', '.join(f"{name} {type_}" for name, type_ in self.SCHEMA['columns'])
        return f"CREATE TABLE IF NOT EXISTS {table} ({cols})"

    def _init_database(self):
        """Initialize SQLite database with migration support"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check if migration is needed
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='accounts'")
        table_exists = cursor.fetchone() is not None
        
        if table_exists:
            cursor.execute("PRAGMA table_info(accounts)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'profile_username' not in columns:
                # Migration needed
                print("🔄 Migrating database schema...")
                
                # Create new table
                cursor.execute(self._get_create_table_sql().replace('accounts', 'accounts_new'))
                
                # Migrate data: copy login/password to both profile and chat fields
                cursor.execute('''
                    INSERT INTO accounts_new (
                        profile_username,
                        profile_password,
                        user_id,
                        chat_username,
                        chat_password,
                        avatar,
                        background,
                        custom_background,
                        active
                    )
                    SELECT
                        login,
                        password,
                        user_id,
                        login,
                        password,
                        avatar,
                        background,
                        custom_background,
                        active
                    FROM accounts;
                ''')
                
                # Replace old table
                cursor.execute('DROP TABLE accounts')
                cursor.execute('ALTER TABLE accounts_new RENAME TO accounts')
                print("✅ Migration complete")
        else:
            # Create fresh table
            cursor.execute(self._get_create_table_sql())
        
        conn.commit()
        conn.close()

    def _load_config(self) -> dict:
        for i in range(3):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content: return json.loads(content)
                time.sleep(0.1)
            except:
                if i == 2: return {}
                time.sleep(0.1)
        return {}

    def add_account(self, profile_username: str, profile_password: str,
                    user_id: str, chat_username: str, chat_password: str,
                    avatar: str = None, background: str = None,
                    set_active: bool = False) -> bool:
        """Add new account"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            if set_active:
                cursor.execute('UPDATE accounts SET active = 0')

            cursor.execute('''
                INSERT INTO accounts (
                    profile_username,
                    profile_password,
                    user_id,
                    chat_username,
                    chat_password,
                    avatar,
                    background,
                    custom_background,
                    active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                profile_username,
                profile_password,
                user_id,
                chat_username,
                chat_password,
                avatar,
                background,
                None,
                1 if set_active else 0
            ))

            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            return False
        except Exception as e:
            print(f"❌ Error: {e}")
            return False

    def remove_account(self, chat_username: str) -> bool:
        """Remove account by chat username"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM accounts WHERE chat_username = ?', (chat_username,))
            deleted = cursor.rowcount > 0
            conn.commit()
            conn.close()
            return deleted
        except Exception as e:
            print(f"❌ Error: {e}")
            return False

    def get_active_account(self) -> Optional[Dict]:
        """Get active account"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM accounts WHERE active = 1 LIMIT 1')
        row = cursor.fetchone()
        conn.close()

        if row:
            return self._row_to_dict(row)

        return self.get_account_by_index(0)

    def get_account_by_chat_username(self, chat_username: str) -> Optional[Dict]:
        """Get account by chat username"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM accounts WHERE chat_username = ?', (chat_username,))
        row = cursor.fetchone()
        conn.close()
        return self._row_to_dict(row) if row else None

    def get_account_by_index(self, index: int) -> Optional[Dict]:
        """Get account by index"""
        accounts = self.list_accounts()
        if 0 <= index < len(accounts):
            return accounts[index]
        return None

    def list_accounts(self) -> List[Dict]:
        """List all accounts"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM accounts ORDER BY id')
        rows = cursor.fetchall()
        conn.close()
        return [self._row_to_dict(row) for row in rows]

    def switch_account(self, chat_username: str) -> bool:
        """Switch active account"""
        account = self.get_account_by_chat_username(chat_username)
        if not account:
            return False

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('UPDATE accounts SET active = 0')
            cursor.execute('UPDATE accounts SET active = 1 WHERE chat_username = ?', (chat_username,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"❌ Error: {e}")
            return False

    def update_account_color(self, chat_username: str, background: str, 
                           avatar: Optional[str] = None) -> bool:
        """Update account server background color and optionally avatar."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            update_fields = {'background': background}
            if avatar is not None:
                update_fields['avatar'] = avatar

            set_clause = ', '.join(f"{k}=?" for k in update_fields)
            params = list(update_fields.values()) + [chat_username]
            cursor.execute(f'UPDATE accounts SET {set_clause} WHERE chat_username=?', params)

            updated = cursor.rowcount > 0
            conn.commit()
            conn.close()
            return updated
        except Exception as e:
            print(f"❌ Error updating account: {e}")
            return False

    def _row_to_dict(self, row) -> Dict:
        """Convert row to dict based on schema"""
        if not row:
            return None
        
        result = {}
        for i, (col_name, _) in enumerate(self.SCHEMA['columns']):
            result[col_name] = row[i]
        
        # Convert active to boolean
        result['active'] = bool(result['active'])
        
        return result

    def get_server_config(self) -> Dict:
        return self.config.get('server', {})

    def get_rooms(self) -> List[Dict]:
        return self.config.get('rooms', [])

    def get_connection_config(self) -> Dict:
        return self.config.get('connection', {})
