"""Chatlog fetcher and parser with SQLite database storage"""
import requests
from datetime import datetime
from typing import List, Optional, Tuple
from lxml import etree

from core.chatlogs_db import ChatlogDB, ChatMessage


class ChatlogNotFoundError(Exception):
    """Raised when chatlog is not found (404)"""
    pass


class ChatlogsParser:
    BASE_URL = "https://klavogonki.ru/chatlogs"
    MIN_DATE = datetime(2012, 2, 12).date()
    MAX_FILE_SIZE_MB = 10  # Maximum file size in MB
    
    def __init__(self, session: Optional[requests.Session] = None, db: Optional[ChatlogDB] = None):
        self.session = session or requests.Session()
        self.db = db or ChatlogDB()
    
    def fetch_log(self, date: Optional[str] = None) -> Tuple[str, bool, bool]:
        """Fetch chatlog HTML for date (YYYY-MM-DD)
        
        Returns: (html, was_truncated, from_cache)
        Raises: ChatlogNotFoundError, ValueError
        """
        date = date or datetime.now().strftime('%Y-%m-%d')
        
        # Check minimum date
        date_obj = datetime.strptime(date, '%Y-%m-%d').date()
        if date_obj < self.MIN_DATE:
            raise ValueError(f"Date cannot be before {self.MIN_DATE.strftime('%Y-%m-%d')}")
        
        # Check database status
        is_cached, was_truncated, is_404 = self.db.is_date_cached(date)
        
        if is_404:
            raise ChatlogNotFoundError(f"Chatlog not found for date {date} (cached 404)")
        
        if is_cached:
            # Return empty string since we don't need HTML when using DB
            return "", was_truncated, True
        
        # Fetch from network
        url = f"{self.BASE_URL}/{date}.html"
        try:
            response = self.session.get(url, timeout=10, stream=True)
            
            if response.status_code == 404:
                self.db.mark_date_not_found(date)
                raise ChatlogNotFoundError(f"Chatlog not found for date {date}")
            
            response.raise_for_status()
            response.encoding = 'utf-8'
            
            # Enforce size limit by streaming
            max_bytes = int(self.MAX_FILE_SIZE_MB * 1024 * 1024)
            was_truncated = False
            content = b''
            
            for chunk in response.iter_content(8192):
                content += chunk
                if len(content) >= max_bytes:
                    content = content[:max_bytes]
                    was_truncated = True
                    response.close()
                    break
            
            html = content.decode('utf-8', errors='ignore')
            return html, was_truncated, False
            
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response and e.response.status_code == 404:
                self.db.mark_date_not_found(date)
                raise ChatlogNotFoundError(f"Chatlog not found for date {date}")
            raise
    
    def parse_messages(self, html: str, date: str) -> List[ChatMessage]:
        """Parse messages from HTML using lxml
        
        Structure: <a class="ts" name="HH:MM:SS"/>
                <font class="mn"><user></font>text<br/>
                OR
                <font class="mne">USERNAME action</font><br/> (for /me actions)
        """
        parser = etree.HTMLParser(encoding='utf-8', recover=True)
        tree = etree.fromstring(html.encode('utf-8'), parser)
        messages = []
        
        for ts_elem in tree.xpath('//a[@class="ts"]'):
            timestamp = ts_elem.get('name')
            if not timestamp:
                continue
            
            font_elems = ts_elem.xpath('following-sibling::font[(@class="mn" or @class="mne")][1]')
            if not font_elems:
                continue
            
            font_elem = font_elems[0]
            cls = font_elem.get('class')
            text = (font_elem.text or '').strip()
            
            if cls == 'mn':
                username = text.strip('<> ')
                if not username:
                    continue
                
                parts = []
                if font_elem.tail:
                    parts.append(font_elem.tail)
                
                prev_was_br = False
                for sibling in font_elem.itersiblings():
                    if sibling.tag == 'a' and sibling.get('class') == 'ts':
                        break
                    
                    if sibling.tag == 'br':
                        parts.append('\n')
                        prev_was_br = True
                        continue
                    
                    if sibling.tag == 'a' and sibling.get('href'):
                        parts.append(sibling.text or sibling.get('href'))
                        if sibling.tail:
                            parts.append(sibling.tail)
                        prev_was_br = False
                    
                    else:
                        if sibling.text:
                            parts.append(sibling.text)
                        if sibling.tail:
                            parts.append(sibling.tail)
                        prev_was_br = False
                
                message = ''.join(parts).strip()
            
            else:  # mne
                if not text:
                    continue
                parts = text.split(None, 1)
                username = parts[0]
                action = parts[1] if len(parts) > 1 else text
                message = f"/me {action}"
            
            if message:
                messages.append(ChatMessage(timestamp, username, message, date))
        
        return messages

    def get_messages(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        usernames: Optional[List[str]] = None,
        search_terms: Optional[List[str]] = None,
        mention_keywords: Optional[List[str]] = None
    ) -> Tuple[List[ChatMessage], bool, bool]:
        """Get messages for a single date or date range with optional filters
        
        Args:
            from_date: Start date (YYYY-MM-DD). If None, uses today
            to_date: End date (YYYY-MM-DD). If None, treated as single date query
            usernames: List of usernames to filter by
            search_terms: Search terms for message content
            mention_keywords: Keywords for mentions
        
        Returns:
            Tuple of (messages, was_truncated, from_cache)
            - For single date: was_truncated and from_cache apply to that date
            - For date range: was_truncated is True if ANY date was truncated,
              from_cache is True if ALL dates were cached
        
        Raises:
            ChatlogNotFoundError: If date/range not found
            ValueError: If date is invalid
        """
        from_date = from_date or datetime.now().strftime('%Y-%m-%d')
        
        # Single date query
        if to_date is None:
            return self._get_single_date(from_date, usernames, search_terms, mention_keywords)
        
        # Date range query
        return self._get_date_range(from_date, to_date, usernames, search_terms, mention_keywords)
    
    def _get_single_date(
        self,
        date: str,
        usernames: Optional[List[str]] = None,
        search_terms: Optional[List[str]] = None,
        mention_keywords: Optional[List[str]] = None
    ) -> Tuple[List[ChatMessage], bool, bool]:
        """Get messages for a single date"""
        # Check if we have this date in DB
        is_cached, was_truncated, is_404 = self.db.is_date_cached(date)
        
        if is_404:
            raise ChatlogNotFoundError(f"Chatlog not found for date {date}")
        
        if is_cached:
            # Get from database with filters
            messages = self.db.get_messages(date, None, usernames, search_terms, mention_keywords)
            return messages, was_truncated, True
        
        # Fetch from network
        html, was_truncated, _ = self.fetch_log(date)
        
        # Parse messages
        messages = self.parse_messages(html, date)
        
        # Save to database
        self.db.save_messages(date, messages, was_truncated)
        
        # Apply filters if any
        if usernames or search_terms or mention_keywords:
            messages = self.db.get_messages(date, None, usernames, search_terms, mention_keywords)
        
        return messages, was_truncated, False
    
    def _get_date_range(
        self,
        from_date: str,
        to_date: str,
        usernames: Optional[List[str]] = None,
        search_terms: Optional[List[str]] = None,
        mention_keywords: Optional[List[str]] = None
    ) -> Tuple[List[ChatMessage], bool, bool]:
        """Get messages for a date range
        
        This is optimized for database queries when data is cached.
        """
        # Get missing dates that need to be fetched
        missing_dates = self.db.get_missing_dates(from_date, to_date)
        
        # Track if any date was truncated
        any_truncated = False
        all_cached = len(missing_dates) == 0
        
        # Fetch missing dates (if any)
        for date in missing_dates:
            try:
                html, was_truncated, _ = self.fetch_log(date)
                messages = self.parse_messages(html, date)
                self.db.save_messages(date, messages, was_truncated)
                
                if was_truncated:
                    any_truncated = True
                    
            except ChatlogNotFoundError:
                # Already marked as 404 in fetch_log
                pass
            except Exception as e:
                print(f"Error fetching {date}: {e}")
        
        # Check if any cached date was truncated
        if not any_truncated:
            # Need to check all dates in range for truncation
            cached_dates = self.db.get_cached_dates(from_date, to_date)
            for date in cached_dates:
                _, was_truncated, _ = self.db.is_date_cached(date)
                if was_truncated:
                    any_truncated = True
                    break
        
        # Now get all messages from DB with filters
        messages = self.db.get_messages(from_date, to_date, usernames, search_terms, mention_keywords)
        
        return messages, any_truncated, all_cached
