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

    // Function to add a message to the chat
    function addMessage(text, sender, sources = [], contextParts = []) {
        const messageElement = document.createElement('div');
        messageElement.classList.add('message', sender);
        
        // Store context parts with a unique ID linked to the message
        const messageId = `msg-${Date.now()}-${Math.random().toString(16).substring(2)}`;
        messageElement.dataset.messageId = messageId;
        messageContextParts[messageId] = contextParts;

        // Sanitize text before setting innerHTML if needed, or use textContent
        // Using markdown rendering later would be safer
        messageElement.textContent = text; // Display text simply for now

        // Add source pills if available (for assistant messages)
        if (sender === 'assistant' && sources && sources.length > 0) {
            const sourceContainer = document.createElement('div');
            sourceContainer.className = 'source-pills';
            
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
                    // Clear current pills and show all
                    sourceContainer.innerHTML = ''; 
                    sources.forEach((source, index) => {
                        const sourcePill = createSourcePill(source, messageId, index);
                        sourceContainer.appendChild(sourcePill);
                    });
                };
                sourceContainer.appendChild(showMore);
            }
            messageElement.appendChild(sourceContainer);
        }
        
        chatMessages.appendChild(messageElement);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    // Function to update a message in the chat (for status updates)
    function updateMessage(messageId, newText) {
        const messageElement = chatMessages.querySelector(`[data-message-id="${messageId}"]`);
        if (messageElement) {
            // Potentially use a markdown parser here in the future
            messageElement.textContent = newText;
            chatMessages.scrollTop = chatMessages.scrollHeight; // Re-scroll
        }
    }

    // Function to add the final assistant message (replaces addMessage for assistant)
    function addAssistantResponse(messageId, text, sources = [], contextParts = []) {
        const messageElement = chatMessages.querySelector(`[data-message-id="${messageId}"]`);
        if (!messageElement) {
            console.error("Could not find placeholder message element to update:", messageId);
            addMessage(text, 'assistant', sources, contextParts); // Fallback to adding new
            return;
        }
        
        messageElement.classList.remove('thinking'); // Remove thinking style if any
        messageElement.textContent = text; // Set final text
        
        // Add source pills
        if (sources && sources.length > 0) {
            const sourceContainer = document.createElement('div');
            sourceContainer.className = 'source-pills';
            
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
                    // Clear current pills and show all
                    sourceContainer.innerHTML = ''; 
                    sources.forEach((source, index) => {
                        const sourcePill = createSourcePill(source, messageId, index);
                        sourceContainer.appendChild(sourcePill);
                    });
                };
                sourceContainer.appendChild(showMore);
            }
            messageElement.appendChild(sourceContainer);
        }

        // Update context parts map
        messageContextParts[messageId] = contextParts;

        chatMessages.scrollTop = chatMessages.scrollHeight; // Re-scroll
    }

    // Function to show source content in the side panel
    function showSourceContent(index, messageContextParts) {
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

    // Function to send message to the server
    async function sendMessage() {
        const message = userInput.value.trim();
        if (!message) return;

        // Add user message to chat
        addMessage(message, 'user');
        userInput.value = '';

        // Add initial "Thinking..." placeholder for the assistant
        const thinkingMessageId = `msg-${Date.now()}-${Math.random().toString(16).substring(2)}`;
        const thinkingElement = document.createElement('div');
        thinkingElement.classList.add('message', 'assistant', 'thinking'); // Add a 'thinking' class for potential styling
        thinkingElement.dataset.messageId = thinkingMessageId;
        thinkingElement.textContent = "Thinking...";
        chatMessages.appendChild(thinkingElement);
        chatMessages.scrollTop = chatMessages.scrollHeight;

        // Start simulated progress updates
        const timer1 = setTimeout(() => updateMessage(thinkingMessageId, "Searching knowledge base..."), 1000); // Update after 1 sec
        const timer2 = setTimeout(() => updateMessage(thinkingMessageId, "Consulting LLM..."), 3000); // Update after 3 secs total

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ message }),
            });
            
            // Clear timers once response is received
            clearTimeout(timer1);
            clearTimeout(timer2);

            const data = await response.json();
            console.log("Received data from /api/chat:", data);

            if (response.ok) {
                console.log("Passing to addAssistantResponse:", {
                    messageId: thinkingMessageId, 
                    response: data.response,
                    sources: data.sources,
                    context_parts: data.context_parts
                });
                // Update the placeholder with the final response
                addAssistantResponse(thinkingMessageId, data.response, data.sources, data.context_parts);

                // Update LLM Info display
                if (data.llm_provider && data.llm_model && llmInfoSpan) {
                    llmInfoSpan.textContent = `LLM: ${data.llm_provider} (${data.llm_model})`;
                }
            } else {
                // Update placeholder with error
                updateMessage(thinkingMessageId, `Error: ${data.error}`);
                chatMessages.querySelector(`[data-message-id="${thinkingMessageId}"]`)?.classList.remove('thinking');
                chatMessages.querySelector(`[data-message-id="${thinkingMessageId}"]`)?.classList.add('system'); // Style as system error
            }
        } catch (error) {
             // Clear timers on error
            clearTimeout(timer1);
            clearTimeout(timer2);
            // Update placeholder with connection error
            updateMessage(thinkingMessageId, 'Error: Could not connect to the server');
            chatMessages.querySelector(`[data-message-id="${thinkingMessageId}"]`)?.classList.remove('thinking');
            chatMessages.querySelector(`[data-message-id="${thinkingMessageId}"]`)?.classList.add('system'); // Style as system error
            console.error('Error:', error);
        }
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