
import os
import json

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "settings.json")
CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "credentials.json")
TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "token.json")

def load_settings():
    default_settings = {
        "agent_name": "System Agent", 
        "model": "mistral",
        "mode": "local",
        "openai_key": "",
        "anthropic_key": "",
        "gemini_key": "",
        "show_browser": False
    }
    
    if not os.path.exists(SETTINGS_FILE):
        return default_settings
    
    try:
        with open(SETTINGS_FILE, 'r') as f:
            data = json.load(f)
            # Merge defaults
            return {**default_settings, **data}
    except Exception as e:
        print(f"DEBUG: Error loading settings: {e}")
        return default_settings
