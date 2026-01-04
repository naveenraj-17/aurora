import { useState, useEffect } from 'react';
import { Settings, X, Shield, HelpCircle, Trash, Cpu, Cloud, Database, LayoutGrid, Bot, Plus, Save } from 'lucide-react';

interface SettingsModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSave: (name: string, model: string, mode: string, keys: any) => void;
    credentials?: any;
    showBrowser: boolean;
    onToggleBrowser: (val: boolean) => void;
}

type Tab = 'general' | 'models' | 'workspace' | 'memory' | 'agents' | 'datalab';

// Tool Group Definitions for UI
const CAPABILITIES = [
    {
        id: 'gmail',
        label: 'Gmail',
        description: 'Read, draft, and send emails.',
        tools: ['list_emails', 'read_email', 'get_recent_emails_content', 'draft_email', 'send_email']
    },
    {
        id: 'drive',
        label: 'Google Drive',
        description: 'List and read files from Drive.',
        tools: ['list_files', 'read_file_content', 'create_file']
    },
    {
        id: 'calendar',
        label: 'Calendar',
        description: 'View and schedule events.',
        tools: ['list_upcoming_events', 'create_event']
    },
    {
        id: 'local_files',
        label: 'Local Files',
        description: 'Access files on your computer.',
        tools: ['list_local_files', 'read_local_file']
    },
    {
        id: 'browser',
        label: 'Browser Automation',
        description: 'Visit websites and read content.',
        tools: ['visit_page']
    },
    {
        id: 'web_search',
        label: 'Web Search',
        description: 'Search the internet for info.',
        tools: ['search_web']
    }
];


export const SettingsModal = ({ isOpen, onClose, onSave, credentials, showBrowser, onToggleBrowser }: SettingsModalProps) => {
    const [activeTab, setActiveTab] = useState<Tab>('general');
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

    // Agents State
    const [agents, setAgents] = useState<any[]>([]);
    const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
    const [draftAgent, setDraftAgent] = useState<any>(null);


    // Confirmation Modal State
    const [confirmAction, setConfirmAction] = useState<{ type: 'recent' | 'all', message: string } | null>(null);

    // Data Lab State
    const [dlTopic, setDlTopic] = useState('');
    const [dlCount, setDlCount] = useState(10);
    const [dlProvider, setDlProvider] = useState('openai');
    const [dlSystemPrompt, setDlSystemPrompt] = useState('You are a helpful assistant.');
    const [dlEdgeCases, setDlEdgeCases] = useState('');
    const [dlStatus, setDlStatus] = useState<any>(null);
    const [dlDatasets, setDlDatasets] = useState<any[]>([]);

    useEffect(() => {
        if (activeTab === 'datalab') {
            // Initial fetch
            fetchDatasets();
            fetchStatus();
            // Poll
            const interval = setInterval(() => {
                fetchStatus();
                if (dlStatus?.status === 'generating') fetchDatasets(); // Refresh list occasionally
            }, 2000);
            return () => clearInterval(interval);
        }
    }, [activeTab]);

    const fetchDatasets = () => fetch('/api/synthetic/datasets').then(r => r.json()).then(setDlDatasets).catch(() => { });
    const fetchStatus = () => fetch('/api/synthetic/status').then(r => r.json()).then(setDlStatus).catch(() => { });

    const handleGenerateData = async () => {
        if (!dlTopic) return alert("Please enter a topic.");
        if (dlProvider === 'openai' && !openaiKey) return alert("OpenAI Key required.");
        if (dlProvider === 'gemini' && !geminiKey) return alert("Gemini Key required.");

        try {
            const res = await fetch('/api/synthetic/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    topic: dlTopic,
                    count: dlCount,
                    provider: dlProvider,
                    api_key: dlProvider === 'openai' ? openaiKey : geminiKey,
                    system_prompt: dlSystemPrompt,
                    edge_cases: dlEdgeCases
                })
            });
            if (res.ok) {
                alert("Generation Started!");
                fetchStatus();
            } else {
                const err = await res.json();
                alert("Error: " + err.detail);
            }
        } catch (e) {
            alert("Failed to start generation.");
        }
    };

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

            // Get Agents
            fetch('/api/agents')
                .then(res => res.json())
                .then(data => {
                    setAgents(Array.isArray(data) ? data : []);
                    if (data && data.length > 0 && !selectedAgentId) {
                        // Don't auto-select to allow "Create New" flow naturally, 
                        // but listing them is enough.
                    }
                });
        }
    }, [isOpen]);

    // Handle Save Agent
    const handleSaveAgent = async () => {
        if (!draftAgent) return;

        try {
            const res = await fetch('/api/agents', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(draftAgent)
            });
            if (res.ok) {
                const saved = await res.json();
                // Update local list
                const idx = agents.findIndex((a: any) => a.id === saved.id);
                if (idx >= 0) {
                    const newAgents = [...agents];
                    newAgents[idx] = saved;
                    setAgents(newAgents);
                } else {
                    setAgents([...agents, saved]);
                }
                alert("Agent saved successfully!");
            }
        } catch (e) {
            alert("Error saving agent.");
        }
    };

    // Handle Delete Agent
    const handleDeleteAgent = async (id: string) => {
        if (!confirm("Are you sure you want to delete this agent?")) return;
        try {
            await fetch(`/api/agents/${id}`, { method: 'DELETE' });
            setAgents(agents.filter((a: any) => a.id !== id));
            if (selectedAgentId === id) {
                setSelectedAgentId(null);
                setDraftAgent(null);
            }
        } catch (e) {
            alert("Error deleting agent");
        }
    };


    if (!isOpen) return null;

    // Filter models based on mode
    const filteredModels = mode === 'local' ? localModels : cloudModels;

    const tabs = [
        { id: 'general', label: 'General', icon: LayoutGrid },
        { id: 'agents', label: 'Build Agents', icon: Bot },
        { id: 'datalab', label: 'Data Lab', icon: Database },
        { id: 'models', label: 'Models', icon: Cpu },
        { id: 'workspace', label: 'Google Workspace', icon: Cloud },
        { id: 'memory', label: 'Memory', icon: Trash }, // Icon change for memory to differentiate? Keeping Database for Data Lab.
    ];

    // Added font-mono to ensure inheritance if not already inherited
    return (
        <>
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 backdrop-blur-md animate-in fade-in duration-200 font-mono">
                <div className="w-full h-full md:w-[90vw] md:h-[85vh] md:max-w-6xl md:border md:border-white/10 bg-black shadow-2xl flex flex-col md:flex-row overflow-hidden relative">

                    {/* Header (Mobile) / Close Button */}
                    <button
                        onClick={onClose}
                        className="absolute top-4 right-4 z-50 p-2 text-zinc-500 hover:text-white hover:bg-zinc-900 transition-colors"
                    >
                        <X className="h-6 w-6" />
                    </button>

                    {/* Sidebar */}
                    <div className="w-full md:w-64 bg-zinc-950 border-b md:border-b-0 md:border-r border-white/10 flex flex-col shrink-0">
                        <div className="p-6 border-b border-white/10 md:mb-2">
                            <h2 className="text-xl font-bold flex items-center gap-3 tracking-wider">
                                <Settings className="h-5 w-5 text-white" />
                                SETTINGS
                            </h2>
                        </div>

                        <nav className="flex-1 p-2 space-y-1 overflow-x-auto md:overflow-visible flex md:flex-col">
                            {tabs.map((tab) => {
                                const Icon = tab.icon;
                                const isActive = activeTab === tab.id;
                                return (
                                    <button
                                        key={tab.id}
                                        onClick={() => setActiveTab(tab.id as Tab)}
                                        // FIXED: Reduced padding (py-3 -> py-2.5) and removed translate-x-1 to fix misalignment
                                        className={`flex items-center gap-3 px-4 py-2.5 text-sm font-medium transition-all duration-200 whitespace-nowrap md:whitespace-normal
                                            ${isActive
                                                ? 'bg-white text-black shadow-lg'
                                                : 'text-zinc-400 hover:text-white hover:bg-white/5'
                                            }`}
                                    >
                                        <Icon className={`h-4 w-4 ${isActive ? 'text-black' : 'text-zinc-500 group-hover:text-white'}`} />
                                        {tab.label}
                                    </button>
                                );
                            })}
                        </nav>

                        <div className="p-4 border-t border-white/10 hidden md:block">
                            <div className="text-[10px] text-zinc-600 font-mono text-center">
                                ANTIGRAVITY v1.0
                            </div>
                        </div>
                    </div>

                    {/* Main Content Area */}
                    {/* FIXED: Changed bg-black/50 to bg-transparent to allow parent bg-black (which inverts properly) to show through. */}
                    <div className="flex-1 flex flex-col h-full overflow-hidden bg-transparent">
                        <div className="flex-1 overflow-y-auto p-6 md:p-12">
                            <div className="max-w-3xl mx-auto space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-300">

                                <div className="mb-8">
                                    <h1 className="text-3xl font-bold mb-2">{tabs.find(t => t.id === activeTab)?.label}</h1>
                                    <p className="text-zinc-500 text-sm">Manage your agent's {activeTab} configuration.</p>
                                </div>

                                {/* GENERAL TAB */}
                                {activeTab === 'general' && (
                                    <div className="space-y-8">
                                        <div className="space-y-2">
                                            <label className="text-xs uppercase font-bold text-zinc-500 tracking-wider">Global Agent Name</label>
                                            {/* FIXED: Reduced padding (p-4 -> p-2.5) and font size (text-lg -> text-sm) */}
                                            <input
                                                type="text"
                                                value={agentName}
                                                onChange={(e) => setAgentName(e.target.value)}
                                                className="w-full bg-zinc-900 border border-zinc-800 p-2.5 text-sm focus:border-white focus:outline-none transition-colors text-white placeholder:text-zinc-700 font-medium"
                                                placeholder="Enter Agent Name"
                                            />
                                            <p className="text-xs text-zinc-600">This name identifies your agent across the system.</p>
                                        </div>

                                        {/* FIXED: Changed bg-zinc-900/30 to bg-zinc-900/20 to match globals.css override for light mode */}
                                        <div className="p-4 bg-zinc-900/20 border border-zinc-800 flex items-center justify-between">
                                            <div className="space-y-1">
                                                <div className="flex items-center gap-2">
                                                    <span className="font-medium text-white">Show Browser Window</span>
                                                    <div className="group relative">
                                                        <HelpCircle className="h-4 w-4 text-zinc-500 cursor-help" />
                                                        <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 w-64 bg-zinc-800 text-xs text-zinc-300 p-3 border border-zinc-700 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-50 shadow-xl">
                                                            When enabled, the agent will open a visible browser window for web searches and navigation. Useful for debugging visually.
                                                        </div>
                                                    </div>
                                                </div>
                                                <p className="text-xs text-zinc-500">Toggle visibility of the automated browser instance.</p>
                                            </div>
                                            <label className="relative inline-flex items-center cursor-pointer">
                                                <input
                                                    type="checkbox"
                                                    checked={showBrowser}
                                                    onChange={(e) => onToggleBrowser(e.target.checked)}
                                                    className="sr-only peer"
                                                />
                                                <div className="w-11 h-6 bg-zinc-800 peer-focus:outline-none peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-zinc-400 after:border-zinc-300 after:border after:h-5 after:w-5 after:transition-all peer-checked:bg-white peer-checked:after:bg-black peer-checked:after:border-transparent"></div>
                                            </label>
                                        </div>
                                    </div>
                                )}

                                {/* AGENTS TAB */}
                                {activeTab === 'agents' && (
                                    <div className="grid grid-cols-1 md:grid-cols-12 gap-6 h-[600px]">
                                        {/* List */}
                                        <div className="md:col-span-4 border-r border-zinc-800 pr-4 flex flex-col h-full">
                                            <div className="mb-4 flex justify-between items-center">
                                                <h3 className="text-sm font-bold text-zinc-400">YOUR AGENTS</h3>
                                                <button
                                                    onClick={() => {
                                                        const newAgent = {
                                                            id: `agent_${Date.now()}`,
                                                            name: "New Agent",
                                                            description: "A custom agent.",
                                                            system_prompt: "You are a helpful assistant.",
                                                            tools: [],
                                                            avatar: "default"
                                                        };
                                                        setDraftAgent(newAgent);
                                                        setSelectedAgentId(newAgent.id);
                                                    }}
                                                    className="p-1.5 hover:bg-zinc-800 text-white transition-colors border border-dashed border-zinc-600 hover:border-white"
                                                    title="Create New Agent"
                                                >
                                                    <Plus className="h-4 w-4" />
                                                </button>
                                            </div>
                                            <div className="space-y-2 overflow-y-auto flex-1">
                                                {Array.isArray(agents) && agents.map((a: any) => (
                                                    <div
                                                        key={a.id}
                                                        onClick={() => {
                                                            setSelectedAgentId(a.id);
                                                            setDraftAgent({ ...a }); // Deep copy to draft
                                                        }}
                                                        className={`p-3 border cursor-pointer transition-all group relative
                                                            ${selectedAgentId === a.id
                                                                ? 'bg-zinc-900 border-white shadow-lg'
                                                                : 'bg-black border-zinc-800 hover:border-zinc-600'
                                                            }`}
                                                    >
                                                        <div className="flex items-center gap-3">
                                                            <div className={`h-8 w-8 rounded-full flex items-center justify-center text-xs font-bold
                                                                ${selectedAgentId === a.id ? 'bg-white text-black' : 'bg-zinc-800 text-zinc-400'}
                                                            `}>
                                                                {a.name.substring(0, 2).toUpperCase()}
                                                            </div>
                                                            <div className="flex-1 min-w-0">
                                                                <div className="text-xs font-bold text-white truncate">{a.name}</div>
                                                                <div className="text-[10px] text-zinc-500 truncate">{a.description}</div>
                                                            </div>
                                                        </div>
                                                        {a.id !== 'aurora' && (
                                                            <button
                                                                onClick={(e) => {
                                                                    e.stopPropagation();
                                                                    handleDeleteAgent(a.id);
                                                                }}
                                                                className="absolute top-2 right-2 p-1 text-zinc-600 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
                                                            >
                                                                <Trash className="h-3 w-3" />
                                                            </button>
                                                        )}
                                                    </div>
                                                ))}
                                            </div>
                                        </div>

                                        {/* Edit Form */}
                                        <div className="md:col-span-8 pl-4 h-full overflow-y-auto">
                                            {draftAgent ? (
                                                <div className="space-y-6 h-full flex flex-col pb-4">
                                                    <div className="flex items-center justify-between">
                                                        <h3 className="text-sm font-bold text-white flex items-center gap-2">
                                                            <div className={`h-2 w-2 rounded-full ${draftAgent.id === 'aurora' ? 'bg-blue-500' : 'bg-purple-500'}`} />
                                                            EDITING: {draftAgent.name.toUpperCase()}
                                                        </h3>
                                                        <button
                                                            onClick={handleSaveAgent}
                                                            className="flex items-center gap-2 px-4 py-1.5 bg-white text-black text-xs font-bold hover:bg-zinc-200"
                                                        >
                                                            <Save className="h-3 w-3" /> SAVE AGENT
                                                        </button>
                                                    </div>

                                                    <div className="grid grid-cols-2 gap-4">
                                                        <div className="space-y-1">
                                                            <label className="text-[10px] font-bold text-zinc-500 uppercase">Name</label>
                                                            <input
                                                                type="text"
                                                                value={draftAgent.name}
                                                                onChange={e => setDraftAgent({ ...draftAgent, name: e.target.value })}
                                                                className="w-full bg-zinc-950 border border-zinc-800 p-2 text-xs text-white focus:border-white focus:outline-none"
                                                            />
                                                        </div>
                                                        <div className="space-y-1">
                                                            <label className="text-[10px] font-bold text-zinc-500 uppercase">Description</label>
                                                            <input
                                                                type="text"
                                                                value={draftAgent.description}
                                                                onChange={e => setDraftAgent({ ...draftAgent, description: e.target.value })}
                                                                className="w-full bg-zinc-950 border border-zinc-800 p-2 text-xs text-white focus:border-white focus:outline-none"
                                                            />
                                                        </div>
                                                    </div>

                                                    <div className="space-y-1">
                                                        <label className="text-[10px] font-bold text-zinc-500 uppercase">Capabilities (Tools)</label>
                                                        <div className="grid grid-cols-2 gap-2">
                                                            {CAPABILITIES.map(cap => {
                                                                const isEnabled = draftAgent.tools.includes("all") || cap.tools.every(t => draftAgent.tools.includes(t));
                                                                return (
                                                                    <div
                                                                        key={cap.id}
                                                                        onClick={() => {
                                                                            if (draftAgent.tools.includes("all")) {
                                                                                // If all, switching to selective means we add ALL tools except this one? 
                                                                                // Or better, just clear "all" and add specific tools.
                                                                                // Complex logic. For MVP:
                                                                                // If switching OFF a capability while "all" is true -> Remove "all", add all defined tools MINUS this group.
                                                                                // But for simplicity of Phase 1, "Aurora" is "all". Others are specific.
                                                                                if (isEnabled) {
                                                                                    // Disable
                                                                                    // Replace "all" with all flattened tools minus this group
                                                                                    const allToolsFlat = CAPABILITIES.flatMap(c => c.tools);
                                                                                    const newTools = allToolsFlat.filter(t => !cap.tools.includes(t));
                                                                                    setDraftAgent({ ...draftAgent, tools: newTools });
                                                                                } else {
                                                                                    // Enable
                                                                                    // Add these tools
                                                                                    // If we now have ALL tools, maybe switch back to "all"? Optional.
                                                                                    setDraftAgent({ ...draftAgent, tools: [...draftAgent.tools, ...cap.tools] });
                                                                                }
                                                                            } else {
                                                                                // Standard Toggle
                                                                                if (isEnabled) {
                                                                                    // Remove
                                                                                    const newTools = draftAgent.tools.filter((t: string) => !cap.tools.includes(t));
                                                                                    setDraftAgent({ ...draftAgent, tools: newTools });
                                                                                } else {
                                                                                    // Add
                                                                                    setDraftAgent({ ...draftAgent, tools: [...draftAgent.tools, ...cap.tools] });
                                                                                }
                                                                            }
                                                                        }}
                                                                        className={`p-2 border cursor-pointer hover:border-zinc-500 transition-colors
                                                                            ${isEnabled
                                                                                ? 'bg-zinc-900 border-zinc-600'
                                                                                : 'bg-black border-zinc-800 opacity-50'
                                                                            }`}
                                                                    >
                                                                        <div className="flex items-center gap-2">
                                                                            <div className={`w-3 h-3 border ${isEnabled ? 'bg-green-500 border-green-500' : 'border-zinc-600'}`}></div>
                                                                            <span className="text-xs font-bold text-white">{cap.label}</span>
                                                                        </div>
                                                                        <p className="text-[9px] text-zinc-500 mt-1 pl-5">{cap.description}</p>
                                                                    </div>
                                                                );
                                                            })}
                                                        </div>
                                                    </div>

                                                    <div className="space-y-1 flex-1 flex flex-col min-h-0">
                                                        <label className="text-[10px] font-bold text-zinc-500 uppercase">System Prompt (The Brain)</label>
                                                        <textarea
                                                            value={draftAgent.system_prompt}
                                                            onChange={e => setDraftAgent({ ...draftAgent, system_prompt: e.target.value })}
                                                            className="w-full flex-1 min-h-[200px] bg-zinc-950 border border-zinc-800 p-3 text-xs font-mono text-zinc-300 focus:border-white focus:outline-none resize-none leading-relaxed"
                                                        />
                                                    </div>
                                                </div>
                                            ) : (
                                                <div className="h-full flex flex-col items-center justify-center text-zinc-600 space-y-4">
                                                    <Bot className="h-12 w-12 opacity-20" />
                                                    <p className="text-sm">Select an agent to edit or create a new one.</p>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                )}

                                {/* DATA LAB TAB */}
                                {activeTab === 'datalab' && (
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-8 h-full">
                                        <div className="space-y-6 overflow-y-auto pr-2">
                                            <div className="space-y-4">
                                                <div className="space-y-1">
                                                    <label className="text-[10px] uppercase font-bold text-zinc-500">Domain / Topic</label>
                                                    <input type="text" value={dlTopic} onChange={e => setDlTopic(e.target.value)}
                                                        className="w-full bg-zinc-900 border border-zinc-800 p-3 text-sm text-white focus:border-white focus:outline-none"
                                                        placeholder="e.g. Medical Assistant, Python Coding Tutor" />
                                                </div>

                                                <div className="grid grid-cols-2 gap-4">
                                                    <div className="space-y-1">
                                                        <label className="text-[10px] uppercase font-bold text-zinc-500">Count</label>
                                                        <input type="number" value={dlCount} onChange={e => setDlCount(parseInt(e.target.value))}
                                                            className="w-full bg-zinc-900 border border-zinc-800 p-3 text-sm text-white focus:border-white focus:outline-none"
                                                            min={1} max={100} />
                                                    </div>
                                                    <div className="space-y-1">
                                                        <label className="text-[10px] uppercase font-bold text-zinc-500">Provider</label>
                                                        <select value={dlProvider} onChange={e => setDlProvider(e.target.value)}
                                                            className="w-full bg-zinc-900 border border-zinc-800 p-3 text-sm text-white focus:border-white focus:outline-none appearance-none">
                                                            <option value="openai">OpenAI (GPT-4o)</option>
                                                            <option value="gemini">Gemini (1.5 Pro)</option>
                                                        </select>
                                                    </div>
                                                </div>

                                                <div className="space-y-1">
                                                    <label className="text-[10px] uppercase font-bold text-zinc-500">Target Persona (System Prompt)</label>
                                                    <textarea value={dlSystemPrompt} onChange={e => setDlSystemPrompt(e.target.value)}
                                                        className="w-full h-24 bg-zinc-900 border border-zinc-800 p-3 text-xs font-mono text-zinc-300 focus:border-white focus:outline-none resize-none" />
                                                </div>

                                                <div className="space-y-1">
                                                    <label className="text-[10px] uppercase font-bold text-zinc-500">Edge Cases & Constraints</label>
                                                    <textarea value={dlEdgeCases} onChange={e => setDlEdgeCases(e.target.value)}
                                                        className="w-full h-24 bg-zinc-900 border border-zinc-800 p-3 text-xs font-mono text-zinc-300 focus:border-white focus:outline-none resize-none"
                                                        placeholder="e.g. 'If user asks for illegal advice, politely refuse.' or 'Always include code comments.'" />
                                                </div>

                                                <button onClick={handleGenerateData} disabled={dlStatus?.status === 'generating'}
                                                    className="w-full py-4 bg-white text-black font-bold text-sm tracking-uppercase hover:bg-zinc-200 disabled:opacity-50 disabled:cursor-not-allowed">
                                                    {dlStatus?.status === 'generating' ? 'GENERATING...' : 'START GENERATION JOB'}
                                                </button>
                                            </div>
                                        </div>

                                        <div className="bg-zinc-950 border border-zinc-800 p-6 flex flex-col h-full">
                                            <h3 className="text-sm font-bold text-zinc-400 mb-4 flex items-center justify-between">
                                                <span>DATASETS</span>
                                                {dlStatus?.status === 'generating' && (
                                                    <span className="text-green-500 text-xs animate-pulse">Running: {dlStatus.completed}/{dlStatus.total}</span>
                                                )}
                                                {dlStatus?.status === 'failed' && (
                                                    <span className="text-red-500 text-xs">Failed: {dlStatus.error}</span>
                                                )}
                                            </h3>

                                            <div className="flex-1 overflow-y-auto space-y-2">
                                                {dlDatasets.length === 0 ? (
                                                    <div className="text-center py-10 text-zinc-600 text-xs italic">No datasets generated yet.</div>
                                                ) : (
                                                    dlDatasets.map((ds: any) => (
                                                        <div key={ds.filename} className="p-3 bg-black border border-zinc-800 flex justify-between items-center group hover:border-zinc-600">
                                                            <div className="flex-1 min-w-0">
                                                                <div className="text-xs text-white font-mono truncate mb-1">{ds.filename}</div>
                                                                <div className="text-[10px] text-zinc-500 flex gap-2">
                                                                    <span>{(ds.size / 1024).toFixed(1)} KB</span>
                                                                    <span>•</span>
                                                                    <span>{new Date(ds.created).toLocaleDateString()}</span>
                                                                </div>
                                                            </div>
                                                            <Database className="h-4 w-4 text-zinc-600 group-hover:text-zinc-400" />
                                                        </div>
                                                    ))
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                )}

                                {/* MODELS TAB */}
                                {activeTab === 'models' && (
                                    <div className="space-y-8">
                                        <div className="space-y-4">
                                            <label className="text-xs uppercase font-bold text-zinc-500 tracking-wider">Operation Mode</label>
                                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                                <label className={`relative flex flex-col p-4 cursor-pointer border transition-all duration-200
                                                    ${mode === 'local'
                                                        ? 'bg-zinc-900 border-white ring-1 ring-white/20'
                                                        : 'bg-zinc-950 border-zinc-800 hover:border-zinc-700 hover:bg-zinc-900/50'}`}>
                                                    <input
                                                        type="radio"
                                                        name="mode"
                                                        value="local"
                                                        checked={mode === 'local'}
                                                        onChange={() => {
                                                            setMode('local');
                                                            if (localModels.length > 0 && !localModels.includes(selectedModel)) setSelectedModel(localModels[0]);
                                                            else if (!localModels.includes(selectedModel)) setSelectedModel('mistral');
                                                        }}
                                                        className="sr-only"
                                                    />
                                                    <div className="flex items-center gap-2 mb-2">
                                                        <Cpu className={`h-5 w-5 ${mode === 'local' ? 'text-white' : 'text-zinc-500'}`} />
                                                        <span className={`font-bold ${mode === 'local' ? 'text-white' : 'text-zinc-400'}`}>Local Network (Ollama)</span>
                                                    </div>
                                                    <p className="text-xs text-zinc-500 leading-relaxed">Runs locally on your machine. Private, free, but requires hardware resources.</p>
                                                </label>

                                                <label className={`relative flex flex-col p-4 cursor-pointer border transition-all duration-200
                                                    ${mode === 'cloud'
                                                        ? 'bg-zinc-900 border-white ring-1 ring-white/20'
                                                        : 'bg-zinc-950 border-zinc-800 hover:border-zinc-700 hover:bg-zinc-900/50'}`}>
                                                    <input
                                                        type="radio"
                                                        name="mode"
                                                        value="cloud"
                                                        checked={mode === 'cloud'}
                                                        onChange={() => {
                                                            setMode('cloud');
                                                            if (cloudModels.length > 0 && !cloudModels.includes(selectedModel)) setSelectedModel(cloudModels[0]);
                                                            else if (!cloudModels.includes(selectedModel)) setSelectedModel('gemini-2.0-flash');
                                                        }}
                                                        className="sr-only"
                                                    />
                                                    <div className="flex items-center gap-2 mb-2">
                                                        <Cloud className={`h-5 w-5 ${mode === 'cloud' ? 'text-white' : 'text-zinc-500'}`} />
                                                        <span className={`font-bold ${mode === 'cloud' ? 'text-white' : 'text-zinc-400'}`}>Cloud API</span>
                                                    </div>
                                                    <p className="text-xs text-zinc-500 leading-relaxed">Uses external providers (OpenAI, Gemini). Faster, smarter, but requires API keys.</p>
                                                    {mode === 'cloud' && (
                                                        <div className="absolute top-4 right-4 text-orange-500">
                                                            <Shield className="h-4 w-4" />
                                                        </div>
                                                    )}
                                                </label>
                                            </div>
                                        </div>

                                        <div className="space-y-2">
                                            <label className="text-xs uppercase font-bold text-zinc-500 tracking-wider">Target Model</label>
                                            <div className="relative">
                                                {/* FIXED: Reduced padding (p-4 -> p-2.5) */}
                                                <select
                                                    value={selectedModel}
                                                    onChange={(e) => setSelectedModel(e.target.value)}
                                                    className="w-full appearance-none bg-zinc-900 border border-zinc-800 p-2.5 text-sm focus:border-white focus:outline-none transition-colors text-white cursor-pointer"
                                                >
                                                    {loadingModels ? (
                                                        <option>Loading models...</option>
                                                    ) : (
                                                        <>
                                                            <option value="" disabled>Select a model...</option>
                                                            {filteredModels.map((m: string) => (
                                                                <option key={m} value={m}>{m}</option>
                                                            ))}
                                                        </>
                                                    )}
                                                </select>
                                                <div className="absolute inset-y-0 right-4 flex items-center pointer-events-none text-zinc-500">
                                                    <Settings className="h-4 w-4" />
                                                </div>
                                            </div>
                                        </div>

                                        {mode === 'cloud' && (
                                            <div className="space-y-6 pt-6 border-t border-zinc-800/50">
                                                <h3 className="text-sm font-bold text-white mb-4">API Configurations</h3>

                                                <div className="space-y-2">
                                                    <label className="text-[10px] uppercase font-bold text-zinc-500">OpenAI API Key</label>
                                                    <input type="password" value={openaiKey} onChange={e => setOpenaiKey(e.target.value)}
                                                        className="w-full bg-zinc-900 border border-zinc-800 p-3 text-xs text-white focus:border-white focus:outline-none transition-colors" placeholder="sk-..." />
                                                </div>
                                                <div className="space-y-2">
                                                    <label className="text-[10px] uppercase font-bold text-zinc-500">Anthropic API Key</label>
                                                    <input type="password" value={anthropicKey} onChange={e => setAnthropicKey(e.target.value)}
                                                        className="w-full bg-zinc-900 border border-zinc-800 p-3 text-xs text-white focus:border-white focus:outline-none transition-colors" placeholder="sk-ant-..." />
                                                </div>
                                                <div className="space-y-2">
                                                    <label className="text-[10px] uppercase font-bold text-zinc-500">Gemini API Key</label>
                                                    <input type="password" value={geminiKey} onChange={e => setGeminiKey(e.target.value)}
                                                        className="w-full bg-zinc-900 border border-zinc-800 p-3 text-xs text-white focus:border-white focus:outline-none transition-colors" placeholder="AIza..." />
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                )}

                                {/* GOOGLE WORKSPACE TAB */}
                                {activeTab === 'workspace' && (
                                    <div className="space-y-8">
                                        <div className="bg-zinc-900 border border-zinc-800 overflow-hidden">
                                            {/* FIXED: Changed bg-zinc-950/50 to bg-zinc-950 to remove opacity and fix light mode grey issue */}
                                            <div className="p-4 border-b border-zinc-800 bg-zinc-950 flex items-center justify-between">
                                                <div className="flex items-center gap-3">
                                                    <div className={`h-2 w-2 ${credentials ? 'bg-green-500 shadow-[0_0_10px_rgba(34,197,94,0.5)]' : 'bg-red-500'}`} />
                                                    <span className="text-sm font-bold text-zinc-400">Connection Status</span>
                                                </div>
                                                <span className={`text-xs px-2 py-1 bg-zinc-900 border border-zinc-800 ${credentials ? 'text-green-400' : 'text-zinc-500'}`}>
                                                    {credentials ? 'CONNECTED' : 'DISCONNECTED'}
                                                </span>
                                            </div>

                                            <div className="p-6 space-y-6">
                                                {credentials ? (
                                                    <div className="space-y-4">
                                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                                                            <div className="p-3 bg-black border border-zinc-800">
                                                                <span className="block text-zinc-500 mb-1">Client ID</span>
                                                                <span className="font-mono text-zinc-300 break-all">{credentials.client_id?.substring(0, 20)}...</span>
                                                            </div>
                                                            <div className="p-3 bg-black border border-zinc-800">
                                                                <span className="block text-zinc-500 mb-1">Project ID</span>
                                                                <span className="font-mono text-zinc-300">{credentials.project_id}</span>
                                                            </div>
                                                        </div>

                                                        <a
                                                            href="/auth/login"
                                                            className="flex items-center justify-center gap-2 w-full bg-white text-black py-3 text-sm font-bold hover:bg-zinc-200 transition-colors uppercase tracking-wide"
                                                        >
                                                            <Shield className="h-4 w-4" />
                                                            {credentials.token_uri ? "Reconnect Account" : "Connect Account"}
                                                        </a>
                                                    </div>
                                                ) : (
                                                    <div className="text-center py-8 px-4">
                                                        <Shield className="h-12 w-12 text-zinc-700 mx-auto mb-4" />
                                                        <h3 className="text-white font-bold mb-2">No Credentials Found</h3>
                                                        <p className="text-sm text-zinc-500 max-w-sm mx-auto mb-6">
                                                            To use Google Workspace features (Gmail, Drive, Calendar), you need to configure OAuth credentials.
                                                        </p>

                                                        <div className="text-left text-xs bg-black p-4 border border-zinc-800 mb-6">
                                                            <p className="font-bold text-zinc-300 mb-2">Quick Setup Guide:</p>
                                                            <ol className="list-decimal pl-4 space-y-2 text-zinc-500">
                                                                <li>Go to <a href="https://console.cloud.google.com/" target="_blank" className="text-blue-400 hover:text-blue-300 underline">Google Cloud Console</a> & create a Project.</li>
                                                                <li>Enable: <em>Gmail, Drive, Calendar APIs</em>.</li>
                                                                <li>Create OAuth Client ID (Desktop App).</li>
                                                                <li>Download JSON and paste below.</li>
                                                            </ol>
                                                        </div>
                                                    </div>
                                                )}

                                                <div className="border-t border-zinc-800 pt-6 space-y-4">
                                                    {/* Upload Area */}
                                                    <details className="group appearance-none">
                                                        <summary className="cursor-pointer text-xs font-bold text-zinc-400 hover:text-white list-none flex items-center gap-2 p-3 bg-zinc-950 border border-zinc-800 hover:border-zinc-700 transition-colors">
                                                            <span>+ PASTE CREDENTIALS.JSON CONTENT</span>
                                                        </summary>
                                                        <div className="mt-2">
                                                            <textarea
                                                                className="w-full h-32 bg-black border border-zinc-800 p-3 text-[10px] font-mono text-zinc-300 focus:border-white focus:outline-none resize-none"
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

                                                    {/* Token Import */}
                                                    <details className="group appearance-none">
                                                        <summary className="cursor-pointer text-xs font-bold text-zinc-500 hover:text-white mt-2 list-none flex items-center gap-2">
                                                            <span className="underline decoration-dotted decoration-zinc-700 hover:decoration-zinc-500">Advanced: Import existing Token JSON (Skip OAuth)</span>
                                                        </summary>
                                                        <div className="mt-2">
                                                            <textarea
                                                                className="w-full h-24 bg-black border border-zinc-800 p-3 font-mono text-xs text-zinc-300 focus:border-white focus:outline-none resize-none"
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
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                )}

                                {/* MEMORY TAB */}
                                {activeTab === 'memory' && (
                                    <div className="space-y-8">
                                        <div className="p-6 bg-red-950/10 border border-red-900/30 space-y-6">
                                            <div>
                                                <h3 className="text-lg font-bold text-red-500 flex items-center gap-2">
                                                    <Database className="h-5 w-5" />
                                                    Danger Zone
                                                </h3>
                                                <p className="text-sm text-red-900/70 mt-1">Manage your agents memory and history. Actions here are irreversible.</p>
                                            </div>

                                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                                <button
                                                    onClick={() => handleClearHistory('recent')}
                                                    className="flex flex-col items-start p-4 bg-red-900/10 border border-red-900/30 hover:bg-red-900/20 hover:border-red-500/50 transition-all text-left"
                                                >
                                                    <span className="font-bold text-red-400 mb-1 flex items-center gap-2">
                                                        <Trash className="h-4 w-4" /> Clear Recent
                                                    </span>
                                                    <span className="text-xs text-red-900/60">Removes strictly the current session's short-term conversation buffer.</span>
                                                </button>

                                                <button
                                                    onClick={() => handleClearHistory('all')}
                                                    className="flex flex-col items-start p-4 bg-red-950/30 border border-red-900/50 hover:bg-red-900/40 hover:border-red-500 transition-all text-left"
                                                >
                                                    <span className="font-bold text-red-400 mb-1 flex items-center current-color gap-2">
                                                        <Trash className="h-4 w-4" /> Clear All History
                                                    </span>
                                                    <span className="text-xs text-red-900/60">Detailed wipe of ALL long-term memories (Vector DB) and session data.</span>
                                                </button>
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* Footer Content Actions */}
                        {/* FIXED: Changed bg-black/50 to bg-zinc-950 for consistent solid background */}
                        <div className="p-6 border-t border-white/10 bg-zinc-950 flex justify-end gap-4 shrink-0">
                            <button
                                onClick={onClose}
                                className="px-6 py-2.5 text-sm font-medium border border-zinc-700 hover:bg-zinc-800 text-zinc-300 hover:text-white transition-colors"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={() => {
                                    onSave(agentName, selectedModel, mode, { openai_key: openaiKey, anthropic_key: anthropicKey, gemini_key: geminiKey, show_browser: showBrowser });
                                    onClose();
                                }}
                                className="px-6 py-2.5 text-sm font-bold bg-white text-black hover:bg-zinc-200 transition-all shadow-[0_0_20px_rgba(255,255,255,0.1)] hover:shadow-[0_0_25px_rgba(255,255,255,0.2)]"
                            >
                                Save Changes
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            {/* Custom Confirmation Modal */}
            {confirmAction && (
                <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-200 font-mono">
                    <div className="w-full max-w-sm border border-red-500/30 bg-black shadow-[0_0_50px_rgba(255,0,0,0.1)] p-6 relative overflow-hidden">
                        <div className="absolute top-0 inset-x-0 h-1 bg-gradient-to-r from-transparent via-red-500 to-transparent opacity-50"></div>
                        <h3 className="text-lg font-bold text-red-500 mb-4 flex items-center gap-2">
                            <Shield className="h-5 w-5" /> CONFIRM DELETION
                        </h3>
                        <p className="text-sm text-zinc-300 mb-8 leading-relaxed">
                            {confirmAction.message}
                        </p>
                        <div className="flex justify-end gap-3">
                            <button
                                onClick={() => setConfirmAction(null)}
                                className="px-4 py-2 text-xs font-medium border border-zinc-800 hover:bg-zinc-900 text-zinc-400 hover:text-white transition-colors"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={executeClearHistory}
                                className="px-4 py-2 text-xs bg-red-900/20 border border-red-900/50 text-red-500 hover:bg-red-900/40 hover:text-red-400 font-bold transition-colors"
                            >
                                Yes, Delete It
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
};
