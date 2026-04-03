import re
from typing import List, Tuple

def parse_mentions(text: str, my_username: str) -> List[Tuple[bool, str]]:
    """
    Parse text and identify mentions of my_username.
    
    Args:
        text: The text to process
        my_username: The username to highlight (case-insensitive)
    
    Returns:
        List of (is_mention: bool, text: str) tuples
    """
    if not my_username or not text:
        return [(False, text)]
    
    # Create pattern to match username as whole word (case-insensitive)
    pattern = r'\b' + re.escape(my_username.lower()) + r'\b'
    
    segments = []
    last_end = 0
    
    for match in re.finditer(pattern, text, re.IGNORECASE):
        # Add text before mention
        if match.start() > last_end:
            segments.append((False, text[last_end:match.start()]))
        
        # Add mention
        segments.append((True, text[match.start():match.end()]))
        last_end = match.end()
    
    # Add remaining text
    if last_end < len(text):
        segments.append((False, text[last_end:]))
    
    return segments if segments else [(False, text)]