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
    
    // Track errors in a global array
    window.mobileDebugErrors = [];
    window.mobileDebugEvents = [];
    window.mobileDebugLogs = [];
    
    // Track critical messages and errors
    const originalConsoleError = console.error;
    console.error = function() {
        window.mobileDebugErrors.push({
            timestamp: new Date().toISOString(),
            message: Array.from(arguments).join(' ')
        });
        originalConsoleError.apply(console, arguments);
    };
    
    const originalConsoleLog = console.log;
    console.log = function() {
        if (arguments[0] && typeof arguments[0] === 'string' && arguments[0].includes('[Debug]')) {
            window.mobileDebugLogs.push({
                timestamp: new Date().toISOString(),
                message: Array.from(arguments).join(' ')
            });
        }
        originalConsoleLog.apply(console, arguments);
    };
    
    // Setup global error catching
    window.addEventListener('error', function(e) {
        window.mobileDebugErrors.push({
            timestamp: new Date().toISOString(),
            message: `Error: ${e.message}`,
            file: e.filename,
            line: e.lineno,
            col: e.colno
        });
    });
    
    // Debug helpers for specific issues
    const mobileDebug = {
        // Track button events to debug settings button issue
        trackButtonEvents: function(buttonId) {
            const button = document.getElementById(buttonId);
            if (!button) {
                console.error(`[Debug] Button with ID ${buttonId} not found`);
                return;
            }
            
            console.log(`[Debug] Setting up event tracking for button: ${buttonId}`);
            
            // Log button details
            console.log(`[Debug] Button details:`, {
                id: button.id,
                className: button.className,
                style: button.getAttribute('style'),
                parentNode: button.parentNode?.tagName,
                innerHTML: button.innerHTML,
                boundingRect: button.getBoundingClientRect()
            });
            
            // Track all events on this button
            const events = ['click', 'touchstart', 'touchend', 'mousedown', 'mouseup'];
            events.forEach(eventType => {
                button.addEventListener(eventType, function(e) {
                    // Prevent this debug listener from interfering with the actual events
                    e.stopPropagation();
                    
                    console.log(`[Debug] Button ${eventType} event:`, {
                        type: e.type,
                        target: e.target.id || e.target.tagName,
                        timestamp: new Date().toISOString(),
                        clientX: e.clientX || (e.touches && e.touches[0] ? e.touches[0].clientX : 'N/A'),
                        clientY: e.clientY || (e.touches && e.touches[0] ? e.touches[0].clientY : 'N/A'),
                        defaultPrevented: e.defaultPrevented
                    });
                    
                    window.mobileDebugEvents.push({
                        element: buttonId,
                        event: eventType,
                        timestamp: new Date().toISOString()
                    });
                    
                    // Update debug panel if open
                    if (document.getElementById('mobile-debug-panel').style.transform !== 'translateY(100%)') {
                        collectDebugInfo();
                    }
                    
                    // Allow event to proceed normally
                    return true;
                }, true); // Use capture phase
            });
            
            console.log(`[Debug] Event tracking setup complete for button: ${buttonId}`);
        },
        
        // Track rich text rendering
        monitorRichText: function() {
            console.log(`[Debug] Setting up rich text rendering monitoring`);
            
            // Check if the marked library is available
            if (typeof marked === 'undefined') {
                console.error(`[Debug] Marked library not available!`);
            } else {
                console.log(`[Debug] Marked library is available: ${marked.version}`);
            }
            
            // Check if DNDUtilities is available
            if (!window.DNDUtilities) {
                console.error(`[Debug] DNDUtilities not available!`);
                return;
            }
            
            // Check if formatMessageText exists
            if (!window.DNDUtilities.formatMessageText) {
                console.error(`[Debug] DNDUtilities.formatMessageText not found!`);
                return;
            }
            
            // Hook into formatMessageText to debug issues
            const originalFormatMessageText = window.DNDUtilities.formatMessageText;
            window.DNDUtilities.formatMessageText = function(text) {
                console.log(`[Debug] Formatting message:`, {
                    inputLength: text?.length,
                    sample: text?.substring(0, 50) + (text?.length > 50 ? '...' : '')
                });
                
                try {
                    const result = originalFormatMessageText.apply(this, arguments);
                    console.log(`[Debug] Format result:`, {
                        outputLength: result?.length,
                        sample: result?.substring(0, 50) + (result?.length > 50 ? '...' : '')
                    });
                    return result;
                } catch (error) {
                    console.error(`[Debug] Error in formatMessageText:`, error);
                    
                    // In case of error, provide a simple fallback implementation
                    if (typeof marked !== 'undefined') {
                        try {
                            return marked.parse(text);
                        } catch (markedError) {
                            console.error(`[Debug] Fallback marked parsing failed:`, markedError);
                            return text; // Return original as last resort
                        }
                    }
                    
                    return text; // Return original text as fallback
                }
            };
            
            console.log(`[Debug] Rich text monitoring setup complete`);
        },
        
        // Initialize both debuggers
        initAll: function() {
            // Set a small delay to ensure DOM is fully loaded
            setTimeout(() => {
                try {
                    this.trackButtonEvents('mobile-settings-toggle');
                    this.monitorRichText();
                    console.log(`[Debug] All debuggers initialized`);
                } catch (error) {
                    console.error(`[Debug] Error initializing debuggers:`, error);
                }
            }, 1000);
        }
    };
    
    // Initialize all debuggers
    mobileDebug.initAll();
    
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
        
        // Add debug logs section
        if (window.mobileDebugLogs && window.mobileDebugLogs.length > 0) {
            addSection('Debug Logs (Last 5)');
            const recentLogs = window.mobileDebugLogs.slice(-5);
            recentLogs.forEach(log => {
                addItem(log.timestamp.split('T')[1].split('.')[0], log.message);
            });
        }
        
        // Add errors section
        if (window.mobileDebugErrors && window.mobileDebugErrors.length > 0) {
            addSection('Errors (Last 5)');
            const recentErrors = window.mobileDebugErrors.slice(-5);
            recentErrors.forEach(error => {
                addItem(error.timestamp.split('T')[1].split('.')[0], error.message);
            });
        }
        
        // Add button events section
        if (window.mobileDebugEvents && window.mobileDebugEvents.length > 0) {
            addSection('Button Events (Last 5)');
            const recentEvents = window.mobileDebugEvents.slice(-5);
            recentEvents.forEach(event => {
                addItem(`${event.timestamp.split('T')[1].split('.')[0]}`, `${event.element}: ${event.event}`);
            });
        }
        
        // Show settings button details
        const settingsButton = document.getElementById('mobile-settings-toggle');
        if (settingsButton) {
            addSection('Settings Button');
            const buttonStyles = window.getComputedStyle(settingsButton);
            addItem('Classes', settingsButton.className);
            addItem('Style Attr', settingsButton.getAttribute('style') || 'none');
            addItem('Z-Index', buttonStyles.zIndex);
            addItem('Position', buttonStyles.position);
            addItem('Display', buttonStyles.display);
            
            // Get bounding rect
            const rect = settingsButton.getBoundingClientRect();
            addItem('Dimensions', `${Math.round(rect.width)}x${Math.round(rect.height)}px`);
            addItem('Position', `(${Math.round(rect.left)},${Math.round(rect.top)}) to (${Math.round(rect.right)},${Math.round(rect.bottom)})`);
        }
        
        // Check for marked library
        if (typeof marked !== 'undefined') {
            addSection('Markdown');
            addItem('Marked Version', marked.version || 'unknown');
            addItem('Marked Available', 'Yes');
        } else {
            addSection('Markdown');
            addItem('Marked Available', 'No');
        }
        
        // DNDUtilities check
        addSection('Utilities');
        addItem('DNDUtilities', window.DNDUtilities ? 'Available' : 'Not Available');
        if (window.DNDUtilities) {
            addItem('formatMessageText', window.DNDUtilities.formatMessageText ? 'Available' : 'Not Available');
        }
        
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
    
    // Expose the debug console to the global scope
    window.mobileDebug = mobileDebug;
}); 