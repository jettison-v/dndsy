// Source panel management

// Device detection functions
function isMobile() {
    return window.innerWidth <= 768;
}

function isTablet() {
    return window.innerWidth > 768 && window.innerWidth <= 950;
}

// Add mobile class to body if on mobile device
function initializeMobileView() {
    if (isMobile()) {
        document.body.classList.add('mobile-view');
    } else {
        document.body.classList.remove('mobile-view');
    }
}

// Source panel state
let isSourcePanelOpen = false;
let isSourcePanelExpanded = false;

// Toggle the source panel (open/close)
function toggleSourcePanel() {
    const sourcePanel = document.querySelector('.source-panel');
    
    if (!sourcePanel) return;
    
    if (isSourcePanelOpen) {
        // Close panel
        if (isMobile() || isTablet()) {
            // For mobile and tablet, just remove the open class immediately
            sourcePanel.classList.remove('open');
            // Ensure no other classes remain
            sourcePanel.classList.remove('expanded');
            sourcePanel.classList.remove('collapsing');
        } else {
            // For desktop, use animation
            sourcePanel.classList.add('closing');
            sourcePanel.classList.remove('open');
        }
        
        isSourcePanelOpen = false;
        
        // Clean up after panel close
        cleanupSourcePanel();
    } else {
        // Open panel
        sourcePanel.classList.remove('closing');
        sourcePanel.classList.add('open');
        isSourcePanelOpen = true;
        
        // On mobile or tablet, prevent body scrolling when panel is open
        if (isMobile() || isTablet()) {
            document.body.style.overflow = 'hidden';
            
            // For tablets, ensure panel is in full screen mode by removing other classes
            if (isTablet()) {
                sourcePanel.classList.remove('expanded');
                sourcePanel.classList.remove('collapsing');
                // Force recalculation of styles
                void sourcePanel.offsetWidth;
            }
        }
        
        // Reset expanded state (desktop only feature)
        if (isMobile() || isTablet()) {
            isSourcePanelExpanded = false;
            sourcePanel.classList.remove('expanded');
        }
    }
}

// Toggle expanded state (desktop only)
function toggleSourcePanelExpanded() {
    const sourcePanel = document.querySelector('.source-panel');
    
    if (!sourcePanel || isMobile() || isTablet()) return; // Don't expand on mobile or tablet
    
    if (isSourcePanelExpanded) {
        sourcePanel.classList.remove('expanded');
        isSourcePanelExpanded = false;
    } else {
        sourcePanel.classList.add('expanded');
        isSourcePanelExpanded = true;
    }
}

// Cleanup after closing source panel
function cleanupSourcePanel() {
    // Restore body scrolling if on mobile or tablet
    if (isMobile() || isTablet()) {
        document.body.style.overflow = '';
    }
}

// Initialize once DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initializeMobileView();
    
    // Set up toggle button click event
    const toggleBtn = document.getElementById('toggle-source-btn');
    if (toggleBtn) {
        toggleBtn.addEventListener('click', toggleSourcePanel);
    }
    
    // Set up close button click event
    const closeBtn = document.querySelector('.close-source-btn');
    if (closeBtn) {
        closeBtn.addEventListener('click', toggleSourcePanel);
    }
    
    // Set up expand button click event (desktop only)
    const expandBtn = document.querySelector('.expand-button');
    if (expandBtn) {
        expandBtn.addEventListener('click', toggleSourcePanelExpanded);
    }
    
    // Handle animation end for cleanup (desktop only)
    const sourcePanel = document.querySelector('.source-panel');
    if (sourcePanel) {
        sourcePanel.addEventListener('animationend', function(e) {
            if ((!isMobile() && !isTablet()) && e.animationName.includes('Out')) {
                sourcePanel.classList.remove('closing');
            }
        });
    }
    
    // Handle window resize for mobile detection
    window.addEventListener('resize', function() {
        initializeMobileView();
        
        // Reset expanded state on resize to mobile or tablet
        if ((isMobile() || isTablet()) && isSourcePanelExpanded) {
            const sourcePanel = document.querySelector('.source-panel');
            if (sourcePanel) {
                sourcePanel.classList.remove('expanded');
                isSourcePanelExpanded = false;
            }
        }
    });
}); 