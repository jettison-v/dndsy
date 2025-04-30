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
        if (!text) return '';
        
        // First process code blocks to prevent other formatting inside them
        let formattedText = text;
        
        // Find and replace code blocks first
        const codeBlockRegex = /```([\s\S]*?)```/g;
        const codeBlocks = [];
        let match;
        
        // Replace code blocks with placeholders
        while ((match = codeBlockRegex.exec(text)) !== null) {
            const placeholder = `__CODE_BLOCK_${codeBlocks.length}__`;
            codeBlocks.push(match[1]);
            formattedText = formattedText.replace(match[0], placeholder);
        }
        
        // Find and replace inline code
        const inlineCodeRegex = /`([^`]+)`/g;
        const inlineCodes = [];
        
        // Replace inline code with placeholders
        while ((match = inlineCodeRegex.exec(formattedText)) !== null) {
            const placeholder = `__INLINE_CODE_${inlineCodes.length}__`;
            inlineCodes.push(match[1]);
            formattedText = formattedText.replace(match[0], placeholder);
        }
        
        // Process markdown
        formattedText = formattedText
            // Headers
            .replace(/^### (.*$)/gm, '<h3>$1</h3>')
            .replace(/^## (.*$)/gm, '<h2>$1</h2>')
            .replace(/^# (.*$)/gm, '<h1>$1</h1>')
            // Bold and italic
            .replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>')
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            // Lists (need to handle them as groups)
            .replace(/^\s*\n\* (.*)/gm, '<ul>\n<li>$1</li>')
            .replace(/^\* (.*)/gm, '<li>$1</li>')
            .replace(/^\s*\n\d+\. (.*)/gm, '<ol>\n<li>$1</li>')
            .replace(/^\d+\. (.*)/gm, '<li>$1</li>')
            // Line breaks
            .replace(/\n/g, '<br>');
        
        // Clean up list tags
        formattedText = formattedText
            .replace(/<\/ul>\s*<br><ul>/g, '')
            .replace(/<\/ol>\s*<br><ol>/g, '')
            .replace(/(<\/li><br>)/g, '</li>');
        
        // If we have an unclosed list tag at the end, close it
        if (formattedText.includes('<ul>') || formattedText.includes('<ol>')) {
            if ((formattedText.match(/<ul>/g) || []).length > (formattedText.match(/<\/ul>/g) || []).length) {
                formattedText += '</ul>';
            }
            if ((formattedText.match(/<ol>/g) || []).length > (formattedText.match(/<\/ol>/g) || []).length) {
                formattedText += '</ol>';
            }
        }
        
        // Put code blocks back
        codeBlocks.forEach((block, index) => {
            const escapedHtml = block
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
            formattedText = formattedText.replace(`__CODE_BLOCK_${index}__`, `<pre><code>${escapedHtml}</code></pre>`);
        });
        
        // Put inline code back
        inlineCodes.forEach((code, index) => {
            const escapedHtml = code
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
            formattedText = formattedText.replace(`__INLINE_CODE_${index}__`, `<code>${escapedHtml}</code>`);
        });
        
        return formattedText;
    }
    
    /**
     * Process text for links
     * @param {HTMLElement} messageElement The message element to process
     * @param {Object} linkData Link data from the server
     */
    function processLinksInMessage(messageElement, linkData) {
        if (!messageElement || !linkData) return;
        
        const messageText = messageElement.querySelector('.message-text');
        if (!messageText) return;
        
        // Process the message HTML to find potential link texts
        const content = messageText.innerHTML;
        
        // Create temporary element to work with the HTML
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = content;
        
        // Process all text nodes
        const textNodes = [];
        const walk = document.createTreeWalker(
            tempDiv, 
            NodeFilter.SHOW_TEXT, 
            null, 
            false
        );
        
        let node;
        while (node = walk.nextNode()) {
            textNodes.push(node);
        }
        
        // Check each text node for potential links
        let hasChanges = false;
        textNodes.forEach(textNode => {
            const original = textNode.nodeValue;
            let updated = original;
            
            // Check against link data
            for (const [linkText, linkInfo] of Object.entries(linkData)) {
                // Case-insensitive match
                const regex = new RegExp(`(\\b${escapeRegExp(linkText)}\\b)`, 'gi');
                if (regex.test(updated)) {
                    const typeClass = linkInfo.type === 'internal' ? 'internal-link' : 'external-link';
                    const attrs = linkInfo.type === 'internal' 
                        ? `data-s3-key="${linkInfo.s3_key || ''}" data-page="${linkInfo.page || ''}"` 
                        : `href="${linkInfo.url || '#'}" target="_blank"`;
                    
                    updated = updated.replace(regex, `<a class="${typeClass}" ${attrs}>$1</a>`);
                    hasChanges = true;
                }
            }
            
            // Replace node if changes were made
            if (updated !== original) {
                const fragment = document.createRange().createContextualFragment(updated);
                textNode.parentNode.replaceChild(fragment, textNode);
            }
        });
        
        if (hasChanges) {
            messageText.innerHTML = tempDiv.innerHTML;
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