import requests
import json

url = "http://localhost:8000/api/settings"
payload = {"agent_name": "Jarvis", "model": "llama3:latest"}
headers = {"Content-Type": "application/json"}

try:
    response = requests.post(url, json=payload, headers=headers)
    print(f"Restored Settings: {response.text}")
except Exception as e:
    print(f"Error: {e}")
