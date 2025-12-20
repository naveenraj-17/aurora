
import asyncio
from playwright.async_api import async_playwright
import os
import sys

async def main():
    print(f"DISPLAY env var: '{os.environ.get('DISPLAY')}'")
    async with async_playwright() as p:
        print("Attempting Headed Launch...")
        try:
            browser = await p.chromium.launch(headless=False)
            print("SUCCESS: Headed Browser Launched!")
            await browser.close()
        except Exception as e:
            print(f"FAILURE: Headed Launch failed: {e}")
            
        print("Attempting Headless Launch...")
        try:
            browser = await p.chromium.launch(headless=True)
            print("SUCCESS: Headless Browser Launched!")
            await browser.close()
        except Exception as e:
            print(f"FAILURE: Headless Launch failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
