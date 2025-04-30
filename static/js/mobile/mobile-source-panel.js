/**
 * mobile-source-panel.js
 * Handles source panel functionality for mobile interface
 */

document.addEventListener('DOMContentLoaded', () => {
    // Source panel elements
    const sourcePanel = document.getElementById('source-panel');
    const sourceContent = document.getElementById('source-content');
    const chatMessages = document.getElementById('chat-messages');
    
    // Track active source
    let currentSourceKey = null;
    let currentPage = 1;
    let totalPages = 1;
    let currentStoreType = '';
    
    // Setup source pill handling
    if (chatMessages) {
        chatMessages.addEventListener('click', (event) => {
            const sourcePill = event.target.closest('.source-pill');
            if (sourcePill) {
                event.preventDefault();
                event.stopPropagation();
                handleSourcePillClick(sourcePill);
            }
        });
    }
    
    /**
     * Handle source pill click
     * @param {HTMLElement} pill The source pill element
     */
    function handleSourcePillClick(pill) {
        // Get data attributes
        const s3Key = pill.dataset.s3Key;
        const pageNumber = parseInt(pill.dataset.page, 10) || 1;
        const score = pill.dataset.score;
        const storeType = pill.dataset.storeType || document.getElementById('vector-store-dropdown')?.value || 'semantic';
        
        // Set active state on pill
        document.querySelectorAll('.source-pill').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        
        // Show loading indicator
        if (sourceContent) {
            sourceContent.innerHTML = '<div class="source-loading"><div class="spinner"></div><p>Loading source content...</p></div>';
        }
        
        // Open source panel
        if (window.mobileUI && !sourcePanel.classList.contains('open')) {
            window.mobileUI.openSourcePanel();
        }
        
        // Fetch and display content
        fetchSourceContent(s3Key, pageNumber, storeType);
    }
    
    /**
     * Fetch source content from the server
     * @param {string} s3Key S3 key of the source
     * @param {number} pageNumber Page number to fetch
     * @param {string} storeType Vector store type
     */
    function fetchSourceContent(s3Key, pageNumber, storeType) {
        // Store current source info
        currentSourceKey = s3Key;
        currentPage = pageNumber;
        currentStoreType = storeType;
        
        // Show loading indicator if content exists
        if (sourceContent) {
            sourceContent.innerHTML = '<div class="source-loading"><div class="spinner"></div><p>Loading source content...</p></div>';
        }
        
        // Use the shared utility if available
        if (window.DNDUtilities) {
            DNDUtilities.fetchSourceContent(
                s3Key,
                pageNumber,
                storeType,
                // Success callback
                (details, s3Key, pageNumber) => {
                    if (!details) {
                        throw new Error('No details returned from server');
                    }
                    
                    // Extract source name from S3 key
                    const sourceName = s3Key.split('/').pop().replace(/\.[^/.]+$/, "");
                    totalPages = details.total_pages || 1;
                    
                    // Display content
                    displaySourceContent(details, sourceName, pageNumber);
                },
                // Error callback
                (errorMessage) => {
                    console.error('Error fetching source details:', errorMessage);
                    if (sourceContent) {
                        sourceContent.innerHTML = `<p class="error-source">Error loading source: ${errorMessage}</p>`;
                    }
                    
                    // Remove active state from pills on error
                    document.querySelectorAll('.source-pill').forEach(p => p.classList.remove('active'));
                }
            );
        } else {
            // Fallback to direct fetch if utility not available
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
                    
                    // Extract source name from S3 key
                    const sourceName = s3Key.split('/').pop().replace(/\.[^/.]+$/, "");
                    totalPages = details.total_pages || 1;
                    
                    // Display content
                    displaySourceContent(details, sourceName, pageNumber);
                })
                .catch(error => {
                    console.error('Error fetching source details:', error);
                    if (sourceContent) {
                        sourceContent.innerHTML = `<p class="error-source">Error loading source: ${error.message}</p>`;
                    }
                    
                    // Remove active state from pills on error
                    document.querySelectorAll('.source-pill').forEach(p => p.classList.remove('active'));
                });
        }
    }
    
    /**
     * Display source content in the panel
     * @param {Object} details Source content details from API
     * @param {string} sourceName Name of the source
     * @param {number} pageNumber Current page number
     */
    function displaySourceContent(details, sourceName, pageNumber) {
        if (!sourceContent) return;
        
        // Clear existing content
        sourceContent.innerHTML = '';
        
        // Update header
        const panelHeader = sourcePanel.querySelector('.source-panel-header h3');
        if (panelHeader) {
            panelHeader.textContent = `${sourceName} (Page ${pageNumber})`;
        }
        
        if (details.image_url || details.image_base64) {
            // Display image content
            const imageContainer = document.createElement('div');
            imageContainer.id = 'source-image-container';
            
            const img = document.createElement('img');
            img.className = 'source-image';
            img.alt = `${sourceName} page ${pageNumber}`;
            img.src = details.image_url || `data:image/jpeg;base64,${details.image_base64}`;
            
            imageContainer.appendChild(img);
            sourceContent.appendChild(imageContainer);
            
            // Add zoom controls
            addZoomControls(img);
        } else if (details.text) {
            // Display text content
            const textContainer = document.createElement('div');
            textContainer.className = 'source-text';
            textContainer.innerHTML = details.text;
            sourceContent.appendChild(textContainer);
        } else {
            // No content available
            sourceContent.innerHTML = '<p class="no-source">No source content available</p>';
        }
        
        // Add navigation if needed
        if (totalPages > 1) {
            addSourceNavigation(sourceContent, pageNumber, totalPages);
        }
    }
    
    /**
     * Add zoom controls for image content
     * @param {HTMLImageElement} img The image element to control
     */
    function addZoomControls(img) {
        // Create zoom controls container
        const zoomControls = document.createElement('div');
        zoomControls.className = 'zoom-controls';
        zoomControls.innerHTML = `
            <button id="zoom-in" title="Zoom In"><i class="fas fa-search-plus"></i></button>
            <button id="zoom-reset" title="Reset Zoom"><i class="fas fa-sync-alt"></i></button>
            <button id="zoom-out" title="Zoom Out"><i class="fas fa-search-minus"></i></button>
        `;
        
        sourceContent.appendChild(zoomControls);
        
        // Current zoom level
        let zoomLevel = 1;
        
        // Zoom in button
        document.getElementById('zoom-in').addEventListener('click', () => {
            if (zoomLevel < 3) {
                zoomLevel += 0.25;
                img.style.transform = `scale(${zoomLevel})`;
            }
        });
        
        // Reset zoom button
        document.getElementById('zoom-reset').addEventListener('click', () => {
            zoomLevel = 1;
            img.style.transform = 'scale(1)';
        });
        
        // Zoom out button
        document.getElementById('zoom-out').addEventListener('click', () => {
            if (zoomLevel > 0.5) {
                zoomLevel -= 0.25;
                img.style.transform = `scale(${zoomLevel})`;
            }
        });
    }
    
    /**
     * Add page navigation controls
     * @param {HTMLElement} container Container element for navigation
     * @param {number} currentPage Current page number
     * @param {number} totalPages Total number of pages
     */
    function addSourceNavigation(container, currentPage, totalPages) {
        const navContainer = document.createElement('div');
        navContainer.className = 'source-navigation';
        
        // Previous button
        const prevButton = document.createElement('button');
        prevButton.innerHTML = '<i class="fas fa-chevron-left"></i> Previous';
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
                fetchSourceContent(currentSourceKey, currentPage - 1, currentStoreType);
            }
        });
        
        nextButton.addEventListener('click', () => {
            if (currentPage < totalPages) {
                fetchSourceContent(currentSourceKey, currentPage + 1, currentStoreType);
            }
        });
        
        // Add to navigation container
        navContainer.appendChild(prevButton);
        navContainer.appendChild(pageIndicator);
        navContainer.appendChild(nextButton);
        
        // Add navigation to container
        container.appendChild(navContainer);
    }
}); 