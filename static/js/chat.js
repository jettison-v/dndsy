document.addEventListener('DOMContentLoaded', () => {
    const chatMessages = document.getElementById('chat-messages');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');
    const sourcePanel = document.getElementById('source-panel');
    const sourceContent = document.getElementById('source-content');
    const closePanel = document.getElementById('close-panel');
    const llmInfoSpan = document.getElementById('llm-info');
    const mobileSourceToggle = document.getElementById('mobile-source-toggle');
    const zoomInBtn = document.getElementById('zoom-in');
    const zoomOutBtn = document.getElementById('zoom-out');
    const zoomResetBtn = document.getElementById('zoom-reset');
    
    let isFirstMessage = true;
    let messageContextParts = {};
    let currentEventSource = null;
    let currentZoomLevel = 1;
    
    // Initialize source panel state
    let sourcePanelOpen = false;

    // Add zoom functionality
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
    
    // Mobile source panel toggle
    if (mobileSourceToggle) {
        mobileSourceToggle.addEventListener('click', () => {
            sourcePanelOpen = !sourcePanelOpen;
            if (sourcePanelOpen) {
                sourcePanel.classList.add('open');
                mobileSourceToggle.querySelector('i').classList.replace('fa-book', 'fa-times');
            } else {
                sourcePanel.classList.remove('open');
                mobileSourceToggle.querySelector('i').classList.replace('fa-times', 'fa-book');
            }
        });
    }

    // Function to add a message to the chat
    function addMessage(text, sender, messageId = null) {
        const messageElement = document.createElement('div');
        messageElement.classList.add('message', sender);
        
        const id = messageId || `msg-${Date.now()}-${Math.random().toString(16).substring(2)}`;
        messageElement.dataset.messageId = id;
        
        // Create a span for the main text content
        const textSpan = document.createElement('span');
        textSpan.className = 'message-text'; 
        
        // Set initial text (parsing happens in appendToMessage)
        textSpan.textContent = text; 
        
        messageElement.appendChild(textSpan);
        
        // Placeholder for source pills container (added later if needed)
        const sourceContainer = document.createElement('div');
        sourceContainer.className = 'source-pills';
        sourceContainer.style.display = 'none'; // Hide initially
        messageElement.appendChild(sourceContainer);
        
        // Apply slide-in animation
        messageElement.style.animationDuration = '0.3s';
        
        chatMessages.appendChild(messageElement);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        return id;
    }
    
    // Function to append text to the message text span
    function appendToMessage(messageId, textChunk) {
        const messageElement = chatMessages.querySelector(`[data-message-id="${messageId}"]`);
        if (!messageElement) {
            console.error("Failed to find message element for ID:", messageId);
            return;
        }
        
        const textSpan = messageElement.querySelector('.message-text');
        if (!textSpan) {
            console.error("Failed to find text span within message element:", messageId);
            return;
        }
        
        // Remove the thinking indicator if it exists and we are appending real text
        const indicator = textSpan.querySelector('.thinking-indicator');
        if (indicator) {
            indicator.remove();
        }

        // Directly append text chunk
        textSpan.textContent += textChunk;
    }

    // Function to add source pills (appends to existing container)
    function addSourcePills(messageId, sources /* contextParts removed */) {
        const messageElement = chatMessages.querySelector(`[data-message-id="${messageId}"]`);
        const sourceContainer = messageElement?.querySelector('.source-pills'); // Find the container
         if (!sourceContainer || !sources || sources.length === 0) return;

         // Removed: messageContextParts[messageId] = contextParts;
         sourceContainer.innerHTML = ''; // Clear previous pills if any (e.g., on error)
         
         // --- Logic to parse source name and page from source string --- 
         // REMOVED: No longer needed as backend sends structured data
         /* 
         const parseSourceString = (sourceStr) => { ... };
         */
         // --- End parsing logic --- 

         const MAX_VISIBLE_PILLS = 3;
         let sourcesToShow = sources; // sources is now a list of objects
         let hiddenCount = 0;

         if (sources.length > MAX_VISIBLE_PILLS) {
             sourcesToShow = sources.slice(0, MAX_VISIBLE_PILLS);
             hiddenCount = sources.length - MAX_VISIBLE_PILLS;
         }

         sourcesToShow.forEach((sourceObj, index) => {
             // sourceObj = { display: "... (page X)", s3_key: "...", page: X, score: Y }
             if (sourceObj && sourceObj.display && sourceObj.s3_key && sourceObj.page) {
                 const sourcePill = createSourcePill(sourceObj.display, messageId, sourceObj.s3_key, sourceObj.page, sourceObj.score);
                 sourceContainer.appendChild(sourcePill);
             } else {
                 console.warn("Invalid source object received:", sourceObj);
             }
         });

         if (hiddenCount > 0) {
             const showMore = document.createElement('a');
             showMore.href = '#';
             showMore.textContent = `Show ${hiddenCount} more source${hiddenCount > 1 ? 's' : ''}`;
             showMore.className = 'show-more-sources';
             showMore.onclick = (e) => {
                 e.preventDefault();
                 sourceContainer.innerHTML = ''; 
                 sources.forEach((sourceObj, index) => { // Iterate full list
                     if (sourceObj && sourceObj.display && sourceObj.s3_key && sourceObj.page) {
                         const sourcePill = createSourcePill(sourceObj.display, messageId, sourceObj.s3_key, sourceObj.page, sourceObj.score);
                         sourceContainer.appendChild(sourcePill);
                     } else {
                         console.warn("Invalid source object received when showing more:", sourceObj);
                     }
                 });
             };
             sourceContainer.appendChild(showMore);
         }
         sourceContainer.style.display = 'flex'; // Show the container
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
    // Now takes score
    function createSourcePill(displayText, messageId, s3Key, pageNumber, score) {
        const pill = document.createElement('span');
        pill.className = 'source-pill';
        pill.textContent = displayText; // Keep original display text
        pill.dataset.messageId = messageId;
        pill.dataset.s3Key = s3Key;
        pill.dataset.pageNumber = pageNumber;
        pill.dataset.score = score !== undefined ? score : ''; // Store score
        
        pill.addEventListener('click', async () => { // Make listener async
            // Clear previous active states
            document.querySelectorAll('.source-pill').forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            
            // Show loading state in panel
            sourceContent.innerHTML = '<p class="loading-source">Loading source details...</p>';
            sourcePanel.classList.add('open');
            
            const currentScore = pill.dataset.score;
            // Log the values being sent
            console.log(`Fetching details for: s3Key='${s3Key}', pageNumber='${pageNumber}', score='${currentScore}'`);
            
            try {
                // Send s3Key as the 'source' parameter
                const response = await fetch(`/api/get_context_details?source=${encodeURIComponent(s3Key)}&page=${pageNumber}`);
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
                }
                const details = await response.json();
                // Pass fetched details, original displayText, s3Key, AND score to showSourcePanel
                showSourcePanel(details, displayText, pageNumber, s3Key, currentScore);
                
            } catch (error) {
                console.error('Error fetching source details:', error);
                sourceContent.innerHTML = `<p class="error-source">Error loading source: ${error.message}</p>`;
            }
        });
        return pill;
    }

    // Function to show source content in the side panel
    // Modified to accept score and implement zoom
    function showSourcePanel(details, displayText, pageNumber, s3Key, score) { 
        // Details object expected: {"text": "...", "image_url": "...", "total_pages": ...} 
        if (!details) {
            sourceContent.innerHTML = '<p class="error-source">Error: Received no details for source.</p>';
            return;
        }
        
        const imageUrl = details.image_url;
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
        
        // Reset zoom level
        currentZoomLevel = 1;
        
        // Container for the image with overflow scroll
        const imageContainer = document.createElement('div');
        imageContainer.id = 'source-image-container';
        
        if (imageUrl) {
            // Show loading indicator
            imageContainer.innerHTML = `<p class="loading-source">Loading page image...</p>`;
            sourceContent.appendChild(imageContainer);
            
            // Load the image
            const img = new Image();
            img.onload = function() {
                // Remove loading indicator
                imageContainer.innerHTML = '';
                imageContainer.appendChild(img);
                
                // Add page navigation
                addSourceNavigation(pageNumber, totalPages, s3Key);
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
        sourcePanel.classList.add('open');
        sourcePanelOpen = true;
        
        // Update mobile toggle button if on mobile
        if (window.innerWidth <= 768 && mobileSourceToggle) {
            mobileSourceToggle.querySelector('i').classList.replace('fa-book', 'fa-times');
        }
    }

    // Navigate source page
    async function navigateSourcePage(direction) {
        const currentPage = parseInt(sourceContent.dataset.currentPage, 10);
        const totalPages = parseInt(sourceContent.dataset.totalPages, 10);
        // Need the S3 Key for the API call - how do we get it here?
        // We could store it on sourceContent.dataset when showSourcePanel is first called.
        // Let's assume we stored it: sourceContent.dataset.s3Key 
        // !!! This requires adding sourceContent.dataset.s3Key = s3Key in showSourcePanel !!!
        const s3Key = sourceContent.dataset.s3Key; // NEED TO ADD THIS TO showSourcePanel
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

        if(pageIndicator) pageIndicator.textContent = `Loading page ${newPage}...`;
        if(headerText) headerText.textContent = `${readableSourceName} (Loading page ${newPage}...)`;
        if(imageContainer) imageContainer.innerHTML = '<p class="loading-source">Loading image...</p>';
        if(prevButton) prevButton.disabled = true;
        if(nextButton) nextButton.disabled = true;
        
        try {
            const response = await fetch(`/api/get_context_details?source=${encodeURIComponent(s3Key)}&page=${newPage}`);
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
            }
            const details = await response.json();
            const newDisplayText = `${readableSourceName} (page ${newPage})`;
            // Call showSourcePanel without score for navigated pages
            showSourcePanel(details, newDisplayText, newPage, s3Key, undefined); 
        } catch (error) {
            console.error('Error fetching details for navigated page:', error);
            if(imageContainer) imageContainer.innerHTML = `<p class="error-source">Error loading page ${newPage}: ${error.message}</p>`;
            // Re-enable buttons based on original page maybe?
            if(prevButton) prevButton.disabled = currentPage <= 1;
            if(nextButton) nextButton.disabled = isNaN(totalPages) || currentPage >= totalPages;
        }
    }

    // Update source image - simplified as showSourcePanel now handles most state
    function updateSourceImage(pageNumber) {
        const imageContainer = document.getElementById('source-image-container');
        const s3BaseUrl = sourceContent.dataset.s3BaseUrl;
        
        if (!imageContainer) return;
        
        imageContainer.innerHTML = '<p class="loading-source">Loading image...</p>'; // Show loading indicator
        
        if (!s3BaseUrl) {
            imageContainer.innerHTML = '<p class="error-source">Source image not available (URL missing).</p>';
            return; 
        }
        
        const imageUrl = `${s3BaseUrl}/page_${pageNumber}.png`;
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
                 addSourcePills(assistantMessageId, metadata.sources);

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
            
            const textSpan = chatMessages.querySelector(`[data-message-id="${assistantMessageId}"] .message-text`);
            
            if (textSpan) {
                console.log("Attempting final parse. typeof window.marked:", typeof window.marked);
                const fullText = textSpan.textContent || "";
                let generatedHtml = null;

                // Check if marked is loaded, could be function or object with .parse
                if (typeof window.marked === 'function') {
                    generatedHtml = window.marked(fullText); // Use marked directly if it's the function
                } else if (typeof window.marked === 'object' && typeof window.marked.parse === 'function') {
                    generatedHtml = window.marked.parse(fullText); // Use marked.parse if it's a method
                }
                
                if (generatedHtml !== null) {
                    textSpan.innerHTML = generatedHtml;
                    // Ensure code blocks are highlighted after rendering
                    // highlightCodeBlocks(textSpan); // Temporarily comment out
                } else {
                    console.error("Marked function or marked.parse not found after stream end. Cannot parse markdown.");
                    // Keep the textContent as is
                }
                
                // Remove indicator if somehow still present
                const indicator = textSpan.querySelector('.thinking-indicator');
                if (indicator) indicator.remove();
            } else {
                 console.error("Failed to find text span after stream end for ID:", assistantMessageId);
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

    // Handle close panel button
    closePanel.addEventListener('click', () => {
        sourcePanel.classList.remove('open');
        sourcePanelOpen = false;
        
        // Update mobile toggle button if on mobile
        if (window.innerWidth <= 768 && mobileSourceToggle) {
            mobileSourceToggle.querySelector('i').classList.replace('fa-times', 'fa-book');
        }
    });

    // Function to add navigation to source panel
    function addSourceNavigation(currentPage, totalPages, s3Key) {
        const sourceContent = document.getElementById('source-content');
        // Create navigation container
        const navContainer = document.createElement('div');
        navContainer.className = 'source-nav';
        
        // Previous button
        const prevButton = document.createElement('button');
        prevButton.innerHTML = '<i class="fas fa-arrow-left"></i> Previous';
        prevButton.disabled = currentPage <= 1;
        prevButton.addEventListener('click', () => navigateSourcePage(-1));
        
        // Page indicator
        const pageIndicator = document.createElement('span');
        pageIndicator.textContent = `${currentPage} / ${totalPages}`;
        
        // Next button
        const nextButton = document.createElement('button');
        nextButton.innerHTML = 'Next <i class="fas fa-arrow-right"></i>';
        nextButton.disabled = totalPages === 'N/A' || currentPage >= parseInt(totalPages);
        nextButton.addEventListener('click', () => navigateSourcePage(1));
        
        // Add elements to navigation container
        navContainer.appendChild(prevButton);
        navContainer.appendChild(pageIndicator);
        navContainer.appendChild(nextButton);
        
        // Add navigation to source content
        sourceContent.appendChild(navContainer);
    }
}); 