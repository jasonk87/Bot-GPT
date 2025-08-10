import { marked } from 'https://cdn.jsdelivr.net/npm/marked/marked.min.js';

let currentAgentBubble = null;

export function getAgentIcon(agentName) {
    const icons = {
        'coder': `<svg class="w-full h-full" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l-4 4-4-4 4-4"></path></svg>`,
        'project manager': `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-full h-full"><path d="M12 2a2 2 0 0 0-2 2v2h4V4a2 2 0 0 0-2-2zM6 8v10c0 1.1.9 2 2 2h8a2 2 0 0 0 2-2V8H6zM4 8c-1.1 0-2 .9-2 2v8a2 2 0 0 0 2 2h2v-2H4V10h2V8H4zm16 0h-2v2h2v8h-2v2h2a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2zM9 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0zm6 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0z" /></svg>`
    };
    const lowerAgentName = agentName.toLowerCase();
    for (const key in icons) {
        if (lowerAgentName.includes(key)) return icons[key];
    }
    return icons['project manager'];
}

export function createBotMessageContainer() {
    const chatContainer = document.getElementById('chat-container');
    const botMessageWrapper = document.createElement('div');
    botMessageWrapper.className = 'flex max-w-3xl w-full items-start self-start mx-auto newly-added';
    botMessageWrapper.innerHTML = `
        <div class="agent-icon-container w-8 h-8 flex-shrink-0 mr-2 text-gray-400"></div>
        <div class="flex-1 bot-bubble">
            <div class="agent-status-container p-2"></div>
            <div class="answer-content prose prose-invert max-w-none" style="display: none;"></div>
        </div>`;
    chatContainer.appendChild(botMessageWrapper);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    currentAgentBubble = botMessageWrapper;
    return botMessageWrapper;
}

export function updateActiveBubble(agentName, statusHTML) {
    if (!currentAgentBubble) return;
    const iconContainer = currentAgentBubble.querySelector('.agent-icon-container');
    const statusContainer = currentAgentBubble.querySelector('.agent-status-container');
    const agentDisplayName = agentName.replace('ask_', '').replace(/_/g, ' ');

    iconContainer.innerHTML = getAgentIcon(agentDisplayName);
    statusContainer.innerHTML = `<strong>${agentDisplayName}:</strong> ${statusHTML}`;
    statusContainer.style.display = 'block';

    const answerContent = currentAgentBubble.querySelector('.answer-content');
    if (answerContent) answerContent.style.display = 'none';
}

export function updateBotBubble(bubbleElement, responseContent, isFinal = false) {
    if (!bubbleElement) return;
    const statusContainer = bubbleElement.querySelector('.agent-status-container');
    const answerContent = bubbleElement.querySelector('.answer-content');

    if (statusContainer) statusContainer.style.display = 'none';
    if (answerContent) {
        answerContent.style.display = 'block';
        answerContent.innerHTML = marked.parse(responseContent);
    }

    if (isFinal) {
        const iconContainer = bubbleElement.querySelector('.agent-icon-container');
        if (iconContainer) iconContainer.innerHTML = getAgentIcon('Project Manager');
    }
}

export function appendMessage(text, sender) {
    const chatContainer = document.getElementById('chat-container');
    const messageWrapper = document.createElement('div');
    messageWrapper.className = `flex max-w-3xl w-full items-start self-${sender === 'user' ? 'end' : 'start'} mx-auto newly-added`;
    if (sender === 'user') {
        messageWrapper.innerHTML = `
            <div class="flex-1 user-bubble"><div class="text-white max-w-none">${marked.parse(text)}</div></div>
            <div class="w-8 h-8 flex-shrink-0 ml-2 text-blue-300"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-full h-full"><path fill-rule="evenodd" d="M7.5 6a4.5 4.5 0 119 0 4.5 4.5 0 01-9 0zM3.751 20.105a8.25 8.25 0 0116.498 0 .75.75 0 01-.437.695A18.683 18.683 0 0112 22.5c-2.786 0-5.433-.608-7.812-1.7a.75.75 0 01-.437-.695z" clip-rule="evenodd" /></svg></div>`;
    }
    chatContainer.appendChild(messageWrapper);
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

export function setAgentRunning(isRunning) {
    const chatInput = document.getElementById('chat-input');
    const sendButton = document.getElementById('send-button');
    chatInput.disabled = isRunning;
    sendButton.disabled = isRunning;
    if (isRunning) {
        sendButton.innerHTML = `<svg class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>`;
    } else {
        sendButton.innerHTML = `<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14M12 5l7 7-7 7"></path></svg>`;
    }
}

export function isScrolledToBottom(el) {
    const threshold = 5;
    return el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
}
