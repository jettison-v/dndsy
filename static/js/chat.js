document.addEventListener('DOMContentLoaded', () => {
    const chatMessages = document.getElementById('chat-messages');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');
    const sourcePanel = document.getElementById('source-panel');
    const sourceContent = document.getElementById('source-content');
    const closePanel = document.getElementById('close-panel');
    let isFirstMessage = true;

    // Function to add a message to the chat
    function addMessage(content, type, sources = null, contextParts = []) {
        if (isFirstMessage && type === 'user') {
            // Clear welcome message when first user message is sent
            chatMessages.innerHTML = '';
            isFirstMessage = false;
        }
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${type}`;
        
        // Add the main message content
        const messageParagraph = document.createElement('p');
        messageParagraph.innerHTML = content; // Use innerHTML in case of markdown/links later
        messageDiv.appendChild(messageParagraph);
        
        // Add sources if they exist
        if (sources && sources.length > 0 && contextParts && contextParts.length > 0) {
            const sourcePillsContainer = document.createElement('div');
            sourcePillsContainer.className = 'source-pills';
            
            // --- Display Top Source Pill --- 
            const topSource = sources[0];
            const topPill = document.createElement('span');
            topPill.className = 'source-pill';
            topPill.textContent = topSource;
            topPill.dataset.index = 0;
            topPill.addEventListener('click', () => {
                showSourceContent(0, contextParts);
            });
            sourcePillsContainer.appendChild(topPill);

            // --- "Show More" Button and Pills (if applicable) --- 
            if (sources.length > 1) {
                const remainingCount = sources.length - 1;

                // Create Show More Button
                const showMoreButton = document.createElement('button');
                showMoreButton.className = 'show-more-sources-button';
                showMoreButton.textContent = `Show ${remainingCount} more source${remainingCount > 1 ? 's' : ''}`;

                // Create Hide Button (initially hidden by CSS)
                const hideSourcesButton = document.createElement('button');
                hideSourcesButton.className = 'hide-sources-button'; // New class
                hideSourcesButton.textContent = 'Hide extra sources';

                // Add remaining pills (with extra class, initially hidden by CSS)
                for (let i = 1; i < sources.length; i++) {
                    const source = sources[i];
                    const pill = document.createElement('span');
                    pill.className = 'source-pill extra-source-pill'; // Add extra class
                    pill.textContent = source;
                    pill.dataset.index = i;
                    pill.addEventListener('click', () => { 
                        showSourceContent(i, contextParts);
                    });
                    sourcePillsContainer.appendChild(pill);
                }

                // Show More Button Logic
                showMoreButton.addEventListener('click', () => {
                    sourcePillsContainer.classList.add('extra-sources-visible');
                });

                // Hide Button Logic
                hideSourcesButton.addEventListener('click', () => {
                    sourcePillsContainer.classList.remove('extra-sources-visible');
                });
                
                // Append buttons
                sourcePillsContainer.appendChild(showMoreButton);
                sourcePillsContainer.appendChild(hideSourcesButton);
            }
            
            messageDiv.appendChild(sourcePillsContainer); // Append the container with pill(s) and button
        } 
        
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
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

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ message }),
            });

            const data = await response.json();
            
            // Log the raw data received from the API
            console.log("Received data from /api/chat:", data); 

            if (response.ok) {
                // Log what is being passed to addMessage
                console.log("Passing to addMessage:", {
                    response: data.response,
                    sources: data.sources,
                    context_parts: data.context_parts 
                });
                addMessage(data.response, 'assistant', data.sources, data.context_parts);
            } else {
                addMessage(`Error: ${data.error}`, 'system');
            }
        } catch (error) {
            addMessage('Error: Could not connect to the server', 'system');
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