import axios from 'axios';

const apiClient = axios.create({
    baseURL: '/api',
    withCredentials: true,  // send httpOnly auth cookie on every request
    headers: {},
});

export const getApiErrorMessage = (error: unknown, fallback: string) => {
    if (axios.isAxiosError(error)) {
        const detail = error.response?.data?.detail;
        if (typeof detail === 'string' && detail.trim()) {
            return detail;
        }
        if (Array.isArray(detail) && detail.length > 0) {
            return detail
                .map((item) => item?.msg || item?.message || JSON.stringify(item))
                .join('; ');
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
