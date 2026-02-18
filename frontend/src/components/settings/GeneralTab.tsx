import { HelpCircle } from 'lucide-react';

interface GeneralTabProps {
    agentName: string;
    setAgentName: (v: string) => void;
    showBrowser: boolean;
    onToggleBrowser: (v: boolean) => void;
    onSave: () => void;
}

export const GeneralTab = ({ agentName, setAgentName, showBrowser, onToggleBrowser, onSave }: GeneralTabProps) => (
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
                onClick={onSave}
                className="px-6 py-2.5 text-sm font-bold bg-white text-black hover:bg-zinc-200 transition-all shadow-lg"
            >
                Save Changes
            </button>
        </div>
    </div>
);
