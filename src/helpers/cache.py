"""Centralized cache system for avatars and user data"""
import re, json, threading
from pathlib import Path
from typing import Optional, Dict, Callable
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtGui import QPixmap
from helpers.load import fetch_avatar_bytes, load_avatar_from_disk
from helpers.data import get_data_dir
from helpers.color_contrast import optimize_color_contrast


class CacheManager:
    """Thread-safe singleton cache manager for avatars and user data.

    Persistent store: settings/data.json  —  keyed by user_id (permanent).
    Schema per entry: { login, background?, light?, dark? }

    Rules on upsert (update_user):
      • Same user_id, new login   → rename; stale reverse-index entry removed.
      • Same user_id, new bg      → recompute both-theme colors.
      • No change at all          → no-op (no disk write).
    """

    _instance = None
    _lock = threading.Lock()
    _BG_HEX = {"dark": "#1E1E1E", "light": "#FFFFFF"}

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._avatar_stamps: Dict[str, str] = {}  # user_id → updated timestamp
        self._data: Dict[str, Dict] = {}          # user_id → {login, background?, light?, dark?}
        self._avatar_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cache_avatar_loader")
        self._cache_lock = threading.Lock()
        self._data_path = Path(__file__).parent.parent / "settings" / "data.json"
        self._initialized = True
        self._load_data()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load_data(self) -> None:
        try:
            raw = json.loads(self._data_path.read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                for uid, entry in raw.items():
                    if isinstance(entry, dict) and entry.get('login'):
                        self._data[str(uid)] = entry
        except Exception:
            pass

    def _save_data(self, snapshot: dict) -> None:
        try:
            lines = ',\n'.join(
                f'  {json.dumps(uid)}: {json.dumps(entry, ensure_ascii=False)}'
                for uid, entry in snapshot.items()
            )
            self._data_path.write_text(f'{{\n{lines}\n}}', encoding='utf-8')
        except Exception as e:
            print(f"Error saving data.json: {e}")

    # ── User data API ─────────────────────────────────────────────────────────

    def update_user(self, user_id: str, login: str, background: str = None) -> None:
        """Upsert user entry. Corrects stale login, recomputes colors if background changed."""
        if not user_id or not login:
            return
        user_id, login = str(user_id), str(login)
        with self._cache_lock:
            entry = dict(self._data.get(user_id, {}))
            changed = False

            if entry.get('login') != login:
                entry['login'] = login
                changed = True

            if background and entry.get('background') != background:
                entry['background'] = background
                entry['light'] = optimize_color_contrast(background, self._BG_HEX['light'], 4.5)
                entry['dark']  = optimize_color_contrast(background, self._BG_HEX['dark'],  4.5)
                changed = True

            if not changed:
                return
            self._data[user_id] = entry
            snapshot = self._data.copy()
        self._avatar_executor.submit(self._save_data, snapshot)

    def get_user_id(self, login: str) -> Optional[str]:
        with self._cache_lock:
            for uid, entry in self._data.items():
                if entry.get('login') == login:
                    return uid
        return None

    def get_username_color(self, login: str, is_dark: bool) -> str:
        """Return precomputed color for login, or theme default if unknown."""
        with self._cache_lock:
            for entry in self._data.values():
                if entry.get('login') == login:
                    if entry.get('dark'):
                        return entry['dark'] if is_dark else entry['light']
                    break
        return '#CCCCCC' if is_dark else '#666666'

    def has_user(self, user_id: str) -> bool:
        """Return True if user_id is present in the persistent data store."""
        return bool(user_id) and user_id in self._data

    # ── Avatar API ────────────────────────────────────────────────────────────

    def _dir(self):
        return get_data_dir("avatars")

    def _path(self, user_id, updated):
        return self._dir() / f"{user_id}_{updated}.png"

    @staticmethod
    def _parse_stamp(avatar_path):
        m = re.search(r'updated=(\d+)', avatar_path or '')
        return m.group(1) if m else None

    def _fetch_and_save(self, user_id: str, path, callback: Callable = None) -> None:
        data = fetch_avatar_bytes(user_id)
        if data:
            path.write_bytes(data)
            for f in self._dir().glob(f"{user_id}_*.png"):
                if f != path: f.unlink(missing_ok=True)
            if callback:
                px = load_avatar_from_disk(path)
                if px: callback(user_id, px)

    def get_avatar(self, user_id: str) -> Optional[QPixmap]:
        upd = self._avatar_stamps.get(user_id)
        return load_avatar_from_disk(self._path(user_id, upd)) if upd else None

    def ensure_avatar(self, user_id: str, avatar_path: str, callback: Callable = None) -> None:
        updated = self._parse_stamp(avatar_path)
        if not updated or not user_id:
            return
        with self._cache_lock:
            prev = self._avatar_stamps.get(user_id)
            self._avatar_stamps[user_id] = updated

        def _work():
            path = self._path(user_id, updated)
            if path.exists():
                if callback and prev != updated:
                    px = load_avatar_from_disk(path)
                    if px: callback(user_id, px)
            else:
                self._fetch_and_save(user_id, path, callback)

        self._avatar_executor.submit(_work)

    def load_avatar_async(self, user_id: str, callback: Callable, timeout: int = 2) -> None:
        def _work():
            upd = self._avatar_stamps.get(user_id)
            if upd:
                px = load_avatar_from_disk(self._path(user_id, upd))
                if px: callback(user_id, px)
                return
            for f in self._dir().glob(f"{user_id}_*.png"):
                px = load_avatar_from_disk(f)
                if px:
                    with self._cache_lock:
                        self._avatar_stamps[user_id] = f.stem.split("_", 1)[1]
                    callback(user_id, px); return
            self._fetch_and_save(user_id, self._dir() / f"{user_id}_0.png", callback)

        self._avatar_executor.submit(_work)

    def clear_avatars(self) -> None:
        with self._cache_lock: self._avatar_stamps.clear()

    def remove_avatar(self, user_id: str) -> None:
        with self._cache_lock: self._avatar_stamps.pop(user_id, None)
        for f in self._dir().glob(f"{user_id}_*.png"):
            f.unlink(missing_ok=True)

    # ── Misc ──────────────────────────────────────────────────────────────────

    def clear_all(self) -> None:
        self.clear_avatars()

    def shutdown(self) -> None:
        if hasattr(self, '_avatar_executor'):
            self._avatar_executor.shutdown(wait=False)


_cache_manager = CacheManager()

def get_cache() -> CacheManager:
    return _cache_manager