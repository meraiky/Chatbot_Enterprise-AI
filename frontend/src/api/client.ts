import axios from 'axios';

const apiClient = axios.create({
    baseURL: '/api',
    withCredentials: true,  // send httpOnly auth cookie on every request
    headers: {},
});

let refreshPromise: Promise<unknown> | null = null;

apiClient.interceptors.response.use(
    (response) => response,
    async (error) => {
        if (!axios.isAxiosError(error) || error.response?.status !== 401 || !error.config) {
            return Promise.reject(error);
        }

        const originalRequest = error.config;
        const requestUrl = String(originalRequest.url || '');
        if (
            (originalRequest as { _retry?: boolean })._retry ||
            requestUrl.includes('/v1/auth/login') ||
            requestUrl.includes('/v1/auth/refresh')
        ) {
            return Promise.reject(error);
        }

        (originalRequest as { _retry?: boolean })._retry = true;
        refreshPromise = refreshPromise || apiClient.post('/v1/auth/refresh');
        try {
            await refreshPromise;
            return apiClient(originalRequest);
        } finally {
            refreshPromise = null;
        }
    },
);

export const getApiErrorMessage = (error: unknown, fallback: string) => {
    if (axios.isAxiosError(error)) {
        const data = error.response?.data;
        const detail = data?.detail;
        if (typeof detail === 'string' && detail.trim()) {
            return detail;
        }
        if (Array.isArray(detail) && detail.length > 0) {
            return detail
                .map((item) => item?.msg || item?.message || JSON.stringify(item))
                .join('; ');
        }
        // ChatbotException responses use a `message` field instead of `detail`
        if (typeof data?.message === 'string' && data.message.trim()) {
            return data.message;
        }
        if (error.message) {
            return error.message;
        }
    }

    if (error instanceof Error && error.message) {
        return error.message;
    }

    return fallback;
};

export default apiClient;
