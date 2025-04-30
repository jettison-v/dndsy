/**
 * mobile-chat.js
 * Handles chat interactions for the mobile version of the AskDND app
 */

document.addEventListener('DOMContentLoaded', () => {
    // UI elements
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');
    const chatMessages = document.getElementById('chat-messages');
    const vectorStoreDropdown = document.getElementById('vector-store-dropdown');
    const llmModelDropdown = document.getElementById('llm-model-dropdown');
    
    // State tracking
    let isWaitingForResponse = false;
    let currentStreamedMessage = null;
    
    // Initialize event listeners
    if (userInput && sendButton) {
        sendButton.addEventListener('click', handleSendMessage);
        
        // Send message on Enter (but allow Shift+Enter for new lines)
        userInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                handleSendMessage();
            }
        });
        
        // Auto-resize textarea as user types
        userInput.addEventListener('input', autoResizeTextarea);
    }
    
    // Handle vector store change
    if (vectorStoreDropdown) {
        vectorStoreDropdown.addEventListener('change', () => {
            // Store the selection in local storage
            localStorage.setItem('preferred_vector_store', vectorStoreDropdown.value);
        });
        
        // Load stored preference if available
        const storedVectorStore = localStorage.getItem('preferred_vector_store');
        if (storedVectorStore && [...vectorStoreDropdown.options].some(opt => opt.value === storedVectorStore)) {
            vectorStoreDropdown.value = storedVectorStore;
        }
    }
    
    // Handle LLM model change
    if (llmModelDropdown) {
        llmModelDropdown.addEventListener('change', () => {
            // Make API call to change the model
            changeModel(llmModelDropdown.value);
            
            // Store the selection in local storage
            localStorage.setItem('preferred_llm_model', llmModelDropdown.value);
        });
        
        // Load stored preference if available
        const storedLlmModel = localStorage.getItem('preferred_llm_model');
        if (storedLlmModel && [...llmModelDropdown.options].some(opt => opt.value === storedLlmModel)) {
            // If stored model is different from current selection, change it
            if (llmModelDropdown.value !== storedLlmModel) {
                llmModelDropdown.value = storedLlmModel;
                changeModel(storedLlmModel);
            }
        }
    }
    
    /**
     * Handle sending a chat message
     */
    function handleSendMessage() {
        if (isWaitingForResponse || !userInput || !userInput.value.trim()) {
            return;
        }
        
        const message = userInput.value.trim();
        addUserMessage(message);
        userInput.value = '';
        autoResizeTextarea();
        
        // Begin AI response
        fetchAIResponse(message);
    }
    
    /**
     * Auto-resize the textarea based on content
     */
    function autoResizeTextarea() {
        if (!userInput) return;
        
        // Reset height to auto to get accurate scrollHeight
        userInput.style.height = 'auto';
        
        // Set new height based on scrollHeight, with a maximum
        const newHeight = Math.min(userInput.scrollHeight, 100);
        userInput.style.height = `${newHeight}px`;
    }
    
    /**
     * Add a user message to the chat
     * @param {string} message User's message text
     */
    function addUserMessage(message) {
        if (!chatMessages) return;
        
        // Create message element
        const messageElement = document.createElement('div');
        messageElement.className = 'message user';
        messageElement.innerHTML = `<div class="message-text">${formatMessageText(message)}</div>`;
        
        // Add to chat and scroll to bottom
        chatMessages.appendChild(messageElement);
        scrollToBottom();
    }
    
    /**
     * Add the AI's response to the chat
     * @param {string} message AI's message text
     */
    function addAIMessage(message) {
        if (!chatMessages) return;
        
        // Create message element
        const messageElement = document.createElement('div');
        messageElement.className = 'message assistant';
        messageElement.innerHTML = `<div class="message-text">${formatMessageText(message)}</div>`;
        
        // Add to chat and scroll to bottom
        chatMessages.appendChild(messageElement);
        scrollToBottom();
        
        return messageElement;
    }
    
    /**
     * Format message text with markdown rendering
     * @param {string} text Raw message text
     * @returns {string} Formatted HTML
     */
    function formatMessageText(text) {
        // Simple markdown handling
        return text
            .replace(/\n/g, '<br>') // Line breaks
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>') // Bold
            .replace(/\*(.*?)\*/g, '<em>$1</em>'); // Italic
    }
    
    /**
     * Create a loading message with animated dots
     * @returns {HTMLElement} The loading message element
     */
    function createLoadingMessage() {
        const loadingElement = document.createElement('div');
        loadingElement.className = 'message assistant';
        loadingElement.innerHTML = `
            <div class="message-text">
                <div class="loading-dots">
                    <span></span>
                    <span></span>
                    <span></span>
                </div>
            </div>
        `;
        
        chatMessages.appendChild(loadingElement);
        scrollToBottom();
        
        return loadingElement;
    }
    
    /**
     * Scroll the chat to the bottom
     */
    function scrollToBottom() {
        if (chatMessages) {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    }
    
    /**
     * Fetch AI response using server-sent events (SSE)
     * @param {string} userMessage The user's message to respond to
     */
    function fetchAIResponse(userMessage) {
        // Prevent multiple requests
        if (isWaitingForResponse) return;
        isWaitingForResponse = true;
        
        // Show loading indicator
        const loadingMessage = createLoadingMessage();
        
        // Get the current vector store type
        const vectorStoreType = vectorStoreDropdown ? vectorStoreDropdown.value : 'semantic';
        
        // Get the current LLM model
        const model = llmModelDropdown ? llmModelDropdown.value : null;
        
        // Build URL with parameters
        const params = new URLSearchParams({
            message: userMessage,
            vector_store_type: vectorStoreType
        });
        
        if (model) {
            params.append('model', model);
        }
        
        // Create the SSE connection
        const eventSource = new EventSource(`/api/chat?${params.toString()}`);
        
        // Handle streamed response
        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                
                // Check for error messages
                if (data.error) {
                    // Replace loading message with error
                    if (loadingMessage) {
                        loadingMessage.innerHTML = `
                            <div class="message-text">
                                <p class="error">Error: ${data.error}</p>
                            </div>
                        `;
                        loadingMessage.className = 'message error';
                    }
                    eventSource.close();
                    isWaitingForResponse = false;
                    return;
                }
                
                // Handle token responses
                if (data.token) {
                    if (!currentStreamedMessage) {
                        // Replace loading indicator with actual message
                        chatMessages.removeChild(loadingMessage);
                        currentStreamedMessage = addAIMessage('');
                    }
                    
                    // Append token to current message
                    const messageText = currentStreamedMessage.querySelector('.message-text');
                    messageText.innerHTML += data.token;
                    
                    // Scroll to keep up with new content
                    scrollToBottom();
                }
                
                // Handle source documents
                if (data.sources && data.sources.length > 0) {
                    // Create source pills container if it doesn't exist
                    if (!currentStreamedMessage.querySelector('.source-pills-container')) {
                        const pillsContainer = document.createElement('div');
                        pillsContainer.className = 'source-pills-container';
                        currentStreamedMessage.appendChild(pillsContainer);
                    }
                    
                    const pillsContainer = currentStreamedMessage.querySelector('.source-pills-container');
                    
                    // Process each source
                    data.sources.forEach(source => {
                        // Check if pill for this source already exists
                        const sourceId = `${source.s3_key}-${source.page}`;
                        if (!document.getElementById(sourceId)) {
                            const pill = document.createElement('div');
                            pill.className = 'source-pill';
                            pill.id = sourceId;
                            pill.innerHTML = `<i class="fas fa-book"></i> ${source.filename} (p.${source.page})`;
                            
                            // Set data attributes
                            pill.dataset.s3Key = source.s3_key;
                            pill.dataset.page = source.page;
                            pill.dataset.score = source.score;
                            pill.dataset.filename = source.filename;
                            pill.dataset.storeType = vectorStoreType;
                            
                            pillsContainer.appendChild(pill);
                        }
                    });
                    
                    // Scroll to keep up with new content
                    scrollToBottom();
                }
                
                // Handle end of response
                if (data.done) {
                    eventSource.close();
                    isWaitingForResponse = false;
                    currentStreamedMessage = null;
                }
            } catch (error) {
                console.error('Error parsing event data:', error);
            }
        };
        
        // Handle errors
        eventSource.onerror = (error) => {
            console.error('EventSource error:', error);
            
            // Remove loading indicator if needed
            if (loadingMessage && loadingMessage.parentNode) {
                chatMessages.removeChild(loadingMessage);
            }
            
            // Add error message
            const errorMessage = document.createElement('div');
            errorMessage.className = 'message error';
            errorMessage.innerHTML = `
                <div class="message-text">
                    <p>Sorry, there was an error connecting to the server. Please try again.</p>
                </div>
            `;
            chatMessages.appendChild(errorMessage);
            
            // Clean up
            eventSource.close();
            isWaitingForResponse = false;
            currentStreamedMessage = null;
            scrollToBottom();
        };
    }
    
    /**
     * Change the LLM model via API
     * @param {string} modelName New model name
     */
    function changeModel(modelName) {
        fetch('/api/change_model', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ model: modelName }),
        })
        .then(response => response.json())
        .then(data => {
            if (!data.success) {
                console.error('Error changing model:', data.error);
            }
        })
        .catch(error => {
            console.error('Error changing model:', error);
        });
    }
}); 