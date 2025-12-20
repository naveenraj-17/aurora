import requests
import json

url = "http://localhost:8000/api/settings"
payload = {"agent_name": "Test Agent", "model": "llama3"}
headers = {"Content-Type": "application/json"}

try:
    print(f"Sending POST to {url} with {payload}")
    response = requests.post(url, json=payload, headers=headers)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
except Exception as e:
    print(f"Error: {e}")
