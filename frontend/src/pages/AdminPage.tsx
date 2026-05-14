import React, { useState, useEffect } from 'react';
import apiClient, { getApiErrorMessage } from '../api/client';
import type { CurrentUser } from '../App';
import { Upload, Trash2, FileText, Activity, Database, ShieldAlert, Coins, RefreshCw, Download, Cpu, LayoutDashboard, Settings } from 'lucide-react';
import ModelConfigPanel from './ModelConfigPanel';

// Helper for Loader2
const Loader2 = ({ className, size }: { className?: string, size?: number }) => (
    <svg
        className={className}
        width={size || 24}
        height={size || 24}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
    >
        <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.85.83 6.72 2.24" />
        <path d="M21 3v5h-5" />
    </svg>
);

type DocType = 'Internal' | 'External';

type GuardMode = DocType | '';

interface DocumentItem {
    doc_id: string;
    source: string;
    type: DocType;
    chunks: number;
}

interface IngestionJob {
    doc_id: string;
    status: 'pending' | 'processing' | 'indexed' | 'failed' | string;
    progress: number;
    progress_message?: string | null;
    error_message?: string | null;
}

interface DocumentImage {
    image_id: string;
    page?: number | null;
}

interface TopicGuardItem {
    id: number;
    pattern: string;
    mode: GuardMode;
    reason?: string;
    is_active: boolean;
}

interface UsageStats {
    total_entries: number;
    total_hits: number;
    hit_rate: string;
}

interface TokenUsageSummary {
    records: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    actual_tokens: number;
    estimated_tokens: number;
    by_operation: Array<{
        operation: string;
        model: string;
        estimated: boolean | number;
        records: number;
        total_tokens: number;
    }>;
}

interface TokenUsageRecord {
    created_at: string;
    request_id: string;
    conversation_id?: string | null;
    operation: string;
    mode?: DocType | null;
    provider: string;
    model: string;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    estimated: boolean | number;
    metadata?: {
        question?: string;
        answer_preview?: string;
        sources?: Array<{ source?: string; page?: number; type?: string }>;
    };
}

interface GuardFormState {
    pattern: string;
    mode: GuardMode;
    reason: string;
}

const AdminPage = ({ currentUser }: { currentUser: CurrentUser | null }) => {
    const [docs, setDocs] = useState<DocumentItem[]>([]);
    const [ingestionJobs, setIngestionJobs] = useState<Record<string, IngestionJob>>({});
    const [documentImages, setDocumentImages] = useState<Record<string, DocumentImage[]>>({});
    const [guards, setGuards] = useState<TopicGuardItem[]>([]);
    const [stats, setStats] = useState<UsageStats>({ total_entries: 0, total_hits: 0, hit_rate: '0%' });
    const [tokenSummary, setTokenSummary] = useState<TokenUsageSummary>({
        records: 0,
        input_tokens: 0,
        output_tokens: 0,
        total_tokens: 0,
        actual_tokens: 0,
        estimated_tokens: 0,
        by_operation: [],
    });
    const [tokenRecords, setTokenRecords] = useState<TokenUsageRecord[]>([]);
    const [uploading, setUploading] = useState(false);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [newGuard, setNewGuard] = useState<GuardFormState>({ pattern: '', mode: 'Internal', reason: '' });
    const [activeTab, setActiveTab] = useState<'dashboard' | 'knowledge' | 'guards' | 'models'>('dashboard');
    const [canManageModels, setCanManageModels] = useState(false);

    useEffect(() => {
        fetchData();
        // Derive permissions from the user object passed by App (no JWT parsing needed)
        if (currentUser) {
            setCanManageModels(currentUser.role === 'admin' || currentUser.can_manage_models === true);
        }
    }, [currentUser]);

    const fetchData = async () => {
        setLoading(true);
        setError(null);
        try {
            const [docsRes, guardsRes, statsRes] = await Promise.all([
                apiClient.get('/v1/document'),
                apiClient.get('/v1/admin/topic-guards'),
                apiClient.get('/v1/admin/qa-cache/stats'),
            ]);
            const documents = docsRes.data.documents as DocumentItem[];
            setDocs(documents);
            setGuards(guardsRes.data.guards);
            setStats(statsRes.data);

            const jobEntries = await Promise.all(
                documents.map(async (doc) => {
                    try {
                        const response = await apiClient.get(`/v1/document/ingestion/${doc.doc_id}`);
                        return [doc.doc_id, response.data as IngestionJob] as const;
                    } catch {
                        return null;
                    }
                })
            );
            setIngestionJobs(
                Object.fromEntries(jobEntries.filter((entry): entry is readonly [string, IngestionJob] => Boolean(entry)))
            );

            const imageEntries = await Promise.all(
                documents.map(async (doc) => {
                    try {
                        const response = await apiClient.get(`/v1/document/${doc.doc_id}/images`);
                        return [doc.doc_id, response.data.images as DocumentImage[]] as const;
                    } catch {
                        return [doc.doc_id, []] as const;
                    }
                })
            );
            setDocumentImages(Object.fromEntries(imageEntries));

            const [usageSummaryRes, usageRecordsRes] = await Promise.all([
                apiClient.get('/v1/usage/summary'),
                apiClient.get('/v1/usage/records', { params: { limit: 25 } }),
            ]);
            setTokenSummary(usageSummaryRes.data);
            setTokenRecords(usageRecordsRes.data.records);
        } catch (error: unknown) {
            console.error('Failed to fetch admin data', error);
            setError(getApiErrorMessage(error, 'Failed to load administration data. Please refresh the page.'));
        } finally {
            setLoading(false);
        }
    };

    const handleUpload = async (e: React.FormEvent<HTMLFormElement>) => {
        e.preventDefault();
        const formData = new FormData(e.currentTarget);
        setUploading(true);
        try {
            await apiClient.post('/v1/document/upload', formData);
            await fetchData();
        } catch (error: unknown) {
            setError(`Upload failed: ${getApiErrorMessage(error, 'Please check the file and try again.')}`);
            setTimeout(() => setError(null), 5000);
        } finally {
            setUploading(false);
        }
    };

    const deleteDoc = async (id: string) => {
        if (!confirm("Delete this document?")) return;
        try {
            await apiClient.delete(`/v1/document/${id}`);
            await fetchData();
        } catch (error: unknown) {
            setError(getApiErrorMessage(error, 'Failed to delete document.'));
            setTimeout(() => setError(null), 5000);
        }
    };

    const addGuard = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            await apiClient.post('/v1/admin/topic-guards', newGuard);
            setNewGuard({ pattern: '', mode: 'Internal', reason: '' });
            await fetchData();
        } catch (error: unknown) {
            setError(getApiErrorMessage(error, 'Failed to add topic guard.'));
            setTimeout(() => setError(null), 5000);
        }
    };

    const toggleGuard = async (id: number, active: boolean) => {
        try {
            await apiClient.patch(`/v1/admin/topic-guards/${id}`, { is_active: active });
            await fetchData();
        } catch (error: unknown) {
            setError(getApiErrorMessage(error, 'Failed to update guard status.'));
            setTimeout(() => setError(null), 5000);
        }
    };

    const reprocessDoc = async (id: string) => {
        try {
            await apiClient.post(`/v1/document/reprocess/${id}`);
            await fetchData();
        } catch (error: unknown) {
            setError(getApiErrorMessage(error, 'Failed to re-index document.'));
            setTimeout(() => setError(null), 5000);
        }
    };

    const clearTokenHistory = async () => {
        if (!confirm('Clear all token usage history?')) return;
        try {
            await apiClient.delete('/v1/usage');
            await fetchData();
        } catch (error: unknown) {
            setError(getApiErrorMessage(error, 'Failed to clear token history.'));
            setTimeout(() => setError(null), 5000);
        }
    };

    const exportAuditLog = async () => {
        try {
            const response = await apiClient.get('/v1/usage/audit/export', { params: { limit: 1000 } });
            const blob = new Blob([JSON.stringify(response.data.records, null, 2)], {
                type: 'application/json',
            });
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = `chat-audit-${new Date().toISOString().slice(0, 10)}.json`;
            link.click();
            URL.revokeObjectURL(url);
        } catch (error: unknown) {
            setError(getApiErrorMessage(error, 'Failed to export audit log.'));
            setTimeout(() => setError(null), 5000);
        }
    };

    const formatNumber = (value: number) => new Intl.NumberFormat().format(value || 0);

    const formatTime = (value: string) => {
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
    };

    const previewText = (value?: unknown, fallback = '-') => {
        if (value === null || value === undefined) return fallback;
        const text = typeof value === 'string' ? value : JSON.stringify(value);
        if (!text.trim()) return fallback;
        return text.length > 140 ? `${text.slice(0, 140)}...` : text;
    };

    const shortId = (value?: string | null) => {
        if (!value) return '-';
        return value.length > 12 ? `${value.slice(0, 8)}...` : value;
    };

    const statusTone = (status?: string) => {
        if (status === 'indexed') return 'bg-emerald-100 text-emerald-700';
        if (status === 'processing' || status === 'pending') return 'bg-amber-100 text-amber-700';
        if (status === 'failed') return 'bg-red-100 text-red-700';
        return 'bg-slate-100 text-slate-600';
    };

    if (loading) {
        return (
            <div className="h-full flex items-center justify-center">
                <div className="flex flex-col items-center gap-3">
                    <Loader2 className="animate-spin text-blue-600" size={40} />
                    <p className="text-slate-500 font-medium">Loading administration panel...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-6 max-w-7xl mx-auto pb-12">
            {error && (
                <div className="p-4 bg-red-50 border border-red-200 text-red-600 rounded-xl flex items-center gap-3 text-sm font-medium animate-in fade-in slide-in-from-top-2">
                    <ShieldAlert size={18} />
                    {error}
                </div>
            )}

            {/* Tab Navigation */}
            <div className="flex flex-wrap gap-2 p-1 bg-slate-100 rounded-xl w-fit">
                <button
                    onClick={() => setActiveTab('dashboard')}
                    className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${activeTab === 'dashboard' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}
                >
                    <LayoutDashboard size={16} />
                    Overview
                </button>
                <button
                    onClick={() => setActiveTab('knowledge')}
                    className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${activeTab === 'knowledge' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}
                >
                    <Database size={16} />
                    Knowledge Base
                </button>
                <button
                    onClick={() => setActiveTab('guards')}
                    className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${activeTab === 'guards' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}
                >
                    <ShieldAlert size={16} />
                    Topic Guards
                </button>
                {canManageModels && (
                    <button
                        onClick={() => setActiveTab('models')}
                        className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${activeTab === 'models' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}
                    >
                        <Cpu size={16} />
                        Model Config
                    </button>
                )}
            </div>

            {activeTab === 'dashboard' && (
                <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
                    {/* Stats Overview */}
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                        <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm flex items-center gap-4">
                            <div className="p-3 bg-blue-100 text-blue-600 rounded-xl"><Database size={24} /></div>
                            <div>
                                <p className="text-sm text-slate-500">Indexed Docs</p>
                                <p className="text-2xl font-bold">{docs.length}</p>
                            </div>
                        </div>
                        <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm flex items-center gap-4">
                            <div className="p-3 bg-green-100 text-green-600 rounded-xl"><Activity size={24} /></div>
                            <div>
                                <p className="text-sm text-slate-500">Cache Hit Rate</p>
                                <p className="text-2xl font-bold">{stats.hit_rate}</p>
                            </div>
                        </div>
                        <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm flex items-center gap-4">
                            <div className="p-3 bg-red-100 text-red-600 rounded-xl"><ShieldAlert size={24} /></div>
                            <div>
                                <p className="text-sm text-slate-500">Active Guards</p>
                                <p className="text-2xl font-bold">{guards.filter(g => g.is_active).length}</p>
                            </div>
                        </div>
                        <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm flex items-center gap-4">
                            <div className="p-3 bg-amber-100 text-amber-600 rounded-xl"><Coins size={24} /></div>
                            <div>
                                <p className="text-sm text-slate-500">Token Usage</p>
                                <p className="text-2xl font-bold">{formatNumber(tokenSummary.total_tokens)}</p>
                            </div>
                        </div>
                    </div>

                    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
                        <div className="p-6 border-b border-slate-100 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                            <div>
                                <h3 className="font-semibold flex items-center gap-2"><Coins size={18} /> Token History</h3>
                                <p className="text-xs text-slate-500 mt-1">
                                    {formatNumber(tokenSummary.records)} records · {formatNumber(tokenSummary.input_tokens)} input · {formatNumber(tokenSummary.output_tokens)} output · {formatNumber(tokenSummary.estimated_tokens)} estimated
                                </p>
                            </div>
                            <div className="flex gap-2">
                                <button
                                    onClick={fetchData}
                                    className="px-3 py-2 rounded-lg border border-slate-200 text-sm font-medium text-slate-600 hover:bg-slate-50 flex items-center gap-2"
                                >
                                    <RefreshCw size={14} />
                                    Refresh
                                </button>
                                <button
                                    onClick={exportAuditLog}
                                    className="px-3 py-2 rounded-lg border border-slate-200 text-sm font-medium text-slate-600 hover:bg-slate-50 flex items-center gap-2"
                                >
                                    <Download size={14} />
                                    Export Audit
                                </button>
                                <button
                                    onClick={clearTokenHistory}
                                    className="px-3 py-2 rounded-lg bg-red-50 text-sm font-medium text-red-600 hover:bg-red-100 flex items-center gap-2"
                                >
                                    <Trash2 size={14} />
                                    Clear
                                </button>
                            </div>
                        </div>

                        <div className="grid grid-cols-1 lg:grid-cols-3 border-b border-slate-100">
                            {tokenSummary.by_operation.slice(0, 3).map((item) => (
                                <div key={`${item.operation}-${item.model}-${item.estimated}`} className="p-4 border-b border-slate-100 lg:border-b-0 lg:border-r last:border-r-0">
                                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{item.operation}</p>
                                    <p className="mt-1 truncate text-sm font-medium text-slate-800">{item.model}</p>
                                    <p className="mt-2 text-xl font-bold">{formatNumber(item.total_tokens)}</p>
                                    <p className="text-xs text-slate-500">{formatNumber(item.records)} records · {item.estimated ? 'estimated' : 'actual'}</p>
                                </div>
                            ))}
                            {tokenSummary.by_operation.length === 0 && (
                                <div className="p-6 text-sm text-slate-500">No token usage recorded yet.</div>
                            )}
                        </div>

                        <div className="overflow-x-auto">
                            <table className="w-full text-left text-sm">
                                <thead className="bg-slate-50 text-slate-500 uppercase text-[10px] font-bold">
                                    <tr>
                                        <th className="px-6 py-3">Time</th>
                                        <th className="px-6 py-3">Operation</th>
                                        <th className="px-6 py-3">Session</th>
                                        <th className="px-6 py-3">Mode</th>
                                        <th className="px-6 py-3">Question / Answer</th>
                                        <th className="px-6 py-3">Model</th>
                                        <th className="px-6 py-3 text-right">Input</th>
                                        <th className="px-6 py-3 text-right">Output</th>
                                        <th className="px-6 py-3 text-right">Total</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-100">
                                    {tokenRecords.map((record) => (
                                        <tr key={`${record.request_id}-${record.created_at}-${record.operation}`} className="hover:bg-slate-50 transition-colors">
                                            <td className="px-6 py-4 text-slate-500 whitespace-nowrap">{formatTime(record.created_at)}</td>
                                            <td className="px-6 py-4 font-medium">{record.operation}</td>
                                            <td className="px-6 py-4 text-slate-500 font-mono text-xs">{shortId(record.conversation_id)}</td>
                                            <td className="px-6 py-4 text-slate-500">{record.mode || '-'}</td>
                                            <td className="px-6 py-4 min-w-[280px] max-w-[420px]">
                                                <div className="space-y-1">
                                                    <p className="text-xs font-medium text-slate-800">{previewText(record.metadata?.question)}</p>
                                                    <p className="text-xs text-slate-500">{previewText(record.metadata?.answer_preview)}</p>
                                                </div>
                                            </td>
                                            <td className="px-6 py-4 text-slate-500 max-w-[240px] truncate">{record.model}</td>
                                            <td className="px-6 py-4 text-right">{formatNumber(record.input_tokens)}</td>
                                            <td className="px-6 py-4 text-right">{formatNumber(record.output_tokens)}</td>
                                            <td className="px-6 py-4 text-right font-semibold">
                                                {formatNumber(record.total_tokens)}
                                                {record.estimated ? <span className="ml-1 text-[10px] text-slate-400">est</span> : null}
                                            </td>
                                        </tr>
                                    ))}
                                    {tokenRecords.length === 0 && (
                                        <tr>
                                            <td colSpan={9} className="px-6 py-8 text-center text-sm text-slate-500">
                                                No recent token usage.
                                            </td>
                                        </tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            )}

            {activeTab === 'knowledge' && (
                <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
                    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
                        <div className="p-6 border-b border-slate-100 flex justify-between items-center">
                            <h3 className="font-semibold flex items-center gap-2"><FileText size={18} /> Knowledge Base</h3>
                        </div>

                        <form onSubmit={handleUpload} className="p-6 bg-slate-50 border-b border-slate-100 flex gap-3">
                            <select name="doc_type" className="text-sm border rounded px-2 py-2 bg-white">
                                <option value="External">External</option>
                                <option value="Internal">Internal</option>
                            </select>
                            <input type="file" name="file" accept=".pdf" required className="text-sm flex-1" />
                            <button
                                disabled={uploading}
                                className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:bg-slate-300 flex items-center gap-2"
                            >
                                {uploading ? <Loader2 className="animate-spin" size={16} /> : <Upload size={16} />}
                                Upload
                            </button>
                        </form>

                        <div className="overflow-x-auto">
                            <table className="w-full text-left text-sm">
                                <thead className="bg-slate-50 text-slate-500 uppercase text-[10px] font-bold">
                                    <tr>
                                        <th className="px-6 py-3">Source</th>
                                        <th className="px-6 py-3">Type</th>
                                        <th className="px-6 py-3">Chunks</th>
                                        <th className="px-6 py-3">Images</th>
                                        <th className="px-6 py-3">Status</th>
                                        <th className="px-6 py-3 text-right">Action</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-100">
                                    {docs.map((doc) => (
                                        <tr key={doc.doc_id} className="hover:bg-slate-50 transition-colors">
                                            <td className="px-6 py-4 font-medium">
                                                <div className="space-y-1">
                                                    <p>{doc.source}</p>
                                                    {ingestionJobs[doc.doc_id]?.error_message ? (
                                                        <p className="text-xs text-red-500">{ingestionJobs[doc.doc_id].error_message}</p>
                                                    ) : null}
                                                </div>
                                            </td>
                                            <td className="px-6 py-4">
                                                <span className={`px-2 py-1 rounded-full text-[10px] font-bold ${doc.type === 'Internal' ? 'bg-purple-100 text-purple-600' : 'bg-blue-100 text-blue-600'}`}>
                                                    {doc.type}
                                                </span>
                                            </td>
                                            <td className="px-6 py-4 text-slate-500">{doc.chunks}</td>
                                            <td className="px-6 py-4 text-slate-500">{documentImages[doc.doc_id]?.length || 0}</td>
                                            <td className="px-6 py-4">
                                                <span className={`px-2 py-1 rounded-full text-[10px] font-bold ${statusTone(ingestionJobs[doc.doc_id]?.status)}`}>
                                                    {ingestionJobs[doc.doc_id]?.status || 'legacy'}
                                                </span>
                                                {ingestionJobs[doc.doc_id]?.status === 'processing' ? (
                                                    <span className="ml-2 text-xs text-slate-500">{ingestionJobs[doc.doc_id].progress}%</span>
                                                ) : null}
                                            </td>
                                            <td className="px-6 py-4 text-right">
                                                <div className="flex justify-end gap-2">
                                                    <button
                                                        type="button"
                                                        onClick={() => reprocessDoc(doc.doc_id)}
                                                        className="text-slate-400 hover:text-blue-600 transition-colors"
                                                        title="Re-index from stored source"
                                                    >
                                                        <RefreshCw size={16} />
                                                    </button>
                                                    <button onClick={() => deleteDoc(doc.doc_id)} className="text-slate-400 hover:text-red-500 transition-colors">
                                                        <Trash2 size={16} />
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            )}

            {activeTab === 'guards' && (
                <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
                    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
                        <div className="p-6 border-b border-slate-100 flex justify-between items-center">
                            <h3 className="font-semibold flex items-center gap-2"><ShieldAlert size={18} /> Topic Guards</h3>
                        </div>

                        <form onSubmit={addGuard} className="p-6 bg-slate-50 border-b border-slate-100 space-y-3">
                            <div className="flex gap-3">
                                <input
                                    placeholder="Pattern (e.g. 'salary', 'password')"
                                    value={newGuard.pattern}
                                    onChange={e => setNewGuard({ ...newGuard, pattern: e.target.value })}
                                    className="flex-1 p-2 text-sm border rounded bg-white"
                                    required
                                />
                                <select
                                    value={newGuard.mode}
                                    onChange={e => setNewGuard({ ...newGuard, mode: e.target.value as GuardMode })}
                                    className="text-sm border rounded px-2 bg-white"
                                >
                                    <option value="Internal">Internal</option>
                                    <option value="External">External</option>
                                    <option value="">Both</option>
                                </select>
                            </div>
                            <div className="flex gap-3">
                                <input
                                    placeholder="Reason for blocking..."
                                    value={newGuard.reason}
                                    onChange={e => setNewGuard({ ...newGuard, reason: e.target.value })}
                                    className="flex-1 p-2 text-sm border rounded bg-white"
                                />
                                <button className="bg-slate-800 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-slate-900">
                                    Add Rule
                                </button>
                            </div>
                        </form>

                        <div className="divide-y divide-slate-100">
                            {guards.map((guard) => (
                                <div key={guard.id} className="p-4 flex items-center justify-between hover:bg-slate-50 transition-colors">
                                    <div className="flex-1">
                                        <div className="flex items-center gap-2">
                                            <span className="font-medium text-sm">{guard.pattern}</span>
                                            <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${guard.mode === 'Internal' ? 'bg-purple-100 text-purple-600' : 'bg-blue-100 text-blue-600'}`}>
                                                {guard.mode || 'Both'}
                                            </span>
                                        </div>
                                        <p className="text-xs text-slate-500">{guard.reason || 'No reason provided'}</p>
                                    </div>
                                    <div className="flex items-center gap-4">
                                        <label className="relative inline-flex items-center cursor-pointer">
                                            <input
                                                type="checkbox"
                                                checked={guard.is_active}
                                                onChange={e => toggleGuard(guard.id, e.target.checked)}
                                                className="sr-only peer"
                                            />
                                            <div className="w-9 h-5 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-blue-600"></div>
                                        </label>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            {activeTab === 'models' && canManageModels && (
                <div className="animate-in fade-in slide-in-from-bottom-2 duration-300">
                    <ModelConfigPanel />
                </div>
            )}
        </div>
    );
};

export default AdminPage;
