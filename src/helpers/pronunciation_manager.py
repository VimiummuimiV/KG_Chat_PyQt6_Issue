"""Username Pronunciation Manager"""
import json
from pathlib import Path
from typing import Dict, Optional


class PronunciationManager:
    """Manages username pronunciation mappings for TTS"""
    
    def __init__(self, settings_path: Path):
        self.settings_path = settings_path / "pronunciation.json"
        self.mappings: Dict[str, str] = {}
        self.load()
    
    def load(self):
        """Load pronunciation mappings from JSON file"""
        if self.settings_path.exists():
            try:
                with open(self.settings_path, 'r', encoding='utf-8') as f:
                    self.mappings = json.load(f)
            except Exception as e:
                print(f"Error loading pronunciation mappings: {e}")
                self.mappings = {}
        else:
            self.mappings = {}
    
    def save(self):
        """Save pronunciation mappings to JSON file"""
        try:
            with open(self.settings_path, 'w', encoding='utf-8') as f:
                json.dump(self.mappings, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving pronunciation mappings: {e}")
    
    def add_mapping(self, original: str, pronunciation: str):
        """Add or update a pronunciation mapping"""
        if original and pronunciation:
            self.mappings[original] = pronunciation
            self.save()
    
    def remove_mapping(self, original: str):
        """Remove a pronunciation mapping"""
        if original in self.mappings:
            del self.mappings[original]
            self.save()
    
    def get_pronunciation(self, username: str) -> str:
        """Get pronunciation for username, return original if not mapped"""
        return self.mappings.get(username, username)
    
    def get_all_mappings(self) -> Dict[str, str]:
        """Get all pronunciation mappings"""
        return self.mappings.copy()
    
    def clear_all(self):
        """Clear all pronunciation mappings"""
        self.mappings.clear()
        self.save()
