// Global scope for elements that are always present
const authScreen = document.getElementById('auth-screen');
const mainApp = document.getElementById('main-app');
const loginForm = document.getElementById('login-form');
const registerForm = document.getElementById('register-form');
const authTabs = document.querySelectorAll('.auth-tab-btn');
const authError = document.getElementById('auth-error');
const lastUserRow = document.getElementById('last-user-row');
const continueLastUserBtn = document.getElementById('continue-last-user-btn');
const lastUserName = document.getElementById('last-user-name');

// App-specific elements, to be initialized after login
let chatContainer, chatInput, sendButton, modelSelect, fileExplorer,
    welcomeUser, logoutBtn, deleteModal, deleteModalText, cancelDeleteBtn, confirmDeleteBtn,
    conversationList, newChatBtn, chatsTabBtn, filesTabBtn, conversationsPanel, filesPanel,
    sidePanel, menuBtn, welcomeMessage, uploadBtn, fileInput, fileViewerContainer, closeViewerBtn, overlay,
    uploadModal, uploadForm, cancelUploadBtn, dropZone, fileList, uploadPrompt,
    settingsBtn, settingsModal, settingsForm, cancelSettingsBtn, personaSelect, currentModelDisplay,
    shareModal, cancelShareBtn, shareUserList,
    copyFileBtn, saveFileBtn, canvasToggleBtn,
    participantList,
    summarizeBtn, summaryModal, summaryContent, closeSummaryBtn,
    agentModeToggle, toolsDropdownBtn, toolsDropdownMenu,
    attachImageBtn, imageInput, imagePreviewContainer,
    planToggleBtn, planPanel, planContent, planActions, approvePlanBtn, rejectPlanBtn;

const API_BASE = '/api';
let conversationHistory = [];
let currentConversationId = null;
let currentConversationRole = null;
let deleteResolver = null;
let userModel = null;
let currentUsername = null;
let editor = null;
let socket = null;
let debounceTimer = null;

// --- Agent State ---
let isAgentRunning = false;
let stopBtnListener = null;
let isCanvasMode = false;
let currentAgentBubble = null;
let fullAgentResponse = "";
let currentResponseContent = "";
let openTabs = [];
let activeTabIndex = -1;
let conversationRunStates = {};
let pendingNewConversationRun = null;

function getCurrentConversationStorageKey() {
    return currentUsername ? `botgpt_current_conversation_id_${currentUsername}` : 'botgpt_current_conversation_id';
}

function getTabsStorageKey(conversationId) {
    return currentUsername ? `botgpt_tabs_${currentUsername}_${conversationId}` : `botgpt_tabs_${conversationId}`;
}

function saveCurrentConversationId(conversationId) {
    localStorage.setItem(getCurrentConversationStorageKey(), conversationId);
}

function clearCurrentConversationId() {
    localStorage.removeItem(getCurrentConversationStorageKey());
}

function getSavedCurrentConversationId() {
    return localStorage.getItem(getCurrentConversationStorageKey());
}

function clearConversationSessionState(conversationId) {
    if (!conversationId) return;
    localStorage.removeItem(getTabsStorageKey(conversationId));
    clearConversationRunState(conversationId);
    if (currentConversationId === conversationId) {
        currentConversationId = null;
        currentConversationRole = 'owner';
        conversationHistory = [];
        currentAgentBubble = null;
        currentResponseContent = '';
        setAgentRunning(false);
        clearCurrentConversationId();
    }
}

function switchAuthTab(tabName) {
    authTabs.forEach(tab => {
        const isActive = tab.dataset.tab === tabName;
        tab.classList.toggle('border-blue-500', isActive);
        tab.classList.toggle('text-white', isActive);
        tab.classList.toggle('text-gray-400', !isActive);
    });

    if (tabName === 'login') {
        loginForm.classList.remove('hidden');
        registerForm.classList.add('hidden');
    } else {
        loginForm.classList.add('hidden');
        registerForm.classList.remove('hidden');
    }
    authError.textContent = '';
}

function updateLastUserUI(username) {
    if (username) {
        lastUserName.textContent = username;
        lastUserRow.classList.remove('hidden');
    } else {
        lastUserName.textContent = '';
        lastUserRow.classList.add('hidden');
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    const savedUsername = localStorage.getItem('botgpt_last_username') || '';
    if (savedUsername) {
        const loginUsername = document.getElementById('login-username');
        const registerUsername = document.getElementById('register-username');
        if (loginUsername && !loginUsername.value) loginUsername.value = savedUsername;
        if (registerUsername && !registerUsername.value) registerUsername.value = savedUsername;
    }
    updateLastUserUI(savedUsername);

    const response = await fetch(`${window.location.origin}/check_auth`);
    if (response.ok) {
        const user = await response.json();
        if (user.authenticated) {
            initializeApp(user.username);
            return;
        }
    }
    authScreen.style.display = 'flex';
    mainApp.style.display = 'none';
});

authTabs.forEach(tab => {
    tab.addEventListener('click', () => {
        switchAuthTab(tab.dataset.tab);
    });
});

continueLastUserBtn.addEventListener('click', () => {
    const savedUsername = localStorage.getItem('botgpt_last_username') || '';
    if (!savedUsername) return;
    document.getElementById('login-username').value = savedUsername;
    switchAuthTab('login');
    document.getElementById('login-password').focus();
});

loginForm.addEventListener('submit', handleAuthFormSubmit);
registerForm.addEventListener('submit', handleAuthFormSubmit);

async function handleAuthFormSubmit(e) {
    e.preventDefault();
    const isLogin = e.target.id === 'login-form';
    const url = isLogin ? '/login' : '/register';
    const username = document.getElementById(`${isLogin ? 'login' : 'register'}-username`).value.trim();
    const password = document.getElementById(`${isLogin ? 'login' : 'register'}-password`).value;

    const response = await fetch(`${window.location.origin}${url}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
    });
    const data = await response.json();
    if (response.ok) {
        localStorage.setItem('botgpt_last_username', data.username);
        updateLastUserUI(data.username);
        initializeApp(data.username);
    } else {
        if (!isLogin && response.status === 409) {
            document.getElementById('login-username').value = username;
            switchAuthTab('login');
            authError.textContent = `That account already exists. Sign in as ${username}.`;
            document.getElementById('login-password').focus();
            return;
        }

        if (isLogin && response.status === 401) {
            authError.textContent = 'That username/password combination did not match. Check the password or register a new account.';
        } else {
            authError.textContent = data.message;
        }
    }
}

async function initializeApp(username) {
    currentUsername = username;
    localStorage.setItem('botgpt_last_username', username);
    authScreen.style.display = 'none';
    mainApp.style.display = 'flex';

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
    fileViewerContainer = document.getElementById('file-viewer-container');
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
    canvasToggleBtn = document.getElementById('canvas-toggle-btn');
    participantList = document.getElementById('participant-list');
    summarizeBtn = document.getElementById('summarize-btn');
    summaryModal = document.getElementById('summary-modal');
    summaryContent = document.getElementById('summary-content');
    closeSummaryBtn = document.getElementById('close-summary-btn');
    agentModeToggle = document.getElementById('agent-mode-toggle');
    planToggleBtn = document.getElementById('plan-toggle-btn');
    planPanel = document.getElementById('plan-panel');
    planContent = document.getElementById('plan-content');
    planActions = document.getElementById('plan-actions');
    approvePlanBtn = document.getElementById('approve-plan-btn');
    rejectPlanBtn = document.getElementById('reject-plan-btn');
    toolsDropdownBtn = document.getElementById('tools-dropdown-btn');
    toolsDropdownMenu = document.getElementById('tools-dropdown-menu');

    // Image Upload Elements
    attachImageBtn = document.getElementById('attach-image-btn');
    imageInput = document.getElementById('image-input');
    imagePreviewContainer = document.getElementById('image-preview-container');

    welcomeUser.textContent = `Welcome, ${username}!`;

    // --- Image Upload Logic ---
    attachImageBtn.addEventListener('click', () => imageInput.click());
    imageInput.addEventListener('change', handleImageSelection);

    // --- Tools Dropdown Logic ---
    toolsDropdownBtn.addEventListener('click', () => {
        toolsDropdownMenu.classList.toggle('hidden');
    });

    // Close dropdown if clicking outside
    document.addEventListener('click', (event) => {
        if (!document.getElementById('tools-dropdown').contains(event.target)) {
            toolsDropdownMenu.classList.add('hidden');
        }
    });


    // --- Event Listeners for Plan Approval ---
    approvePlanBtn.addEventListener('click', () => {
        socket.emit('user_response', { conversation_id: currentConversationId, response: 'approve' });
        planActions.style.display = 'none';
    });

    rejectPlanBtn.addEventListener('click', () => {
        socket.emit('user_response', { conversation_id: currentConversationId, response: 'reject' });
        planActions.style.display = 'none';
    });

    // --- Session Persistence ---
    // (See loadTabState and saveTabState at the bottom of the file)

    // --- Socket.IO Connection ---
    socket = io();
    socket.on('connect', () => {
        console.log('Socket.IO connected');
    });
    socket.on('disconnect', () => {
        console.log('Socket.IO disconnected');
    });

    socket.on('ai_response', (data) => {
        try {
            switch(data.type) {
                case 'user_message':
                    appendMessage(data.content, 'other_user');
                    break;
                case 'conversation_id':
                    if (!currentConversationId) {
                        currentConversationId = data.id;
                        saveCurrentConversationId(currentConversationId);
                        if (pendingNewConversationRun) {
                            conversationRunStates[currentConversationId] = { ...pendingNewConversationRun };
                            pendingNewConversationRun = null;
                        }
                        addConversationToList(data.id, "New Chat");
                        socket.emit('join', {room: currentConversationId});
                    }
                    break;
                case 'open_canvas':
                    openFileCanvas(data.filename);
                    break;
                case 'plan_step_update':
                    const planStepContainer = currentAgentBubble.querySelector('.plan-step-container');
                    const planStepContent = planStepContainer.querySelector('.plan-step-content');
                    planStepContainer.style.display = 'block';
                    planStepContent.textContent = `${data.step_number}. ${data.step_description}`;
                    break;
                case 'assistant_chunk':
                    // This is the main event for streaming content
                    markConversationRunState(currentConversationId, { isRunning: true, stage: 'answering' });
                    currentResponseContent += data.content;
                    updateBotBubble(currentAgentBubble, currentResponseContent, false);
                    break;
                case 'assistant_end':
                    // This signals the end of a single thought-act-observe loop from the AI
                    // We add the full response to history here to ensure it's available for the next loop
                    if (currentResponseContent) {
                        const lastMessage = conversationHistory[conversationHistory.length - 1];
                        if (!(lastMessage && lastMessage.role === 'assistant' && lastMessage.content === currentResponseContent)) {
                            conversationHistory.push({ role: 'assistant', content: currentResponseContent });
                        }
                    }
                    markConversationRunState(currentConversationId, { isRunning: true, partialResponse: currentResponseContent, stage: 'thinking' });
                    // Final render of this loop's output, with code highlighting
                    updateBotBubble(currentAgentBubble, currentResponseContent, true);
                    // Reset for the next potential stream of thought from the AI
                    currentResponseContent = "";
                    break;
                case 'tool_call':
                     // A tool call is part of the assistant's response, so we display it.
                    markConversationRunState(currentConversationId, {
                        isRunning: true,
                        stage: 'tool_call',
                        toolName: data.name,
                        toolParams: data.params,
                        partialResponse: currentResponseContent,
                    });
                    updateBotBubble(currentAgentBubble, currentResponseContent, true);
                    showToolCall(currentAgentBubble, data.name, data.params);
                    break;
                case 'tool_result':
                    markConversationRunState(currentConversationId, { isRunning: true, stage: 'after_tool' });
                    updateAgentStatus(currentAgentBubble, `Tool finished. Analyzing results...`);
                    break;
                case 'tool_error':
                    markConversationRunState(currentConversationId, { isRunning: true, stage: 'tool_error', error: data.error });
                    updateAgentStatus(currentAgentBubble, `Tool Error: ${data.error}. Thinking...`, true);
                    break;
                case 'final_answer':
                    // This is now the definitive final answer from the agent.
                    // The content here is the complete, final conversational response.
                    currentResponseContent = data.content;
                    if (currentResponseContent) {
                        const lastMessage = conversationHistory[conversationHistory.length - 1];
                        if (!(lastMessage && lastMessage.role === 'assistant' && lastMessage.content === currentResponseContent)) {
                            conversationHistory.push({ role: 'assistant', content: currentResponseContent });
                        }
                    }
                    markConversationRunState(currentConversationId, { isRunning: true, partialResponse: currentResponseContent, stage: 'final_answer' });
                    updateBotBubble(currentAgentBubble, currentResponseContent, true);
                    break;
                case 'done':
                    // The 'done' event now signifies the absolute end of the agent's work.
                    clearConversationRunState(currentConversationId);
                    setAgentRunning(false);
                    const conversationItem = document.querySelector(`.conversation-item[data-id='${currentConversationId}'] .truncate`);
                    if (conversationItem && data.title) {
                        conversationItem.textContent = data.title;
                    }
                    // Reset content for the next user message
                    currentResponseContent = "";
                    break;
                case 'agent_error':
                    if (data.error === 'Conversation not found.') {
                        clearConversationSessionState(currentConversationId);
                        startNewChat();
                        break;
                    }
                    markConversationRunState(currentConversationId, { isRunning: true, stage: 'error', error: data.error });
                    updateAgentStatus(currentAgentBubble, `An error occurred: ${data.error}`, true);
                    setAgentRunning(false);
                    break;
                case 'refresh_files':
                    if (data.conversation_id === currentConversationId) {
                        populateFileExplorer();
                    }
                    break;
                case 'file_updated': {
                    // Update content in tabs if open
                    const tabIndex = openTabs.findIndex(t => t.path === data.path);
                    if (tabIndex !== -1) {
                        openTabs[tabIndex].content = data.content;
                        // If it's the active tab and editor is initialized, update it
                        if (tabIndex === activeTabIndex && editor) {
                            if (editor.getValue() !== data.content) {
                                editor.setValue(data.content);
                            }
                        }
                    }
                    break;
                }
            }
            smartScroll(chatContainer);
        } catch (e) {
            console.error("Error parsing socket event data:", e);
        }
    });

    socket.on('plan_updated', (data) => {
        planPanel.classList.remove('hidden');
        planPanel.classList.add('flex');
        planContent.innerHTML = '';
        const ul = document.createElement('ul');
        ul.className = 'space-y-2';
        data.steps.forEach((step, index) => {
            const li = document.createElement('li');
            li.id = `task-item-${index}`;
            li.className = 'flex items-center text-gray-400';
            li.innerHTML = `<span class="task-status mr-2">▫️</span><span class="flex-1">${step}</span>`;
            ul.appendChild(li);
        });
        planContent.appendChild(ul);

        // Show approval buttons if the plan requires it
        if (data.requires_approval) {
            planActions.style.display = 'flex';
        } else {
            planActions.style.display = 'none';
        }
    });

    socket.on('task_updated', (data) => {
        const taskItem = document.getElementById(`task-item-${data.step_index}`);
        if (taskItem) {
            const statusSpan = taskItem.querySelector('.task-status');
            taskItem.classList.remove('text-gray-400', 'text-yellow-400', 'text-green-400', 'text-red-400');
            let statusIcon = '▫️';
            let statusColor = 'text-gray-400';

            switch(data.status) {
                case 'in_progress':
                    statusIcon = '⏳';
                    statusColor = 'text-yellow-400';
                    break;
                case 'completed':
                    statusIcon = '✅';
                    statusColor = 'text-green-400';
                    break;
                case 'failed':
                    statusIcon = '❌';
                    statusColor = 'text-red-400';
                    break;
            }
            statusSpan.textContent = statusIcon;
            taskItem.classList.add(statusColor);

            // Add error message if present
            if (data.status === 'failed' && data.message) {
                let errorMsg = taskItem.querySelector('.error-message');
                if (!errorMsg) {
                    errorMsg = document.createElement('div');
                    errorMsg.className = 'error-message text-xs text-red-500 pl-6';
                    taskItem.appendChild(errorMsg);
                }
                errorMsg.textContent = data.message;
            }
        }
    });

    socket.on('participant_update', (data) => {
        updateParticipantList(data.participants);
    });

    socket.on('conversations_loaded', (conversations) => {
        populateConversations(conversations);
    });

    socket.on('conversation_loaded', (data) => {
        loadConversation(data);
    });

    function updateParticipantList(participants) {
        if (!participantList) return;
        participantList.innerHTML = ''; // Clear the list
        if (participants && participants.length > 0) {
            participants.forEach(p => {
                const participantElement = document.createElement('div');
                participantElement.className = 'p-2 text-sm text-gray-300 truncate';
                participantElement.textContent = p.username;
                participantList.appendChild(participantElement);
            });
        } else {
            participantList.innerHTML = '<p class="text-sm text-gray-500">No participants.</p>';
        }
    }

    // Attach event listeners
    logoutBtn.addEventListener('click', async () => {
        await fetch(`${window.location.origin}/logout`);
        window.location.reload();
    });

    newChatBtn.addEventListener('click', startNewChat);
    cancelDeleteBtn.addEventListener('click', () => deleteResolver(false));
    confirmDeleteBtn.addEventListener('click', () => deleteResolver(true));

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

    // --- Summary Modal Logic ---
    summarizeBtn.addEventListener('click', async () => {
        if (!currentConversationId) {
            alert("Please start or select a conversation first.");
            return;
        }

        summaryModal.classList.remove('hidden');
        summaryContent.innerHTML = '<p>Generating summary...</p>';

        try {
            const response = await fetch(`${window.location.origin}${API_BASE}/conversation/${currentConversationId}/summarize`);
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let fullSummary = '';

            reader.read().then(function processText({ done, value }) {
                if (done) {
                    summaryContent.innerHTML = marked.parse(fullSummary);
                    return;
                }

                fullSummary += decoder.decode(value, { stream: true });
                summaryContent.innerHTML = marked.parse(fullSummary);

                // Keep reading
                reader.read().then(processText);
            });

        } catch (error) {
            summaryContent.innerHTML = `<p class="text-red-400">Error generating summary: ${error.message}</p>`;
        }
    });

    closeSummaryBtn.addEventListener('click', () => {
        summaryModal.classList.add('hidden');
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

            // --- Canvas Toggle Logic ---
            canvasToggleBtn.addEventListener('click', () => {
                const canvasPanel = document.getElementById('canvas-panel');
                const isCurrentlyVisible = !canvasPanel.classList.contains('hidden');

                if (isCurrentlyVisible) {
                    hideCanvasPanel();
                } else {
                    if (openTabs.length > 0) {
                        renderCanvasPanel();
                    } else {
                        // Create a default scratchpad
                        openTabs.push({
                            path: 'Scratchpad',
                            content: '// Start typing here...',
                            mode: 'javascript'
                        });
                        activeTabIndex = 0;
                        renderCanvasPanel();
                    }
                    isCanvasMode = true;
                    canvasToggleBtn.classList.add('toggled');
                }
                saveTabState();
            });

            // The old copy/save listeners are removed as their functionality
            // is now part of the dynamically created canvas header in showCanvasPanel.

    planToggleBtn.addEventListener('click', () => {
        planPanel.classList.toggle('hidden');
        planPanel.classList.toggle('flex');
    });

    function handleSendButtonClick() {
        if (isAgentRunning && agentModeToggle.checked) {
            // If the agent is running in agent mode, this is a "Stop" button
            socket.emit('stop_agent', { conversation_id: currentConversationId });
        } else {
            // Otherwise, it's a "Send" button
            sendMessage();
        }
    }

    sendButton.addEventListener('click', handleSendButtonClick);
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

    const savedConvoId = getSavedCurrentConversationId();
    if (savedConvoId) {
        // We'll let the socket 'load_conversation' event handle the full restore of messages
        // But we can eagerly load the tabs.
        currentConversationId = savedConvoId;
        await populateFileExplorer();
        await loadTabState();
        socket.emit('load_conversation', { conversation_id: savedConvoId });
    } else {
        await populateFileExplorer();
    }

    socket.emit('load_conversations');

    // --- Resizer Logic ---
    const resizer = document.getElementById('resizer');
    const chatColumn = document.getElementById('chat-column');
    const canvasPanel = document.getElementById('canvas-panel');

    let isResizing = false;

    if (resizer) {
        resizer.addEventListener('mousedown', (e) => {
            isResizing = true;
            // Add a class to the body to prevent text selection during resize
            document.body.classList.add('resizing');
            document.addEventListener('mousemove', handleMouseMove);
            document.addEventListener('mouseup', () => {
                isResizing = false;
                document.body.classList.remove('resizing');
                document.removeEventListener('mousemove', handleMouseMove);
                // Optional: Recalculate CodeMirror layout
                if (editor) {
                    editor.refresh();
                }
            }, { once: true });
        });
    }

    function handleMouseMove(e) {
        if (!isResizing) return;
        const mainWrapper = document.getElementById('main-content-wrapper');
        const totalWidth = mainWrapper.offsetWidth;
        // Calculate new width based on mouse position relative to the main wrapper's start
        const newChatWidth = e.clientX - mainWrapper.getBoundingClientRect().left;

        // Enforce min/max widths
        const minWidth = totalWidth * 0.2; // 20% min width
        const maxWidth = totalWidth * 0.8; // 80% max width

        if (newChatWidth > minWidth && newChatWidth < maxWidth) {
            const newCanvasWidth = totalWidth - newChatWidth - resizer.offsetWidth;
            chatColumn.style.width = `${newChatWidth}px`;
            canvasPanel.style.width = `${newCanvasWidth}px`;
        }
    }
}

async function loadUserSettings() {
    try {
        const response = await fetch(`${API_BASE}/settings`);
        const settings = await response.json();

        // Populate Persona Dropdown
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
    fileExplorer.innerHTML = '<p class="text-gray-400">Loading files...</p>';
    try {
        const response = await fetch(`${window.location.origin}${API_BASE}/workspace/files/${currentConversationId}`);
        if (response.status === 404) {
            clearConversationSessionState(currentConversationId);
            fileExplorer.innerHTML = '<p class="text-gray-400">No active conversation. Start a new chat to see files.</p>';
            return;
        }
        const files = await response.json();

        let header = '';
        if (currentConversationRole === 'owner') {
            header = `
                <div class="flex justify-end p-1">
                    <button class="new-folder-btn text-gray-400 hover:text-white" title="New Folder">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 13h6m-3-3v6m-9 1V7a2 2 0 012-2h5l2 3h9a2 2 0 012 2v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"></path></svg>
                    </button>
                </div>
            `;
        }
        fileExplorer.innerHTML = header + buildFileTree(files);
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

        let actionButtons = '';
        if (currentConversationRole === 'owner') {
            actionButtons = `
                <div class="flex items-center">
                    <button class="rename-btn text-gray-400 hover:text-white mr-2" title="Rename">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
                    </button>
                    <button class="delete-btn text-red-500 hover:text-red-400 font-bold" title="Delete">&times;</button>
                </div>`;
        }

        html += `<li class="file-item item-hover flex items-center justify-between group" data-path="${fullPath}" data-type="${node.type}">
                            <span class="flex-1 cursor-pointer hover:text-blue-400 truncate">${icon} ${node.name}</span>
                            <div class="hidden group-hover:flex items-center">${actionButtons}</div>
                         </li>`;
        if (isDir && node.children) {
            html += `<li class="pl-4">${buildFileTree(node.children, fullPath)}</li>`;
        }
    });
    html += '</ul>';
    return html;
}

function attachFileEventListeners() {
    // New Folder button
    const newFolderBtn = document.querySelector('.new-folder-btn');
    if (newFolderBtn) {
        newFolderBtn.addEventListener('click', () => handleNewFolder());
    }

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

        const renameBtn = item.querySelector('.rename-btn');
        if (renameBtn) {
            renameBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                handleRename(path);
            });
        }
    });
}

async function handleNewFolder() {
    const folderName = prompt("Enter the name for the new folder:");
    if (!folderName) return;

    fileExplorer.innerHTML = '<p class="text-gray-400">Creating folder...</p>';
    try {
        const response = await fetch(`${window.location.origin}${API_BASE}/workspace/folder`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                path: folderName,
                conversation_id: currentConversationId
            })
        });
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error);
        }
        await populateFileExplorer();
    } catch (error) {
        alert(`Error creating folder: ${error.message}`);
        await populateFileExplorer();
    }
}

async function handleRename(oldPath) {
    const newName = prompt(`Enter the new name for "${oldPath}":`);
    if (!newName) return;

    // Construct the new path, preserving the directory structure
    const pathParts = oldPath.split('/');
    pathParts[pathParts.length - 1] = newName;
    const newPath = pathParts.join('/');

    fileExplorer.innerHTML = '<p class="text-gray-400">Renaming...</p>';
    try {
        const response = await fetch(`${window.location.origin}${API_BASE}/workspace/rename`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                old_path: oldPath,
                new_path: newPath,
                conversation_id: currentConversationId
            })
        });
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error);
        }
        await populateFileExplorer();
    } catch (error) {
        alert(`Error renaming: ${error.message}`);
        await populateFileExplorer();
    }
}

        function renderCanvasPanel() {
            const canvasPanel = document.getElementById('canvas-panel');
            const resizer = document.getElementById('resizer');
            const mainContentWrapper = document.getElementById('main-content-wrapper');

            if (openTabs.length === 0) {
                hideCanvasPanel();
                return;
            }

            if (window.innerWidth < 640) {
                mainContentWrapper.style.display = 'none';
            }

            // Build Tabs HTML
            let tabsHtml = '<div class="canvas-tabs-row">';
            openTabs.forEach((tab, index) => {
                const isActive = index === activeTabIndex ? 'active' : '';
                const filename = tab.path.split('/').pop();
                tabsHtml += `
                    <div class="canvas-tab ${isActive}" data-index="${index}" title="${tab.path}">
                        <span class="tab-name text-sm">${filename}</span>
                        <span class="canvas-tab-close" data-index="${index}">&times;</span>
                    </div>
                `;
            });
            tabsHtml += '</div>';

            const activeTab = openTabs[activeTabIndex];

            canvasPanel.innerHTML = `
                ${tabsHtml}
                <div class="canvas-header">
                    <h3 class="canvas-header-title text-sm" title="${activeTab.path}">${activeTab.path}</h3>
                    <div class="canvas-header-buttons">
                        <button id="canvas-copy-btn">Copy</button>
                        <button id="canvas-save-btn">Save</button>
                        <button id="canvas-close-btn">Close Panel</button>
                    </div>
                </div>
                <div id="file-viewer" class="flex-1"></div>
            `;

            canvasPanel.classList.remove('hidden');
            canvasPanel.classList.add('flex');
            resizer.classList.remove('hidden');

            // Attach Tab Listeners
            document.querySelectorAll('.canvas-tab').forEach(tabEl => {
                tabEl.addEventListener('click', (e) => {
                    if (e.target.classList.contains('canvas-tab-close')) return;
                    const index = parseInt(tabEl.dataset.index);
                    if (index !== activeTabIndex) {
                         if (editor) {
                             openTabs[activeTabIndex].content = editor.getValue();
                         }
                         activeTabIndex = index;
                         renderCanvasPanel();
                         saveTabState();
                    }
                });
            });

            document.querySelectorAll('.canvas-tab-close').forEach(closeBtn => {
                closeBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const index = parseInt(closeBtn.dataset.index);
                    closeTab(index);
                });
            });

            // Attach Header Listeners
            document.getElementById('canvas-copy-btn').addEventListener('click', () => {
                if (editor) navigator.clipboard.writeText(editor.getValue());
            });

            document.getElementById('canvas-save-btn').addEventListener('click', async () => {
                if (editor) {
                    const newContent = editor.getValue();
                    openTabs[activeTabIndex].content = newContent;

                    const saveBtn = document.getElementById('canvas-save-btn');
                    saveBtn.textContent = 'Saving...';

                    try {
                        const response = await fetch(`${window.location.origin}${API_BASE}/workspace/file`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                path: activeTab.path,
                                content: newContent,
                                conversation_id: currentConversationId
                            })
                        });
                        if (!response.ok) {
                            const data = await response.json();
                            throw new Error(data.error);
                        }
                        saveBtn.textContent = 'Saved!';
                        setTimeout(() => { saveBtn.textContent = 'Save'; }, 2000);
                    } catch (error) {
                        alert(`Error saving file: ${error.message}`);
                        saveBtn.textContent = 'Save';
                    }
                }
            });

            document.getElementById('canvas-close-btn').addEventListener('click', hideCanvasPanel);

            initializeEditor(activeTab.content, activeTab.mode);
        }

        function closeTab(index) {
            if (editor && activeTabIndex === index) {
                // If closing active tab, save content first? No, closing means discard unsaved UI state.
            }

            openTabs.splice(index, 1);

            if (openTabs.length === 0) {
                activeTabIndex = -1;
                hideCanvasPanel();
            } else {
                if (index === activeTabIndex) {
                    activeTabIndex = Math.max(0, index - 1);
                } else if (index < activeTabIndex) {
                    activeTabIndex--;
                }
                renderCanvasPanel();
            }
            saveTabState();
        }

        function hideCanvasPanel() {
            // Save state of active editor
            if (editor && activeTabIndex !== -1 && openTabs[activeTabIndex]) {
                openTabs[activeTabIndex].content = editor.getValue();
            }

            const canvasPanel = document.getElementById('canvas-panel');
            const resizer = document.getElementById('resizer');
            const mainContentWrapper = document.getElementById('main-content-wrapper');

            if (window.innerWidth < 640) {
                mainContentWrapper.style.display = 'flex';
            }

            canvasPanel.classList.add('hidden');
            canvasPanel.classList.remove('flex');
            resizer.classList.add('hidden');

            if (editor) {
                editor.getWrapperElement().remove();
                editor = null;
            }

            isCanvasMode = false;
            canvasToggleBtn.classList.remove('toggled');
            saveTabState();
        }

        async function openFileCanvas(path) {
            const existingIndex = openTabs.findIndex(t => t.path === path);
            if (existingIndex !== -1) {
                activeTabIndex = existingIndex;
                renderCanvasPanel();
                isCanvasMode = true;
                canvasToggleBtn.classList.add('toggled');
                saveTabState();
                return;
            }

            try {
                const response = await fetch(`${window.location.origin}${API_BASE}/workspace/file?path=${encodeURIComponent(path)}&conversation_id=${currentConversationId}`);
                const data = await response.json();
                if (!response.ok) throw new Error(data.error);

                let mode = 'text/plain';
                if (path.endsWith('.py')) mode = 'python';
                if (path.endsWith('.js')) mode = 'javascript';
                if (path.endsWith('.html')) mode = 'xml';
                if (path.endsWith('.css')) mode = 'css';
                if (path.endsWith('.json')) mode = 'javascript';

                openTabs.push({
                    path: path,
                    content: data.content,
                    mode: mode
                });
                activeTabIndex = openTabs.length - 1;

                renderCanvasPanel();

                isCanvasMode = true;
                canvasToggleBtn.classList.add('toggled');
                saveTabState();

            } catch (error) {
                alert(`Error opening file: ${error.message}`);
            }
        }

        function initializeEditor(content, mode) {
            const editorContainer = document.getElementById('file-viewer');
            if (!editorContainer) return;
            editorContainer.innerHTML = '';
            editor = CodeMirror(editorContainer, {
                value: content,
                mode: mode,
                theme: 'dracula',
                lineNumbers: true,
                readOnly: currentConversationRole !== 'owner'
            });

            // Add debounce for auto-saving
            editor.on('change', () => {
                clearTimeout(debounceTimer);
                const saveBtn = document.getElementById('canvas-save-btn');
                if (saveBtn) {
                    saveBtn.textContent = 'Saving...';
                }
                debounceTimer = setTimeout(() => {
                    if (saveBtn) {
                        saveBtn.click(); // Trigger the save button's existing click logic
                    }
                }, 1500); // Save after 1.5 seconds of inactivity
            });
        }

async function confirmDeletion(id, type, itemType) {
    deleteModalText.textContent = `Are you sure you want to delete this ${itemType}: ${id}?`;
    deleteModal.classList.remove('hidden');
    const confirmed = await new Promise(resolve => { deleteResolver = resolve; });
    if (confirmed) {
        if (itemType === 'file' || itemType === 'directory') {
            fileExplorer.innerHTML = '<p class="text-gray-400">Deleting...</p>';
        }
        try {
            let url, body;
            if (itemType === 'file' || itemType === 'directory') {
                url = `${API_BASE}/workspace/file`;
                body = { path: id, conversation_id: currentConversationId };
            } else {
                url = `${API_BASE}/conversations`;
                body = { conversation_id: id };
            }
            const response = await fetch(url, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            let responseData = null;
            const contentType = response.headers.get('content-type') || '';
            if (contentType.includes('application/json')) {
                responseData = await response.json();
            } else {
                const text = await response.text();
                responseData = { error: text };
            }
            if (!response.ok) {
                throw new Error(responseData.error || responseData.message || `Request failed with status ${response.status}`);
            }

            if (itemType === 'file' || itemType === 'directory') {
                await populateFileExplorer();
            } else {
                socket.emit('load_conversations');
                if (id === currentConversationId) {
                    startNewChat();
                }
            }
        } catch (error) {
            console.error(`Failed to delete ${id}:`, error);
            const cleanedMessage = String(error.message || 'Unknown error')
                .replace(/<[^>]+>/g, ' ')
                .replace(/\s+/g, ' ')
                .trim();
            alert(`Error deleting ${itemType}: ${cleanedMessage}`);
            if (itemType === 'file' || itemType === 'directory') {
                await populateFileExplorer();
            }
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
    } finally {
        setAgentRunning(false);
    }
}

function setAgentRunning(isRunning, agentMode = false) {
    isAgentRunning = isRunning;
    chatInput.disabled = isRunning;

    if (isRunning) {
        if (agentMode) {
            // Transform to a Stop button
            sendButton.innerHTML = `<svg class="w-6 h-6" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8 7a.5.5 0 01.5-.5h3a.5.5 0 010 1h-3A.5.5 0 018 7zm2 4a.5.5 0 01.5.5v3a.5.5 0 01-1 0v-3a.5.5 0 01.5-.5z" clip-rule="evenodd"></path></svg>`;
            sendButton.classList.remove('bg-blue-600', 'hover:bg-blue-700');
            sendButton.classList.add('bg-red-600', 'hover:bg-red-700');
            sendButton.disabled = false; // Keep it enabled to be clickable
        } else {
            // Standard thinking spinner
            sendButton.disabled = true;
            sendButton.classList.add('bg-gray-500', 'cursor-not-allowed');
            sendButton.classList.remove('bg-blue-600', 'hover:bg-blue-700', 'bg-red-600', 'hover:bg-red-700');
            sendButton.innerHTML = `<svg class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>`;
        }
    } else {
        // Revert to Send button
        sendButton.disabled = false;
        sendButton.classList.remove('bg-gray-500', 'cursor-not-allowed', 'bg-red-600', 'hover:bg-red-700');
        sendButton.classList.add('bg-blue-600', 'hover:bg-blue-700');
        sendButton.innerHTML = `<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14M12 5l7 7-7 7"></path></svg>`;
    }
}

function markConversationRunState(conversationId, patch) {
    if (!conversationId) return;
    conversationRunStates[conversationId] = {
        ...(conversationRunStates[conversationId] || {}),
        ...patch,
    };
}

function clearConversationRunState(conversationId) {
    if (!conversationId) return;
    delete conversationRunStates[conversationId];
}

function getConversationRunState(conversationId) {
    return conversationId ? conversationRunStates[conversationId] || null : null;
}

function showRecoveredRunIndicator(bubbleElement, text = 'Still working...') {
    if (!bubbleElement) return;
    const agentStatus = bubbleElement.querySelector('.agent-status');
    agentStatus.textContent = text;
    agentStatus.style.display = 'block';
    agentStatus.classList.remove('text-red-400');
}

function restoreActiveRun(activeRun) {
    if (!activeRun || !activeRun.is_running) {
        currentAgentBubble = null;
        currentResponseContent = '';
        setAgentRunning(false);
        return;
    }

    currentAgentBubble = createBotMessageContainer(false);
    currentResponseContent = activeRun.partial_response || '';

    if (currentResponseContent) {
        updateBotBubble(currentAgentBubble, currentResponseContent, false);
        showRecoveredRunIndicator(currentAgentBubble);
    }

    switch (activeRun.stage) {
        case 'tool_call':
            showToolCall(currentAgentBubble, activeRun.tool_name, activeRun.tool_params);
            break;
        case 'after_tool':
            updateAgentStatus(currentAgentBubble, 'Tool finished. Analyzing results...');
            break;
        case 'tool_error':
        case 'error':
            updateAgentStatus(currentAgentBubble, `An error occurred: ${activeRun.error || 'Unknown error'}`, true);
            break;
        default:
            if (!currentResponseContent) {
                showRecoveredRunIndicator(currentAgentBubble);
            }
            break;
    }

    setAgentRunning(true, !!activeRun.agent_mode);
}

let pendingImages = [];

function handleImageSelection() {
    const files = Array.from(imageInput.files);
    if (files.length === 0) return;

    files.forEach(file => {
        const reader = new FileReader();
        reader.onload = (e) => {
            const base64 = e.target.result;
            pendingImages.push(base64);

            const previewWrapper = document.createElement('div');
            previewWrapper.className = "relative w-16 h-16 flex-shrink-0";

            const img = document.createElement('img');
            img.src = base64;
            img.className = "w-full h-full object-cover rounded border border-gray-600";

            const removeBtn = document.createElement('button');
            removeBtn.innerHTML = "&times;";
            removeBtn.className = "absolute -top-2 -right-2 bg-red-600 text-white rounded-full w-5 h-5 flex items-center justify-center text-xs";
            removeBtn.onclick = () => {
                pendingImages = pendingImages.filter(p => p !== base64);
                previewWrapper.remove();
                if (pendingImages.length === 0) imagePreviewContainer.classList.add('hidden');
            };

            previewWrapper.appendChild(img);
            previewWrapper.appendChild(removeBtn);
            imagePreviewContainer.appendChild(previewWrapper);
        };
        reader.readAsDataURL(file);
    });

    imagePreviewContainer.classList.remove('hidden');
    imageInput.value = ''; // Reset so same file can be selected again
}

function sendMessage() {
    const text = chatInput.value.trim();
    if ((!text && pendingImages.length === 0) || getConversationRunState(currentConversationId)?.isRunning) return;

    const agentMode = agentModeToggle.checked;
    setAgentRunning(true, agentMode);

    welcomeMessage.style.display = 'none';

    // Display user message with images if present
    appendMessage(text, 'user', true, pendingImages);

    // Prepare message for history/backend
    const newMessage = { role: 'user', content: text };
    if (pendingImages.length > 0) {
        newMessage.images = [...pendingImages]; // Send images to backend
    }

    conversationHistory.push(newMessage);

    chatInput.value = '';
    chatInput.style.height = 'auto';

    // Clear pending images
    pendingImages = [];
    imagePreviewContainer.innerHTML = '';
    imagePreviewContainer.classList.add('hidden');

    currentAgentBubble = createBotMessageContainer();
    currentResponseContent = ""; // Reset the content for the new message
    if (currentConversationId) {
        markConversationRunState(currentConversationId, { isRunning: true, agentMode, stage: 'thinking', partialResponse: '' });
    } else {
        pendingNewConversationRun = { isRunning: true, agentMode, stage: 'thinking', partialResponse: '' };
    }

    const params = {
        messages: JSON.stringify(conversationHistory),
        model: userModel,
        conversation_id: currentConversationId || '',
        canvas_mode: isCanvasMode,
        agent_mode: agentMode
    };
    try {
        socket.emit('chat_message', params);
    } catch (error) {
        console.error("Error sending message:", error);
        setAgentRunning(false);
    }
}

function createBotMessageContainer(animate = true) {
    const botMessageWrapper = document.createElement('div');
    let classes = 'flex max-w-3xl w-full items-start self-start mx-auto';
    if (animate) {
        classes += ' newly-added';
    }
    botMessageWrapper.className = classes;

    botMessageWrapper.innerHTML = `
        <div class="w-8 h-8 rounded-full bg-gray-600 flex-shrink-0 mr-2 flex items-center justify-center">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" fill="currentColor" class="bi bi-robot" viewBox="0 0 16 16">
                <path d="M6 12.5a.5.5 0 0 1 .5-.5h3a.5.5 0 0 1 0 1h-3a.5.5 0 0 1-.5-.5M3 8.062C3 6.76 4.235 5.765 5.53 5.886a26.6 26.6 0 0 0 4.94 0C11.765 5.765 13 6.76 13 8.062v1.157a.93.93 0 0 1-.765.935c-.845.147-2.34.346-4.235.346s-3.39-.2-4.235-.346A.93.93 0 0 1 3 9.219zm4.542-.827a.25.25 0 0 0-.217.068l-.92.9a25 25 0 0 1-1.871-.183.25.25 0 0 0-.217.068l-.92.9a.25.25 0 0 0 .169.434h.295c.079 0 .152-.031.206-.086l.92-.9a.25.25 0 0 1 .169-.068c.975.083 2.04.083 3.015 0a.25.25 0 0 1 .169.068l.92.9c.054.055.127.086.206.086h.295a.25.25 0 0 0 .169-.434l-.92-.9a.25.25 0 0 0-.217-.068 25 25 0 0 1-1.871.183l-.92-.9a.25.25 0 0 0-.217-.068Z"/>
                <path d="M8 1a2.5 2.5 0 0 1 2.5 2.5V4h-5v-.5A2.5 2.5 0 0 1 8 1m3.5 3v-.5a3.5 3.5 0 1 0-7 0V4H1v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V4zM1 5h14v9a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1z"/>
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

    smartScroll(chatContainer);
    return botMessageWrapper;
}

function updateBotBubble(bubbleElement, responseContent, isFinal = false) {
    if (!bubbleElement) return;

    const thinkingContainer = bubbleElement.querySelector('.thinking-process-container');
    const thinkingContentEl = thinkingContainer.querySelector('.thinking-content');
    const answerContent = bubbleElement.querySelector('.answer-content');
    const agentStatus = bubbleElement.querySelector('.agent-status');
    const toolActivity = bubbleElement.querySelector('.tool-activity');

    // Extract thought content
    const thinkMatch = responseContent.match(/<think>([\s\S]*?)<\/think>/);
    const thinkContent = thinkMatch ? thinkMatch[1] : null;

    // Extract conversational content (everything outside think and tool blocks)
    const conversationalContent = responseContent
        .replace(/<think>[\s\S]*?<\/think>/g, '')
        .replace(/```json\s*([\s\S]*?)\s*```/g, '')
        .trim();

    if (thinkContent) {
        thinkingContainer.style.display = 'block';
        thinkingContentEl.innerHTML = marked.parse(thinkContent);
        smartScroll(thinkingContentEl);
    } else {
        // Hide it only if we are in a final state, otherwise it might just not have arrived yet
        if (isFinal) {
            thinkingContainer.style.display = 'none';
        }
    }

    if (conversationalContent) {
        agentStatus.style.display = 'none';
        toolActivity.style.display = 'none';
        answerContent.style.display = 'block';
        answerContent.innerHTML = marked.parse(conversationalContent);
    } else {
        answerContent.style.display = 'none';
        // If there's no conversational content yet, and no tool is active, show the "thinking" status
        if ((!toolActivity.style.display || toolActivity.style.display === 'none') && !isFinal) {
             agentStatus.style.display = 'block';
        }
    }

    if (isFinal) {
        // Hide the main thinking indicator when the turn is truly over
        agentStatus.style.display = 'none';
        if (conversationalContent || thinkContent) {
            toolActivity.style.display = 'none';
        }
        if (!conversationalContent && !thinkContent) {
            // If there's no content at all in the end, don't show an empty bubble.
            // This can happen if the AI only calls a tool.
            answerContent.style.display = 'none';
        }

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
        if (item.dataset.id !== currentConversationId) {
            socket.emit('load_conversation', { conversation_id: item.dataset.id });
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

function populateConversations(convos) {
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
            if (convo.id !== currentConversationId) {
                socket.emit('load_conversation', { conversation_id: convo.id });
            }
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

function loadConversation(data) {
    if (currentConversationId && currentConversationId !== data.id) {
        socket.emit('leave', { room: currentConversationId });
        // Switching conversation, so clear current tabs unless we want global tabs?
        // Tabs should be conversation-scoped.
        // But if we are reloading page, we already loaded tabs for THIS conversation.
        // If we are clicking a new conversation in the list, we should clear/load new tabs.
    }

    // Check if we switched conversations
    if (currentConversationId !== data.id) {
         currentConversationId = data.id;
         openTabs = [];
         activeTabIndex = -1;
         hideCanvasPanel();
         saveCurrentConversationId(currentConversationId);
         loadTabState(); // Load tabs for the NEW conversation
    }

    currentConversationId = data.id;
    saveCurrentConversationId(currentConversationId);

    currentConversationRole = data.role;
    chatContainer.innerHTML = '';
    welcomeMessage.style.display = 'none';
    currentAgentBubble = null;
    currentResponseContent = '';

    conversationHistory = data.messages || [];
    // Re-render history
    conversationHistory.forEach(msg => {
        if (msg.role === 'user') {
            appendMessage(msg.content, 'user', false);
        } else if (msg.role === 'assistant') {
            const botBubble = createBotMessageContainer(false);
            updateBotBubble(botBubble, msg.content, true);
        }
    });

    if (data.active_run && data.active_run.is_running) {
        markConversationRunState(data.id, {
            isRunning: true,
            agentMode: !!data.active_run.agent_mode,
            partialResponse: data.active_run.partial_response || '',
            stage: data.active_run.stage || 'thinking',
            toolName: data.active_run.tool_name || null,
            toolParams: data.active_run.tool_params || null,
            error: data.active_run.error || null,
        });
        restoreActiveRun(data.active_run);
    } else {
        clearConversationRunState(data.id);
        setAgentRunning(false);
    }

    chatContainer.scrollTop = chatContainer.scrollHeight;
    socket.emit('join', { room: data.id });
    populateFileExplorer();
    socket.emit('load_conversations'); // To update the active state
}

function smartScroll(element) {
    // Use a small timeout to allow the DOM to update before we calculate scroll positions
    setTimeout(() => {
        if (!element) return;
        const threshold = 20; // A bit more lenient
        // Check if the user has scrolled up from the bottom
        const isScrolledUp = element.scrollHeight - element.clientHeight > element.scrollTop + threshold;

        // Only scroll to the bottom if the user hasn't intentionally scrolled up
        if (!isScrolledUp) {
            element.scrollTop = element.scrollHeight;
        }
    }, 50); // 50ms delay to be safe
}

function startNewChat() {
    if (currentConversationId) {
        socket.emit('leave', { room: currentConversationId });
    }
    currentConversationId = null;
    currentConversationRole = 'owner';
    conversationHistory = [];
    openTabs = [];
    activeTabIndex = -1;
    pendingImages = [];
    imagePreviewContainer.innerHTML = '';
    imagePreviewContainer.classList.add('hidden');
    clearCurrentConversationId();
    chatContainer.innerHTML = '';
    welcomeMessage.style.display = 'flex';
    planContent.innerHTML = '';
    planPanel.classList.add('hidden');
    planPanel.classList.remove('flex');
    hideCanvasPanel();
    currentAgentBubble = null;
    currentResponseContent = '';
    setAgentRunning(false);
    populateFileExplorer();
    socket.emit('load_conversations'); // To update active state
}

function appendMessage(text, sender, animate = true, images = []) {
    const messageWrapper = document.createElement('div');
    let classes = `flex max-w-3xl w-full items-start self-${sender === 'user' ? 'end' : 'start'} mx-auto`;
    if (animate) {
        classes += ' newly-added';
    }
    messageWrapper.className = classes;

    if (sender === 'user') {
        let imageGrid = '';
        if (images && images.length > 0) {
            imageGrid = `<div class="flex flex-wrap gap-2 mb-2">`;
            images.forEach(imgSrc => {
                 imageGrid += `<img src="${imgSrc}" class="max-w-[150px] max-h-[150px] rounded border border-gray-600">`;
            });
            imageGrid += `</div>`;
        }

        messageWrapper.innerHTML = `
            <div class="flex-1 user-bubble">
                ${imageGrid}
                <div class="prose prose-invert max-w-none">${marked.parse(text)}</div>
            </div>
            <div class="w-8 h-8 rounded-full bg-blue-800 flex-shrink-0 ml-2 flex items-center justify-center">
                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" fill="currentColor" class="bi bi-person" viewBox="0 0 16 16">
                    <path d="M8 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6m2-3a2 2 0 1 1-4 0 2 2 0 0 1 4 0m4 8c0 1-1 1-1 1H3s-1 0-1-1 1-4 6-4 6 3 6 4m-1-.004c-.001-.246-.154-.986-.832-1.664C11.516 10.68 10.289 10 8 10s-3.516.68-4.168 1.332c-.678.678-.83 1.418-.832 1.664z"/>
                </svg>
            </div>`;
    } else if (sender === 'other_user') {
        messageWrapper.innerHTML = `
            <div class="w-8 h-8 rounded-full bg-green-800 flex-shrink-0 mr-2 flex items-center justify-center">
                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" fill="currentColor" class="bi bi-person" viewBox="0 0 16 16">
                    <path d="M8 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6m2-3a2 2 0 1 1-4 0 2 2 0 0 1 4 0m4 8c0 1-1 1-1 1H3s-1 0-1-1 1-4 6-4 6 3 6 4m-1-.004c-.001-.246-.154-.986-.832-1.664C11.516 10.68 10.289 10 8 10s-3.516.68-4.168 1.332c-.678.678-.83 1.418-.832 1.664z"/>
                </svg>
            </div>
            <div class="flex-1 bot-bubble">
                <div class="prose prose-invert max-w-none">${marked.parse(text)}</div>
            </div>`;
    }

    chatContainer.appendChild(messageWrapper);
    smartScroll(chatContainer);
}

function saveTabState() {
    if (!currentConversationId) return;

    const tabsToSave = openTabs.map(tab => ({
        path: tab.path,
        mode: tab.mode
    }));

    const state = {
        tabs: tabsToSave,
        activeTabIndex: activeTabIndex,
        isCanvasMode: isCanvasMode
    };

    localStorage.setItem(getTabsStorageKey(currentConversationId), JSON.stringify(state));
}

async function loadTabState() {
    if (!currentConversationId) return;

    const savedState = localStorage.getItem(getTabsStorageKey(currentConversationId));
    if (!savedState) return;

    try {
        const state = JSON.parse(savedState);
        const tabsToLoad = state.tabs || [];
        const savedActiveIndex = state.activeTabIndex;
        const savedCanvasMode = state.isCanvasMode;

        // Reset tabs
        openTabs = [];

        // We need to fetch content for each tab to ensure it's up to date
        // Use Promise.all for parallel fetching
        const promises = tabsToLoad.map(async (tab) => {
            if (tab.path === 'Scratchpad') {
                 return {
                    path: 'Scratchpad',
                    content: '// Start typing here...', // Or maybe persist scratchpad content too?
                    mode: tab.mode
                };
            }
            try {
                const response = await fetch(`${window.location.origin}${API_BASE}/workspace/file?path=${encodeURIComponent(tab.path)}&conversation_id=${currentConversationId}`);
                if (!response.ok) throw new Error('Failed');
                const data = await response.json();
                return {
                    path: tab.path,
                    content: data.content,
                    mode: tab.mode
                };
            } catch (e) {
                console.warn(`Could not load tab content for ${tab.path}:`, e);
                return null; // Filter out later
            }
        });

        const loadedTabs = await Promise.all(promises);
        openTabs = loadedTabs.filter(t => t !== null);

        // Restore active index within bounds
        if (openTabs.length > 0) {
            if (savedActiveIndex >= 0 && savedActiveIndex < openTabs.length) {
                activeTabIndex = savedActiveIndex;
            } else {
                activeTabIndex = 0;
            }

            // Only render/show if it was open before or we have tabs
            // If savedCanvasMode was true, we show it.
            if (savedCanvasMode) {
                 renderCanvasPanel();
                 isCanvasMode = true;
                 canvasToggleBtn.classList.add('toggled');
            }
        }

    } catch (e) {
        console.error("Error loading tab state:", e);
    }
}
