import { create } from 'zustand';
import apiClient from '../api/client';

export type Provider = 'gemini' | 'anthropic';

export interface UserSettings {
    preferred_model: Provider;
    model_name: string | null;
    temperature: number;
    system_prompt: string | null;
    credentials: Record<string, boolean>;
}

export interface WebSearchPreferences {
    allow_web_search: boolean;
    auto_web_search: boolean;
    web_search_providers: string[];
}

interface UserStore {
    settings: UserSettings | null;
    webSearchPreferences: WebSearchPreferences | null;
    loading: boolean;
    error: string | null;

    fetchSettings: () => Promise<void>;
    updateSettings: (settings: Partial<UserSettings>) => Promise<void>;
    updateCredential: (provider: Provider, apiKey: string) => Promise<void>;
    deleteCredential: (provider: Provider) => Promise<void>;
    fetchWebSearchPreferences: () => Promise<void>;
    updateWebSearchPreferences: (preferences: Partial<WebSearchPreferences>) => Promise<void>;
}

export const useUserStore = create<UserStore>((set, get) => ({
    settings: null,
    webSearchPreferences: null,
    loading: false,
    error: null,

    fetchSettings: async () => {
        set({ loading: true, error: null });
        try {
            const response = await apiClient.get('/v1/users/me/settings');
            set({ settings: response.data, loading: false });
        } catch (error: any) {
            set({ error: error.response?.data?.detail || 'Failed to fetch settings', loading: false });
        }
    },

    updateSettings: async (updates: Partial<UserSettings>) => {
        set({ loading: true, error: null });
        try {
            const response = await apiClient.put('/v1/users/me/settings', updates);
            set({ settings: response.data, loading: false });
        } catch (error: any) {
            set({ error: error.response?.data?.detail || 'Failed to update settings', loading: false });
            throw error;
        }
    },

    updateCredential: async (provider: Provider, apiKey: string) => {
        set({ loading: true, error: null });
        try {
            await apiClient.put(`/v1/users/me/credentials/${provider}`, { api_key: apiKey });
            // Refresh settings to update credential status
            await get().fetchSettings();
        } catch (error: any) {
            set({ error: error.response?.data?.detail || `Failed to update ${provider} credential`, loading: false });
            throw error;
        }
    },

    deleteCredential: async (provider: Provider) => {
        set({ loading: true, error: null });
        try {
            await apiClient.delete(`/v1/users/me/credentials/${provider}`);
            // Refresh settings to update credential status
            await get().fetchSettings();
        } catch (error: any) {
            set({ error: error.response?.data?.detail || `Failed to delete ${provider} credential`, loading: false });
            throw error;
        }
    },

    fetchWebSearchPreferences: async () => {
        set({ loading: true, error: null });
        try {
            const response = await apiClient.get('/v1/users/me/web-search-preferences');
            set({ webSearchPreferences: response.data, loading: false });
        } catch (error: any) {
            set({ error: error.response?.data?.detail || 'Failed to fetch web search preferences', loading: false });
        }
    },

    updateWebSearchPreferences: async (preferences: Partial<WebSearchPreferences>) => {
        set({ loading: true, error: null });
        try {
            const response = await apiClient.put('/v1/users/me/web-search-preferences', preferences);
            set({ webSearchPreferences: response.data, loading: false });
        } catch (error: any) {
            set({ error: error.response?.data?.detail || 'Failed to update web search preferences', loading: false });
            throw error;
        }
    },
}));
