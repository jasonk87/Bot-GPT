import { checkAuth, setupAuth } from './auth.js';
import { startChatEventSource } from './api.js';
import { setupEventSource } from './events.js';
import { appendMessage, createBotMessageContainer, setAgentRunning } from './ui.js';

let conversationHistory = [];
let isAgentRunning = false;
let eventSource = null;

document.addEventListener('DOMContentLoaded', () => {
    checkAuth(initializeApp);
});

function initializeApp(username) {
    setupAuth(initializeApp);
    
    document.getElementById('welcome-user').textContent = `Welcome, ${username}!`;
    
    const sendButton = document.getElementById('send-button');
    const chatInput = document.getElementById('chat-input');
    const newChatBtn = document.getElementById('new-chat-btn');

    sendButton.addEventListener('click', () => sendMessage());
    chatInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            sendMessage();
        }
    });
    newChatBtn.addEventListener('click', startNewChat);
}

function sendMessage() {
    const chatInput = document.getElementById('chat-input');
    const text = chatInput.value.trim();
    if (!text || isAgentRunning) return;

    setAgentRunning(true);
    
    const userMessage = { role: 'user', content: text };
    appendMessage(text, 'user');
    conversationHistory.push(userMessage);
    
    chatInput.value = '';
    chatInput.style.height = 'auto';

    createBotMessageContainer();
    
    eventSource = startChatEventSource(userMessage);
    setupEventSource(eventSource, (isRunning) => {
        setAgentRunning(isRunning);
    });
}

function startNewChat() {
    if (isAgentRunning) return;
    conversationHistory = [];
    document.getElementById('chat-container').innerHTML = '';
    const welcomeMessage = document.getElementById('welcome-message');
    if(welcomeMessage) welcomeMessage.style.display = 'block';
}
