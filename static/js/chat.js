document.addEventListener('DOMContentLoaded', () => {
    // Check if setting-change style is defined
    const settingChangeStyle = getComputedStyle(document.documentElement)
        .getPropertyValue('--setting-change-bg') || 'rgba(228, 7, 18, 0.1)';
    console.log('Setting change style background:', settingChangeStyle);

    /*
    ========================================
      ELEMENT SELECTORS & INITIALIZATION
    ========================================
    */
    const chatMessages = document.getElementById('chat-messages');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');
    const sourcePanel = document.getElementById('source-panel');
    const sourceContent = document.getElementById('source-content');
    const closePanel = document.getElementById('close-panel');
    const expandPanel = document.getElementById('expand-panel');
    const expandedSourcePills = document.getElementById('expanded-source-pills');
    const mobileSourceToggle = document.getElementById('mobile-source-toggle');
    const zoomInBtn = document.getElementById('zoom-in');
    const zoomOutBtn = document.getElementById('zoom-out');
    const zoomResetBtn = document.getElementById('zoom-reset');
    const vectorStoreSelector = document.getElementById('vector-store-selector');
    const vectorStoreDropdown = document.getElementById('vector-store-dropdown');
    const vectorStoreInfoBtn = document.getElementById('vector-store-info-btn');
    const modalOverlay = document.getElementById('modal-overlay');
    const pageContextModal = document.getElementById('page-context-modal');
    const semanticContextModal = document.getElementById('semantic-context-modal');
    const modalCloseButtons = document.querySelectorAll('.modal-close');
    const llmModelDropdown = document.getElementById('llm-model-dropdown');
    
    let isFirstMessage = true;
    let messageContextParts = {};
    let currentEventSource = null;
    let currentZoomLevel = 1;
    let isPanelExpanded = false;
    let activeSources = []; // Store active sources for expanded view
    let currentVectorStore = vectorStoreDropdown ? vectorStoreDropdown.value : 'semantic';
    
    // Initialize source panel state
    let sourcePanelOpen = false;

    /*
    ========================================
      VECTOR STORE SELECTION & MODALS
    ========================================
    */
    if (vectorStoreDropdown) {
        vectorStoreDropdown.addEventListener('change', () => {
            // Get previous and new vector store values
            const previousStore = currentVectorStore;
            const newStore = vectorStoreDropdown.value;
            
            // Update current vector store
            currentVectorStore = newStore;
            
            // Add system message to chat indicating the change
            const storeDisplayName = (newStore === 'standard') ? 'Page Context' : 
                                    (newStore === 'semantic') ? 'Semantic Context' : 
                                    newStore.charAt(0).toUpperCase() + newStore.slice(1);
            
            // Don't add system message on initial load - only for actual changes
            if (isFirstMessage === false) {
                addMessage(`Vector Store changed to ${storeDisplayName}`, 'system');
            }
        });
    }

    // Add event listener for LLM model changes if it becomes enabled in the future
    if (llmModelDropdown) {
        console.log('Setting up model dropdown listener');
        llmModelDropdown.addEventListener('change', async () => {
            const previousModel = llmModelDropdown.getAttribute('data-current-model') || llmModelDropdown.value;
            const newModel = llmModelDropdown.value;
            
            console.log('Model dropdown changed:', { previousModel, newModel });
            
            // Don't send request if there's no change
            if (previousModel === newModel) {
                console.log('No model change detected, skipping');
                return;
            }
            
            try {
                console.log('Sending model change request for:', newModel);
                // Send request to change model
                const response = await fetch('/api/change_model', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ model: newModel }),
                });
                
                console.log('Model change response status:', response.status);
                
                if (!response.ok) {
                    const errorData = await response.json();
                    console.error('Model change error response:', errorData);
                    throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
                }
                
                const data = await response.json();
                console.log('Model change success data:', data);
                
                // Store current model for future reference
                llmModelDropdown.setAttribute('data-current-model', newModel);
                
                // Don't add system message on initial load - only for actual changes
                if (isFirstMessage === false) {
                    console.log('Displaying model change message:', data.display_name);
                    const messageText = `Model changed to ${data.display_name}`;
                    console.log('Message text to be added:', messageText);
                    const messageId = addMessage(messageText, 'system');
                    console.log('Message added with ID:', messageId);
                    
                    // Add a test message the simple way to see if it shows up
                    const testMsg = document.createElement('div');
                    testMsg.className = 'message system setting-change';
                    testMsg.textContent = `TEST: Model changed to ${data.display_name}`;
                    testMsg.style.display = 'block';
                    testMsg.style.marginTop = '10px';
                    testMsg.style.backgroundColor = 'rgba(228, 7, 18, 0.2)'; 
                    testMsg.style.color = 'white';
                    testMsg.style.padding = '10px';
                    testMsg.style.borderRadius = '8px';
                    chatMessages.appendChild(testMsg);
                    
                    // Force scroll
                    chatMessages.scrollTop = chatMessages.scrollHeight;
                } else {
                    console.log('First message flag is true, not showing model change message');
                }
            } catch (error) {
                console.error('Error changing LLM model:', error);
                // Revert to previous selection on error
                llmModelDropdown.value = previousModel;
                addMessage(`Error changing model: ${error.message}`, 'system');
            }
        });
    } else {
        console.warn('LLM model dropdown element not found');
    }

    // Vector Store Info Button
    if (vectorStoreInfoBtn) {
        vectorStoreInfoBtn.addEventListener('click', () => {
            // Show appropriate modal
            const currentValue = vectorStoreDropdown.value;
            
            if (currentValue === 'standard') {
                showModal(pageContextModal);
            } else if (currentValue === 'semantic') {
                showModal(semanticContextModal);
            }
        });
    }

    // Handle modal visibility
    function showModal(modal) {
        if (modalOverlay && modal) {
            modalOverlay.style.display = 'block';
            modal.style.display = 'block';
        }
    }

    function hideAllModals() {
        if (modalOverlay) {
            modalOverlay.style.display = 'none';
        }
        
        const modals = document.querySelectorAll('.vector-store-modal');
        modals.forEach(modal => {
            modal.style.display = 'none';
        });
    }

    // Modal close buttons
    if (modalCloseButtons) {
        modalCloseButtons.forEach(button => {
            button.addEventListener('click', hideAllModals);
        });
    }

    // Close modal when clicking overlay
    if (modalOverlay) {
        modalOverlay.addEventListener('click', hideAllModals);
    }

    // Close modal with Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            hideAllModals();
        }
    });

    /*
    ========================================
      SOURCE PANEL UI (EXPAND/COLLAPSE, ZOOM, MOBILE TOGGLE)
    ========================================
    */

    // ---- Expand/Collapse ----
    if (expandPanel) {
        expandPanel.addEventListener('click', () => {
            if (isPanelExpanded) {
                // Toggle from expanded to normal open state
                sourcePanel.classList.add('collapsing');
                setTimeout(() => {
                    sourcePanel.classList.remove('expanded');
                    
                    setTimeout(() => {
                        sourcePanel.classList.remove('collapsing');
                        sourcePanel.classList.add('open');
                    }, 300);
                }, 10);

                expandPanel.innerHTML = '<i class="fas fa-external-link-alt"></i>';
                expandPanel.title = 'Expand';
                isPanelExpanded = false;
            } else {
                // Toggle from normal to expanded state
                sourcePanel.classList.add('expanded');
                
                expandPanel.innerHTML = '<i class="fas fa-compress"></i>';
                expandPanel.title = 'Compress';
                isPanelExpanded = true;
                
                // Clone source pills to expanded view if available
                updateExpandedSourcePills();
            }
        });
    }
    
    // ---- Update Expanded Pills Helper ----
    function updateExpandedSourcePills() {
        if (!expandedSourcePills) return;
        
        // Clear the source pills container completely
        const sourcePillsContainer = document.getElementById('expanded-source-pills');
        sourcePillsContainer.innerHTML = '';
        
        // Find the currently active source pill *in the main chat*
        const activePillInChat = chatMessages.querySelector('.source-pill.active');
        
        if (!activePillInChat || !activePillInChat.dataset.messageId) {
            sourcePillsContainer.innerHTML = '<p class="info-text">No active source selected.</p>';
            return; // No active source to relate to
        }
        
        const activeMessageId = activePillInChat.dataset.messageId;
        const relatedMessageElement = chatMessages.querySelector(`.message[data-message-id="${activeMessageId}"] .message-text`);
        
        // ===== 1. SOURCES SECTION (now first) =====
        const sourcesSection = document.createElement('div');
        sourcesSection.className = 'expanded-sources-section';
        
        // Remove the Sources heading - per user request
        // const sourcesHeading = document.createElement('h3');
        // sourcesHeading.textContent = 'Sources';
        // sourcesSection.appendChild(sourcesHeading);
        
        const pillsContainer = document.createElement('div');
        pillsContainer.className = 'expanded-source-pills-container';
        sourcesSection.appendChild(pillsContainer);
        
        sourcePillsContainer.appendChild(sourcesSection);
        
        // ===== 2. DIVIDER =====
        const divider = document.createElement('div');
        divider.className = 'expanded-sources-divider';
        sourcePillsContainer.appendChild(divider);
        
        // ===== 3. MESSAGE CONTENT SECTION (now last) =====
        const messageContainer = document.createElement('div');
        messageContainer.className = 'expanded-message-container';
        
        const messageContent = document.createElement('div');
        messageContent.id = 'expanded-message-content';
        messageContent.className = 'expanded-message-content';
        
        if (relatedMessageElement) {
            // Check if the message text has been fully processed with markdown
            const fullText = relatedMessageElement.dataset.fullText;
            
            if (fullText && typeof window.marked !== 'undefined') {
                try {
                    // Use the same markdown formatting as in the chat window
                    messageContent.innerHTML = window.marked.parse(fullText);
                    
                    // Ensure code blocks are properly formatted
                    messageContent.querySelectorAll('pre code').forEach(block => {
                        block.style.display = 'block';
                        block.style.whiteSpace = 'pre';
                        block.style.overflowX = 'auto';
                    });
                    
                    // Ensure list items have proper indentation
                    messageContent.querySelectorAll('ul, ol').forEach(list => {
                        list.style.paddingLeft = '1.5rem';
                    });
                } catch (error) {
                    console.error('Error parsing markdown in expanded view:', error);
                    // Fallback to the HTML content of the message
                    messageContent.innerHTML = relatedMessageElement.innerHTML;
                }
            } else {
                // If no full text is available, use the HTML content directly
                messageContent.innerHTML = relatedMessageElement.innerHTML;
            }
        } else {
            messageContent.innerHTML = '<p class="info-text">Could not find related message content.</p>';
        }
        
        messageContainer.appendChild(messageContent);
        sourcePillsContainer.appendChild(messageContainer);

        // Find all source pills in the chat associated with the active messageId
        chatMessages.querySelectorAll(`.message[data-message-id="${activeMessageId}"] .source-pill`).forEach(pillInChat => {
            const clonedPill = pillInChat.cloneNode(true);
            
            // Re-attach click listener for the cloned pill
            clonedPill.addEventListener('click', async () => {
                const s3Key = clonedPill.dataset.s3Key;
                const pageNumber = clonedPill.dataset.page;
                const score = clonedPill.dataset.score;
                const storeType = clonedPill.dataset.storeType || currentVectorStore;
                const filename = clonedPill.dataset.filename; // Get filename from dataset
                
                // Update active state within the *expanded* panel
                pillsContainer.querySelectorAll('.source-pill').forEach(p => p.classList.remove('active'));
                clonedPill.classList.add('active');

                // Also update the corresponding pill in the main chat for consistency
                const correspondingPillInChat = chatMessages.querySelector(`.message[data-message-id="${activeMessageId}"] .source-pill[data-s3-key="${s3Key}"][data-page="${pageNumber}"]`);
                if (correspondingPillInChat) {
                    chatMessages.querySelectorAll('.source-pill').forEach(p => p.classList.remove('active'));
                    correspondingPillInChat.classList.add('active');
                }
                
                // Don't change the left side layout when clicking pills in expanded view
                // Just update the main content area
                // Show loading in main content area
                sourceContent.innerHTML = '<p class="loading-source">Loading source details...</p>';
                
                try {
                    // Fetch and show source in the main content area
                    const response = await fetch(`/api/get_context_details?source=${encodeURIComponent(s3Key)}&page=${pageNumber}&vector_store_type=${storeType}`);
                    if (!response.ok) {
                        const errorData = await response.json();
                        throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
                    }
                    const details = await response.json();
                    if (!details) throw new Error('No details returned from server');
                    
                    // Display in the main content area
                    showSourcePanel(details, `${filename} (page ${pageNumber})`, pageNumber, s3Key, score, storeType);
                    
                } catch (error) {
                    console.error('Error fetching source details from expanded pill click:', error);
                    sourceContent.innerHTML = `<p class="error-source">Error loading source: ${error.message}</p>`;
                }
            });
            
            pillsContainer.appendChild(clonedPill);
        });
    }

    // ---- Zoom Controls ----
    if (zoomInBtn && zoomOutBtn && zoomResetBtn) {
        zoomInBtn.addEventListener('click', () => {
            if (currentZoomLevel < 2.5) {
                currentZoomLevel += 0.25;
                updateZoom();
            }
        });
        
        zoomOutBtn.addEventListener('click', () => {
            if (currentZoomLevel > 0.5) {
                currentZoomLevel -= 0.25;
                updateZoom();
            }
        });
        
        zoomResetBtn.addEventListener('click', () => {
            currentZoomLevel = 1;
            updateZoom();
        });
    }
    
    // ---- Update Zoom Helper ----
    function updateZoom() {
        const imgContainer = document.getElementById('source-image-container');
        if (imgContainer) {
            const img = imgContainer.querySelector('img');
            if (img) {
                img.style.transform = `scale(${currentZoomLevel})`;
                img.style.transformOrigin = 'center top';
            }
        }
    }
    
    // ---- Mobile Source Toggle ----
    if (mobileSourceToggle) {
        mobileSourceToggle.addEventListener('click', () => {
            if (sourcePanelOpen) {
                sourcePanel.classList.add('closing');
                
                // Wait for animation to complete before removing open class
                setTimeout(() => {
                    sourcePanel.classList.remove('open');
                    sourcePanel.classList.remove('closing');
                    sourcePanelOpen = false;
                    
                    // Remove active class from all source pills when panel is closed
                    document.querySelectorAll('.source-pill').forEach(pill => {
                        pill.classList.remove('active');
                    });
                    
                    mobileSourceToggle.querySelector('i').classList.replace('fa-times', 'fa-book');
                }, 300); // Match the animation duration
            } else {
                sourcePanel.classList.add('open');
                sourcePanelOpen = true;
                mobileSourceToggle.querySelector('i').classList.replace('fa-book', 'fa-times');
                
                setTimeout(() => {
                }, 300);
            }
        });
    }

    /*
    ========================================
      CHAT MESSAGE HANDLING
    ========================================
    */

    // ---- Add Message to DOM ----
    function addMessage(text, sender, messageId = null) {
        console.log('addMessage called with:', { text, sender });
        // If this is the first user message, remove the welcome system message
        if (sender === 'user' && isFirstMessage) {
            const systemMessages = chatMessages.querySelectorAll('.message.system');
            systemMessages.forEach(msg => {
                msg.style.display = 'none';
            });
            isFirstMessage = false;
            // Update centering since we removed the welcome message
            centerInitialMessage();
        }
        
        const messageElement = document.createElement('div');
        messageElement.classList.add('message', sender);
        
        // Add special styling for setting change notifications
        const isVectorStoreMsg = text.includes('Vector Store changed');
        const isModelChangeMsg = text.includes('Model changed to');
        console.log('Message pattern check:', { isVectorStoreMsg, isModelChangeMsg, text });
        
        if (sender === 'system' && (isVectorStoreMsg || isModelChangeMsg)) {
            messageElement.classList.add('setting-change');
            console.log('Added setting-change class to message:', text);
            console.log('Message classes:', messageElement.className);
        }
        
        const id = messageId || `msg-${Date.now()}-${Math.random().toString(16).substring(2)}`;
        messageElement.dataset.messageId = id;
        
        // Create a span for the main text content
        const textSpan = document.createElement('span');
        textSpan.className = 'message-text'; 
        
        // Set initial text (parsing happens in appendToMessage)
        textSpan.textContent = text;
        
        // Add a data attribute to store the accumulated text for formatting
        if (sender === 'assistant') {
            textSpan.dataset.fullText = '';
        }
        
        messageElement.appendChild(textSpan);
        
        // Placeholder for source pills container (added later if needed)
        const sourceContainer = document.createElement('div');
        sourceContainer.className = 'source-pills';
        sourceContainer.style.display = 'none'; // Hide initially
        messageElement.appendChild(sourceContainer);
        
        chatMessages.appendChild(messageElement);
        
        // Debug added message
        if (sender === 'system' && messageElement.classList.contains('setting-change')) {
            console.log('Setting-change message added to DOM:', messageElement);
            console.log('All setting-change messages in DOM:', 
                chatMessages.querySelectorAll('.message.system.setting-change').length);
            
            // Force message to be visible
            messageElement.style.display = 'block';
            messageElement.style.opacity = '1';
            messageElement.style.visibility = 'visible';
        }
        
        // Update centering after adding a new message
        centerInitialMessage();
        
        chatMessages.scrollTop = chatMessages.scrollHeight;
        return id;
    }
    
    // ---- Append Text Chunk to Message ----
    function appendToMessage(messageId, textChunk) {
        const messageElement = chatMessages.querySelector(`[data-message-id="${messageId}"]`);
        if (!messageElement) {
            return;
        }
        
        const textSpan = messageElement.querySelector('.message-text');
        if (!textSpan) {
            return;
        }
        
        // Remove the thinking indicator if it exists and we are appending real text
        const indicator = textSpan.querySelector('.thinking-indicator');
        if (indicator) {
            indicator.remove();
        }

        // Accumulate the full text to ensure proper markdown formatting
        if (textSpan.dataset.fullText !== undefined) {
            textSpan.dataset.fullText += textChunk;
            
            // Check if marked library is available before using it
            if (typeof window.marked !== 'undefined') {
                try {
                    // Format with markdown
                    textSpan.innerHTML = window.marked.parse(textSpan.dataset.fullText);
                } catch (error) {
                    console.error('Error parsing markdown:', error);
                    // Fallback to simple formatting
                    formatTextWithBasicRules(textSpan, textSpan.dataset.fullText);
                }
            } else {
                // If marked is not available, use basic text formatting
                formatTextWithBasicRules(textSpan, textSpan.dataset.fullText);
            }
            
            // If the source panel is expanded and the active message is being updated,
            // refresh the expanded view to keep it in sync
            if (isPanelExpanded) {
                const activePill = chatMessages.querySelector('.source-pill.active');
                if (activePill && activePill.dataset.messageId === messageId) {
                    updateExpandedSourcePills();
                }
            }
        } else {
            // For non-assistant messages (like user input), just append text directly
            textSpan.textContent += textChunk;
        }
        
        // Scroll to the bottom of the chat
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }
    
    // ---- Basic formatting helper without marked library ----
    function formatTextWithBasicRules(element, text) {
        // Convert line breaks to paragraphs
        const paragraphs = text.split('\n\n');
        let formattedText = '';
        
        paragraphs.forEach(paragraph => {
            if (paragraph.trim() !== '') {
                // Check if it might be a code block
                if (paragraph.startsWith('```') && paragraph.endsWith('```')) {
                    const code = paragraph.substring(3, paragraph.length - 3);
                    formattedText += `<pre><code>${escapeHTML(code)}</code></pre>`;
                } else if (paragraph.startsWith('# ')) {
                    // H1 heading
                    formattedText += `<h1>${escapeHTML(paragraph.substring(2))}</h1>`;
                } else if (paragraph.startsWith('## ')) {
                    // H2 heading
                    formattedText += `<h2>${escapeHTML(paragraph.substring(3))}</h2>`;
                } else if (paragraph.startsWith('### ')) {
                    // H3 heading
                    formattedText += `<h3>${escapeHTML(paragraph.substring(4))}</h3>`;
                } else {
                    // Regular paragraph
                    formattedText += `<p>${formatInlineElements(paragraph)}</p>`;
                }
            }
        });
        
        element.innerHTML = formattedText;
    }
    
    // ---- Helper for escaping HTML ----
    function escapeHTML(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    // ---- Format inline markdown elements ----
    function formatInlineElements(text) {
        // Handle bold text
        text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        
        // Handle italic text
        text = text.replace(/\*(.*?)\*/g, '<em>$1</em>');
        
        // Handle inline code
        text = text.replace(/`(.*?)`/g, '<code>$1</code>');
        
        // Handle links
        text = text.replace(/\[(.*?)\]\((.*?)\)/g, '<a href="$2">$1</a>');
        
        return text;
    }

    // ---- Add Source Pills to Message ----
    function addSourcePills(messageId, sources) {
        const messageElement = chatMessages.querySelector(`[data-message-id="${messageId}"]`);
        if (!messageElement) return;
        
        const pillsContainer = messageElement.querySelector('.source-pills');
        if (!pillsContainer) return;
        
        if (!sources || sources.length === 0) {
            pillsContainer.style.display = 'none';
            return;
        }
        
        // Store active sources for expanded view
        activeSources = sources;
        
        // Clear existing pills
        pillsContainer.innerHTML = '';
        
        // Create label
        const label = document.createElement('span');
        label.className = 'source-pills-label';
        label.textContent = 'Sources:';
        pillsContainer.appendChild(label);
        
        // Add source pills
        sources.forEach(source => {
            const pill = createSourcePill(source, messageId);
            pillsContainer.appendChild(pill);
        });
        
        // Show the pills container
        pillsContainer.style.display = 'flex';
    }
    
    // ---- Update Message Text (for Status) ----
    function updateMessageText(messageId, newText, showIndicator = true) {
        const textSpan = chatMessages.querySelector(`[data-message-id="${messageId}"] .message-text`);
        if (textSpan) {
            let content = `<span class="status-text">${newText}</span>`;
            if (showIndicator) {
                content += ' <span class="thinking-indicator"><span></span><span></span><span></span></span>';
            }
            // Status messages are temporary, don't parse markdown here
            textSpan.innerHTML = content; 
            chatMessages.scrollTop = chatMessages.scrollHeight; 
        }
    }

    // ---- Create Source Pill Helper ----
    function createSourcePill(source, messageId) {
        // Correct property names to match what comes from the API (snake_case)
        const { s3_key, file_path, page, score, chunk_index } = source;
        
        // Extract just the filename without path or extension
        let filename = s3_key.split('/').pop();
        if (filename.includes('.')) {
            filename = filename.substring(0, filename.lastIndexOf('.'));
        }
        
        // Clean up filename for display
        filename = filename.replace(/^\d+\s*-\s*/, ''); // Remove leading numbers and dashes
        
        // Get just the document name without nested folder structure for display
        const simpleDocName = filename.split(' - ').pop() || filename;
        
        // Limit the filename length for display - Increased from 20 to 30
        const maxFilenameLength = 30;
        const displayFilename = simpleDocName.length > maxFilenameLength 
            ? simpleDocName.substring(0, maxFilenameLength) + '...' 
            : simpleDocName;
        
        // Create the pill element
        const pill = document.createElement('button');
        pill.className = 'source-pill';
        
        // Format display text to be more compact
        pill.innerText = `${displayFilename} (p.${page})`;
        
        // Create more informative tooltip with full context
        let tooltipContent = `Source: ${filename}\nPage: ${page}`;
        if (score !== undefined) {
            tooltipContent += `\nRelevance: ${(score * 100).toFixed(1)}%`;
        }
        // Prioritize chunk_info and other path fields for tooltip
        const hierarchyPath = source.chunk_info || 
                              source.hierarchy_path || 
                              source.document_path || 
                              source.path || 
                              source.context_path || 
                              source.file_path || // Add original file_path as fallback
                              ''; // Default to empty string if no path found
        
        // Only show path for semantic search results
        if (source.store_type === 'semantic' && hierarchyPath) {
            tooltipContent += `\nPath: ${hierarchyPath}`;
        }
        
        pill.dataset.tooltip = tooltipContent;
        
        // Store data for retrieval
        pill.dataset.s3Key = s3_key;
        pill.dataset.page = page;
        pill.dataset.score = score;
        pill.dataset.filename = filename;
        // Also need to update the store_type here
        pill.dataset.storeType = source.store_type;
        pill.dataset.messageId = messageId;
        
        // Add click event listener
        pill.addEventListener('click', async function() {
            // Set this pill as active
            document.querySelectorAll('.source-pill').forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            
            try {
                // Request source details from backend using the correct endpoint
                const response = await fetch(`/api/get_context_details?source=${encodeURIComponent(s3_key)}&page=${page}&vector_store_type=${source.store_type || currentVectorStore}`);
                
                if (!response.ok) {
                    return response.json().then(errorData => {
                        throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
                    });
                }
                
                // Parse response
                const details = await response.json();
                
                if (!details) {
                    throw new Error('No details returned from server');
                }
                
                // Use the showSourcePanel function (same as expanded view)
                showSourcePanel(details, `${filename} (page ${page})`, page, s3_key, score, source.store_type);
                
            } catch (error) {
                console.error('Error fetching source details:', error);
                sourceContent.innerHTML = `<p class="error-source">Error loading source: ${error.message}</p>`;
                pill.classList.remove('active');
            }
        });
        
        return pill;
    }

    /*
    ========================================
      SOURCE PANEL CONTENT & NAVIGATION
    ========================================
    */

    // ---- Convert S3 URL ----
    function convertS3UrlToHttps(s3Url) {
        if (!s3Url) return null;
        
        // If it's already an HTTPS URL, return it as is
        if (s3Url.startsWith('http')) {
            return s3Url;
        }
        
        // Handle s3:// URLs
        if (s3Url.startsWith('s3://')) {
            // Extract bucket and key from s3:// URL
            const s3Regex = /s3:\/\/([^/]+)\/(.+)/;
            const match = s3Url.match(s3Regex);
            
            if (match && match.length === 3) {
                const bucket = match[1];
                const key = match[2];
                // Convert to HTTPS URL
                return `https://${bucket}.s3.amazonaws.com/${key}`;
            }
        }
        
        // For relative paths or other formats, return as is
        return s3Url;
    }

    // ---- Show Source Content in Panel ----
    function showSourcePanel(details, displayText, pageNumber, s3Key, score, storeType = currentVectorStore) { 
        // Reset zoom level whenever a new source is shown
        currentZoomLevel = 1;
        updateZoom(); // Apply reset
        
        // Details object expected: {"text": "...", "image_url": "...", "total_pages": ...} 
        if (!details) {
            sourceContent.innerHTML = '<p class="error-source">Error: Received no details for source.</p>';
            return;
        }
        
        // Convert the S3 URL to an HTTPS URL that browsers can load
        const imageUrl = convertS3UrlToHttps(details.image_url);
        
        const totalPages = details.total_pages || 'N/A'; 

        // Clear previous content
        sourceContent.innerHTML = ''; 
        sourceContent.dataset.currentPage = pageNumber; 
        sourceContent.dataset.totalPages = totalPages;
        // Store the displayText (which contains the readable name) for navigation header
        const headerTextMatch = displayText.match(/^(.*?)\s*\(page\s*\d+\)$/i); 
        const readableSourceName = headerTextMatch ? headerTextMatch[1].trim() : displayText;
        sourceContent.dataset.readableSourceName = readableSourceName; 
        sourceContent.dataset.s3Key = s3Key;

        // Create a header for the source info
        const sourceHeader = document.createElement('div');
        sourceHeader.className = 'source-detail-header';
        sourceHeader.innerHTML = `
            <h4>${readableSourceName}</h4>
            <div class="source-metadata">
                <span class="page-info">Page ${pageNumber}${totalPages !== 'N/A' ? ` of ${totalPages}` : ''}</span>
                ${score ? `<span class="relevance-score">Relevance: ${Math.round(score * 100)}%</span>` : ''}
            </div>
        `;
        sourceContent.appendChild(sourceHeader);
        
        // Container for the image with overflow scroll
        const imageContainer = document.createElement('div');
        imageContainer.id = 'source-image-container';
        
        if (imageUrl) {
            // Add image container to DOM first
            sourceContent.appendChild(imageContainer);
            
            // Load the image
            const img = new Image();
            
            // Add a simple loading indicator
            imageContainer.innerHTML = `
                <div class="source-loading">
                    <div class="spinner"></div>
                </div>
            `;
            
            img.onload = function() {
                // Remove loading indicator
                imageContainer.innerHTML = '';
                imageContainer.appendChild(img);
                
                // Add zoom controls as overlay
                const zoomControls = document.createElement('div');
                zoomControls.className = 'image-zoom-controls';
                zoomControls.innerHTML = `
                    <button id="zoom-in-overlay" title="Zoom In"><i class="fas fa-search-plus"></i></button>
                    <button id="zoom-reset-overlay" title="Reset Zoom"><i class="fas fa-sync-alt"></i></button>
                    <button id="zoom-out-overlay" title="Zoom Out"><i class="fas fa-search-minus"></i></button>
                `;
                imageContainer.appendChild(zoomControls);
                
                // Add zoom functionality
                document.getElementById('zoom-in-overlay').addEventListener('click', () => {
                    if (currentZoomLevel < 2.5) {
                        currentZoomLevel += 0.25;
                        updateZoom();
                    }
                });
                
                document.getElementById('zoom-out-overlay').addEventListener('click', () => {
                    if (currentZoomLevel > 0.5) {
                        currentZoomLevel -= 0.25;
                        updateZoom();
                    }
                });
                
                document.getElementById('zoom-reset-overlay').addEventListener('click', () => {
                    currentZoomLevel = 1;
                    updateZoom();
                });
                
                // Add page navigation
                addSourceNavigation(pageNumber, totalPages, s3Key, storeType);
            };
            
            img.onerror = function() {
                imageContainer.innerHTML = `<p class="error-source">Error loading image. Please try again.</p>`;
            };
            
            img.src = imageUrl;
            img.alt = `Page ${pageNumber} of ${readableSourceName}`;
            img.style.transform = `scale(${currentZoomLevel})`;
            img.style.transformOrigin = 'center top';
            img.style.transition = 'transform 0.2s ease-out';
        } else {
            imageContainer.innerHTML = `<p class="error-source">No image available for this source.</p>`;
            sourceContent.appendChild(imageContainer);
        }
        
        // Show source panel if not already visible
        if (!sourcePanelOpen) {
            sourcePanel.classList.add('open');
            sourcePanelOpen = true;
        }
        
        // Update mobile toggle button if on mobile
        if (window.innerWidth <= 768 && mobileSourceToggle) {
            mobileSourceToggle.querySelector('i').classList.replace('fa-book', 'fa-times');
        }
    }

    // ---- Navigate Source Pages (Prev/Next) ----
    async function navigateSourcePage(direction, context) {
        const currentPage = parseInt(sourceContent.dataset.currentPage, 10);
        const totalPages = parseInt(sourceContent.dataset.totalPages, 10);
        const s3Key = context?.s3Key || sourceContent.dataset.s3Key;
        const readableSourceName = sourceContent.dataset.readableSourceName;
        const newPage = currentPage + direction;

        if (isNaN(newPage) || !s3Key || newPage < 1 || (!isNaN(totalPages) && newPage > totalPages)) {
            console.error('Invalid page navigation attempt', { newPage, totalPages, s3Key });
            return;
        }
        
        // Update UI immediately to show loading
        const pageIndicator = document.getElementById('source-page-indicator');
        const headerText = document.getElementById('source-panel-header-text');
        const imageContainer = document.getElementById('source-image-container');
        const prevButton = document.getElementById('source-prev-button');
        const nextButton = document.getElementById('source-next-button');

        if(pageIndicator) pageIndicator.textContent = `Page ${newPage}`;
        if(imageContainer) {
            imageContainer.innerHTML = `
                <div class="source-loading">
                    <div class="spinner"></div>
                </div>
            `;
        }
        if(prevButton) prevButton.disabled = true;
        if(nextButton) nextButton.disabled = true;
        
        try {
            const response = await fetch(`/api/get_context_details?source=${encodeURIComponent(s3Key)}&page=${newPage}&vector_store_type=${context?.storeType || currentVectorStore}`);
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
            }
            const details = await response.json();
            
            // Ensure we convert S3 URLs to HTTPS
            if (details.image_url && details.image_url.startsWith('s3://')) {
                details.image_url = convertS3UrlToHttps(details.image_url);
            }
            
            const newDisplayText = `${readableSourceName} (page ${newPage})`;
            // Call showSourcePanel without score for navigated pages
            showSourcePanel(details, newDisplayText, newPage, s3Key, undefined, context?.storeType || currentVectorStore); 
        } catch (error) {
            console.error('Error fetching details for navigated page:', error);
            if(imageContainer) imageContainer.innerHTML = `<p class="error-source">Error loading page ${newPage}: ${error.message}</p>`;
            // Re-enable buttons based on original page
            if(prevButton) prevButton.disabled = currentPage <= 1;
            if(nextButton) nextButton.disabled = isNaN(totalPages) || currentPage >= totalPages;
        }
    }

    // ---- Update Source Image Display ----
    function updateSourceImage(pageNumber) {
        const imageContainer = document.getElementById('source-image-container');
        const s3BaseUrl = sourceContent.dataset.s3BaseUrl;
        
        if (!imageContainer) return;
        
        imageContainer.innerHTML = '<p class="loading-source">Loading image...</p>'; // Show loading indicator
        
        if (!s3BaseUrl) {
            imageContainer.innerHTML = '<p class="error-source">Source image not available (URL missing).</p>';
            return; 
        }
        
        // Ensure we use HTTP URLs, not S3 URLs
        let imageUrl = `${s3BaseUrl}/page_${pageNumber}.png`;
        if (imageUrl.startsWith('s3://')) {
            imageUrl = convertS3UrlToHttps(imageUrl);
        }
        
        const img = document.createElement('img');
        img.src = imageUrl;
        img.alt = `Source page ${pageNumber}`;
        img.onload = () => {
            imageContainer.innerHTML = ''; // Clear loading indicator
            imageContainer.appendChild(img);
        };
        img.onerror = () => {
            imageContainer.innerHTML = `<p class="error-source">Error loading image for page ${pageNumber}.</p>`;
        };
    }

    /*
    ========================================
      API COMMUNICATION (SEND MESSAGE & SSE HANDLING)
    ========================================
    */
    function sendMessage() {
        const message = userInput.value.trim();
        if (!message) return;
        
        // Add the user's message to the chat
        addMessage(message, 'user');
        
        // Clear the input field
        userInput.value = '';
        
        // Cancel any existing response if there is one
        if (currentEventSource) {
            currentEventSource.close();
            currentEventSource = null;
        }
        
        // Add assistant message with thinking indicator
        const assistantMessageId = addMessage('', 'assistant');
        updateMessageText(assistantMessageId, 'Searching knowledge base', true); // Initial status
        
        // Encode the message for the URL
        const encodedMessage = encodeURIComponent(message);
        
        // Get current model
        const currentModel = llmModelDropdown ? llmModelDropdown.value : null;
        
        // Add vector store type and model to request
        const url = `/api/chat?message=${encodedMessage}&vector_store_type=${currentVectorStore}${currentModel ? `&model=${currentModel}` : ''}`;
        
        // Use Server-Sent Events (EventSource) for streaming
        currentEventSource = new EventSource(url);
        
        // Event listener for metadata
        currentEventSource.addEventListener('metadata', event => {
            const metadata = JSON.parse(event.data);
            
            // Store LLM and vector store info no longer needed since the display elements were removed
            
            // Add source pills if available
            if (metadata.sources && metadata.sources.length > 0) {
                // Add store_type to each source
                const sourcesWithStoreType = metadata.sources.map(source => ({
                    ...source,
                    store_type: metadata.store_type || currentVectorStore
                }));
                
                addSourcePills(assistantMessageId, sourcesWithStoreType);
                
                // Store context parts for this message
                messageContextParts[assistantMessageId] = metadata.sources;
            }
        });
        
        // Event listener for status updates
        currentEventSource.addEventListener('status', event => {
            try {
                const status = JSON.parse(event.data);
                // Update message with new status if provided
                if (status && status.status) {
                    updateMessageText(assistantMessageId, status.status, true);
                }
            } catch (e) {
                console.error('Error parsing status event:', e);
            }
        });
        
        // Event listener for streaming chunks of text
        currentEventSource.addEventListener('message', event => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'text' && data.content) {
                    // Update the message text with the new chunk
                    appendToMessage(assistantMessageId, data.content);
                }
            } catch (e) {
                console.error('Error parsing message event data:', e);
            }
        });
        
        // Event listener for errors
        currentEventSource.addEventListener('error', event => {
            console.error('SSE Error event triggered');
            
            // Close the event source to prevent further errors
            if (currentEventSource) {
                currentEventSource.close();
                currentEventSource = null;
            }
            
            // Only show an error message if we haven't received a done event
            if (event.data) {
                try {
                    const errorData = JSON.parse(event.data);
                    console.error('Error data:', errorData);
                    
                    // Update UI to show error
                    updateMessageText(
                        assistantMessageId, 
                        `<span class="error-message">Error: ${errorData.error || 'Connection to assistant lost.'}</span>`, 
                        false
                    );
                } catch (e) {
                    console.error('Error parsing error event data:', e);
                }
            }
        });
        
        // Event listener for completion (done)
        currentEventSource.addEventListener('done', event => {
            // Close the event source cleanly
            if (currentEventSource) {
                currentEventSource.close();
                currentEventSource = null;
            }
            
            // If the panel is expanded, refresh the expanded content view
            // to ensure it has the final formatted message content
            if (isPanelExpanded) {
                updateExpandedSourcePills();
            }
        });
        
        // Handle general connection errors
        currentEventSource.onerror = error => {
            console.error('EventSource general error:', error);
            
            // Close the connection if it's not already closed
            if (currentEventSource && currentEventSource.readyState !== 2) {
                currentEventSource.close();
                currentEventSource = null;
            }
        };
    }

    /*
    ========================================
      EVENT LISTENERS (Send Button, Input, Close Panel, ESC Key)
    ========================================
    */

    // ---- Send Button & Enter Key ----
    sendButton.addEventListener('click', sendMessage);
    
    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // ---- Close Panel Button ----
    closePanel.addEventListener('click', () => {
        if (sourcePanel.classList.contains('collapsing') || 
            sourcePanel.classList.contains('closing')) {
            return;
        }
        
        // If expanded, collapse first then close
        if (isPanelExpanded) {
            sourcePanel.classList.add('collapsing');
            
            setTimeout(() => {
                sourcePanel.classList.remove('expanded');
            }, 10);
            
            setTimeout(() => {
                sourcePanel.classList.remove('collapsing');
                sourcePanel.classList.add('closing');
                
                setTimeout(() => {
                    sourcePanel.classList.remove('open');
                    sourcePanel.classList.remove('closing');
                    sourcePanelOpen = false;
                    
                    // Remove active class from all source pills when panel is closed
                    document.querySelectorAll('.source-pill').forEach(pill => {
                        pill.classList.remove('active');
                    });
                    
                    // Update mobile toggle button if on mobile
                    if (window.innerWidth <= 768 && mobileSourceToggle) {
                        mobileSourceToggle.querySelector('i').classList.replace('fa-times', 'fa-book');
                    }
                }, 300);
            }, 300);
            
            expandPanel.innerHTML = '<i class="fas fa-external-link-alt"></i>';
            expandPanel.title = 'Expand';
            isPanelExpanded = false;
        } else {
            sourcePanel.classList.add('closing');
            
            setTimeout(() => {
                sourcePanel.classList.remove('open');
                sourcePanel.classList.remove('closing');
                sourcePanelOpen = false;
                
                // Remove active class from all source pills when panel is closed
                document.querySelectorAll('.source-pill').forEach(pill => {
                    pill.classList.remove('active');
                });
                
                // Update mobile toggle button if on mobile
                if (window.innerWidth <= 768 && mobileSourceToggle) {
                    mobileSourceToggle.querySelector('i').classList.replace('fa-times', 'fa-book');
                }
            }, 300); // Match the animation duration
        }
    });

    // ---- Add Source Navigation Buttons ----
    function addSourceNavigation(currentPage, totalPages, s3Key, storeType = currentVectorStore) {
        const sourceContent = document.getElementById('source-content');
        // Create navigation container
        const navContainer = document.createElement('div');
        navContainer.className = 'source-nav';
        
        // Previous button
        const prevButton = document.createElement('button');
        prevButton.innerHTML = '<i class="fas fa-arrow-left"></i> Previous';
        prevButton.disabled = currentPage <= 1;
        prevButton.addEventListener('click', () => navigateSourcePage(-1, { s3Key, currentPage, totalPages, storeType }));
        
        // Page indicator
        const pageIndicator = document.createElement('span');
        pageIndicator.textContent = `${currentPage} / ${totalPages}`;
        
        // Next button
        const nextButton = document.createElement('button');
        nextButton.innerHTML = 'Next <i class="fas fa-arrow-right"></i>';
        nextButton.disabled = totalPages === 'N/A' || currentPage >= parseInt(totalPages);
        nextButton.addEventListener('click', () => navigateSourcePage(1, { s3Key, currentPage, totalPages, storeType }));
        
        // Add elements to navigation container
        navContainer.appendChild(prevButton);
        navContainer.appendChild(pageIndicator);
        navContainer.appendChild(nextButton);
        
        // Add navigation to source content
        sourceContent.appendChild(navContainer);
    }

    // ---- ESC Key to Close Panel ----
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && (sourcePanelOpen || isPanelExpanded)) {
            if (isPanelExpanded) {
                sourcePanel.classList.add('collapsing');
                
                setTimeout(() => {
                    sourcePanel.classList.remove('expanded');
                    
                    setTimeout(() => {
                        sourcePanel.classList.remove('collapsing');
                        sourcePanel.classList.add('closing');
                        
                        setTimeout(() => {
                            sourcePanel.classList.remove('open');
                            sourcePanel.classList.remove('closing');
                            sourcePanelOpen = false;
                            isPanelExpanded = false;
                            
                            // Remove active class from all source pills when panel is closed
                            document.querySelectorAll('.source-pill').forEach(pill => {
                                pill.classList.remove('active');
                            });
                            
                            // Update expand button state
                            if (expandPanel) {
                                expandPanel.innerHTML = '<i class="fas fa-external-link-alt"></i>';
                                expandPanel.title = 'Expand';
                            }
                            
                            // Update mobile toggle button if on mobile
                            if (window.innerWidth <= 768 && mobileSourceToggle) {
                                mobileSourceToggle.querySelector('i').classList.replace('fa-times', 'fa-book');
                            }
                        }, 300);
                    }, 300);
                }, 10);
            } else {
                // Just close the panel normally
                sourcePanel.classList.add('closing');
                
                setTimeout(() => {
                    sourcePanel.classList.remove('open');
                    sourcePanel.classList.remove('closing');
                    sourcePanelOpen = false;
                    
                    // Remove active class from all source pills when panel is closed
                    document.querySelectorAll('.source-pill').forEach(pill => {
                        pill.classList.remove('active');
                    });
                    
                    // Update mobile toggle button if on mobile
                    if (window.innerWidth <= 768 && mobileSourceToggle) {
                        mobileSourceToggle.querySelector('i').classList.replace('fa-times', 'fa-book');
                    }
                }, 300);
            }
        }
    });
    
    // ---- Dynamic Tooltip Positioning ----
    document.addEventListener('mouseover', function(e) {
        // Check if the hovered element is a source pill with a tooltip
        if (e.target.classList.contains('source-pill') && e.target.dataset.tooltip) {
            const pill = e.target;
            const pillRect = pill.getBoundingClientRect();
            const tooltipWidth = 300; // Matches the max-width in CSS
            
            // Get the after and before pseudo-elements (tooltip and arrow)
            const tooltip = window.getComputedStyle(pill, '::after');
            const arrow = window.getComputedStyle(pill, '::before');
            
            // Check position relative to viewport
            const viewportWidth = window.innerWidth;
            const viewportHeight = window.innerHeight;
            
            // Calculate available space in each direction
            const spaceAbove = pillRect.top;
            const spaceBelow = viewportHeight - pillRect.bottom;
            const spaceLeft = pillRect.left;
            const spaceRight = viewportWidth - pillRect.right;
            
            // Determine if tooltip should go above, below, left or right
            let position = 'bottom'; // Default position
            
            if (spaceBelow < 150 && spaceAbove > 150) {
                // Not enough space below but enough space above
                position = 'top';
            } else if (pillRect.left < tooltipWidth / 2) {
                // Too close to left edge
                position = 'right-start';
            } else if (viewportWidth - pillRect.right < tooltipWidth / 2) {
                // Too close to right edge
                position = 'left-start';
            }
            
            // Apply custom positioning with inline styles
            switch (position) {
                case 'top':
                    pill.style.setProperty('--tooltip-top', 'auto');
                    pill.style.setProperty('--tooltip-bottom', '115%');
                    pill.style.setProperty('--tooltip-transform', 'translateX(-50%)');
                    pill.style.setProperty('--tooltip-arrow-top', 'auto');
                    pill.style.setProperty('--tooltip-arrow-bottom', '100%');
                    pill.style.setProperty('--tooltip-arrow-border-color', 'rgba(33, 33, 33, 0.9) transparent transparent transparent');
                    break;
                    
                case 'right-start':
                    pill.style.setProperty('--tooltip-top', '0');
                    pill.style.setProperty('--tooltip-left', '100%');
                    pill.style.setProperty('--tooltip-transform', 'translateY(0)');
                    pill.style.setProperty('--tooltip-arrow-top', '10px');
                    pill.style.setProperty('--tooltip-arrow-left', 'calc(100% - 5px)');
                    pill.style.setProperty('--tooltip-arrow-border-color', 'transparent rgba(33, 33, 33, 0.9) transparent transparent');
                    pill.style.setProperty('--tooltip-margin', '0 0 0 10px');
                    break;
                    
                case 'left-start':
                    pill.style.setProperty('--tooltip-top', '0');
                    pill.style.setProperty('--tooltip-left', 'auto');
                    pill.style.setProperty('--tooltip-right', '100%');
                    pill.style.setProperty('--tooltip-transform', 'translateY(0)');
                    pill.style.setProperty('--tooltip-arrow-top', '10px');
                    pill.style.setProperty('--tooltip-arrow-left', 'auto');
                    pill.style.setProperty('--tooltip-arrow-right', '-10px');
                    pill.style.setProperty('--tooltip-arrow-border-color', 'transparent transparent transparent rgba(33, 33, 33, 0.9)');
                    pill.style.setProperty('--tooltip-margin', '0 10px 0 0');
                    break;
                    
                default: // bottom (default)
                    pill.style.setProperty('--tooltip-top', '115%');
                    pill.style.setProperty('--tooltip-bottom', 'auto');
                    pill.style.setProperty('--tooltip-left', '50%');
                    pill.style.setProperty('--tooltip-right', 'auto');
                    pill.style.setProperty('--tooltip-transform', 'translateX(-50%)');
                    pill.style.setProperty('--tooltip-arrow-top', '110%');
                    pill.style.setProperty('--tooltip-arrow-bottom', 'auto');
                    pill.style.setProperty('--tooltip-arrow-left', '50%');
                    pill.style.setProperty('--tooltip-arrow-right', 'auto');
                    pill.style.setProperty('--tooltip-arrow-border-color', 'transparent transparent rgba(33, 33, 33, 0.9) transparent');
                    pill.style.setProperty('--tooltip-margin', '5px 0 0 0');
                    break;
            }
        }
    });
    
    // Clear custom positioning styles when leaving a pill
    document.addEventListener('mouseout', function(e) {
        if (e.target.classList.contains('source-pill') && e.target.dataset.tooltip) {
            const pill = e.target;
            // Reset any custom positioning
            pill.style.removeProperty('--tooltip-top');
            pill.style.removeProperty('--tooltip-bottom');
            pill.style.removeProperty('--tooltip-left');
            pill.style.removeProperty('--tooltip-right');
            pill.style.removeProperty('--tooltip-transform');
            pill.style.removeProperty('--tooltip-arrow-top');
            pill.style.removeProperty('--tooltip-arrow-bottom');
            pill.style.removeProperty('--tooltip-arrow-left');
            pill.style.removeProperty('--tooltip-arrow-right');
            pill.style.removeProperty('--tooltip-arrow-border-color');
            pill.style.removeProperty('--tooltip-margin');
        }
    });

    // Center the initial welcome message vertically
    function centerInitialMessage() {
        if (chatMessages.children.length === 1 && chatMessages.querySelector('.message.system')) {
            chatMessages.style.display = 'flex';
            chatMessages.style.justifyContent = 'center';
            chatMessages.style.alignItems = 'center';
        } else {
            chatMessages.style.display = 'block';
            chatMessages.style.justifyContent = '';
            chatMessages.style.alignItems = '';
        }
    }
    
    // Call it on initial load
    centerInitialMessage();
}); 