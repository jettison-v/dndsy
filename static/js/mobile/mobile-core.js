/**
 * mobile-core.js
 * Core mobile UI functionality for the AskDND application
 */

document.addEventListener('DOMContentLoaded', () => {
    console.log("[Debug] mobile-core.js loaded");
    
    // UI elements
    const mobileSettingsToggle = document.getElementById('mobile-settings-toggle');
    const mobileSettingsPanel = document.getElementById('mobile-settings-panel');
    const closeSettingsPanel = document.getElementById('close-settings-panel');
    const mobileHeaderSourceToggle = document.getElementById('mobile-header-source-toggle');
    const sourcePanel = document.getElementById('source-panel');
    const closePanel = document.getElementById('close-panel');
    const aboutProjectButton = document.getElementById('about-project-button');
    const aboutProjectModal = document.getElementById('about-project-modal');
    const aboutProjectCloseButton = document.getElementById('about-project-close-button');
    const githubRepoButton = document.getElementById('github-repo-button');
    
    // Initialize settings panel functionality
    if (mobileSettingsToggle && mobileSettingsPanel && closeSettingsPanel) {
        console.log("[Debug] Setting up standard click listener for settings button.");
        mobileSettingsToggle.addEventListener('click', function(e) {
            e.stopPropagation(); // Stop event bubbling
            e.preventDefault();  // Prevent default link behavior (if any)
            console.log("[Debug] Settings Toggle Clicked!");
            if (mobileSettingsPanel.classList.contains('open')) {
                closeSettings();
            } else {
                openSettings();
            }
        });

        closeSettingsPanel.addEventListener('click', function(e) {
            e.stopPropagation();
            e.preventDefault();
            console.log("[Debug] Close Settings Clicked!");
            closeSettings();
        });

        // Close when clicking outside
        document.addEventListener('click', (event) => {
            if (!mobileSettingsPanel || !mobileSettingsToggle) return; // Safety check
            if (mobileSettingsPanel.classList.contains('open') && 
                !mobileSettingsPanel.contains(event.target) && 
                !mobileSettingsToggle.contains(event.target)) {
                console.log("[Debug] Click outside detected, closing settings.");
                closeSettings();
            }
        });
    } else {
        console.error("[Debug] Could not find all settings elements for initialization.");
    }
    
    // Initialize source panel functionality
    if (mobileHeaderSourceToggle && sourcePanel && closePanel) {
        // Use direct onclick handlers instead of event listeners
        mobileHeaderSourceToggle.onclick = function(event) {
            event.preventDefault();
            event.stopPropagation();
            toggleSourcePanel();
            return false;
        };
        
        closePanel.onclick = function(event) {
            event.preventDefault();
            event.stopPropagation();
            closeSourcePanel();
            return false;
        };
    }
    
    // Initialize about modal functionality
    if (aboutProjectButton && aboutProjectModal && aboutProjectCloseButton) {
        console.log("[Debug] Initializing About Project modal listeners.");
        
        // Function to open the modal
        const openAboutModal = () => {
            console.log("[Debug] Opening About Project modal.");
            if (aboutProjectModal) {
                aboutProjectModal.classList.add('open');
                document.body.classList.add('modal-open'); // Prevent background scroll
            }
        };

        // Function to close the modal
        const closeAboutModal = () => {
            console.log("[Debug] Closing About Project modal.");
            if (aboutProjectModal) {
                aboutProjectModal.classList.remove('open');
                document.body.classList.remove('modal-open'); // Allow background scroll
            }
        };

        // Open modal when button is clicked
        aboutProjectButton.addEventListener('click', openAboutModal);
        
        // Close modal when close button is clicked
        aboutProjectCloseButton.addEventListener('click', closeAboutModal);
        
        // Close modal when clicking outside the modal content (on the overlay)
        aboutProjectModal.addEventListener('click', (event) => {
            // Check if the click is directly on the overlay element itself
            if (event.target === aboutProjectModal) {
                console.log("[Debug] Clicked on modal overlay.");
                closeAboutModal();
            }
        });
    } else {
         console.warn("[Debug] Could not find all elements for About Project modal.");
    }
    
    // GitHub repo button
    if (githubRepoButton) {
        githubRepoButton.addEventListener('click', () => {
            window.open('https://github.com/jettison-v/dndsy', '_blank');
        });
    }
    
    // Handle back button for modals and panels
    window.addEventListener('popstate', handleBackButton);
    
    /**
     * Toggle settings panel visibility
     */
    function toggleSettingsPanel() {
        if (mobileSettingsPanel.classList.contains('open')) {
            closeSettings();
        } else {
            openSettings();
        }
    }
    
    /**
     * Open settings panel
     */
    function openSettings() {
        if (!mobileSettingsPanel) return;
        console.log("[Debug] Opening Settings Panel");
        mobileSettingsPanel.classList.add('open');
        document.body.classList.add('panel-open');
    }
    
    /**
     * Close settings panel
     */
    function closeSettings() {
        if (!mobileSettingsPanel) return;
        console.log("[Debug] Closing Settings Panel");
        mobileSettingsPanel.classList.remove('open');
        document.body.classList.remove('panel-open');
    }
    
    /**
     * Toggle source panel visibility
     */
    function toggleSourcePanel() {
        if (sourcePanel.classList.contains('open')) {
            closeSourcePanel();
        } else {
            openSourcePanel();
        }
    }
    
    /**
     * Open source panel
     */
    function openSourcePanel() {
        if (!sourcePanel) return;
        console.log("[Debug] Opening Source Panel");
        // Close other panels first
        closeSettings(); // Ensure settings is closed
        closeAboutModal(); // Ensure about modal is closed
        sourcePanel.classList.add('open');
        document.body.classList.add('panel-open');
        // Update button icon if needed (assuming mobileHeaderSourceToggle exists)
        // const icon = mobileHeaderSourceToggle?.querySelector('i');
        // if (icon) icon.className = 'fas fa-times';
    }
    
    /**
     * Close source panel
     */
    function closeSourcePanel() {
        if (!sourcePanel) return;
        console.log("[Debug] Closing Source Panel");
        sourcePanel.classList.remove('open');
        document.body.classList.remove('panel-open');
        // Update button icon if needed
        // const icon = mobileHeaderSourceToggle?.querySelector('i');
        // if (icon) icon.className = 'fas fa-book';
    }
    
    /**
     * Handle back button navigation for modals and panels
     */
    function handleBackButton(event) {
        if (mobileSettingsPanel.classList.contains('open')) {
            closeSettings();
            event.preventDefault();
        }
        
        if (sourcePanel.classList.contains('open')) {
            closeSourcePanel();
            event.preventDefault();
        }
        
        if (aboutProjectModal.classList.contains('open')) {
            closeAboutModal();
            event.preventDefault();
        }
    }
    
    // Make functions available globally
    window.mobileUI = {
        openSourcePanel: openSourcePanel, 
        closeSourcePanel: closeSourcePanel,
        openAboutModal: openAboutModal,
        closeAboutModal: closeAboutModal,
        closeSettings: closeSettings // Keep closeSettings exposed if needed
    };
    console.log("[Debug] mobileUI object created:", window.mobileUI);
}); 