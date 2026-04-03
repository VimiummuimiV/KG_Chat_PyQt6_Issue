"""API data helpers for fetching user information"""
import requests
from typing import Optional, Dict, List, Any, Set
from datetime import datetime


def extract_hex_color(color_str: str) -> Optional[str]:
    """Extract valid hex color (#RRGGBB) from string"""
    if not isinstance(color_str, str):
        return None
    import re
    match = re.match(r'^#([0-9a-fA-F]{6})\b', color_str)
    return f"#{match.group(1)}" if match else None

def format_registered_date(registered: Dict) -> Optional[str]:
    """Convert Unix timestamp to YYYY-MM-DD format"""
    if not registered or 'sec' not in registered:
        return None
    try:
        date = datetime.fromtimestamp(registered['sec'])
        return date.strftime('%Y-%m-%d')
    except:
        return None

def convert_to_timestamp(sec: int, usec: int) -> Optional[str]:
    """Convert sec and usec to timestamp"""
    if sec is not None and usec is not None:
        return str(sec) + str(usec // 1000)
    return None

def format_username_history(history: List[Dict]) -> List[tuple]:
    """Format username history with timestamps (reversed - newest first)
    Returns list of tuples: (username, date_string) or (username, None)"""
    formatted = []
    
    # Reverse the history so newest changes come first
    for entry in reversed(history):
        username = entry.get('login', '')
        until = entry.get('until', {})
        
        sec = until.get('sec')
        usec = until.get('usec')
        
        if sec and usec is not None:
            # sec is already Unix timestamp in seconds, usec is microseconds
            # Just use sec directly for the date
            try:
                date_str = datetime.fromtimestamp(sec).strftime('%d.%m.%Y')
                formatted.append((username, date_str))
            except (ValueError, OSError):
                formatted.append((username, None))
        else:
            formatted.append((username, None))
    
    return formatted

def fetch_json(url: str, timeout: int = 5) -> Dict:
    """Fetch JSON from URL with validation"""
    response = requests.get(url, timeout=timeout)
    if not response.ok:
        raise Exception(f"Failed to fetch {url}")
    return response.json()

def get_exact_user_id_by_name(username: str) -> Optional[int]:
    """Get exact user ID by username via search API"""
    try:
        search_api_url = f"https://klavogonki.ru/api/profile/search-users?query={username}"
        search_results = fetch_json(search_api_url)
        
        if not search_results.get('all'):
            return None
        
        for user in search_results['all']:
            if user.get('login') == username:
                return user.get('id')
        
        return None
    except Exception as e:
        print(f"Error getting user ID: {e}")
        return None

def get_all_user_ids_by_name(username: str) -> List[int]:
    """Get all user IDs matching username via search API"""
    try:
        search_api_url = f"https://klavogonki.ru/api/profile/search-users?query={username}"
        search_results = fetch_json(search_api_url)
        
        if not search_results.get('all'):
            return []
        
        return [user['id'] for user in search_results['all'] if 'id' in user]
    except Exception as e:
        print(f"Error getting user IDs: {e}")
        return []

def get_user_summary_by_id(user_id: int) -> Optional[Dict]:
    """Get user summary data by ID"""
    try:
        profile_api_url = f"https://klavogonki.ru/api/profile/get-summary?id={user_id}"
        summary = fetch_json(profile_api_url)
        return summary
    except Exception as e:
        print(f"Error getting user summary: {e}")
        raise

def get_user_index_data_by_id(user_id: int) -> Optional[Dict]:
    """Get user index data by ID"""
    try:
        index_api_url = f"https://klavogonki.ru/api/profile/get-index-data?userId={user_id}"
        index_data = fetch_json(index_api_url)
        return index_data
    except Exception as e:
        print(f"Error getting user index data: {e}")
        raise


# Data types that require the index-data API
INDEX_DATA_TYPES: Set[str] = {
    'bio', 'bioText', 'bioOldText', 'bioEditedDate', 'stats', 'registered',
    'achievesCount', 'totalRaces', 'bestSpeed', 'ratingLevel', 'friendsCount',
    'vocsCount', 'carsCount', 'achieves', 'allIndexData'
}

# Data types that require the summary API
SUMMARY_DATA_TYPES: Set[str] = {
    'usernamesHistory', 'currentLogin', 'userId', 'level', 'status', 'title',
    'car', 'carColor', 'isOnline', 'avatar', 'avatarTimestamp', 'blocked', 
    'isFriend', 'publicPrefs', 'allUserData'
}


def get_data_by_name(username: str, data_type: str) -> Any:
    """
    MAIN FUNCTION: Get specific data by username - automatically chooses correct API
    
    Args:
        username: Username to look up
        data_type: Type of data to retrieve (see INDEX_DATA_TYPES and SUMMARY_DATA_TYPES)
    
    Returns:
        Requested data or None if not found
    """
    try:
        user_id = get_exact_user_id_by_name(username)
        if not user_id:
            raise Exception(f'User with username "{username}" not found')
        
        return get_data_by_id(user_id, data_type)
    except Exception as e:
        print(f"Error getting {data_type} for user {username}: {e}")
        return None

def get_data_by_id(user_id: int, data_type: str) -> Any:
    """
    MAIN FUNCTION: Get specific data by user ID - automatically chooses correct API
    
    Args:
        user_id: User ID to look up
        data_type: Type of data to retrieve
    
    Returns:
        Requested data or None if not found
    """
    try:
        if data_type in INDEX_DATA_TYPES:
            index_data = get_user_index_data_by_id(user_id)
            return extract_data(index_data, data_type, 'index')
        elif data_type in SUMMARY_DATA_TYPES:
            summary = get_user_summary_by_id(user_id)
            return extract_data(summary, data_type, 'summary')
        else:
            raise Exception(f'Unknown data type: {data_type}')
    except Exception as e:
        print(f"Error getting {data_type} for user ID {user_id}: {e}")
        return None

def extract_data(data: Dict, data_type: str, api_type: str) -> Any:
    """
    Universal data extractor function - handles both API responses
    
    Args:
        data: API response data
        data_type: Type of data to extract
        api_type: Either 'summary' or 'index'
    
    Returns:
        Extracted data or None
    """
    if not data:
        return None
    
    if api_type == 'summary':
        # Merge user data with response data
        user_data = {**(data.get('user') or {}), **data}
        
        # Switch-case equivalent using dictionary mapping
        extractors = {
            'usernamesHistory': lambda: (
                [item.get('login') for item in user_data.get('history', [])]
                if isinstance(user_data.get('history'), list)
                else []
            ),
            'currentLogin': lambda: user_data.get('login'),
            'userId': lambda: user_data.get('id'),
            'level': lambda: user_data.get('level'),
            'status': lambda: user_data.get('status'),
            'title': lambda: (
                user_data.get('title') or 
                (user_data.get('status', {}).get('title') if isinstance(user_data.get('status'), dict) else None)
            ),
            'car': lambda: user_data.get('car'),
            'carColor': lambda: (
                extract_hex_color(user_data['car']['color']) 
                if user_data.get('car') and isinstance(user_data['car'], dict) and 'color' in user_data['car']
                else None
            ),
            'isOnline': lambda: user_data.get('is_online', False),
            'avatar': lambda: user_data.get('avatar'),
            'avatarTimestamp': lambda: (
                convert_to_timestamp(avatar['sec'], avatar['usec'])
                if (avatar := user_data.get('avatar'))
                else None
            ),
            'blocked': lambda: user_data.get('blocked'),
            'isFriend': lambda: user_data.get('is_friend', False),
            'publicPrefs': lambda: user_data.get('public_prefs'),
            'allUserData': lambda: user_data,
        }
        
        extractor = extractors.get(data_type)
        return extractor() if extractor else None
    
    elif api_type == 'index':
        # Switch-case equivalent using dictionary mapping
        extractors = {
            'bio': lambda: data.get('bio'),
            'bioText': lambda: data.get('bio', {}).get('text') if isinstance(data.get('bio'), dict) else None,
            'bioOldText': lambda: data.get('bio', {}).get('old_text') if isinstance(data.get('bio'), dict) else None,
            'bioEditedDate': lambda: (
                convert_to_timestamp(edited_date['sec'], edited_date['usec'])
                if (edited_date := data.get('bio', {}).get('edited_date'))
                else None
            ),
            'stats': lambda: data.get('stats'),
            'registered': lambda: format_registered_date(data.get('stats', {}).get('registered')) if data.get('stats') else None,
            'achievesCount': lambda: data.get('stats', {}).get('achieves_cnt') if data.get('stats') else None,
            'totalRaces': lambda: data.get('stats', {}).get('total_num_races') if data.get('stats') else None,
            'bestSpeed': lambda: data.get('stats', {}).get('best_speed') if data.get('stats') else None,
            'ratingLevel': lambda: data.get('stats', {}).get('rating_level') if data.get('stats') else None,
            'friendsCount': lambda: data.get('stats', {}).get('friends_cnt') if data.get('stats') else None,
            'vocsCount': lambda: data.get('stats', {}).get('vocs_cnt') if data.get('stats') else None,
            'carsCount': lambda: data.get('stats', {}).get('cars_cnt') if data.get('stats') else None,
            'achieves': lambda: data.get('achieves'),
            'allIndexData': lambda: data,
        }
        
        extractor = extractors.get(data_type)
        return extractor() if extractor else None
    
    return None

# Convenience helper functions (used by parser)
def get_usernames_history(username: str) -> List[str]:
    """Get username history for a user"""
    history = get_data_by_name(username, 'usernamesHistory')
    return history if isinstance(history, list) else []

def get_registration_date(username: str) -> Optional[str]:
    """Get user registration date (YYYY-MM-DD)"""
    return get_data_by_name(username, 'registered')