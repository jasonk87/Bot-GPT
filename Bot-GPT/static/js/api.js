const API_BASE = '/api';

export async function checkAuth() {
    return await fetch(`${window.location.origin}/check_auth`);
}

export async function handleAuth(username, password, isLogin) {
    const url = isLogin ? '/login' : '/register';
    return await fetch(`${window.location.origin}${url}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
    });
}

export async function logout() {
    await fetch(`${window.location.origin}/logout`);
}

export function startChatEventSource(message) {
    const params = new URLSearchParams({
        message: JSON.stringify(message),
    });
    return new EventSource(`/api/chat?${params.toString()}`);
}
