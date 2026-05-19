import React, { useState, useEffect } from 'react';
import { MessageSquare, LayoutDashboard, User, ShieldCheck, LogIn, LogOut, Settings } from 'lucide-react';
import ChatPage from './pages/ChatPage';
import AdminPage from './pages/AdminPage';
import UserSettingsPage from './pages/UserSettingsPage';
import { useChatStore } from './stores/chatStore';
import ErrorBoundary from './components/ErrorBoundary';
import apiClient, { getApiErrorMessage } from './api/client';

export interface CurrentUser {
    username: string;
    role: string;
    can_manage_models: boolean;
}

type AppView = 'chat' | 'admin' | 'settings';

function App() {
    const [view, setView] = useState<AppView>('chat');
    const [visitedViews, setVisitedViews] = useState<Record<AppView, boolean>>({
        chat: true,
        admin: false,
        settings: false,
    });
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
    const [authChecked, setAuthChecked] = useState(false);
    const [authError, setAuthError] = useState<string | null>(null);
    const [loggingIn, setLoggingIn] = useState(false);
    const { mode, setMode } = useChatStore();

    const isAuthenticated = Boolean(currentUser);

    const showView = (nextView: AppView) => {
        setView(nextView);
        setVisitedViews((prev) => (
            prev[nextView] ? prev : { ...prev, [nextView]: true }
        ));
    };

    // Restore session from existing httpOnly cookie on page load
    useEffect(() => {
        apiClient.get<CurrentUser>('/v1/auth/me')
            .then(res => setCurrentUser(res.data))
            .catch(() => setCurrentUser(null))
            .finally(() => setAuthChecked(true));
    }, []);

    const handleLogin = async (event: React.FormEvent) => {
        event.preventDefault();
        setLoggingIn(true);
        setAuthError(null);
        try {
            const form = new URLSearchParams();
            form.set('username', username);
            form.set('password', password);
            // Login sets httpOnly cookie — no need to store the token ourselves
            await apiClient.post('/v1/auth/login', form, {
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            });
            const me = await apiClient.get<CurrentUser>('/v1/auth/me');
            setCurrentUser(me.data);
            setPassword('');
        } catch (error: unknown) {
            setAuthError(getApiErrorMessage(error, 'Login failed. Check your credentials.'));
        } finally {
            setLoggingIn(false);
        }
    };

    const handleLogout = async () => {
        try {
            await apiClient.post('/v1/auth/logout');
        } catch {
            // best-effort — clear local state regardless
        }
        setCurrentUser(null);
        setView('chat');
        setVisitedViews({ chat: true, admin: false, settings: false });
    };

    // Don't render until we know auth state (avoids flash of login form)
    if (!authChecked) {
        return (
            <div className="flex h-screen items-center justify-center bg-slate-50">
                <div className="text-slate-400 text-sm">Loading...</div>
            </div>
        );
    }

    return (
        <div className="flex h-screen bg-slate-50 text-slate-900 font-sans">
            {/* Sidebar */}
            <aside className="w-64 bg-slate-900 text-white flex flex-col">
                <div className="p-6">
                    <h1 className="text-xl font-bold flex items-center gap-2">
                        <ShieldCheck className="text-blue-400" />
                        Enterprise AI
                    </h1>
                </div>

                <nav className="flex-1 px-4 space-y-2">
                    <button
                        onClick={() => showView('chat')}
                        className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${view === 'chat' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:bg-slate-800 hover:text-white'}`}
                    >
                        <MessageSquare size={20} />
                        Chat Assistant
                    </button>
                    {isAuthenticated && currentUser?.role === 'admin' && (
                        <button
                            onClick={() => showView('admin')}
                            className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${view === 'admin' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:bg-slate-800 hover:text-white'}`}
                        >
                            <LayoutDashboard size={20} />
                            Admin Dashboard
                        </button>
                    )}
                    {isAuthenticated && (
                        <button
                            onClick={() => showView('settings')}
                            className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${view === 'settings' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:bg-slate-800 hover:text-white'}`}
                        >
                            <Settings size={20} />
                            My Settings
                        </button>
                    )}
                </nav>

                <div className="p-4 border-t border-slate-800">
                    {isAuthenticated ? (
                        <div className="space-y-3">
                            <div className="flex items-center gap-3 px-4 text-slate-300">
                                <User size={20} />
                                <span className="text-sm">{currentUser!.username}</span>
                            </div>
                            <button
                                onClick={handleLogout}
                                className="w-full flex items-center justify-center gap-2 rounded-lg bg-slate-800 px-3 py-2 text-sm text-slate-200 hover:bg-slate-700"
                            >
                                <LogOut size={16} />
                                Logout
                            </button>
                        </div>
                    ) : (
                        <form onSubmit={handleLogin} className="space-y-3">
                            <div className="flex items-center gap-2 text-slate-300">
                                <LogIn size={18} />
                                <span className="text-sm font-medium">Admin Login</span>
                            </div>
                            <input
                                value={username}
                                onChange={(event) => setUsername(event.target.value)}
                                placeholder="Username"
                                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:ring-2 focus:ring-blue-500"
                            />
                            <input
                                type="password"
                                value={password}
                                onChange={(event) => setPassword(event.target.value)}
                                placeholder="Password"
                                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:ring-2 focus:ring-blue-500"
                            />
                            {authError && <p className="text-xs text-red-300">{authError}</p>}
                            <button
                                disabled={loggingIn || !username.trim() || !password}
                                className="w-full rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-400"
                            >
                                {loggingIn ? 'Signing in...' : 'Sign in'}
                            </button>
                        </form>
                    )}
                </div>
            </aside>

            {/* Main Content */}
            <main className="flex-1 flex flex-col overflow-hidden">
                <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-8">
                    <h2 className="text-lg font-semibold">
                        {view === 'chat' ? 'AI Chat Assistant' : view === 'admin' ? 'System Administration' : 'My Settings'}
                    </h2>

                    {view === 'chat' && (
                        <div className="flex items-center gap-3">
                            <span className="text-sm text-slate-500">Mode:</span>
                            <select
                                value={mode}
                                onChange={(e) => setMode(e.target.value as 'Internal' | 'External')}
                                className="text-sm border border-slate-300 rounded px-2 py-1 bg-white outline-none focus:ring-2 focus:ring-blue-500"
                            >
                                <option value="External">External (Public)</option>
                                <option value="Internal">Internal (Private)</option>
                            </select>
                        </div>
                    )}
                </header>

                <div className="flex-1 overflow-auto p-6">
                    <ErrorBoundary>
                        <section className={`h-full transition-opacity duration-200 ${view === 'chat' ? 'opacity-100' : 'opacity-0 pointer-events-none absolute'}`}>
                            <ChatPage
                                isAuthenticated={isAuthenticated}
                                isAdmin={currentUser?.role === 'admin'}
                            />
                        </section>
                        {isAuthenticated && currentUser?.role === 'admin' && visitedViews.admin && (
                            <section className={`h-full transition-opacity duration-200 ${view === 'admin' ? 'opacity-100' : 'opacity-0 pointer-events-none absolute'}`}>
                                <AdminPage currentUser={currentUser} />
                            </section>
                        )}
                        {isAuthenticated && visitedViews.settings && (
                            <section className={`h-full transition-opacity duration-200 ${view === 'settings' ? 'opacity-100' : 'opacity-0 pointer-events-none absolute'}`}>
                                <UserSettingsPage />
                            </section>
                        )}
                    </ErrorBoundary>
                </div>
            </main>
        </div>
    );
}

export default App;
