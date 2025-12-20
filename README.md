# MCP Email Chatbot

A local AI agent that can read your emails using Model Context Protocol (MCP) and Ollama.

## Prerequisites
- **Ollama** running locally at `http://localhost:11434` with `llama3.2` (or another model).
- **Python 3.10+**
- **Node.js & npm**

## Project Structure
- `backend/`: FastAPI server + MCP Server (Python)
- `frontend/`: Next.js Chat Interface (TypeScript)

## Running the Application

### 1. Start Ollama
Ensure Ollama is running:
```bash
ollama serve
# In another terminal, pull the model if you haven't:
# ollama pull llama3.2
```

### 2. Start the Backend
The backend orchestrates the MCP server and the LLM.
```bash
cd backend
source venv/bin/activate
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```
You should see: `Connected to MCP Server` and `Available tools: ['list_emails', 'read_email']`.

### 3. Start the Frontend
```bash
cd frontend
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) in your browser.

## Usage
- Ask "Show me my latest emails" to see the mock emails.
- Ask "Read the email from Boss" to see the full content.

## Mock Data
The emails are mocked in `backend/mock_data.py`. You can edit this file to add more test cases.
