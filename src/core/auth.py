import requests
import re
import json


def authenticate(username: str, password: str) -> dict | None:
    try:
        session = requests.Session()
        
        # Get XSRF token
        xsrf_token = session.get("https://klavogonki.ru/login").cookies.get("XSRF-TOKEN")
        if not xsrf_token:
            return None
        
        # Login
        response = session.post(
            "https://klavogonki.ru/login",
            data={
                "redirect": "/gamelist/",
                "X-XSRF-TOKEN": xsrf_token,
                "login": username,
                "pass": password,
                "submit_login": "Войти",
            },
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Referer": "https://klavogonki.ru/login",
                "Origin": "https://klavogonki.ru",
            },
            allow_redirects=True
        )
        
        # Verify login success
        if not response.url.endswith("/gamelist/"):
            return None
        
        # Extract chatParams
        html = session.get(response.url).text
        match = re.search(r'chatParams:\s*(\{.+?\})\s*\}', html)
        
        if not match:
            return None
        
        data = json.loads(match.group(1))
        user = data.get("user", {})
        
        # Get avatar and clean up escaped slashes
        avatar = user.get("avatar", "")
        if avatar:
            avatar = avatar.replace("\\/", "/")
        
        # Get background color or default #808080 if not set
        background = user.get("background", "#808080")
        
        return {
            "id": user.get("id"),
            "login": user.get("login"),
            "pass": data.get("pass"),
            "avatar": avatar,
            "background": background
        }
        
    except Exception:
        return None