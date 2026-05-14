import React, { useState } from 'react';
import { useModelConfigStore, Provider, ModelConfig, RoutingStrategy, ModelTestResult } from '../stores/modelConfigStore';

export default function ModelConfigPanel() {
    const { models, routing, fetchModels, createModel, updateModel, deleteModel, setModelApiKey, deleteModelApiKey, updateRouting, testModel } = useModelConfigStore();

    const [showAddForm, setShowAddForm] = useState(false);
    const [editingModel, setEditingModel] = useState<ModelConfig | null>(null);
    const [apiKeyInput, setApiKeyInput] = useState<{ modelId: number; value: string } | null>(null);
    const [testStatus, setTestStatus] = useState<{ modelId: number; loading: boolean; result: ModelTestResult | null; error: string | null } | null>(null);

    // Form state for new/edit model
    const [formData, setFormData] = useState({
        name: '',
        provider: 'gemini' as Provider,
        model_name: '',
        custom_endpoint: '',
        temperature: 0.2,
        system_prompt: '',
        is_active: true,
        priority: 0,
    });

    const resetForm = () => {
        setFormData({
            name: '',
            provider: 'gemini',
            model_name: '',
            custom_endpoint: '',
            temperature: 0.2,
            system_prompt: '',
            is_active: true,
            priority: 0,
        });
        setShowAddForm(false);
        setEditingModel(null);
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            if (editingModel) {
                await updateModel(editingModel.id, formData);
            } else {
                await createModel(formData);
            }
            resetForm();
            await fetchModels();
        } catch (error) {
            console.error('Failed to save model:', error);
        }
    };

    const handleEdit = (model: ModelConfig) => {
        setEditingModel(model);
        setFormData({
            name: model.name,
            provider: model.provider,
            model_name: model.model_name || '',
            custom_endpoint: model.custom_endpoint || '',
            temperature: model.temperature,
            system_prompt: model.system_prompt || '',
            is_active: model.is_active,
            priority: model.priority,
        });
        setShowAddForm(true);
    };

    const handleDelete = async (id: number) => {
        if (confirm('Are you sure you want to delete this model configuration?')) {
            try {
                await deleteModel(id);
                await fetchModels();
            } catch (error) {
                console.error('Failed to delete model:', error);
            }
        }
    };

    const handleSetApiKey = async (modelId: number) => {
        if (!apiKeyInput || apiKeyInput.modelId !== modelId) return;
        try {
            await setModelApiKey(modelId, apiKeyInput.value);
            setApiKeyInput(null);
            await fetchModels();
        } catch (error) {
            console.error('Failed to set API key:', error);
        }
    };

    const handleDeleteApiKey = async (modelId: number) => {
        if (confirm('Are you sure you want to delete this API key?')) {
            try {
                await deleteModelApiKey(modelId);
                await fetchModels();
            } catch (error) {
                console.error('Failed to delete API key:', error);
            }
        }
    };

    const handleRoutingChange = async (strategy: RoutingStrategy) => {
        try {
            await updateRouting({ strategy });
            await fetchModels();
        } catch (error) {
            console.error('Failed to update routing:', error);
        }
    };

    const handleToggleModelEnabled = async (modelId: number) => {
        const isEnabled = routing.enabled_model_ids.includes(modelId);
        const newEnabledIds = isEnabled
            ? routing.enabled_model_ids.filter((id) => id !== modelId)
            : [...routing.enabled_model_ids, modelId];

        try {
            await updateRouting({ enabled_model_ids: newEnabledIds });
            await fetchModels();
        } catch (error) {
            console.error('Failed to toggle model:', error);
        }
    };

    const handleTestConnection = async (modelId: number) => {
        setTestStatus({ modelId, loading: true, result: null, error: null });
        try {
            const result = await testModel(modelId);
            setTestStatus({ modelId, loading: false, result, error: null });
            // Auto-clear success message after 5 seconds
            if (result.ok) {
                setTimeout(() => {
                    setTestStatus((prev) => (prev?.modelId === modelId ? null : prev));
                }, 5000);
            }
        } catch (error: any) {
            setTestStatus({ modelId, loading: false, result: null, error: error.message });
        }
    };

    return (
        <div className="space-y-6">
            {/* Routing Strategy Section */}
            <div className="bg-white p-6 rounded-lg shadow">
                <h3 className="text-lg font-semibold mb-4">Routing Strategy</h3>
                <div className="space-y-2">
                    <label className="flex items-center gap-2">
                        <input
                            type="radio"
                            name="routing"
                            value="random"
                            checked={routing.strategy === 'random'}
                            onChange={() => handleRoutingChange('random')}
                            className="text-blue-600"
                        />
                        <span className="font-medium">Random</span>
                        <span className="text-sm text-slate-600">— Pick randomly from enabled models</span>
                    </label>
                    <label className="flex items-center gap-2">
                        <input
                            type="radio"
                            name="routing"
                            value="round_robin"
                            checked={routing.strategy === 'round_robin'}
                            onChange={() => handleRoutingChange('round_robin')}
                            className="text-blue-600"
                        />
                        <span className="font-medium">Round Robin</span>
                        <span className="text-sm text-slate-600">— Cycle through enabled models</span>
                    </label>
                    <label className="flex items-center gap-2">
                        <input
                            type="radio"
                            name="routing"
                            value="fallback"
                            checked={routing.strategy === 'fallback'}
                            onChange={() => handleRoutingChange('fallback')}
                            className="text-blue-600"
                        />
                        <span className="font-medium">Fallback</span>
                        <span className="text-sm text-slate-600">— Try models in priority order until one succeeds</span>
                    </label>
                </div>
            </div>

            {/* Models List */}
            <div className="bg-white p-6 rounded-lg shadow">
                <div className="flex justify-between items-center mb-4">
                    <h3 className="text-lg font-semibold">Model Configurations</h3>
                    <button
                        onClick={() => setShowAddForm(!showAddForm)}
                        className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                    >
                        {showAddForm ? 'Cancel' : '+ Add Model'}
                    </button>
                </div>

                {/* Add/Edit Form */}
                {showAddForm && (
                    <form onSubmit={handleSubmit} className="mb-6 p-4 border border-slate-200 rounded-lg space-y-4">
                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label className="block text-sm font-medium mb-1">Name *</label>
                                <input
                                    type="text"
                                    value={formData.name}
                                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                                    className="w-full px-3 py-2 border border-slate-300 rounded"
                                    required
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium mb-1">Provider *</label>
                                <select
                                    value={formData.provider}
                                    onChange={(e) => setFormData({ ...formData, provider: e.target.value as Provider })}
                                    className="w-full px-3 py-2 border border-slate-300 rounded"
                                >
                                    <option value="gemini">Gemini</option>
                                    <option value="anthropic">Anthropic (Claude)</option>
                                    <option value="openai">OpenAI</option>
                                    <option value="custom">Custom Endpoint</option>
                                </select>
                            </div>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label className="block text-sm font-medium mb-1">Model Name</label>
                                <input
                                    type="text"
                                    value={formData.model_name}
                                    onChange={(e) => setFormData({ ...formData, model_name: e.target.value })}
                                    placeholder="e.g., gemini-2.0-flash-exp"
                                    className="w-full px-3 py-2 border border-slate-300 rounded"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium mb-1">Temperature</label>
                                <input
                                    type="number"
                                    step="0.1"
                                    min="0"
                                    max="2"
                                    value={formData.temperature}
                                    onChange={(e) => setFormData({ ...formData, temperature: parseFloat(e.target.value) })}
                                    className="w-full px-3 py-2 border border-slate-300 rounded"
                                />
                            </div>
                        </div>

                        {(formData.provider === 'custom' || formData.provider === 'openai') && (
                            <div>
                                <label className="block text-sm font-medium mb-1">Custom Endpoint</label>
                                <input
                                    type="url"
                                    value={formData.custom_endpoint}
                                    onChange={(e) => setFormData({ ...formData, custom_endpoint: e.target.value })}
                                    placeholder="https://api.example.com/v1"
                                    className="w-full px-3 py-2 border border-slate-300 rounded"
                                />
                            </div>
                        )}

                        <div>
                            <label className="block text-sm font-medium mb-1">System Prompt (Optional)</label>
                            <textarea
                                value={formData.system_prompt}
                                onChange={(e) => setFormData({ ...formData, system_prompt: e.target.value })}
                                rows={3}
                                className="w-full px-3 py-2 border border-slate-300 rounded"
                            />
                        </div>

                        <div className="flex items-center gap-4">
                            <label className="flex items-center gap-2">
                                <input
                                    type="checkbox"
                                    checked={formData.is_active}
                                    onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
                                    className="text-blue-600"
                                />
                                <span className="text-sm">Active</span>
                            </label>
                            <div className="flex items-center gap-2">
                                <label className="text-sm font-medium">Priority:</label>
                                <input
                                    type="number"
                                    value={formData.priority}
                                    onChange={(e) => setFormData({ ...formData, priority: parseInt(e.target.value) })}
                                    className="w-20 px-2 py-1 border border-slate-300 rounded"
                                />
                            </div>
                        </div>

                        <div className="flex gap-2">
                            <button type="submit" className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700">
                                {editingModel ? 'Update' : 'Create'}
                            </button>
                            <button type="button" onClick={resetForm} className="px-4 py-2 bg-slate-300 rounded hover:bg-slate-400">
                                Cancel
                            </button>
                        </div>
                    </form>
                )}

                {/* Models Table */}
                <div className="space-y-3">
                    {models.length === 0 ? (
                        <p className="text-slate-500 text-center py-8">No models configured yet. Add your first model above.</p>
                    ) : (
                        models.map((model) => (
                            <div key={model.id} className="border border-slate-200 rounded-lg p-4">
                                <div className="flex justify-between items-start mb-2">
                                    <div className="flex-1">
                                        <div className="flex items-center gap-3">
                                            <h4 className="font-semibold text-lg">{model.name}</h4>
                                            <span className="px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded">{model.provider}</span>
                                            {model.is_active && <span className="px-2 py-1 text-xs bg-green-100 text-green-800 rounded">Active</span>}
                                            {routing.enabled_model_ids.includes(model.id) && (
                                                <span className="px-2 py-1 text-xs bg-purple-100 text-purple-800 rounded">Enabled for Routing</span>
                                            )}
                                        </div>
                                        <div className="text-sm text-slate-600 mt-1">
                                            {model.model_name && <span>Model: {model.model_name} • </span>}
                                            <span>Temperature: {model.temperature} • </span>
                                            <span>Priority: {model.priority}</span>
                                        </div>
                                        {model.custom_endpoint && (
                                            <div className="text-sm text-slate-600 mt-1">Endpoint: {model.custom_endpoint}</div>
                                        )}
                                    </div>
                                    <div className="flex gap-2">
                                        <button
                                            onClick={() => handleTestConnection(model.id)}
                                            disabled={testStatus?.modelId === model.id && testStatus.loading}
                                            className="px-3 py-1 text-sm bg-green-100 text-green-700 rounded hover:bg-green-200 disabled:opacity-50 disabled:cursor-not-allowed"
                                        >
                                            {testStatus?.modelId === model.id && testStatus.loading ? 'Testing...' : 'Test'}
                                        </button>
                                        <button
                                            onClick={() => handleEdit(model)}
                                            className="px-3 py-1 text-sm bg-blue-100 text-blue-700 rounded hover:bg-blue-200"
                                        >
                                            Edit
                                        </button>
                                        <button
                                            onClick={() => handleDelete(model.id)}
                                            className="px-3 py-1 text-sm bg-red-100 text-red-700 rounded hover:bg-red-200"
                                        >
                                            Delete
                                        </button>
                                    </div>
                                </div>

                                {/* API Key Management */}
                                <div className="mt-3 pt-3 border-t border-slate-200">
                                    <div className="flex items-center gap-2">
                                        <span className="text-sm font-medium">API Key:</span>
                                        {model.has_api_key ? (
                                            <>
                                                <span className="text-sm text-green-600">✓ Configured</span>
                                                <button
                                                    onClick={() => handleDeleteApiKey(model.id)}
                                                    className="text-sm text-red-600 hover:underline"
                                                >
                                                    Remove
                                                </button>
                                            </>
                                        ) : (
                                            <span className="text-sm text-slate-500">Not set</span>
                                        )}
                                    </div>
                                    {apiKeyInput?.modelId === model.id ? (
                                        <div className="flex gap-2 mt-2">
                                            <input
                                                type="password"
                                                value={apiKeyInput.value}
                                                onChange={(e) => setApiKeyInput({ modelId: model.id, value: e.target.value })}
                                                placeholder="Enter API key"
                                                className="flex-1 px-3 py-1 text-sm border border-slate-300 rounded"
                                            />
                                            <button
                                                onClick={() => handleSetApiKey(model.id)}
                                                className="px-3 py-1 text-sm bg-green-600 text-white rounded hover:bg-green-700"
                                            >
                                                Save
                                            </button>
                                            <button
                                                onClick={() => setApiKeyInput(null)}
                                                className="px-3 py-1 text-sm bg-slate-300 rounded hover:bg-slate-400"
                                            >
                                                Cancel
                                            </button>
                                        </div>
                                    ) : (
                                        <button
                                            onClick={() => setApiKeyInput({ modelId: model.id, value: '' })}
                                            className="mt-2 text-sm text-blue-600 hover:underline"
                                        >
                                            {model.has_api_key ? 'Update API Key' : 'Set API Key'}
                                        </button>
                                    )}
                                </div>

                                {/* Enable/Disable for Routing */}
                                <div className="mt-3 pt-3 border-t border-slate-200">
                                    <label className="flex items-center gap-2">
                                        <input
                                            type="checkbox"
                                            checked={routing.enabled_model_ids.includes(model.id)}
                                            onChange={() => handleToggleModelEnabled(model.id)}
                                            className="text-blue-600"
                                        />
                                        <span className="text-sm font-medium">Enable for routing</span>
                                    </label>
                                </div>

                                {/* Test Connection Status */}
                                {testStatus?.modelId === model.id && (
                                    <div className="mt-3 pt-3 border-t border-slate-200">
                                        {testStatus.loading ? (
                                            <div className="flex items-center gap-2 text-sm text-blue-600">
                                                <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                                </svg>
                                                <span>Testing connection...</span>
                                            </div>
                                        ) : testStatus.result?.ok ? (
                                            <div className="flex items-center gap-2 text-sm text-green-600">
                                                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path>
                                                </svg>
                                                <span className="font-medium">Connection successful!</span>
                                                <span className="text-slate-600">— {testStatus.result.detail}</span>
                                            </div>
                                        ) : (
                                            <div className="flex items-start gap-2 text-sm text-red-600">
                                                <svg className="h-5 w-5 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path>
                                                </svg>
                                                <div>
                                                    <div className="font-medium">Connection failed</div>
                                                    <div className="text-slate-600 mt-1">{testStatus.error || testStatus.result?.detail}</div>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        ))
                    )}
                </div>
            </div>
        </div>
    );
}
