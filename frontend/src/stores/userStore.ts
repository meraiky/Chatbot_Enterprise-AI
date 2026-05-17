import { create } from 'zustand';
import apiClient from '../api/client';

export interface WebSearchPreferences {
    allow_web_search: boolean;
    auto_web_search: boolean;
    web_search_providers: string[];
}

interface UserStore {
    webSearchPreferences: WebSearchPreferences | null;
    loading: boolean;
    error: string | null;

    fetchWebSearchPreferences: () => Promise<void>;
    updateWebSearchPreferences: (preferences: Partial<WebSearchPreferences>) => Promise<void>;
}

export const useUserStore = create<UserStore>((set) => ({
    webSearchPreferences: null,
    loading: false,
    error: null,

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
