/* eslint-disable @typescript-eslint/no-explicit-any */
import { Settings, Cpu, Cloud, Shield, Database } from 'lucide-react';

interface ModelsTabProps {
    mode: string; setMode: (v: string) => void;
    selectedModel: string; setSelectedModel: (v: string) => void;
    localModels: string[]; cloudModels: string[];
    filteredModels: string[];
    loadingModels: boolean;
    openaiKey: string; setOpenaiKey: (v: string) => void;
    anthropicKey: string; setAnthropicKey: (v: string) => void;
    geminiKey: string; setGeminiKey: (v: string) => void;
    bedrockApiKey: string; setBedrockApiKey: (v: string) => void;
    awsRegion: string; setAwsRegion: (v: string) => void;
    bedrockInferenceProfile: string; setBedrockInferenceProfile: (v: string) => void;
    bedrockInferenceProfiles: any[];
    loadingInferenceProfiles: boolean;
    onSave: () => void;
}

export const ModelsTab = ({
    mode, setMode, selectedModel, setSelectedModel,
    localModels, cloudModels, filteredModels, loadingModels,
    openaiKey, setOpenaiKey, anthropicKey, setAnthropicKey,
    geminiKey, setGeminiKey, bedrockApiKey, setBedrockApiKey,
    awsRegion, setAwsRegion, bedrockInferenceProfile, setBedrockInferenceProfile,
    bedrockInferenceProfiles, loadingInferenceProfiles, onSave
}: ModelsTabProps) => (
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
                    <p className="text-[10px] text-zinc-500 leading-relaxed">Paste the raw key (starts with ABSK...). You can also paste &quot;Bearer ABSK...&quot; and it will be normalized.</p>
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
                    <p className="text-[10px] text-zinc-500 leading-relaxed">Required for some Bedrock models that don&apos;t support on-demand throughput. Select an inference profile ARN/ID that includes your chosen model.</p>
                </div>
            </div>
        )}
        <div className="pt-4 flex justify-end">
            <button
                onClick={onSave}
                className="px-6 py-2.5 text-sm font-bold bg-white text-black hover:bg-zinc-200 transition-all shadow-lg"
            >
                Save Changes
            </button>
        </div>
    </div>
);
