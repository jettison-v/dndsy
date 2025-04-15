document.addEventListener('DOMContentLoaded', () => {
    /*
    ========================================
      VIEWPORT HEIGHT FIX FOR MOBILE
    ========================================
    */
    // First, set the viewport height custom property
    const setViewportHeight = () => {
        // For standard browsers, 100vh works fine
        // This is just a safety for older iOS browsers
        document.documentElement.style.height = '100%';
        document.body.style.height = '100%';
    };
    
    // Set the height initially
    setViewportHeight();
    
    // Update the height on resize and orientation change
    window.addEventListener('resize', setViewportHeight);
    window.addEventListener('orientationchange', () => {
        setTimeout(setViewportHeight, 100);
    });
    
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
    const mobileHeaderSourceToggle = document.getElementById('mobile-header-source-toggle');
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
    
    // Focus the input field on page load
    if (userInput) {
        setTimeout(() => {
            userInput.focus();
        }, 100);
    }

    // Add event listener for chat messages scroll
    if (chatMessages) {
        chatMessages.addEventListener('scroll', () => {
            // Recalculate viewport height when user scrolls
            // This helps with iOS Safari's dynamic address bar
            if (window.innerWidth <= 768) {
                setTimeout(setViewportHeight, 100);
            }
        });
    }

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
                                    (newStore === 'haystack-qdrant') ? 'Haystack (Qdrant)' :
                                    (newStore === 'haystack-memory') ? 'Haystack (Memory)' :
                                    newStore.charAt(0).toUpperCase() + newStore.slice(1);
            
            // Don't add system message on initial load - only for actual changes
            if (isFirstMessage === false) {
                addMessage(`Vector Store changed to ${storeDisplayName}`, 'system');
            }
        });
    }

    // Add event listener for LLM model changes
    if (llmModelDropdown) {
        // Set initial data-current-model to the current selected value
        const initialSelectedValue = llmModelDropdown.options[llmModelDropdown.selectedIndex].value;
        llmModelDropdown.setAttribute('data-current-model', initialSelectedValue);
        
        llmModelDropdown.addEventListener('change', async () => {
            const selectedIndex = llmModelDropdown.selectedIndex;
            const selectedOption = llmModelDropdown.options[selectedIndex];
            
            // Use actual selected value instead of relying on data attribute
            const oldValue = llmModelDropdown.getAttribute('data-current-model');
            const newValue = selectedOption.value;
            
            // Always set the data-current-model first to avoid race conditions
            llmModelDropdown.setAttribute('data-current-model', newValue);
            
            // Compare actual values
            if (oldValue === newValue) {
                return;
            }
            
            try {
                // Send request to change model
                const response = await fetch('/api/change_model', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ model: newValue }),
                });
                
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
                }
                
                const data = await response.json();
                
                // Don't add system message on initial load - only for actual changes
                if (isFirstMessage === false) {
                    const messageText = `Model changed to ${data.display_name}`;
                    addMessage(messageText, 'system');
                }
            } catch (error) {
                console.error('Error changing LLM model:', error);
                // Revert to previous selection on error
                llmModelDropdown.value = oldValue;
                addMessage(`Error changing model: ${error.message}`, 'system');
            }
        });
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
            } else if (currentValue === 'haystack-qdrant' || currentValue === 'haystack-memory' || currentValue === 'haystack') {
                showModal(document.getElementById('haystack-modal'));
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
                // Apply zoom directly to the image with better positioning
                img.style.transform = `scale(${currentZoomLevel})`;
                img.style.transformOrigin = 'center center';
                img.style.transition = 'transform 0.3s ease';
            }
        }
    }
    
    // ---- Mobile Source Toggle ----
    if (mobileSourceToggle) {
        mobileSourceToggle.addEventListener('click', toggleSourcePanel);
    }

    // ---- Mobile Header Source Toggle ----
    if (mobileHeaderSourceToggle) {
        mobileHeaderSourceToggle.addEventListener('click', toggleSourcePanel);
    }

    // ---- Toggle Source Panel (Open/Close) ----
    function toggleSourcePanel() {
        if (sourcePanel.classList.contains('collapsing') || 
            sourcePanel.classList.contains('closing')) {
            return; // Already in transition
        }
        
        if (sourcePanelOpen) {
            // Close panel
            sourcePanel.classList.add('closing');
            
            setTimeout(() => {
                sourcePanel.classList.remove('open');
                sourcePanel.classList.remove('closing');
                sourcePanelOpen = false;
                
                // Remove active class from all source pills when panel is closed
                document.querySelectorAll('.source-pill').forEach(pill => {
                    pill.classList.remove('active');
                });
                
                // Update mobile toggle buttons if on mobile
                if (window.innerWidth <= 768) {
                    if (mobileSourceToggle) {
                        mobileSourceToggle.querySelector('i').classList.replace('fa-times', 'fa-book');
                    }
                    if (mobileHeaderSourceToggle) {
                        mobileHeaderSourceToggle.querySelector('i').classList.replace('fa-times', 'fa-book');
                    }
                }
            }, 300); // Match the animation duration
        } else {
            // Open panel
            sourcePanel.classList.add('open');
            sourcePanelOpen = true;
            
            // Update mobile toggle buttons if on mobile
            if (window.innerWidth <= 768) {
                if (mobileSourceToggle) {
                    mobileSourceToggle.querySelector('i').classList.replace('fa-book', 'fa-times');
                }
                if (mobileHeaderSourceToggle) {
                    mobileHeaderSourceToggle.querySelector('i').classList.replace('fa-book', 'fa-times');
                }
            }
        }
    }

    /*
    ========================================
      CHAT MESSAGE HANDLING
    ========================================
    */

    // ---- Add Message to DOM ----
    function addMessage(text, sender, messageId = null) {
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
        
        if (sender === 'system' && (isVectorStoreMsg || isModelChangeMsg)) {
            messageElement.classList.add('setting-change');
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
        if (!details) {
            console.error("No details provided to showSourcePanel");
            return;
        }
        
        // Check if the panel isn't already open, and open it
        if (!sourcePanelOpen) {
            toggleSourcePanel();
        }
        
        // Clear any existing content
        sourceContent.innerHTML = '';
        
        // Add a header with source info
        const header = document.createElement('div');
        header.className = 'source-header';
        
        const sourceName = document.createElement('h4');
        sourceName.id = 'source-panel-header-text';
        sourceName.textContent = displayText;
        header.appendChild(sourceName);
        
        sourceContent.appendChild(header);
        
        // Add image container (for PDF preview)
        const imageContainer = document.createElement('div');
        imageContainer.id = 'source-image-container';
        imageContainer.className = 'source-image-container';
        
        // Create zoom controls inside the image container
        const zoomControls = document.createElement('div');
        zoomControls.className = 'image-zoom-controls';
        
        const zoomInBtn = document.createElement('button');
        zoomInBtn.innerHTML = '<i class="fas fa-search-plus"></i>';
        zoomInBtn.title = 'Zoom In';
        zoomInBtn.addEventListener('click', () => {
            if (currentZoomLevel < 2.5) {
                currentZoomLevel += 0.25;
                updateZoom();
            }
        });
        
        const zoomResetBtn = document.createElement('button');
        zoomResetBtn.innerHTML = '<i class="fas fa-sync-alt"></i>';
        zoomResetBtn.title = 'Reset Zoom';
        zoomResetBtn.addEventListener('click', () => {
            currentZoomLevel = 1;
            updateZoom();
        });
        
        const zoomOutBtn = document.createElement('button');
        zoomOutBtn.innerHTML = '<i class="fas fa-search-minus"></i>';
        zoomOutBtn.title = 'Zoom Out';
        zoomOutBtn.addEventListener('click', () => {
            if (currentZoomLevel > 0.5) {
                currentZoomLevel -= 0.25;
                updateZoom();
            }
        });
        
        zoomControls.appendChild(zoomInBtn);
        zoomControls.appendChild(zoomResetBtn);
        zoomControls.appendChild(zoomOutBtn);
        
        // Add placeholder for consistent sizing before image loads
        const placeholder = document.createElement('div');
        placeholder.className = 'image-placeholder';
        imageContainer.appendChild(placeholder);
        
        // Show loading indicator by default
        const loadingIndicator = document.createElement('div');
        loadingIndicator.className = 'image-loading';
        loadingIndicator.textContent = 'Loading image...';
        imageContainer.appendChild(loadingIndicator);
        
        // Add image container to the DOM immediately
        sourceContent.appendChild(imageContainer);
        
        // Process image if available
        if (details.image_url) {
            // Convert S3 URLs to HTTPS if needed
            let imageUrl = details.image_url;
            if (imageUrl.startsWith('s3://')) {
                imageUrl = convertS3UrlToHttps(imageUrl);
            }
            
            // Create and load the image
            const img = document.createElement('img');
            img.className = 'source-image';
            img.src = imageUrl;
            img.alt = `Source page ${pageNumber}`;
            
            // When image loads, replace loading indicator
            img.onload = () => {
                // Clear loading state
                placeholder.remove();
                loadingIndicator.remove();
                
                // Add image and zoom controls
                imageContainer.appendChild(img);
                imageContainer.appendChild(zoomControls);
                
                // Apply zoom if set
                updateZoom();
            };
            
            img.onerror = () => {
                imageContainer.innerHTML = '<p class="error-source">Error loading image</p>';
            };
        } else {
            // No image available
            imageContainer.innerHTML = '<p class="error-source">No image available for this source</p>';
        }
        
        // Store the relevant information in the sourceContent dataset
        sourceContent.dataset.currentPage = pageNumber;
        sourceContent.dataset.totalPages = details.total_pages || 'N/A';
        sourceContent.dataset.s3Key = s3Key;
        sourceContent.dataset.readableSourceName = displayText.split(' (page')[0]; // Extract source name without page
        
        // Add navigation (if applicable)
        addSourceNavigation(pageNumber, details.total_pages, s3Key, storeType);
    }

    // ---- Navigate Source Pages (Prev/Next) ----
    async function navigateSourcePage(direction, context) {
        const currentPage = parseInt(context?.currentPage || sourceContent.dataset.currentPage, 10);
        const s3Key = context?.s3Key || sourceContent.dataset.s3Key;
        const storeType = context?.storeType || currentVectorStore;
        
        if (!s3Key || isNaN(currentPage)) {
            console.error('Invalid page navigation: missing required data', { currentPage, s3Key });
            return;
        }
        
        // Calculate new page based on direction
        let newPage;
        if (direction === 'prev') {
            newPage = currentPage - 1;
            if (newPage < 1) {
                console.error('Cannot navigate to page below 1');
                return;
            }
        } else if (direction === 'next') {
            newPage = currentPage + 1;
            // We'll allow navigating to the next page even if we don't know total pages
        } else {
            console.error('Invalid navigation direction:', direction);
            return;
        }

        // Get the current image container
        const imageContainer = document.getElementById('source-image-container');
        if (!imageContainer) {
            console.error('Image container not found');
            return;
        }
        
        // Save the container size and position
        const containerRect = imageContainer.getBoundingClientRect();
        const containerHeight = containerRect.height;
        
        // Create loading overlay instead of replacing entire content
        const loadingOverlay = document.createElement('div');
        loadingOverlay.className = 'image-loading';
        loadingOverlay.textContent = `Loading page ${newPage}...`;
        imageContainer.appendChild(loadingOverlay);
        
        try {
            // Fetch the details for the new page
            const response = await fetch(`/api/get_context_details?source=${encodeURIComponent(s3Key)}&page=${newPage}&vector_store_type=${storeType}`);
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
            }
            
            const details = await response.json();
            if (!details) {
                throw new Error('No details returned from server');
            }
            
            // Get the readable source name from the current display or dataset
            const readableSourceName = sourceContent.dataset.readableSourceName || s3Key.split('/').pop().replace('.pdf', '');
            
            // Update the source panel with the new page
            showSourcePanel(details, `${readableSourceName} (page ${newPage})`, newPage, s3Key, undefined, storeType);
        } catch (error) {
            console.error('Error navigating to page:', error);
            
            // Show error in the existing container without replacing it
            loadingOverlay.textContent = `Error loading page ${newPage}: ${error.message}`;
            loadingOverlay.className = 'error-source';
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
    async function sendMessage() {
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
        updateMessageText(assistantMessageId, 'Thinking...', true);
        
        // Disable input while processing
        userInput.disabled = true;
        sendButton.disabled = true;
        sendButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

        // Encode the message for the URL
        const encodedMessage = encodeURIComponent(message);
        
        // Get current model
        const currentModel = llmModelDropdown ? llmModelDropdown.value : null;
        
        // Add vector store type and model to request
        const url = `/api/chat?message=${encodedMessage}&vector_store_type=${currentVectorStore}${currentModel ? `&model=${currentModel}` : ''}`;
        
        // Use Server-Sent Events (EventSource) for streaming
        currentEventSource = new EventSource(url);
        
        let accumulatedText = '';
        let sourcesReceived = [];
        let messageLinks = null;
        let renderComplete = false;

        // Event listener for metadata
        currentEventSource.addEventListener('metadata', event => {
            const metadata = JSON.parse(event.data);
            sourcesReceived = metadata.sources || [];
            
            // Store LLM and vector store info no longer needed since the display elements were removed
            
            // Add source pills if available
            const assistantMessage = chatMessages.querySelector(`[data-message-id="${assistantMessageId}"]`);
            if (assistantMessage && metadata.sources && metadata.sources.length > 0) {
                // Add store_type to each source
                const sourcesWithStoreType = metadata.sources.map(source => ({
                    ...source,
                    store_type: metadata.store_type || currentVectorStore
                }));
                
                addSourcePills(assistantMessageId, sourcesWithStoreType);
                
                // Add data attributes for LLM/Store info
                assistantMessage.dataset.llmProvider = metadata.llm_provider;
                assistantMessage.dataset.llmModel = metadata.llm_model;
                assistantMessage.dataset.storeType = metadata.store_type;

                // Show initial source if panel is open and sources exist
                if (sourcesReceived.length > 0 && sourcePanelOpen) {
                    const firstSource = sourcesReceived[0];
                    const firstPill = assistantMessage.querySelector(`.source-pill[data-s3-key="${firstSource.s3_key}"][data-page="${firstSource.page}"]`);
                    if (firstPill) {
                        firstPill.click();
                    } 
                }
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
        
        // Event listener for 'links' event
        currentEventSource.addEventListener('links', (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'links' && data.links) {
                    console.log("Received link data:", data.links);
                    messageLinks = data.links;
                    // If message rendering is already complete (done event arrived first), apply links now
                    if (renderComplete) {
                        const assistantMessage = chatMessages.querySelector(`[data-message-id="${assistantMessageId}"]`);
                        if (assistantMessage) {
                            console.log("Applying hyperlinks after receiving links (render already complete).");
                            applyHyperlinks(assistantMessage, messageLinks);
                        }
                    }
                }
            } catch (e) {
                console.error('Error parsing links event data:', e);
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
            
            // Re-enable input on error
            userInput.disabled = false;
            sendButton.disabled = false;
            sendButton.innerHTML = '<i class="fas fa-paper-plane"></i>';
            
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
            console.log("Received done event");
            renderComplete = true;
            
            // Close the event source cleanly
            if (currentEventSource) {
                currentEventSource.close();
                currentEventSource = null;
            }
            
            try {
                const data = JSON.parse(event.data);
                if (data.success) {
                    // Clear status/indicator only if message was successful
                    const textSpan = chatMessages.querySelector(`[data-message-id="${assistantMessageId}"] .message-text`);
                    if (textSpan) {
                        const indicator = textSpan.querySelector('.thinking-indicator');
                        if (indicator) indicator.remove();
                        const statusText = textSpan.querySelector('.status-text');
                        if (statusText) statusText.remove();
                    }

                    // If link data arrived *before* done, apply links now
                    if (messageLinks) {
                        const assistantMessage = chatMessages.querySelector(`[data-message-id="${assistantMessageId}"]`);
                        if (assistantMessage) {
                            console.log("Applying hyperlinks after receiving done (link data received earlier).");
                            applyHyperlinks(assistantMessage, messageLinks);
                        }
                    } else {
                        console.log("Done event received, but link data hasn't arrived yet (or no links found). Links will be applied when/if 'links' event arrives.");
                    }
                } else {
                    updateMessageText(assistantMessageId, 'Finished with errors', false);
                }
            } catch (e) {
                console.error("Error parsing done event data:", e);
                updateMessageText(assistantMessageId, 'Error processing completion', false);
            }
            
            // Re-enable input after done
            userInput.disabled = false;
            sendButton.disabled = false;
            sendButton.innerHTML = '<i class="fas fa-paper-plane"></i>';
            
            // If the panel is expanded, refresh the expanded content view
            // to ensure it has the final formatted message content
            if (isPanelExpanded) {
                updateExpandedSourcePills();
            }
            // Auto-scroll might be needed again after final render + link application
            chatMessages.scrollTop = chatMessages.scrollHeight;
            // Update centering after response is fully rendered
            centerInitialMessage();
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
                    
                    // Update mobile toggle buttons if on mobile
                    if (window.innerWidth <= 768) {
                        if (mobileSourceToggle) {
                            mobileSourceToggle.querySelector('i').classList.replace('fa-times', 'fa-book');
                        }
                        if (mobileHeaderSourceToggle) {
                            mobileHeaderSourceToggle.querySelector('i').classList.replace('fa-times', 'fa-book');
                        }
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
                
                // Update mobile toggle buttons if on mobile
                if (window.innerWidth <= 768) {
                    if (mobileSourceToggle) {
                        mobileSourceToggle.querySelector('i').classList.replace('fa-times', 'fa-book');
                    }
                    if (mobileHeaderSourceToggle) {
                        mobileHeaderSourceToggle.querySelector('i').classList.replace('fa-times', 'fa-book');
                    }
                }
            }, 300); // Match the animation duration
        }
    });

    // ---- Add Source Navigation Buttons ----
    function addSourceNavigation(currentPage, totalPages, s3Key, storeType = currentVectorStore) {
        // Find or create the navigation container
        let navContainer = document.querySelector('.source-navigation');
        if (!navContainer) {
            navContainer = document.createElement('div');
            navContainer.className = 'source-navigation';
            sourceContent.appendChild(navContainer);
        } else {
            // Clear existing navigation
            navContainer.innerHTML = '';
        }
        
        // Create the page indicator
        const pageIndicator = document.createElement('div');
        pageIndicator.className = 'page-indicator';
        
        // Format page number and handle N/A total pages
        const formattedTotalPages = totalPages && totalPages !== 'N/A' ? totalPages : '?';
        pageIndicator.textContent = `${currentPage} / ${formattedTotalPages}`;
        
        // Create navigation buttons
        const prevButton = document.createElement('button');
        prevButton.innerHTML = '<i class="fas fa-chevron-left"></i> Prev';
        prevButton.className = 'nav-button prev-button';
        prevButton.disabled = currentPage <= 1;
        prevButton.addEventListener('click', () => {
            navigateSourcePage('prev', { 
                currentPage: currentPage, 
                s3Key: s3Key,
                storeType: storeType
            });
        });
        
        const nextButton = document.createElement('button');
        nextButton.innerHTML = 'Next <i class="fas fa-chevron-right"></i>';
        nextButton.className = 'nav-button next-button';
        
        // Only disable next if we know the total pages and are at the last page
        nextButton.disabled = totalPages && totalPages !== 'N/A' && currentPage >= totalPages;
        
        nextButton.addEventListener('click', () => {
            navigateSourcePage('next', { 
                currentPage: currentPage, 
                s3Key: s3Key,
                storeType: storeType
            });
        });
        
        // Append elements to navigation container
        navContainer.appendChild(prevButton);
        navContainer.appendChild(pageIndicator);
        navContainer.appendChild(nextButton);
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
                            
                            // Update mobile toggle buttons if on mobile
                            if (window.innerWidth <= 768) {
                                if (mobileSourceToggle) {
                                    mobileSourceToggle.querySelector('i').classList.replace('fa-times', 'fa-book');
                                }
                                if (mobileHeaderSourceToggle) {
                                    mobileHeaderSourceToggle.querySelector('i').classList.replace('fa-times', 'fa-book');
                                }
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
                    
                    // Update mobile toggle buttons if on mobile
                    if (window.innerWidth <= 768) {
                        if (mobileSourceToggle) {
                            mobileSourceToggle.querySelector('i').classList.replace('fa-times', 'fa-book');
                        }
                        if (mobileHeaderSourceToggle) {
                            mobileHeaderSourceToggle.querySelector('i').classList.replace('fa-times', 'fa-book');
                        }
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
            
            if (spaceBelow < 200 && spaceAbove > 200) {
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
                    pill.style.setProperty('--tooltip-bottom', '130%');
                    pill.style.setProperty('--tooltip-transform', 'translateX(-50%)');
                    pill.style.setProperty('--tooltip-arrow-top', 'auto');
                    pill.style.setProperty('--tooltip-arrow-bottom', '120%');
                    pill.style.setProperty('--tooltip-arrow-border-color', 'rgba(20, 20, 20, 0.95) transparent transparent transparent');
                    pill.style.setProperty('--tooltip-margin', '0');
                    break;
                    
                case 'right-start':
                    pill.style.setProperty('--tooltip-top', '0');
                    pill.style.setProperty('--tooltip-left', 'calc(100% + 15px)');
                    pill.style.setProperty('--tooltip-transform', 'translateY(-25%)');
                    pill.style.setProperty('--tooltip-arrow-top', '25%');
                    pill.style.setProperty('--tooltip-arrow-left', 'calc(100% + 5px)');
                    pill.style.setProperty('--tooltip-arrow-border-color', 'transparent rgba(20, 20, 20, 0.95) transparent transparent');
                    pill.style.setProperty('--tooltip-margin', '0');
                    break;
                    
                case 'left-start':
                    pill.style.setProperty('--tooltip-top', '0');
                    pill.style.setProperty('--tooltip-left', 'auto');
                    pill.style.setProperty('--tooltip-right', 'calc(100% + 15px)');
                    pill.style.setProperty('--tooltip-transform', 'translateY(-25%)');
                    pill.style.setProperty('--tooltip-arrow-top', '25%');
                    pill.style.setProperty('--tooltip-arrow-left', 'auto');
                    pill.style.setProperty('--tooltip-arrow-right', 'calc(100% + 5px)');
                    pill.style.setProperty('--tooltip-arrow-border-color', 'transparent transparent transparent rgba(20, 20, 20, 0.95)');
                    pill.style.setProperty('--tooltip-margin', '0');
                    break;
                    
                default: // bottom 
                    pill.style.setProperty('--tooltip-top', '130%');
                    pill.style.setProperty('--tooltip-bottom', 'auto');
                    pill.style.setProperty('--tooltip-left', '50%');
                    pill.style.setProperty('--tooltip-transform', 'translateX(-50%)');
                    pill.style.setProperty('--tooltip-arrow-top', 'calc(100% + 2px)');
                    pill.style.setProperty('--tooltip-arrow-bottom', 'auto');
                    pill.style.setProperty('--tooltip-arrow-left', '50%');
                    pill.style.setProperty('--tooltip-arrow-border-color', 'transparent transparent rgba(20, 20, 20, 0.95) transparent');
                    pill.style.setProperty('--tooltip-margin', '8px 0 0 0');
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

    // Update the storeChangeCounter and show toast when store changes
    function handleStoreChange(newStore) {
        storeChangeCounter++;
        // Reset any previous search when store changes
        clearSearchResults();

        // Show toast
        let formattedStoreName = newStore;
        
        // Format the store name for display
        if (newStore === "haystack-qdrant") {
            formattedStoreName = "Haystack (Qdrant)";
        } else if (newStore === "haystack-memory") {
            formattedStoreName = "Haystack (Memory)";
        } else if (newStore === "chromadb") {
            formattedStoreName = "ChromaDB";
        } else if (newStore === "pinecone") {
            formattedStoreName = "Pinecone";
        }
        
        let toastHTML = `<span>Vector store changed to ${formattedStoreName}</span>`;
        M.toast({html: toastHTML, classes: 'rounded'});
        
        // Update the currentVectorStore global
        currentVectorStore = newStore;
    }
}); 