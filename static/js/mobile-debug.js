/**
 * Mobile Browser Debugging Tool
 * 
 * This script outputs various browser and device information
 * to help debug display issues on mobile devices.
 */

document.addEventListener('DOMContentLoaded', function() {
    console.log('Mobile debug tool loaded');
    
    // Create debug panel
    const debugPanel = document.createElement('div');
    debugPanel.id = 'mobile-debug-panel';
    debugPanel.style.cssText = `
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        background-color: rgba(0, 0, 0, 0.8);
        color: white;
        font-family: monospace;
        font-size: 10px;
        padding: 10px;
        z-index: 9999;
        max-height: 30vh;
        overflow-y: auto;
        transform: translateY(100%);
        transition: transform 0.3s;
        box-shadow: 0 -2px 10px rgba(0, 0, 0, 0.5);
    `;
    
    // Create toggle button - moved to top-right
    const toggleButton = document.createElement('button');
    toggleButton.id = 'debug-toggle';
    toggleButton.textContent = 'Debug';
    toggleButton.style.cssText = `
        position: fixed;
        top: 10px;
        right: 10px;
        background-color: rgba(228, 7, 18, 0.7);
        color: white;
        border: none;
        border-radius: 4px;
        padding: 3px 6px;
        font-size: 10px;
        z-index: 10000;
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.3);
        opacity: 0.7;
    `;
    
    // Add event listener to toggle debug panel
    toggleButton.addEventListener('click', function() {
        const panel = document.getElementById('mobile-debug-panel');
        if (panel.style.transform === 'translateY(100%)') {
            panel.style.transform = 'translateY(0)';
            collectDebugInfo();
        } else {
            panel.style.transform = 'translateY(100%)';
        }
    });
    
    // Add elements to body
    document.body.appendChild(debugPanel);
    document.body.appendChild(toggleButton);
    
    // Function to collect debug information
    function collectDebugInfo() {
        const panel = document.getElementById('mobile-debug-panel');
        
        // Clear previous content
        panel.innerHTML = '';
        
        // Close button at top of panel
        const closeButton = document.createElement('button');
        closeButton.textContent = '✕ Close';
        closeButton.style.cssText = `
            background-color: #e40712;
            color: white;
            border: none;
            border-radius: 4px;
            padding: 4px 8px;
            margin-bottom: 10px;
            font-size: 10px;
            width: 100%;
        `;
        closeButton.addEventListener('click', function() {
            panel.style.transform = 'translateY(100%)';
        });
        panel.appendChild(closeButton);
        
        // Device Information
        addSection('Device Info');
        addItem('User Agent', navigator.userAgent);
        addItem('Platform', navigator.platform);
        addItem('Vendor', navigator.vendor);
        addItem('Device Pixel Ratio', window.devicePixelRatio);
        
        // Viewport Information
        addSection('Viewport');
        addItem('Inner Width', window.innerWidth + 'px');
        addItem('Inner Height', window.innerHeight + 'px');
        addItem('Outer Width', window.outerWidth + 'px');
        addItem('Outer Height', window.outerHeight + 'px');
        addItem('Client Width', document.documentElement.clientWidth + 'px');
        addItem('Client Height', document.documentElement.clientHeight + 'px');
        addItem('Scroll Width', document.documentElement.scrollWidth + 'px');
        addItem('Scroll Height', document.documentElement.scrollHeight + 'px');
        
        // Screen Information
        addSection('Screen');
        addItem('Width', screen.width + 'px');
        addItem('Height', screen.height + 'px');
        addItem('Available Width', screen.availWidth + 'px');
        addItem('Available Height', screen.availHeight + 'px');
        
        // Browser Information
        addSection('Browser Capabilities');
        addItem('Touch Enabled', 'ontouchstart' in window ? 'Yes' : 'No');
        addItem('CSS Supports', typeof CSS.supports === 'function' ? 'Yes' : 'No');
        addItem('Request Animation Frame', typeof requestAnimationFrame === 'function' ? 'Yes' : 'No');
        
        // HTML & CSS Information 
        addSection('DOM Information');
        addItem('Body Classes', document.body.className || 'none');
        addItem('HTML Classes', document.documentElement.className || 'none');
        
        // Add event listeners for orientation change and resize
        if (!window._listenerAdded) {
            window.addEventListener('resize', function() {
                if (document.getElementById('mobile-debug-panel').style.transform !== 'translateY(100%)') {
                    collectDebugInfo();
                }
            });
            
            window.addEventListener('orientationchange', function() {
                if (document.getElementById('mobile-debug-panel').style.transform !== 'translateY(100%)') {
                    setTimeout(collectDebugInfo, 300); // Delay to ensure correct values after orientation change
                }
            });
            
            window._listenerAdded = true;
        }
        
        // Style Information
        addSection('Computed Styles');
        const body = document.body;
        const computedStyle = window.getComputedStyle(body);
        addItem('Font Size', computedStyle.fontSize);
        addItem('Background Color', computedStyle.backgroundColor);
        
        // Check if mobile-view class is present
        addItem('Has mobile-view class', body.classList.contains('mobile-view') ? 'Yes' : 'No');
        
        // Source panel info
        const sourcePanel = document.querySelector('.source-panel');
        if (sourcePanel) {
            addSection('Source Panel');
            const sourcePanelStyle = window.getComputedStyle(sourcePanel);
            addItem('Width', sourcePanelStyle.width);
            addItem('Max Width', sourcePanelStyle.maxWidth);
            addItem('Position', sourcePanelStyle.position);
            addItem('Display', sourcePanelStyle.display);
            addItem('Z-Index', sourcePanelStyle.zIndex);
            addItem('Classes', sourcePanel.className);
        }
        
        // Input container info
        const inputContainer = document.querySelector('.input-container');
        if (inputContainer) {
            addSection('Input Container');
            const inputStyle = window.getComputedStyle(inputContainer);
            addItem('Position', inputStyle.position);
            addItem('Bottom', inputStyle.bottom);
            addItem('Z-Index', inputStyle.zIndex);
        }
    }
    
    // Helper function to add a section header
    function addSection(title) {
        const panel = document.getElementById('mobile-debug-panel');
        const section = document.createElement('div');
        section.style.cssText = `
            margin-top: 10px;
            margin-bottom: 5px;
            font-weight: bold;
            color: #e40712;
            border-bottom: 1px solid #444;
            padding-bottom: 2px;
        `;
        section.textContent = title;
        panel.appendChild(section);
    }
    
    // Helper function to add an item
    function addItem(key, value) {
        const panel = document.getElementById('mobile-debug-panel');
        const item = document.createElement('div');
        item.style.cssText = `
            margin: 2px 0;
            display: flex;
        `;
        
        const keySpan = document.createElement('span');
        keySpan.style.cssText = `
            flex: 0 0 40%;
            color: #aaa;
        `;
        keySpan.textContent = key + ': ';
        
        const valueSpan = document.createElement('span');
        valueSpan.style.cssText = `
            flex: 0 0 60%;
            word-break: break-all;
        `;
        valueSpan.textContent = value;
        
        item.appendChild(keySpan);
        item.appendChild(valueSpan);
        panel.appendChild(item);
    }
}); 