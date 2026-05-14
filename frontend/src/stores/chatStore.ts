import { create } from 'zustand';

export interface SourceInfo {
    rank?: number;
    source: string;
    page?: number;
    type?: string;
    doc_id?: string;
    distance?: number;
    preview?: string;
}

export interface ExternalSourceInfo {
    url: string;
    title?: string;
    snippet?: string;
}

export interface Message {
    role: 'user' | 'assistant';
    content: string;
    sources?: SourceInfo[];
    externalSources?: ExternalSourceInfo[];
    sourceType?: 'internal' | 'external_web' | 'hybrid' | 'none';
    webSearchOffered?: boolean;
    webSearchPerformed?: boolean;
    suggestion?: string;
    usage?: {
        input_tokens: number;
        output_tokens: number;
        total_tokens: number;
        cached?: boolean;
        estimated?: boolean;
    };
}

interface ChatState {
    messages: Message[];
    isTyping: boolean;
    mode: 'Internal' | 'External';
    conversationId: string;
    setMode: (mode: 'Internal' | 'External') => void;
    addMessage: (message: Message) => void;
    setMessages: (messages: Message[] | ((messages: Message[]) => Message[])) => void;
    setTyping: (isTyping: boolean) => void;
    clearChat: () => void;
}

const createConversationId = () => {
    if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
        return crypto.randomUUID();
    }
    return `conv-${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

export const useChatStore = create<ChatState>((set) => ({
    messages: [],
    isTyping: false,
    mode: 'Internal',
    conversationId: createConversationId(),
    setMode: (mode) => set({ mode }),
    addMessage: (message) => set((state) => ({
        messages: [...state.messages, message],
    })),
    setMessages: (messages) => set((state) => ({
        messages: typeof messages === 'function' ? messages(state.messages) : messages,
    })),
    setTyping: (isTyping) => set({ isTyping }),
    clearChat: () => set({ messages: [], conversationId: createConversationId() }),
}));
