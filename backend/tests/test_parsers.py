
import sys
import os
import asyncio
import json
from unittest.mock import MagicMock, patch

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.pdf_parser import call_tool as call_pdf_tool
from agents.xlsx_parser import call_tool as call_xlsx_tool

# Mock content for PDF (we can't easily mock pdfplumber object structure without a real file or complex mock)
# So for this test, we might just test the *download* logic and error handling if we don't have a real PDF.
# OR we can mock pdfplumber.open

async def test_pdf_parser():
    print("Testing PDF Parser...")
    
    # Mock requests.get
    with patch('requests.get') as mock_get:
        # Mock successful response
        mock_response = MagicMock()
        mock_response.content = b"%PDF-1.4..."
        mock_get.return_value = mock_response
        
        # Mock pdfplumber
        with patch('pdfplumber.open') as mock_pdf_open:
            mock_pdf = MagicMock()
            mock_page = MagicMock()
            mock_page.extract_text.return_value = "Sample PDF Text"
            mock_page.extract_tables.return_value = [[["Header1", "Header2"], ["Value1", "Value2"]]]
            mock_pdf.pages = [mock_page]
            mock_pdf_open.return_value.__enter__.return_value = mock_pdf
            
            result = await call_pdf_tool("parse_pdf", {"file_url": "http://example.com/test.pdf"})
            
            content = result[0].text
            print(f"PDF Output:\n{content}")
            
            assert "Sample PDF Text" in content
            assert "| Header1 | Header2 |" in content
            assert "| Value1 | Value2 |" in content
            print("✅ PDF Parser Test Passed")

async def test_xlsx_parser():
    print("\nTesting XLSX Parser...")
    
    # Mock requests.get
    with patch('requests.get') as mock_get:
        # Mock successful response
        mock_response = MagicMock()
        mock_response.content = b"fake xlsx content"
        mock_get.return_value = mock_response
        
        # Mock pandas.read_excel
        with patch('pandas.read_excel') as mock_read_excel:
            # Return a dict of DataFrames
            df_mock = MagicMock()
            df_mock.empty = False
            df_mock.to_markdown.return_value = "| Col1 | Col2 |\n|---|---|\n| Val1 | Val2 |"
            
            mock_read_excel.return_value = {"Sheet1": df_mock}
            
            result = await call_xlsx_tool("parse_xlsx", {"file_url": "http://example.com/test.xlsx"})
            
            content = result[0].text
            print(f"XLSX Output:\n{content}")
            
            assert "--- Sheet: Sheet1 ---" in content
            assert "| Col1 | Col2 |" in content
            print("✅ XLSX Parser Test Passed")

async def main():
    await test_pdf_parser()
    await test_xlsx_parser()

if __name__ == "__main__":
    asyncio.run(main())
