import os
import platform
from pathlib import Path

def get_data_dir(subdir: str = "") -> Path:
    """Return the appropriate data directory path based on OS, with optional subdirectory."""
    system = platform.system()
    
    if system == "Windows":
        base_dir = Path.home() / "Desktop" / "KG_Chat_Data"
    elif system == "Darwin":
        base_dir = Path.home() / "Desktop" / "KG_Chat_Data"
    elif system == "Linux":
        if os.path.exists("/data/data/com.termux"):
            base_dir = Path.home() / "storage" / "shared" / "KG_Chat_Data"
        else:
            base_dir = Path.home() / "Desktop" / "KG_Chat_Data"
    else:
        base_dir = Path.home() / ".KG_Chat_Data"
    
    if subdir:
        base_dir = base_dir / subdir
    
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir