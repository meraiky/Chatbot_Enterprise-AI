import React, { useState, useEffect, useRef } from 'react';
import { useChatStore, Message } from '../stores/chatStore';
import apiClient from '../api/client';
import { Send, Bot, User, FileText, Loader2, AlertTriangle, Globe, Search } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

type ModeSummary = Record<'Internal' | 'External', { documents: number; chunks: number }>;

type StreamEvent = {
    event: string;
    data: Record<string, any>;
};

const parseSseBlocks = (buffer: string): { events: StreamEvent[]; rest: string } => {
    const blocks = buffer.split('\n\n');
    const events = blocks.slice(0, -1).map((block) => {
        const eventMatch = block.match(/^event:\s*(\w+)/m);
        const event = eventMatch?.[1] || 'token';
        // Collect ALL lines starting with "data:" and join them
        // (handles multi-line JSON that may appear in SSE data field)
        const dataLines = block
            .split('\n')
            .filter((line) => line.startsWith('data:'))
            .map((line) => line.replace(/^data:\s*/, ''));
        const dataText = dataLines.join('') || '{}';
        try {
            return { event, data: JSON.parse(dataText) };
        } catch {
            return { event: 'token', data: { text: dataText } };
        }
    });
    return { events, rest: blocks[blocks.length - 1] || '' };
};

/** Badge showing source type of AI answer */
const SourceTypeBadge = ({ sourceType }: { sourceType?: string }) => {
    if (!sourceType || sourceType === 'none') return null;
    if (sourceType === 'internal') {
        return (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-blue-50 text-blue-700 border border-blue-200">
                <FileText size={9} /> Internal Docs
            </span>
        );
    }
    if (sourceType === 'external_web') {
        return (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
                <Globe size={9} /> Web Search
            </span>
        );
    }
    if (sourceType === 'hybrid') {
        return (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-purple-50 text-purple-700 border border-purple-200">
                <FileText size={9} /><Globe size={9} /> Hybrid
            </span>
        );
    }
    return null;
};

const ChatPage = () => {
    const { messages, isTyping, mode, conversationId, addMessage, setMessages, setTyping, clearChat } = useChatStore();
    const [input, setInput] = useState('');
    const [docSummary, setDocSummary] = useState<ModeSummary | null>(null);
    const scrollRef = useRef<HTMLDivElement>(null);
    const abortControllerRef = useRef<AbortController | null>(null);
    const isMountedRef = useRef(true);

    useEffect(() => {
        apiClient.get('/v1/document/summary')
            .then((response) => setDocSummary(response.data))
            .catch(() => setDocSummary(null));
    }, []);

    useEffect(() => {
        return () => {
            isMountedRef.current = false;
            abortControllerRef.current?.abort();
        };
    }, []);

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [messages, isTyping]);

    /** Core streaming function - handles both initial and web-search-confirmed requests */
    const sendHybridStream = async (question: string, allowWebSearch: boolean) => {
        const response = await fetch(`${apiClient.defaults.baseURL}/v1/chat/message/hybrid/stream`, {
            method: 'POST',
            credentials: 'include',  // send httpOnly auth cookie
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question,
                mode,
                history: messages.filter((m) => !m.webSearchOffered), // exclude intermediate offer messages
                conversation_id: conversationId,
                allow_web_search: allowWebSearch,
            }),
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ detail: 'An unexpected error occurred' }));
            throw new Error(errorData.detail || `Server error: ${response.status}`);
        }

        if (!response.body) throw new Error('No response body');

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let assistantContent = '';
        let buffer = '';
        let metaPayload: Record<string, any> = {};

        // Add placeholder assistant message
        addMessage({ role: 'assistant', content: '' });

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const parsed = parseSseBlocks(buffer);
            buffer = parsed.rest;

            for (const streamEvent of parsed.events) {
                if (streamEvent.event === 'token') {
                    assistantContent += String(streamEvent.data.text || '');
                    setMessages((prev) => {
                        const updated = [...prev];
                        updated[updated.length - 1] = {
                            ...updated[updated.length - 1],
                            content: assistantContent,
                        };
                        return updated;
                    });
                }

                if (streamEvent.event === 'metadata') {
                    metaPayload = streamEvent.data;
                    setMessages((prev) => {
                        const updated = [...prev];
                        updated[updated.length - 1] = {
                            ...updated[updated.length - 1],
                            sources: streamEvent.data.sources || [],
                            externalSources: streamEvent.data.external_sources || [],
                            sourceType: streamEvent.data.source_type,
                            webSearchOffered: streamEvent.data.web_search_offered || false,
                            webSearchPerformed: streamEvent.data.web_search_performed || false,
                            suggestion: streamEvent.data.suggestion,
                            usage: streamEvent.data.usage,
                        };
                        return updated;
                    });
                }
            }
        }

        if (!assistantContent.trim()) {
            setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                    ...updated[updated.length - 1],
                    content: 'Error: No response received from server.',
                };
                return updated;
            });
        }

        return metaPayload;
    };

    const handleSend = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!input.trim() || isTyping) return;

        const question = input.trim();
        const userMsg: Message = { role: 'user', content: question };
        addMessage(userMsg);
        setInput('');
        setTyping(true);

        try {
            await sendHybridStream(question, false);
        } catch (error: unknown) {
            const message = error instanceof Error ? error.message : 'Sorry, I encountered an error. Please try again.';
            addMessage({
                role: 'assistant',
                content: `Error: ${message}`,
            });
        } finally {
            setTyping(false);
        }
    };

    /** Called when user clicks "Yes, search the web" on an offer message */
    const handleAcceptWebSearch = async (originalQuestion: string, offerMsgIdx: number) => {
        if (isTyping) return;

        // Remove the offer message and add user confirmation message
        setMessages((prev) => {
            const updated = [...prev];
            // Mark the offer message as resolved (clear webSearchOffered)
            updated[offerMsgIdx] = {
                ...updated[offerMsgIdx],
                webSearchOffered: false,
                content: updated[offerMsgIdx].content + '\n\n*(Web search requested)*',
            };
            return updated;
        });

        setTyping(true);

        try {
            await sendHybridStream(originalQuestion, true);
        } catch (error: unknown) {
            const message = error instanceof Error ? error.message : 'Sorry, I encountered an error. Please try again.';
            addMessage({
                role: 'assistant',
                content: `Error: ${message}`,
            });
        } finally {
            setTyping(false);
        }
    };

    /** Called when user clicks "No thanks" on a web search offer */
    const handleDeclineWebSearch = (offerMsgIdx: number) => {
        setMessages((prev) => {
            const updated = [...prev];
            updated[offerMsgIdx] = {
                ...updated[offerMsgIdx],
                webSearchOffered: false,
                content: updated[offerMsgIdx].content + '\n\n*(Web search declined)*',
            };
            return updated;
        });
    };

    /** Find the user message that triggered a given assistant message */
    const findUserQuestion = (assistantIdx: number): string => {
        for (let i = assistantIdx - 1; i >= 0; i--) {
            if (messages[i].role === 'user') return messages[i].content;
        }
        return '';
    };

    const activeSummary = docSummary?.[mode];
    const hasDocsForMode = !activeSummary || activeSummary.chunks > 0;

    return (
        <div className="flex flex-col h-full max-w-4xl mx-auto w-full bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
            {/* Chat Header */}
            <div className="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
                <div className="flex items-center gap-2">
                    <Bot className="text-blue-600" size={20} />
                    <span className="font-medium text-slate-700">AI Assistant ({mode})</span>
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 border border-blue-200 font-medium">Hybrid RAG</span>
                </div>
                <button
                    onClick={clearChat}
                    className="text-xs text-slate-400 hover:text-red-500 transition-colors"
                >
                    Clear Conversation
                </button>
            </div>

            {!hasDocsForMode && (
                <div className="mx-6 mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 flex items-start gap-2">
                    <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                    <span>
                        No indexed documents in {mode} mode yet. Switch mode or upload a document with the same type before asking document questions.
                    </span>
                </div>
            )}

            {/* Messages Area */}
            <div
                ref={scrollRef}
                className="flex-1 overflow-y-auto p-6 space-y-6 bg-white"
            >
                {messages.length === 0 && (
                    <div className="h-full flex flex-col items-center justify-center text-center space-y-4 opacity-50">
                        <Bot size={48} className="text-slate-300" />
                        <p className="text-slate-500 max-w-xs">
                            Ask me anything. I'll search internal documents first, then offer to search the web if needed.
                        </p>
                    </div>
                )}

                {messages.map((msg, idx) => (
                    <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        <div className={`flex gap-3 max-w-[85%] ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
                            <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${msg.role === 'user' ? 'bg-blue-600 text-white' : 'bg-slate-200 text-slate-600'}`}>
                                {msg.role === 'user' ? <User size={16} /> : <Bot size={16} />}
                            </div>
                            <div className={`p-4 rounded-2xl ${msg.role === 'user' ? 'bg-blue-600 text-white rounded-tr-none' : 'bg-slate-100 text-slate-800 rounded-tl-none'}`}>

                                {/* Source type badge (assistant only) */}
                                {msg.role === 'assistant' && msg.sourceType && msg.sourceType !== 'none' && (
                                    <div className="mb-2">
                                        <SourceTypeBadge sourceType={msg.sourceType} />
                                    </div>
                                )}

                                {/* Message content */}
                                {msg.role === 'assistant' ? (
                                    <div className="text-sm leading-relaxed text-slate-800 space-y-2">
                                        <ReactMarkdown
                                            remarkPlugins={[remarkGfm]}
                                            components={{
                                                p: ({ children }) => <p className="my-2">{children}</p>,
                                                ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>,
                                                ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>,
                                                li: ({ children }) => <li className="pl-1">{children}</li>,
                                                strong: ({ children }) => <strong className="font-semibold text-slate-950">{children}</strong>,
                                                h1: ({ children }) => <h1 className="mt-1 text-base font-semibold text-slate-950">{children}</h1>,
                                                h2: ({ children }) => <h2 className="mt-1 text-sm font-semibold text-slate-950">{children}</h2>,
                                                h3: ({ children }) => <h3 className="mt-1 text-sm font-semibold text-slate-950">{children}</h3>,
                                                a: ({ href, children }) => (
                                                    <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-600 underline hover:text-blue-800">
                                                        {children}
                                                    </a>
                                                ),
                                            }}
                                        >
                                            {msg.content}
                                        </ReactMarkdown>
                                    </div>
                                ) : (
                                    <p className="text-sm leading-relaxed whitespace-pre-wrap">{msg.content}</p>
                                )}

                                {/* Web Search Offer UI */}
                                {msg.role === 'assistant' && msg.webSearchOffered && !isTyping && (
                                    <div className="mt-3 pt-3 border-t border-slate-200/50">
                                        <div className="flex items-center gap-2 mb-2">
                                            <Search size={13} className="text-emerald-600" />
                                            <span className="text-xs font-medium text-slate-700">Search the web?</span>
                                        </div>
                                        <div className="flex gap-2">
                                            <button
                                                onClick={() => handleAcceptWebSearch(findUserQuestion(idx), idx)}
                                                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 text-white text-xs font-medium hover:bg-emerald-700 transition-colors"
                                            >
                                                <Globe size={12} /> Yes, search web
                                            </button>
                                            <button
                                                onClick={() => handleDeclineWebSearch(idx)}
                                                className="px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 text-xs font-medium hover:bg-slate-100 transition-colors"
                                            >
                                                No thanks
                                            </button>
                                        </div>
                                    </div>
                                )}

                                {/* Internal document sources */}
                                {msg.sources && msg.sources.length > 0 && (
                                    <div className="mt-3 pt-3 border-t border-slate-200/50 space-y-2">
                                        <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1">📄 Internal Sources:</p>
                                        <div className="flex flex-wrap gap-2">
                                            {msg.sources.map((src, sIdx) => (
                                                <div key={sIdx} className="flex items-center gap-1 px-2 py-1 bg-white/50 rounded text-[11px] text-slate-600 border border-slate-200">
                                                    <FileText size={10} />
                                                    {src.source} {src.page ? `(p.${src.page})` : ''}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {/* External web sources */}
                                {msg.externalSources && msg.externalSources.length > 0 && (
                                    <div className="mt-3 pt-3 border-t border-slate-200/50 space-y-2">
                                        <p className="text-[10px] font-bold uppercase tracking-wider text-emerald-600 mb-1">🌐 Web Sources:</p>
                                        <div className="flex flex-col gap-1.5">
                                            {msg.externalSources.map((src, sIdx) => (
                                                <a
                                                    key={sIdx}
                                                    href={src.url}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    className="flex items-start gap-1.5 px-2 py-1.5 bg-emerald-50/70 hover:bg-emerald-100/70 rounded text-[11px] text-emerald-700 border border-emerald-200 transition-colors"
                                                >
                                                    <Globe size={10} className="mt-0.5 shrink-0" />
                                                    <div>
                                                        <div className="font-medium">{src.title || src.url}</div>
                                                        {src.snippet && <div className="text-emerald-600 opacity-80 truncate max-w-xs">{src.snippet}</div>}
                                                    </div>
                                                </a>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {/* Token usage */}
                                {msg.role === 'assistant' && msg.usage && (
                                    <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-200/50 pt-3 text-[11px] text-slate-500">
                                        <span className="rounded border border-slate-200 bg-white/70 px-2 py-1">
                                            {msg.usage.total_tokens || 0} tokens
                                        </span>
                                        <span className="rounded border border-slate-200 bg-white/70 px-2 py-1">
                                            in {msg.usage.input_tokens || 0} / out {msg.usage.output_tokens || 0}
                                        </span>
                                        {msg.usage.cached && (
                                            <span className="rounded border border-green-200 bg-green-50 px-2 py-1 text-green-700">
                                                cache hit
                                            </span>
                                        )}
                                        {msg.webSearchPerformed && (
                                            <span className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1 text-emerald-700 flex items-center gap-1">
                                                <Globe size={9} /> web searched
                                            </span>
                                        )}
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                ))}

                {isTyping && (
                    <div className="flex justify-start">
                        <div className="flex gap-3">
                            <div className="w-8 h-8 rounded-full bg-slate-200 text-slate-600 flex items-center justify-center">
                                <Bot size={16} />
                            </div>
                            <div className="bg-slate-100 p-4 rounded-2xl rounded-tl-none">
                                <Loader2 className="animate-spin text-slate-400" size={18} />
                            </div>
                        </div>
                    </div>
                )}
            </div>

            {/* Input Area */}
            <form onSubmit={handleSend} className="p-4 border-t border-slate-100 bg-slate-50/50">
                <div className="relative flex items-center gap-2">
                    <input
                        type="text"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        placeholder="Type your question..."
                        className="flex-1 p-3 pr-12 rounded-xl border border-slate-200 bg-white outline-none focus:ring-2 focus:ring-blue-500 transition-all text-sm"
                    />
                    <button
                        type="submit"
                        disabled={!input.trim() || isTyping}
                        className="absolute right-2 p-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-slate-300 transition-colors"
                    >
                        <Send size={18} />
                    </button>
                </div>
                <p className="mt-1.5 text-[10px] text-slate-400 text-center">
                    Searches internal docs first · Offers web search if needed
                </p>
            </form>
        </div>
    );
};

export default ChatPage;
