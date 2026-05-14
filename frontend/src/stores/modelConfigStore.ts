import { create } from 'zustand';
import apiClient from '../api/client';

export type Provider = 'gemini' | 'anthropic' | 'openai' | 'custom';
export type RoutingStrategy = 'random' | 'round_robin' | 'fallback';

export interface ModelConfig {
    id: number;
    name: string;
    provider: Provider;
    model_name: string | null;
    has_api_key: boolean;
    custom_endpoint: string | null;
    custom_headers: Record<string, string> | null;
    temperature: number;
    system_prompt: string | null;
    is_active: boolean;
    priority: number;
}

export interface RoutingConfig {
    strategy: RoutingStrategy;
    enabled_model_ids: number[];
    fallback_order: number[];
}

export interface UserModelsResponse {
    models: ModelConfig[];
    routing: RoutingConfig;
}

export interface ModelTestResult {
    ok: boolean;
    model_id: number;
    provider: Provider;
    model_name: string | null;
    endpoint: string | null;
    detail: string;
}

interface ModelConfigStore {
    models: ModelConfig[];
    routing: RoutingConfig;
    loading: boolean;
    error: string | null;

    fetchModels: () => Promise<void>;
    createModel: (data: {
        name: string;
        provider: Provider;
        model_name?: string;
        custom_endpoint?: string;
        custom_headers?: Record<string, string>;
        temperature?: number;
        system_prompt?: string;
        is_active?: boolean;
        priority?: number;
    }) => Promise<ModelConfig>;
    updateModel: (id: number, data: Partial<ModelConfig>) => Promise<ModelConfig>;
    deleteModel: (id: number) => Promise<void>;
    setModelApiKey: (id: number, apiKey: string) => Promise<ModelConfig>;
    deleteModelApiKey: (id: number) => Promise<ModelConfig>;
    updateRouting: (data: Partial<RoutingConfig>) => Promise<RoutingConfig>;
    testModel: (id: number) => Promise<ModelTestResult>;
}

export const useModelConfigStore = create<ModelConfigStore>((set, get) => ({
    models: [],
    routing: {
        strategy: 'random',
        enabled_model_ids: [],
        fallback_order: [],
    },
    loading: false,
    error: null,

    fetchModels: async () => {
        set({ loading: true, error: null });
        try {
            const response = await apiClient.get<UserModelsResponse>('/v1/users/me/models');
            set({
                models: response.data.models,
                routing: response.data.routing,
                loading: false,
            });
        } catch (error: any) {
            set({
                error: error.response?.data?.detail || 'Failed to fetch models',
                loading: false,
            });
            throw error;
        }
    },

    createModel: async (data) => {
        set({ loading: true, error: null });
        try {
            const response = await apiClient.post<ModelConfig>('/v1/users/me/models', data);
            const newModel = response.data;
            set((state) => ({
                models: [...state.models, newModel],
                loading: false,
            }));
            return newModel;
        } catch (error: any) {
            set({
                error: error.response?.data?.detail || 'Failed to create model',
                loading: false,
            });
            throw error;
        }
    },

    updateModel: async (id, data) => {
        set({ loading: true, error: null });
        try {
            const response = await apiClient.put<ModelConfig>(`/v1/users/me/models/${id}`, data);
            const updatedModel = response.data;
            set((state) => ({
                models: state.models.map((m) => (m.id === id ? updatedModel : m)),
                loading: false,
            }));
            return updatedModel;
        } catch (error: any) {
            set({
                error: error.response?.data?.detail || 'Failed to update model',
                loading: false,
            });
            throw error;
        }
    },

    deleteModel: async (id) => {
        set({ loading: true, error: null });
        try {
            await apiClient.delete(`/v1/users/me/models/${id}`);
            set((state) => ({
                models: state.models.filter((m) => m.id !== id),
                routing: {
                    ...state.routing,
                    enabled_model_ids: state.routing.enabled_model_ids.filter((mid) => mid !== id),
                    fallback_order: state.routing.fallback_order.filter((mid) => mid !== id),
                },
                loading: false,
            }));
        } catch (error: any) {
            set({
                error: error.response?.data?.detail || 'Failed to delete model',
                loading: false,
            });
            throw error;
        }
    },

    setModelApiKey: async (id, apiKey) => {
        set({ loading: true, error: null });
        try {
            const response = await apiClient.put<ModelConfig>(
                `/v1/users/me/models/${id}/api-key`,
                { api_key: apiKey }
            );
            const updatedModel = response.data;
            set((state) => ({
                models: state.models.map((m) => (m.id === id ? updatedModel : m)),
                loading: false,
            }));
            return updatedModel;
        } catch (error: any) {
            set({
                error: error.response?.data?.detail || 'Failed to set API key',
                loading: false,
            });
            throw error;
        }
    },

    deleteModelApiKey: async (id) => {
        set({ loading: true, error: null });
        try {
            const response = await apiClient.delete<ModelConfig>(`/v1/users/me/models/${id}/api-key`);
            const updatedModel = response.data;
            set((state) => ({
                models: state.models.map((m) => (m.id === id ? updatedModel : m)),
                loading: false,
            }));
            return updatedModel;
        } catch (error: any) {
            set({
                error: error.response?.data?.detail || 'Failed to delete API key',
                loading: false,
            });
            throw error;
        }
    },

    updateRouting: async (data) => {
        set({ loading: true, error: null });
        try {
            const response = await apiClient.put<RoutingConfig>('/v1/users/me/routing', data);
            const updatedRouting = response.data;
            set({
                routing: updatedRouting,
                loading: false,
            });
            return updatedRouting;
        } catch (error: any) {
            set({
                error: error.response?.data?.detail || 'Failed to update routing',
                loading: false,
            });
            throw error;
        }
    },

    testModel: async (id) => {
        try {
            const response = await apiClient.post<ModelTestResult>(`/v1/users/me/models/${id}/test`);
            return response.data;
        } catch (error: any) {
            throw new Error(error.response?.data?.detail || 'Failed to test model connection');
        }
    },
}));
