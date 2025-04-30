/**
 * dnd-utilities.js
 * Common utilities shared between desktop and mobile experiences
 */

// Module pattern for encapsulation
const DNDUtilities = (function() {
    /**
     * Format message text with markdown rendering
     * @param {string} text Raw message text
     * @returns {string} Formatted HTML
     */
    function formatMessageText(text) {
        console.log("[>>>formatMessageText] Input text length:", text?.length);
        if (!text) {
            console.log("[<<<formatMessageText] Returning empty string for no text.");
            return '';
        }

        try {
            if (typeof marked === 'undefined') {
                console.error("[!!!formatMessageText] marked library is NOT defined.");
                // Basic fallback: escape HTML characters and convert newlines
                const fallbackHtml = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>'); 
                console.log("[<<<formatMessageText] Returning fallback HTML (length:", fallbackHtml.length, ")");
                return fallbackHtml;
            }
            
            console.log("[>>>formatMessageText] marked library found. Calling marked.parse() with defaults...");
            // Use default marked options - this should handle basic markdown including links and breaks
            const parsedHtml = marked.parse(text); 
            console.log("[<<<formatMessageText] marked.parse successful. Output HTML length:", parsedHtml?.length);
            // console.log("[<<<formatMessageText] Sample Output:", parsedHtml?.substring(0, 300)); // Uncomment for detail
            return parsedHtml;
            
        } catch (error) {
            console.error("[!!!formatMessageText] CRITICAL ERROR:", error);
            // Ultimate fallback: return escaped text with simple line breaks
             const errorFallbackHtml = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
             console.log("[<<<formatMessageText] Returning ERROR fallback HTML (length:", errorFallbackHtml.length, ")");
             return errorFallbackHtml;
        }
    }
    
    /**
     * Process text for links
     * @param {HTMLElement} messageElement The message element to process
     * @param {Object} linkData Link data from the server
     */
    function processLinksInMessage(messageElement, linkData) {
        if (!messageElement || !linkData) {
            console.log("[Debug] processLinksInMessage: Exiting - No element or linkData.");
            return false;
        }
        
        const messageText = messageElement.querySelector('.message-text');
        if (!messageText) {
             console.log("[Debug] processLinksInMessage: Exiting - .message-text not found.");
            return false;
        }
        
        console.log("[Debug] processLinksInMessage: Starting link processing for element:", messageElement.className);
        const content = messageText.innerHTML;
        console.log("[Debug] processLinksInMessage: Initial innerHTML length:", content.length);
        
        // Create temporary element to work with the HTML
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = content;
        
        // Process all text nodes
        const textNodes = [];
        const walk = document.createTreeWalker(tempDiv, NodeFilter.SHOW_TEXT, null, false);
        let node;
        while (node = walk.nextNode()) {
             if (node.nodeValue.trim()) { // Only process non-empty text nodes
                textNodes.push(node);
             }
        }
        console.log(`[Debug] processLinksInMessage: Found ${textNodes.length} non-empty text nodes.`);

        // Check each text node for potential links
        let hasChanges = false;
        textNodes.forEach((textNode, index) => {
            const originalValue = textNode.nodeValue;
            let processedValue = originalValue;
            console.log(`[Debug] processLinksInMessage: Processing text node ${index}: "${originalValue.substring(0,50)}..."`);

            for (const [linkText, linkInfo] of Object.entries(linkData)) {
                try {
                    const regex = new RegExp(`(\\b${escapeRegExp(linkText)}\\b)`, 'gi');
                    if (regex.test(processedValue)) {
                        console.log(`[Debug] processLinksInMessage: Found match for "${linkText}" in node ${index}.`);
                        const typeClass = linkInfo.type === 'internal' ? 'internal-link' : 'external-link';
                        const attrs = linkInfo.type === 'internal' 
                            ? `data-s3-key="${linkInfo.s3_key || ''}" data-page="${linkInfo.page || ''}"` 
                            : `href="${linkInfo.url || '#'}" target="_blank"`;
                        
                        // IMPORTANT: Replace only within the current processedValue string, not globally
                        processedValue = processedValue.replace(regex, `<a class="${typeClass}" ${attrs}>$1</a>`);
                        hasChanges = true; // Mark that a change occurred in this node
                    }
                } catch (e) {
                    console.error(`[Debug] processLinksInMessage: Regex error for linkText "${linkText}":`, e);
                }
            }
            
            // If this specific node's text was modified, replace it in the tempDiv
            if (processedValue !== originalValue) {
                console.log(`[Debug] processLinksInMessage: Replacing node ${index} content.`);
                const fragment = document.createRange().createContextualFragment(processedValue);
                textNode.parentNode.replaceChild(fragment, textNode);
            }
        });
        
        // Only update the actual DOM if any changes were made across all text nodes
        if (hasChanges) {
            console.log("[Debug] processLinksInMessage: Changes detected, updating messageText.innerHTML.");
            messageText.innerHTML = tempDiv.innerHTML;
        } else {
            console.log("[Debug] processLinksInMessage: No link changes detected.");
        }
        
        return hasChanges;
    }
    
    /**
     * Fetch source content from the server
     * @param {string} s3Key S3 key of the source
     * @param {number} pageNumber Page number to fetch
     * @param {string} storeType Vector store type
     * @param {Function} onSuccess Success callback with details object
     * @param {Function} onError Error callback with error message
     */
    function fetchSourceContent(s3Key, pageNumber, storeType, onSuccess, onError) {
        // Debug log - can be removed after troubleshooting
        console.log('Fetching source content:', s3Key, pageNumber, storeType);
        
        fetch(`/api/get_context_details?source=${encodeURIComponent(s3Key)}&page=${pageNumber}&vector_store_type=${storeType}`)
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
                
                // Debug log - can be removed after troubleshooting
                console.log('Source details received:', {
                    hasImageBase64: !!details.image_base64,
                    imageBase64Length: details.image_base64 ? details.image_base64.length : 0,
                    hasImageUrl: !!details.image_url,
                    hasTextContent: !!(details.text_content || details.text),
                    totalPages: details.total_pages
                });
                
                // Ensure we have a uniform structure for both APIs
                if (details.text && !details.text_content) {
                    details.text_content = details.text;
                }
                
                // Setup image URL handling with multiple fallback options
                if (details.image_url) {
                    // Array of possible image loading strategies
                    const strategies = [];
                    
                    if (details.image_url.startsWith('s3://')) {
                        // 1. Primary strategy: Use the API proxy endpoint for S3 images
                        details.transformed_image_url = `/api/get_pdf_image?key=${encodeURIComponent(details.image_url)}`;
                        strategies.push({
                            name: 'api_proxy',
                            url: details.transformed_image_url,
                            description: 'Using API proxy for S3 image'
                        });
                        
                        // 2. Fallback: Direct S3 URL
                        const s3Url = details.image_url;
                        const s3Parts = s3Url.replace('s3://', '').split('/');
                        const bucket = s3Parts.shift();
                        const key = s3Parts.join('/');
                        details.direct_s3_url = `https://${bucket}.s3.amazonaws.com/${key}`;
                        strategies.push({
                            name: 'direct_s3',
                            url: details.direct_s3_url,
                            description: 'Using direct S3 URL'
                        });
                    } else if (details.image_url.includes('s3.amazonaws.com')) {
                        // Already a direct S3 URL, just ensure it's HTTPS
                        details.transformed_image_url = details.image_url.replace('http://', 'https://');
                        strategies.push({
                            name: 'direct_url',
                            url: details.transformed_image_url,
                            description: 'Using standardized S3 URL'
                        });
                    } else if (details.image_url.startsWith('/api/get_pdf_image')) {
                        // API endpoint URL - keep as is
                        details.transformed_image_url = details.image_url;
                        strategies.push({
                            name: 'api_endpoint',
                            url: details.transformed_image_url,
                            description: 'Using existing API endpoint URL'
                        });
                    } else {
                        // Any other URL format, use directly
                        details.transformed_image_url = details.image_url;
                        strategies.push({
                            name: 'direct_url',
                            url: details.transformed_image_url,
                            description: 'Using direct image URL'
                        });
                    }
                    
                    // If we have base64 data as well, add that as the last fallback
                    if (details.image_base64) {
                        strategies.push({
                            name: 'base64',
                            url: `data:image/jpeg;base64,${details.image_base64}`,
                            description: 'Using base64 image data'
                        });
                    }
                    
                    // Add strategies to details for use by clients
                    details.imageStrategies = strategies;
                    console.log('Image loading strategies:', strategies);
                }
                
                if (typeof onSuccess === 'function') {
                    onSuccess(details, s3Key, pageNumber);
                }
            })
            .catch(error => {
                console.error('Error fetching source details:', error);
                
                if (typeof onError === 'function') {
                    onError(error.message);
                }
            });
    }
    
    /**
     * Load an image with fallback strategies
     * @param {HTMLImageElement} imgElement The image element to load
     * @param {Array} strategies Array of image loading strategies 
     * @param {Function} onError Optional error callback
     */
    function loadImageWithFallback(imgElement, strategies, onError) {
        if (!imgElement || !strategies || strategies.length === 0) {
            console.error('Missing required parameters for loadImageWithFallback');
            return;
        }
        
        let currentIndex = 0;
        
        // Function to try the next strategy
        const tryNextStrategy = () => {
            if (currentIndex >= strategies.length) {
                console.error('All image loading strategies failed');
                if (typeof onError === 'function') {
                    onError('Failed to load image after trying all methods');
                }
                return;
            }
            
            const strategy = strategies[currentIndex];
            console.log(`Trying image strategy ${currentIndex + 1}/${strategies.length}: ${strategy.name}`);
            
            // Set the image source to the current strategy
            imgElement.src = strategy.url;
            currentIndex++;
        };
        
        // Add error handler to try next strategy on failure
        imgElement.onerror = () => {
            console.error(`Strategy ${currentIndex} failed: ${strategies[currentIndex - 1].name}`);
            tryNextStrategy();
        };
        
        // Start with the first strategy
        tryNextStrategy();
    }
    
    /**
     * Helper function to escape special characters in regex
     */
    function escapeRegExp(string) {
        return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }
    
    // Public API
    return {
        formatMessageText,
        processLinksInMessage,
        fetchSourceContent,
        loadImageWithFallback,
        escapeRegExp
    };
})();

// Make available globally
window.DNDUtilities = DNDUtilities; 