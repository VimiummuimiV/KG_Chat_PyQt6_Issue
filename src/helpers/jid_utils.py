"""JID helper utilities"""
from typing import Optional, Tuple


def extract_user_data_from_jid(jid: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Extract (user_id, login) from a JID resource.

    Returns a tuple (user_id, login) where either element may be None
    if not present in the provided JID.

    Expected resource examples:
      - room@domain/user_id#login  -> (user_id, login)
      - room@domain/login          -> (None, login)
      - None or unexpected format  -> (None, None)
    """
    if not jid:
        return None, None

    try:
        resource = jid.split('/')[-1]
        if '#' in resource:
            parts = resource.split('#')
            if len(parts) >= 2:
                return parts[0], parts[1].split('/')[0]
        # Fallback: resource may be login only
        if resource:
            return None, resource.split('/')[0]
    except Exception:
        pass

    return None, None
