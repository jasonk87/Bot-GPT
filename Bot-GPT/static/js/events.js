import { updateActiveBubble, updateBotBubble } from './ui.js';
import { setAgentRunning } from './ui.js';

export function setupEventSource(eventSource) {
    eventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);
        switch(data.type) {
            case 'agent_start':
                updateActiveBubble(data.agent, 'Thinking... <span class="dots"><span>.</span><span>.</span><span>.</span></span>');
                break;
            case 'agent_thought':
                updateActiveBubble(data.agent, `<em>"${data.thought}"</em>`);
                break;
            case 'agent_tool_start':
                updateActiveBubble(data.agent, `<strong>Using tool:</strong> \`${data.tool}\``);
                break;
            case 'agent_end':
                updateActiveBubble('Project Manager', 'Processing results...');
                break;
            case 'final_answer':
                const currentAgentBubble = document.querySelector('.newly-added:last-child');
                updateBotBubble(currentAgentBubble, data.content, true);
                setAgentRunning(false);
                eventSource.close();
                break;
        }
    };

    eventSource.onerror = function() {
        updateActiveBubble('Error', 'Connection failed. Please refresh.');
        setAgentRunning(false);
        eventSource.close();
    };
}
