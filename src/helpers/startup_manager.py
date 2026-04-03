"""
System startup manager for cross-platform auto-start functionality
Supports Windows, Linux (systemd/autostart), and macOS
"""
import sys
import os
from pathlib import Path
import platform

class StartupManager:
    """Manages application auto-start on system boot"""
    
    def __init__(self, app_name: str = "KG_Chat", app_path: str = None):
        self.app_name = app_name
        self.app_path = app_path or sys.executable
        self.system = platform.system()
        self.script_dir = Path(__file__).parent.parent
        self.main_script = self.script_dir / "main.py"
    
    def is_enabled(self) -> bool:
        """Check if auto-start is currently enabled"""
        try:
            if self.system == "Windows":
                import winreg
                key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
                try:
                    winreg.QueryValueEx(key, self.app_name)
                    winreg.CloseKey(key)
                    return True
                except FileNotFoundError:
                    winreg.CloseKey(key)
                    return False
            elif self.system == "Linux":
                autostart_dir = Path.home() / ".config" / "autostart"
                desktop_file = autostart_dir / f"{self.app_name.replace(' ', '-').lower()}.desktop"
                return desktop_file.exists()
            elif self.system == "Darwin":  # macOS
                launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
                plist_name = f"com.{self.app_name.replace(' ', '-').lower()}.plist"
                plist_path = launch_agents_dir / plist_name
                return plist_path.exists()
            return False
        except Exception as e:
            print(f"Error checking startup status: {e}")
            return False
    
    def enable(self) -> bool:
        """Enable auto-start on system boot"""
        try:
            if self.system == "Windows":
                import winreg
                key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
                python_exe = sys.executable
                if python_exe.endswith("python.exe"):
                    python_exe = python_exe.replace("python.exe", "pythonw.exe")
                command = f'"{python_exe}" "{self.main_script}"'
                winreg.SetValueEx(key, self.app_name, 0, winreg.REG_SZ, command)
                winreg.CloseKey(key)
                return True
            elif self.system == "Linux":
                autostart_dir = Path.home() / ".config" / "autostart"
                autostart_dir.mkdir(parents=True, exist_ok=True)
                desktop_file = autostart_dir / f"{self.app_name.replace(' ', '-').lower()}.desktop"
                content = f"""[Desktop Entry]
                Type=Application
                Name={self.app_name}
                Exec={sys.executable} {self.main_script}
                Hidden=false
                NoDisplay=false
                X-GNOME-Autostart-enabled=true
                Comment=Start {self.app_name} on login
                """
                desktop_file.write_text(content)
                desktop_file.chmod(0o755)
                return True
            elif self.system == "Darwin":  # macOS
                launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
                launch_agents_dir.mkdir(parents=True, exist_ok=True)
                plist_name = f"com.{self.app_name.replace(' ', '-').lower()}.plist"
                plist_path = launch_agents_dir / plist_name
                content = f"""<?xml version="1.0" encoding="UTF-8"?>
                <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
                <plist version="1.0">
                <dict>
                    <key>Label</key>
                    <string>com.{self.app_name.replace(' ', '-').lower()}</string>
                    <key>ProgramArguments</key>
                    <array>
                        <string>{sys.executable}</string>
                        <string>{self.main_script}</string>
                    </array>
                    <key>RunAtLoad</key>
                    <true/>
                    <key>KeepAlive</key>
                    <false/>
                </dict>
                </plist>
                """
                plist_path.write_text(content)
                return True
            return False
        except Exception as e:
            print(f"Error enabling startup: {e}")
            return False
    
    def disable(self) -> bool:
        """Disable auto-start on system boot"""
        try:
            if self.system == "Windows":
                import winreg
                key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
                try:
                    winreg.DeleteValue(key, self.app_name)
                except FileNotFoundError:
                    pass  # Already disabled
                winreg.CloseKey(key)
                return True
            elif self.system == "Linux":
                autostart_dir = Path.home() / ".config" / "autostart"
                desktop_file = autostart_dir / f"{self.app_name.replace(' ', '-').lower()}.desktop"
                if desktop_file.exists():
                    desktop_file.unlink()
                return True
            elif self.system == "Darwin":  # macOS
                launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
                plist_name = f"com.{self.app_name.replace(' ', '-').lower()}.plist"
                plist_path = launch_agents_dir / plist_name
                if plist_path.exists():
                    plist_path.unlink()
                return True
            return False
        except Exception as e:
            print(f"Error disabling startup: {e}")
            return False
