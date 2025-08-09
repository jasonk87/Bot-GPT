// Global scope for elements that are always present
const authScreen = document.getElementById('auth-screen');
const mainApp = document.getElementById('main-app');
const loginForm = document.getElementById('login-form');
const registerForm = document.getElementById('register-form');
const authTabs = document.querySelectorAll('.auth-tab-btn');
const authError = document.getElementById('auth-error');

// App-specific elements, to be initialized after login
let chatContainer, chatInput, sendButton, modelSelect, fileExplorer,
    welcomeUser, logoutBtn, deleteModal, deleteModalText, cancelDeleteBtn, confirmDeleteBtn,
    conversationList, newChatBtn, chatsTabBtn, filesTabBtn, conversationsPanel, filesPanel,
    sidePanel, menuBtn, welcomeMessage, uploadBtn, fileInput, closeViewerBtn, overlay,
    uploadModal, uploadForm, cancelUploadBtn, dropZone, fileList, uploadPrompt,
    settingsBtn, settingsModal, settingsForm, cancelSettingsBtn, personaSelect, currentModelDisplay,
    shareModal, cancelShareBtn, shareUserList,
    copyFileBtn, saveFileBtn, chatColumn, canvasColumn, fileViewerEl, canvasToggleBtn;

const API_BASE = '/api';
let conversationHistory = [];
let currentConversationId = null;
let currentConversationRole = null;
let deleteResolver = null;
let userModel = null;
let editor = null;
let eventSource = null;

// --- Agent State ---
let isAgentRunning = false;
let isCanvasMode = false;
let currentAgentBubble = null;

// Configure marked.js to render line breaks
marked.setOptions({
    breaks: true,
    gfm: true
});

document.addEventListener('DOMContentLoaded', async () => {
    const response = await fetch(`${window.location.origin}/check_auth`);
    if (response.ok) {
        const user = await response.json();
        initializeApp(user.username);
    } else {
        authScreen.style.display = 'flex';
        mainApp.style.display = 'none';
    }
});

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

loginForm.addEventListener('submit', handleAuthFormSubmit);
registerForm.addEventListener('submit', handleAuthFormSubmit);

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
        initializeApp(data.username);
    } else {
        authError.textContent = data.message;
    }
}

function isScrolledToBottom(el) {
    const threshold = 5; // A small buffer in pixels
    // Check if the user is within the threshold of the bottom
    return el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
}

async function initializeApp(username) {
    
    authScreen.style.display = 'none';
    mainApp.style.display = 'flex';

    const style = document.createElement('style');
    // --- MODIFICATION START ---
    // The CSS selector that applied bottom margins has been modified
    // to EXCLUDE the 'pre' element. This stops the formatting from
    // affecting code blocks, making them look normal as requested.
    style.textContent = `
        /* --- General Bubble Styles --- */
        .user-bubble,
        .bot-bubble .answer-content {
            color: white;
        }

        .user-bubble ul, .bot-bubble .answer-content ul,
        .user-bubble ol, .bot-bubble .answer-content ol {
            padding-left: 1.5em;
        }
        .user-bubble ul { list-style-type: disc; }
        .user-bubble ol { list-style-type: decimal; }
        .bot-bubble .answer-content ul { list-style-type: disc; }
        .bot-bubble .answer-content ol { list-style-type: decimal; }

        /* --- Definitive Styles for AI Response Readability (CODE BLOCKS EXCLUDED) --- */
        .bot-bubble .answer-content > p,
        .bot-bubble .answer-content > ul,
        .bot-bubble .answer-content > ol,
        .bot-bubble .answer-content > h1,
        .bot-bubble .answer-content > h2,
        .bot-bubble .answer-content > h3,
        .bot-bubble .answer-content > blockquote,
        .bot-bubble .answer-content > table {
            margin-bottom: 1.25em;
        }

        .bot-bubble .answer-content li {
            margin-bottom: 0.5em;
        }
        .bot-bubble .answer-content li:last-child {
            margin-bottom: 0;
        }

        .bot-bubble .answer-content > *:last-child {
            margin-bottom: 0;
        }

        /* --- Agent Status Bar & Animations --- */
        #agent-status-bar {
            display: none;
            padding: 8px;
            margin: 10px 20px;
            background-color: rgba(44, 62, 80, 0.5);
            border-radius: 8px;
            text-align: center;
            font-style: italic;
            color: #bdc3c7;
            transition: all 0.3s ease;
        }
        #agent-status-bar.active {
            display: block;
        }
        .dots span {
            animation: blink 1.4s infinite both;
            display: inline-block;
        }
        .dots span:nth-child(2) { animation-delay: 0.2s; }
        .dots span:nth-child(3) { animation-delay: 0.4s; }
        @keyframes blink {
            0% { opacity: 0.2; }
            20% { opacity: 1; }
            100% { opacity: 0.2; }
        }
        .agent-active-glow {
            border-radius: 12px;
            box-shadow: 0 0 15px rgba(52, 152, 219, 0.5);
            animation: glow 2s infinite alternate;
            transition: box-shadow 0.3s ease-in-out;
        }
        @keyframes glow {
            from { box-shadow: 0 0 5px rgba(52, 152, 219, 0.3); }
            to { box-shadow: 0 0 20px rgba(52, 152, 219, 0.8); }
        }
        .avatar-thinking {
            animation: pulse-avatar 1.5s infinite;
        }
        @keyframes pulse-avatar {
            0% { transform: scale(1); box-shadow: 0 0 0 0 rgba(52, 152, 219, 0.4); }
            70% { transform: scale(1.05); box-shadow: 0 0 5px 7px rgba(52, 152, 219, 0); }
            100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(52, 152, 219, 0); }
        }
    `;
    // --- MODIFICATION END ---
    document.head.appendChild(style);

    // Initialize app-specific elements
    chatContainer = document.getElementById('chat-container');
    chatInput = document.getElementById('chat-input');
    sendButton = document.getElementById('send-button');
    modelSelect = document.getElementById('model-select');
    fileExplorer = document.getElementById('file-explorer');
    welcomeUser = document.getElementById('welcome-user');
    logoutBtn = document.getElementById('logout-btn');
    deleteModal = document.getElementById('delete-modal');
    deleteModalText = document.getElementById('delete-modal-text');
    cancelDeleteBtn = document.getElementById('cancel-delete-btn');
    confirmDeleteBtn = document.getElementById('confirm-delete-btn');
    conversationList = document.getElementById('conversation-list');
    newChatBtn = document.getElementById('new-chat-btn');
    chatsTabBtn = document.getElementById('chats-tab-btn');
    filesTabBtn = document.getElementById('files-tab-btn');
    conversationsPanel = document.getElementById('conversations-panel');
    filesPanel = document.getElementById('files-panel');
    sidePanel = document.getElementById('side-panel');
    menuBtn = document.getElementById('menu-btn');
    welcomeMessage = document.getElementById('welcome-message');
    uploadBtn = document.getElementById('upload-btn');
    closeViewerBtn = document.getElementById('close-viewer-btn');
    overlay = document.getElementById('overlay');
    uploadModal = document.getElementById('upload-modal');
    uploadForm = document.getElementById('upload-form');
    cancelUploadBtn = document.getElementById('cancel-upload-btn');
    dropZone = document.getElementById('drop-zone');
    fileInput = document.getElementById('file-input');
    fileList = document.getElementById('file-list');
    uploadPrompt = document.getElementById('upload-prompt');
    settingsBtn = document.getElementById('settings-btn');
    settingsModal = document.getElementById('settings-modal');
    settingsForm = document.getElementById('settings-form');
    cancelSettingsBtn = document.getElementById('cancel-settings-btn');
    personaSelect = document.getElementById('persona-select');
    currentModelDisplay = document.getElementById('current-model-display');
    shareModal = document.getElementById('share-modal');
    cancelShareBtn = document.getElementById('cancel-share-btn');
    shareUserList = document.getElementById('share-user-list');
    copyFileBtn = document.getElementById('copy-file-btn');
    saveFileBtn = document.getElementById('save-file-btn');
    chatColumn = document.getElementById('chat-column');
    canvasColumn = document.getElementById('canvas-column');
    fileViewerEl = document.getElementById('file-viewer');
    canvasToggleBtn = document.getElementById('canvas-toggle-btn');

    welcomeUser.textContent = `Welcome, ${username}!`;

    // Attach event listeners
    logoutBtn.addEventListener('click', async () => {
        await fetch(`${window.location.origin}/logout`);
        window.location.reload();
    });
    
    newChatBtn.addEventListener('click', startNewChat);
    cancelDeleteBtn.addEventListener('click', () => deleteResolver(false));
    confirmDeleteBtn.addEventListener('click', () => deleteResolver(true));
    closeViewerBtn.addEventListener('click', closeFileCanvas);

    chatsTabBtn.addEventListener('click', () => switchSidePanel('chats'));
    filesTabBtn.addEventListener('click', () => switchSidePanel('files'));
    
    menuBtn.addEventListener('click', () => {
        sidePanel.classList.toggle('-translate-x-full');
        overlay.classList.toggle('hidden');
    });
    
    overlay.addEventListener('click', () => {
         sidePanel.classList.add('-translate-x-full');
         overlay.classList.add('hidden');
    });

    // --- Upload Modal Logic ---
    uploadBtn.addEventListener('click', () => uploadModal.classList.remove('hidden'));
    cancelUploadBtn.addEventListener('click', () => uploadModal.classList.add('hidden'));
    dropZone.addEventListener('click', () => fileInput.click());
    dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('drag-over'); });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('drag-over');
        fileInput.files = e.dataTransfer.files;
        updateFileList();
    });
    fileInput.addEventListener('change', updateFileList);
    uploadForm.addEventListener('submit', handleFileUpload);
    
    // --- Settings Modal Logic ---
    settingsBtn.addEventListener('click', () => settingsModal.classList.remove('hidden'));
    cancelSettingsBtn.addEventListener('click', () => settingsModal.classList.add('hidden'));
    settingsForm.addEventListener('submit', handleSaveSettings);

    // --- Share Modal Logic ---
    cancelShareBtn.addEventListener('click', () => shareModal.classList.add('hidden'));

    // --- File Canvas Logic ---
    canvasToggleBtn.addEventListener('click', () => {
        isCanvasMode = !isCanvasMode;
        canvasToggleBtn.classList.toggle('bg-blue-600', isCanvasMode);
        canvasToggleBtn.classList.toggle('text-white', isCanvasMode);
    });

    copyFileBtn.addEventListener('click', () => {
        if (editor) {
            navigator.clipboard.writeText(editor.getValue());
            copyFileBtn.textContent = 'Copied!';
            setTimeout(() => { copyFileBtn.textContent = 'Copy'; }, 2000);
        }
    });

    saveFileBtn.addEventListener('click', async () => {
        if (editor) {
            const path = document.getElementById('file-viewer-filename').textContent;
            const content = editor.getValue();
            try {
                const response = await fetch(`${window.location.origin}${API_BASE}/workspace/file`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        path: path,
                        content: content,
                        conversation_id: currentConversationId
                    })
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error);
                saveFileBtn.textContent = 'Saved!';
                setTimeout(() => { saveFileBtn.textContent = 'Save'; }, 2000);
            } catch (error) {
                alert(`Error saving file: ${error.message}`);
            }
        }
    });

    sendButton.addEventListener('click', () => sendMessage());
    chatInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            sendMessage();
        }
    });
    // Auto-resize textarea
    chatInput.addEventListener('input', () => {
        chatInput.style.height = 'auto';
        chatInput.style.height = (chatInput.scrollHeight) + 'px';
    });

    await populateModels();
    await loadUserSettings();
    await populateFileExplorer();
    await populateConversations();
}

async function loadUserSettings() {
    try {
        const response = await fetch(`${API_BASE}/settings`);
        const settings = await response.json();
        
        personaSelect.innerHTML = '';
        for (const [key, name] of Object.entries(settings.available_personas)) {
            const option = document.createElement('option');
            option.value = key;
            option.textContent = name;
            personaSelect.appendChild(option);
        }
        
        userModel = settings.model || (modelSelect.options.length > 0 ? modelSelect.options[0].value : '');
        if (userModel) modelSelect.value = userModel;
        currentModelDisplay.textContent = userModel;
        personaSelect.value = settings.persona || 'default';

    } catch (error) {
        console.error("Failed to load user settings:", error);
    }
}

async function handleSaveSettings(e) {
    e.preventDefault();
    const newModel = modelSelect.value;
    const newPersona = personaSelect.value;
    try {
        const response = await fetch(`${API_BASE}/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: newModel, persona: newPersona }),
        });
        if (!response.ok) throw new Error('Failed to save settings');
        userModel = newModel;
        currentModelDisplay.textContent = userModel;
        settingsModal.classList.add('hidden');
    } catch (error) {
        alert(`Error saving settings: ${error.message}`);
    }
}

function switchSidePanel(tab) {
    if (tab === 'chats') {
        conversationsPanel.style.display = 'flex';
        filesPanel.style.display = 'none';
        chatsTabBtn.classList.add('active');
        filesTabBtn.classList.remove('active');
    } else {
        conversationsPanel.style.display = 'none';
        filesPanel.style.display = 'flex';
        chatsTabBtn.classList.remove('active');
        filesTabBtn.classList.add('active');
    }
}

async function populateModels() {
    try {
        const response = await fetch(`${window.location.origin}${API_BASE}/models`);
        if (!response.ok) throw new Error("Failed to fetch models");
        const models = await response.json();
        modelSelect.innerHTML = '';
        models.forEach(model => {
            const option = document.createElement('option');
            option.value = model.name;
            option.textContent = model.name;
            modelSelect.appendChild(option);
        });
    } catch (error) { console.error("Failed to fetch models:", error); }
}

async function populateFileExplorer() {
    if (!currentConversationId) {
        fileExplorer.innerHTML = '<p class="text-gray-400">No active conversation. Start a new chat to see files.</p>';
        return;
    }
    try {
        const response = await fetch(`${window.location.origin}${API_BASE}/workspace/files/${currentConversationId}`);
        const files = await response.json();
        fileExplorer.innerHTML = buildFileTree(files);
        attachFileEventListeners();
    } catch (error) {
        console.error("Failed to populate file explorer:", error);
        fileExplorer.innerHTML = '<p class="text-red-400">Could not load files.</p>';
    }
}

function buildFileTree(nodes, pathPrefix = '') {
    if (!nodes || nodes.length === 0) return '';
    let html = '<ul class="space-y-1">';
    nodes.forEach(node => {
        const fullPath = pathPrefix ? `${pathPrefix}/${node.name}` : node.name;
        const isDir = node.type === 'directory';
        const icon = isDir ? '&#128193;' : '&#128196;';
                
        let deleteBtn = '';
        if (currentConversationRole === 'owner') {
            deleteBtn = `<button class="delete-btn text-red-500 hover:text-red-400 font-bold ml-2 flex-shrink-0" title="Delete">&times;</button>`;
        }

        html += `<li class="file-item item-hover flex items-center justify-between group" data-path="${fullPath}" data-type="${node.type}">
                    <span class="flex-1 cursor-pointer hover:text-blue-400 truncate">${icon} ${node.name}</span>
                    ${deleteBtn}
                 </li>`;
        if (isDir && node.children) {
            html += `<li class="pl-4">${buildFileTree(node.children, fullPath)}</li>`;
        }
    });
    html += '</ul>';
    return html;
}

function attachFileEventListeners() {
    document.querySelectorAll('.file-item').forEach(item => {
        const path = item.dataset.path;
        const type = item.dataset.type;
        item.querySelector('span').addEventListener('click', () => {
            if (type === 'file') {
                openFileCanvas(path);
            }
        });
                
        const deleteBtn = item.querySelector('.delete-btn');
        if (deleteBtn) {
            deleteBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                confirmDeletion(path, type, 'file');
            });
        }
    });
}

async function openFileCanvas(path) {
    try {
        if (editor) {
            editor.toTextArea();
            editor = null;
        }

        const response = await fetch(`${window.location.origin}${API_BASE}/workspace/file?path=${encodeURIComponent(path)}&conversation_id=${currentConversationId}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);

        document.getElementById('file-viewer-filename').textContent = path;
        
        // Show canvas column and adjust chat column width
        canvasColumn.classList.remove('hidden');
        canvasColumn.classList.add('flex');
        chatColumn.classList.remove('w-full');
        chatColumn.classList.add('md:w-1/2');
        // On mobile, hide chat column completely
        if (window.innerWidth < 768) {
            chatColumn.classList.add('hidden');
        }

        let mode = 'text/plain';
        if (path.endsWith('.py')) mode = 'python';
        if (path.endsWith('.js')) mode = 'javascript';

        initializeEditor(data.content, mode);
    } catch (error) {
        alert(`Error opening file: ${error.message}`);
    }
}

function closeFileCanvas() {
    // V2.2 Bug Fix: Add a more robust check to prevent errors when closing an already-closed canvas.
    if (editor && typeof editor.toTextArea === 'function') {
        editor.toTextArea();
    }
    editor = null; // Always nullify the editor
    canvasColumn.classList.add('hidden');
    canvasColumn.classList.remove('flex');
    chatColumn.classList.remove('md:w-1/2', 'hidden');
    chatColumn.classList.add('w-full');
}

function initializeEditor(content, mode) {
    // V2.2 Bug Fix: Add a more robust check
    if (editor && typeof editor.toTextArea === 'function') {
        editor.toTextArea();
    }
    editor = null;
    fileViewerEl.innerHTML = ''; // Clear previous editor
    editor = CodeMirror(fileViewerEl, {
        value: content,
        mode: mode,
        theme: 'dracula',
        lineNumbers: true,
        readOnly: currentConversationRole !== 'owner'
    });
}

async function confirmDeletion(id, type, itemType) {
    deleteModalText.textContent = `Are you sure you want to delete this ${itemType}: ${id}?`;
    deleteModal.classList.remove('hidden');
    const confirmed = await new Promise(resolve => { deleteResolver = resolve; });
    if (confirmed) {
        try {
            let url, body;
            if (itemType === 'file') {
                url = `${API_BASE}/workspace/file`;
                body = { path: id, conversation_id: currentConversationId };
            } else {
                url = `${API_BASE}/conversation/${id}`;
                body = {};
            }
            const response = await fetch(url, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (!response.ok) throw new Error(await response.text());
            
            if (itemType === 'file') {
                await populateFileExplorer();
            } else {
                await populateConversations();
                if (id === currentConversationId) {
                    startNewChat();
                }
            }
        } catch (error) {
            console.error(`Failed to delete ${id}:`, error);
            alert(`Error deleting ${itemType}: ${error.message}`);
        }
    }
    deleteModal.classList.add('hidden');
}

function updateFileList() {
    if (fileInput.files.length > 0) {
        fileList.innerHTML = `${fileInput.files.length} file(s) selected.`;
    } else {
        fileList.innerHTML = '';
    }
}

async function handleFileUpload(event) {
    event.preventDefault();
    const files = fileInput.files;
    if (files.length === 0) {
        alert('Please select files to upload.');
        return;
    }

    const formData = new FormData();
    formData.append('prompt', uploadPrompt.value);
    formData.append('conversation_id', currentConversationId || '');

    for (let i = 0; i < files.length; i++) {
        formData.append('files[]', files[i]);
    }

    try {
        const response = await fetch(`${window.location.origin}/api/upload`, {
            method: 'POST',
            body: formData,
        });
        const data = await response.json();
        if (response.ok) {
            if (!currentConversationId) {
                currentConversationId = data.conversation_id;
                conversationHistory = []; // Start fresh history
            }
            await populateFileExplorer();
            uploadModal.classList.add('hidden');
            uploadForm.reset();
            updateFileList();
            chatInput.value = data.message;
            sendMessage();
        } else {
            alert(`Error uploading file: ${data.error}`);
        }
    } catch (error) {
        alert(`Error uploading file: ${error.message}`);
    }
}

function setAgentRunning(isRunning) {
    isAgentRunning = isRunning;
    chatInput.disabled = isRunning;
    sendButton.disabled = isRunning;

    const inputContainer = document.getElementById('chat-input-container');

    if (isRunning) {
        sendButton.classList.add('bg-gray-500', 'cursor-not-allowed');
        sendButton.classList.remove('bg-blue-600', 'hover:bg-blue-700');
        sendButton.innerHTML = `<svg class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>`;
        inputContainer.classList.add('agent-active-glow');
        if (currentAgentBubble) {
            currentAgentBubble.querySelector('.w-8.h-8').classList.add('avatar-thinking');
        }
    } else {
        sendButton.classList.remove('bg-gray-500', 'cursor-not-allowed');
        sendButton.classList.add('bg-blue-600', 'hover:bg-blue-700');
        sendButton.innerHTML = `<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14M12 5l7 7-7 7"></path></svg>`;
        inputContainer.classList.remove('agent-active-glow');
        document.querySelectorAll('.avatar-thinking').forEach(el => {
            el.classList.remove('avatar-thinking');
        });

        // Also ensure the agent status bar is cleared
        const statusBar = document.getElementById('agent-status-bar');
        statusBar.classList.remove('active');
        statusBar.innerHTML = '';

        if (eventSource) {
            eventSource.close();
        }
    }
}

function sendMessage() {
    const text = chatInput.value.trim();
    if (!text || isAgentRunning) return;

    setAgentRunning(true);
    
    welcomeMessage.style.display = 'none';
    const userMessage = { role: 'user', content: text };
    appendMessage(text, 'user');
    conversationHistory.push(userMessage);
    
    chatInput.value = '';
    chatInput.style.height = 'auto';

    currentAgentBubble = createBotMessageContainer();
    let thinkContent = "";
    let finalAnswerContent = "";
    let inThinkBlock = true;
    
    const isNewConversation = !currentConversationId;

    const params = {
        message: JSON.stringify(userMessage),
        model: userModel,
        conversation_id: currentConversationId || ''
    };

    if (isCanvasMode) {
        params.canvas_mode = 'true';
    }

    eventSource = new EventSource(`/api/chat?${new URLSearchParams(params).toString()}`);

    eventSource.onmessage = function(event) {
        try {
            // --- MODIFICATION START ---
            // Check if we should scroll before making any changes
            const shouldScroll = isScrolledToBottom(chatContainer);
            // --- MODIFICATION END ---
            
            const data = JSON.parse(event.data);

            switch(data.type) {
                case 'conversation_id':
                    if (isNewConversation) {
                        currentConversationId = data.id;
                        addConversationToList(data.id, "New Chat");
                    }
                    break;
                case 'agent_start': {
                    const statusBar = document.getElementById('agent-status-bar');
                    const agentName = data.agent.replace('ask_', '').replace(/_/g, ' ');
                    const icon = getAgentIcon(agentName);
                    statusBar.innerHTML = `${icon} <strong>Delegating to ${agentName}...</strong>`;
                    statusBar.classList.add('active');
                    break;
                }
                case 'agent_thought': {
                    const statusBar = document.getElementById('agent-status-bar');
                    const icon = getAgentIcon('coder agent'); // Assume thoughts come from coder for now
                    statusBar.innerHTML = `${icon} <em>"${data.thought}"</em>`;
                    break;
                }
                case 'agent_tool_start': {
                    const statusBar = document.getElementById('agent-status-bar');
                     const icon = getAgentIcon('coder agent'); // Assume tools come from coder for now
                    statusBar.innerHTML = `${icon} <strong>Using tool:</strong> \`${data.tool}\``;
                    break;
                }
                case 'agent_end':
                    const endBar = document.getElementById('agent-status-bar');
                    endBar.classList.remove('active');
                    endBar.innerHTML = '';
                    break;
                case 'refresh_files':
                    populateFileExplorer();
                    break;
                case 'open_canvas':
                    if (isCanvasMode) {
                        openFileCanvas(data.filename);
                    }
                    populateFileExplorer();
                    break;
                case 'file_updated':
                    const currentCanvasFile = document.getElementById('file-viewer-filename').textContent;
                    if (editor && data.path === currentCanvasFile) {
                        editor.setValue(data.content);
                    }
                    break;
                case 'plan_step_update':
                    const planStepContainer = currentAgentBubble.querySelector('.plan-step-container');
                    const planStepContent = planStepContainer.querySelector('.plan-step-content');
                    planStepContainer.style.display = 'block';
                    planStepContent.textContent = `${data.step_number}. ${data.step_description}`;
                    break;
                case 'assistant_chunk':
                    if (inThinkBlock) {
                        thinkContent += data.content;
                        const thinkEndMatch = thinkContent.indexOf('</think>');
                        if (thinkEndMatch !== -1) {
                            inThinkBlock = false;
                            finalAnswerContent = thinkContent.substring(thinkEndMatch + 8);
                            thinkContent = thinkContent.substring(0, thinkEndMatch);
                            
                            const thinkingContainer = currentAgentBubble.querySelector('.thinking-process-container');
                            thinkingContainer.querySelector('.thinking-content').style.display = 'none';
                        }
                        
                        const thinkingContainer = currentAgentBubble.querySelector('.thinking-process-container');
                        thinkingContainer.style.display = 'block';
                        const thinkingContentEl = thinkingContainer.querySelector('.thinking-content');
                        thinkingContentEl.innerHTML = marked.parse(thinkContent.replace('<think>', ''));
                        
                        // This ensures the thinking box itself always scrolls
                        thinkingContentEl.scrollTop = thinkingContentEl.scrollHeight;
                        
                    } else {
                        finalAnswerContent += data.content;
                    }
                    updateBotBubble(currentAgentBubble, finalAnswerContent);
                    break;
                case 'assistant_end':
                    thinkContent = "";
                    finalAnswerContent = "";
                    inThinkBlock = true;
                    break;
                case 'tool_call':
                    showToolCall(currentAgentBubble, data.name, data.params);
                    break;
                case 'tool_result':
                    updateAgentStatus(currentAgentBubble, `Tool finished. Analyzing results...`, false);
                    break;
                case 'tool_error':
                    updateAgentStatus(currentAgentBubble, `Tool Error: ${data.error}. Thinking...`, true);
                    break;
                case 'final_answer':
                    conversationHistory.push({ role: 'assistant', content: data.content });
                    updateBotBubble(currentAgentBubble, data.content, true);
                    setAgentRunning(false);
                    eventSource.close();
                    populateConversations();
                    break;
                case 'agent_error':
                    updateAgentStatus(currentAgentBubble, `An error occurred: ${data.error}`, true);
                    setAgentRunning(false);
                    eventSource.close();
                    break;
            }

            // --- MODIFICATION START ---
            // If the user was at the bottom, scroll to the new bottom
            if (shouldScroll) {
                chatContainer.scrollTop = chatContainer.scrollHeight;
            }
            // --- MODIFICATION END ---
        } catch (e) {
            console.error("Error parsing SSE event data:", event.data, e);
        }
    };

    eventSource.onerror = function(err) {
        console.error("EventSource failed:", err);
        if(currentAgentBubble) updateAgentStatus(currentAgentBubble, "Connection to server lost. Please check the server logs and refresh the page.", true);
        setAgentRunning(false);
        eventSource.close();
    };
}

function getAgentIcon(agentName) {
    const icons = {
        'coder agent': `<svg class="w-5 h-5 inline-block mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l-4 4-4-4 4-4"></path></svg>`,
        'debugger': `<svg class="w-5 h-5 inline-block mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 8v8m-3-5v3m-3-1v1m-4-3h12a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h1m6 0h1a2 2 0 012 2v2"></path></svg>`,
        'default': `<svg class="w-5 h-5 inline-block mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 16v-2m8-6h-2M4 12H2m15.364 6.364l-1.414-1.414M6.05 6.05L4.636 4.636m12.728 0l-1.414 1.414M6.05 17.95l-1.414 1.414"></path></svg>`
    };
    for (const key in icons) {
        if (agentName.includes(key)) {
            return icons[key];
        }
    }
    return icons['default'];
}

function createBotMessageContainer(animate = true) {
    // --- MODIFICATION START ---
    const shouldScroll = isScrolledToBottom(chatContainer);
    // --- MODIFICATION END ---

    const botMessageWrapper = document.createElement('div');
    let classes = 'flex max-w-3xl w-full items-start self-start mx-auto';
    if (animate) {
        classes += ' newly-added';
    }
    botMessageWrapper.className = classes;
    
    botMessageWrapper.innerHTML = `
        <div class="w-8 h-8 flex-shrink-0 mr-2 text-gray-400">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-full h-full">
                <path d="M12 2a2 2 0 0 0-2 2v2h4V4a2 2 0 0 0-2-2zM6 8v10c0 1.1.9 2 2 2h8a2 2 0 0 0 2-2V8H6zM4 8c-1.1 0-2 .9-2 2v8a2 2 0 0 0 2 2h2v-2H4V10h2V8H4zm16 0h-2v2h2v8h-2v2h2a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2zM9 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0zm6 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0z" />
            </svg>
        </div>
        <div class="flex-1 bot-bubble">
            <div class="thinking-process-container" style="display: none;">
                <div class="thinking-header">
                    <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 9l4-4 4 4m0 6l-4 4-4-4"></path></svg>
                    <span>Thinking...</span>
                </div>
                <div class="thinking-content prose prose-invert max-w-none"></div>
            </div>
            <div class="plan-step-container" style="display: none;">
                <div class="plan-step-header">
                    <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"></path></svg>
                    <span>Current Step</span>
                </div>
                <div class="plan-step-content"></div>
            </div>
            <div class="agent-status">
                <div class="thinking-indicator">
                    <span></span><span></span><span></span>
                </div>
            </div>
            <div class="tool-activity" style="display: none;">
                <div class="tool-activity-header">
                    <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l-4 4-4-4 4-4"></path></svg>
                    <span class="font-semibold tool-header-text">Tool Call</span>
                </div>
                <div class="tool-activity-body">
                    <pre class="tool-params bg-gray-900 p-2 rounded text-xs"></pre>
                </div>
            </div>
            <div class="answer-content prose prose-invert max-w-none" style="display: none;"></div>
        </div>`;
    chatContainer.appendChild(botMessageWrapper);
            
    const thinkingHeader = botMessageWrapper.querySelector('.thinking-header');
    const thinkingContent = botMessageWrapper.querySelector('.thinking-content');
    thinkingHeader.addEventListener('click', () => {
        thinkingContent.style.display = thinkingContent.style.display === 'none' ? 'block' : 'none';
    });

    // --- MODIFICATION START ---
    if (shouldScroll) {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }
    // --- MODIFICATION END ---
    
    return botMessageWrapper;
}

function updateBotBubble(bubbleElement, responseContent, isFinal = false) {
    if (!bubbleElement) return;
    const agentStatus = bubbleElement.querySelector('.agent-status');
    const toolActivity = bubbleElement.querySelector('.tool-activity');
    const answerContent = bubbleElement.querySelector('.answer-content');
    
    agentStatus.style.display = 'none';
    agentStatus.classList.remove('text-red-400');
    toolActivity.style.display = 'none';
    answerContent.style.display = 'block';

    const finalConversational = responseContent
        .replace(/<think>[\s\S]*?<\/think>/g, '')
        .replace(/```json\s*([\s\S]*?)\s*```/g, '')
        .trim();
    answerContent.innerHTML = marked.parse(finalConversational);

    if (isFinal) {
        bubbleElement.querySelectorAll('pre code').forEach((block) => {
            hljs.highlightElement(block);
            const copyBtn = document.createElement('button');
            copyBtn.className = 'copy-btn';
            copyBtn.textContent = 'Copy';
            copyBtn.onclick = () => {
                navigator.clipboard.writeText(block.textContent);
                copyBtn.textContent = 'Copied!';
                setTimeout(() => copyBtn.textContent = 'Copy', 2000);
            };
            block.parentElement.appendChild(copyBtn);
        });
    }
}

function updateAgentStatus(bubbleElement, statusText, isError = false) {
    if (!bubbleElement) return;
    const agentStatus = bubbleElement.querySelector('.agent-status');
    const toolActivity = bubbleElement.querySelector('.tool-activity');
    const answerContent = bubbleElement.querySelector('.answer-content');
    
    agentStatus.innerHTML = statusText;
    agentStatus.style.display = 'block';
    toolActivity.style.display = 'none';
    answerContent.style.display = 'none';
    
    agentStatus.classList.toggle('text-red-400', isError);
}

function showToolCall(bubbleElement, toolName, toolParams) {
    if (!bubbleElement) return;
    const agentStatus = bubbleElement.querySelector('.agent-status');
    const toolActivity = bubbleElement.querySelector('.tool-activity');
    const answerContent = bubbleElement.querySelector('.answer-content');
    const toolHeaderEl = toolActivity.querySelector('.tool-header-text');
    const toolParamsEl = toolActivity.querySelector('.tool-params');

    agentStatus.style.display = 'none';
    agentStatus.classList.remove('text-red-400');
    answerContent.style.display = 'none';
    toolActivity.style.display = 'block';

    toolHeaderEl.textContent = `Action: ${toolName}`;
    toolParamsEl.textContent = JSON.stringify(toolParams, null, 2);
}

function addConversationToList(id, title) {
    const item = document.createElement('div');
    item.className = 'conversation-item item-hover group flex justify-between items-center p-2 rounded-md cursor-pointer hover:bg-gray-700';
    item.dataset.id = id;

    let buttons = `<button class="share-btn p-1 text-gray-400 hover:text-white" title="Share">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.684 13.342C8.886 12.938 9 12.482 9 12s-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6.002l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.368a3 3 0 105.367 2.684 3 3 0 00-5.367-2.684z"></path></svg>
                   </button>
                   <button class="delete-btn p-1 text-gray-400 hover:text-white" title="Delete">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                   </button>`;
    
    item.innerHTML = `<span class="truncate flex-1">${title}</span><div class="flex items-center">${buttons}</div>`;

    item.addEventListener('click', () => {
        if (item.dataset.id !== currentConversationId && !isAgentRunning) {
            loadConversation(item.dataset.id);
        }
    });
    
    item.querySelector('.share-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        openShareModal(item.dataset.id);
    });
    item.querySelector('.delete-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        confirmDeletion(item.dataset.id, 'conversation', 'conversation');
    });

    conversationList.prepend(item);
    
    document.querySelectorAll('.conversation-item').forEach(otherItem => {
        otherItem.classList.remove('active');
    });
    item.classList.add('active');
}

async function populateConversations() {
    try {
        const response = await fetch(`${window.location.origin}${API_BASE}/conversations`);
        const convos = await response.json();
        conversationList.innerHTML = '';
        convos.forEach(convo => {
            const item = document.createElement('div');
            const isActive = convo.id === currentConversationId;
            item.className = `conversation-item item-hover group flex justify-between items-center p-2 rounded-md cursor-pointer hover:bg-gray-700 ${isActive ? 'active' : ''}`;
            item.dataset.id = convo.id;

            let buttons = '';
            if (convo.role === 'owner') {
                buttons = `<button class="share-btn p-1 text-gray-400 hover:text-white" title="Share">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.684 13.342C8.886 12.938 9 12.482 9 12s-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6.002l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.368a3 3 0 105.367 2.684 3 3 0 00-5.367-2.684z"></path></svg>
                           </button>
                           <button class="delete-btn p-1 text-gray-400 hover:text-white" title="Delete">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                           </button>`;
            }
            item.innerHTML = `<span class="truncate flex-1">${convo.title}</span><div class="flex items-center">${buttons}</div>`;
            
            item.addEventListener('click', () => {
                if (!isActive && !isAgentRunning) loadConversation(convo.id);
            });

            if (convo.role === 'owner') {
                item.querySelector('.share-btn').addEventListener('click', (e) => {
                    e.stopPropagation();
                    openShareModal(convo.id);
                });
                item.querySelector('.delete-btn').addEventListener('click', (e) => {
                    e.stopPropagation();
                    confirmDeletion(convo.id, 'conversation', 'conversation');
                });
            }
            conversationList.appendChild(item);
        });
    } catch (error) {
        console.error("Failed to populate conversations:", error);
    }
}

async function openShareModal(conversationId) {
    shareModal.classList.remove('hidden');
    shareUserList.innerHTML = '<p>Loading users...</p>';
    try {
        const response = await fetch(`${window.location.origin}${API_BASE}/users`);
        const users = await response.json();
        if (users.length === 0) {
            shareUserList.innerHTML = '<p>No other users to share with.</p>';
            return;
        }
        shareUserList.innerHTML = '';
        users.forEach(user => {
            const userItem = document.createElement('div');
            userItem.className = 'p-2 hover:bg-gray-700 cursor-pointer rounded';
            userItem.textContent = user.username;
            userItem.addEventListener('click', async () => {
                try {
                    const shareResponse = await fetch(`${window.location.origin}${API_BASE}/conversation/${conversationId}/share`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ user_id: user.id }),
                    });
                    const data = await shareResponse.json();
                    if (shareResponse.ok) {
                        alert(`Conversation shared with ${user.username}`);
                        shareModal.classList.add('hidden');
                    } else {
                        throw new Error(data.message || 'Failed to share conversation');
                    }
                } catch (error) {
                    alert(`Error: ${error.message}`);
                }
            });
            shareUserList.appendChild(userItem);
        });
    } catch (error) {
        shareUserList.innerHTML = `<p class="text-red-400">Could not load users: ${error.message}</p>`;
    }
}

async function loadConversation(id) {
    try {
        // V2.2 Bug Fix: Ensure canvas is closed when switching conversations
        closeFileCanvas();

        const response = await fetch(`${window.location.origin}${API_BASE}/conversation/${id}`);
        const data = await response.json();
        currentConversationId = id;
        currentConversationRole = data.role;
        chatContainer.innerHTML = '';
        welcomeMessage.style.display = 'none';
        
        conversationHistory = data.messages || [];
        // Re-render history, filtering out tool responses for a cleaner view
        conversationHistory.forEach(msg => {
            if (msg.role === 'user') {
                // Do not show the user messages that are just tool responses
                if (!msg.content.startsWith('TOOL RESPONSE:')) {
                    appendMessage(msg.content, 'user', false);
                }
            } else if (msg.role === 'assistant') {
                // Do not show the intermediate assistant messages that are just tool calls
                if (!msg.content.includes('```json')) {
                    const botBubble = createBotMessageContainer(false);
                    updateBotBubble(botBubble, msg.content, true);
                }
            }
        });

        chatContainer.scrollTop = chatContainer.scrollHeight;
        await populateFileExplorer();
        await populateConversations();
    } catch (error) {
        console.error("Error loading conversation:", error);
    }
}

function startNewChat() {
    if (isAgentRunning) return;
    currentConversationId = null;
    currentConversationRole = 'owner';
    conversationHistory = [];
    chatContainer.innerHTML = '';
    welcomeMessage.style.display = 'flex';
    closeFileCanvas();
    populateFileExplorer();
    populateConversations();
}

function appendMessage(text, sender, animate = true) {
    // --- MODIFICATION START ---
    const shouldScroll = isScrolledToBottom(chatContainer);
    // --- MODIFICATION END ---

    const messageWrapper = document.createElement('div');
    let classes = `flex max-w-3xl w-full items-start self-${sender === 'user' ? 'end' : 'start'} mx-auto`;
    if (animate) {
        classes += ' newly-added';
    }
    messageWrapper.className = classes;

    if (sender === 'user') {
        messageWrapper.innerHTML = `
            <div class="flex-1 user-bubble">
                <div class="text-white max-w-none">${marked.parse(text)}</div>
            </div>
            <div class="w-8 h-8 flex-shrink-0 ml-2 text-blue-300">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-full h-full">
                  <path fill-rule="evenodd" d="M7.5 6a4.5 4.5 0 119 0 4.5 4.5 0 01-9 0zM3.751 20.105a8.25 8.25 0 0116.498 0 .75.75 0 01-.437.695A18.683 18.683 0 0112 22.5c-2.786 0-5.433-.608-7.812-1.7a.75.75 0 01-.437-.695z" clip-rule="evenodd" />
                </svg>
            </div>`;
    } 

    chatContainer.appendChild(messageWrapper);
    
    // --- MODIFICATION START ---
    if (shouldScroll) {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }
    // --- MODIFICATION END ---
}