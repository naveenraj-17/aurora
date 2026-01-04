'use client';

import { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, ChevronRight, Settings, Terminal, Sun, Moon } from 'lucide-react';

import { SettingsModal } from '@/components/SettingsModal';
import { AuthPrompt } from '@/components/AuthPrompt';
import { EmailList } from '@/components/EmailList';
import { EmailRenderer } from '@/components/EmailRenderer';
import { DriveList } from '@/components/DriveList';
import { EventList } from '@/components/EventList';
import { LocalFileList } from '@/components/LocalFileList';
import { EmailComposer } from '@/components/EmailComposer';

import { renderTextContent, cn } from '@/lib/utils';
import { Message, SystemStatus } from '@/types';

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', content: 'System Internal v1.0. Ready for input.' }
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [agentName, setAgentName] = useState('Loading...');
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [showBrowser, setShowBrowser] = useState(false);
  const [credentials, setCredentials] = useState(null);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Helper to refresh status
  const refreshSystemStatus = () => {
    fetch('/api/status').then(r => r.json()).then(d => setSystemStatus(d)).catch(console.error);
  };

  // Initial Data Fetch
  useEffect(() => {
    // 1. Get Agent Name
    fetch('/api/settings').then(r => r.json()).then(d => {
      setAgentName(d.agent_name || 'System Agent');
      setShowBrowser(d.show_browser === true);
    }).catch(() => setAgentName('Offline'));
    // 2. Get Credentials (masked)
    fetch('/api/config').then(r => r.json()).then(d => setCredentials(d)).catch(console.error);
    // 3. Get Status
    refreshSystemStatus();
  }, []);

  // State to track if a draft has been sent
  const [sentDrafts, setSentDrafts] = useState<Set<number>>(new Set());

  const handleSendEmail = (index: number, to: string, cc: string, bcc: string, subject: string, body: string) => {
    setSentDrafts(prev => new Set(prev).add(index));
    let command = `Confirmed. Please immediately execute the send_email tool. To: "${to}", Subject: "${subject}", Body: "${body}"`;
    if (cc) command += `, Cc: "${cc}"`;
    if (bcc) command += `, Bcc: "${bcc}"`;

    // Send directly
    processMessage(command);
  };

  const handleSwitchAgent = async (agentId: string) => {
    try {
      const res = await fetch('/api/agents/active', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId })
      });
      if (res.ok) {
        // Refresh status immediately
        const statusRes = await fetch('/api/status');
        const statusData = await statusRes.json();
        setSystemStatus(statusData);
        if (statusData.agents[agentId]) {
          setAgentName(statusData.agents[agentId].name);
        }

        // Optional: Add a system message saying "Switched to X"
        setMessages(prev => [...prev, { role: 'assistant', content: `System: Switched active agent to ${statusData.agents[agentId]?.name || agentId}. Ready.` }]);
      }
    } catch (e) {
      console.error("Failed to switch agent", e);
    }
  };

  const handleUpdateSettings = async (name: string, model: string, mode: string, keys: any) => {
    await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agent_name: name,
        model: model,
        mode: mode,
        openai_key: keys.openai_key,
        anthropic_key: keys.anthropic_key,
        gemini_key: keys.gemini_key,
        show_browser: keys.show_browser
      })
    });
    setAgentName(name);
    setShowBrowser(keys.show_browser);
    // Refresh status to update header
    fetch('/api/status').then(r => r.json()).then(d => setSystemStatus(d));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage = input.trim();
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);

    await processMessage(userMessage);
  };

  const handleEmailClick = async (emailId: string) => {
    const userMessage = `Read email ${emailId}`;
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    await processMessage(userMessage);
  };

  const handleSummarizeFile = async (path: string) => {
    const userMessage = `Summarize the content of ${path}`;
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    await processMessage(userMessage);
  };

  const handleLocateFile = async (path: string) => {
    const userMessage = `Locate file ${path}`;
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    await processMessage(userMessage);
  };

  const handleOpenFile = async (path: string) => {
    setMessages(prev => [...prev, { role: 'user', content: `Open file: ${path}` }]);
    await processMessage(`Open file: ${path}`);
  };

  // Refactor duplicate fetch logic into helper
  const processMessage = async (content: string) => {
    setIsLoading(true);
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: content }),
      });
      const data = await res.json();
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.response,
        intent: data.intent,
        data: data.data
      }]);
    } catch (err) {
      setMessages(prev => [...prev, { role: 'assistant', content: "Error communicating with agent." }]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <main className={cn("flex h-screen bg-black text-white font-mono overflow-hidden", theme === 'light' ? 'light-mode' : '')}>
      {/* Settings Modal */}
      {/* Settings Modal */}
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => {
          setIsSettingsOpen(false);
          refreshSystemStatus();
        }}
        onSave={handleUpdateSettings}
        credentials={credentials}
        showBrowser={showBrowser}
        onToggleBrowser={setShowBrowser}
      />

      <div className="flex-1 flex flex-col w-full border-x border-zinc-800 shadow-2xl relative">
        {/* Header */}
        <header className="h-14 border-b border-zinc-800 bg-zinc-950 px-6 shrink-0 z-10">
          <div className='w-full md:max-w-5xl mx-auto h-full flex items-center justify-between'>
            <div className="flex items-center gap-3">
              <div className="h-3 w-3 bg-green-500 rounded-full animate-pulse shadow-[0_0_10px_#22c55e]"></div>
              <h1 className="text-sm font-bold tracking-widest uppercase text-zinc-300">
                {agentName} <span className="text-zinc-600">-</span> <span className="text-zinc-500">Ask Anything</span>
              </h1>
            </div>
            <div className="flex items-center">
              {/* Mode & Model Info */}
              <div className="hidden md:flex items-center gap-4 text-[10px] text-zinc-500 uppercase tracking-wider border-r border-zinc-800 pr-4">
                <div className="flex items-center gap-2">
                  <span className="text-zinc-600">Mode:</span>
                  <span className={cn("font-bold", systemStatus?.mode === 'cloud' ? "text-blue-400" : "text-green-400")}>
                    {systemStatus?.mode || 'Loading...'}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-zinc-600">Model:</span>
                  <span className="text-zinc-300">{systemStatus?.model || 'Loading...'}</span>
                </div>
              </div>

              {/* Status Indicators */}
              {/* Agents Hover Status */}
              <div className="group relative flex items-center gap-2 cursor-pointer border-r border-zinc-800 pl-4 pr-4 hover:bg-zinc-900 transition-colors">
                <span className="text-[10px] font-bold text-zinc-500 tracking-widest uppercase group-hover:text-zinc-300 transition-colors">AGENTS</span>

                {/* Dropdown on Hover */}
                <div className="absolute right-0 top-full mt-0 w-64 bg-zinc-950 border border-zinc-800 p-2 shadow-2xl opacity-0 translate-y-2 group-hover:opacity-100 group-hover:translate-y-0 transition-all pointer-events-none group-hover:pointer-events-auto z-50">
                  <div className="space-y-1">
                    {systemStatus?.agents && Object.entries(systemStatus.agents).map(([id, info]) => {
                      const isActive = systemStatus.active_agent_id === id;
                      // Handle legacy string vs new object structure if backend update lags (safety)
                      const name = typeof info === 'string' ? id : info.name;
                      const status = typeof info === 'string' ? info : info.status;

                      return (
                        <button
                          key={id}
                          onClick={() => handleSwitchAgent(id)}
                          className={cn(
                            "nav-button w-full flex items-center justify-between px-3 py-2 text-[10px] uppercase tracking-wider text-left border border-transparent hover:border-zinc-700 transition-all",
                            isActive ? "bg-zinc-900 text-white border-zinc-800" : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-900/50"
                          )}>
                          <div className="flex items-center gap-2">
                            <div className={cn("h-1.5 w-1.5 rounded-full", status === 'online' ? "bg-green-500 shadow-[0_0_5px_#22c55e]" : "bg-red-500")}></div>
                            <span className="truncate max-w-[120px]">{name}</span>
                          </div>
                          {isActive && <div className="h-1.5 w-1.5 bg-white rounded-full animate-pulse"></div>}
                        </button>
                      );
                    })}
                    {(!systemStatus?.agents || Object.keys(systemStatus.agents).length === 0) && (
                      <div className="text-[10px] text-zinc-600 italic px-3 py-2">No agents detected.</div>
                    )}
                  </div>
                </div>
              </div>

              <button
                onClick={() => setTheme(prev => prev === 'dark' ? 'light' : 'dark')}
                className="p-2 ml-2 hover:bg-zinc-900 rounded text-zinc-400 hover:text-white transition-colors"
                title={theme === 'dark' ? "Switch to Light Mode" : "Switch to Dark Mode"}
              >
                {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              </button>

              <button
                onClick={() => setIsSettingsOpen(true)}
                className="p-2 ml-2 hover:bg-zinc-900 rounded text-zinc-400 hover:text-white transition-colors"
              >
                <Settings className="h-4 w-4" />
              </button>
            </div>
          </div>

        </header>

        {/* Chat Area */}
        <div className="flex-1 overflow-y-auto p-6 scroll-smooth custom-scrollbar pb-32">
          <div className="w-full md:max-w-5xl mx-auto space-y-6">
            {messages.map((msg, idx) => (
              <div key={idx} className={cn(
                "flex gap-4 max-w-3xl",
                msg.role === 'user' ? "ml-auto flex-row-reverse" : ""
              )}>
                <div className={cn(
                  "h-8 w-8 shrink-0 flex items-center justify-center border",
                  msg.role === 'user' ? "bg-white border-white text-black" : "bg-black border-zinc-700 text-zinc-400"
                )}>
                  {msg.role === 'user' ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
                </div>

                <div className="flex flex-col flex-1 min-w-0 gap-2">
                  <div className={cn(
                    "p-4 text-sm leading-relaxed border relative",
                    msg.role === 'user'
                      ? "bg-zinc-900 border-zinc-800 text-zinc-100 self-end max-w-[80%]"
                      : "bg-zinc-900/50 border-zinc-800 text-zinc-100 self-start max-w-full"
                  )}>
                    {/* Intent Indicator for Assistant */}
                    {msg.role === 'assistant' && msg.intent && (
                      <div className="absolute -top-3 left-2 bg-zinc-950 border border-zinc-800 px-2 py-0.5 text-[8px] uppercase tracking-wider text-zinc-500">
                        {msg.intent} Operation
                      </div>
                    )}

                    {/* Content */}
                    <div className="prose prose-invert max-w-none text-zinc-100 font-medium">
                      {renderTextContent(msg.content)}
                    </div>
                  </div>

                  {/* Dynamic UI based on Intent - Rendered Outside Bubble */}
                  {msg.role === 'assistant' && (
                    <div className="w-full mt-2 pl-1">
                      {msg.intent === 'list_emails' && <EmailList emails={msg.data?.emails || msg.data} onEmailClick={handleEmailClick} />}
                      {msg.intent === 'read_email' && <EmailRenderer email={msg.data} />}
                      {msg.intent === 'list_files' && <DriveList files={msg.data?.files || msg.data} />}
                      {msg.intent === 'list_events' && <EventList events={msg.data?.events || msg.data} />}
                      {msg.intent === 'request_auth' && <AuthPrompt onOpenSettings={() => setIsSettingsOpen(true)} credentials={credentials} />}
                      {msg.intent === 'list_local_files' && <LocalFileList files={msg.data?.files || msg.data} onSummarizeFile={handleSummarizeFile} onLocateFile={handleLocateFile} onOpenFile={handleOpenFile} />}
                      {msg.intent === 'render_local_file' && (
                        <div className="mt-4 p-4 bg-zinc-950 border border-zinc-800 font-mono text-xs whitespace-pre-wrap max-h-96 overflow-auto text-zinc-300">
                          {msg.data.content}
                        </div>
                      )}
                      {msg.intent === 'draft_email' && !sentDrafts.has(idx) && (
                        <EmailComposer
                          to={msg.data.to}
                          initialSubject={msg.data.subject}
                          initialBody={msg.data.body}
                          onSend={(t, c, b, s, bo) => handleSendEmail(idx, t, c, b, s, bo)}
                          onCancel={() => setSentDrafts(prev => new Set(prev).add(idx))}
                        />
                      )}
                      {msg.intent === 'draft_email' && sentDrafts.has(idx) && (
                        <div className="mt-2 text-xs text-zinc-500 italic border-l-2 border-zinc-800 pl-2">
                          Draft processed.
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}

            {/* Loading Indicator */}
            {isLoading && (
              <div className="flex gap-4 max-w-3xl">
                <div className="h-8 w-8 shrink-0 flex items-center justify-center border bg-black border-zinc-700 text-zinc-400">
                  <Bot className="h-4 w-4 animate-pulse" />
                </div>
                <div className="flex items-center gap-1 p-4 bg-zinc-900/50 border border-zinc-800 self-start">
                  <div className="w-1.5 h-1.5 bg-zinc-500 rounded-full animate-bounce [animation-delay:-0.3s]"></div>
                  <div className="w-1.5 h-1.5 bg-zinc-500 rounded-full animate-bounce [animation-delay:-0.15s]"></div>
                  <div className="w-1.5 h-1.5 bg-zinc-500 rounded-full animate-bounce"></div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* Input Area */}
        <div className="absolute bottom-0 left-0 right-0 p-6 bg-gradient-to-t from-black via-black to-transparent">
          <div className="w-full md:max-w-5xl mx-auto">
            <form
              onSubmit={handleSubmit}
              className="flex items-center gap-0 border border-zinc-700 bg-black shadow-2xl focus-within:border-white focus-within:ring-1 focus-within:ring-white transition-all overflow-hidden"
            >
              <div className="pl-4 pr-2 text-zinc-500">
                <Terminal className={cn("h-4 w-4", isLoading ? "animate-pulse text-green-500" : "")} />
              </div>
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={isLoading ? "Agent is processing..." : "Enter command..."}
                disabled={isLoading}
                className="flex-1 bg-transparent p-4 text-sm focus:outline-none font-mono text-white placeholder:text-zinc-600"
                autoFocus
              />
              <button
                type="submit"
                disabled={isLoading || !input.trim()}
                className="p-4 md:px-6 bg-zinc-900 border-l border-zinc-700 text-zinc-400 font-bold text-xs uppercase hover:bg-zinc-800 hover:text-white disabled:opacity-50 disabled:cursor-not-allowed transition-all"
              >
                <span className="hidden md:inline">Execute</span>
                <Send className="h-4 w-4 md:hidden" />
              </button>
            </form>
            <div className="text-center mt-2">
              <p className="text-[10px] text-zinc-600 uppercase tracking-widest">
                System Active // Ready for Input
              </p>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
