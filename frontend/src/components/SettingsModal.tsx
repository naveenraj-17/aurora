/* eslint-disable @typescript-eslint/ban-ts-comment */
/* eslint-disable react/no-unescaped-entities */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState, useEffect, useRef } from 'react';
import { Settings, X, Shield, HelpCircle, Trash, Cpu, Cloud, Database, LayoutGrid, Bot, Plus, Save, Wrench } from 'lucide-react';

interface SettingsModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSave: (name: string, model: string, mode: string, keys: any) => void | Promise<void>;
    credentials?: any;
    showBrowser: boolean;
    onToggleBrowser: (val: boolean) => void;
}

type Tab = 'general' | 'models' | 'workspace' | 'database' | 'memory' | 'agents' | 'datalab' | 'custom_tools' | 'personal_details';

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
    },
    {
        id: 'maps',
        label: 'Google Maps',
        description: 'Distance, duration, and directions link between two points.',
        tools: ['get_map_details']
    },
    {
        id: 'sql',
        label: 'SQL Database',
        description: 'Query business database (Tables, SQL).',
        tools: ['list_tables', 'get_table_schema', 'run_sql_query']
    },
    {
        id: 'datetime',
        label: 'Date & Time',
        description: 'Get current and future dates with natural language.',
        tools: ['get_datetime']
    },
    {
        id: 'collect_data',
        label: 'Data Collection',
        description: 'Request user input via dynamic forms.',
        tools: ['collect_data']
    },
    {
        id: 'personal_details',
        label: 'Personal Details',
        description: 'Get saved personal info (name, phone, address).',
        tools: ['get_personal_details']
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
    const [bedrockApiKey, setBedrockApiKey] = useState('');
    const [awsRegion, setAwsRegion] = useState('us-east-1');
    const [bedrockInferenceProfile, setBedrockInferenceProfile] = useState('');
    const [bedrockInferenceProfiles, setBedrockInferenceProfiles] = useState<Array<{ id: string; arn: string; name: string; status?: string }>>([]);
    const [loadingInferenceProfiles, setLoadingInferenceProfiles] = useState(false);
    const [sqlConnectionString, setSqlConnectionString] = useState('');

    // Integrations: Google Maps
    const [googleMapsApiKey, setGoogleMapsApiKey] = useState('');

    // Personal Details
    const [pdFirstName, setPdFirstName] = useState('');
    const [pdLastName, setPdLastName] = useState('');
    const [pdEmail, setPdEmail] = useState('');
    const [pdPhone, setPdPhone] = useState('');
    const [pdAddress1, setPdAddress1] = useState('');
    const [pdAddress2, setPdAddress2] = useState('');
    const [pdCity, setPdCity] = useState('');
    const [pdState, setPdState] = useState('');
    const [pdZipcode, setPdZipcode] = useState('');

    // Integrations: n8n
    const [n8nUrl, setN8nUrl] = useState('http://localhost:5678');
    const [n8nApiKey, setN8nApiKey] = useState('');
    const [globalConfig, setGlobalConfig] = useState<{ id: string, key: string, value: string }[]>([]);

    // Agents State
    const [agents, setAgents] = useState<any[]>([]);
    const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
    const [draftAgent, setDraftAgent] = useState<any>(null);


    // Custom Tools State
    const [customTools, setCustomTools] = useState<any[]>([]);
    const [draftTool, setDraftTool] = useState<any>(null);
    const [toolBuilderMode, setToolBuilderMode] = useState<'config' | 'n8n'>('config');
    const [headerRows, setHeaderRows] = useState<{ id: string, key: string, value: string }[]>([]);
    const [showToast, setShowToast] = useState(false);

    // n8n workflows (for Tool Builder dropdown)
    const [n8nWorkflows, setN8nWorkflows] = useState<any[]>([]);
    const [n8nWorkflowsLoading, setN8nWorkflowsLoading] = useState(false);

    const refreshBedrockModels = async () => {
        setLoadingModels(true);
        try {
            const res = await fetch('/api/bedrock/models');
            const data = await res.json();
            const bedrock = Array.isArray(data.models) ? data.models : [];
            if (bedrock.length > 0) {
                setCloudModels(prev => {
                    const nonBedrock = (prev || []).filter((m: string) => !m.startsWith('bedrock.'));
                    return [...nonBedrock, ...bedrock];
                });
            }
        } catch {
            // ignore
        } finally {
            setLoadingModels(false);
        }
    };

    const refreshBedrockInferenceProfiles = async () => {
        setLoadingInferenceProfiles(true);
        try {
            const res = await fetch('/api/bedrock/inference-profiles');
            const data = await res.json();
            const profiles = Array.isArray(data.profiles) ? data.profiles : [];
            setBedrockInferenceProfiles(profiles);
        } catch {
            setBedrockInferenceProfiles([]);
        } finally {
            setLoadingInferenceProfiles(false);
        }
    };

    const handleSaveSection = async () => {
        await Promise.resolve(onSave(agentName, selectedModel, mode, {
            openai_key: openaiKey,
            anthropic_key: anthropicKey,
            gemini_key: geminiKey,
            bedrock_api_key: bedrockApiKey,
            google_maps_api_key: googleMapsApiKey,
            bedrock_inference_profile: bedrockInferenceProfile,
            aws_region: awsRegion,
            sql_connection_string: sqlConnectionString,
            n8n_url: n8nUrl,
            n8n_api_key: n8nApiKey,
            global_config: globalConfig.reduce((acc, curr) => {
                if (curr.key.trim()) acc[curr.key.trim()] = curr.value;
                return acc;
            }, {} as Record<string, string>),
            show_browser: showBrowser
        }));

        if (mode === 'bedrock') {
            await refreshBedrockModels();
            await refreshBedrockInferenceProfiles();
        }
        setShowToast(true);
        setTimeout(() => setShowToast(false), 3000);
    };

    const handleSavePersonalDetails = async () => {
        try {
            const res = await fetch('/api/personal-details', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    first_name: pdFirstName,
                    last_name: pdLastName,
                    email: pdEmail,
                    phone_number: pdPhone,
                    address: {
                        address1: pdAddress1,
                        address2: pdAddress2,
                        city: pdCity,
                        state: pdState,
                        zipcode: pdZipcode
                    }
                })
            });
            if (!res.ok) throw new Error('Failed to save personal details');
            setShowToast(true);
            setTimeout(() => setShowToast(false), 3000);
        } catch {
            alert('Error saving personal details.');
        }
    };

    // Fullscreen State
    const [isIframeFullscreen, setIsIframeFullscreen] = useState(false);
    const [n8nWorkflowId, setN8nWorkflowId] = useState<string | null>(null);
    const [isN8nLoading, setIsN8nLoading] = useState(true);
    const n8nIframeRef = useRef<HTMLIFrameElement>(null);

    // Reset n8n loading state when switching modes
    useEffect(() => {
        if (toolBuilderMode === 'n8n') {
            setIsN8nLoading(true);
        }
    }, [toolBuilderMode]);

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

    const getN8nBaseUrl = () => (n8nUrl || 'http://localhost:5678').replace(/\/+$/, '');

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

    // Close on escape
    useEffect(() => {
        const handleEsc = (e: KeyboardEvent) => {
            if (e.key === 'Escape') onClose();
        };
        document.addEventListener('keydown', handleEsc);
        return () => document.removeEventListener('keydown', handleEsc);
    }, [onClose]);
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
                    setBedrockApiKey(data.bedrock_api_key || '');
                    setGoogleMapsApiKey(data.google_maps_api_key || '');
                    setAwsRegion(data.aws_region || 'us-east-1');
                    setBedrockInferenceProfile(data.bedrock_inference_profile || '');
                    setSqlConnectionString(data.sql_connection_string || '');
                    setN8nUrl(data.n8n_url || 'http://localhost:5678');
                    setN8nApiKey(data.n8n_api_key || '');
                    if (data.global_config) {
                         const configArray = Object.entries(data.global_config).map(([k, v]) => ({
                             id: Math.random().toString(36).substr(2, 9),
                             key: k,
                             value: v as string
                         }));
                         setGlobalConfig(configArray);
                    } else {
                        setGlobalConfig([]);
                    }
                });

            // Personal details
            fetch('/api/personal-details')
                .then(res => res.json())
                .then(data => {
                    setPdFirstName(data.first_name || '');
                    setPdLastName(data.last_name || '');
                    setPdEmail(data.email || '');
                    setPdPhone(data.phone_number || '');
                    const addr = data.address || {};
                    setPdAddress1(addr.address1 || '');
                    setPdAddress2(addr.address2 || '');
                    setPdCity(addr.city || '');
                    setPdState(addr.state || '');
                    setPdZipcode(addr.zipcode || '');
                })
                .catch(() => { });

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
                });

            // Get Custom Tools
            fetch('/api/tools/custom')
                .then(res => res.json())
                .then(data => {
                    setCustomTools(Array.isArray(data) ? data : []);
                });
        }
    }, [isOpen]);

    // Refresh Bedrock models dynamically when switching into bedrock mode.
    useEffect(() => {
        if (!isOpen) return;
        if (mode !== 'bedrock') return;

        refreshBedrockModels();
        refreshBedrockInferenceProfiles();
    }, [isOpen, mode]);

    // Fetch n8n workflows when the Tool Builder is open (for dropdown)
    useEffect(() => {
        if (!isOpen) return;
        if (activeTab !== 'custom_tools') return;
        if (!draftTool) return;
        if (toolBuilderMode !== 'config') return;
        if (n8nWorkflows.length > 0) return;
        fetchN8nWorkflows();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isOpen, activeTab, draftTool, toolBuilderMode]);

    // Handle Save Custom Tool
    const handleSaveTool = async () => {
        if (!draftTool) return;
        // Validate
        if (!draftTool.name || !draftTool.url) {
            alert("Name and URL are required.");
            return;
        }

        // Validate Schemas
        let finalInputSchema = draftTool.inputSchema;
        let finalOutputSchema = draftTool.outputSchema;

        try {
            if (typeof draftTool.inputSchemaStr === 'string') {
                finalInputSchema = JSON.parse(draftTool.inputSchemaStr);
            }
        } catch (e) {
            alert("Invalid Input Schema JSON");
            return;
        }

        try {
            if (typeof draftTool.outputSchemaStr === 'string' && draftTool.outputSchemaStr.trim()) {
                finalOutputSchema = JSON.parse(draftTool.outputSchemaStr);
            } else if (!draftTool.outputSchemaStr || !draftTool.outputSchemaStr.trim()) {
                finalOutputSchema = undefined;
            }
        } catch (e) {
            alert("Invalid Output Schema JSON");
            return;
        }

        try {
            // Convert header rows to object
            const headersObj: Record<string, string> = {};
            headerRows.forEach(r => {
                if (r.key.trim()) headersObj[r.key.trim()] = r.value;
            });

            const payload = {
                ...draftTool,
                inputSchema: finalInputSchema,
                outputSchema: finalOutputSchema,
                headers: headersObj
            };

            // Clean up temporary fields
            delete payload.inputSchemaStr;
            delete payload.outputSchemaStr;

            const res = await fetch('/api/tools/custom', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (res.ok) {
                const savedResp = await res.json();
                const saved = savedResp?.tool ?? savedResp;
                // Refresh list
                const idx = customTools.findIndex((t: any) => t.name === draftTool.name);
                if (idx >= 0) {
                    const newTools = [...customTools];
                    newTools[idx] = saved;
                    setCustomTools(newTools);
                } else {
                    setCustomTools([...customTools, saved]);
                }
                setDraftTool(null);
                setToolBuilderMode('config');
                alert("Tool saved successfully!");
            } else {
                alert("Failed to save tool");
            }
        } catch (e) {
            alert("Error saving tool.");
        }
    };

    const fetchN8nWorkflows = async () => {
        if (n8nWorkflowsLoading) return;
        setN8nWorkflowsLoading(true);
        try {
            const res = await fetch('/api/n8n/workflows');
            if (!res.ok) {
                setN8nWorkflows([]);
                return;
            }
            const data = await res.json();
            setN8nWorkflows(Array.isArray(data) ? data : []);
        } catch {
            setN8nWorkflows([]);
        } finally {
            setN8nWorkflowsLoading(false);
        }
    };

    // Handle Delete Tool
    const handleDeleteTool = async (name: string) => {
        if (!confirm("Delete this tool?")) return;
        try {
            await fetch(`/api/tools/custom/${name}`, { method: 'DELETE' });
            setCustomTools(customTools.filter(t => t.name !== name));
        } catch (e) { alert("Error deleting tool"); }
    };

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
    const filteredModels = mode === 'local'
        ? localModels
        : (mode === 'bedrock' ? cloudModels.filter(m => m.startsWith('bedrock')) : cloudModels.filter(m => !m.startsWith('bedrock')));

    const tabs = [
        { id: 'general', label: 'General', icon: LayoutGrid },
        { id: 'personal_details', label: 'Personal Details', icon: Shield },
        { id: 'agents', label: 'Build Agents', icon: Bot },
        { id: 'custom_tools', label: 'Tool Builder', icon: Wrench },
        { id: 'datalab', label: 'Data Lab', icon: Database },
        { id: 'models', label: 'Models', icon: Cpu },
        { id: 'workspace', label: 'Integrations', icon: Cloud },
        { id: 'database', label: 'Database', icon: Database },
        { id: 'memory', label: 'Memory', icon: Trash }, // Icon change for memory to differentiate? Keeping Database for Data Lab.
    ];

    // Added font-mono to ensure inheritance if not already inherited
    return (
        <>
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 backdrop-blur-md animate-in fade-in duration-200 font-mono">
                <div className="w-full h-full bg-black shadow-2xl flex flex-col md:flex-row overflow-hidden relative">

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
                                Aurora v1.0
                            </div>
                        </div>
                    </div>

                    {/* Main Content Area */}
                    {/* FIXED: Changed bg-black/50 to bg-transparent to allow parent bg-black (which inverts properly) to show through. */}
                    <div className="flex-1 flex flex-col h-full overflow-hidden bg-transparent">
                        <div className="flex-1 overflow-y-auto p-6 md:p-12">
                            <div className="max-w-5xl mx-auto space-y-10 animate-in fade-in slide-in-from-bottom-4 duration-300">

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
                                        <div className="pt-4 flex justify-end">
                                            <button
                                                onClick={handleSaveSection}
                                                className="px-6 py-2.5 text-sm font-bold bg-white text-black hover:bg-zinc-200 transition-all shadow-lg"
                                            >
                                                Save Changes
                                            </button>
                                        </div>
                                    </div>
                                )}

                                {/* AGENTS TAB */}
                                {activeTab === 'agents' && (
                                    <div className="grid grid-cols-1 md:grid-cols-12 gap-10">
                                        {/* List */}
                                        <div className="md:col-span-4 border-r border-zinc-800 pr-4 flex flex-col sticky top-0 h-fit self-start">
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

                                            <div className="space-y-2 flex-1">
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
                                        <div className="md:col-span-8 pl-4">
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

                                                    <div className="grid grid-cols-2 gap-6">
                                                        <div className="space-y-1">
                                                            <label className="text-[10px] font-bold text-zinc-500 uppercase">Name</label>
                                                            <input
                                                                type="text"
                                                                value={draftAgent.name}
                                                                onChange={e => setDraftAgent({ ...draftAgent, name: e.target.value })}
                                                                className="w-full bg-zinc-950 border border-zinc-800 p-3 text-xs text-white focus:border-white focus:outline-none"
                                                            />
                                                        </div>
                                                        <div className="space-y-1">
                                                            <label className="text-[10px] font-bold text-zinc-500 uppercase">Description</label>
                                                            <input
                                                                type="text"
                                                                value={draftAgent.description}
                                                                onChange={e => setDraftAgent({ ...draftAgent, description: e.target.value })}
                                                                className="w-full bg-zinc-950 border border-zinc-800 p-3 text-xs text-white focus:border-white focus:outline-none"
                                                            />
                                                        </div>
                                                        <div className="space-y-1">
                                                            <label className="text-[10px] font-bold text-zinc-500 uppercase">Agent Type</label>
                                                            <select
                                                                value={draftAgent.type || 'conversational'}
                                                                onChange={e => setDraftAgent({ ...draftAgent, type: e.target.value })}
                                                                className="w-full bg-zinc-950 border border-zinc-800 p-3 text-xs text-white focus:border-white focus:outline-none"
                                                            >
                                                                <option value="conversational">Conversational</option>
                                                                <option value="analysis">Analysis</option>
                                                                <option value="workflow">Workflow</option>
                                                            </select>
                                                            <p className="text-[9px] text-zinc-500 mt-1">Analysis agents support dynamic RAG for report tools</p>
                                                        </div>
                                                    </div>

                                                    {draftAgent.id === 'aurora' ? (
                                                        <div className="p-4 bg-blue-900/10 border border-blue-900/30 text-blue-300 text-xs text-center">
                                                            <div className="font-bold mb-1">System Managed</div>
                                                            The capabilities and brain of the default agent are managed by the core system for optimal business performance.
                                                        </div>
                                                    ) : (
                                                        <>
                                                            <div className="space-y-3">
                                                                <label className="text-[10px] font-bold text-zinc-500 uppercase">Capabilities (Tools)</label>
                                                                <div className="grid grid-cols-2 gap-4">
                                                                    {(() => {
                                                                        // Merge Built-in Capabilities with Custom Tools
                                                                        const customCaps = customTools.map(t => ({
                                                                            id: t.name,
                                                                            label: t.generalName || t.name,
                                                                            description: t.description,
                                                                            tools: [t.name],
                                                                            isCustom: true
                                                                        }));
                                                                        const allCaps = [...CAPABILITIES, ...customCaps];

                                                                        return allCaps.map(cap => {
                                                                            const isEnabled = draftAgent.tools.includes("all") || cap.tools.every(t => draftAgent.tools.includes(t));
                                                                            return (
                                                                                <div
                                                                                    key={cap.id}
                                                                                    onClick={() => {
                                                                                        if (draftAgent.tools.includes("all")) {
                                                                                            // Complex logic for "all", simplifying to disable "all" and just toggle this one
                                                                                            if (isEnabled) {
                                                                                                const allToolsFlat = CAPABILITIES.flatMap(c => c.tools).concat(customTools.map(t => t.name));
                                                                                                const newTools = allToolsFlat.filter(t => !cap.tools.includes(t));
                                                                                                setDraftAgent({ ...draftAgent, tools: newTools });
                                                                                            } else {
                                                                                                setDraftAgent({ ...draftAgent, tools: [...draftAgent.tools, ...cap.tools] });
                                                                                            }
                                                                                        } else {
                                                                                            if (isEnabled) {
                                                                                                const newTools = draftAgent.tools.filter((t: string) => !cap.tools.includes(t));
                                                                                                setDraftAgent({ ...draftAgent, tools: newTools });
                                                                                            } else {
                                                                                                setDraftAgent({ ...draftAgent, tools: [...draftAgent.tools, ...cap.tools] });
                                                                                            }
                                                                                        }
                                                                                    }}
                                                                                    className={`p-4 border cursor-pointer hover:border-zinc-500 transition-colors
                                                                                        ${isEnabled
                                                                                            ? 'bg-zinc-900 border-zinc-600'
                                                                                            : 'bg-black border-zinc-800 opacity-50'
                                                                                        }`}
                                                                                >
                                                                                    <div className="flex items-center gap-2">
                                                                                        <div className={`w-3 h-3 border ${isEnabled ? 'bg-green-500 border-green-500' : 'border-zinc-600'}`}></div>
                                                                                        <span className="text-xs font-bold text-white truncate">{cap.label}</span>
                                                                                        {/* @ts-ignore */}
                                                                                        {cap.isCustom && <span className="text-[9px] px-1 bg-zinc-800 text-zinc-400 rounded">CUSTOM</span>}
                                                                                    </div>
                                                                                    <p className="text-[9px] text-zinc-500 mt-1 pl-5 truncate">{cap.description}</p>
                                                                                </div>
                                                                            );
                                                                        });
                                                                    })()}
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
                                                        </>
                                                    )}
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

                                {/* CUSTOM TOOLS TAB */}
                                {activeTab === 'custom_tools' && (
                                    <div className="flex flex-col min-h-[600px]">
                                        {!draftTool ? (
                                            /* List View */
                                            <div className="space-y-4">
                                                <div className="flex justify-between items-center">
                                                    <div>
                                                        <h3 className="text-lg font-bold text-white flex items-center gap-2">
                                                            <Wrench className="h-5 w-5" /> Custom Tools
                                                        </h3>
                                                        <p className="text-zinc-500 text-sm">Extend your agent with n8n workflows or webhooks.</p>
                                                    </div>
                                                    <button
                                                        onClick={() => {
                                                            const initialInput = { type: "object", properties: { input: { type: "string" } } };
                                                            setDraftTool({
                                                                name: "",
                                                                generalName: "",
                                                                description: "",
                                                                url: "",
                                                                method: "POST",
                                                                inputSchema: initialInput,
                                                                inputSchemaStr: JSON.stringify(initialInput, null, 2),
                                                                outputSchemaStr: ""
                                                            });
                                                            setHeaderRows([{ id: 'h1', key: '', value: '' }]);
                                                        }}
                                                        className="px-4 py-2 bg-white text-black font-bold text-xs uppercase flex items-center gap-2 hover:bg-zinc-200"
                                                    >
                                                        <Plus className="h-4 w-4" /> Create Tool
                                                    </button>
                                                </div>

                                                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                                                    {customTools.map((t: any) => (
                                                        <div key={t.name} className="p-4 bg-zinc-900 border border-zinc-800 hover:border-zinc-600 transition-all group relative">
                                                            <div className="font-bold text-white mb-1 flex items-center gap-2">
                                                                {t.generalName || t.name}
                                                                {t.generalName && <span className="text-[9px] text-zinc-500 font-normal">({t.name})</span>}
                                                            </div>
                                                            <div className="text-xs text-zinc-500 mb-2 h-8 overflow-hidden">{t.description}</div>
                                                            <div className="text-[10px] font-mono text-zinc-600 truncate">{t.url}</div>
                                                            <button
                                                                onClick={() => handleDeleteTool(t.name)}
                                                                className="absolute top-2 right-2 p-1 text-zinc-600 hover:text-red-500 opacity-0 group-hover:opacity-100"
                                                            >
                                                                <Trash className="h-4 w-4" />
                                                            </button>
                                                            <button
                                                                onClick={() => {
                                                                    setDraftTool({
                                                                        ...t,
                                                                        inputSchemaStr: JSON.stringify(t.inputSchema || {}, null, 2),
                                                                        outputSchemaStr: t.outputSchema ? JSON.stringify(t.outputSchema, null, 2) : ""
                                                                    });
                                                                    // Populate headers
                                                                    const rows = Object.entries(t.headers || {}).map(([k, v], i) => ({
                                                                        id: `h-${i}`,
                                                                        key: k,
                                                                        value: v as string
                                                                    }));
                                                                    setHeaderRows(rows.length ? rows : [{ id: 'h1', key: '', value: '' }]);
                                                                }}
                                                                className="absolute bottom-2 right-2 text-[10px] text-zinc-400 hover:text-white font-bold uppercase"
                                                            >
                                                                Edit
                                                            </button>
                                                        </div>
                                                    ))}
                                                    {customTools.length === 0 && (
                                                        <div className="col-span-full py-12 text-center text-zinc-600 italic text-sm border border-dashed border-zinc-800">
                                                            No custom tools yet. Build one to connect n8n!
                                                        </div>
                                                    )}
                                                </div>
                                            </div>
                                        ) : (
                                            /* Builder View */
                                            <div className="flex flex-col h-full">
                                                <div className="flex items-center justify-between mb-4 pb-4 border-b border-zinc-800">
                                                    <div className="flex items-center gap-4">
                                                        <button onClick={() => { setDraftTool(null); setToolBuilderMode('config'); }} className="text-zinc-500 hover:text-white">
                                                            <X className="h-5 w-5" />
                                                        </button>
                                                        <h3 className="font-bold text-white uppercase tracking-wider">
                                                            {draftTool.name ? `Editing: ${draftTool.name}` : 'New Tool Builder'}
                                                        </h3>
                                                    </div>
                                                    <div className="flex gap-2">
                                                        <div className="flex bg-zinc-900 border border-zinc-800 p-1 rounded">
                                                            <button
                                                                onClick={() => setToolBuilderMode('config')}
                                                                className={`px-3 py-1 text-xs font-bold rounded ${toolBuilderMode === 'config' ? 'bg-zinc-700 text-white' : 'text-zinc-500 hover:text-zinc-300'}`}
                                                            >
                                                                CONFIG
                                                            </button>
                                                            <button
                                                                onClick={() => setToolBuilderMode('n8n')}
                                                                className={`px-3 py-1 text-xs font-bold rounded ${toolBuilderMode === 'n8n' ? 'bg-[#ff6d5a] text-white' : 'text-zinc-500 hover:text-zinc-300'}`}
                                                            >
                                                                n8n BUILDER
                                                            </button>
                                                        </div>
                                                        <button onClick={handleSaveTool} className="px-4 py-1.5 bg-white text-black text-xs font-bold hover:bg-zinc-200">
                                                            SAVE
                                                        </button>
                                                    </div>
                                                </div>

                                                {toolBuilderMode === 'config' ? (
                                                    <div className="space-y-6 pr-2">
                                                        <div className="grid grid-cols-2 gap-4">
                                                            <div className="space-y-1">
                                                                <label className="text-[10px] uppercase font-bold text-zinc-500">General Name</label>
                                                                <input type="text" value={draftTool.generalName || ''} onChange={e => {
                                                                    const val = e.target.value;
                                                                    const update: any = { ...draftTool, generalName: val };
                                                                    // Auto-fill snake_case functionality
                                                                    if (!draftTool.name) {
                                                                        update.name = val.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
                                                                    }
                                                                    setDraftTool(update);
                                                                }}
                                                                    className="w-full bg-zinc-900 border border-zinc-800 p-2 text-sm text-white focus:border-white focus:outline-none placeholder:text-zinc-700"
                                                                    placeholder="e.g. Create Jira Ticket" />
                                                            </div>
                                                            <div className="space-y-1">
                                                                <label className="text-[10px] uppercase font-bold text-zinc-500">System Name (Snake Case)</label>
                                                                <input type="text" value={draftTool.name} onChange={e => setDraftTool({ ...draftTool, name: e.target.value })}
                                                                    className="w-full bg-zinc-900 border border-zinc-800 p-2 text-sm text-white focus:border-white focus:outline-none font-mono placeholder:text-zinc-700" placeholder="e.g. create_jira_ticket" />
                                                            </div>
                                                            <div className="space-y-1">
                                                                <label className="text-[10px] uppercase font-bold text-zinc-500">Method</label>
                                                                <select value={draftTool.method} onChange={e => setDraftTool({ ...draftTool, method: e.target.value })}
                                                                    className="w-full bg-zinc-900 border border-zinc-800 p-2 text-sm text-white focus:border-white focus:outline-none">
                                                                    <option>POST</option>
                                                                    <option>GET</option>
                                                                </select>
                                                            </div>
                                                            <div className="space-y-1">
                                                                <label className="text-[10px] uppercase font-bold text-zinc-500">Tool Type</label>
                                                                <select value={draftTool.tool_type || 'standard'} onChange={e => setDraftTool({ ...draftTool, tool_type: e.target.value })}
                                                                    className="w-full bg-zinc-900 border border-zinc-800 p-2 text-sm text-white focus:border-white focus:outline-none">
                                                                    <option value="standard">Standard</option>
                                                                    <option value="report">Report (Supports RAG)</option>
                                                                </select>
                                                                <p className="text-[9px] text-zinc-500">Report tools enable dynamic RAG for analysis agents</p>
                                                            </div>
                                                        </div>

                                                        <div className="space-y-1 col-span-2">
                                                            <label className="text-[10px] uppercase font-bold text-zinc-500">Description (For AI)</label>
                                                            <textarea 
                                                                value={draftTool.description} 
                                                                onChange={e => setDraftTool({ ...draftTool, description: e.target.value })}
                                                                className="w-full bg-zinc-900 border border-zinc-800 p-2 text-sm text-white focus:border-white focus:outline-none resize-vertical min-h-[100px]"
                                                                placeholder="What does this tool do? Describe its purpose, workflow, and critical rules..."
                                                            />
                                                            <p className="text-[10px] text-zinc-600">Provide detailed instructions for the AI on how to use this tool correctly.</p>
                                                        </div>

                                                        {draftTool.tool_type === 'report' && (
                                                            <div className="space-y-1 col-span-2">
                                                                <label className="text-[10px] uppercase font-bold text-zinc-500">Field Descriptions (JSON)</label>
                                                                <textarea 
                                                                    value={typeof draftTool.field_descriptions === 'string' ? draftTool.field_descriptions : JSON.stringify(draftTool.field_descriptions || [], null, 2)}
                                                                    onChange={e => setDraftTool({ ...draftTool, field_descriptions: e.target.value })}
                                                                    className="w-full bg-zinc-900 border border-zinc-800 p-2 text-xs font-mono text-zinc-300 focus:border-white focus:outline-none resize-vertical min-h-[150px]"
                                                                    placeholder={JSON.stringify([
                                                                        {
                                                                            type: "delinquency",
                                                                            fields: {
                                                                                tenant_id: "Unique identifier for tenant",
                                                                                balance_due: "Outstanding balance amount"
                                                                            }
                                                                        }
                                                                    ], null, 2)}
                                                                />
                                                                <p className="text-[10px] text-zinc-600">Define field descriptions for each report type. Only relevant types are sent to LLM.</p>
                                                            </div>
                                                        )}


                                                        <div className="space-y-1">
                                                            <label className="text-[10px] uppercase font-bold text-zinc-500">n8n Workflow</label>
                                                            <select
                                                                value={draftTool.workflowId || ''}
                                                                onChange={async (e) => {
                                                                    const workflowId = e.target.value;
                                                                    setDraftTool({ ...draftTool, workflowId });
                                                                    setN8nWorkflowId(workflowId || null);
                                                                    if (!workflowId) return;
                                                                    try {
                                                                        const res = await fetch(`/api/n8n/workflows/${workflowId}/webhook`);
                                                                        if (!res.ok) return;
                                                                        const data = await res.json();
                                                                        if (data?.productionUrl) {
                                                                            setDraftTool({ ...draftTool, workflowId, url: data.productionUrl });
                                                                        }
                                                                    } catch {
                                                                        // ignore
                                                                    }
                                                                }}
                                                                className="w-full bg-zinc-900 border border-zinc-800 p-2 text-sm text-white focus:border-white focus:outline-none"
                                                            >
                                                                <option value="">{n8nWorkflowsLoading ? 'Loading workflows...' : 'Select a workflow (optional)'}</option>
                                                                {Array.isArray(n8nWorkflows) && n8nWorkflows.map((w: any) => (
                                                                    <option key={String(w.id)} value={String(w.id)}>
                                                                        {w.name || w.id}
                                                                    </option>
                                                                ))}
                                                            </select>
                                                            <p className="text-[10px] text-zinc-600">
                                                                Configure n8n in Integrations to enable workflow listing.
                                                            </p>
                                                        </div>

                                                        <div className="space-y-1">
                                                            <div className="flex items-center gap-2">
                                                                <label className="text-[10px] uppercase font-bold text-zinc-500">Webhook URL</label>
                                                                <div className="group relative">
                                                                    <svg className="w-3.5 h-3.5 text-zinc-600 hover:text-[#ff6d5a] cursor-help" fill="currentColor" viewBox="0 0 20 20">
                                                                        <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-8-3a1 1 0 00-.867.5 1 1 0 11-1.731-1A3 3 0 0113 8a3.001 3.001 0 01-2 2.83V11a1 1 0 11-2 0v-1a1 1 0 011-1 1 1 0 100-2zm0 8a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
                                                                    </svg>
                                                                    {/* Tooltip */}
                                                                    <div className="invisible group-hover:visible absolute left-0 top-6 w-72 p-3 bg-zinc-900 border border-zinc-700 text-[10px] text-zinc-300 z-50 shadow-xl">
                                                                        <p className="font-bold text-[#ff6d5a] mb-2">💡 Quick Setup:</p>
                                                                        <ol className="list-decimal list-inside space-y-1 pl-1">
                                                                            <li>Click <span className="font-bold">n8n BUILDER</span> tab</li>
                                                                            <li>Add <span className="font-mono bg-zinc-800 px-1">Webhook</span> node</li>
                                                                            <li>Set webhook path</li>
                                                                            <li>Build workflow &amp; Save</li>
                                                                            <li>URL auto-populates here!</li>
                                                                        </ol>
                                                                    </div>
                                                                </div>
                                                            </div>
                                                            <input type="text" value={draftTool.url} onChange={e => setDraftTool({ ...draftTool, url: e.target.value })}
                                                                className="w-full bg-zinc-900 border border-zinc-800 p-2 text-sm text-white focus:border-white focus:outline-none font-mono"
                                                                placeholder="http://localhost:5678/webhook/..." />
                                                        </div>

                                                        <div className="space-y-2 pt-2">
                                                            <div className="flex justify-between items-end mb-1">
                                                                <label className="text-[10px] uppercase font-bold text-zinc-500">Headers</label>
                                                                <button
                                                                    onClick={() => setHeaderRows([...headerRows, { id: `h-${Date.now()}`, key: '', value: '' }])}
                                                                    className="text-[10px] text-zinc-400 hover:text-white font-bold bg-zinc-800 px-2 py-1 rounded transition-colors"
                                                                >
                                                                    + ADD HEADER
                                                                </button>
                                                            </div>
                                                            {headerRows.map((row, idx) => (
                                                                <div key={row.id} className="flex gap-2 items-center">
                                                                    <input
                                                                        type="text"
                                                                        placeholder="Key (e.g. Authorization)"
                                                                        value={row.key}
                                                                        onChange={e => {
                                                                            const newRows = [...headerRows];
                                                                            newRows[idx].key = e.target.value;
                                                                            setHeaderRows(newRows);
                                                                        }}
                                                                        className="flex-1 bg-zinc-900 border border-zinc-800 p-2 text-sm text-white focus:border-white focus:outline-none font-mono"
                                                                    />
                                                                    <input
                                                                        type="text"
                                                                        placeholder="Value"
                                                                        value={row.value}
                                                                        onChange={e => {
                                                                            const newRows = [...headerRows];
                                                                            newRows[idx].value = e.target.value;
                                                                            setHeaderRows(newRows);
                                                                        }}
                                                                        className="flex-1 bg-zinc-900 border border-zinc-800 p-2 text-sm text-white focus:border-white focus:outline-none font-mono"
                                                                    />
                                                                    <button
                                                                        onClick={() => setHeaderRows(headerRows.filter(r => r.id !== row.id))}
                                                                        className="p-2 text-zinc-600 hover:text-red-500 transition-colors"
                                                                    >
                                                                        <Trash className="h-4 w-4" />
                                                                    </button>
                                                                </div>
                                                            ))}
                                                        </div>
                                                        <div className="grid grid-cols-2 gap-4 flex-1 min-h-0">
                                                            <div className="space-y-1 flex flex-col min-h-[280px]">
                                                                <label className="text-[10px] uppercase font-bold text-zinc-500">Input Schema (JSON)</label>
                                                                <textarea
                                                                    value={draftTool.inputSchemaStr}
                                                                    onChange={e => setDraftTool({ ...draftTool, inputSchemaStr: e.target.value })}
                                                                    className="w-full flex-1 bg-zinc-950 border border-zinc-800 p-3 text-[10px] font-mono text-zinc-300 focus:border-white focus:outline-none resize-none"
                                                                    placeholder='{"type": "object", "properties": {"msg": {"type": "string"}}}'
                                                                />
                                                            </div>
                                                            <div className="space-y-1 flex flex-col min-h-[280px]">
                                                                <label className="text-[10px] uppercase font-bold text-zinc-500">Output Schema (JSON)</label>
                                                                <textarea
                                                                    value={draftTool.outputSchemaStr}
                                                                    onChange={e => setDraftTool({ ...draftTool, outputSchemaStr: e.target.value })}
                                                                    className="w-full flex-1 bg-zinc-900 border border-zinc-800 p-3 text-[10px] font-mono text-zinc-300 focus:border-white focus:outline-none resize-none"
                                                                    placeholder='(Optional) {"properties": {"id": {"type": "string"}}} - Filters response to these keys.'
                                                                />
                                                            </div>
                                                        </div>
                                                    </div>
                                                ) : (
                                                    <div className="h-[600px] bg-white relative overflow-hidden border border-zinc-800">
                                                        {/* Workflow ID Display - Bottom Left */}
                                                        {draftTool.workflowId && (
                                                            <div className="absolute bottom-4 left-4 z-20 flex items-center gap-2 bg-zinc-900 border border-zinc-700 p-1.5 rounded shadow-lg">
                                                                <div className="px-1 text-[10px] font-bold text-zinc-500 uppercase tracking-wider">ID:</div>
                                                                <code className="text-xs text-white font-mono">{draftTool.workflowId}</code>
                                                                <button
                                                                    onClick={() => navigator.clipboard.writeText(draftTool.workflowId || '')}
                                                                    className="p-1 hover:bg-zinc-800 text-zinc-400 hover:text-white rounded"
                                                                    title="Copy ID"
                                                                >
                                                                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
                                                                </button>
                                                            </div>
                                                        )}


                                                        {/* Fullscreen Toggle Button - Bottom Right */}
                                                        <button
                                                            onClick={() => setIsIframeFullscreen(!isIframeFullscreen)}
                                                            className="absolute bottom-4 right-4 z-20 p-2 bg-zinc-900 hover:bg-zinc-800 text-white rounded border border-zinc-700 flex items-center gap-2 text-xs font-bold shadow-lg"
                                                            title={isIframeFullscreen ? "Exit Fullscreen" : "Enter Fullscreen"}
                                                        >
                                                            {isIframeFullscreen ? (
                                                                <>
                                                                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                                                    </svg>
                                                                    Exit Fullscreen
                                                                </>
                                                            ) : (
                                                                <>
                                                                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
                                                                    </svg>
                                                                    Fullscreen
                                                                </>
                                                            )}
                                                        </button>

                                                        {/* Loading message - only show when not fullscreen */}
                                                        {!isIframeFullscreen && isN8nLoading && (
                                                            <div className="absolute inset-0 flex items-center justify-center text-black/50 z-0">
                                                                <div className="text-center">
                                                                    <p className="font-bold">Loading n8n Editor...</p>
                                                                    <p className="text-xs">Ensure n8n is running at {getN8nBaseUrl()}</p>
                                                                </div>
                                                            </div>
                                                        )}

                                                        {/* n8n iframe - normal view */}
                                                        {!isIframeFullscreen && (
                                                            <iframe
                                                                onLoad={() => setIsN8nLoading(false)}
                                                                src={
                                                                    (() => {
                                                                        const base = getN8nBaseUrl();
                                                                        if (draftTool?.workflowId) return `${base}/workflow/${draftTool.workflowId}`;
                                                                        return `${base}/workflow/new`;
                                                                    })()
                                                                }
                                                                ref={n8nIframeRef}
                                                                className="w-full h-full z-10"
                                                                title="n8n Editor"
                                                                allow="clipboard-read; clipboard-write"
                                                                sandbox="allow-forms allow-modals allow-popups allow-presentation allow-same-origin allow-scripts"
                                                            />
                                                        )}
                                                    </div>
                                                )}
                                            </div>
                                        )}
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
                                            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
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

                                                <label className={`relative flex flex-col p-4 cursor-pointer border transition-all duration-200
                                                    ${mode === 'bedrock'
                                                        ? 'bg-zinc-900 border-white ring-1 ring-white/20'
                                                        : 'bg-zinc-950 border-zinc-800 hover:border-zinc-700 hover:bg-zinc-900/50'}`}>
                                                    <input
                                                        type="radio"
                                                        name="mode"
                                                        value="bedrock"
                                                        checked={mode === 'bedrock'}
                                                        onChange={() => {
                                                            setMode('bedrock');
                                                            const bedrockModels = cloudModels.filter(m => m.startsWith('bedrock'));
                                                            if (bedrockModels.length > 0 && !bedrockModels.includes(selectedModel)) setSelectedModel(bedrockModels[0]);
                                                        }}
                                                        className="sr-only"
                                                    />
                                                    <div className="flex items-center gap-2 mb-2">
                                                        <Database className={`h-5 w-5 ${mode === 'bedrock' ? 'text-white' : 'text-zinc-500'}`} />
                                                        <span className={`font-bold ${mode === 'bedrock' ? 'text-white' : 'text-zinc-400'}`}>AWS Bedrock</span>
                                                    </div>
                                                    <p className="text-xs text-zinc-500 leading-relaxed">Enterprise-grade models via AWS. Uses a Bedrock API key (ABSK...) and Region.</p>
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

                                        {mode === 'bedrock' && (
                                            <div className="space-y-6 pt-6 border-t border-zinc-800/50">
                                                <h3 className="text-sm font-bold text-white mb-4">AWS Bedrock Configuration</h3>
                                                <div className="space-y-2">
                                                    <label className="text-[10px] uppercase font-bold text-zinc-500">Bedrock API Key</label>
                                                    <input type="password" value={bedrockApiKey} onChange={e => setBedrockApiKey(e.target.value)}
                                                        className="w-full bg-zinc-900 border border-zinc-800 p-3 text-xs text-white focus:border-white focus:outline-none transition-colors" placeholder="ABSK..." />
                                                    <p className="text-[10px] text-zinc-500 leading-relaxed">Paste the raw key (starts with ABSK...). You can also paste "Bearer ABSK..." and it will be normalized.</p>
                                                </div>
                                                <div className="space-y-2">
                                                    <label className="text-[10px] uppercase font-bold text-zinc-500">AWS Region</label>
                                                    <input type="text" value={awsRegion} onChange={e => setAwsRegion(e.target.value)}
                                                        className="w-full bg-zinc-900 border border-zinc-800 p-3 text-xs text-white focus:border-white focus:outline-none transition-colors" placeholder="us-east-1" />
                                                </div>
                                                <div className="space-y-2">
                                                    <label className="text-[10px] uppercase font-bold text-zinc-500">Inference Profile (Optional)</label>
                                                    <select
                                                        value={bedrockInferenceProfile}
                                                        onChange={(e) => setBedrockInferenceProfile(e.target.value)}
                                                        className="w-full appearance-none bg-zinc-900 border border-zinc-800 p-3 text-xs focus:border-white focus:outline-none transition-colors text-white cursor-pointer"
                                                    >
                                                        <option value="">None (on-demand)</option>
                                                        {loadingInferenceProfiles ? (
                                                            <option value="" disabled>Loading inference profiles...</option>
                                                        ) : (
                                                            bedrockInferenceProfiles.map((p) => {
                                                                const value = (p.arn || p.id || '').toString();
                                                                const label = (p.name || p.arn || p.id || '').toString();
                                                                if (!value) return null;
                                                                return (
                                                                    <option key={value} value={value}>
                                                                        {label}
                                                                    </option>
                                                                );
                                                            })
                                                        )}
                                                    </select>
                                                    <p className="text-[10px] text-zinc-500 leading-relaxed">Required for some Bedrock models that don't support on-demand throughput. Select an inference profile ARN/ID that includes your chosen model.</p>
                                                </div>
                                            </div>
                                        )}
                                        <div className="pt-4 flex justify-end">
                                            <button
                                                onClick={handleSaveSection}
                                                className="px-6 py-2.5 text-sm font-bold bg-white text-black hover:bg-zinc-200 transition-all shadow-lg"
                                            >
                                                Save Changes
                                            </button>
                                        </div>
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

                                        {/* n8n Integration */}
                                        <div className="bg-zinc-900 border border-zinc-800 overflow-hidden">
                                            <div className="p-4 border-b border-zinc-800 bg-zinc-950 flex items-center justify-between">
                                                <div className="flex items-center gap-3">
                                                    <div className={`h-2 w-2 ${n8nApiKey ? 'bg-green-500' : 'bg-red-500'}`} />
                                                    <span className="text-sm font-bold text-zinc-400">n8n</span>
                                                </div>
                                                <span className={`text-xs px-2 py-1 bg-zinc-900 border border-zinc-800 ${n8nApiKey ? 'text-green-400' : 'text-zinc-500'}`}>
                                                    {n8nApiKey ? 'CONFIGURED' : 'NOT CONFIGURED'}
                                                </span>
                                            </div>
                                            <div className="p-6 space-y-6">
                                                <div className="space-y-2">
                                                    <label className="text-xs uppercase font-bold text-zinc-500 tracking-wider">n8n URL</label>
                                                    <input
                                                        type="text"
                                                        value={n8nUrl}
                                                        onChange={(e) => setN8nUrl(e.target.value)}
                                                        className="w-full bg-zinc-900 border border-zinc-800 p-3 text-sm text-white focus:border-white focus:outline-none transition-colors font-mono"
                                                        placeholder="http://localhost:5678"
                                                    />
                                                    <p className="text-xs text-zinc-600">Defaults to localhost for local dev. Use your production n8n base URL in deployment.</p>
                                                </div>
                                                <div className="space-y-2">
                                                    <label className="text-xs uppercase font-bold text-zinc-500 tracking-wider">n8n API Key</label>
                                                    <input
                                                        type="password"
                                                        value={n8nApiKey}
                                                        onChange={(e) => setN8nApiKey(e.target.value)}
                                                        className="w-full bg-zinc-900 border border-zinc-800 p-3 text-sm text-white focus:border-white focus:outline-none transition-colors font-mono"
                                                        placeholder="X-N8N-API-KEY"
                                                    />
                                                    <p className="text-xs text-zinc-600">Used server-side to list workflows and derive webhook URLs.</p>
                                                </div>

                                                <div className="space-y-4 pt-4 border-t border-zinc-800">
                                                    <div className="flex items-center justify-between">
                                                        <div>
                                                            <h4 className="text-xs uppercase font-bold text-zinc-500 tracking-wider">Global Configuration Variables</h4>
                                                            <p className="text-xs text-zinc-600 mt-1">These values are synced to the 'global_config' data table in n8n.</p>
                                                        </div>
                                                        <button
                                                            onClick={() => setGlobalConfig([...globalConfig, { id: Math.random().toString(36).substr(2, 9), key: '', value: '' }])}
                                                            className="flex items-center gap-1.5 px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-white text-[10px] font-bold uppercase transition-colors"
                                                        >
                                                            <Plus className="h-3 w-3" /> Add Variable
                                                        </button>
                                                    </div>

                                                    <div className="space-y-2">
                                                        {globalConfig.length === 0 ? (
                                                            <div className="text-center py-4 bg-zinc-950 border border-zinc-800 border-dashed text-zinc-600 text-xs italic">
                                                                No global variables configured.
                                                            </div>
                                                        ) : (
                                                            <div className="space-y-2">
                                                                {globalConfig.map((item, idx) => (
                                                                    <div key={item.id} className="flex gap-2 items-start animate-in fade-in slide-in-from-left-2 duration-200">
                                                                        <input
                                                                            type="text"
                                                                            value={item.key}
                                                                            onChange={(e) => {
                                                                                const newConfig = [...globalConfig];
                                                                                newConfig[idx].key = e.target.value;
                                                                                setGlobalConfig(newConfig);
                                                                            }}
                                                                            placeholder="Key (e.g. USER_ID)"
                                                                            className="flex-1 bg-zinc-950 border border-zinc-800 p-2 text-xs text-white focus:border-white focus:outline-none font-mono placeholder:text-zinc-700"
                                                                        />
                                                                        <input
                                                                            type="text"
                                                                            value={item.value}
                                                                            onChange={(e) => {
                                                                                const newConfig = [...globalConfig];
                                                                                newConfig[idx].value = e.target.value;
                                                                                setGlobalConfig(newConfig);
                                                                            }}
                                                                            placeholder="Value"
                                                                            className="flex-[2] bg-zinc-950 border border-zinc-800 p-2 text-xs text-white focus:border-white focus:outline-none font-mono placeholder:text-zinc-700"
                                                                        />
                                                                        <button
                                                                            onClick={() => setGlobalConfig(globalConfig.filter(i => i.id !== item.id))}
                                                                            className="p-2 text-zinc-600 hover:text-red-500 hover:bg-zinc-900 transition-colors"
                                                                            title="Remove variable"
                                                                        >
                                                                            <Trash className="h-3.5 w-3.5" />
                                                                        </button>
                                                                    </div>
                                                                ))}
                                                            </div>
                                                        )}
                                                    </div>

                                                </div>
                                                <div className="pt-2 flex justify-end">
                                                    <button
                                                        onClick={handleSaveSection}
                                                        className="px-6 py-2.5 text-sm font-bold bg-white text-black hover:bg-zinc-200 transition-all shadow-lg"
                                                    >
                                                        Save Changes
                                                    </button>
                                                </div>
                                            </div>
                                        </div>

                                        {/* Google Maps Integration */}
                                        <div className="bg-zinc-900 border border-zinc-800 overflow-hidden">
                                            <div className="p-4 border-b border-zinc-800 bg-zinc-950 flex items-center justify-between">
                                                <div className="flex items-center gap-3">
                                                    <div className={`h-2 w-2 ${googleMapsApiKey ? 'bg-green-500' : 'bg-red-500'}`} />
                                                    <span className="text-sm font-bold text-zinc-400">Google Maps</span>
                                                </div>
                                                <span className={`text-xs px-2 py-1 bg-zinc-900 border border-zinc-800 ${googleMapsApiKey ? 'text-green-400' : 'text-zinc-500'}`}>
                                                    {googleMapsApiKey ? 'CONFIGURED' : 'NOT CONFIGURED'}
                                                </span>
                                            </div>
                                            <div className="p-6 space-y-6">
                                                <div className="space-y-2">
                                                    <label className="text-xs uppercase font-bold text-zinc-500 tracking-wider">Maps API Key</label>
                                                    <input
                                                        type="password"
                                                        value={googleMapsApiKey}
                                                        onChange={(e) => setGoogleMapsApiKey(e.target.value)}
                                                        className="w-full bg-zinc-900 border border-zinc-800 p-3 text-sm text-white focus:border-white focus:outline-none transition-colors font-mono"
                                                        placeholder="AIza..."
                                                    />
                                                    <p className="text-xs text-zinc-600">Used server-side for map distance calculations (Distance Matrix API).</p>
                                                </div>

                                                <div className="pt-2 flex justify-end">
                                                    <button
                                                        onClick={handleSaveSection}
                                                        className="px-6 py-2.5 text-sm font-bold bg-white text-black hover:bg-zinc-200 transition-all shadow-lg"
                                                    >
                                                        Save Changes
                                                    </button>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                )}

                                {/* PERSONAL DETAILS TAB */}
                                {activeTab === 'personal_details' && (
                                    <div className="space-y-8">
                                        <div className="mb-4">
                                            <h3 className="text-lg font-bold text-white flex items-center gap-2">
                                                <Shield className="h-5 w-5" />
                                                Personal Details
                                            </h3>
                                            <p className="text-zinc-500 text-sm mt-1">
                                                Saved details the agent can use when completing workflows.
                                            </p>
                                        </div>

                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                            <div className="space-y-2">
                                                <label className="text-xs uppercase font-bold text-zinc-500 tracking-wider">First Name</label>
                                                <input
                                                    type="text"
                                                    value={pdFirstName}
                                                    onChange={(e) => setPdFirstName(e.target.value)}
                                                    className="w-full bg-zinc-900 border border-zinc-800 p-3 text-sm text-white focus:border-white focus:outline-none transition-colors"
                                                    placeholder="First name"
                                                />
                                            </div>
                                            <div className="space-y-2">
                                                <label className="text-xs uppercase font-bold text-zinc-500 tracking-wider">Last Name</label>
                                                <input
                                                    type="text"
                                                    value={pdLastName}
                                                    onChange={(e) => setPdLastName(e.target.value)}
                                                    className="w-full bg-zinc-900 border border-zinc-800 p-3 text-sm text-white focus:border-white focus:outline-none transition-colors"
                                                    placeholder="Last name"
                                                />
                                            </div>
                                            <div className="space-y-2">
                                                <label className="text-xs uppercase font-bold text-zinc-500 tracking-wider">Email</label>
                                                <input
                                                    type="email"
                                                    value={pdEmail}
                                                    onChange={(e) => setPdEmail(e.target.value)}
                                                    className="w-full bg-zinc-900 border border-zinc-800 p-3 text-sm text-white focus:border-white focus:outline-none transition-colors font-mono"
                                                    placeholder="name@company.com"
                                                />
                                            </div>
                                            <div className="space-y-2">
                                                <label className="text-xs uppercase font-bold text-zinc-500 tracking-wider">Phone Number</label>
                                                <input
                                                    type="tel"
                                                    value={pdPhone}
                                                    onChange={(e) => setPdPhone(e.target.value)}
                                                    className="w-full bg-zinc-900 border border-zinc-800 p-3 text-sm text-white focus:border-white focus:outline-none transition-colors font-mono"
                                                    placeholder="+1 555 555 5555"
                                                />
                                            </div>
                                        </div>

                                        <div className="border border-zinc-800 bg-zinc-900/20 p-6 space-y-6">
                                            <div>
                                                <div className="text-sm font-bold text-white">Address</div>
                                                <div className="text-xs text-zinc-500">Used when a workflow needs a billing or mailing address.</div>
                                            </div>

                                            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                                <div className="space-y-2">
                                                    <label className="text-xs uppercase font-bold text-zinc-500 tracking-wider">Address 1</label>
                                                    <input
                                                        type="text"
                                                        value={pdAddress1}
                                                        onChange={(e) => setPdAddress1(e.target.value)}
                                                        className="w-full bg-zinc-900 border border-zinc-800 p-3 text-sm text-white focus:border-white focus:outline-none transition-colors"
                                                        placeholder="Street address"
                                                    />
                                                </div>
                                                <div className="space-y-2">
                                                    <label className="text-xs uppercase font-bold text-zinc-500 tracking-wider">Address 2</label>
                                                    <input
                                                        type="text"
                                                        value={pdAddress2}
                                                        onChange={(e) => setPdAddress2(e.target.value)}
                                                        className="w-full bg-zinc-900 border border-zinc-800 p-3 text-sm text-white focus:border-white focus:outline-none transition-colors"
                                                        placeholder="Apt, suite, unit"
                                                    />
                                                </div>
                                                <div className="space-y-2">
                                                    <label className="text-xs uppercase font-bold text-zinc-500 tracking-wider">City</label>
                                                    <input
                                                        type="text"
                                                        value={pdCity}
                                                        onChange={(e) => setPdCity(e.target.value)}
                                                        className="w-full bg-zinc-900 border border-zinc-800 p-3 text-sm text-white focus:border-white focus:outline-none transition-colors"
                                                        placeholder="City"
                                                    />
                                                </div>
                                                <div className="space-y-2">
                                                    <label className="text-xs uppercase font-bold text-zinc-500 tracking-wider">State</label>
                                                    <input
                                                        type="text"
                                                        value={pdState}
                                                        onChange={(e) => setPdState(e.target.value)}
                                                        className="w-full bg-zinc-900 border border-zinc-800 p-3 text-sm text-white focus:border-white focus:outline-none transition-colors"
                                                        placeholder="State"
                                                    />
                                                </div>
                                                <div className="space-y-2">
                                                    <label className="text-xs uppercase font-bold text-zinc-500 tracking-wider">Zipcode</label>
                                                    <input
                                                        type="text"
                                                        value={pdZipcode}
                                                        onChange={(e) => setPdZipcode(e.target.value)}
                                                        className="w-full bg-zinc-900 border border-zinc-800 p-3 text-sm text-white focus:border-white focus:outline-none transition-colors font-mono"
                                                        placeholder="Zipcode"
                                                    />
                                                </div>
                                            </div>
                                        </div>

                                        <div className="pt-2 flex justify-end">
                                            <button
                                                onClick={handleSavePersonalDetails}
                                                className="px-6 py-2.5 text-sm font-bold bg-white text-black hover:bg-zinc-200 transition-all shadow-lg"
                                            >
                                                Save Changes
                                            </button>
                                        </div>
                                    </div>
                                )}

                                {/* DATABASE TAB */}
                                {activeTab === 'database' && (
                                    <div className="space-y-8">
                                        <div className="mb-4">
                                            <h3 className="text-lg font-bold text-white flex items-center gap-2">
                                                <Database className="h-5 w-5" />
                                                SQL Database Connection
                                            </h3>
                                            <p className="text-zinc-500 text-sm mt-1">
                                                Connect your agent to a SQL database (PostgreSQL, MySQL, SQLite) to enable business intelligence capabilities.
                                            </p>
                                        </div>

                                        <div className="space-y-4">
                                            <div className="space-y-2">
                                                <label className="text-xs uppercase font-bold text-zinc-500 tracking-wider">Connection String (SQLAlchemy URL)</label>
                                                <input
                                                    type="password"
                                                    value={sqlConnectionString}
                                                    onChange={(e) => setSqlConnectionString(e.target.value)}
                                                    className="w-full bg-zinc-900 border border-zinc-800 p-3 text-sm text-white focus:border-white focus:outline-none transition-colors font-mono"
                                                    placeholder="postgresql://user:password@localhost:5432/dbname"
                                                />
                                                <p className="text-xs text-zinc-600">
                                                    Format: <code>dialect+driver://username:password@host:port/database</code><br />
                                                    Examples:<br />
                                                    - Postgres: <code>postgresql://scott:tiger@localhost/test</code><br />
                                                    - MySQL: <code>mysql+pymysql://user:pass@localhost/foo</code><br />
                                                    - SQLite: <code>sqlite:///foo.db</code>
                                                </p>
                                            </div>

                                            <div className="p-4 bg-zinc-900/50 border border-zinc-800 text-xs text-zinc-400">
                                                <strong>Security Note:</strong> The agent will have access to execute queries. Use a read-only user if possible.
                                            </div>
                                        </div>
                                        <div className="pt-4 flex justify-end">
                                            <button
                                                onClick={handleSaveSection}
                                                className="px-6 py-2.5 text-sm font-bold bg-white text-black hover:bg-zinc-200 transition-all shadow-lg"
                                            >
                                                Save Changes
                                            </button>
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
                        {/* Footer Removed - Per-section save applied */}
                    </div>
                </div>
            </div >

            {/* Toast Notification */}
            {
                showToast && (
                    <div className="fixed top-8 left-1/2 -translate-x-1/2 z-[100] bg-green-500 text-black px-6 py-2 rounded-full shadow-2xl font-bold text-xs uppercase animate-in fade-in slide-in-from-top-4 duration-300 flex items-center gap-2">
                        <div className="h-2 w-2 bg-black rounded-full animate-pulse"></div>
                        Configuration Saved
                    </div>
                )
            }


            {/* Custom Confirmation Modal */}
            {
                confirmAction && (
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
                )
            }

            {/* Fullscreen n8n Iframe Overlay - Rendered outside modal to avoid clipping */}
            {
                isIframeFullscreen && toolBuilderMode === 'n8n' && draftTool && (
                    <div className="fixed inset-0 z-[200] bg-white">
                        {/* Exit Fullscreen Button - Bottom position */}
                        <button
                            onClick={() => setIsIframeFullscreen(false)}
                            className="absolute bottom-4 right-4 z-[210] p-3 bg-zinc-900 hover:bg-zinc-800 text-white rounded border border-zinc-700 flex items-center gap-2 text-sm font-bold shadow-2xl"
                        >
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                            Exit Fullscreen
                        </button>

                        {/* Fullscreen iframe */}
                        <iframe
                            src={
                                (() => {
                                    const base = getN8nBaseUrl();
                                    if (draftTool?.workflowId) return `${base}/workflow/${draftTool.workflowId}`;
                                    return `${base}/workflow/new`;
                                })()
                            }
                            className="w-full h-full"
                            title="n8n Editor Fullscreen"
                            allow="clipboard-read; clipboard-write"
                            sandbox="allow-forms allow-modals allow-popups allow-presentation allow-same-origin allow-scripts"
                        />
                    </div>
                )
            }
        </>
    );
};
