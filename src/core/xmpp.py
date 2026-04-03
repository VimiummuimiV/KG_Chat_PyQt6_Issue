"""XMPP BOSH Client"""
import requests
import xml.etree.ElementTree as ET
import base64
import random
from pathlib import Path
from typing import Optional, Callable
from datetime import datetime

from .accounts import AccountManager
from .userlist import UserList
from .messages import MessageParser

class XMPPClient:
    """XMPP BOSH Client"""
   
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = Path(__file__).parent / ".." / "settings/config.json"
       
        self.account_manager = AccountManager(str(config_path))
        self.connected_account = None
        self.rid = int(random.random() * 1e10)
        self.sid = None
        self.jid = None
       
        self.message_callback: Optional[Callable] = None
        self.presence_callback: Optional[Callable] = None
       
        self.user_list = UserList()
        self.initial_roster_received = False
       
        server = self.account_manager.get_server_config()
        self.url = server.get('url')
        self.domain = server.get('domain')
        self.resource = server.get('resource')
       
        if not self.url or not self.domain:
            raise RuntimeError("❌ Invalid config")
       
        conn = self.account_manager.get_connection_config()
        self.conn_params = {
            'xml:lang': conn.get('lang', 'en'),
            'wait': conn.get('wait', '60'),
            'hold': conn.get('hold', '1'),
            'content': conn.get('content_type', 'text/xml; charset=utf-8'),
            'ver': conn.get('version', '1.6'),
            'xmpp:version': conn.get('xmpp_version', '1.0')
        }
       
        self.headers = {
            'Content-Type': 'text/xml; charset=UTF-8',
            'Origin': 'https://klavogonki.ru',
            'Referer': 'https://klavogonki.ru/gamelist/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Connection': 'keep-alive'
        }
       
        self.session = requests.Session()
        self.session.headers.update(self.headers)
   
    def set_message_callback(self, callback: Callable):
        """Set message callback"""
        self.message_callback = callback
   
    def set_presence_callback(self, callback: Callable):
        """Set presence callback"""
        self.presence_callback = callback

    def _get_effective_background(self) -> Optional[str]:
        """Get effective background: custom if exists, otherwise server background"""
        if self.connected_account is None:
            return None
        return self.connected_account.get('custom_background') or self.connected_account.get('background')
   
    def build_body(self, children=None, **attrs):
        """Build BOSH body"""
        body = ET.Element('body', {
            'rid': str(self.rid),
            'xmlns': 'http://jabber.org/protocol/httpbind',
            **{k: v for k, v in attrs.items() if v is not None}
        })
        if self.sid:
            body.set('sid', self.sid)
        if any(k.startswith('xmpp:') for k in attrs):
            body.set('xmlns:xmpp', 'urn:xmpp:xbosh')
        if children:
            for child in children:
                body.append(child)
        return ET.tostring(body, encoding='utf-8').decode('utf-8')
   
    def send_request(self, payload, verbose: bool = True, timeout: int = 10):
        """Send request with configurable timeout"""
        if verbose:
            print(f"\n📤 {payload[:100]}...")
       
        response = self.session.post(self.url, data=payload, timeout=timeout)
        response.raise_for_status()
       
        if verbose:
            print(f"📥 {response.text[:100]}...")
        return response.text
   
    def parse_xml(self, xml_text):
        """Parse XML"""
        try:
            return ET.fromstring(xml_text)
        except ET.ParseError as e:
            print(f"❌ Parse error: {e}")
            return None
   
    def connect(self, account=None):
        """Connect to XMPP"""
        if account is None:
            account = self.account_manager.get_active_account()
        elif isinstance(account, str):
            account = self.account_manager.get_account_by_chat_username(account)
       
        if not account:
            print("❌ No account")
            return False
       
        self.connected_account = account
       
        print(f"🔑 Connecting: {account['chat_username']}")
       
        user_id = account['user_id']
        chat_username = account['chat_username']
        chat_password = account['chat_password']
       
        try:
            # Initialize session
            print(f"🔌 [1/5] Sending session init to {self.url}...")
            payload = self.build_body(to=self.domain, **self.conn_params)
            root = self.parse_xml(self.send_request(payload, verbose=False, timeout=20))
            if root is not None:
                self.sid = root.get('sid')
                print(f"✅ [1/5] Session init OK - SID: {self.sid}")
            else:
                print(f"❌ [1/5] Session init failed - no XML response")

            if not self.sid:
                print(f"❌ [1/5] No SID received - aborting connect")
                return False

            # Auth
            print(f"🔐 [2/5] Sending auth for user: {chat_username}...")
            self.rid += 1
            authcid = f'{user_id}#{chat_username}'
            auth_str = f'\0{authcid}\0{chat_password}'
            auth_b64 = base64.b64encode(auth_str.encode('utf-8')).decode('ascii')

            auth_elem = ET.Element('auth', {
                'xmlns': 'urn:ietf:params:xml:ns:xmpp-sasl',
                'mechanism': 'PLAIN'
            })
            auth_elem.text = auth_b64

            self.send_request(self.build_body(children=[auth_elem]), verbose=False, timeout=10)
            print(f"✅ [2/5] Auth sent OK")

            # Restart stream
            print(f"🔄 [3/5] Restarting stream...")
            self.rid += 1
            payload = self.build_body(**{
                'xmpp:restart': 'true',
                'to': self.domain,
                'xml:lang': 'en'
            })
            self.send_request(payload, verbose=False, timeout=10)
            print(f"✅ [3/5] Stream restart OK")

            # Bind resource
            print(f"📎 [4/5] Binding resource...")
            self.rid += 1
            iq = ET.Element('iq', {'type': 'set', 'id': 'bind_1', 'xmlns': 'jabber:client'})
            bind = ET.SubElement(iq, 'bind', {'xmlns': 'urn:ietf:params:xml:ns:xmpp-bind'})
            ET.SubElement(bind, 'resource').text = self.resource

            root = self.parse_xml(self.send_request(self.build_body(children=[iq]), verbose=False, timeout=10))
            if root is not None:
                jid_el = root.find('.//{urn:ietf:params:xml:ns:xmpp-bind}jid')
                if jid_el is not None:
                    self.jid = jid_el.text
                    print(f"✅ [4/5] Bind OK - JID: {self.jid}")
                else:
                    print(f"❌ [4/5] Bind response received but no JID element found")
            else:
                print(f"❌ [4/5] Bind failed - no XML response")

            if not self.jid:
                print(f"❌ [4/5] No JID - aborting connect")
                return False

            # Session
            print(f"🗂️ [5/5] Starting session...")
            self.rid += 1
            iq = ET.Element('iq', {'type': 'set', 'id': 'session_1', 'xmlns': 'jabber:client'})
            ET.SubElement(iq, 'session', {'xmlns': 'urn:ietf:params:xml:ns:xmpp-session'})
            self.send_request(self.build_body(children=[iq]), verbose=False, timeout=10)
            print(f"✅ [5/5] Session OK - connect complete")

            return True

        except requests.Timeout as e:
            print(f"❌ Connection timeout: {e}")
            return False

        except Exception as e:
            print(f"❌ Connection error: {type(e).__name__}: {e}")
            return False
   
    def join_room(self, room_jid, nickname=None):
        """Join MUC room"""
        if not hasattr(self, '_joined_rooms'):
            self._joined_rooms = set()
        if room_jid in self._joined_rooms:
            print(f"ℹ️ Already joined: {room_jid}")
            return
       
        if self.connected_account is None:
            print("❌ No connected account")
            return
       
        if nickname is None:
            nickname = f"{self.connected_account['user_id']}#{self.connected_account['chat_username']}"
       
        self.rid += 1
        presence = ET.Element('presence', {
            'xmlns': 'jabber:client',
            'to': f'{room_jid}/{nickname}'
        })
        ET.SubElement(presence, 'x', {'xmlns': 'http://jabber.org/protocol/muc'})
       
        # Add user data with avatar and background
        x_data = ET.SubElement(presence, 'x', {'xmlns': 'klavogonki:userdata'})
        user = ET.SubElement(x_data, 'user')
        ET.SubElement(user, 'login').text = self.connected_account['chat_username']
        
        # Add avatar if available
        if self.connected_account.get('avatar'):
            ET.SubElement(user, 'avatar').text = self.connected_account['avatar']
        
        # Use effective background (custom if exists, otherwise server)
        bg = self._get_effective_background()
        if bg:
            ET.SubElement(user, 'background').text = bg
       
        try:
            response = self.send_request(self.build_body(children=[presence]), verbose=False, timeout=15)
           
            self.initial_roster_received = False
            self._process_response(response, is_initial_roster=True)
            self.initial_roster_received = True
            self._joined_rooms.add(room_jid)
            print(f"✅ Joined room")
           
        except requests.Timeout:
            print("❌ Join timeout")
        except Exception as e:
            print(f"❌ Join error: {e}")
   
    def send_message(self, body: str, to_jid: str = None, msg_type: str = 'groupchat', max_retries: int = 5):
        """Send message - supports both groupchat and private chat, with retry"""
        if not self.sid or not self.jid:
            print(f"❌ Send aborted: sid={bool(self.sid)}, jid={bool(self.jid)}")
            return False

        if self.connected_account is None:
            print(f"❌ Send aborted: no connected account")
            return False

        # Determine recipient
        if to_jid is None and msg_type == 'groupchat':
            rooms = self.account_manager.get_rooms()
            for room in rooms:
                if room.get('auto_join'):
                    to_jid = room['jid']
                    break

        if not to_jid:
            print(f"❌ Send aborted: no target JID")
            return False

        # Build message element once, reuse across retries
        def _build_payload():
            self.rid += 1
            message = ET.Element('message', {
                'xmlns': 'jabber:client',
                'to': to_jid,
                'type': msg_type,
                'from': self.jid
            })
            ET.SubElement(message, 'body').text = body

            x_data = ET.SubElement(message, 'x', {'xmlns': 'klavogonki:userdata'})
            user = ET.SubElement(x_data, 'user')
            ET.SubElement(user, 'login').text = self.connected_account['chat_username']

            if self.connected_account.get('avatar'):
                ET.SubElement(user, 'avatar').text = self.connected_account['avatar']

            bg = self._get_effective_background()
            if bg:
                ET.SubElement(user, 'background').text = bg

            return self.build_body(children=[message])

        for attempt in range(1, max_retries + 1):
            try:
                print(f"📤 Sending message attempt {attempt}/{max_retries} to {to_jid} (RID: {self.rid + 1})")
                payload = _build_payload()
                response = self.send_request(payload, verbose=False, timeout=15)
                print(f"✅ Message sent OK on attempt {attempt}")
                return True
            except Exception as e:
                print(f"❌ Send error attempt {attempt}/{max_retries}: {type(e).__name__}: {e}")
                if attempt < max_retries:
                    import time
                    wait = min(attempt * 2, 10)  # 2s, 4s, 6s, 8s, 10s between retries
                    print(f"🔁 Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    print(f"❌ All {max_retries} send attempts failed for message: {body[:50]}")
                    return False
   
    def _process_response(self, xml_text: str, is_initial_roster: bool = False):
        """Process response"""
        messages, presence_updates = MessageParser.parse(xml_text)
        
        # Override own background in received messages and presence
        effective_bg = self._get_effective_background()
        own_username = self.connected_account.get('chat_username') if self.connected_account else None
        
        if own_username and effective_bg:
            for collection in (messages, presence_updates):
                for item in collection:
                    if item.login == own_username:
                        item.background = effective_bg
       
        for msg in messages:
            try:
                msg.initial = bool(is_initial_roster)
            except Exception:
                msg.initial = False

            body = (msg.body or "").strip()
            # Skip only the anonymous room notification message
            if 'not anonymous' in body.lower():
                continue
           
            if self.message_callback:
                self.message_callback(msg)
       
        for pres in presence_updates:
            # Skip bot from userlist
            if pres.login == 'Клавобот':
                continue
           
            if pres.presence_type == 'available':
                existing_user = self.user_list.get(pres.from_jid)
                is_new_user = existing_user is None
               
                old_game_id = existing_user.game_id if existing_user else None
                new_game_id = pres.game_id
               
                self.user_list.add_or_update(
                    jid=pres.from_jid,
                    login=pres.login,
                    user_id=pres.user_id,
                    background=pres.background,
                    game_id=pres.game_id,
                    affiliation=pres.affiliation,
                    role=pres.role,
                    moderator=getattr(pres, 'moderator', False)
                )
               
                if not is_initial_roster and self.initial_roster_received:
                    login = pres.login if pres.login else pres.from_jid.split('/')[-1]
                   
                    if is_new_user:
                        print(f"➕ {login} joined")
                    elif old_game_id is None and new_game_id:
                        print(f"🚀 {login} → game #{new_game_id}")
                    elif old_game_id and new_game_id is None:
                        print(f"🏁 {login} left game")
                    elif old_game_id and new_game_id and old_game_id != new_game_id:
                        print(f"🚀 {login} → game #{new_game_id}")
               
                if self.presence_callback:
                    self.presence_callback(pres)
                   
            elif pres.presence_type == 'unavailable':
                existing_user = self.user_list.get(pres.from_jid)
                self.user_list.remove(pres.from_jid)
               
                if self.initial_roster_received and existing_user and not is_initial_roster:
                    login = pres.login if pres.login else pres.from_jid.split('/')[-1]
                    print(f"➖ {login} left")
               
                if self.presence_callback:
                    self.presence_callback(pres)
   
    def listen(self):
        """Listen for messages"""
        print("📡 Listening...\n")
        poll_count = 0
        try:
            while True:
                self.rid += 1
                poll_count += 1
                if poll_count % 10 == 1:
                    print(f"📡 Long-poll #{poll_count} (RID: {self.rid})")
                response = self.send_request(self.build_body(), verbose=False, timeout=70)
               
                root = self.parse_xml(response)
                if root is not None:
                    if root.get('type') == 'terminate':
                        print(f"\n⚠️ Server sent terminate after {poll_count} polls")
                        break
                   
                    self._process_response(response)
       
        except KeyboardInterrupt:
            print("\n👋 Bye")
        except requests.Timeout as e:
            print(f"\n❌ Listen timeout after {poll_count} polls: {e}")
        except Exception as e:
            print(f"\n❌ Listen error after {poll_count} polls: {type(e).__name__}: {e}")
   
    def disconnect(self):
        """Disconnect"""
        if self.sid:
            try:
                self.rid += 1
                self.send_request(self.build_body(type='terminate'), verbose=False, timeout=5)
            except:
                pass
            finally:
                self.sid = None
                self.jid = None
                self.connected_account = None
                if hasattr(self, 'session'):
                    self.session.close()