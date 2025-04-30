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
        escapeRegExp
    };
})();

// Make available globally
window.DNDUtilities = DNDUtilities; 