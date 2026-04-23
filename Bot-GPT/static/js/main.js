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
    planToggleBtn, planPanel, planContent, planActions, approvePlanBtn, rejectPlanBtn,
    responseModeSelect, thoughtPanelDefaultToggle,
    liveActivityBar, liveActivityText, liveActivityPanel, activityPanelToggle, activityStageText, activityFocusText, activityActionText,
    toolTimelineToggle, toolTimelineList,
    proactiveDashboard, heartbeatLabel, taskDashboardSummary, taskDashboardList, notificationInboxSummary,
    telegramPairBtn, telegramPairCode,
    dependencyBanner, dependencyBannerText, dependencyBannerDismiss, dependencyBannerDetails,
    dependencyDetailsModal, dependencyDetailsContent, closeDependencyDetailsBtn, copyDependencyDetailsBtn;

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
let currentResponseMode = null;
let selectedResponseModePreference = 'auto';
let thoughtPanelExpandedByDefault = false;
let openTabs = [];
let activeTabIndex = -1;
let conversationRunStates = {};
let pendingNewConversationRun = null;
let dependencyBannerDismissedForSession = false;
let lastDependencyReport = null;
let liveActivityState = {
    currentStage: 'idle',
    currentFocus: '—',
    lastAction: 'Waiting for request.',
    activeTool: null,
    startedAt: null,
};
let toolTimelineEntries = [];
let toolTimelineByCallId = new Map();
let artifactState = {
    currentArtifactId: null,
    artifactStatus: 'idle',
    artifactType: 'unknown',
    lastUpdatedAt: null,
    previewAvailable: false,
};
let artifactPreviewVisible = false;
let artifactList = [];
let artifactById = new Map();
let workspacePanelCollapsedMobile = true;
let artifactVersions = [];
let selectedArtifactVersionId = null;
let proactiveDashboardTimer = null;

function getCurrentConversationStorageKey() {
    return currentUsername ? `botgpt_current_conversation_id_${currentUsername}` : 'botgpt_current_conversation_id';
}

function getTabsStorageKey(conversationId) {
    return currentUsername ? `botgpt_tabs_${currentUsername}_${conversationId}` : `botgpt_tabs_${conversationId}`;
}

function sortArtifacts(items = []) {
    return [...items].sort((a, b) => Number(b.last_updated_at || 0) - Number(a.last_updated_at || 0));
}

function upsertArtifactEntry(entry) {
    if (!entry || !entry.artifact_id) return;
    const normalized = {
        artifact_id: entry.artifact_id,
        conversation_id: entry.conversation_id || currentConversationId,
        artifact_type: entry.artifact_type || inferArtifactType(entry.artifact_id),
        last_updated_at: entry.last_updated_at || Date.now() / 1000,
        title: entry.title || entry.artifact_id.split('/').pop(),
    };
    artifactById.set(normalized.artifact_id, normalized);
    artifactList = sortArtifacts(Array.from(artifactById.values()));
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

function formatRelativeTime(epochSeconds) {
    if (!epochSeconds) return '—';
    const delta = Math.max(0, Math.floor(Date.now() / 1000 - Number(epochSeconds)));
    if (delta < 60) return `${delta}s ago`;
    if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
    return `${Math.floor(delta / 3600)}h ago`;
}

async function refreshProactiveDashboard() {
    if (!proactiveDashboard) return;
    try {
        const [tasksRes, heartbeatRes, notificationsRes, telegramStatusRes] = await Promise.all([
            fetch(`${API_BASE}/tasks`),
            fetch(`${API_BASE}/system/heartbeat`),
            fetch(`${API_BASE}/notifications?unread_only=1`),
            fetch(`${API_BASE}/telegram/status`),
        ]);
        const tasksData = await tasksRes.json();
        const heartbeatData = await heartbeatRes.json();
        const notificationsData = await notificationsRes.json();
        const telegramData = await telegramStatusRes.json();

        const tasks = tasksData.tasks || [];
        const unread = notificationsData.notifications || [];
        heartbeatLabel.textContent = `Heartbeat: ${formatRelativeTime(heartbeatData.last_heartbeat)}`;
        taskDashboardSummary.textContent = tasks.length
            ? `${tasks.filter((t) => t.status === 'active').length} active task(s) • last activity ${formatRelativeTime(heartbeatData.last_task_activity)}`
            : 'No background tasks configured.';
        notificationInboxSummary.textContent = `Notifications: ${unread.length} unread`;

        taskDashboardList.innerHTML = '';
        tasks.slice(0, 5).forEach((task) => {
            const li = document.createElement('li');
            const lastResult = task.last_result?.message || 'No results yet';
            li.className = 'text-gray-300';
            li.textContent = `${task.name} — ${task.status} — last ${formatRelativeTime(task.last_run)} — next ${formatRelativeTime(task.next_run)} — ${lastResult}`;
            taskDashboardList.appendChild(li);
        });
        if (telegramPairCode) {
            const linked = telegramData.linked_accounts || [];
            telegramPairCode.textContent = linked.length
                ? `Paired: @${linked[0].telegram_username || linked[0].telegram_user_id}`
                : 'Not paired';
        }
    } catch (error) {
        console.error('Failed to refresh proactive dashboard', error);
        if (taskDashboardSummary) taskDashboardSummary.textContent = 'Proactive dashboard unavailable.';
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
    dependencyBanner = document.getElementById('dependency-banner');
    dependencyBannerText = document.getElementById('dependency-banner-text');
    dependencyBannerDismiss = document.getElementById('dependency-banner-dismiss');
    dependencyBannerDetails = document.getElementById('dependency-banner-details');
    dependencyDetailsModal = document.getElementById('dependency-details-modal');
    dependencyDetailsContent = document.getElementById('dependency-details-content');
    closeDependencyDetailsBtn = document.getElementById('close-dependency-details-btn');
    copyDependencyDetailsBtn = document.getElementById('copy-dependency-details-btn');
    responseModeSelect = document.getElementById('response-mode-select');
    thoughtPanelDefaultToggle = document.getElementById('thought-panel-default-toggle');
    liveActivityBar = document.getElementById('live-activity-bar');
    liveActivityText = document.getElementById('live-activity-text');
    liveActivityPanel = document.getElementById('live-activity-panel');
    activityPanelToggle = document.getElementById('activity-panel-toggle');
    activityStageText = document.getElementById('activity-stage-text');
    activityFocusText = document.getElementById('activity-focus-text');
    activityActionText = document.getElementById('activity-action-text');
    toolTimelineToggle = document.getElementById('tool-timeline-toggle');
    toolTimelineList = document.getElementById('tool-timeline-list');
    proactiveDashboard = document.getElementById('proactive-dashboard');
    heartbeatLabel = document.getElementById('heartbeat-label');
    taskDashboardSummary = document.getElementById('task-dashboard-summary');
    taskDashboardList = document.getElementById('task-dashboard-list');
    notificationInboxSummary = document.getElementById('notification-inbox-summary');
    telegramPairBtn = document.getElementById('telegram-pair-btn');
    telegramPairCode = document.getElementById('telegram-pair-code');

    // Image Upload Elements
    attachImageBtn = document.getElementById('attach-image-btn');
    imageInput = document.getElementById('image-input');
    imagePreviewContainer = document.getElementById('image-preview-container');

    welcomeUser.textContent = `Welcome, ${username}!`;
    activityPanelToggle?.addEventListener('click', () => {
        const isOpen = liveActivityPanel?.dataset.open === 'true';
        liveActivityPanel.dataset.open = isOpen ? 'false' : 'true';
    });
    toolTimelineToggle?.addEventListener('click', () => {
        const isOpen = toolTimelineList?.dataset.open === 'true';
        toolTimelineList.dataset.open = isOpen ? 'false' : 'true';
    });
    updateLiveActivity({ stage: 'idle', action: 'Ready for your request.' });
    resetToolTimeline();
    await refreshProactiveDashboard();
    if (proactiveDashboardTimer) clearInterval(proactiveDashboardTimer);
    proactiveDashboardTimer = setInterval(refreshProactiveDashboard, 30000);
    telegramPairBtn?.addEventListener('click', async () => {
        try {
            const response = await fetch(`${API_BASE}/telegram/pairing-code`, { method: 'POST' });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || 'Failed to generate pairing code');
            telegramPairCode.textContent = `${payload.pairing_code} (expires soon)`;
        } catch (error) {
            console.error('Telegram pairing code error', error);
            telegramPairCode.textContent = 'Pairing unavailable';
        }
    });

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

    const responseModeStorageKey = currentUsername ? `botgpt_response_mode_${currentUsername}` : 'botgpt_response_mode';
    const thoughtPanelStorageKey = currentUsername ? `botgpt_thought_panel_expanded_${currentUsername}` : 'botgpt_thought_panel_expanded';
    const dependencyBannerStorageKey = currentUsername ? `botgpt_dependency_banner_dismissed_${currentUsername}` : 'botgpt_dependency_banner_dismissed';
    dependencyBannerDismissedForSession = sessionStorage.getItem(dependencyBannerStorageKey) === '1';
    selectedResponseModePreference = localStorage.getItem(responseModeStorageKey) || 'auto';
    thoughtPanelExpandedByDefault = localStorage.getItem(thoughtPanelStorageKey) === '1';
    if (responseModeSelect) {
        responseModeSelect.value = selectedResponseModePreference;
        responseModeSelect.addEventListener('change', async () => {
            selectedResponseModePreference = responseModeSelect.value || 'auto';
            localStorage.setItem(responseModeStorageKey, selectedResponseModePreference);
            try {
                await fetch(`${API_BASE}/settings`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ response_mode_preference: selectedResponseModePreference }),
                });
            } catch (error) {
                console.error("Failed to save response mode preference:", error);
            }
        });
    }
    if (thoughtPanelDefaultToggle) {
        thoughtPanelDefaultToggle.checked = thoughtPanelExpandedByDefault;
        thoughtPanelDefaultToggle.addEventListener('change', async () => {
            thoughtPanelExpandedByDefault = !!thoughtPanelDefaultToggle.checked;
            localStorage.setItem(thoughtPanelStorageKey, thoughtPanelExpandedByDefault ? '1' : '0');
            try {
                await fetch(`${API_BASE}/settings`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ thought_panel_expanded: thoughtPanelExpandedByDefault }),
                });
            } catch (error) {
                console.error("Failed to save thought panel preference:", error);
            }
        });
    }

    if (dependencyBannerDismiss) {
        dependencyBannerDismiss.addEventListener('click', () => {
            dependencyBannerDismissedForSession = true;
            sessionStorage.setItem(dependencyBannerStorageKey, '1');
            if (dependencyBanner) {
                dependencyBanner.classList.add('hidden');
            }
        });
    }

    if (dependencyBannerDetails && dependencyDetailsModal && dependencyDetailsContent) {
        dependencyBannerDetails.addEventListener('click', () => {
            const report = lastDependencyReport || {};
            const required = report.required || {};
            const optional = report.optional || {};
            const missingRequired = report.missing_required || [];
            const missingOptional = report.missing_optional || [];
            const recommendations = report.recommendations || [];
            dependencyDetailsContent.textContent = [
                "Dependency Health Report",
                "------------------------",
                `Status: ${report.status || 'unknown'}`,
                "",
                `Missing required: ${missingRequired.length ? missingRequired.join(', ') : 'none'}`,
                `Missing optional: ${missingOptional.length ? missingOptional.join(', ') : 'none'}`,
                "",
                "Required modules:",
                JSON.stringify(required, null, 2),
                "",
                "Optional modules:",
                JSON.stringify(optional, null, 2),
                "",
                "Recovery guidance:",
                ...(recommendations.length
                    ? recommendations.map((item) => `- ${item}`)
                    : [
                        "- Install missing required modules first (app stability).",
                        "- Install optional modules to restore degraded features.",
                    ]),
            ].join('\n');
            dependencyDetailsModal.classList.remove('hidden');
        });
    }

    if (closeDependencyDetailsBtn && dependencyDetailsModal) {
        closeDependencyDetailsBtn.addEventListener('click', () => {
            dependencyDetailsModal.classList.add('hidden');
        });
    }

    if (copyDependencyDetailsBtn && dependencyDetailsContent) {
        copyDependencyDetailsBtn.addEventListener('click', async () => {
            const original = copyDependencyDetailsBtn.textContent;
            try {
                await navigator.clipboard.writeText(dependencyDetailsContent.textContent || '');
                copyDependencyDetailsBtn.textContent = 'Copied!';
                setTimeout(() => { copyDependencyDetailsBtn.textContent = original; }, 1200);
            } catch (error) {
                console.error("Failed to copy dependency diagnostics:", error);
                copyDependencyDetailsBtn.textContent = 'Copy failed';
                setTimeout(() => { copyDependencyDetailsBtn.textContent = original; }, 1200);
            }
        });
    }


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
    socket.on('proactive_notification', (notification) => {
        const title = notification?.title || 'Background task update';
        const message = notification?.message || 'A background task completed.';
        addMessage(`🔔 ${title}: ${message}`, 'assistant');
        refreshProactiveDashboard();
    });
    socket.on('proactive_task_update', () => {
        refreshProactiveDashboard();
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
                    upsertArtifactEntry({
                        artifact_id: data.filename,
                        artifact_type: inferArtifactType(data.filename),
                        last_updated_at: Date.now() / 1000,
                    });
                    updateArtifactState({
                        currentArtifactId: data.filename,
                        artifactType: inferArtifactType(data.filename),
                        artifactStatus: 'created',
                        previewAvailable: false,
                    });
                    updateLiveActivity({ stage: 'acting', action: `Created artifact: ${data.filename}` });
                    openFileCanvas(data.filename);
                    break;
                case 'plan_step_update':
                    const planStepContainer = currentAgentBubble.querySelector('.plan-step-container');
                    const planStepContent = planStepContainer.querySelector('.plan-step-content');
                    planStepContainer.style.display = 'block';
                    planStepContent.textContent = `${data.step_number}. ${data.step_description}`;
                    break;
                case 'progress_update':
                    markConversationRunState(currentConversationId, { isRunning: true, stage: data.stage });
                    updateProgressTimeline(currentAgentBubble, data);
                    updateLiveActivity({ stage: data.stage, action: data.label || null });
                    break;
                case 'activity_update':
                    updateLiveActivity({
                        stage: data.stage || 'analyzing',
                        focus: data.focus || null,
                        action: data.last_action || null,
                        activeTool: data.active_tool || null,
                    });
                    break;
                case 'assistant_chunk':
                    // This is the main event for streaming content
                    markConversationRunState(currentConversationId, { isRunning: true, stage: 'answering' });
                    updateLiveActivity({ stage: 'analyzing', action: 'Composing response…' });
                    currentResponseContent += data.content;
                    updateBotBubble(currentAgentBubble, currentResponseContent, false);
                    break;
                case 'response_mode':
                    currentResponseMode = data.mode || null;
                    updateResponseModeBadge(currentAgentBubble, currentResponseMode);
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
                    updateToolTimelineFromEvent('tool_call', data);
                    updateLiveActivity({
                        stage: 'tool_execution',
                        activeTool: data.name,
                        action: `Running ${String(data.name || 'tool').replace(/_/g, ' ')}…`,
                    });
                    break;
                case 'tool_result':
                    markConversationRunState(currentConversationId, { isRunning: true, stage: 'after_tool' });
                    updateAgentStatus(currentAgentBubble, `Tool finished. Analyzing results...`);
                    updateToolTimelineFromEvent('tool_result', data);
                    updateLiveActivity({ stage: 'analyzing', action: 'Analyzing tool results…', activeTool: null });
                    break;
                case 'tool_error':
                    markConversationRunState(currentConversationId, { isRunning: true, stage: 'tool_error', error: data.error });
                    updateAgentStatus(currentAgentBubble, `Tool Error: ${data.error}. Thinking...`, true);
                    updateToolTimelineFromEvent('tool_error', data);
                    updateLiveActivity({ stage: 'analyzing', action: 'Tool failed. Re-evaluating next step…', activeTool: null });
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
                    updateLiveActivity({ stage: 'finalizing', action: 'Finalizing answer…' });
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
                    updateLiveActivity({ stage: 'idle', action: 'Ready for your next request.', activeTool: null, resetTimer: true });
                    break;
                case 'agent_error':
                    if (data.error === 'Conversation not found.') {
                        clearConversationSessionState(currentConversationId);
                        startNewChat();
                        break;
                    }
                    markConversationRunState(currentConversationId, { isRunning: true, stage: 'error', error: data.error });
                    updateAgentStatus(currentAgentBubble, `An error occurred: ${data.error}`, true);
                    updateLiveActivity({ stage: 'error', action: `Issue: ${data.error}`, activeTool: null });
                    setAgentRunning(false);
                    break;
                case 'refresh_files':
                    if (data.conversation_id === currentConversationId) {
                        populateFileExplorer();
                    }
                    break;
                case 'file_updated': {
                    upsertArtifactEntry({
                        artifact_id: data.path,
                        artifact_type: inferArtifactType(data.path),
                        last_updated_at: Date.now() / 1000,
                    });
                    updateArtifactState({
                        currentArtifactId: data.path,
                        artifactType: inferArtifactType(data.path),
                        artifactStatus: 'updated',
                        previewAvailable: true,
                    });
                    updateLiveActivity({ stage: 'analyzing', action: `Updated artifact: ${data.path}` });
                    // Update content in tabs if open
                    const tabIndex = openTabs.findIndex(t => t.path === data.path);
                    if (tabIndex !== -1) {
                        openTabs[tabIndex].content = data.content;
                        // If it's the active tab and editor is initialized, update it
                        if (tabIndex === activeTabIndex && editor) {
                            if (editor.getValue() !== data.content) {
                                editor.setValue(data.content);
                            }
                            renderArtifactPreview(data.content, data.path);
                            if (artifactState.currentArtifactId === data.path) {
                                loadVersionsForArtifact(data.path).then(() => renderCanvasPanel());
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
    await loadDependencyHealthBanner();

    const savedConvoId = getSavedCurrentConversationId();
    if (savedConvoId) {
        // We'll let the socket 'load_conversation' event handle the full restore of messages
        // But we can eagerly load the tabs.
        currentConversationId = savedConvoId;
        await populateFileExplorer();
        await loadArtifactsForCurrentConversation();
        await loadTabState();
        socket.emit('load_conversation', { conversation_id: savedConvoId });
    } else {
        await populateFileExplorer();
        await loadArtifactsForCurrentConversation();
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

async function loadDependencyHealthBanner() {
    if (!dependencyBanner || !dependencyBannerText) return;
    try {
        const response = await fetch('/health/dependencies');
        if (!response.ok) return;
        const report = await response.json();
        lastDependencyReport = report;
        const missingRequired = report.missing_required || [];
        const missingOptional = report.missing_optional || [];

        if (!missingRequired.length && !missingOptional.length) {
            dependencyBanner.classList.add('hidden');
            dependencyBannerText.textContent = '';
            return;
        }

        if (dependencyBannerDismissedForSession) {
            dependencyBanner.classList.add('hidden');
            return;
        }

        const parts = [];
        if (missingRequired.length) {
            parts.push(`Missing required: ${missingRequired.join(', ')}`);
        }
        if (missingOptional.length) {
            parts.push(`Missing optional: ${missingOptional.join(', ')}`);
        }
        dependencyBannerText.textContent = `Dependency health warning — ${parts.join(' | ')}`;
        dependencyBanner.classList.remove('hidden');
    } catch (error) {
        console.error("Failed to load dependency health:", error);
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
        selectedResponseModePreference = settings.response_mode_preference || selectedResponseModePreference || 'auto';
        if (responseModeSelect) {
            responseModeSelect.value = selectedResponseModePreference;
        }
        thoughtPanelExpandedByDefault = !!settings.thought_panel_expanded;
        if (thoughtPanelDefaultToggle) {
            thoughtPanelDefaultToggle.checked = thoughtPanelExpandedByDefault;
        }

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

async function loadArtifactsForCurrentConversation() {
    if (!currentConversationId) {
        artifactList = [];
        artifactById = new Map();
        artifactVersions = [];
        selectedArtifactVersionId = null;
        return;
    }
    try {
        const response = await fetch(`${window.location.origin}${API_BASE}/conversation/${currentConversationId}/artifacts`);
        if (!response.ok) return;
        const data = await response.json();
        artifactList = sortArtifacts(data.artifacts || []);
        artifactById = new Map(artifactList.map((artifact) => [artifact.artifact_id, artifact]));
        if (data.last_active_artifact_id) {
            updateArtifactState({
                currentArtifactId: data.last_active_artifact_id,
                artifactType: inferArtifactType(data.last_active_artifact_id),
                artifactStatus: 'restored',
                previewAvailable: true,
            });
        }
    } catch (error) {
        console.warn('Failed to load artifacts', error);
    }
}

function computeSimpleLineDiff(currentContent = '', versionContent = '') {
    const currentLines = String(currentContent || '').split('\n');
    const versionLines = String(versionContent || '').split('\n');
    const maxLen = Math.max(currentLines.length, versionLines.length);
    const diffRows = [];
    for (let i = 0; i < maxLen; i += 1) {
        const before = versionLines[i] ?? '';
        const after = currentLines[i] ?? '';
        if (before === after) continue;
        diffRows.push(`- ${before}`);
        diffRows.push(`+ ${after}`);
        if (diffRows.length >= 80) break;
    }
    if (diffRows.length === 0) return 'No line differences.';
    return diffRows.join('\n');
}

async function loadVersionsForArtifact(artifactId) {
    if (!artifactId || !currentConversationId) {
        artifactVersions = [];
        selectedArtifactVersionId = null;
        return;
    }
    try {
        const response = await fetch(`${window.location.origin}${API_BASE}/artifact/${encodeURIComponent(artifactId)}/versions?conversation_id=${encodeURIComponent(currentConversationId)}`);
        if (!response.ok) {
            artifactVersions = [];
            selectedArtifactVersionId = null;
            return;
        }
        const data = await response.json();
        artifactVersions = data.versions || [];
    } catch (error) {
        artifactVersions = [];
        console.warn('Failed to load artifact versions', error);
    }
}

async function previewArtifactVersion(artifactId, versionId) {
    if (!artifactId || !versionId || !currentConversationId) return;
    try {
        const response = await fetch(`${window.location.origin}${API_BASE}/artifact/${encodeURIComponent(artifactId)}/version/${encodeURIComponent(versionId)}?conversation_id=${encodeURIComponent(currentConversationId)}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Failed to load version');
        selectedArtifactVersionId = versionId;
        const activeTab = openTabs[activeTabIndex];
        const currentContent = activeTab?.content || (editor ? editor.getValue() : '');
        const diff = computeSimpleLineDiff(currentContent, data.content || '');
        artifactPreviewVisible = true;
        renderCanvasPanel();
        const previewContainer = document.getElementById('artifact-preview');
        if (!previewContainer) return;
        previewContainer.innerHTML = `
            <div class="text-xs text-gray-300 mb-2">Version ${versionId} (${new Date(Number(data.timestamp) * 1000).toLocaleString()})</div>
            <pre class="text-xs text-gray-300 bg-gray-900 p-3 rounded overflow-auto h-full">${diff.replace(/[<>&]/g, (m) => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[m]))}</pre>
        `;
    } catch (error) {
        alert(`Error loading version preview: ${error.message}`);
    }
}

async function restoreArtifactVersion(artifactId, versionId) {
    if (!artifactId || !versionId || !currentConversationId) return;
    try {
        const response = await fetch(`${window.location.origin}${API_BASE}/artifact/${encodeURIComponent(artifactId)}/version/${encodeURIComponent(versionId)}/restore`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ conversation_id: currentConversationId }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Restore failed');
        await openFileCanvas(artifactId, { source: 'restore' });
        await loadVersionsForArtifact(artifactId);
        updateLiveActivity({ stage: 'acting', action: `Restored ${artifactId} to ${versionId}` });
        renderCanvasPanel();
    } catch (error) {
        alert(`Error restoring version: ${error.message}`);
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
            const artifactMeta = artifactStatusText();
            const workspaceRows = artifactList.length > 0
                ? artifactList.map((artifact) => {
                    const isActive = artifact.artifact_id === activeTab.path ? 'bg-blue-900 text-blue-100' : 'text-gray-300 hover:bg-gray-800';
                    const updated = artifact.last_updated_at
                        ? new Date(Number(artifact.last_updated_at) * 1000).toLocaleString()
                        : '—';
                    return `
                        <button class="workspace-artifact-item w-full text-left px-2 py-1 rounded ${isActive}" data-artifact-id="${artifact.artifact_id}">
                            <div class="truncate text-xs">${artifact.title || artifact.artifact_id}</div>
                            <div class="text-[10px] text-gray-400 truncate">${updated}</div>
                        </button>
                    `;
                }).join('')
                : '<div class="text-xs text-gray-500 px-2 py-3">No artifacts created yet</div>';
            const versionRows = artifactVersions.length > 0
                ? artifactVersions.map((version) => {
                    const isSelected = version.version_id === selectedArtifactVersionId ? 'bg-indigo-900 text-indigo-100' : 'text-gray-300 hover:bg-gray-800';
                    const summary = version.change_summary ? ` • ${version.change_summary}` : '';
                    return `
                        <div class="rounded ${isSelected} px-2 py-1">
                            <button class="workspace-version-item w-full text-left" data-version-id="${version.version_id}" data-artifact-id="${activeTab.path}">
                                <div class="text-[10px] truncate">${new Date(Number(version.timestamp) * 1000).toLocaleString()}${summary}</div>
                            </button>
                            <div class="flex gap-1 mt-1">
                                <button class="version-preview-btn text-[10px] border border-gray-700 rounded px-1 py-0.5" data-version-id="${version.version_id}" data-artifact-id="${activeTab.path}">Preview</button>
                                <button class="version-restore-btn text-[10px] border border-gray-700 rounded px-1 py-0.5" data-version-id="${version.version_id}" data-artifact-id="${activeTab.path}">Restore</button>
                            </div>
                        </div>
                    `;
                }).join('')
                : '<div class="text-xs text-gray-500 px-2 py-2">No previous versions yet</div>';

            canvasPanel.innerHTML = `
                ${tabsHtml}
                <div class="canvas-header">
                    <div class="flex-1 min-w-0">
                        <h3 class="canvas-header-title text-sm" title="${activeTab.path}">${activeTab.path}</h3>
                        <div class="text-xs text-gray-400 mt-1">${artifactMeta}</div>
                    </div>
                    <div class="canvas-header-buttons">
                        <button id="canvas-preview-btn">${artifactPreviewVisible ? 'Editor' : 'Preview'}</button>
                        <button id="canvas-copy-btn">Copy</button>
                        <button id="canvas-save-btn">Save</button>
                        <button id="canvas-close-btn">Close Panel</button>
                    </div>
                </div>
                <div class="px-2 pb-2 sm:hidden">
                    <button id="workspace-mobile-toggle" class="text-xs border border-gray-700 rounded px-2 py-1 text-gray-300">${workspacePanelCollapsedMobile ? 'Show Workspace' : 'Hide Workspace'}</button>
                </div>
                <div class="flex-1 min-h-0 flex">
                    <aside id="workspace-panel" class="w-56 border-r border-gray-800 overflow-y-auto ${workspacePanelCollapsedMobile ? 'hidden sm:block' : 'block'}">
                        <div class="px-2 py-2 text-xs uppercase tracking-wide text-gray-400">Workspace</div>
                        <div class="space-y-1 px-1 pb-2">${workspaceRows}</div>
                        <div class="px-2 py-2 text-xs uppercase tracking-wide text-gray-400 border-t border-gray-800">Versions</div>
                        <div class="space-y-1 px-1 pb-2">${versionRows}</div>
                    </aside>
                    <div class="flex-1 min-w-0 flex">
                        <div id="file-viewer" class="flex-1 ${artifactPreviewVisible ? 'hidden' : ''}"></div>
                        <div id="artifact-preview" class="flex-1 p-2 ${artifactPreviewVisible ? '' : 'hidden'}"></div>
                    </div>
                </div>
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
                         const nextTab = openTabs[activeTabIndex];
                         updateArtifactState({
                             currentArtifactId: nextTab.path,
                             artifactType: inferArtifactType(nextTab.path),
                             artifactStatus: 'focused',
                             previewAvailable: true,
                         });
                         persistLastActiveArtifact(nextTab.path);
                         loadVersionsForArtifact(nextTab.path).then(() => {
                             if (openTabs[activeTabIndex] && openTabs[activeTabIndex].path === nextTab.path) {
                                 renderCanvasPanel();
                             }
                         });
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
            document.getElementById('canvas-preview-btn').addEventListener('click', () => {
                artifactPreviewVisible = !artifactPreviewVisible;
                renderCanvasPanel();
            });
            const workspaceToggleBtn = document.getElementById('workspace-mobile-toggle');
            if (workspaceToggleBtn) {
                workspaceToggleBtn.addEventListener('click', () => {
                    workspacePanelCollapsedMobile = !workspacePanelCollapsedMobile;
                    renderCanvasPanel();
                });
            }
            document.querySelectorAll('.workspace-artifact-item').forEach((item) => {
                item.addEventListener('click', async () => {
                    const artifactId = item.dataset.artifactId;
                    await openFileCanvas(artifactId, { source: 'workspace' });
                });
            });
            document.querySelectorAll('.version-preview-btn').forEach((btn) => {
                btn.addEventListener('click', async (event) => {
                    event.stopPropagation();
                    await previewArtifactVersion(btn.dataset.artifactId, btn.dataset.versionId);
                });
            });
            document.querySelectorAll('.version-restore-btn').forEach((btn) => {
                btn.addEventListener('click', async (event) => {
                    event.stopPropagation();
                    await restoreArtifactVersion(btn.dataset.artifactId, btn.dataset.versionId);
                });
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
                        updateArtifactState({
                            currentArtifactId: activeTab.path,
                            artifactType: inferArtifactType(activeTab.path),
                            artifactStatus: 'updated',
                            previewAvailable: true,
                        });
                        upsertArtifactEntry({
                            artifact_id: activeTab.path,
                            artifact_type: inferArtifactType(activeTab.path),
                            last_updated_at: Date.now() / 1000,
                        });
                        setTimeout(() => { saveBtn.textContent = 'Save'; }, 2000);
                    } catch (error) {
                        alert(`Error saving file: ${error.message}`);
                        saveBtn.textContent = 'Save';
                    }
                }
            });

            document.getElementById('canvas-close-btn').addEventListener('click', hideCanvasPanel);

            initializeEditor(activeTab.content, activeTab.mode);
            renderArtifactPreview(activeTab.content, activeTab.path);
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

        async function persistLastActiveArtifact(artifactId) {
            if (!currentConversationId || !artifactId) return;
            try {
                await fetch(`${window.location.origin}${API_BASE}/conversation/${currentConversationId}/artifacts`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ artifact_id: artifactId }),
                });
            } catch (error) {
                console.warn('Unable to persist active artifact', error);
            }
        }

        async function openFileCanvas(path, options = {}) {
            const existingIndex = openTabs.findIndex(t => t.path === path);
            if (existingIndex !== -1) {
                activeTabIndex = existingIndex;
                updateArtifactState({
                    currentArtifactId: path,
                    artifactType: inferArtifactType(path),
                    artifactStatus: 'focused',
                    previewAvailable: true,
                });
                await persistLastActiveArtifact(path);
                await loadVersionsForArtifact(path);
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
                updateArtifactState({
                    currentArtifactId: path,
                    artifactType: inferArtifactType(path),
                    artifactStatus: options.source === 'timeline' ? 'opened_from_timeline' : 'opened',
                    previewAvailable: true,
                });
                upsertArtifactEntry({ artifact_id: path, artifact_type: inferArtifactType(path) });
                await persistLastActiveArtifact(path);
                await loadVersionsForArtifact(path);

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
    resetToolTimeline();
    updateLiveActivity({
        stage: 'planning',
        action: 'Planning next step…',
        focus: text || 'Working on your latest request.',
        activeTool: null,
        resetTimer: true,
    });

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
    currentResponseMode = null;
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
        agent_mode: agentMode,
        response_mode_preference: selectedResponseModePreference
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
                            <svg class="w-4 h-4 mr-2 thought-toggle-icon transition-transform duration-150" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 9l4-4 4 4m0 6l-4 4-4-4"></path></svg>
                            <span class="flex-1">Thought process</span>
                            <span class="thinking-meta text-xs text-gray-400">Hidden</span>
                        </div>
                        <div class="thinking-content prose prose-invert max-w-none" style="display: none;"></div>
                    </div>
            <div class="plan-step-container" style="display: none;">
                <div class="plan-step-header">
                    <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"></path></svg>
                    <span>Current Step</span>
                </div>
                <div class="plan-step-content"></div>
            </div>
            <div class="progress-timeline-container" style="display: none;">
                <button type="button" class="progress-timeline-header w-full text-left text-xs text-gray-300 mb-1 font-semibold flex items-center">
                    <svg class="w-4 h-4 mr-2 progress-toggle-icon transition-transform duration-150" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 9l4-4 4 4m0 6l-4 4-4-4"></path></svg>
                    <span class="flex-1">Progress</span>
                    <span class="progress-meta text-xs text-gray-400">0 steps</span>
                </button>
                <ul class="progress-timeline text-xs text-gray-400 space-y-1" style="display: none;"></ul>
            </div>
            <div class="agent-status">
                <div class="thinking-indicator">
                    <span></span><span></span><span></span>
                </div>
            </div>
            <div class="response-mode-badge text-xs text-gray-400 mt-1 hidden"></div>
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
            const thoughtToggleIcon = botMessageWrapper.querySelector('.thought-toggle-icon');
            const thinkingMeta = botMessageWrapper.querySelector('.thinking-meta');
            thinkingContent.style.display = thoughtPanelExpandedByDefault ? 'block' : 'none';
            thoughtToggleIcon?.classList.toggle('rotate-180', thoughtPanelExpandedByDefault);
            if (thinkingMeta) thinkingMeta.textContent = thoughtPanelExpandedByDefault ? 'Visible' : 'Hidden';
            thinkingHeader.addEventListener('click', () => {
                const expanded = thinkingContent.style.display !== 'none';
                thinkingContent.style.display = expanded ? 'none' : 'block';
                thoughtToggleIcon?.classList.toggle('rotate-180', !expanded);
                if (thinkingMeta) thinkingMeta.textContent = expanded ? 'Hidden' : 'Visible';
            });
            const progressHeader = botMessageWrapper.querySelector('.progress-timeline-header');
            const progressTimeline = botMessageWrapper.querySelector('.progress-timeline');
            const progressToggleIcon = botMessageWrapper.querySelector('.progress-toggle-icon');
            progressHeader?.addEventListener('click', () => {
                const expanded = progressTimeline.style.display !== 'none';
                progressTimeline.style.display = expanded ? 'none' : 'block';
                progressToggleIcon?.classList.toggle('rotate-180', !expanded);
            });

    smartScroll(chatContainer);
    return botMessageWrapper;
}

function updateResponseModeBadge(bubbleElement, mode) {
    if (!bubbleElement) return;
    const badge = bubbleElement.querySelector('.response-mode-badge');
    if (!badge) return;

    if (!mode) {
        badge.classList.add('hidden');
        badge.textContent = '';
        return;
    }

    const normalized = String(mode).toLowerCase();
    const label = normalized.charAt(0).toUpperCase() + normalized.slice(1);
    badge.textContent = `Response mode: ${label}`;
    badge.classList.remove('hidden');
}

function updateProgressTimeline(bubbleElement, progressEvent) {
    if (!bubbleElement || !progressEvent) return;
    const container = bubbleElement.querySelector('.progress-timeline-container');
    const timeline = bubbleElement.querySelector('.progress-timeline');
    if (!container || !timeline) return;

    container.style.display = 'block';
    const label = progressEvent.label || progressEvent.stage || 'Working';
    const stage = String(progressEvent.stage || '').toLowerCase();
    const stageMarker = {
        planning: '🧭',
        executing: '⚙️',
        verifying: '🧪',
        finalizing: '✅',
    }[stage] || '•';
    const nextText = `${stageMarker} ${label}`;
    const lastItem = timeline.lastElementChild;
    if (lastItem && lastItem.textContent === nextText) {
        return;
    }

    const item = document.createElement('li');
    item.textContent = nextText;
    item.className = {
        planning: 'text-blue-300',
        executing: 'text-yellow-300',
        verifying: 'text-purple-300',
        finalizing: 'text-green-300',
    }[stage] || 'text-gray-400';
    timeline.appendChild(item);
    const progressMeta = bubbleElement.querySelector('.progress-meta');
    if (progressMeta) {
        const count = timeline.children.length;
        progressMeta.textContent = `${count} step${count === 1 ? '' : 's'}`;
    }

    const maxItems = 8;
    while (timeline.children.length > maxItems) {
        timeline.removeChild(timeline.firstChild);
    }
}

function inferActivityStage(stage, fallback = 'analyzing') {
    const normalized = String(stage || '').toLowerCase();
    if (['planning'].includes(normalized)) return 'planning';
    if (['executing', 'tool_call'].includes(normalized)) return 'acting';
    if (['tool_execution', 'after_tool', 'tool_error'].includes(normalized)) return 'tool_execution';
    if (['verifying', 'thinking', 'answering', 'analyzing'].includes(normalized)) return 'analyzing';
    if (['finalizing', 'final_answer', 'done'].includes(normalized)) return 'finalizing';
    if (['idle', 'error'].includes(normalized)) return normalized;
    return fallback;
}

function formatActivityStatus(stage, action, activeTool) {
    const toolLabel = activeTool ? ` (${activeTool})` : '';
    const labels = {
        planning: 'Planning next step…',
        acting: 'Preparing action…',
        tool_execution: `Running tool${toolLabel}…`,
        analyzing: 'Analyzing results…',
        finalizing: 'Finalizing answer…',
        error: 'Paused due to an issue.',
        idle: 'Idle',
    };
    return action || labels[stage] || 'Working…';
}

function updateLiveActivity({ stage, focus, action, activeTool, resetTimer = false }) {
    const nextStage = inferActivityStage(stage, liveActivityState.currentStage);
    if (resetTimer || !liveActivityState.startedAt) {
        liveActivityState.startedAt = Date.now();
    }
    if (focus) liveActivityState.currentFocus = focus;
    if (action) liveActivityState.lastAction = action;
    if (activeTool !== undefined) liveActivityState.activeTool = activeTool;
    liveActivityState.currentStage = nextStage;

    const status = formatActivityStatus(nextStage, action, liveActivityState.activeTool);
    if (liveActivityText) liveActivityText.textContent = status;
    if (activityStageText) activityStageText.textContent = nextStage;
    if (activityFocusText) activityFocusText.textContent = liveActivityState.currentFocus || '—';
    if (activityActionText) activityActionText.textContent = liveActivityState.lastAction || status;
    if (liveActivityBar) {
        liveActivityBar.classList.toggle('opacity-80', nextStage === 'idle');
    }
}

function resetToolTimeline() {
    toolTimelineEntries = [];
    toolTimelineByCallId = new Map();
    if (toolTimelineList) {
        toolTimelineList.innerHTML = '';
        toolTimelineList.dataset.open = 'false';
    }
}

function formatTimelineSummary(toolName, status, payload) {
    const readableName = String(toolName || 'Tool').replace(/_/g, ' ');
    if (payload && typeof payload === 'object' && payload.path) {
        return `${readableName}: ${payload.path}`;
    }
    if (status === 'error') return `${readableName} failed`;
    if (status === 'partial') return `${readableName} completed with warnings`;
    return `${readableName} completed`;
}

function shouldSuppressTimelineNoise(entry) {
    const summary = entry.short_summary || '';
    const isLowValue = /redundant_call_same_context|loop_guard_non_retryable_repeat/.test(summary) || entry.usefulness_hint === 'low_signal_empty_result';
    const last = toolTimelineEntries[toolTimelineEntries.length - 1];
    if (!last) return false;
    if (isLowValue && last.short_summary === summary && last.status === entry.status) {
        return true;
    }
    return false;
}

function renderToolTimeline() {
    if (!toolTimelineList) return;
    toolTimelineList.innerHTML = '';
    toolTimelineEntries.forEach((entry, index) => {
        const li = document.createElement('li');
        li.className = 'tool-step text-xs text-gray-300';
        const icon = entry.status === 'success' ? '✅' : entry.status === 'partial' ? '⚠️' : '❌';
        li.innerHTML = `<div>${icon} ${entry.short_summary} <span class="text-gray-500">${entry.timestamp}</span></div>`;
        const detail = document.createElement('div');
        detail.className = 'tool-step-details';
        detail.dataset.open = 'false';
        const detailLines = [];
        if (entry.params_preview) detailLines.push(`Params: ${entry.params_preview}`);
        if (entry.result_preview) detailLines.push(`Result: ${entry.result_preview}`);
        if (entry.error_message) detailLines.push(`Error: ${entry.error_message}`);
        if (entry.retryable !== undefined && entry.retryable !== null) detailLines.push(`Retryable: ${entry.retryable}`);
        if (entry.usefulness_hint) detailLines.push(`Usefulness: ${entry.usefulness_hint}`);
        detail.textContent = detailLines.join('\n');
        li.appendChild(detail);
        li.addEventListener('click', () => {
            const open = detail.dataset.open === 'true';
            detail.dataset.open = open ? 'false' : 'true';
            if (entry.artifact_path) {
                openFileCanvas(entry.artifact_path, { source: 'timeline' });
            }
        });
        toolTimelineList.appendChild(li);
    });
}

function updateToolTimelineFromEvent(type, data) {
    if (!data) return;
    if (type === 'tool_call') {
        const entry = {
            tool_name: data.name,
            status: 'partial',
            short_summary: formatTimelineSummary(data.name, 'partial', null),
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
            params_preview: JSON.stringify(data.params || {}),
            result_preview: null,
            error_message: null,
            retryable: null,
            usefulness_hint: null,
            artifact_path: data.params?.path || data.params?.filename || null,
        };
        toolTimelineByCallId.set(data.tool_call_id, entry);
        if (!shouldSuppressTimelineNoise(entry)) {
            toolTimelineEntries.push(entry);
            renderToolTimeline();
        }
        return;
    }

    if (type === 'tool_result' || type === 'tool_error') {
        const existing = toolTimelineByCallId.get(data.tool_call_id) || {
            tool_name: data.name || 'tool',
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        };
        const meta = data.meta || {};
        const status = type === 'tool_result' ? 'success' : 'error';
        existing.status = status;
        existing.short_summary = formatTimelineSummary(existing.tool_name || meta.tool_name, status, data.result || meta.result);
        existing.result_preview = data.result ? JSON.stringify(data.result).slice(0, 180) : null;
        existing.error_message = type === 'tool_error' ? (meta.error_message || data.error || '').slice(0, 180) : null;
        existing.retryable = meta.retryable;
        existing.usefulness_hint = meta.usefulness_hint || null;
        existing.artifact_path = existing.artifact_path || data.result?.path || data.result?.filename || meta.result?.path || meta.result?.filename || null;
        if (shouldSuppressTimelineNoise(existing)) {
            return;
        }
        if (!toolTimelineEntries.includes(existing)) {
            toolTimelineEntries.push(existing);
        }
        renderToolTimeline();
    }
}

function inferArtifactType(path = '') {
    const lower = String(path).toLowerCase();
    if (lower.endsWith('.md') || lower.endsWith('.markdown')) return 'markdown';
    if (lower.endsWith('.html') || lower.endsWith('.htm')) return 'html';
    if (/\.(py|js|ts|tsx|jsx|css|json|sql|sh|txt|yml|yaml|xml)$/.test(lower)) return 'code';
    return 'unknown';
}

function updateArtifactState(partial) {
    artifactState = {
        ...artifactState,
        ...partial,
        lastUpdatedAt: partial.lastUpdatedAt || new Date().toISOString(),
    };
}

function artifactStatusText() {
    const status = artifactState.artifactStatus || 'idle';
    const type = artifactState.artifactType || 'unknown';
    const updated = artifactState.lastUpdatedAt ? new Date(artifactState.lastUpdatedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—';
    const preview = artifactState.previewAvailable ? 'preview ready' : 'preview unavailable';
    return `${type} • ${status} • ${preview} • updated ${updated}`;
}

function renderArtifactPreview(content, path) {
    const previewContainer = document.getElementById('artifact-preview');
    if (!previewContainer) return;
    const type = inferArtifactType(path);
    previewContainer.innerHTML = '';
    try {
        if (type === 'markdown') {
            previewContainer.innerHTML = marked.parse(content || '');
            updateArtifactState({ artifactType: type, artifactStatus: 'preview_ready', previewAvailable: true });
            return;
        }
        if (type === 'html') {
            const iframe = document.createElement('iframe');
            iframe.className = 'w-full h-full border border-gray-700 rounded';
            iframe.setAttribute('sandbox', 'allow-same-origin');
            iframe.srcdoc = content || '';
            previewContainer.appendChild(iframe);
            updateArtifactState({ artifactType: type, artifactStatus: 'preview_ready', previewAvailable: true });
            return;
        }

        const pre = document.createElement('pre');
        pre.className = 'text-xs text-gray-300 bg-gray-900 p-3 rounded overflow-auto h-full';
        pre.textContent = content || '';
        previewContainer.appendChild(pre);
        updateArtifactState({ artifactType: type, artifactStatus: 'preview_ready', previewAvailable: true });
    } catch (error) {
        const fallback = document.createElement('div');
        fallback.className = 'text-xs text-yellow-300';
        fallback.textContent = 'Preview unavailable, file saved successfully.';
        previewContainer.appendChild(fallback);
        updateArtifactState({ artifactType: type, artifactStatus: 'preview_failed', previewAvailable: false });
    }
}

function updateBotBubble(bubbleElement, responseContent, isFinal = false) {
    if (!bubbleElement) return;

    const thinkingContainer = bubbleElement.querySelector('.thinking-process-container');
    const thinkingContentEl = thinkingContainer.querySelector('.thinking-content');
    const answerContent = bubbleElement.querySelector('.answer-content');
    const agentStatus = bubbleElement.querySelector('.agent-status');
    const toolActivity = bubbleElement.querySelector('.tool-activity');

    // Extract thought content
    const thinkStart = responseContent.indexOf('<think>');
    const thinkEnd = thinkStart >= 0 ? responseContent.indexOf('</think>', thinkStart + 7) : -1;
    let thinkContent = null;
    if (thinkStart >= 0) {
        thinkContent = thinkEnd >= 0
            ? responseContent.slice(thinkStart + 7, thinkEnd)
            : responseContent.slice(thinkStart + 7);
    }

    // Extract conversational content (everything outside think and tool blocks)
    const conversationalContent = responseContent
        .replace(/<think>[\s\S]*?<\/think>/g, '')
        .replace(/<think>[\s\S]*$/g, '')
        .replace(/```json\s*([\s\S]*?)\s*```/g, '')
        .trim();

    if (thinkContent) {
        thinkingContainer.style.display = 'block';
        thinkingContentEl.innerHTML = marked.parse(thinkContent);
        const thinkingMeta = bubbleElement.querySelector('.thinking-meta');
        if (thinkingMeta) {
            const lineCount = thinkContent.split('\n').filter(Boolean).length;
            thinkingMeta.textContent = isFinal ? `${lineCount} line${lineCount === 1 ? '' : 's'}` : 'Streaming...';
        }
        smartScroll(thinkingContentEl);
    } else {
        // Hide it only if we are in a final state, otherwise it might just not have arrived yet
        if (isFinal) {
            thinkingContainer.style.display = 'none';
            const thinkingContent = bubbleElement.querySelector('.thinking-content');
            const thoughtToggleIcon = bubbleElement.querySelector('.thought-toggle-icon');
            const thinkingMeta = bubbleElement.querySelector('.thinking-meta');
            if (thinkingContent) {
                const shouldExpand = thoughtPanelExpandedByDefault;
                thinkingContent.style.display = shouldExpand ? 'block' : 'none';
                thoughtToggleIcon?.classList.toggle('rotate-180', shouldExpand);
                if (thinkingMeta && !thinkContent) {
                    thinkingMeta.textContent = shouldExpand ? 'Visible' : 'Hidden';
                }
            }
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
        const progressTimeline = bubbleElement.querySelector('.progress-timeline');
        const progressToggleIcon = bubbleElement.querySelector('.progress-toggle-icon');
        if (progressTimeline) {
            progressTimeline.style.display = 'none';
            progressToggleIcon?.classList.remove('rotate-180');
        }
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
         artifactList = [];
         artifactById = new Map();
         artifactVersions = [];
         selectedArtifactVersionId = null;
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
    artifactList = sortArtifacts(data.artifacts || []);
    artifactById = new Map(artifactList.map((artifact) => [artifact.artifact_id, artifact]));
    if (data.last_active_artifact_id) {
        updateArtifactState({
            currentArtifactId: data.last_active_artifact_id,
            artifactType: inferArtifactType(data.last_active_artifact_id),
            artifactStatus: 'restored',
            previewAvailable: true,
        });
    }
    if (data.last_active_artifact_id) {
        loadVersionsForArtifact(data.last_active_artifact_id);
    }
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
    if (!data.artifacts) {
        loadArtifactsForCurrentConversation();
    }
    if (data.last_active_artifact_id && openTabs.length === 0) {
        openFileCanvas(data.last_active_artifact_id, { source: 'restore' });
    }
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
    artifactList = [];
    artifactById = new Map();
    artifactVersions = [];
    selectedArtifactVersionId = null;
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
