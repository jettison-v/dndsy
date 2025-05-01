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
    const sourceContent = document.getElementById('source-content');
    
    // State tracking
    let isWaitingForResponse = false;
    let currentStreamedMessage = null;
    let accumulatedRawText = ''; // Added: Variable to store raw text chunks
    let receivedLinkData = null; // Added: Variable to store link data
    
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
    
    // Initialize with system message
    if (chatMessages) {
        // Show welcome message
        const welcomeMessage = document.querySelector('.welcome-message');
        if (welcomeMessage) {
            chatMessages.appendChild(welcomeMessage);
        }
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
        // Get the initial model set by the server and log it
        const serverModel = llmModelDropdown.value;
        console.log(`[Debug] LLM Dropdown: Initial value from server = ${serverModel}`);
        
        // Trust the server-set value on load. Do not check localStorage here.
        // LocalStorage is only used to remember the *user's* last explicit selection.
        
        console.log(`[Debug] LLM Dropdown: Using server value: ${llmModelDropdown.value}`);

        // Add event listener for USER changes
        llmModelDropdown.addEventListener('change', () => {
            const selectedModel = llmModelDropdown.value;
            console.log(`[Debug] User changed LLM Model dropdown to: ${selectedModel}`);
            // Make API call to change the model
            changeModel(selectedModel);
            // Store the user's selection in local storage
            localStorage.setItem('preferred_llm_model', selectedModel);
        });
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
        const formattedHtml = formatMessageText(message);
        console.log("[Debug] User message HTML before insert:", formattedHtml?.substring(0,200));
        messageElement.innerHTML = `<div class="message-text">${formattedHtml}</div>`;
        
        // Add to chat and scroll to bottom
        chatMessages.appendChild(messageElement);
        scrollToBottom();
    }
    
    /**
     * Add the AI's response to the chat
     * @param {string} initialContent Initial content for the AI message
     * @returns {HTMLElement} The created AI message element
     */
    function addAIMessage(initialContent = '') {
        if (!chatMessages) return null;
        
        const messageElement = document.createElement('div');
        messageElement.className = 'message assistant';
        
        // Start with potentially empty, but formatted content
        const formattedHtml = formatMessageText(initialContent);
        console.log("[Debug] Initial AI message HTML:", formattedHtml?.substring(0,100));
        messageElement.innerHTML = `<div class="message-text">${formattedHtml}</div>`;
        
        chatMessages.appendChild(messageElement);
        scrollToBottom();
        return messageElement; // Return the created element
    }
    
    /**
     * Format message text with rich formatting
     */
    function formatMessageText(text) {
        // First try to use DNDUtilities
        if (window.DNDUtilities && typeof DNDUtilities.formatMessageText === 'function') {
            try {
                return DNDUtilities.formatMessageText(text);
            } catch (e) {
                console.error('Error using DNDUtilities.formatMessageText:', e);
                // Continue to fallback options
            }
        }
        
        // Next try to use marked library directly
        if (typeof marked !== 'undefined') {
            try {
                return marked.parse(text);
            } catch (e) {
                console.error('Error using marked.parse:', e);
                // Continue to fallback options
            }
        }
        
        // Basic fallback formatting
        return text
            // Bold
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            // Italic
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            // Links (simple case)
            .replace(/\[(.*?)\]\((.*?)\)/g, '<a href="$2">$1</a>')
            // New lines
            .replace(/\n/g, '<br>')
            // Basic code
            .replace(/`(.*?)`/g, '<code>$1</code>');
    }
    
    /**
     * Process links in message
     */
    function processLinks(messageElement, linkData) {
        console.log("[Debug] processLinks called. Element:", messageElement?.className, "Link data keys:", Object.keys(linkData || {}));
        
        // Define common words to exclude from linking (similar to desktop)
        const stopWords = new Set([
            // Articles
            'a', 'an', 'the',
            // Prepositions
            'to', 'in', 'on', 'at', 'by', 'for', 'with', 'from', 'of', 'about',
            // Conjunctions
            'and', 'or', 'but', 'so', 'if', 'as',
            // Other common short words
            'is', 'it', 'be', 'this', 'that', 'do', 'go', 'me', 'my',
            // D&D-specific common words
            'd20', 'dm', 'pc', 'ac', 'hp'
        ]);

        // Filter and sort linkData (similar to desktop)
        const filteredSortedLinkData = {};
        if (linkData) {
            Object.keys(linkData)
                .filter(key => key && key.length > 2 && !stopWords.has(key.toLowerCase())) // Filter length > 2 and stopwords
                .sort((a, b) => b.length - a.length) // Sort by length descending
                .forEach(key => {
                    filteredSortedLinkData[key] = linkData[key];
                });
        }

        if (!messageElement || !filteredSortedLinkData || Object.keys(filteredSortedLinkData).length === 0) {
            console.log("[Debug] processLinks exiting early - no element or no valid/filtered linkData.");
            return false;
        }

        // Check if DNDUtilities function exists
        if (!window.DNDUtilities || typeof window.DNDUtilities.processLinksInMessage !== 'function') {
            console.error("[!!! Debug] DNDUtilities.processLinksInMessage is not available!");
            return false;
        }

        console.log("[Debug Mobile Chat] Data passed to DNDUtilities.processLinksInMessage:", JSON.stringify(filteredSortedLinkData, null, 2));

        try {
            console.log(`[Debug] Calling DNDUtilities.processLinksInMessage with ${Object.keys(filteredSortedLinkData).length} filtered/sorted links.`);
            // Use the filtered and sorted link data
            const hasLinks = DNDUtilities.processLinksInMessage(messageElement, filteredSortedLinkData);
            console.log("[Debug] DNDUtilities.processLinksInMessage returned:", hasLinks);
            
            // If links were added, add our mobile-specific event listeners
            if (hasLinks) {
                console.log("[Debug] Links were added, setting up internal link listeners...");
                // Add event listeners for internal links
                const internalLinks = messageElement.querySelectorAll('.internal-link');
                console.log(`[Debug] Found ${internalLinks.length} internal links.`);
                
                internalLinks.forEach(link => {
                    // Remove previous listener if any to avoid duplicates
                    link.onclick = null; 
                    
                    link.addEventListener('click', (e) => {
                        console.log("[Debug] Internal link click listener fired.");
                        e.preventDefault();
                        e.stopPropagation(); // Stop propagation here as well
                        
                        const s3Key = link.getAttribute('data-s3-key');
                        const page = link.getAttribute('data-page');
                        console.log(`[Debug] Internal link data: Key=${s3Key}, Page=${page}`);
                        
                        if (s3Key && page) {
                            // Trigger source content viewer
                            console.log("[Debug] Attempting to open source panel via window.mobileUI...");
                            if (window.mobileUI && window.mobileUI.openSourcePanel) {
                                console.log("[Debug] Opening source panel via internal link.");
                                window.mobileUI.openSourcePanel();
                                fetchSourceContent(s3Key, page, 'semantic'); // Assuming semantic for now
                            } else {
                                console.error("[Debug] mobileUI.openSourcePanel not found!");
                            }
                        } else {
                            console.error("[Debug] Missing s3Key or page on internal link!");
                        }
                    }, true); // Use capture phase
                });
            } else {
                 console.log("[Debug] No links processed by DNDUtilities.");
            }
            return hasLinks;
        } catch (e) {
            console.error('[Debug] CRITICAL ERROR processing links:', e);
            return false;
        }
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
        
        // Hide welcome message when first message is sent
        const welcomeMessage = document.querySelector('.welcome-message');
        if (welcomeMessage) {
            welcomeMessage.style.display = 'none';
        }
        
        // Reset accumulators for new response
        accumulatedRawText = ''; 
        receivedLinkData = null;
        currentStreamedMessage = null; // Reset the reference to the message element
        
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
                
                // Check for error messages first
                if (data.error) {
                    // Replace loading message with error
                    if (loadingMessage && loadingMessage.parentNode) {
                       chatMessages.removeChild(loadingMessage);
                    }
                    // Add a dedicated error message element
                    const errorElement = document.createElement('div');
                    errorElement.className = 'message error';
                    errorElement.innerHTML = `<div class="message-text"><p>Error: ${data.error}</p></div>`;
                    chatMessages.appendChild(errorElement);
                    scrollToBottom();
                    
                    eventSource.close();
                    isWaitingForResponse = false;
                    accumulatedRawText = ''; // Reset on error
                    receivedLinkData = null;
                    currentStreamedMessage = null;
                    return;
                }

                // --- Handle different event types ---

                // Handle 'metadata' event (usually arrives early)
                if (data.type === 'metadata') {
                     console.log('[Debug mobile-chat] Received metadata:', data);
                     // Create the message element if it doesn't exist yet
                     if (!currentStreamedMessage && loadingMessage) {
                         // Message element doesn't exist yet, use the loading message div
                         currentStreamedMessage = loadingMessage;
                         // Keep loading dots for now, just ensure class is right
                         currentStreamedMessage.className = 'message assistant'; 
                         console.log("[Debug mobile-chat] Initializing message element from loading msg (metadata).");
                     }
                     // Process source pills if provided in metadata
                     if (data.sources && data.sources.length > 0 && currentStreamedMessage) {
                         processSourcePills(currentStreamedMessage, data.sources, vectorStoreType); // Extracted pill logic
                     }
                     // Potentially store other metadata if needed later
                     // currentStreamedMessage.metadata = data; 
                     return; // Don't process further for metadata events
                }

                // Handle 'links' event (store data)
                if (data.type === 'links' && data.links) {
                    console.log("[Debug mobile-chat] Storing link data received.");
                    receivedLinkData = data.links; // Store globally for this response
                    // Ensure message element exists if links arrive before text
                     if (!currentStreamedMessage && loadingMessage) {
                         // Message element doesn't exist yet, use the loading message div
                         currentStreamedMessage = loadingMessage;
                         // Keep loading dots for now, just ensure class is right
                         currentStreamedMessage.className = 'message assistant'; 
                         console.log("[Debug mobile-chat] Initializing message element from loading msg (links).");
                     }
                    return; // Don't process further for link events
                }

                // Handle 'text' chunk (accumulate raw text)
                if (data.type === 'text' && data.content) {
                    // Ensure message element exists, using loading msg if needed
                    if (!currentStreamedMessage && loadingMessage) {
                        currentStreamedMessage = loadingMessage;
                        // Keep loading dots for now, just ensure class is right
                        currentStreamedMessage.className = 'message assistant'; 
                        console.log("[Debug mobile-chat] Initializing message element from loading msg (text).");
                    }
                      accumulatedRawText += data.content; // Append raw text
                      return; // Don't process further for text chunk events
                }
                
                // Handle 'done' event (final processing)
                if (data.type === 'done' || data.done) { // Handle both event:done and data.done for robustness
                    console.log("[Debug mobile-chat] Received done event. Processing final message.");
                    
                    eventSource.close(); // Close connection first

                    if (currentStreamedMessage) {
                        // Find the message text container (should exist from loading message)
                        let messageTextElement = currentStreamedMessage.querySelector('.message-text');
                        
                        if (messageTextElement) {
                            // Clear only the text container (removes loading dots)
                            messageTextElement.innerHTML = ''; 
                        } else {
                            // Fallback: create if it doesn't exist (should not happen)
                            console.warn("[Debug mobile-chat] .message-text not found in done handler, creating.");
                            messageTextElement = document.createElement('div');
                            messageTextElement.className = 'message-text';
                            // Prepend it so pills (if added later) come after
                            currentStreamedMessage.prepend(messageTextElement); 
                        }
                        
                        // Render final content
                        if (messageTextElement) {
                            // 1. Format the *entire* accumulated text
                            console.log(`[Debug mobile-chat] Formatting final accumulated text (length: ${accumulatedRawText.length})`);
                            const finalFormattedHtml = formatMessageText(accumulatedRawText);
                            messageTextElement.innerHTML = finalFormattedHtml; // Set final HTML
                            console.log(`[Debug mobile-chat] Final HTML set (length: ${finalFormattedHtml.length})`);

                            // 2. Process links using the stored link data
                            if (receivedLinkData && Object.keys(receivedLinkData).length > 0) {
                                // Pass the raw receivedLinkData here; filtering/sorting happens inside processLinks
                                console.log("[Debug mobile-chat] Processing links on final message. Raw link keys count:", Object.keys(receivedLinkData).length);
                                processLinks(currentStreamedMessage, receivedLinkData);
                            } else {
                                console.log("[Debug mobile-chat] No link data found or links event not received.");
                            }
                        } else {
                             console.error("[Debug mobile-chat] Done event: Cannot find .message-text element in final message.");
                        }
                    } else {
                        console.warn("[Debug mobile-chat] Done event received but no currentStreamedMessage element exists. Was there any content?");
                        // If loading message still exists, remove it
                         if (loadingMessage && loadingMessage.parentNode) {
                            chatMessages.removeChild(loadingMessage);
                         }
                    }
                    
                    // Final cleanup
                    isWaitingForResponse = false;
                    accumulatedRawText = ''; 
                    receivedLinkData = null;
                    currentStreamedMessage = null; 
                    scrollToBottom(); // Ensure scrolled to the very end
                    return; 
                }

                // Handle unknown event types
                console.warn("[Debug mobile-chat] Received unknown event data structure:", data);

            } catch (error) {
                 console.error('Error parsing SSE event data:', error, 'Raw data:', event.data);
                 // More robust error handling
                 if (loadingMessage && loadingMessage.parentNode) {
                     // Remove loading message on error too
                     chatMessages.removeChild(loadingMessage);
                 }
                 // Add error message if none exists for this response
                 if (!document.querySelector('.message.error')) { // Avoid duplicate errors
                    const errorElement = document.createElement('div');
                    errorElement.className = 'message error';
                    errorElement.innerHTML = `<div class="message-text"><p>Error processing response. Please check console.</p></div>`;
                    chatMessages.appendChild(errorElement);
                    scrollToBottom();
                 }
                 if (eventSource) eventSource.close();
                 isWaitingForResponse = false;
                 accumulatedRawText = ''; 
                 receivedLinkData = null;
                 currentStreamedMessage = null;
            }
        };
        
        // Separate handler for metadata event via addEventListener
        // Note: This might be redundant if metadata is also sent via onmessage
        eventSource.addEventListener('metadata', (event) => {
             try {
                const data = JSON.parse(event.data);
                console.log('[Debug mobile-chat] Received metadata via addEventListener:', data);
                if (!currentStreamedMessage) {
                    // Use loading message if first event
                    if (loadingMessage) {
                        currentStreamedMessage = loadingMessage;
                        currentStreamedMessage.className = 'message assistant'; 
                        console.log("[Debug mobile-chat] Initializing message element from loading msg (metadata listener).");
                    }
                }
                 if (data.sources && data.sources.length > 0 && currentStreamedMessage) {
                     processSourcePills(currentStreamedMessage, data.sources, vectorStoreType);
                 }
             } catch (error) {
                 console.error('Error parsing metadata event (via addEventListener):', error);
             }
        });

        // Separate handler for links event via addEventListener
        // Note: This might be redundant if links are also sent via onmessage
         eventSource.addEventListener('links', (event) => {
             try {
                 const data = JSON.parse(event.data);
                 console.log('[Debug mobile-chat] Received links via addEventListener:', data);
                 if (data.links) {
                    receivedLinkData = data.links;
                     if (!currentStreamedMessage) {
                         // Use loading message if first event
                         if (loadingMessage) {
                            currentStreamedMessage = loadingMessage;
                            currentStreamedMessage.className = 'message assistant'; 
                            console.log("[Debug mobile-chat] Initializing message element from loading msg (links listener).");
                        }
                     }
                 }
             } catch (error) {
                 console.error('Error parsing links event (via addEventListener):', error);
             }
         });

        // Separate handler for done event via addEventListener
        // Note: This might be redundant if done is also sent via onmessage
        eventSource.addEventListener('done', (event) => {
            console.log("[Debug mobile-chat] Received done event via addEventListener. Processing final message.");
            
            eventSource.close(); // Close connection first
            
            if (currentStreamedMessage) {
                // Find the message text container (should exist from loading message)
                let messageTextElement = currentStreamedMessage.querySelector('.message-text');
                
                if (messageTextElement) {
                    // Clear only the text container (removes loading dots)
                    messageTextElement.innerHTML = ''; 
                } else {
                    // Fallback: create if it doesn't exist (should not happen)
                    console.warn("[Debug mobile-chat] .message-text not found in done listener, creating.");
                    messageTextElement = document.createElement('div');
                    messageTextElement.className = 'message-text';
                    // Prepend it so pills (if added later) come after
                    currentStreamedMessage.prepend(messageTextElement); 
                }
                
                // Render final content
                if (messageTextElement) {
                    // 1. Format the *entire* accumulated text
                    console.log(`[Debug mobile-chat] Formatting final accumulated text (length: ${accumulatedRawText.length}) (from addEventListener)`);
                    const finalFormattedHtml = formatMessageText(accumulatedRawText);
                    messageTextElement.innerHTML = finalFormattedHtml; // Set final HTML
                    console.log(`[Debug mobile-chat] Final HTML set (length: ${finalFormattedHtml.length}) (from addEventListener)`);

                    // 2. Process links using the stored link data
                    if (receivedLinkData && Object.keys(receivedLinkData).length > 0) {
                        // Pass the raw receivedLinkData here; filtering/sorting happens inside processLinks
                        console.log("[Debug mobile-chat] Processing links on final message (from addEventListener). Raw link keys count:", Object.keys(receivedLinkData).length);
                        processLinks(currentStreamedMessage, receivedLinkData);
                    } else {
                        console.log("[Debug mobile-chat] No link data found or links event not received. (from addEventListener)");
                    }
                } else {
                     console.error("[Debug mobile-chat] Done event (addEventListener): Cannot find .message-text element in final message.");
                }
            } else {
                console.warn("[Debug mobile-chat] Done event received (addEventListener) but no currentStreamedMessage element exists.");
                 if (loadingMessage && loadingMessage.parentNode) {
                    chatMessages.removeChild(loadingMessage);
                 }
            }
            
            // Final cleanup
            isWaitingForResponse = false;
            accumulatedRawText = ''; 
            receivedLinkData = null;
            currentStreamedMessage = null; 
            scrollToBottom(); 
        });
        
        // Handle general error event for the connection
        eventSource.onerror = (error) => {
            console.error('EventSource connection error:', error);
            
            // Remove loading indicator if it still exists
            if (loadingMessage && loadingMessage.parentNode) {
                chatMessages.removeChild(loadingMessage);
            }
            
            // Add a generic error message if one isn't already present
            if (!document.querySelector('.message.error')) { 
                const errorMessageElement = document.createElement('div');
                errorMessageElement.className = 'message error';
                errorMessageElement.innerHTML = `
                    <div class="message-text">
                        <p>Sorry, there was a connection error. Please try again.</p>
                    </div>
                `;
                chatMessages.appendChild(errorMessageElement);
                 scrollToBottom();
            }
            
            // Clean up state
            eventSource.close();
            isWaitingForResponse = false;
            accumulatedRawText = '';
            receivedLinkData = null;
            currentStreamedMessage = null;
        };
    }
    
    /**
     * Processes source pills and adds them to the message element.
     * @param {HTMLElement} messageElement The AI message element.
     * @param {Array} sources Array of source objects from metadata.
     * @param {string} vectorStoreType The vector store type used for the query.
     */
    function processSourcePills(messageElement, sources, vectorStoreType) {
        if (!messageElement || !sources || sources.length === 0) return;

        // Ensure the message text element exists or create it if needed
        let messageText = messageElement.querySelector('.message-text');
        if (!messageText) {
            messageText = document.createElement('div');
            messageText.className = 'message-text';
            messageElement.appendChild(messageText);
            console.warn("[Debug mobile-chat] Created .message-text in processSourcePills as it was missing.")
        }

        // Create source pills container if it doesn't exist
        let pillsContainer = messageElement.querySelector('.source-pills-container');
        if (!pillsContainer) {
            pillsContainer = document.createElement('div');
            pillsContainer.className = 'source-pills-container';
            // Always append the pills container *after* the message text container
            messageElement.appendChild(pillsContainer);
        }
                    
        // Process each source
        sources.forEach(source => {
            // Check if pill for this source already exists
            const sourceId = `${source.s3_key}-${source.page}`;
            // Use a more specific selector within the current message element
            if (!messageElement.querySelector(`#pill-${sourceId.replace(/[^a-zA-Z0-9-_]/g, '')}`)) { // Sanitize ID for querySelector
                const pill = document.createElement('div');
                pill.className = 'source-pill';
                pill.id = `pill-${sourceId.replace(/[^a-zA-Z0-9-_]/g, '')}`; // Sanitize ID
                           
                // Format source name to be more concise: "Document Name (Pg X)"
                let displayName = source.display || source.s3_key.split('/').pop().replace(/\.[^/.]+$/, "");
                // If the filename is too long, truncate it
                if (displayName.length > 20) {
                   displayName = displayName.substring(0, 18) + '...';
                }
                pill.innerHTML = `<i class="fas fa-book"></i> ${displayName} (Pg ${source.page})`;
                           
                // Set data attributes
                pill.dataset.s3Key = source.s3_key;
                pill.dataset.page = source.page;
                pill.dataset.score = source.score;
                pill.dataset.filename = source.filename || source.s3_key.split('/').pop().replace(/\.[^/.]+$/, "");
                // Ensure vectorStoreType is defined in this scope before assigning
                if (typeof vectorStoreType !== 'undefined') {
                   pill.dataset.storeType = vectorStoreType;
                } else {
                    console.error(`[!!!Debug Error] vectorStoreType is undefined when creating pill ${sourceId}! Using fallback.`);
                    pill.dataset.storeType = 'semantic'; // Fallback
                }
                           
                // Add click handler to pill for displaying source content
                pill.addEventListener('click', function(e) {
                    console.log("[Debug] Source pill click listener fired.");
                    e.stopPropagation(); 
                    e.preventDefault();  
                    console.log("[Debug] Source Pill Clicked!", {
                        s3Key: this.dataset.s3Key,
                        page: this.dataset.page,
                        storeType: this.dataset.storeType
                    });

                    // Highlight the clicked pill
                    document.querySelectorAll('.source-pill.active').forEach(activePill => activePill.classList.remove('active'));
                    this.classList.add('active');

                    console.log("[Debug] Attempting to open source panel via window.mobileUI...");
                    if (typeof window.mobileUI !== 'undefined' && typeof window.mobileUI.openSourcePanel === 'function') {
                        console.log("[Debug] Calling mobileUI.openSourcePanel()");
                        window.mobileUI.openSourcePanel();
                        fetchSourceContent(this.dataset.s3Key, this.dataset.page, this.dataset.storeType);
                    } else {
                        console.error("[Debug] mobileUI.openSourcePanel not found or not a function!");
                        alert("Error: Could not open source panel."); 
                    }
                });
                           
                pillsContainer.appendChild(pill);
            }
        });
    }
    
    /**
     * Fetch source content
     * Uses the shared utility if available or provides a fallback
     */
    function fetchSourceContent(s3Key, page, storeType) {
        console.log(`[Debug] fetchSourceContent called with: key=${s3Key}, page=${page}, store=${storeType}`);
        if (!sourceContent) {
            console.error('Source content element not found');
            return;
        }
        
        // Show loading indicator
        sourceContent.innerHTML = '<p class="loading-source">Loading source content...</p>';
        
        // Use the shared utility if available
        if (window.DNDUtilities && typeof DNDUtilities.fetchSourceContent === 'function') {
            DNDUtilities.fetchSourceContent(s3Key, page, storeType, 
                // Success callback - Pass storeType through
                (details) => {
                    displaySourceDetails(details, s3Key, page, storeType); // Pass storeType here
                }, 
                // Error callback
                (errorMessage) => {
                    sourceContent.innerHTML = `<p class="error-source">Error: ${errorMessage}</p>`;
                }
            );
        } else {
            // Fallback implementation
            fetch(`/api/get_context_details?source=${encodeURIComponent(s3Key)}&page=${page}&vector_store_type=${storeType}`)
                .then(response => {
                    if (!response.ok) {
                        return response.json().then(errorData => {
                            throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
                        });
                    }
                    return response.json();
                })
                .then(details => {
                    displaySourceDetails(details, s3Key, page, storeType); // Pass storeType here too
                    console.log(`[Debug] fetchSourceContent (fallback) successful for: key=${s3Key}, page=${page}`);
                })
                .catch(error => {
                    console.error('Error fetching source content:', error);
                    sourceContent.innerHTML = `<p class="error-source">Error: ${error.message}</p>`;
                });
        }
        console.log(`[Debug] fetchSourceContent finished for: key=${s3Key}, page=${page}`);
    }
    
    /**
     * Display source details in the source panel
     */
    function displaySourceDetails(details, s3Key, page, storeType) { // Add storeType parameter
        if (!details) {
            sourceContent.innerHTML = '<p class="error-source">No details returned from server</p>';
            return;
        }
        
        // Clear loading indicator
        sourceContent.innerHTML = '';
        
        // Display source name
        const filename = s3Key.split('/').pop().replace(/\.[^/.]+$/, "");
        const header = document.createElement('div');
        header.className = 'source-header';
        
        const sourceName = document.createElement('h4');
        sourceName.textContent = `${filename} (page ${page})`;
        header.appendChild(sourceName);
        
        sourceContent.appendChild(header);
        
        // Display content based on type
        if (details.image_url || details.image_base64) {
            // Display image content
            const imageContainer = document.createElement('div');
            imageContainer.id = 'source-image-container';
            imageContainer.className = 'source-image-container';
            
            const img = document.createElement('img');
            img.className = 'source-image';
            img.alt = `${filename} (page ${page})`;
            
            // Use the shared utility for image loading if available
            if (window.DNDUtilities && DNDUtilities.loadImageWithFallback && details.imageStrategies) {
                DNDUtilities.loadImageWithFallback(img, details.imageStrategies, (errorMsg) => {
                    console.error('Image loading failed:', errorMsg);
                    img.alt = 'Error loading image';
                    img.style.display = 'none';
                    imageContainer.innerHTML += `<p class="error-source">Failed to load image.</p>`;
                });
            } else {
                // Basic fallback implementation
                if (details.image_url) {
                    if (details.image_url.startsWith('s3://')) {
                        img.src = `/api/get_pdf_image?key=${encodeURIComponent(details.image_url)}`;
                    } else {
                        img.src = details.image_url;
                    }
                } else if (details.image_base64) {
                    img.src = `data:image/jpeg;base64,${details.image_base64}`;
                }
                
                img.onerror = () => {
                    img.alt = 'Error loading image';
                    img.style.display = 'none';
                    imageContainer.innerHTML += `<p class="error-source">Error loading image.</p>`;
                };
            }
            
            imageContainer.appendChild(img);
            sourceContent.appendChild(imageContainer);
        } else if (details.text_content) {
            // Display text content
            const textContainer = document.createElement('div');
            textContainer.className = 'source-text';
            textContainer.innerHTML = details.text_content;
            sourceContent.appendChild(textContainer);
        } else {
            // No content available
            sourceContent.innerHTML += '<p class="no-source">No source content available</p>';
        }
        
        // Add page navigation if needed
        if (details.total_pages && details.total_pages > 1) {
            addSourceNavigation(sourceContent, parseInt(page), details.total_pages, s3Key, storeType); // Pass storeType
        }
    }
    
    /**
     * Add source navigation buttons
     */
    function addSourceNavigation(container, currentPage, totalPages, s3Key, storeType) {
        const navContainer = document.createElement('div');
        navContainer.className = 'source-navigation';
        
        // Previous button
        const prevButton = document.createElement('button');
        prevButton.innerHTML = '<i class="fas fa-chevron-left"></i> Prev';
        prevButton.className = 'nav-button prev-button';
        prevButton.disabled = currentPage <= 1;
        
        // Page indicator
        const pageIndicator = document.createElement('div');
        pageIndicator.className = 'page-indicator';
        pageIndicator.textContent = `${currentPage} / ${totalPages}`;
        
        // Next button
        const nextButton = document.createElement('button');
        nextButton.innerHTML = 'Next <i class="fas fa-chevron-right"></i>';
        nextButton.className = 'nav-button next-button';
        nextButton.disabled = currentPage >= totalPages;
        
        // Add event listeners
        prevButton.addEventListener('click', () => {
            if (currentPage > 1) {
                fetchSourceContent(s3Key, currentPage - 1, storeType);
            }
        });
        
        nextButton.addEventListener('click', () => {
            if (currentPage < totalPages) {
                fetchSourceContent(s3Key, currentPage + 1, storeType);
            }
        });
        
        // Add elements to container
        navContainer.appendChild(prevButton);
        navContainer.appendChild(pageIndicator);
        navContainer.appendChild(nextButton);
        
        container.appendChild(navContainer);
    }
    
    /**
     * Change the LLM model via API
     * @param {string} modelName New model name
     */
    function changeModel(modelName) {
        console.log(`[Debug] changeModel function called with: ${modelName}`); // Log when this is called
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