
import requests
import time
import sys

BASE_URL = "http://localhost:8000"

def chat(message):
    print(f"\nUser: {message}")
    try:
        resp = requests.post(f"{BASE_URL}/chat", json={"message": message}, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        print(f"Assistant: {data['response']}")
        if data.get('data'):
            print(f"Data: {data['data']}")
        return data['response']
    except Exception as e:
        print(f"Error: {e}")
        return ""

def verify_memory():
    # 1. Wait for server (simple poll)
    print("Waiting for server...")
    for _ in range(10):
        try:
            requests.get(f"{BASE_URL}/api/status")
            break
        except:
            time.sleep(1)
            
    # 2. Turn 1: Establish Context
    # We pretend to fetch an email. Since we can't easily mock the email tool without more work, 
    # we'll use a simpler proxy: "Remember that the secret code is 12345."
    # If the agent puts this in history, the next turn should know it.
    
    r1 = chat("The secret code is 998877. Don't forget it.")
    
    # 3. Turn 2: Recall Context
    r2 = chat("What is the secret code I just told you?")
    
    if "998877" in r2:
        print("\nSUCCESS: Context retained across turns.")
    else:
        print("\nFAILURE: Context lost.")

if __name__ == "__main__":
    verify_memory()
