"""SQLite database manager for chatlogs"""
import sqlite3
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Set
from dataclasses import dataclass
from pathlib import Path
from contextlib import contextmanager
import threading

from helpers.data import get_data_dir


@dataclass
class ChatMessage:
    timestamp: str
    username: str
    message: str
    date: str  # YYYY-MM-DD
    
    def __repr__(self):
        return f"{self.date} {self.timestamp} {self.username}: {self.message}"


class ChatlogDB:
    """Thread-safe SQLite database manager for chatlogs"""
    
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = get_data_dir("chatlogs") / "chatlogs.db"
        
        self.db_path = db_path
        self._local = threading.local()
        self._write_lock = threading.Lock()  # Lock for write operations
        self._initialize_db()
    
    @contextmanager
    def _get_connection(self):
        """Get thread-local database connection"""
        if not hasattr(self._local, 'conn'):
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0,  # 30 second timeout for locks
                isolation_level=None  # Autocommit mode
            )
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
            self._local.conn.execute("PRAGMA busy_timeout=30000")  # 30 second busy timeout
        
        try:
            yield self._local.conn
        except Exception:
            try:
                self._local.conn.rollback()
            except:
                pass
            raise
    
    def _initialize_db(self):
        """Create tables and indexes if they don't exist"""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chatlogs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    username TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for fast queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_date 
                ON chatlogs(date)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_username 
                ON chatlogs(username COLLATE NOCASE)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_date_username 
                ON chatlogs(date, username COLLATE NOCASE)
            """)
            
            # Table to track which dates have been fetched (including 404s)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS date_status (
                    date TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    was_truncated INTEGER DEFAULT 0,
                    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
    
    def is_date_cached(self, date: str) -> Tuple[bool, bool, bool]:
        """Check if date is cached
        
        Returns: (is_cached, was_truncated, is_404)
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT status, was_truncated FROM date_status WHERE date = ?",
                (date,)
            )
            row = cursor.fetchone()
            
            if not row:
                return False, False, False
            
            status, was_truncated = row
            is_404 = (status == "not_found")
            is_cached = (status == "cached")
            
            return is_cached, bool(was_truncated), is_404
    
    def mark_date_not_found(self, date: str):
        """Mark date as 404"""
        # Don't cache today's 404s
        if datetime.strptime(date, '%Y-%m-%d').date() >= datetime.now().date():
            return
        
        with self._write_lock:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO date_status (date, status, was_truncated)
                    VALUES (?, 'not_found', 0)
                """, (date,))
    
    def save_messages(self, date: str, messages: List[ChatMessage], was_truncated: bool = False):
        """Save messages for a date (replaces existing)"""
        # Don't cache today
        if datetime.strptime(date, '%Y-%m-%d').date() >= datetime.now().date():
            return
        
        with self._write_lock:  # Serialize all writes
            with self._get_connection() as conn:
                # Use transaction for atomic operation
                conn.execute("BEGIN IMMEDIATE")
                
                try:
                    # Delete existing messages for this date
                    conn.execute("DELETE FROM chatlogs WHERE date = ?", (date,))
                    
                    # Insert new messages in batches
                    if messages:
                        batch_size = 500
                        for i in range(0, len(messages), batch_size):
                            batch = messages[i:i + batch_size]
                            conn.executemany("""
                                INSERT INTO chatlogs (date, timestamp, username, message)
                                VALUES (?, ?, ?, ?)
                            """, [(date, msg.timestamp, msg.username, msg.message) for msg in batch])
                    
                    # Update status
                    conn.execute("""
                        INSERT OR REPLACE INTO date_status (date, status, was_truncated)
                        VALUES (?, 'cached', ?)
                    """, (date, 1 if was_truncated else 0))
                    
                    conn.execute("COMMIT")
                except Exception as e:
                    conn.execute("ROLLBACK")
                    raise
    
    def get_messages(
        self,
        from_date: str,
        to_date: Optional[str] = None,
        usernames: Optional[List[str]] = None,
        search_terms: Optional[List[str]] = None,
        mention_keywords: Optional[List[str]] = None
    ) -> List[ChatMessage]:
        """Get messages for a single date or date range with optional filters
        
        Args:
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD). If None, only gets messages for from_date
            usernames: List of usernames to filter by (case-insensitive)
            search_terms: Search terms for message content (OR condition, case-insensitive)
            mention_keywords: Keywords for mentions (OR condition, case-insensitive)
        
        Returns:
            List of ChatMessage objects
        
        Note:
            All filters are case-insensitive and applied as AND conditions between
            filter types, but OR within each filter type.
        """
        # If no to_date specified, treat as single date query
        if to_date is None:
            to_date = from_date
        
        query = "SELECT date, timestamp, username, message FROM chatlogs WHERE date >= ? AND date <= ?"
        params = [from_date, to_date]
        
        # Username filter - case-insensitive for Cyrillic support
        if usernames:
            username_conditions = ["username = ? COLLATE NOCASE" for _ in usernames]
            query += f" AND ({' OR '.join(username_conditions)})"
            params.extend(usernames)
        
        # Search terms filter (any term matches) - case-insensitive
        if search_terms:
            term_conditions = ["message LIKE ? COLLATE NOCASE" for _ in search_terms]
            query += f" AND ({' OR '.join(term_conditions)})"
            params.extend([f"%{term}%" for term in search_terms])
        
        # Mention keywords filter (any keyword matches) - case-insensitive
        if mention_keywords:
            keyword_conditions = ["message LIKE ? COLLATE NOCASE" for _ in mention_keywords]
            query += f" AND ({' OR '.join(keyword_conditions)})"
            params.extend([f"%{keyword}%" for keyword in mention_keywords])
        
        query += " ORDER BY date, timestamp"
        
        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            return [
                ChatMessage(timestamp=row[1], username=row[2], message=row[3], date=row[0])
                for row in cursor.fetchall()
            ]
    
    def get_cached_dates(self, from_date: str, to_date: str) -> Set[str]:
        """Get set of dates that are cached in the given range"""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT date FROM date_status 
                WHERE date >= ? AND date <= ? AND status = 'cached'
            """, (from_date, to_date))
            return {row[0] for row in cursor.fetchall()}
    
    def get_missing_dates(self, from_date: str, to_date: str) -> List[str]:
        """Get list of dates that need to be fetched"""
        # Generate all dates in range
        start = datetime.strptime(from_date, '%Y-%m-%d').date()
        end = datetime.strptime(to_date, '%Y-%m-%d').date()
        
        all_dates = set()
        current = start
        while current <= end:
            all_dates.add(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)
        
        # Get cached dates (including 404s)
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT date FROM date_status 
                WHERE date >= ? AND date <= ?
            """, (from_date, to_date))
            cached = {row[0] for row in cursor.fetchall()}
        
        # Return missing dates sorted
        return sorted(all_dates - cached)
    
    def get_database_stats(self) -> dict:
        """Get database statistics"""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM chatlogs")
            total_messages = cursor.fetchone()[0]
            
            cursor = conn.execute("SELECT COUNT(*) FROM date_status WHERE status = 'cached'")
            cached_dates = cursor.fetchone()[0]
            
            cursor = conn.execute("SELECT COUNT(*) FROM date_status WHERE status = 'not_found'")
            not_found_dates = cursor.fetchone()[0]
            
            cursor = conn.execute("SELECT COUNT(DISTINCT username) FROM chatlogs")
            unique_users = cursor.fetchone()[0]
            
            # Get database file size
            db_size_mb = self.db_path.stat().st_size / (1024 * 1024) if self.db_path.exists() else 0
            
            return {
                'total_messages': total_messages,
                'cached_dates': cached_dates,
                'not_found_dates': not_found_dates,
                'unique_users': unique_users,
                'db_size_mb': round(db_size_mb, 2)
            }
    
    def vacuum(self):
        """Optimize database (reclaim space)"""
        with self._get_connection() as conn:
            conn.execute("VACUUM")
    
    def close(self):
        """Close database connection"""
        if hasattr(self._local, 'conn'):
            self._local.conn.close()
            delattr(self._local, 'conn')
