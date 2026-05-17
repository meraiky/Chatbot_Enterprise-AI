import React, { useEffect, useState } from 'react';
import { Save, AlertCircle, CheckCircle, Globe, Search } from 'lucide-react';
import { useUserStore } from '../stores/userStore';

export default function UserSettingsPage() {
    const {
        webSearchPreferences,
        loading,
        error,
        fetchWebSearchPreferences,
        updateWebSearchPreferences,
    } = useUserStore();

    const [allowWebSearch, setAllowWebSearch] = useState(false);
    const [autoWebSearch, setAutoWebSearch] = useState(false);
    const [selectedProviders, setSelectedProviders] = useState<string[]>(['duckduckgo']);

    const [webSaveStatus, setWebSaveStatus] = useState<'idle' | 'saving' | 'success' | 'error'>('idle');

    useEffect(() => {
        fetchWebSearchPreferences();
    }, [fetchWebSearchPreferences]);

    useEffect(() => {
        if (webSearchPreferences) {
            setAllowWebSearch(webSearchPreferences.allow_web_search);
            setAutoWebSearch(webSearchPreferences.auto_web_search);
            setSelectedProviders(webSearchPreferences.web_search_providers || ['duckduckgo']);
        }
    }, [webSearchPreferences]);

    const handleSaveWebSearchSettings = async () => {
        setWebSaveStatus('saving');
        try {
            await updateWebSearchPreferences({
                allow_web_search: allowWebSearch,
                auto_web_search: autoWebSearch,
                web_search_providers: selectedProviders,
            });
            setWebSaveStatus('success');
            setTimeout(() => setWebSaveStatus('idle'), 2000);
        } catch {
            setWebSaveStatus('error');
            setTimeout(() => setWebSaveStatus('idle'), 3000);
        }
    };

    const handleProviderToggle = (provider: string) => {
        setSelectedProviders((prev) => {
            if (prev.includes(provider)) {
                return prev.filter((p) => p !== provider);
            }
            return [...prev, provider];
        });
    };

    if (loading && !webSearchPreferences) {
        return (
            <div className="flex items-center justify-center h-64">
                <div className="text-slate-500">Loading settings...</div>
            </div>
        );
    }

    return (
        <div className="max-w-6xl mx-auto">
            <div className="bg-slate-50 rounded-lg shadow p-6">
                <div className="space-y-6">
                        <div className="bg-white rounded-lg shadow p-6">
                            <div className="flex items-start gap-3 mb-4">
                                <div className="p-2 rounded-lg bg-emerald-50 text-emerald-600">
                                    <Globe size={20} />
                                </div>
                                <div>
                                    <h2 className="text-xl font-semibold text-slate-900">Web Search Preferences</h2>
                                    <p className="text-sm text-slate-600 mt-1">
                                        Control when the assistant may use external web sources after searching your internal documents first.
                                    </p>
                                </div>
                            </div>

                            {error && (
                                <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-start gap-2 text-sm text-red-700">
                                    <AlertCircle size={16} className="mt-0.5 flex-shrink-0" />
                                    <span>{error}</span>
                                </div>
                            )}

                            <div className="space-y-5">
                                <label className="flex items-start gap-3 rounded-lg border border-slate-200 bg-slate-50 p-4">
                                    <input
                                        type="checkbox"
                                        checked={allowWebSearch}
                                        onChange={(e) => setAllowWebSearch(e.target.checked)}
                                        className="mt-1"
                                    />
                                    <div>
                                        <div className="font-medium text-slate-800">Enable web search fallback</div>
                                        <div className="text-sm text-slate-600 mt-1">
                                            Allow the assistant to offer internet search when internal RAG does not find enough relevant information.
                                        </div>
                                    </div>
                                </label>

                                <label className={`flex items-start gap-3 rounded-lg border p-4 ${allowWebSearch ? 'border-slate-200 bg-slate-50' : 'border-slate-100 bg-slate-100 opacity-60'}`}>
                                    <input
                                        type="checkbox"
                                        checked={autoWebSearch}
                                        disabled={!allowWebSearch}
                                        onChange={(e) => setAutoWebSearch(e.target.checked)}
                                        className="mt-1"
                                    />
                                    <div>
                                        <div className="font-medium text-slate-800">Auto web search</div>
                                        <div className="text-sm text-slate-600 mt-1">
                                            Skip the confirmation step and automatically search the web when internal documents are insufficient.
                                        </div>
                                    </div>
                                </label>

                                <div className={`rounded-lg border p-4 ${allowWebSearch ? 'border-slate-200 bg-white' : 'border-slate-100 bg-slate-100 opacity-60'}`}>
                                    <div className="flex items-center gap-2 mb-3">
                                        <Search size={16} className="text-slate-600" />
                                        <h3 className="font-medium text-slate-800">Search providers</h3>
                                    </div>
                                    <p className="text-sm text-slate-600 mb-4">
                                        Choose which providers may be used for external search. Keep at least one provider selected.
                                    </p>

                                    <div className="space-y-3">
                                        <label className="flex items-start gap-3">
                                            <input
                                                type="checkbox"
                                                checked={selectedProviders.includes('duckduckgo')}
                                                disabled={!allowWebSearch}
                                                onChange={() => handleProviderToggle('duckduckgo')}
                                                className="mt-1"
                                            />
                                            <div>
                                                <div className="font-medium text-slate-800">DuckDuckGo</div>
                                                <div className="text-sm text-slate-600">Free default provider, no API key required.</div>
                                            </div>
                                        </label>

                                        <label className="flex items-start gap-3">
                                            <input
                                                type="checkbox"
                                                checked={selectedProviders.includes('google')}
                                                disabled={!allowWebSearch}
                                                onChange={() => handleProviderToggle('google')}
                                                className="mt-1"
                                            />
                                            <div>
                                                <div className="font-medium text-slate-800">Google Custom Search</div>
                                                <div className="text-sm text-slate-600">Requires backend API credentials if configured.</div>
                                            </div>
                                        </label>

                                        <label className="flex items-start gap-3">
                                            <input
                                                type="checkbox"
                                                checked={selectedProviders.includes('bing')}
                                                disabled={!allowWebSearch}
                                                onChange={() => handleProviderToggle('bing')}
                                                className="mt-1"
                                            />
                                            <div>
                                                <div className="font-medium text-slate-800">Bing Search</div>
                                                <div className="text-sm text-slate-600">Requires backend API credentials if configured.</div>
                                            </div>
                                        </label>
                                    </div>
                                </div>

                                <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800">
                                    Internal documents and web results are stored separately to prevent source confusion and preserve answer traceability.
                                </div>

                                <button
                                    onClick={handleSaveWebSearchSettings}
                                    disabled={webSaveStatus === 'saving' || (allowWebSearch && selectedProviders.length === 0)}
                                    className="flex items-center gap-2 px-4 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-500 disabled:bg-slate-400"
                                >
                                    {webSaveStatus === 'success' ? <CheckCircle size={16} /> : <Save size={16} />}
                                    {webSaveStatus === 'saving' ? 'Saving...' : webSaveStatus === 'success' ? 'Saved!' : 'Save Web Search Settings'}
                                </button>
                            </div>
                        </div>
                    </div>
            </div>
        </div>
    );
}
