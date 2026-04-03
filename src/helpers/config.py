"""Configuration manager"""
import json


class Config:
    def __init__(self, path):
        self.path = path
        self.data = self.load()
    
    def load(self):
        with open(self.path, 'r') as f:
            return json.load(f)
    
    def save(self):
        with open(self.path, 'w') as f:
            json.dump(self.data, f, indent=2)
    
    def get(self, *keys):
        value = self.data
        for key in keys:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        return value
    
    def set(self, *keys, value):
        d = self.data
        for key in keys[:-1]:
            d = d.setdefault(key, {})
        d[keys[-1]] = value
        self.save()