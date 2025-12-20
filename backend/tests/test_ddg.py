
from duckduckgo_search import DDGS
import json

def test_search(query):
    print(f"--- Searching for: '{query}' ---")
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
            for i, r in enumerate(results):
                print(f"{i+1}. {r['title']} - {r['href']}")
                print(f"   {r['body'][:100]}...")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_search("recent space exploration news")
    print("\n")
    test_search("space exploration news")
