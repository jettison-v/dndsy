/**
 * mobile-ui.js
 * Handles mobile-specific UI behavior for the DNDsy application.
 * This provides a simplified mobile experience with limited functionality:
 * 1. Chat with DNDsy
 * 2. Open source content one at a time in full screen
 * 3. Apply links for opening source content or new browser tabs
 */

document.addEventListener('DOMContentLoaded', () => {
    // Only run this code on mobile devices - use strict less than or equal comparison
    if (window.innerWidth > 768) return;
    
    // Apply mobile-specific class to body for CSS targeting
    document.body.classList.add('mobile-view');
    
    // Elements
    const sourcePanel = document.getElementById('source-panel');
    const mobileSourceToggle = document.getElementById('mobile-source-toggle');
    const mobileHeaderSourceToggle = document.getElementById('mobile-header-source-toggle');
    const closePanel = document.getElementById('close-panel');
    const chatMessages = document.getElementById('chat-messages');
    
    // Store the original toggle functions to avoid conflict
    const originalToggleSourcePanel = window.toggleSourcePanel;
    
    // Enable mobile-specific behaviors
    initializeMobileBehaviors();
    
    // Handle window resize
    window.addEventListener('resize', handleResize);
    
    /**
     * Initialize mobile-specific behaviors
     */
    function initializeMobileBehaviors() {
        // Add event listeners for mobile source toggles
        if (mobileSourceToggle) {
            mobileSourceToggle.addEventListener('click', handleMobileSourceToggle);
        }
        
        if (mobileHeaderSourceToggle) {
            mobileHeaderSourceToggle.addEventListener('click', handleMobileSourceToggle);
        }
        
        // Override close button behavior on mobile
        if (closePanel) {
            // Remove any existing event listeners (inefficient but effective)
            const newCloseBtn = closePanel.cloneNode(true);
            closePanel.parentNode.replaceChild(newCloseBtn, closePanel);
            newCloseBtn.addEventListener('click', closeMobileSourcePanel);
        }
        
        // Add event delegation for source pill clicks in chat
        if (chatMessages) {
            chatMessages.addEventListener('click', (event) => {
                const sourcePill = event.target.closest('.source-pill');
                if (sourcePill) {
                    handleMobileSourcePillClick(sourcePill);
                    event.preventDefault(); // Prevent default behavior
                    event.stopPropagation(); // Stop event from bubbling up
                }
            });
        }
    }
    
    /**
     * Handle window resize events
     */
    function handleResize() {
        if (window.innerWidth > 768) {
            // Remove mobile view class if no longer a mobile device
            document.body.classList.remove('mobile-view');
            
            // Restore original behaviors (if we're switching back to desktop)
            cleanupMobileBehaviors();
        } else if (window.innerWidth <= 768) {
            // Add mobile view class if this is a mobile device
            document.body.classList.add('mobile-view');
            
            // Reinitialize mobile behaviors if we switched to mobile
            initializeMobileBehaviors();
        }
    }
    
    /**
     * Clean up mobile-specific behaviors
     */
    function cleanupMobileBehaviors() {
        // Remove mobile-specific event listeners
        if (mobileSourceToggle) {
            mobileSourceToggle.removeEventListener('click', handleMobileSourceToggle);
        }
        
        if (mobileHeaderSourceToggle) {
            mobileHeaderSourceToggle.removeEventListener('click', handleMobileSourceToggle);
        }
        
        // Restore original close button behavior
        if (closePanel) {
            // This is a crude way to restore original behavior, but it works
            const newCloseBtn = closePanel.cloneNode(true);
            closePanel.parentNode.replaceChild(newCloseBtn, closePanel);
        }
    }
    
    /**
     * Handle mobile source toggle button clicks
     * @param {Event} event Click event
     */
    function handleMobileSourceToggle(event) {
        event.preventDefault();
        event.stopPropagation();
        
        toggleMobileSourcePanel();
    }
    
    /**
     * Toggle source panel visibility for mobile
     */
    function toggleMobileSourcePanel() {
        if (sourcePanel.classList.contains('open')) {
            closeMobileSourcePanel();
        } else {
            // Open the source panel
            sourcePanel.classList.remove('closing');
            sourcePanel.classList.add('open');
            
            // Update toggle button icons
            if (mobileSourceToggle) {
                const icon = mobileSourceToggle.querySelector('i');
                if (icon) icon.classList.replace('fa-book', 'fa-times');
            }
            
            if (mobileHeaderSourceToggle) {
                const icon = mobileHeaderSourceToggle.querySelector('i');
                if (icon) icon.classList.replace('fa-book', 'fa-times');
            }
            
            // Scroll the source content to the top when opening
            const sourceContent = document.getElementById('source-content');
            if (sourceContent) {
                sourceContent.scrollTop = 0;
            }
        }
    }
    
    /**
     * Close the source panel for mobile
     */
    function closeMobileSourcePanel() {
        // Add closing animation class
        sourcePanel.classList.add('closing');
        
        // Update toggle button icons
        if (mobileSourceToggle) {
            const icon = mobileSourceToggle.querySelector('i');
            if (icon) icon.classList.replace('fa-times', 'fa-book');
        }
        
        if (mobileHeaderSourceToggle) {
            const icon = mobileHeaderSourceToggle.querySelector('i');
            if (icon) icon.classList.replace('fa-times', 'fa-book');
        }
        
        // Remove open class after animation completes
        setTimeout(() => {
            sourcePanel.classList.remove('open');
            sourcePanel.classList.remove('closing');
            
            // Remove active class from all source pills when panel is closed
            document.querySelectorAll('.source-pill').forEach(pill => {
                pill.classList.remove('active');
            });
        }, 300);
    }
    
    /**
     * Handle source pill clicks in mobile view
     * @param {HTMLElement} pill The source pill element that was clicked
     */
    function handleMobileSourcePillClick(pill) {
        // Get data attributes from the pill
        const s3Key = pill.dataset.s3Key;
        const pageNumber = pill.dataset.page;
        const score = pill.dataset.score;
        // Get current vector store setting from the dropdown or use semantic as fallback
        const storeType = pill.dataset.storeType || document.getElementById('vector-store-dropdown')?.value || 'semantic';
        const filename = pill.dataset.filename;
        
        // Set this pill as active
        document.querySelectorAll('.source-pill').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        
        // Show loading in source panel
        const sourceContent = document.getElementById('source-content');
        if (sourceContent) {
            sourceContent.innerHTML = '<div class="source-loading"><div class="spinner"></div><p>Loading source content...</p></div>';
        }
        
        // Open the source panel if not already open
        if (!sourcePanel.classList.contains('open')) {
            toggleMobileSourcePanel();
        }
        
        // Fetch context details from API
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
                
                displayMobileSource(details, `${filename} (page ${pageNumber})`, pageNumber, s3Key, score, storeType);
            })
            .catch(error => {
                console.error('Error fetching source details:', error);
                if (sourceContent) {
                    sourceContent.innerHTML = `<p class="error-source">Error loading source: ${error.message}</p>`;
                }
                pill.classList.remove('active');
            });
    }
    
    /**
     * Display source content in mobile view
     * @param {Object} details Source content details
     * @param {string} displayText Text to display in the header
     * @param {number} pageNumber Current page number
     * @param {string} s3Key S3 key for the source
     * @param {string} score Relevance score
     * @param {string} storeType Vector store type
     */
    function displayMobileSource(details, displayText, pageNumber, s3Key, score, storeType) {
        const sourceContent = document.getElementById('source-content');
        if (!sourceContent) return;
        
        // Clear existing content
        sourceContent.innerHTML = '';
        
        // Create header with source info
        const header = document.createElement('div');
        header.className = 'source-header';
        
        const sourceName = document.createElement('h4');
        sourceName.textContent = displayText;
        header.appendChild(sourceName);
        
        sourceContent.appendChild(header);
        
        if (details.image_base64) {
            // Display image content
            const imageContainer = document.createElement('div');
            imageContainer.id = 'source-image-container';
            imageContainer.className = 'source-image-container';
            
            const img = document.createElement('img');
            img.className = 'source-image';
            img.alt = displayText;
            img.src = `data:image/jpeg;base64,${details.image_base64}`;
            
            imageContainer.appendChild(img);
            sourceContent.appendChild(imageContainer);
            
            // Add zoom controls
            const zoomControls = document.createElement('div');
            zoomControls.className = 'zoom-controls';
            zoomControls.innerHTML = `
                <button id="mobile-zoom-in" title="Zoom In"><i class="fas fa-search-plus"></i></button>
                <button id="mobile-zoom-reset" title="Reset Zoom"><i class="fas fa-sync-alt"></i></button>
                <button id="mobile-zoom-out" title="Zoom Out"><i class="fas fa-search-minus"></i></button>
            `;
            sourceContent.appendChild(zoomControls);
            
            // Add zoom functionality
            let currentZoomLevel = 1;
            document.getElementById('mobile-zoom-in').addEventListener('click', () => {
                if (currentZoomLevel < 2.5) {
                    currentZoomLevel += 0.25;
                    img.style.transform = `scale(${currentZoomLevel})`;
                }
            });
            
            document.getElementById('mobile-zoom-reset').addEventListener('click', () => {
                currentZoomLevel = 1;
                img.style.transform = `scale(${currentZoomLevel})`;
            });
            
            document.getElementById('mobile-zoom-out').addEventListener('click', () => {
                if (currentZoomLevel > 0.5) {
                    currentZoomLevel -= 0.25;
                    img.style.transform = `scale(${currentZoomLevel})`;
                }
            });
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
        
        // Add navigation if total_pages is provided
        if (details.total_pages && details.total_pages > 1) {
            addMobileSourceNavigation(sourceContent, parseInt(pageNumber), details.total_pages, s3Key, storeType);
        }
    }
    
    /**
     * Add navigation buttons for source pages
     * @param {HTMLElement} container Container element for navigation
     * @param {number} currentPage Current page number
     * @param {number} totalPages Total number of pages
     * @param {string} s3Key S3 key for the source
     * @param {string} storeType Vector store type
     */
    function addMobileSourceNavigation(container, currentPage, totalPages, s3Key, storeType) {
        // Create navigation container
        const navContainer = document.createElement('div');
        navContainer.className = 'source-navigation';
        
        // Create previous button
        const prevButton = document.createElement('button');
        prevButton.innerHTML = '<i class="fas fa-chevron-left"></i> Prev';
        prevButton.className = 'nav-button prev-button';
        prevButton.disabled = currentPage <= 1;
        
        // Create page indicator
        const pageIndicator = document.createElement('div');
        pageIndicator.className = 'page-indicator';
        pageIndicator.textContent = `${currentPage} / ${totalPages}`;
        
        // Create next button
        const nextButton = document.createElement('button');
        nextButton.innerHTML = 'Next <i class="fas fa-chevron-right"></i>';
        nextButton.className = 'nav-button next-button';
        nextButton.disabled = currentPage >= totalPages;
        
        // Add event listeners for navigation
        prevButton.addEventListener('click', () => {
            navigateMobileSourcePage('prev', currentPage, s3Key, storeType);
        });
        
        nextButton.addEventListener('click', () => {
            navigateMobileSourcePage('next', currentPage, s3Key, storeType);
        });
        
        // Add elements to navigation container
        navContainer.appendChild(prevButton);
        navContainer.appendChild(pageIndicator);
        navContainer.appendChild(nextButton);
        
        // Add navigation to the container
        container.appendChild(navContainer);
    }
    
    /**
     * Navigate to a different page in the source
     * @param {string} direction Direction to navigate ('prev' or 'next')
     * @param {number} currentPage Current page number
     * @param {string} s3Key S3 key for the source
     * @param {string} storeType Vector store type
     */
    function navigateMobileSourcePage(direction, currentPage, s3Key, storeType) {
        // Calculate new page based on direction
        let newPage;
        if (direction === 'prev') {
            newPage = currentPage - 1;
            if (newPage < 1) return; // Cannot go below page 1
        } else if (direction === 'next') {
            newPage = currentPage + 1;
        } else {
            return; // Invalid direction
        }
        
        // Show loading indicator
        const sourceContent = document.getElementById('source-content');
        if (sourceContent) {
            sourceContent.innerHTML = '<div class="source-loading"><div class="spinner"></div><p>Loading page...</p></div>';
        }
        
        // Fetch new page details
        fetch(`/api/get_context_details?source=${encodeURIComponent(s3Key)}&page=${newPage}&vector_store_type=${storeType}`)
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
                
                // Get readable source name from the s3Key
                const filename = s3Key.split('/').pop().replace(/\.[^/.]+$/, "");
                
                // Display the new page
                displayMobileSource(details, `${filename} (page ${newPage})`, newPage, s3Key, null, storeType);
            })
            .catch(error => {
                console.error('Error navigating to page:', error);
                if (sourceContent) {
                    sourceContent.innerHTML = `<p class="error-source">Error loading page: ${error.message}</p>`;
                }
            });
    }
}); 