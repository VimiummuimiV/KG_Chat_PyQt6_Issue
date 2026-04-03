"""Helper for /me action message formatting"""

def format_me_action(text: str, username: str) -> tuple[str, bool]:
    """Convert '/me action' to 'username action'."""
    if text and text.strip().startswith('/me '):
        action = text.strip()[4:]  # Remove '/me ' prefix
        return f"{username} {action}", True
    return text, False