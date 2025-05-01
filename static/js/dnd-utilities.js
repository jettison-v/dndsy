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
     * Process text for links using direct DOM manipulation.
     * @param {HTMLElement} messageElement The message element to process
     * @param {Object} linkData Link data from the server (already filtered/sorted)
     */
    function processLinksInMessage(messageElement, linkData) {
        if (!messageElement || !linkData || Object.keys(linkData).length === 0) {
            console.log("[DNDUtils Debug] processLinks: Exiting - No element or linkData.");
            return false;
        }

        const messageTextElement = messageElement.querySelector('.message-text');
        if (!messageTextElement) {
            console.log("[DNDUtils Debug] processLinks: Exiting - .message-text not found.");
            return false;
        }

        console.log(`[DNDUtils Debug] processLinks: Starting link processing for element: ${messageElement.className}, Links: ${Object.keys(linkData).length}`);
        let hasChanges = false;

        try {
            // Use TreeWalker to find text nodes, ignoring those inside existing links or code blocks
            const walker = document.createTreeWalker(
                messageTextElement,
                NodeFilter.SHOW_TEXT,
                {
                    acceptNode: function(node) {
                        // Ignore nodes within existing <a>, <pre>, or <code> tags
                        if (node.parentElement.closest('a, pre, code')) {
                            return NodeFilter.FILTER_REJECT;
                        }
                        // Accept non-empty text nodes
                        if (node.nodeValue.trim() === '') {
                            return NodeFilter.FILTER_REJECT;
                        }
                        return NodeFilter.FILTER_ACCEPT;
                    }
                },
                false
            );

            let node;
            const nodesToProcess = [];
            while (node = walker.nextNode()) {
                nodesToProcess.push(node);
            }
            console.log(`[DNDUtils Debug] Found ${nodesToProcess.length} text nodes to process.`);

            // Get link keys sorted by length descending (already done in mobile-chat.js, but good to have here too for robustness)
            const sortedLinkKeys = Object.keys(linkData).sort((a, b) => b.length - a.length);

            nodesToProcess.forEach((textNode) => {
                let currentNode = textNode;
                // Process keys from longest to shortest for this node
                for (const key of sortedLinkKeys) {
                    if (!currentNode || !currentNode.nodeValue) break; // Stop if node is removed or empty

                    const linkInfo = linkData[key];
                    const originalText = linkInfo.original_text || key; // Use original casing if available
                    // Use word boundaries in regex ( doesn't work well with some punctuation)
                    const pattern = `(^|[^a-zA-Z0-9])(${escapeRegExp(originalText)})([^a-zA-Z0-9]|$)`;
                    const regex = new RegExp(pattern, 'gi'); // Case-insensitive

                    let match = regex.exec(currentNode.nodeValue);
                    if (match) {
                         console.log(`[DNDUtils Debug] Match found for "${originalText}" in node: "${currentNode.nodeValue.substring(0, 50)}..."`);
                        
                        // Calculate split points
                        const matchStartIndex = match.index + match[1].length; // Start of actual keyword
                        const matchEndIndex = matchStartIndex + match[2].length; // End of actual keyword

                        // Create the link element
                        const linkElement = document.createElement('a');
                        linkElement.textContent = match[2]; // The matched text
                        linkElement.className = linkInfo.type === 'internal' ? 'internal-link' : 'external-link';

                        if (linkInfo.type === 'internal') {
                            linkElement.href = '#'; // Prevent page jump
                            linkElement.dataset.s3Key = linkInfo.s3_key || '';
                            linkElement.dataset.page = linkInfo.page || '';
                            linkElement.title = `Internal link to page ${linkInfo.page || '?'}: ${linkInfo.snippet || ''}`;
                        } else { // External link
                            linkElement.href = linkInfo.url || '#';
                            linkElement.target = '_blank';
                            linkElement.rel = 'noopener noreferrer';
                            linkElement.title = `External link: ${linkInfo.url || ''}`;
                            // Append external link icon
                            linkElement.innerHTML += ' <i class="fas fa-external-link-alt fa-xs" style="vertical-align: super; opacity: 0.7;"></i>';
                        }

                        // Split the text node
                        let textAfter = currentNode.splitText(matchEndIndex);
                        let matchedTextNode = currentNode.splitText(matchStartIndex); // This node contains the text to be replaced
                        
                        // Insert the link element before the 'after' text node
                        currentNode.parentNode.insertBefore(linkElement, textAfter);
                        
                        // *** Remove the original text node that contained the matched text ***
                        currentNode.parentNode.removeChild(matchedTextNode);
                        
                        hasChanges = true;

                        // Continue searching *after* the inserted link
                        currentNode = textAfter;
                        regex.lastIndex = 0; // Reset regex index for the new text node
                        // Re-run the *same* key search on the remaining part of the node
                        // This is complex; simpler to just move to next node for now
                        break; // Move to the next key for this node segment (or next node)
                    }
                } // End loop through keys
            }); // End loop through text nodes

            console.log("[DNDUtils Debug] Finished link processing DOM modifications.");
        } catch (error) {
            console.error("[DNDUtils Error] Error processing links:", error);
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