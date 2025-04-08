document.addEventListener('DOMContentLoaded', () => {
    const chatMessages = document.getElementById('chat-messages');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');
    const sourcePanel = document.getElementById('source-panel');
    const sourceContent = document.getElementById('source-content');
    const closePanel = document.getElementById('close-panel');
    const llmInfoSpan = document.getElementById('llm-info');
    let isFirstMessage = true;
    let messageContextParts = {};
    let currentEventSource = null;

    // Function to add a message to the chat
    function addMessage(text, sender, messageId = null) {
        const messageElement = document.createElement('div');
        messageElement.classList.add('message', sender);
        
        const id = messageId || `msg-${Date.now()}-${Math.random().toString(16).substring(2)}`;
        messageElement.dataset.messageId = id;
        
        // Create a span for the main text content
        const textSpan = document.createElement('span');
        textSpan.className = 'message-text'; 
        
        // Render markdown for assistant, otherwise use textContent
        if (sender === 'assistant') {
            // Ensure marked is loaded
            if (typeof marked === 'function') { 
                textSpan.innerHTML = marked.parse(text || ""); // Use marked to parse markdown
            } else {
                console.error("marked.js not loaded. Displaying raw text.");
                textSpan.textContent = text; // Fallback
            }
        } else {
            textSpan.textContent = text; // User/System messages as plain text
        }
        messageElement.appendChild(textSpan);
        
        // Placeholder for source pills container (added later if needed)
        const sourceContainer = document.createElement('div');
        sourceContainer.className = 'source-pills';
        sourceContainer.style.display = 'none'; // Hide initially
        messageElement.appendChild(sourceContainer);
        
        chatMessages.appendChild(messageElement);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        return id;
    }
    
    // Function to append text to the message text span
    function appendToMessage(messageId, textChunk) {
        const textSpan = chatMessages.querySelector(`[data-message-id="${messageId}"] .message-text`);
        if (textSpan) {
            // Append raw text chunk
            textSpan.textContent += textChunk;
            // Re-parse the whole content with marked (might be slightly inefficient but ensures correct rendering)
            if (typeof marked === 'function') {
                 // Store current scroll position
                 const isScrolledToBottom = chatMessages.scrollHeight - chatMessages.clientHeight <= chatMessages.scrollTop + 1;
                 
                 textSpan.innerHTML = marked.parse(textSpan.textContent || "");
                 
                 // Restore scroll position if it was at the bottom
                 if (isScrolledToBottom) {
                     chatMessages.scrollTop = chatMessages.scrollHeight;
                 }
            } else {
                 // Fallback if marked not loaded (shouldn't happen)
                 chatMessages.scrollTop = chatMessages.scrollHeight; 
            }
        }
    }

    // Function to add source pills (appends to existing container)
    function addSourcePills(messageId, sources, contextParts) {
        const messageElement = chatMessages.querySelector(`[data-message-id="${messageId}"]`);
        const sourceContainer = messageElement?.querySelector('.source-pills'); // Find the container
         if (!sourceContainer || !sources || sources.length === 0) return;

         messageContextParts[messageId] = contextParts;
         sourceContainer.innerHTML = ''; // Clear previous pills if any (e.g., on error)
         
         const MAX_VISIBLE_PILLS = 3;
         let sourcesToShow = sources;
         let hiddenCount = 0;

         if (sources.length > MAX_VISIBLE_PILLS) {
             sourcesToShow = sources.slice(0, MAX_VISIBLE_PILLS);
             hiddenCount = sources.length - MAX_VISIBLE_PILLS;
         }

         sourcesToShow.forEach((source, index) => {
             const sourcePill = createSourcePill(source, messageId, index);
             sourceContainer.appendChild(sourcePill);
         });

         if (hiddenCount > 0) {
             const showMore = document.createElement('a');
             showMore.href = '#';
             showMore.textContent = `Show ${hiddenCount} more source${hiddenCount > 1 ? 's' : ''}`;
             showMore.className = 'show-more-sources';
             showMore.onclick = (e) => {
                 e.preventDefault();
                 sourceContainer.innerHTML = ''; 
                 sources.forEach((source, index) => {
                     const sourcePill = createSourcePill(source, messageId, index);
                     sourceContainer.appendChild(sourcePill);
                 });
             };
             sourceContainer.appendChild(showMore);
         }
         sourceContainer.style.display = 'flex'; // Show the container
         // messageElement.appendChild(sourceContainer); // No longer need to append here
    }
    
    // Function to update message text (used for status)
    function updateMessageText(messageId, newText, showIndicator = true) {
        const textSpan = chatMessages.querySelector(`[data-message-id="${messageId}"] .message-text`);
        if (textSpan) {
            let content = newText;
            if (showIndicator) {
                content += ' <span class="thinking-indicator"><span></span><span></span><span></span></span>';
            }
            // Status messages are temporary, don't parse markdown here
            textSpan.innerHTML = content; 
            chatMessages.scrollTop = chatMessages.scrollHeight; 
        }
    }

    // Helper function to create a source pill element
    function createSourcePill(sourceText, messageId, index) {
        const pill = document.createElement('span');
        pill.className = 'source-pill';
        pill.textContent = sourceText;
        pill.dataset.messageId = messageId;
        pill.dataset.index = index;
        pill.addEventListener('click', () => {
            const contextParts = messageContextParts[messageId];
            if (contextParts && contextParts[index]) {
                showSourcePanel(contextParts, index);
            } else {
                console.error('Could not find context data for source pill', messageId, index);
            }
        });
        return pill;
    }

    // Function to show source content in the side panel
    function showSourcePanel(messageContextParts, index) {
        if (!messageContextParts || !messageContextParts[index]) {
            console.error(`No context part found for index: ${index}`);
            return;
        }
        
        const part = messageContextParts[index];
        
        // Clear previous content
        sourceContent.innerHTML = ''; 
        sourceContent.dataset.currentPage = part.page; // Store current state
        sourceContent.dataset.totalPages = part.total_pages;
        sourceContent.dataset.sourceDir = part.source_dir;
        sourceContent.dataset.sourceName = part.source; // Original source name
        // Store base S3 URL pattern if available, removing the filename part
        if (part.image_url) {
            const urlParts = part.image_url.split('/');
            urlParts.pop(); // Remove the filename (e.g., page_84.png)
            sourceContent.dataset.s3BaseUrl = urlParts.join('/'); 
        } else {
             sourceContent.dataset.s3BaseUrl = ''; // Handle case where image URL might be missing
        }
        // sourceContent.dataset.imagePattern = `/static/pdf_page_images/${part.source_dir}/page_{page}.png`; // REMOVED old static pattern

        // --- Header --- 
        const header = document.createElement('h4');
        header.id = 'source-panel-header-text'; // ID for easy updates
        header.textContent = `${part.source} (Page ${part.page} of ${part.total_pages || 'N/A'})`;
        sourceContent.appendChild(header);
        
        // --- Relevance Score --- 
        const scoreP = document.createElement('p');
        scoreP.className = 'source-score';
        scoreP.textContent = `Relevance: ${(part.score * 100).toFixed(1)}%`;
        sourceContent.appendChild(scoreP);

        // --- Image Container (for potential loading states) ---
        const imageContainer = document.createElement('div');
        imageContainer.id = 'source-image-container';
        sourceContent.appendChild(imageContainer);

        // --- Navigation --- 
        const navContainer = document.createElement('div');
        navContainer.className = 'source-nav';

        const prevButton = document.createElement('button');
        prevButton.id = 'source-prev-button';
        prevButton.textContent = 'Previous';
        prevButton.disabled = part.page <= 1;
        prevButton.addEventListener('click', () => navigateSourcePage(-1));

        const pageIndicator = document.createElement('span');
        pageIndicator.id = 'source-page-indicator';
        pageIndicator.textContent = `Page ${part.page} / ${part.total_pages || 'N/A'}`;

        const nextButton = document.createElement('button');
        nextButton.id = 'source-next-button';
        nextButton.textContent = 'Next';
        nextButton.disabled = !part.total_pages || part.page >= part.total_pages;
        nextButton.addEventListener('click', () => navigateSourcePage(1));

        navContainer.appendChild(prevButton);
        navContainer.appendChild(pageIndicator);
        navContainer.appendChild(nextButton);
        sourceContent.appendChild(navContainer);
        
        // --- Initial Image Load --- 
        updateSourceImage(part.page);

        // --- Active Pill Update --- 
        document.querySelectorAll('.source-pill').forEach(pill => {
            pill.classList.remove('active');
            if (pill.dataset.index === index.toString()) {
                pill.classList.add('active');
            }
        });
        
        // Show the panel
        sourcePanel.classList.add('open');
    }

    // Add the new navigateSourcePage function
    function navigateSourcePage(direction) {
        const currentPage = parseInt(sourceContent.dataset.currentPage, 10);
        const totalPages = parseInt(sourceContent.dataset.totalPages, 10);
        const newPage = currentPage + direction;

        if (isNaN(totalPages) || newPage < 1 || newPage > totalPages) {
            console.error('Invalid page navigation attempt');
            return;
        }

        updateSourceImage(newPage);
    }

    // Add the new updateSourceImage function
    function updateSourceImage(pageNumber) {
        const imageContainer = document.getElementById('source-image-container');
        const headerText = document.getElementById('source-panel-header-text');
        const pageIndicator = document.getElementById('source-page-indicator');
        const prevButton = document.getElementById('source-prev-button');
        const nextButton = document.getElementById('source-next-button');
        const totalPages = parseInt(sourceContent.dataset.totalPages, 10);
        const sourceName = sourceContent.dataset.sourceName;
        const s3BaseUrl = sourceContent.dataset.s3BaseUrl; // Get the base S3 URL

        if (!imageContainer || !s3BaseUrl || !headerText || !pageIndicator || !prevButton || !nextButton) {
            if (!s3BaseUrl) {
                 imageContainer.innerHTML = '<p style="color: orange; font-style: italic;">Source image not available (S3 URL missing).</p>';
                 return; // Don't proceed if no base URL
            }
            console.error('Required elements or base URL for image update not found');
            return;
        }

        // Construct the full S3 URL for the target page
        const imageUrl = `${s3BaseUrl}/page_${pageNumber}.png`;

        // Update stored state
        sourceContent.dataset.currentPage = pageNumber;

        // Clear previous image/loading state
        imageContainer.innerHTML = '<p>Loading page...</p>'; // Simple loading indicator

        const img = new Image(); // Use new Image() for better loading checks
        img.alt = `Source image: ${sourceName} - Page ${pageNumber}`;
        img.style.width = '100%';
        img.style.height = 'auto';
        img.style.display = 'block';
        img.style.marginTop = '1rem';

        img.onload = () => {
            imageContainer.innerHTML = ''; // Clear loading indicator
            imageContainer.appendChild(img);
        };
        img.onerror = () => {
            imageContainer.innerHTML = '<p style="color: red; font-style: italic;">Error loading page image.</p>';
        };
        img.src = imageUrl; // Start loading

        // Update header and indicator
        const totalPagesDisplay = isNaN(totalPages) ? 'N/A' : totalPages;
        headerText.textContent = `${sourceName} (Page ${pageNumber} of ${totalPagesDisplay})`;
        pageIndicator.textContent = `Page ${pageNumber} / ${totalPagesDisplay}`;

        // Update button states
        prevButton.disabled = pageNumber <= 1;
        nextButton.disabled = isNaN(totalPages) || pageNumber >= totalPages;
    }

    // Function to send message and handle SSE stream
    function sendMessage() {
        const message = userInput.value.trim();
        if (!message) return;

        // Stop any previous stream if it's still running
        if (currentEventSource) {
            currentEventSource.close();
            console.log("Closed previous EventSource connection.");
        }

        addMessage(message, 'user');
        userInput.value = '';

        // Add placeholder for assistant message with initial status
        const assistantMessageId = addMessage("", 'assistant'); 
        updateMessageText(assistantMessageId, 'Searching knowledge base', true); // Show indicator after text

        // --- Use EventSource for streaming --- 
        // Pass message via query parameter (simple approach, consider security/length limits)
        // Alternatively, initiate SSE connection first, then send message via separate POST
        const queryParams = new URLSearchParams({ message: message });
        currentEventSource = new EventSource(`/api/chat?${queryParams.toString()}`);
        console.log("EventSource connected.");

        let isFirstTextChunk = true; // Track first text chunk

        currentEventSource.onmessage = function(event) {
            console.log("SSE message received:", event.data);
            try {
                const data = JSON.parse(event.data);
                
                if (data.type === 'text') {
                    if (isFirstTextChunk) {
                        // Clear status text AND indicator from the text span
                        const textSpan = chatMessages.querySelector(`[data-message-id="${assistantMessageId}"] .message-text`);
                        if (textSpan) textSpan.innerHTML = ""; 
                        isFirstTextChunk = false;
                    }
                    appendToMessage(assistantMessageId, data.content);
                }
                // Note: Metadata event is handled by onopen or a specific event type
            } catch (e) {
                console.error("Failed to parse SSE data:", event.data, e);
                // Maybe display raw data or an error?
                appendToMessage(assistantMessageId, ` [Error parsing data: ${event.data}] `);
            }
        };

        currentEventSource.addEventListener('status', function(event) {
            console.log("SSE status received:", event.data);
             try {
                const statusData = JSON.parse(event.data);
                 // Update the text span with the new status, keep indicator
                 updateMessageText(assistantMessageId, statusData.status || 'Processing', true);
            } catch (e) {
                console.error("Failed to parse SSE status:", event.data, e);
            }
        });

        currentEventSource.addEventListener('metadata', function(event) {
            console.log("SSE metadata received:", event.data);
             try {
                const metadata = JSON.parse(event.data);
                 // Update LLM Info display
                 if (metadata.llm_provider && metadata.llm_model && llmInfoSpan) {
                     llmInfoSpan.textContent = `LLM: ${metadata.llm_provider} (${metadata.llm_model})`;
                 }
                 // Add source pills (will append to the dedicated container)
                 addSourcePills(assistantMessageId, metadata.sources, metadata.context_parts);

            } catch (e) {
                console.error("Failed to parse SSE metadata:", event.data, e);
            }
        });

        currentEventSource.addEventListener('error', function(event) {
            console.error("SSE Error event:", event);
            let errorMsg = "Error communicating with server.";
             try {
                // Attempt to parse error data if backend sends JSON in error event
                 const errorData = JSON.parse(event.data); 
                 if(errorData.error) errorMsg = errorData.error;
             } catch(e) { /* Ignore if not JSON */ }

            const assistantMsgElement = chatMessages.querySelector(`[data-message-id="${assistantMessageId}"]`);
            if (assistantMsgElement) {
                 const textSpan = assistantMsgElement.querySelector('.message-text');
                 // Update text span, explicitly no indicator needed for error message
                 if(textSpan) updateMessageText(assistantMessageId, `Error: ${errorMsg}`, false);
                 assistantMsgElement.classList.remove('assistant');
                 assistantMsgElement.classList.add('system');
            }
            currentEventSource.close(); // Close connection on error
            currentEventSource = null;
        });

         currentEventSource.addEventListener('end', function(event) {
            console.log("SSE stream ended.");
            currentEventSource.close();
            currentEventSource = null;
            // Optional: Check if the text span is still empty/showing indicator
            const textSpan = chatMessages.querySelector(`[data-message-id="${assistantMessageId}"] .message-text`);
            // Check if empty OR if it still contains only the indicator span
            if (textSpan && (textSpan.textContent.trim() === "" || textSpan.querySelector('.thinking-indicator'))) { 
                // Update text span, explicitly no indicator
                updateMessageText(assistantMessageId, "(No text received)", false);
            }
        });

        // Note: The old try/catch around fetch is removed as errors are handled by EventSource listeners
    }

    // Event listeners
    sendButton.addEventListener('click', sendMessage);
    
    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Close panel button
    closePanel.addEventListener('click', () => {
        sourcePanel.classList.remove('open');
        document.querySelectorAll('.source-pill').forEach(pill => {
            pill.classList.remove('active');
        });
    });
}); 