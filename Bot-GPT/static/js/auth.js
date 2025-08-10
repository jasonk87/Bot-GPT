export function setupAuth(initializeApp) {
    const authScreen = document.getElementById('auth-screen');
    const mainApp = document.getElementById('main-app');
    const loginForm = document.getElementById('login-form');
    const registerForm = document.getElementById('register-form');
    const authTabs = document.querySelectorAll('.auth-tab-btn');
    const authError = document.getElementById('auth-error');

    authTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            authTabs.forEach(t => {
                t.classList.remove('border-blue-500', 'text-white');
                t.classList.add('text-gray-400');
            });
            tab.classList.add('border-blue-500', 'text-white');
            tab.classList.remove('text-gray-400');
            if (tab.dataset.tab === 'login') {
                loginForm.classList.remove('hidden');
                registerForm.classList.add('hidden');
            } else {
                loginForm.classList.add('hidden');
                registerForm.classList.remove('hidden');
            }
            authError.textContent = '';
        });
    });

    async function handleAuthFormSubmit(e) {
        e.preventDefault();
        const isLogin = e.target.id === 'login-form';
        const url = isLogin ? '/login' : '/register';
        const username = document.getElementById(`${isLogin ? 'login' : 'register'}-username`).value;
        const password = document.getElementById(`${isLogin ? 'login' : 'register'}-password`).value;

        const response = await fetch(`${window.location.origin}${url}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
        });
        const data = await response.json();
        if (response.ok) {
            authScreen.style.display = 'none';
            mainApp.style.display = 'flex';
            initializeApp(data.username);
        } else {
            authError.textContent = data.message;
        }
    }

    loginForm.addEventListener('submit', handleAuthFormSubmit);
    registerForm.addEventListener('submit', handleAuthFormSubmit);
}

export async function checkAuth(initializeApp) {
    const authScreen = document.getElementById('auth-screen');
    const mainApp = document.getElementById('main-app');
    const response = await fetch(`${window.location.origin}/check_auth`);
    if (response.ok) {
        const user = await response.json();
        authScreen.style.display = 'none';
        mainApp.style.display = 'flex';
        initializeApp(user.username);
    } else {
        authScreen.style.display = 'flex';
        mainApp.style.display = 'none';
    }
}
