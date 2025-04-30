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
        // Use the shared utility
        return window.DNDUtilities ? DNDUtilities.formatMessageText(text) : text;
    }
    
    /**
     * Process text for links
     * @param {HTMLElement} messageElement The message element to process
     * @param {Object} linkData Link data from the server
     */
    function processLinksInMessage(messageElement, linkData) {
        // Use the shared utility, but add our own event handlers for mobile
        if (window.DNDUtilities) {
            const hasLinks = DNDUtilities.processLinksInMessage(messageElement, linkData);
            
            // If links were added, add our mobile-specific event listeners
            if (hasLinks) {
                // Add event listeners for internal links
                messageElement.querySelectorAll('.internal-link').forEach(link => {
                    link.addEventListener('click', (e) => {
                        e.preventDefault();
                        const s3Key = link.getAttribute('data-s3-key');
                        const page = link.getAttribute('data-page');
                        if (s3Key && page) {
                            // Trigger source content viewer
                            if (window.mobileUI && window.mobileUI.openSourcePanel) {
                                const pillsContainer = messageElement.querySelector('.source-pills-container');
                                if (pillsContainer) {
                                    // Find matching pill if it exists
                                    const pill = Array.from(pillsContainer.children).find(
                                        p => p.dataset.s3Key === s3Key && p.dataset.page === page
                                    );
                                    if (pill) {
                                        pill.click();
                                    }
                                } else {
                                    // No pill, just open source panel and fetch content
                                    window.mobileUI.openSourcePanel();
                                    fetchSourceContent(s3Key, page, 'semantic');
                                }
                            }
                        }
                    });
                });
            }
            return hasLinks;
        }
        return false;
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
                
                // Handle typed responses
                if (data.type === 'text' && data.content) {
                    if (!currentStreamedMessage) {
                        // Replace loading indicator with actual message
                        if (loadingMessage && loadingMessage.parentNode) {
                            chatMessages.removeChild(loadingMessage);
                        }
                        currentStreamedMessage = addAIMessage('');
                    }
                    
                    // Append token to current message
                    const messageText = currentStreamedMessage.querySelector('.message-text');
                    messageText.innerHTML += data.content;
                    
                    // Scroll to keep up with new content
                    scrollToBottom();
                }
                // Keeping original 'token' handler for backward compatibility
                else if (data.token) {
                    if (!currentStreamedMessage) {
                        // Replace loading indicator with actual message
                        if (loadingMessage && loadingMessage.parentNode) {
                            chatMessages.removeChild(loadingMessage);
                        }
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
                    if (currentStreamedMessage && !currentStreamedMessage.querySelector('.source-pills-container')) {
                        const pillsContainer = document.createElement('div');
                        pillsContainer.className = 'source-pills-container';
                        currentStreamedMessage.appendChild(pillsContainer);
                    }
                    
                    const pillsContainer = currentStreamedMessage.querySelector('.source-pills-container');
                    if (pillsContainer) {
                        // Process each source
                        data.sources.forEach(source => {
                            // Check if pill for this source already exists
                            const sourceId = `${source.s3_key}-${source.page}`;
                            if (!document.getElementById(sourceId)) {
                                const pill = document.createElement('div');
                                pill.className = 'source-pill';
                                pill.id = sourceId;
                                
                                // Format source name to be more concise: "Document Name (Pg X)"
                                let displayName = source.filename || source.s3_key.split('/').pop().replace(/\.[^/.]+$/, "");
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
                                pill.dataset.storeType = vectorStoreType;
                                
                                // Add click handler to pill for displaying source content
                                pill.addEventListener('click', function() {
                                    // Open source panel if available
                                    if (window.mobileUI && window.mobileUI.openSourcePanel) {
                                        window.mobileUI.openSourcePanel();
                                    }
                                    
                                    // Fetch and display source content
                                    fetchSourceContent(source.s3_key, source.page, vectorStoreType);
                                });
                                
                                pillsContainer.appendChild(pill);
                            }
                        });
                    }
                    
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
        
        // Add specific event handlers for SSE events
        eventSource.addEventListener('error', (event) => {
            console.error('EventSource error:', event);
            
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
        });
        
        // Handle metadata event
        eventSource.addEventListener('metadata', (event) => {
            try {
                const data = JSON.parse(event.data);
                console.log('Received metadata:', data);
                
                // Create a message if none exists yet
                if (!currentStreamedMessage) {
                    if (loadingMessage && loadingMessage.parentNode) {
                        chatMessages.removeChild(loadingMessage);
                    }
                    currentStreamedMessage = addAIMessage('');
                }
                
                // Handle sources if available
                if (data.sources && data.sources.length > 0 && currentStreamedMessage) {
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
                            pill.dataset.storeType = vectorStoreType;
                            
                            // Add click handler to pill for displaying source content
                            pill.addEventListener('click', function() {
                                // Open source panel if available
                                if (window.mobileUI && window.mobileUI.openSourcePanel) {
                                    window.mobileUI.openSourcePanel();
                                }
                                
                                // Fetch and display source content
                                fetchSourceContent(source.s3_key, source.page, vectorStoreType);
                            });
                            
                            pillsContainer.appendChild(pill);
                        }
                    });
                }
            } catch (error) {
                console.error('Error parsing metadata event:', error);
            }
        });
        
        // Handle links event
        eventSource.addEventListener('links', (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'links' && data.links && currentStreamedMessage) {
                    // Process links in the current message
                    processLinksInMessage(currentStreamedMessage, data.links);
                }
            } catch (error) {
                console.error('Error parsing links event:', error);
            }
        });
        
        // Handle done event
        eventSource.addEventListener('done', (event) => {
            eventSource.close();
            isWaitingForResponse = false;
            currentStreamedMessage = null;
        });
        
        // Handle error event
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
     * Fetch and display source content
     * @param {string} s3Key The S3 key of the source
     * @param {number} page The page number
     * @param {string} storeType The vector store type
     */
    function fetchSourceContent(s3Key, page, storeType) {
        // Get the source panel content element
        const sourceContent = document.getElementById('source-content');
        if (!sourceContent) return;
        
        // Show loading indicator
        sourceContent.innerHTML = '<div class="source-loading"><div class="spinner"></div><p>Loading source content...</p></div>';
        
        // Use the shared utility
        if (window.DNDUtilities) {
            DNDUtilities.fetchSourceContent(
                s3Key, 
                page, 
                storeType, 
                // Success callback
                (details, s3Key, pageNumber) => {
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
                    if (details.image_base64) {
                        // Display image content
                        const imageContainer = document.createElement('div');
                        imageContainer.id = 'source-image-container';
                        imageContainer.className = 'source-image-container';
                        
                        const img = document.createElement('img');
                        img.className = 'source-image';
                        img.alt = `${filename} (page ${page})`;
                        
                        // Use the shared utility for image loading if available
                        if (window.DNDUtilities && details.imageStrategies) {
                            // Use the shared image loading utility with the provided strategies
                            DNDUtilities.loadImageWithFallback(img, details.imageStrategies, (errorMsg) => {
                                console.error('Image loading failed:', errorMsg);
                                img.alt = 'Error loading image';
                                img.style.display = 'none';
                                imageContainer.innerHTML += `<p class="error-source">Failed to load image after trying all methods.</p>`;
                            });
                        } else {
                            // Fallback to basic approach if utilities aren't available
                            // Handle different image sources appropriately
                            if (details.transformed_image_url) {
                                // Use pre-transformed URL from utilities
                                img.src = details.transformed_image_url;
                                console.log('Using transformed image URL:', img.src);
                            } else if (details.image_url) {
                                // Transform S3 URLs to HTTP URLs if needed
                                if (details.image_url.startsWith('s3://')) {
                                    // Use API proxy for S3 images
                                    img.src = `/api/get_pdf_image?key=${encodeURIComponent(details.image_url)}`;
                                    console.log('Using API proxy for S3 image:', img.src);
                                } else {
                                    img.src = details.image_url;
                                }
                            } else if (details.image_base64) {
                                img.src = `data:image/jpeg;base64,${details.image_base64}`;
                            }
                            
                            // Add error handler for debugging
                            img.onerror = (e) => {
                                console.error('Failed to load image:', e);
                                console.error('Image src was:', img.src);
                                
                                // Try fallback to direct S3 URL if available
                                if (details.direct_s3_url && img.src !== details.direct_s3_url) {
                                    console.log('Trying fallback to direct S3 URL:', details.direct_s3_url);
                                    img.src = details.direct_s3_url;
                                    return; // Stop here to let the fallback attempt work
                                }
                                
                                // If fallback also fails or isn't available
                                img.alt = 'Error loading image';
                                img.style.display = 'none';
                                imageContainer.innerHTML += `<p class="error-source">Error loading image.<br>URL: ${img.src.substring(0, 100)}...</p>`;
                            };
                        }
                        
                        imageContainer.appendChild(img);
                        sourceContent.appendChild(imageContainer);
                        
                        // Native pinch-zoom is used instead of custom zoom controls
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
                        addSourceNavigation(sourceContent, parseInt(page), details.total_pages, s3Key, storeType);
                    }
                },
                // Error callback
                (errorMsg) => {
                    sourceContent.innerHTML = `<p class="error-source">Error: ${errorMsg}</p>`;
                }
            );
        } else {
            // Fallback if utility isn't available
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
                    if (!details) {
                        throw new Error('No details returned from server');
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
                    if (details.image_base64) {
                        // Display image content
                        const imageContainer = document.createElement('div');
                        imageContainer.id = 'source-image-container';
                        imageContainer.className = 'source-image-container';
                        
                        const img = document.createElement('img');
                        img.className = 'source-image';
                        img.alt = `${filename} (page ${page})`;
                        
                        // Use the shared utility for image loading if available
                        if (window.DNDUtilities && details.imageStrategies) {
                            // Use the shared image loading utility with the provided strategies
                            DNDUtilities.loadImageWithFallback(img, details.imageStrategies, (errorMsg) => {
                                console.error('Image loading failed:', errorMsg);
                                img.alt = 'Error loading image';
                                img.style.display = 'none';
                                imageContainer.innerHTML += `<p class="error-source">Failed to load image after trying all methods.</p>`;
                            });
                        } else {
                            // Fallback to basic approach if utilities aren't available
                            // Handle different image sources appropriately
                            if (details.transformed_image_url) {
                                // Use pre-transformed URL from utilities
                                img.src = details.transformed_image_url;
                                console.log('Using transformed image URL:', img.src);
                            } else if (details.image_url) {
                                // Transform S3 URLs to HTTP URLs if needed
                                if (details.image_url.startsWith('s3://')) {
                                    // Use API proxy for S3 images
                                    img.src = `/api/get_pdf_image?key=${encodeURIComponent(details.image_url)}`;
                                    console.log('Using API proxy for S3 image:', img.src);
                                } else {
                                    img.src = details.image_url;
                                }
                            } else if (details.image_base64) {
                                img.src = `data:image/jpeg;base64,${details.image_base64}`;
                            }
                            
                            // Add error handler for debugging
                            img.onerror = (e) => {
                                console.error('Failed to load image:', e);
                                console.error('Image src was:', img.src);
                                
                                // Try fallback to direct S3 URL if available
                                if (details.direct_s3_url && img.src !== details.direct_s3_url) {
                                    console.log('Trying fallback to direct S3 URL:', details.direct_s3_url);
                                    img.src = details.direct_s3_url;
                                    return; // Stop here to let the fallback attempt work
                                }
                                
                                // If fallback also fails or isn't available
                                img.alt = 'Error loading image';
                                img.style.display = 'none';
                                imageContainer.innerHTML += `<p class="error-source">Error loading image.<br>URL: ${img.src.substring(0, 100)}...</p>`;
                            };
                        }
                        
                        imageContainer.appendChild(img);
                        sourceContent.appendChild(imageContainer);
                        
                        // Native pinch-zoom is used instead of custom zoom controls
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
                        addSourceNavigation(sourceContent, parseInt(page), details.total_pages, s3Key, storeType);
                    }
                })
                .catch(error => {
                    console.error('Error fetching source content:', error);
                    sourceContent.innerHTML = `<p class="error-source">Error: ${error.message}</p>`;
                });
        }
    }
    
    /**
     * Add source navigation buttons
     * @param {HTMLElement} container The container element
     * @param {number} currentPage Current page number
     * @param {number} totalPages Total number of pages
     * @param {string} s3Key S3 key for the source
     * @param {string} storeType Vector store type
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