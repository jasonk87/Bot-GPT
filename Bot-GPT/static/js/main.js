// main.js (Consolidated and with ALL UI Enhancements Restored)

// --- API Functions ---
const API_BASE = '/api';

async function checkAuth() {
    return await fetch(`${window.location.origin}/check_auth`);
}

async function handleAuth(username, password, isLogin) {
    const url = isLogin ? '/login' : '/register';
    return await fetch(`${window.location.origin}${url}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
    });
}

async function logout() {
    await fetch(`${window.location.origin}/logout`);
}

function startChatEventSource(params) {
    return new EventSource(`${API_BASE}/chat?${new URLSearchParams(params).toString()}`);
}

async function getModels() {
    return await fetch(`${API_BASE}/models`);
}

async function getConversations() {
    return await fetch(`${API_BASE}/conversations`);
}

async function getConversation(id) {
    return await fetch(`${API_BASE}/conversation/${id}`);
}

async function getWorkspaceFiles(conversationId) {
    return await fetch(`${API_BASE}/workspace/files/${conversationId}`);
}

async function getWorkspaceFileContent(path, conversationId) {
    const params = new URLSearchParams({ path, conversation_id: conversationId });
    return await fetch(`${API_BASE}/workspace/file?${params.toString()}`);
}

async function saveWorkspaceFile(path, content, conversationId) {
    return await fetch(`${API_BASE}/workspace/file`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            path: path,
            content: content,
            conversation_id: conversationId
        })
    });
}

async function deleteItem(itemType, id, path, conversationId) {
    let url, body;
    if (itemType === 'file') {
        url = `${API_BASE}/workspace/file`;
        body = { path: path, conversation_id: conversationId };
    } else {
        url = `${API_BASE}/conversation/${id}`;
        body = {};
    }
    return await fetch(url, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
}


async function getUserSettings() {
    return await fetch(`${API_BASE}/settings`);
}

async function saveUserSettings(model, persona) {
     return await fetch(`${API_BASE}/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model, persona }),
    });
}

async function getUsers() {
    return await fetch(`${API_BASE}/users`);
}

async function shareConversation(conversationId, userId) {
    return await fetch(`${API_BASE}/conversation/${conversationId}/share`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId }),
    });
}

async function uploadFiles(formData) {
    return await fetch(`${window.location.origin}/api/upload`, {
        method: 'POST',
        body: formData,
    });
}


// --- State Management ---
let conversationHistory = [];
let currentConversationId = null;
let currentConversationRole = null;
let userModel = null;
let editor = null;
let isAgentRunning = false;
let isCanvasMode = false;
let deleteResolver = null;
let eventSource = null;
let currentAgentBubble = null;

// --- DOM Element Store ---
const elements = {};

// --- Helper Functions ---
function kebabToCamel(s) {
    return s.replace(/-./g, x => x[1].toUpperCase());
}


// --- App Initialization ---
document.addEventListener('DOMContentLoaded', () => {
    // These are defined globally for the auth screen
    const authScreen = document.getElementById('auth-screen');
    const mainApp = document.getElementById('main-app');
    
    setupAuth();
    checkAuthAndInit(authScreen, mainApp);
});

async function checkAuthAndInit(authScreen, mainApp) {
    try {
        const response = await checkAuth();
        if (response.ok) {
            const user = await response.json();
            authScreen.style.display = 'none';
            mainApp.style.display = 'flex';
            await initializeApp(user.username);
        } else {
            authScreen.style.display = 'flex';
            mainApp.style.display = 'none';
        }
    } catch (error) {
        authScreen.style.display = 'flex';
        mainApp.style.display = 'none';
    }
}

function setupAuth() {
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
    
    const handleAuthFormSubmit = async (e) => {
        e.preventDefault();
        const isLogin = e.target.id === 'login-form';
        const username = document.getElementById(`${isLogin ? 'login' : 'register'}-username`).value;
        const password = document.getElementById(`${isLogin ? 'login' : 'register'}-password`).value;

        try {
            const response = await handleAuth(username, password, isLogin);
            const data = await response.json();
            if (response.ok) {
                authScreen.style.display = 'none';
                mainApp.style.display = 'flex';
                await initializeApp(data.username);
            } else {
                authError.textContent = data.message;
            }
        } catch (error) {
            authError.textContent = "An error occurred. Please try again.";
        }
    };

    loginForm.addEventListener('submit', handleAuthFormSubmit);
    registerForm.addEventListener('submit', handleAuthFormSubmit);
}

async function initializeApp(username) {
    // Inject Dynamic CSS - RESTORED & FIXED
    const style = document.createElement('style');
    style.textContent = `
        /* General Bubble Styles */
        .bot-bubble, .user-bubble {
            max-width: 100%; /* Prevent bubbles from exceeding parent width */
            overflow-x: hidden; /* Hide horizontal overflow */
        }

        .prose pre {
            white-space: pre-wrap;   /* Allows long lines of code to wrap */
            word-break: break-all;   /* Forces even unbroken strings (like tokens) to wrap */
        }

         /* --- THE DEFINITIVE LIST SPACING & FORMATTING FIX --- */

        /* Rule 1: Reset the List Containers (<ul>, <ol>) */
        /* This overrides the browser's user-agent stylesheet by removing all default margins */
        /* and setting a smaller, consistent padding for the indentation. */
        .bot-bubble .answer-content ul,
        .bot-bubble .answer-content ol {
            margin: 0 0 1em 0; /* Remove top/bottom margins, keep a bottom margin for spacing after the list */
            padding-left: 1.5em; /* A reasonable indent, much smaller than the browser's 40px default */
        }
        .bot-bubble .answer-content ul { list-style-type: disc; }
        .bot-bubble .answer-content ol { list-style-type: decimal; margin-top:1em;}
        .bot-bubble .answer-content h1,h2, h3,h4,h5,h6 { margin-bottom: 0.5em; }
        .bot-bubble .answer-content hr { margin-top: 2em; }


        /* Rule 2: Reset the Paragraphs INSIDE List Items (<li><p>...</p></li>) */
        .bot-bubble .answer-content li p {
            margin: 0; /* Remove all margins from the paragraph itself */
        }

        /* Rule 3: Add a small, consistent space between list items for readability. */
        .bot-bubble .answer-content li {
            padding-bottom: 0.4em; /* Use padding for spacing, which is more reliable than margin here */
        }

        /* Rule 4: Clean up spacing on the very last item to prevent extra space at the bubble's end. */
        .bot-bubble .answer-content li:last-child {
            padding-bottom: 0;
        }
        .bot-bubble .answer-content > *:last-child {
            margin-bottom: 0;
        }

        /* Agent Status Bar & Animations (Keep your existing styles here) */
        #agent-status-bar {
            display: none; padding: 8px; margin: 10px 20px;
            background-color: rgba(44, 62, 80, 0.5);
            border-radius: 8px; text-align: center;
            font-style: italic; color: #bdc3c7;
            transition: all 0.3s ease;
        }
        #agent-status-bar.active { display: block; }
        .dots span { animation: blink 1.4s infinite both; display: inline-block; }
        .dots span:nth-child(2) { animation-delay: 0.2s; }
        .dots span:nth-child(3) { animation-delay: 0.4s; }
        @keyframes blink { 0% { opacity: 0.2; } 20% { opacity: 1; } 100% { opacity: 0.2; } }
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
        .avatar-thinking { animation: pulse-avatar 1.5s infinite; }
        @keyframes pulse-avatar {
            0% { transform: scale(1); box-shadow: 0 0 0 0 rgba(52, 152, 219, 0.4); }
            70% { transform: scale(1.05); box-shadow: 0 0 5px 7px rgba(52, 152, 219, 0); }
            100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(52, 152, 219, 0); }
        }
    `;
    document.head.appendChild(style);

    // Cache all DOM elements
    const ids = [
        'chat-container', 'chat-input', 'send-button', 'model-select', 'file-explorer',
        'welcome-user', 'logout-btn', 'delete-modal', 'delete-modal-text', 'cancel-delete-btn', 'confirm-delete-btn',
        'conversation-list', 'new-chat-btn', 'chats-tab-btn', 'files-tab-btn', 'conversations-panel', 'files-panel',
        'side-panel', 'menu-btn', 'welcome-message', 'upload-btn', 'file-input', 'close-viewer-btn', 'overlay',
        'upload-modal', 'upload-form', 'cancel-upload-btn', 'drop-zone', 'file-list', 'upload-prompt',
        'settings-btn', 'settings-modal', 'settings-form', 'cancel-settings-btn', 'persona-select', 'current-model-display',
        'share-modal', 'cancel-share-btn', 'share-user-list', 'agent-status-bar', 'chat-input-container',
        'copy-file-btn', 'save-file-btn', 'chat-column', 'canvas-column', 'file-viewer',
        'canvas-toggle-btn', 'file-viewer-filename'
    ];
    
    ids.forEach(id => {
        const camelCaseId = kebabToCamel(id);
        elements[camelCaseId] = document.getElementById(id);
        if (!elements[camelCaseId]) {
            console.error(`CRITICAL ERROR: Element with ID '${id}' not found in the DOM.`);
        }
    });

    elements.welcomeUser.textContent = `Welcome, ${username}!`;
    attachEventListeners();
    
    await populateModels();
    populateConversations();
    populateFileExplorer();
    setAgentRunning(false);
}

function attachEventListeners() {
    elements.logoutBtn.addEventListener('click', async () => {
        await logout();
        window.location.reload();
    });
    elements.newChatBtn.addEventListener('click', startNewChat);
    elements.sendButton.addEventListener('click', sendMessage);
    elements.chatInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            sendMessage();
        }
    });
    elements.cancelDeleteBtn.addEventListener('click', () => deleteResolver(false));
    elements.confirmDeleteBtn.addEventListener('click', () => deleteResolver(true));
    elements.closeViewerBtn.addEventListener('click', closeFileCanvas);
    elements.chatsTabBtn.addEventListener('click', () => switchSidePanel('chats'));
    elements.filesTabBtn.addEventListener('click', () => switchSidePanel('files'));
    elements.menuBtn.addEventListener('click', () => {
        elements.sidePanel.classList.toggle('-translate-x-full');
        elements.overlay.classList.toggle('hidden');
    });
    elements.overlay.addEventListener('click', () => {
         elements.sidePanel.classList.add('-translate-x-full');
         elements.overlay.classList.add('hidden');
    });
    elements.uploadBtn.addEventListener('click', () => openModal(elements.uploadModal));
    elements.cancelUploadBtn.addEventListener('click', () => closeModal(elements.uploadModal));
    elements.dropZone.addEventListener('click', () => elements.fileInput.click());
    elements.dropZone.addEventListener('dragover', (e) => { e.preventDefault(); elements.dropZone.classList.add('drag-over'); });
    elements.dropZone.addEventListener('dragleave', () => elements.dropZone.classList.remove('drag-over'));
    elements.dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        elements.dropZone.classList.remove('drag-over');
        elements.fileInput.files = e.dataTransfer.files;
        updateFileList();
    });
    elements.fileInput.addEventListener('change', updateFileList);
    elements.uploadForm.addEventListener('submit', handleFileUpload);
    elements.settingsBtn.addEventListener('click', openSettingsModal);
    elements.cancelSettingsBtn.addEventListener('click', () => closeModal(elements.settingsModal));
    elements.settingsForm.addEventListener('submit', handleSaveSettings);
    elements.cancelShareBtn.addEventListener('click', () => closeModal(elements.shareModal));
    
    // --- THIS IS THE FIX for the canvas toggle button ---
    elements.canvasToggleBtn.addEventListener('click', () => {
        isCanvasMode = !isCanvasMode;
        elements.canvasToggleBtn.classList.toggle('bg-blue-600', isCanvasMode);
        elements.canvasToggleBtn.classList.toggle('text-white', isCanvasMode);
    });

    elements.copyFileBtn.addEventListener('click', () => {
        if (editor) {
            navigator.clipboard.writeText(editor.getValue());
            elements.copyFileBtn.textContent = 'Copied!';
            setTimeout(() => { elements.copyFileBtn.textContent = 'Copy'; }, 2000);
        }
    });
    elements.saveFileBtn.addEventListener('click', handleSaveFile);
    elements.chatInput.addEventListener('input', () => {
        elements.chatInput.style.height = 'auto';
        elements.chatInput.style.height = (elements.chatInput.scrollHeight) + 'px';
    });
}

// --- Core Application Logic ---

function setAgentRunning(isRunning) {
    isAgentRunning = isRunning;
    elements.chatInput.disabled = isRunning;
    elements.sendButton.disabled = isRunning;

    if (isRunning) {
        elements.sendButton.classList.add('bg-gray-500', 'cursor-not-allowed');
        elements.sendButton.classList.remove('bg-blue-600', 'hover:bg-blue-700');
        elements.sendButton.innerHTML = `<svg class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>`;
        
        elements.agentStatusBar.innerHTML = `Agent is running<span class="dots"><span>.</span><span>.</span><span>.</span></span>`;
        elements.agentStatusBar.classList.add('active');
        elements.chatInputContainer.classList.add('agent-active-glow');
        if (currentAgentBubble) {
            currentAgentBubble.querySelector('.w-8.h-8').classList.add('avatar-thinking');
        }
    } else {
        elements.sendButton.classList.remove('bg-gray-500', 'cursor-not-allowed');
        elements.sendButton.classList.add('bg-blue-600', 'hover:bg-blue-700');
        elements.sendButton.innerHTML = `<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14M12 5l7 7-7 7"></path></svg>`;
        
        elements.agentStatusBar.classList.remove('active');
        elements.chatInputContainer.classList.remove('agent-active-glow');
        document.querySelectorAll('.avatar-thinking').forEach(el => el.classList.remove('avatar-thinking'));

        if (eventSource) {
            eventSource.close();
        }
    }
}

function sendMessage() {
    const text = elements.chatInput.value.trim();
    if (!text || isAgentRunning) return;

    setAgentRunning(true);
    elements.welcomeMessage.style.display = 'none';
    const userMessage = { role: 'user', content: text };
    appendMessage(text, 'user');
    conversationHistory.push(userMessage);

    elements.chatInput.value = '';
    elements.chatInput.style.height = 'auto';

    // --- State variables from the fix, correctly placed and reset for each message ---
    currentAgentBubble = createBotMessageContainer();
    let thinkContent = "";
    let finalAnswerContent = "";
    let inThinkBlock = true; // This is the key state tracker for streaming

    const isNewConversation = !currentConversationId;

    const params = {
        message: JSON.stringify(userMessage),
        model: userModel,
        conversation_id: currentConversationId || '',
        canvas_mode: isCanvasMode ? 'true' : 'false' // Kept from your version
    };

    eventSource = startChatEventSource(params);
    
    // --- Fallback handling state from your version ---
    let fullResponseContentForFallback = "";
    let finalAnswerSent = false;

    eventSource.onmessage = function(event) {
        try {
            const data = JSON.parse(event.data);
            
            // --- KEEPS YOUR ROBUST FALLBACK LOGIC ---
            // This handles cases where the stream ends unexpectedly.
            if (data.done === true && !finalAnswerSent) {
                const finalConversational = fullResponseContentForFallback
                    .replace(/<think>[\s\S]*?<\/think>/g, '')
                    .replace(/```json\s*\{[\s\S]*?\}\s*```/g, '')
                    .trim();
                    
                if (finalConversational) {
                    updateBotBubble(currentAgentBubble, finalConversational, true);
                    conversationHistory.push({ role: 'assistant', content: finalConversational });
                } else {
                    currentAgentBubble.remove();
                }
                setAgentRunning(false);
                eventSource.close();
                populateConversations();
                return;
            }

            // Also accumulate for the fallback
            if(data.content) {
                fullResponseContentForFallback += data.content;
            }


            switch(data.type) {
                case 'conversation_id':
                    if (isNewConversation) {
                        currentConversationId = data.id;
                        addConversationToListDOM(data.id, "New Chat", 'owner');
                    }
                    break;
                case 'open_canvas':
                    if (isCanvasMode) openFileCanvas(data.filename);
                    populateFileExplorer();
                    break;

                // --- THIS IS THE NEW, CORRECTED STREAMING LOGIC ---
                case 'assistant_chunk':
                    if (inThinkBlock) {
                        thinkContent += data.content;
                        const thinkingContainer = currentAgentBubble.querySelector('.thinking-process-container');
                        thinkingContainer.style.display = 'block';
                        const thinkingContentEl = thinkingContainer.querySelector('.thinking-content');

                        const thinkEndMatch = thinkContent.indexOf('</think>');
                        if (thinkEndMatch !== -1) {
                            // The '<think>' block has just finished streaming.
                            inThinkBlock = false;
                            const cleanThinkContent = thinkContent.substring(thinkContent.indexOf('<think>') + 7, thinkEndMatch);
                            thinkingContentEl.innerHTML = marked.parse(cleanThinkContent);

                            // Anything after the tag is the start of the real answer.
                            finalAnswerContent = thinkContent.substring(thinkEndMatch + 8);
                            updateBotBubble(currentAgentBubble, finalAnswerContent);
                        } else {
                            // Still inside the '<think>' block, stream the partial thought.
                            const partialThink = thinkContent.replace('<think>', '');
                            thinkingContentEl.innerHTML = marked.parse(partialThink);
                        }
                    } else {
                        // We are now in the answer phase, stream directly to the answer block.
                        finalAnswerContent += data.content;
                        updateBotBubble(currentAgentBubble, finalAnswerContent);
                    }
                    break;
                // --- END OF THE NEW LOGIC ---

                case 'tool_call':
                    showToolCall(currentAgentBubble, data.name, data.params);
                    if (data.name === 'ask_coder') {
                        const iconContainer = currentAgentBubble.querySelector('.bubble-icon-container');
                        if (iconContainer) {
                            iconContainer.innerHTML = document.getElementById('coder-icon').outerHTML;
                        }
                        const coderActivity = currentAgentBubble.querySelector('.coder-activity');
                        if (coderActivity) {
                            coderActivity.style.display = 'block';
                        }
                    }
                    break;
                case 'coder_thought':
                case 'coder_status':
                case 'coder_tool_call':
                case 'coder_tool_result':
                    if (currentAgentBubble) {
                        const streamContainer = currentAgentBubble.querySelector('.coder-activity-stream');
                        if (streamContainer) {
                            const eventElement = document.createElement('div');
                            eventElement.className = 'coder-thought p-2 border-b border-gray-700'; // Using same style for all for now

                            let content = '';
                            if(data.type === 'coder_thought') {
                                content = `<strong>Thought:</strong> ${data.content}`;
                            } else if (data.type === 'coder_status') {
                                content = `<em>Status: ${data.status}</em>`;
                            } else if (data.type === 'coder_tool_call') {
                                content = `<strong>Tool Call:</strong> ${data.name}<pre class="bg-gray-900 p-1 rounded mt-1 text-xs">${JSON.stringify(data.params, null, 2)}</pre>`;
                            } else if (data.type === 'coder_tool_result') {
                                let result_str = data.result;
                                if (typeof result_str !== 'string') {
                                    result_str = JSON.stringify(result_str, null, 2);
                                }
                                content = `<strong>Tool Result:</strong><pre class="bg-gray-900 p-1 rounded mt-1 text-xs">${result_str}</pre>`;
                            }
                            eventElement.innerHTML = content;
                            streamContainer.appendChild(eventElement);
                            streamContainer.scrollTop = streamContainer.scrollHeight;
                        }
                    }
                    break;
                case 'tool_result':
                    console.log("Tool result received, agent is processing...");
                     if (currentAgentBubble) {
                        const iconContainer = currentAgentBubble.querySelector('.bubble-icon-container');
                        if (iconContainer) {
                            iconContainer.innerHTML = document.getElementById('assistant-icon').outerHTML;
                        }
                    }
                    break;
                case 'final_answer':
                    finalAnswerSent = true; // Signal that the final answer was received
                    conversationHistory.push({ role: 'assistant', content: data.content });
                    updateBotBubble(currentAgentBubble, data.content, true); // Final render
                    setAgentRunning(false);
                    eventSource.close();
                    populateConversations();
                    break;
                case 'agent_error':
                    updateAgentStatus(currentAgentBubble, `An error occurred: ${data.error}`, true);
                    setAgentRunning(false);
                    eventSource.close();
                    break;
                default:
                    // This handles any unexpected event types without crashing.
                    break;
            }
        } catch (e) {
            console.error("Error parsing SSE event data:", event.data, e);
        }
    };

    eventSource.onerror = function(err) {
        console.error("EventSource failed:", err);
        if (currentAgentBubble) {
            updateAgentStatus(currentAgentBubble, "Connection to server lost.", true);
        }
        setAgentRunning(false);
        if (eventSource) {
            eventSource.close();
        }
    };
}

function startNewChat() {
    if (isAgentRunning) return;
    currentConversationId = null;
    currentConversationRole = 'owner';
    conversationHistory = [];
    elements.chatContainer.innerHTML = '';
    elements.welcomeMessage.style.display = 'flex';
    closeFileCanvas();
    populateFileExplorer();
    populateConversations();
}

async function loadConversation(id) {
    if (id === currentConversationId || isAgentRunning) return;
    elements.chatContainer.innerHTML = `
        <div id="loading-spinner" class="flex justify-center items-center h-full">
            <div class="animate-spin rounded-full h-32 w-32 border-t-2 border-b-2 border-blue-500"></div>
        </div>
    `;
    try {
        const response = await getConversation(id);
        const data = await response.json();
        currentConversationId = id;
        currentConversationRole = data.role;
        elements.chatContainer.innerHTML = '';
        elements.welcomeMessage.style.display = 'none';

        conversationHistory = data.messages || [];
        conversationHistory.forEach(msg => {
            if (msg.role === 'user') {
                // Filter out tool responses from the user side for a cleaner history
                if (!msg.content.startsWith('TOOL RESPONSE:')) {
                    appendMessage(msg.content, 'user', false);
                }
            } else if (msg.role === 'assistant') {
                // Clean the assistant's message to see if any conversational text remains
                const conversationalContent = msg.content
                    .replace(/<think>[\s\S]*?<\/think>/g, '')
                    .replace(/```json\s*\{[\s\S]*?\}\s*```/g, '') // This is the key line
                    .trim();

                // ONLY create a bubble if there's actual text left to display
                if (conversationalContent) {
                    const botBubble = createBotMessageContainer(false);
                    // Pass only the clean content to the update function
                    updateBotBubble(botBubble, conversationalContent, true);
                }
            }
        });

        elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
        await populateFileExplorer();
        await populateConversations();
    } catch (error) {
        console.error("Error loading conversation:", error);
        elements.chatContainer.innerHTML = '<p class="text-red-400 p-4">Error loading conversation.</p>';
    }
}

// --- UI Rendering Functions ---

function appendMessage(text, sender, animate = true) {
    const messageWrapper = document.createElement('div');
    let classes = `flex max-w-3xl w-full items-start self-${sender === 'user' ? 'end' : 'start'} mx-auto`;
    if (animate) {
        classes += ' newly-added';
    }
    messageWrapper.className = classes;

    if (sender === 'user') {
        messageWrapper.innerHTML = `
            <div class="flex-1 user-bubble">
                <div class="prose prose-invert max-w-none text-white">${marked.parse(text)}</div>
            </div>
            <div class="w-8 h-8 flex-shrink-0 ml-2 text-blue-300">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-full h-full">
                  <path fill-rule="evenodd" d="M7.5 6a4.5 4.5 0 119 0 4.5 4.5 0 01-9 0zM3.751 20.105a8.25 8.25 0 0116.498 0 .75.75 0 01-.437.695A18.683 18.683 0 0112 22.5c-2.786 0-5.433-.608-7.812-1.7a.75.75 0 01-.437-.695z" clip-rule="evenodd" />
                </svg>
            </div>`;
    }

    elements.chatContainer.appendChild(messageWrapper);
    elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
}

function createBotMessageContainer(animate = true) {
    const botMessageWrapper = document.createElement('div');
    botMessageWrapper.className = 'flex max-w-3xl w-full items-start self-start mx-auto';
    if (animate) {
        setTimeout(() => {
            botMessageWrapper.classList.add('newly-added');
        }, 100);
    }
    
    botMessageWrapper.innerHTML = `
        <div class="w-8 h-8 flex-shrink-0 mr-2 text-gray-400 bubble-icon-container">
            ${document.getElementById('assistant-icon').outerHTML}
        </div>
        <div class="flex-1 bot-bubble">
            <div class="thinking-process-container" style="display: none;">
                <div class="thinking-header">
                    <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 9l4-4 4 4m0 6l-4 4-4-4"></path></svg>
                    <span>Thinking...</span>
                </div>
                <div class="thinking-content prose prose-invert max-w-none"></div>
            </div>
            <div class="coder-activity" style="display: none;">
                <div class="coder-activity-header">
                    <svg class="w-5 h-5 mr-2" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">
                        <path fill-rule="evenodd" d="M10.5 4.5a.75.75 0 0 0 0 1.5h3a.75.75 0 0 0 0-1.5h-3ZM10.5 18a.75.75 0 0 0 0 1.5h3a.75.75 0 0 0 0-1.5h-3Z" clip-rule="evenodd" />
                        <path fill-rule="evenodd" d="M8.663 3.603a.75.75 0 0 0-1.06 1.06l-4.5 4.5a.75.75 0 0 0 0 1.06l4.5 4.5a.75.75 0 0 0 1.06-1.06L4.72 10l3.943-3.943a.75.75 0 0 0-1.06-1.06Zm6.674 0a.75.75 0 0 1 1.06 1.06l4.5 4.5a.75.75 0 0 1 0 1.06l-4.5 4.5a.75.75 0 1 1-1.06-1.06L19.28 10l-3.943-3.943a.75.75 0 0 1 1.06-1.06Z" clip-rule="evenodd" />
                    </svg>
                    <span>Coder Agent Activity</span>
                </div>
                <div class="coder-activity-stream scrollable-content"></div>
            </div>
            <div class="plan-step-container" style="display: none;">
                <div class="plan-step-header">
                     <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"></path></svg>
                    <span>Current Step</span>
                </div>
                <div class="plan-step-content"></div>
            </div>
            <div class="agent-status"><div class="thinking-indicator"><span></span><span></span><span></span></div></div>
            <div class="tool-activity" style="display: none;">
                <div class="tool-activity-header">
                    <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l-4 4-4-4 4-4"></path></svg>
                    <span class="font-semibold tool-header-text">Tool Call</span>
                </div>
                <div class="tool-activity-body"><pre class="tool-params bg-gray-900 p-2 rounded text-xs"></pre></div>
            </div>
            <div class="answer-content prose prose-invert max-w-none" style="display: none;"></div>
        </div>`;
    
    elements.chatContainer.appendChild(botMessageWrapper);
            
    const thinkingHeader = botMessageWrapper.querySelector('.thinking-header');
    const thinkingContent = botMessageWrapper.querySelector('.thinking-content');
    thinkingHeader.addEventListener('click', () => {
        thinkingContent.style.display = thinkingContent.style.display === 'none' ? 'block' : 'none';
    });

    elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
    return botMessageWrapper;
}

/**
 * A centralized controller for the bot bubble's visual state.
 * Ensures only one component (status, tool, or answer) is visible at a time.
 * @param {HTMLElement} bubbleElement The parent .bot-bubble element.
 * @param {'status'|'tool_call'|'final_answer'} state The desired state.
 */
function setBubbleState(bubbleElement, state) {
    if (!bubbleElement) return;

    const agentStatus = bubbleElement.querySelector('.agent-status');
    const toolActivity = bubbleElement.querySelector('.tool-activity');
    const answerContent = bubbleElement.querySelector('.answer-content');
    const thinkingContainer = bubbleElement.querySelector('.thinking-process-container');


    // Hide all components by default
    if (agentStatus) agentStatus.style.display = 'none';
    if (toolActivity) toolActivity.style.display = 'none';
    if (answerContent) answerContent.style.display = 'none';
    // Keep the thinking container visible if it has content, but hide others
    if (state !== 'status' && agentStatus) agentStatus.style.display = 'none';


    // Show the correct component based on the state
    if (state === 'status' && agentStatus) {
        agentStatus.style.display = 'block';
    } else if (state === 'tool_call' && toolActivity) {
        toolActivity.style.display = 'block';
    } else if (state === 'final_answer' && answerContent) {
        // When showing the final answer, hide the thinking process unless manually expanded
        if(thinkingContainer) thinkingContainer.style.display = 'none';
        answerContent.style.display = 'block';
    }
}

function updateBotBubble(bubbleElement, responseContent, isFinal = false) {
    if (!bubbleElement) return;
    setBubbleState(bubbleElement, 'final_answer');

    const answerContent = bubbleElement.querySelector('.answer-content');

    // This regex now removes both <think> blocks and json tool call blocks
    const finalConversational = responseContent
        .replace(/<think>[\s\S]*?<\/think>/g, '')
        .replace(/```json\s*\{[\s\S]*?\}\s*```/g, '') // Add this line
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
    setBubbleState(bubbleElement, 'status'); // Use the state manager

    const agentStatus = bubbleElement.querySelector('.agent-status');
    agentStatus.innerHTML = statusText;
    agentStatus.classList.toggle('text-red-400', isError);
}

function showToolCall(bubbleElement, toolName, toolParams) {
    if (!bubbleElement) return;
    setBubbleState(bubbleElement, 'tool_call'); // Use the state manager

    const toolHeaderEl = bubbleElement.querySelector('.tool-header-text');
    const toolParamsEl = bubbleElement.querySelector('.tool-params');
    
    toolHeaderEl.textContent = `Action: ${toolName}`;
    toolParamsEl.textContent = JSON.stringify(toolParams, null, 2);
}

async function populateConversations() {
    try {
        const response = await getConversations();
        const convos = await response.json();
        elements.conversationList.innerHTML = '';
        convos.forEach(convo => {
            addConversationToListDOM(convo.id, convo.title, convo.role);
        });
        document.querySelectorAll('.conversation-item').forEach(item => {
            item.classList.remove('active');
        });
        const activeItem = document.querySelector(`.conversation-item[data-id="${currentConversationId}"]`);
        if (activeItem) {
            activeItem.classList.add('active');
        }
    } catch (error) {
        console.error("Failed to populate conversations:", error);
    }
}

function addConversationToListDOM(id, title, role) {
    const item = document.createElement('div');
    item.className = 'conversation-item item-hover group flex justify-between items-center p-2 rounded-md cursor-pointer';
    item.dataset.id = id;

    let buttons = '';
    if (role === 'owner') {
        buttons = `<button class="share-btn p-1 text-gray-400 hover:text-white" title="Share"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.684 13.342C8.886 12.938 9 12.482 9 12s-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6.002l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.368a3 3 0 105.367 2.684 3 3 0 00-5.367-2.684z"></path></svg></button>
                   <button class="delete-btn p-1 text-gray-400 hover:text-white" title="Delete"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg></button>`;
    }
    
    item.innerHTML = `<span class="truncate flex-1">${title}</span><div class="flex items-center">${buttons}</div>`;

    item.addEventListener('click', () => {
        if (item.dataset.id !== currentConversationId) loadConversation(item.dataset.id);
    });
    
    if (role === 'owner') {
        item.querySelector('.share-btn').addEventListener('click', (e) => { e.stopPropagation(); openShareModal(id); });
        item.querySelector('.delete-btn').addEventListener('click', (e) => { e.stopPropagation(); confirmDeletion(id, 'conversation'); });
    }
    elements.conversationList.prepend(item);
}

async function populateFileExplorer() {
    if (!currentConversationId) {
        elements.fileExplorer.innerHTML = '<p class="text-gray-400">No active conversation.</p>';
        return;
    }
    try {
        const response = await getWorkspaceFiles(currentConversationId);
        const files = await response.json();
        elements.fileExplorer.innerHTML = buildFileTree(files, currentConversationRole);
        attachFileEventListeners();
    } catch (error) {
        console.error("Failed to populate file explorer:", error);
        elements.fileExplorer.innerHTML = '<p class="text-red-400">Could not load files.</p>';
    }
}

function buildFileTree(nodes, role, pathPrefix = '') {
    if (!nodes || nodes.length === 0) return '';
    let html = '<ul class="space-y-1">';
    nodes.forEach(node => {
        const fullPath = pathPrefix ? `${pathPrefix}/${node.name}` : node.name;
        const isDir = node.type === 'directory';
        const fileIcon = '&#128196;'; // File icon
        const dirIcon = '&#128193;'; // Directory icon

        let actionButtons = '';
        if (role === 'owner') {
            actionButtons += `<button class="delete-btn text-red-500 hover:text-red-400 font-bold ml-2 flex-shrink-0" title="Delete">&times;</button>`;
        }

        // Add a download button for files
        if (!isDir) {
            actionButtons += `<button class="download-btn p-1 text-gray-400 hover:text-white flex-shrink-0 ml-1" title="Download">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path></svg>
                              </button>`;
        }

        html += `<li class="file-item item-hover flex items-center justify-between group" data-path="${node.path}" data-type="${node.type}">
                    <span class="flex-1 cursor-pointer hover:text-blue-400 truncate">${isDir ? dirIcon : fileIcon} ${node.name}</span>
                    <div class="flex items-center">${actionButtons}</div>
                 </li>`;

        if (isDir && node.children) {
            html += `<li class="pl-4">${buildFileTree(node.children, role, fullPath)}</li>`;
        }
    });
    html += '</ul>';
    return html;
}

function attachFileEventListeners() {
    document.querySelectorAll('.file-item').forEach(item => {
        const path = item.dataset.path;
        const type = item.dataset.type;

        // Click on file name opens it in canvas
        item.querySelector('span').addEventListener('click', () => {
            if (type === 'file') openFileCanvas(path);
        });

        // Delete button logic
        const deleteBtn = item.querySelector('.delete-btn');
        if (deleteBtn) {
            deleteBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                confirmDeletion(path, 'file');
            });
        }

        const downloadBtn = item.querySelector('.download-btn');
        if (downloadBtn) {
            downloadBtn.addEventListener('click', (e) => {
                e.stopPropagation(); // Don't open the file in the canvas
                // Construct the download URL
                const downloadUrl = `${API_BASE}/workspace/download?path=${encodeURIComponent(path)}&conversation_id=${currentConversationId}`;
                // Trigger the download
                window.location.href = downloadUrl;
            });
        }
    });
}

async function populateModels() {
    try {
        const response = await getModels();
        const data = await response.json();
        if (data.error) throw new Error(data.error);
        elements.modelSelect.innerHTML = '';
        data.forEach(model => {
            const option = document.createElement('option');
            option.value = model.name;
            option.textContent = model.name;
            elements.modelSelect.appendChild(option);
        });
        await loadUserSettings();
    } catch (error) {
        console.error("CRITICAL FAILURE in populateModels:", error);
    }
}

async function loadUserSettings() {
    try {
        const response = await getUserSettings();
        const settings = await response.json();
        userModel = settings.model || (elements.modelSelect.options.length > 0 ? elements.modelSelect.options[0].value : '');
        if (userModel) elements.modelSelect.value = userModel;
        elements.currentModelDisplay.textContent = userModel;
    } catch (error) {
        console.error("Failed to load user settings:", error);
    }
}

// --- UI Helper Functions ---

function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    // Animate in
    setTimeout(() => {
        toast.classList.add('show');
    }, 100);

    // Animate out and remove
    setTimeout(() => {
        toast.classList.remove('show');
        toast.addEventListener('transitionend', () => {
            toast.remove();
        });
    }, 3000);
}

function openModal(modalElement) {
    modalElement.classList.remove('hidden');
    setTimeout(() => modalElement.style.opacity = 1, 10);
}

function closeModal(modalElement) {
    modalElement.style.opacity = 0;
    setTimeout(() => modalElement.classList.add('hidden'), 300);
}


// ... the rest of the helper and modal functions ...

async function openFileCanvas(path) {
    try {
        const response = await getWorkspaceFileContent(path, currentConversationId);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);

        elements.fileViewerFilename.textContent = path;
        elements.canvasColumn.classList.remove('hidden');
        elements.canvasColumn.classList.add('flex');
        elements.chatColumn.classList.remove('w-full');
        elements.chatColumn.classList.add('md:w-1/2');
        if (window.innerWidth < 768) {
            elements.chatColumn.classList.add('hidden');
        }

        let mode = 'text/plain';
        if (path.endsWith('.py')) mode = 'python';
        if (path.endsWith('.js')) mode = 'javascript';
        if (path.endsWith('.html')) mode = 'htmlmixed';
        if (path.endsWith('.css')) mode = 'css';

        initializeEditor(data.content, mode);
    } catch (error) {
        showToast(`Error opening file: ${error.message}`, 'error');
    }
}

function initializeEditor(content, mode) {
    elements.fileViewer.innerHTML = '';
    editor = CodeMirror(elements.fileViewer, {
        value: content,
        mode: mode,
        theme: 'dracula',
        lineNumbers: true,
        readOnly: currentConversationRole !== 'owner'
    });
}

function closeFileCanvas() {
    elements.canvasColumn.classList.add('hidden');
    elements.canvasColumn.classList.remove('flex');
    elements.chatColumn.classList.remove('md:w-1/2', 'hidden');
    elements.chatColumn.classList.add('w-full');
}

async function confirmDeletion(idOrPath, itemType) {
    elements.deleteModalText.textContent = `Are you sure you want to delete this ${itemType}: ${idOrPath}?`;
    openModal(elements.deleteModal);
    const confirmed = await new Promise(resolve => { deleteResolver = resolve; });

    if (confirmed) {
        try {
            const response = await deleteItem(itemType, idOrPath, idOrPath, currentConversationId);
            if (!response.ok) throw new Error(await response.text());

            if (itemType === 'file') {
                await populateFileExplorer();
            } else {
                await populateConversations();
                if (idOrPath === currentConversationId) {
                    startNewChat();
                }
            }
        } catch (error) {
            console.error(`Failed to delete ${idOrPath}:`, error);
            showToast(`Error deleting ${itemType}: ${error.message}`, 'error');
        }
    }
    closeModal(elements.deleteModal);
}

async function handleFileUpload(event) {
    event.preventDefault();
    if (elements.fileInput.files.length === 0) return showToast('Please select files.', 'error');

    const formData = new FormData();
    formData.append('prompt', elements.uploadPrompt.value);
    formData.append('conversation_id', currentConversationId || '');
    for (let file of elements.fileInput.files) {
        formData.append('files[]', file);
    }

    try {
        const response = await uploadFiles(formData);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);

        if (!currentConversationId) {
            currentConversationId = data.conversation_id;
            conversationHistory = [];
        }
        await populateFileExplorer();
        closeModal(elements.uploadModal);
        elements.uploadForm.reset();
        updateFileList();
        elements.chatInput.value = data.message;
        sendMessage();
    } catch (error) {
        showToast(`Error uploading file: ${error.message}`, 'error');
    }
}

function updateFileList() {
    elements.fileList.innerHTML = elements.fileInput.files.length > 0
        ? `${elements.fileInput.files.length} file(s) selected.`
        : '';
}

async function openSettingsModal() {
    openModal(elements.settingsModal);
    try {
        const response = await getUserSettings();
        const settings = await response.json();

        elements.personaSelect.innerHTML = '';
        for (const [key, name] of Object.entries(settings.available_personas)) {
            const option = document.createElement('option');
            option.value = key;
            option.textContent = name;
            elements.personaSelect.appendChild(option);
        }

        if (settings.model) elements.modelSelect.value = settings.model;
        if (settings.persona) elements.personaSelect.value = settings.persona;

    } catch (error) {
        console.error("Failed to load user settings:", error);
    }
}

async function handleSaveSettings(e) {
    e.preventDefault();
    const newModel = elements.modelSelect.value;
    const newPersona = elements.personaSelect.value;
    try {
        const response = await saveUserSettings(newModel, newPersona);
        if (!response.ok) throw new Error('Failed to save settings');
        userModel = newModel;
        elements.currentModelDisplay.textContent = userModel;
        closeModal(elements.settingsModal);
    } catch (error) {
        showToast(`Error saving settings: ${error.message}`, 'error');
    }
}

async function handleSaveFile() {
    if (!editor) return;
    const path = elements.fileViewerFilename.textContent;
    const content = editor.getValue();
    try {
        const response = await saveWorkspaceFile(path, content, currentConversationId);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        elements.saveFileBtn.classList.add('pulse-once');
        showToast('File saved successfully!');
        setTimeout(() => {
            elements.saveFileBtn.classList.remove('pulse-once');
        }, 1000);
    } catch (error) {
        showToast(`Error saving file: ${error.message}`, 'error');
    }
}

async function openShareModal(conversationId) {
    openModal(elements.shareModal);
    elements.shareUserList.innerHTML = '<p>Loading users...</p>';
    try {
        const response = await getUsers();
        const users = await response.json();
        if (users.length === 0) {
            elements.shareUserList.innerHTML = '<p>No other users to share with.</p>';
            return;
        }
        elements.shareUserList.innerHTML = '';
        users.forEach(user => {
            const userItem = document.createElement('div');
            userItem.className = 'p-2 hover:bg-gray-700 cursor-pointer rounded';
            userItem.textContent = user.username;
            userItem.addEventListener('click', async () => {
                try {
                    const shareResponse = await shareConversation(conversationId, user.id);
                    const data = await shareResponse.json();
                    if (shareResponse.ok) {
                        showToast(`Conversation shared with ${user.username}`);
                        closeModal(elements.shareModal);
                    } else {
                        throw new Error(data.message || 'Failed to share');
                    }
                } catch (error) {
                    showToast(`Error: ${error.message}`, 'error');
                }
            });
            elements.shareUserList.appendChild(userItem);
        });
    } catch (error) {
        elements.shareUserList.innerHTML = `<p class="text-red-400">Could not load users: ${error.message}</p>`;
    }
}

function switchSidePanel(tab) {
    if (tab === 'chats') {
        elements.conversationsPanel.style.display = 'flex';
        elements.filesPanel.style.display = 'none';
        elements.chatsTabBtn.classList.add('active');
        elements.filesTabBtn.classList.remove('active');
    } else {
        elements.conversationsPanel.style.display = 'none';
        elements.filesPanel.style.display = 'flex';
        elements.chatsTabBtn.classList.remove('active');
        elements.filesTabBtn.classList.add('active');
    }
}