/**
 * mobile-core.js
 * Core mobile UI functionality for the AskDND application
 */

document.addEventListener('DOMContentLoaded', () => {
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
        mobileSettingsToggle.addEventListener('click', toggleSettingsPanel);
        closeSettingsPanel.addEventListener('click', closeSettings);
        
        // Close settings when clicking outside
        document.addEventListener('click', (event) => {
            if (mobileSettingsPanel.classList.contains('open') && 
                !mobileSettingsPanel.contains(event.target) && 
                event.target !== mobileSettingsToggle) {
                closeSettings();
            }
        });
    }
    
    // Initialize source panel functionality
    if (mobileHeaderSourceToggle && sourcePanel && closePanel) {
        mobileHeaderSourceToggle.addEventListener('click', toggleSourcePanel);
        closePanel.addEventListener('click', closeSourcePanel);
    }
    
    // Initialize about modal functionality
    if (aboutProjectButton && aboutProjectModal && aboutProjectCloseButton) {
        aboutProjectButton.addEventListener('click', openAboutModal);
        aboutProjectCloseButton.addEventListener('click', closeAboutModal);
        
        // Close modal when clicking outside
        aboutProjectModal.addEventListener('click', (event) => {
            if (event.target === aboutProjectModal) {
                closeAboutModal();
            }
        });
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
        // Close other panels first
        closeSourcePanel();
        closeAboutModal();
        
        // Open settings panel
        mobileSettingsPanel.classList.add('open');
        document.body.classList.add('panel-open');
        
        // Add history state for back button
        history.pushState({ panel: 'settings' }, '');
    }
    
    /**
     * Close settings panel
     */
    function closeSettings() {
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
        // Close other panels first
        closeSettings();
        closeAboutModal();
        
        // Open source panel
        sourcePanel.classList.add('open');
        document.body.classList.add('panel-open');
        
        // Update button icon
        const icon = mobileHeaderSourceToggle.querySelector('i');
        if (icon) icon.className = 'fas fa-times';
        
        // Add history state for back button
        history.pushState({ panel: 'source' }, '');
    }
    
    /**
     * Close source panel
     */
    function closeSourcePanel() {
        sourcePanel.classList.remove('open');
        document.body.classList.remove('panel-open');
        
        // Update button icon
        const icon = mobileHeaderSourceToggle.querySelector('i');
        if (icon) icon.className = 'fas fa-book';
    }
    
    /**
     * Open about modal
     */
    function openAboutModal() {
        // Close other panels first
        closeSettings();
        closeSourcePanel();
        
        // Open about modal
        aboutProjectModal.classList.add('open');
        document.body.classList.add('modal-open');
        
        // Add history state for back button
        history.pushState({ panel: 'about' }, '');
    }
    
    /**
     * Close about modal
     */
    function closeAboutModal() {
        aboutProjectModal.classList.remove('open');
        document.body.classList.remove('modal-open');
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
        toggleSettingsPanel,
        openSettings,
        closeSettings,
        toggleSourcePanel,
        openSourcePanel,
        closeSourcePanel,
        openAboutModal,
        closeAboutModal
    };
}); 