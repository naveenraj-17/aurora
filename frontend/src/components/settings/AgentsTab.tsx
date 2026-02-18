/* eslint-disable @typescript-eslint/no-explicit-any */
import { Bot, Plus, Save, Trash } from 'lucide-react';
import { CAPABILITIES } from './types';

interface AgentsTabProps {
    agents: any[];
    selectedAgentId: string | null;
    setSelectedAgentId: (id: string | null) => void;
    draftAgent: any;
    setDraftAgent: (agent: any) => void;
    availableCapabilities: any[];
    customTools: any[];
    onSaveAgent: () => void;
    onDeleteAgent: (id: string) => void;
}

export const AgentsTab = ({
    agents, selectedAgentId, setSelectedAgentId,
    draftAgent, setDraftAgent, availableCapabilities, customTools,
    onSaveAgent, onDeleteAgent
}: AgentsTabProps) => (
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
                                    onDeleteAgent(a.id);
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
                            onClick={onSaveAgent}
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
                                        // Use availableCapabilities which includes MCP and Custom tools
                                        // Filter out duplicates if any (though grouping should handle it)
                                        const allCaps = availableCapabilities;

                                        return allCaps.map(cap => {
                                            const isEnabled = draftAgent.tools.includes("all") || cap.tools.every((t: string) => draftAgent.tools.includes(t));
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
                                                        {cap.toolType === 'custom' && <span className="text-[9px] px-1 bg-zinc-800 text-zinc-400 rounded">CUSTOM</span>}
                                                        {cap.toolType === 'mcp' && <span className="text-[9px] px-1 bg-blue-900/50 text-blue-400 border border-blue-900 rounded">MCP</span>}
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
);
