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
        
        // Main content container with appropriate styling
        const contentContainer = document.createElement('div');
        contentContainer.className = 'mobile-source-content-container';
        sourceContent.appendChild(contentContainer);
        
        if (details.image_base64 || details.image_url) {
            // Display image content
            const imageContainer = document.createElement('div');
            imageContainer.id = 'source-image-container';
            imageContainer.className = 'mobile-source-image-container';
            
            // Create debug info element for troubleshooting
            console.log('Image source details:', {
                hasImageUrl: !!details.image_url,
                imageUrl: details.image_url,
                hasImageBase64: !!details.image_base64,
                imageBase64Length: details.image_base64 ? details.image_base64.length : 0
            });
            
            const img = document.createElement('img');
            img.className = 'source-image';
            img.alt = `${sourceName} page ${pageNumber}`;
            
            // Use the shared utility for image loading with fallback strategies
            if (window.DNDUtilities && details.imageStrategies) {
                // Use the shared image loading utility with the provided strategies
                DNDUtilities.loadImageWithFallback(img, details.imageStrategies, (errorMsg) => {
                    console.error('Image loading failed:', errorMsg);
                    img.alt = 'Error loading image';
                    img.style.display = 'none';
                    imageContainer.innerHTML += `<p class="error-source">Failed to load image after trying all methods.</p>`;
                });
            } else {
                // Fallback to previous cascade approach if utilities aren't available
                // Track attempts to avoid infinite retries
                let attemptCount = 0;
                const maxAttempts = 3;
                
                // Function to try loading the image with different methods
                const tryLoadImage = (method) => {
                    attemptCount++;
                    
                    if (attemptCount > maxAttempts) {
                        console.error('Max image loading attempts reached');
                        img.alt = 'Error loading image after multiple attempts';
                        img.style.display = 'none';
                        imageContainer.innerHTML += `<p class="error-source">Error loading image after multiple attempts.</p>`;
                        return;
                    }
                    
                    switch(method) {
                        case 'transformed':
                            if (details.transformed_image_url) {
                                img.src = details.transformed_image_url;
                                console.log('Using transformed image URL:', img.src);
                            } else {
                                tryLoadImage('api_proxy');
                            }
                            break;
                            
                        case 'api_proxy':
                            if (details.image_url && details.image_url.startsWith('s3://')) {
                                // Format: Extract bucket and key parts correctly
                                const s3Url = details.image_url;
                                console.log('Processing S3 URL:', s3Url);
                                
                                // Try the API proxy endpoint with full URL
                                img.src = `/api/get_pdf_image?key=${encodeURIComponent(s3Url)}`;
                                console.log('Using API proxy for S3 image:', img.src);
                            } else {
                                tryLoadImage('direct_url');
                            }
                            break;
                            
                        case 'direct_url':
                            if (details.image_url && !details.image_url.startsWith('s3://')) {
                                img.src = details.image_url;
                                console.log('Using direct image URL:', img.src);
                            } else {
                                tryLoadImage('direct_s3');
                            }
                            break;
                            
                        case 'direct_s3':
                            if (details.image_url && details.image_url.startsWith('s3://')) {
                                // Try constructing a direct S3 URL
                                const s3Url = details.image_url;
                                const s3Parts = s3Url.replace('s3://', '').split('/');
                                const bucket = s3Parts.shift();
                                const key = s3Parts.join('/');
                                
                                img.src = `https://${bucket}.s3.amazonaws.com/${key}`;
                                console.log('Using direct S3 URL:', img.src);
                            } else {
                                tryLoadImage('base64');
                            }
                            break;
                            
                        case 'base64':
                            if (details.image_base64) {
                                img.src = `data:image/jpeg;base64,${details.image_base64}`;
                                console.log('Using base64 image data');
                            } else {
                                console.error('No more image loading methods available');
                                img.alt = 'No image available';
                                img.style.display = 'none';
                                imageContainer.innerHTML += `<p class="error-source">No image available for this source.</p>`;
                            }
                            break;
                            
                        default:
                            console.error('Unknown image loading method:', method);
                            break;
                    }
                };
                
                // Handle image load errors
                img.onerror = (e) => {
                    console.error('Failed to load image with method', attemptCount, e);
                    console.error('Failed image URL was:', img.src);
                    
                    // Try the next method based on the current attempt
                    const methods = ['transformed', 'api_proxy', 'direct_url', 'direct_s3', 'base64'];
                    if (attemptCount < methods.length) {
                        tryLoadImage(methods[attemptCount]);
                    } else {
                        img.alt = 'Error loading image';
                        img.style.display = 'none';
                        imageContainer.innerHTML += `<p class="error-source">Failed to load image after trying all methods.</p>`;
                    }
                };
                
                // Start loading the image with the first method
                tryLoadImage('transformed');
            }
            
            imageContainer.appendChild(img);
            contentContainer.appendChild(imageContainer);
            
            // Don't add zoom controls on mobile - use native pinch/zoom instead
        } else if (details.text || details.text_content) {
            // Display text content
            const textContainer = document.createElement('div');
            textContainer.className = 'source-text';
            textContainer.innerHTML = details.text || details.text_content;
            contentContainer.appendChild(textContainer);
        } else {
            // No content available
            contentContainer.innerHTML = '<p class="no-source">No source content available</p>';
        }
        
        // Add navigation if needed - this is now added to the source content outside the content container
        if (totalPages > 1) {
            addSourceNavigation(sourceContent, pageNumber, totalPages);
        }
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

    // When the source panel is closed, remove active state from source pills
    document.addEventListener('click', function(event) {
        if (event.target.id === 'close-panel' || event.target.closest('#close-panel')) {
            // Remove active state from all pills
            document.querySelectorAll('.source-pill').forEach(pill => {
                pill.classList.remove('active');
            });
        }
    });
    
    // Add global handler for the closeSourcePanel function
    if (window.mobileUI && window.mobileUI.closeSourcePanel) {
        const originalCloseSourcePanel = window.mobileUI.closeSourcePanel;
        window.mobileUI.closeSourcePanel = function() {
            // Remove active state from all pills
            document.querySelectorAll('.source-pill').forEach(pill => {
                pill.classList.remove('active');
            });
            
            // Call the original function
            originalCloseSourcePanel();
        };
    }
}); 