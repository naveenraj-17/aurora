import { useState, useEffect } from 'react';
import { Settings, X, Shield, HelpCircle, Trash } from 'lucide-react';

interface SettingsModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSave: (name: string, model: string, mode: string, keys: any) => void;
    credentials?: any;
    showBrowser: boolean;
    onToggleBrowser: (val: boolean) => void;
}

export const SettingsModal = ({ isOpen, onClose, onSave, credentials, showBrowser, onToggleBrowser }: SettingsModalProps) => {
    const [agentName, setAgentName] = useState('');
    const [selectedModel, setSelectedModel] = useState('');
    const [mode, setMode] = useState('local'); // local | cloud
    const [localModels, setLocalModels] = useState<string[]>([]);
    const [cloudModels, setCloudModels] = useState<string[]>([]);
    const [loadingModels, setLoadingModels] = useState(false);

    // Keys
    const [openaiKey, setOpenaiKey] = useState('');
    const [anthropicKey, setAnthropicKey] = useState('');
    const [geminiKey, setGeminiKey] = useState('');

    // Confirmation Modal State
    const [confirmAction, setConfirmAction] = useState<{ type: 'recent' | 'all', message: string } | null>(null);

    // History Handler - Open Modal
    const handleClearHistory = (type: 'recent' | 'all') => {
        const message = type === 'recent'
            ? "Are you sure you want to clear RECENT history? This only removes the current session's short-term memory."
            : "Are you sure you want to clear ALL history? This will permanently delete ALL long-term memories (ChromaDB) and the current session.";

        setConfirmAction({ type, message });
    };

    // Actual Execution
    const executeClearHistory = async () => {
        if (!confirmAction) return;

        try {
            const res = await fetch(`/api/history/${confirmAction.type}`, { method: 'DELETE' });
            if (res.ok) {
                // Optional: Toast notification here instead of alert? Keeping alert for now as generic feedback
                alert(`${confirmAction.type === 'recent' ? 'Recent' : 'All'} history cleared successfully.`);
            } else {
                alert("Failed to clear history.");
            }
        } catch (e) {
            alert("Error clearing history.");
        } finally {
            setConfirmAction(null);
        }
    };

    // Fetch data on open
    useEffect(() => {
        if (isOpen) {
            // Get settings
            fetch('/api/settings')
                .then(res => res.json())
                .then(data => {
                    setAgentName(data.agent_name || 'Antigravity Agent');
                    setSelectedModel(data.model || 'mistral');
                    setMode(data.mode || 'local');
                    setOpenaiKey(data.openai_key || '');
                    setAnthropicKey(data.anthropic_key || '');
                    setGeminiKey(data.gemini_key || '');
                });

            // Get models
            setLoadingModels(true);
            fetch('/api/models')
                .then(res => res.json())
                .then(data => {
                    setLocalModels(data.local || []);
                    setCloudModels(data.cloud || []);
                    setLoadingModels(false);
                })
                .catch(() => setLoadingModels(false));
        }
    }, [isOpen]);

    if (!isOpen) return null;

    // Filter models based on mode
    const filteredModels = mode === 'local' ? localModels : cloudModels;

    return (
        <>
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-200">
                <div className="w-full max-w-lg border border-white/20 bg-black shadow-[0_0_30px_rgba(0,255,0,0.1)] p-6 font-mono text-white relative max-h-[90vh] overflow-y-auto">
                    <button onClick={onClose} className="absolute top-4 right-4 text-zinc-500 hover:text-white">
                        <X className="h-5 w-5" />
                    </button>

                    <h2 className="text-xl font-bold border-b border-white/20 pb-2 mb-6 flex items-center gap-2">
                        <Settings className="h-5 w-5" /> SYSTEM CONFIGURATION
                    </h2>

                    <div className="space-y-6">

                        <div className="space-y-2">
                            <label className="text-xs uppercase text-zinc-500">Global Agent Name</label>
                            <input
                                type="text"
                                value={agentName}
                                onChange={(e) => setAgentName(e.target.value)}
                                className="w-full bg-zinc-900 border border-zinc-800 p-2 text-sm focus:border-white focus:outline-none transition-colors text-white placeholder:text-zinc-700"
                                placeholder="Enter Agent Name"
                            />
                        </div>

                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                                <label className="text-xs uppercase text-zinc-500">Show Browser Window</label>
                                <div className="group relative">
                                    <HelpCircle className="h-3 w-3 text-zinc-500 cursor-help" />
                                    <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 w-48 bg-zinc-800 text-xs text-zinc-300 p-2 rounded border border-zinc-700 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-50">
                                        When enabled, the agent will open a visible browser window for web searches and navigation. Useful for debugging visually.
                                    </div>
                                </div>
                            </div>
                            <label className="relative inline-flex items-center cursor-pointer">
                                <input
                                    type="checkbox"
                                    checked={showBrowser}
                                    onChange={(e) => onToggleBrowser(e.target.checked)}
                                    className="sr-only peer"
                                />
                                <div className="w-9 h-5 bg-zinc-700 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-white rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-green-600"></div>
                            </label>
                        </div>

                        <div className="space-y-2">
                            <label className="text-xs uppercase text-zinc-500">Operation Mode</label>
                            <div className="flex gap-4">
                                <label className="flex items-center gap-2 cursor-pointer">
                                    <input
                                        type="radio"
                                        checked={mode === 'local'}
                                        onChange={() => {
                                            setMode('local');
                                            if (localModels.length > 0 && !localModels.includes(selectedModel)) {
                                                setSelectedModel(localModels[0]);
                                            } else if (!localModels.includes(selectedModel)) {
                                                setSelectedModel('mistral');
                                            }
                                        }}
                                        className="accent-white"
                                    />
                                    <span className={mode === 'local' ? 'text-white font-bold' : 'text-zinc-500'}>Local Network (Ollama)</span>
                                </label>
                                <label className="flex items-center gap-2 cursor-pointer">
                                    <input
                                        type="radio"
                                        checked={mode === 'cloud'}
                                        onChange={() => {
                                            setMode('cloud');
                                            if (cloudModels.length > 0 && !cloudModels.includes(selectedModel)) {
                                                setSelectedModel(cloudModels[0]);
                                            } else if (!cloudModels.includes(selectedModel)) {
                                                setSelectedModel('gemini-2.0-flash');
                                            }
                                        }}
                                        className="accent-white"
                                    />
                                    <span className={mode === 'cloud' ? 'text-white font-bold' : 'text-zinc-500'}>Cloud API</span>
                                </label>
                            </div>
                        </div>

                        {mode === 'cloud' && (
                            <div className="p-3 border border-red-900/50 bg-red-950/20 text-red-200 text-xs flex gap-2 items-start">
                                <Shield className="h-4 w-4 shrink-0 mt-0.5" />
                                <p><strong>PRIVACY WARNING:</strong> Request data will be sent to external providers (OpenAI, Anthropic, or Google). Ensure you trust these services with your data.</p>
                            </div>
                        )}

                        {mode === 'cloud' && (
                            <div className="space-y-3 pt-2 border-t border-zinc-900">
                                <div className="space-y-1">
                                    <label className="text-[10px] uppercase text-zinc-500">OpenAI API Key</label>
                                    <input type="password" value={openaiKey} onChange={e => setOpenaiKey(e.target.value)} className="w-full bg-zinc-900 border border-zinc-800 p-2 text-xs text-white focus:border-white focus:outline-none" placeholder="sk-..." />
                                </div>
                                <div className="space-y-1">
                                    <label className="text-[10px] uppercase text-zinc-500">Anthropic API Key</label>
                                    <input type="password" value={anthropicKey} onChange={e => setAnthropicKey(e.target.value)} className="w-full bg-zinc-900 border border-zinc-800 p-2 text-xs text-white focus:border-white focus:outline-none" placeholder="sk-ant-..." />
                                </div>
                                <div className="space-y-1">
                                    <label className="text-[10px] uppercase text-zinc-500">Gemini API Key</label>
                                    <input type="password" value={geminiKey} onChange={e => setGeminiKey(e.target.value)} className="w-full bg-zinc-900 border border-zinc-800 p-2 text-xs text-white focus:border-white focus:outline-none" placeholder="AIza..." />
                                </div>
                            </div>
                        )}

                        <div className="space-y-2">
                            <label className="text-xs uppercase text-zinc-500">Target Model ({mode})</label>
                            <select
                                value={selectedModel}
                                onChange={(e) => setSelectedModel(e.target.value)}
                                className="w-full bg-zinc-900 border border-zinc-800 p-2 text-sm focus:border-white focus:outline-none transition-colors text-white"
                            >
                                {loadingModels ? (
                                    <option>Loading models...</option>
                                ) : (
                                    <>
                                        <option value="" disabled>Select a model...</option>
                                        {filteredModels.map(m => (
                                            <option key={m} value={m}>{m}</option>
                                        ))}
                                    </>
                                )}
                            </select>
                        </div>

                        <div className="space-y-4 pt-4 border-t border-zinc-800">
                            <label className="text-xs uppercase text-zinc-500 font-bold block">Google Workspace Config</label>

                            {/* Status Display */}
                            <div className="bg-zinc-950 border border-zinc-900 p-3 text-xs font-mono text-zinc-400 space-y-2 overflow-hidden">
                                {credentials ? (
                                    <>
                                        <div className="flex justify-between border-b border-zinc-900 pb-1">
                                            <span className="text-zinc-500">Credentials File:</span>
                                            <span className="text-green-500">LOADED</span>
                                        </div>
                                        <div className="flex justify-between"><span>Client ID:</span> <span className="text-zinc-600 truncate max-w-[200px]">{credentials.client_id}</span></div>
                                        <div className="flex justify-between"><span>Project ID:</span> <span className="text-zinc-600">{credentials.project_id}</span></div>

                                        {/* Connect Button Inside Settings */}
                                        <div className="pt-2 mt-2 border-t border-zinc-900">
                                            <a
                                                href="/auth/login"
                                                className="flex items-center justify-center gap-2 w-full bg-white text-black py-2 text-xs font-bold hover:bg-zinc-200 transition-colors uppercase"
                                            >
                                                <Shield className="h-3 w-3" />
                                                {credentials.token_uri ? "Reconnect Account" : "Connect Account"}
                                            </a>
                                        </div>
                                    </>
                                ) : (
                                    <div className="text-center py-2">
                                        <span className="text-zinc-500 italic block mb-2">No credentials.json found.</span>
                                    </div>
                                )}
                            </div>

                            <div className="text-[10px] text-zinc-500 space-y-2 bg-zinc-900/50 p-2 border border-zinc-800/50 rounded">
                                <p className="font-bold text-zinc-300">How to get Credentials:</p>
                                <ol className="list-decimal pl-4 space-y-1">
                                    <li>Go to <a href="https://console.cloud.google.com/" target="_blank" className="text-blue-400 hover:underline">Google Cloud Console</a> & create a Project.</li>
                                    <li>Go to <strong>APIs & Services &gt; Library</strong>. Enable: <em>Gmail API, Google Drive API, Google Calendar API</em>.</li>
                                    <li>Go to <strong>APIs & Services &gt; OAuth Consent Screen</strong>. select "External", Create. Add your email as a Test User.</li>
                                    <li>Go to <strong>Credentials &gt; Create Credentials &gt; OAuth Client ID</strong>.</li>
                                    <li>Select "Desktop App" (or Web App).</li>
                                    <li>Download the JSON file. Rename it to <code>credentials.json</code> content or paste below.</li>
                                </ol>
                            </div>

                            {/* Token Import (Skip OAuth) */}
                            <details className="group">
                                <summary className="cursor-pointer text-xs text-zinc-500 hover:text-white mt-1 list-none flex items-center gap-2">
                                    <span className="underline decoration-zinc-700 decoration-dotted">Advanced: Import existing Token JSON (Skip OAuth)</span>
                                </summary>
                                <div className="mt-2 text-[10px] text-zinc-500">
                                    <p className="mb-1">If you have a <code>token.json</code> from another authenticated machine, paste it here to skip logging in.</p>
                                    <textarea
                                        className="w-full h-24 bg-zinc-950 border border-zinc-800 p-2 font-mono text-zinc-300 focus:border-white focus:outline-none"
                                        placeholder='{"token": "...", "refresh_token": "..."}'
                                        onChange={async (e) => {
                                            const val = e.target.value;
                                            try {
                                                JSON.parse(val);
                                                const res = await fetch('/api/setup/google-token', {
                                                    method: 'POST',
                                                    body: val,
                                                    headers: { 'Content-Type': 'application/json' }
                                                });
                                                if (res.ok) alert("Token Saved! Restarting backend...");
                                            } catch (err) { }
                                        }}
                                    />
                                </div>
                            </details>

                            {/* Upload Area */}
                            <details className="group">
                                <summary className="cursor-pointer text-xs text-zinc-400 hover:text-white list-none flex items-center gap-2 bg-zinc-900 p-2 border border-zinc-800">
                                    <span>+ Paste Credentials JSON</span>
                                </summary>
                                <div className="mt-2 space-y-2">
                                    <textarea
                                        className="w-full h-24 bg-zinc-950 border border-zinc-800 p-2 text-[10px] font-mono text-zinc-300 focus:border-white focus:outline-none"
                                        placeholder='{"installed":{"client_id":"...","project_id":"..."}}'
                                        onChange={async (e) => {
                                            const val = e.target.value;
                                            try {
                                                JSON.parse(val);
                                                const res = await fetch('/api/setup/google-credentials', {
                                                    method: 'POST',
                                                    body: val,
                                                    headers: { 'Content-Type': 'application/json' }
                                                });
                                                if (res.ok) alert("Credentials Saved! Please restart backend to apply.");
                                            } catch (err) { }
                                        }}
                                    />
                                </div>
                            </details>
                        </div>

                        <div className="space-y-4 pt-4 border-t border-zinc-800">
                            <label className="text-xs uppercase text-zinc-500 font-bold block">Memory Management</label>
                            <div className="flex gap-3">
                                <button
                                    onClick={() => handleClearHistory('recent')}
                                    className="flex-1 flex items-center justify-center gap-2 bg-zinc-900 border border-zinc-800 text-zinc-300 py-2 text-xs hover:bg-zinc-800 hover:text-white transition-colors"
                                >
                                    <Trash className="h-3 w-3" />
                                    Clear Recent
                                </button>
                                <button
                                    onClick={() => handleClearHistory('all')}
                                    className="flex-1 flex items-center justify-center gap-2 bg-red-950/30 border border-red-900/50 text-red-400 py-2 text-xs hover:bg-red-900/50 hover:text-red-200 transition-colors"
                                >
                                    <Trash className="h-3 w-3" />
                                    Clear All History
                                </button>
                            </div>
                            <p className="text-[10px] text-zinc-500">
                                <strong>Recent:</strong> Clears current session buffer (last 10 msgs).<br />
                                <strong>All:</strong> Clears everything including long-term vector DB.
                            </p>
                        </div>
                    </div>

                    <div className="mt-8 flex justify-end gap-3">
                        <button onClick={onClose} className="px-4 py-2 text-sm border border-zinc-800 hover:bg-zinc-900 text-zinc-400 hover:text-white transition-colors">
                            CANCEL
                        </button>
                        <button
                            onClick={() => {
                                onSave(agentName, selectedModel, mode, { openai_key: openaiKey, anthropic_key: anthropicKey, gemini_key: geminiKey, show_browser: showBrowser });
                                onClose();
                            }}
                            className="px-4 py-2 text-sm bg-white text-black font-bold hover:bg-zinc-200 transition-colors"
                        >
                            SAVE CHANGES
                        </button>
                    </div>
                </div>
            </div>

            {/* Custom Confirmation Modal */}
            {
                confirmAction && (
                    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-[2px] p-4 animate-in fade-in duration-200">
                        <div className="w-full max-w-sm border border-red-500/30 bg-black shadow-[0_0_50px_rgba(255,0,0,0.1)] p-6 font-mono text-white">
                            <h3 className="text-lg font-bold text-red-500 mb-4 flex items-center gap-2">
                                CONFIRM ACTION
                            </h3>
                            <p className="text-sm text-zinc-300 mb-6 leading-relaxed">
                                {confirmAction.message}
                            </p>
                            <div className="flex justify-end gap-3">
                                <button
                                    onClick={() => setConfirmAction(null)}
                                    className="px-4 py-2 text-xs border border-zinc-800 hover:bg-zinc-900 text-zinc-400 hover:text-white transition-colors"
                                >
                                    CANCEL
                                </button>
                                <button
                                    onClick={executeClearHistory}
                                    className="px-4 py-2 text-xs bg-red-900/20 border border-red-900/50 text-red-500 hover:bg-red-900/40 hover:text-red-400 font-bold transition-colors"
                                >
                                    CONFIRM DELETE
                                </button>
                            </div>
                        </div>
                    </div>
                )
            }
        </>
    );
};
