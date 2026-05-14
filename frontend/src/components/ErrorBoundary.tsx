import React, { Component, ErrorInfo, ReactNode } from 'react';
import { AlertTriangle, RefreshCcw } from 'lucide-react';

interface Props {
    children: ReactNode;
}

interface State {
    hasError: boolean;
    error: Error | null;
}

class ErrorBoundary extends Component<Props, State> {
    public state: State = {
        hasError: false,
        error: null,
    };

    public static getDerivedStateFromError(error: Error): State {
        return { hasError: true, error };
    }

    public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
        console.error("Uncaught error:", error, errorInfo);
    }

    private handleReset = () => {
        this.setState({ hasError: false, error: null });
        window.location.reload();
    };

    public render() {
        if (this.state.hasError) {
            return (
                <div className="flex items-center justify-center h-full w-full p-6">
                    <div className="max-w-md w-full bg-white rounded-2xl shadow-lg border border-red-100 p-8 text-center space-y-4">
                        <div className="mx-auto w-16 h-16 bg-red-50 text-red-500 rounded-full flex items-center justify-center">
                            <AlertTriangle size={32} />
                        </div>
                        <div className="space-y-2">
                            <h3 className="text-xl font-bold text-slate-900">Something went wrong</h3>
                            <p className="text-slate-500 text-sm">
                                An unexpected error occurred in the application. We've been notified and are looking into it.
                            </p>
                        </div>
                        {this.state.error && (
                            <div className="p-3 bg-slate-50 rounded-lg text-left text-xs font-mono text-slate-600 overflow-auto max-h-32 border border-slate-200">
                                {this.state.error.message}
                            </div>
                        )}
                        <button
                            onClick={this.handleReset}
                            className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-slate-900 text-white rounded-xl hover:bg-slate-800 transition-colors font-medium"
                        >
                            <RefreshCcw size={18} />
                            Reload Application
                        </button>
                    </div>
                </div>
            );
        }

        return this.props.children;
    }
}

export default ErrorBoundary;
