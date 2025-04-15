/**
 * Admin UI functionality for DnDSy
 */
document.addEventListener('DOMContentLoaded', function() {
    // DOM Elements
    const adminButton = document.getElementById('admin-button');
    const adminModal = document.getElementById('admin-modal');
    const adminCloseButton = document.getElementById('admin-close-button');
    const adminLoginSection = document.getElementById('admin-login-section');
    const adminContent = document.getElementById('admin-content');
    const adminPassword = document.getElementById('admin-password');
    const adminLoginButton = document.getElementById('admin-login-button');
    const adminLoginError = document.getElementById('admin-login-error');
    const tabButtons = document.querySelectorAll('.admin-tab-button');
    const tabPanes = document.querySelectorAll('.admin-tab-pane');
    
    // Constants
    const ADMIN_PASSWORD = 'DndsyAdmin';
    
    // ============================
    // Admin Modal Functionality
    // ============================
    
    // Open admin modal
    adminButton.addEventListener('click', function() {
        adminModal.style.display = 'block';
        document.body.style.overflow = 'hidden'; // Prevent body scrolling
        // Reset login form
        adminPassword.value = '';
        adminLoginError.textContent = '';
    });
    
    // Close admin modal
    adminCloseButton.addEventListener('click', function() {
        adminModal.style.display = 'none';
        document.body.style.overflow = ''; // Restore body scrolling
    });
    
    // Close modal when clicking outside
    adminModal.addEventListener('click', function(event) {
        if (event.target === adminModal) {
            adminModal.style.display = 'none';
            document.body.style.overflow = ''; // Restore body scrolling
        }
    });
    
    // ============================
    // Admin Authentication
    // ============================
    
    // Handle login button click
    adminLoginButton.addEventListener('click', function() {
        validateAdminLogin();
    });
    
    // Handle Enter key in password field
    adminPassword.addEventListener('keyup', function(event) {
        if (event.key === 'Enter') {
            validateAdminLogin();
        }
    });
    
    // Validate admin login
    function validateAdminLogin() {
        const password = adminPassword.value.trim();
        
        if (password === ADMIN_PASSWORD) {
            // Show admin content and hide login
            adminLoginSection.style.display = 'none';
            adminContent.style.display = 'block';
            
            // Force a browser reflow to ensure proper rendering
            void adminContent.offsetHeight;
            
            // Load initial data for active tab
            const activeTab = document.querySelector('.admin-tab-button.active');
            if (activeTab) {
                loadTabData(activeTab.dataset.tab);
            } else {
                // If no active tab, select the first one
                const firstTab = document.querySelector('.admin-tab-button');
                if (firstTab) {
                    firstTab.click();
                }
            }
        } else {
            adminLoginError.textContent = 'Incorrect password. Please try again.';
            adminPassword.value = '';
            adminPassword.focus();
        }
    }
    
    // ============================
    // Tab Navigation
    // ============================
    
    // Handle tab clicks
    tabButtons.forEach(button => {
        button.addEventListener('click', function() {
            const tabName = this.dataset.tab;
            
            // Update active tab button
            tabButtons.forEach(btn => btn.classList.remove('active'));
            this.classList.add('active');
            
            // Update active tab pane
            tabPanes.forEach(pane => pane.classList.remove('active'));
            const targetPane = document.getElementById(`${tabName}-tab`);
            if (targetPane) {
                targetPane.classList.add('active');
                
                // Force a browser reflow to ensure proper rendering
                void targetPane.offsetHeight;
                
                // Load tab-specific data
                loadTabData(tabName);
            }
        });
    });
    
    // Load data based on active tab
    function loadTabData(tabName) {
        switch(tabName) {
            case 'data-processing':
                // Nothing to load initially, will be loaded on button click
                ensureCheckboxesVisible('data-processing-tab');
                break;
                
            case 'file-management':
                // Will be loaded on button click
                break;
                
            case 'vector-db':
                // Will be loaded on button click
                break;
                
            case 'api-costs':
                // Will be loaded on button click
                break;
                
            case 'config':
                loadSystemPrompt();
                loadEnvironmentVars();
                break;
                
            case 'links':
                // Static links, nothing to load
                break;
        }
    }
    
    // Ensure checkboxes and radio buttons are visible 
    function ensureCheckboxesVisible(tabId) {
        const tab = document.getElementById(tabId);
        if (!tab) return;
        
        // Force checkbox visibility by toggling a class
        const checkboxes = tab.querySelectorAll('input[type="checkbox"], input[type="radio"]');
        checkboxes.forEach(checkbox => {
            checkbox.classList.add('visible-input');
            checkbox.style.opacity = '1';
            checkbox.style.position = 'static';
        });
    }
    
    // ============================
    // Data Processing Tab
    // ============================
    
    const processButton = document.getElementById('process-button');
    const processStatus = document.getElementById('process-status');
    const loadHistoryButton = document.getElementById('load-history-button');
    const processingHistory = document.getElementById('processing-history');
    
    // Elements for live processing status (now in a modal)
    const liveStatusModal = document.getElementById('live-status-modal');
    const liveStatusModalOverlay = document.getElementById('live-status-modal-overlay');
    const liveStatusCloseButton = document.getElementById('live-status-close-button');
    const liveStatusSummary = document.getElementById('live-status-summary');
    const liveMilestones = document.getElementById('live-milestones');
    const liveLogs = document.getElementById('live-logs');
    const cancelProcessingButton = document.getElementById('cancel-processing-button');
    
    let currentEventSource = null; // To hold the active EventSource connection
    let currentRunId = null; // Track the current run ID

    // Process documents button
    processButton.addEventListener('click', function() {
        // Get selected store types
        const storeCheckboxes = document.querySelectorAll('input[type="checkbox"]:checked');
        const storeTypes = Array.from(storeCheckboxes).map(cb => cb.value);
        
        if (storeTypes.length === 0) {
            showStatus(processStatus, 'Please select at least one vector store type', 'error');
            return;
        }
        
        // Get cache behavior
        const cacheBehavior = document.querySelector('input[name="cache-behavior"]:checked');
        if (!cacheBehavior) {
            showStatus(processStatus, 'Please select a cache behavior option', 'error');
            return;
        }
        
        // Get S3 prefix (optional)
        const s3Prefix = document.getElementById('s3-prefix').value.trim();
        
        // Prepare request data
        const requestData = {
            store_types: storeTypes,
            cache_behavior: cacheBehavior.value
        };
        
        if (s3Prefix) {
            requestData.s3_prefix = s3Prefix;
        }
        
        // Confirm with user
        const confirmMessage = `Process documents with the following settings?\n\n` +
            `Vector Stores: ${storeTypes.join(', ')}\n` +
            `Cache Behavior: ${cacheBehavior.value}\n` +
            (s3Prefix ? `S3 Prefix: ${s3Prefix}\n` : '') +
            `\nThis operation may take several minutes.`;
        
        if (!confirm(confirmMessage)) {
            return;
        }
        
        // Update UI - Clear previous live status, disable button
        processButton.disabled = true;
        // showStatus(processStatus, 'Initiating processing run...', 'info'); // Removed old status display
        liveMilestones.innerHTML = ''; // Clear milestones
        liveLogs.innerHTML = ''; // Clear logs
        liveStatusSummary.className = 'admin-status info'; // Reset summary style
        liveStatusSummary.textContent = 'Initiating...';
        cancelProcessingButton.style.display = 'none'; // Hide cancel button initially

        // Send request to API
        fetch('/api/admin/process', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestData)
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => {
                    throw new Error(err.error || 'Failed to process documents');
                });
            }
            return response.json();
        })
        .then(data => {
            if (data.success && data.run_id) {
                // SUCCESS: Show the modal and start listening to the SSE stream
                // showStatus(processStatus, `Processing run ${data.run_id.substring(0, 8)}... started. See live status below.`, 'info'); // Removed old status display
                currentRunId = data.run_id;
                liveStatusModal.style.display = 'block'; // Show live status modal
                liveStatusModalOverlay.style.display = 'block';
                cancelProcessingButton.style.display = 'inline-block'; // Show cancel button
                startProcessingStream(data.run_id);
            } else {
                // Handle cases where the API call succeeded but didn't return a run_id (shouldn't happen)
                throw new Error(data.message || 'Processing initiation failed to return a run ID.');
            }
        })
        .catch(error => {
            // showStatus(processStatus, `Error: ${error.message}`, 'error'); // Removed old status display
            alert(`Error initiating processing: ${error.message}`); // Use alert for initiation errors now
            processButton.disabled = false; // Re-enable button on error
        });
    });
    
    // Function to start listening to the processing stream
    function startProcessingStream(runId) {
        if (currentEventSource) {
            currentEventSource.close(); // Close any existing connection
        }

        const eventSourceUrl = `/api/admin/process_stream/${runId}`;
        console.log(`Connecting to SSE: ${eventSourceUrl}`);
        currentEventSource = new EventSource(eventSourceUrl);

        currentEventSource.onopen = function() {
            console.log("SSE connection opened for run:", runId);
            liveStatusSummary.textContent = 'Connected to processing stream...';
            liveStatusSummary.className = 'admin-status info';
        };

        currentEventSource.onerror = function(event) {
            console.error("SSE Error: ", event);
            let errorMessage = "Connection error with processing stream.";
            if (event.target && event.target.readyState === EventSource.CLOSED) {
                 errorMessage = "Connection closed unexpectedly.";
            } else if (event.message) {
                 errorMessage = `Stream error: ${event.message}`;
            }
            // showStatus(processStatus, `Error: ${errorMessage}`, 'error'); // Removed old status display
            liveStatusSummary.textContent = `Error: ${errorMessage}`;
            liveStatusSummary.className = 'admin-status error';
            closeProcessingStream(false); // Close and indicate failure
        };

        // Listener for general updates (log, milestone, progress, etc.)
        currentEventSource.addEventListener('update', function(event) {
            try {
                const data = JSON.parse(event.data);
                console.log("SSE update:", data);
                handleStreamUpdate(data);
            } catch (e) {
                console.error("Error parsing SSE update data:", e);
                // Add raw data as log if parsing fails
                addLogLine(`[RAW] ${event.data}`);
            }
        });

        // Listener for specific error events from the stream
        currentEventSource.addEventListener('error', function(event) {
            try {
                const data = JSON.parse(event.data);
                console.error("SSE stream error event:", data);
                // showStatus(processStatus, `Stream Error: ${data.message || 'Unknown stream error'}`, 'error'); // Removed old status display
                liveStatusSummary.textContent = `Error: ${data.message || 'Unknown stream error'}`;
                liveStatusSummary.className = 'admin-status error';
            } catch (e) {
                console.error("Error parsing SSE error data:", e);
                showStatus(processStatus, 'Received an unparsable stream error.', 'error');
            }
            // Don't close stream here, wait for 'end' or onerror
        });

        // Listener for the final end event
        currentEventSource.addEventListener('end', function(event) {
            console.log("SSE end event received:", event.data);
             try {
                const data = JSON.parse(event.data);
                // Use the status field from the end event data
                const finalStatus = data.status || ('Unknown Status'); 
                const finalMessage = `Run finished. Status: ${finalStatus}${data.duration ? ` (Duration: ${data.duration}s)` : ''}`;
                
                // Update ONLY the live summary status
                liveStatusSummary.textContent = finalMessage;
                liveStatusSummary.className = data.success ? 'admin-status success' : 'admin-status error';
                // Clear the old status message - No longer needed
                // showStatus(processStatus, '', ''); 
                // processStatus.style.display = 'none'; 

            } catch (e) {
                console.error("Error parsing SSE end data:", e);
                 const fallbackMessage = "Processing run finished, but status couldn't be parsed.";
                 liveStatusSummary.textContent = fallbackMessage;
                 liveStatusSummary.className = 'admin-status warning';
                 // Clear the old status message - No longer needed
                 // showStatus(processStatus, '', '');
                 // processStatus.style.display = 'none'; 
            }
            closeProcessingStream(true); // Close stream after end event
            
            // Change Cancel button to Close button
            // Re-select the button by ID inside the handler to ensure we have the correct node
            const buttonToUpdate = document.getElementById('cancel-processing-button');
            if (buttonToUpdate) {
                buttonToUpdate.textContent = 'Close';
                buttonToUpdate.style.backgroundColor = ''; // Reset background color
                // Remove previous listener and add a new one to just close the modal
                const newCloseButton = buttonToUpdate.cloneNode(true);
                // Replace the updated button in the DOM before adding listener to the new node
                buttonToUpdate.parentNode.replaceChild(newCloseButton, buttonToUpdate);
                newCloseButton.addEventListener('click', () => {
                    liveStatusModal.style.display = 'none';
                    liveStatusModalOverlay.style.display = 'none';
                });
            } else {
                console.warn("Could not find cancel/close button to update on stream end.");
            }
        });
        
        // Add listener for the cancel button
        // Remove previous listener if any to avoid duplicates
        cancelProcessingButton.replaceWith(cancelProcessingButton.cloneNode(true));
        // Re-select the button after cloning
        const newCancelButton = document.getElementById('cancel-processing-button'); 
        if (newCancelButton) {
             newCancelButton.style.display = 'inline-block'; // Ensure it's visible
             newCancelButton.addEventListener('click', handleCancelProcessing);
        }
    }
    
    // Function to handle updates received from the SSE stream
    function handleStreamUpdate(data) {
        switch(data.type) {
            case 'start':
                liveStatusSummary.textContent = data.message || 'Processing started.';
                // addLogLine(`[START] ${data.message}`); // Don't clutter logs
                break;
            case 'milestone':
                addMilestone(data.message, data.long_running, data.id);
                // addLogLine(`[MILESTONE] ${data.message}`); // Don't clutter logs
                // Update summary only when a *specific* long-running task starts/finishes
                if (data.id) { 
                    liveStatusSummary.textContent = data.message;
                }
                break;
            case 'log':
                addLogLine(data.message); // Only add explicit logs
                break;
            case 'summary':
                 addLogLine(`[SUMMARY] Unique PDFs: ${data.unique_pdfs}. Details: ${JSON.stringify(data.details)}`); // Keep summary log
                 break;
            case 'progress': // Placeholder for future progress bar handling
                // Update progress bar for data.document / data.step ?
                // addLogLine(`[PROGRESS] ${data.document ? data.document + ' - ' : ''}${data.step}: ${data.value * 100}%`); // Optional: Log progress?
                break;
            case 'error': // Handle errors reported by the script itself
                addLogLine(`[ERROR] ${data.message}`, 'error');
                liveStatusSummary.textContent = `Error: ${data.message}`;
                liveStatusSummary.className = 'admin-status error';
                break;
            // Ignore 'end' type here, it's handled by the specific 'end' event listener
        }
    }

    // Function to add a log line to the live log view
    function addLogLine(message, level = 'info') {
        const logEntry = document.createElement('div');
        logEntry.textContent = message;
        if (level === 'error') {
            logEntry.style.color = 'var(--accent-color)';
        }
        liveLogs.appendChild(logEntry);
        // Auto-scroll to the bottom
        liveLogs.scrollTop = liveLogs.scrollHeight;
    }

    // Function to add a milestone
    function addMilestone(message, isLongRunning = false, id = null) {
        let milestoneEntry = null;
        const elementId = id ? `milestone-${id}` : null;
        
        // If an ID is provided, try to find an existing element
        if (elementId) {
            milestoneEntry = document.getElementById(elementId);
        }
        
        if (milestoneEntry) {
            // Existing milestone found - Update it (assume it's finishing)
            milestoneEntry.innerHTML = `<i class="fas fa-check-circle" style="color: #28a745; margin-right: 5px;"></i> ${message}`;
        } else {
            // No existing milestone found OR no ID provided - Create a new one
            milestoneEntry = document.createElement('div');
            milestoneEntry.classList.add('milestone');
            if (elementId) {
                 milestoneEntry.id = elementId;
            }
            
            let content = `<i class="fas fa-check-circle" style="color: #28a745; margin-right: 5px;"></i> ${message}`;
            // Use spinner only if it's explicitly a long-running task *start*
            if (isLongRunning) {
                content = `<i class="fas fa-spinner fa-spin" style="margin-right: 5px;"></i> ${message}`;
            }
            milestoneEntry.innerHTML = content;
            liveMilestones.appendChild(milestoneEntry);
        }
    }

    // Add event listener for the live status modal close button
    if (liveStatusCloseButton) {
        liveStatusCloseButton.addEventListener('click', () => {
            liveStatusModal.style.display = 'none';
            liveStatusModalOverlay.style.display = 'none';
            // Note: We don't close the EventSource here, 
            // processing continues in the background.
        });
    }

    // Function to close the SSE stream and update UI
    function closeProcessingStream(finishedNaturally) {
        if (currentEventSource) {
            currentEventSource.close();
            currentEventSource = null;
            console.log("SSE connection closed for run:", currentRunId);
        }
        processButton.disabled = false; // Re-enable process button
        cancelProcessingButton.style.display = 'none'; // Hide cancel button
        
        // Hide the modal if the stream ends (naturally or error)
        // Unless the user manually closed it already.
        if (liveStatusModal.style.display === 'block') {
            // Keep the modal open for a short time to show final status?
            // Or close immediately:
            // liveStatusModal.style.display = 'none';
            // liveStatusModalOverlay.style.display = 'none';
            // For now, let's keep it open showing the final status.
            // The user can close it manually.
        }

        // If the stream didn't finish naturally (e.g., error, manual cancel), 
        // ensure the final status reflects interruption if not already set.
        if (!finishedNaturally && liveStatusSummary.textContent.startsWith('Connected')) {
            liveStatusSummary.textContent = "Stream interrupted.";
            liveStatusSummary.className = 'admin-status warning';
            // showStatus(processStatus, '', ''); // Removed old status display
            // processStatus.style.display = 'none'; 
        } 
        // Reset run ID *after* potential history refresh
        currentRunId = null;
        
        // Refresh history whenever the stream closes after a run started
        // Add a small delay before refreshing history to allow backend to potentially update the file
        setTimeout(() => {
            console.log("Refreshing history after stream closed...");
            loadHistoryButton.click(); // Trigger history reload
        }, 500); 
    }
    
    // Function to handle cancel button click
    function handleCancelProcessing() {
        if (!currentRunId) {
            alert("No active processing run to cancel.");
            return;
        }
        
        const runIdShort = currentRunId.substring(0,8);
        
        if (!confirm(`Are you sure you want to attempt to cancel processing run ${runIdShort}...? This might leave things in an inconsistent state.`)) {
            return;
        }
        
        console.log(`Attempting to cancel run: ${currentRunId}`);
        liveStatusSummary.textContent = "Sending cancellation request...";
        liveStatusSummary.className = 'admin-status warning';
        cancelProcessingButton.disabled = true; // Disable button while cancelling

        // Send request to backend to cancel
        fetch(`/api/admin/cancel_run/${currentRunId}`, {
            method: 'POST',
            headers: {
                 // Add any necessary headers, e.g., CSRF token if implemented
            }
        })
        .then(response => response.json()) // Always expect JSON back
        .then(data => {
            console.log("Cancel response:", data);
            if (data.success) {
                 alert(`Cancellation signal sent to run ${runIdShort}.`);
                 // Update UI immediately, but stream closure will handle final state
                 liveStatusSummary.textContent = "Cancellation signal sent...";
                 liveStatusSummary.className = 'admin-status warning';
                 // Close the modal after user dismisses the alert
                 liveStatusModal.style.display = 'none';
                 liveStatusModalOverlay.style.display = 'none';
            } else {
                alert(`Failed to cancel run ${runIdShort}: ${data.message || 'Unknown error'}`);
                liveStatusSummary.textContent = `Cancellation failed: ${data.message || 'Unknown error'}`;
                liveStatusSummary.className = 'admin-status error';
                 cancelProcessingButton.disabled = false; // Re-enable if cancel failed
            }
             // Don't close the stream here; let the backend thread finish and send the 'end' event
             // which will trigger closeProcessingStream.
        })
        .catch(error => {
            console.error("Error sending cancel request:", error);
            alert(`Error sending cancellation request: ${error.message}`);
            liveStatusSummary.textContent = `Cancellation request error: ${error.message}`;
            liveStatusSummary.className = 'admin-status error';
            cancelProcessingButton.disabled = false; // Re-enable on fetch error
        });

        // // For now, we just close the stream and update UI - REMOVED OLD LOGIC
        // liveStatusSummary.textContent = "Cancellation requested...";
        // liveStatusSummary.className = 'admin-status warning';
        // closeProcessingStream(false); // Close stream, indicate not finished naturally
        // alert("Frontend cancelled stream. Backend cancellation needs implementation.");
    }

    // Load processing history
    loadHistoryButton.addEventListener('click', function() {
        loadHistoryButton.disabled = true;
        processingHistory.innerHTML = '<p>Loading history...</p>';
        
        fetch('/api/admin/history')
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => {
                    throw new Error(err.error || 'Failed to load history');
                });
            }
            return response.json();
        })
        .then(data => {
            displayProcessingHistory(data);
        })
        .catch(error => {
            processingHistory.innerHTML = `<p class="admin-error">Error: ${error.message}</p>`;
        })
        .finally(() => {
            loadHistoryButton.disabled = false;
        });
    });
    
    // Display processing history data
    function displayProcessingHistory(data) {
        if (!data || data.length === 0) { // Check if array is empty
            processingHistory.innerHTML = '<p>No processing run history available.</p>';
            return;
        }
        
        let html = `
            <table class="admin-table">
                <thead>
                    <tr>
                        <th>Start Time</th>
                        <th>Duration</th>
                        <th>Status</th>
                        <th>Parameters</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
        `;
        
        // Data is already sorted by start time (newest first) from the backend
        for (const run of data) {
            const startTime = new Date(run.start_time).toLocaleString();
            const duration = run.duration_seconds !== null ? `${run.duration_seconds.toFixed(1)}s` : 'N/A';
            const statusClass = run.status.toLowerCase().includes('fail') ? 'admin-error' : (run.status === 'Running' ? 'admin-info' : 'admin-success');
            const statusText = run.status;
            const params = run.parameters;
            const paramsSummary = `Stores: ${params.store_types.join(', ') || 'N/A'}; Cache: ${params.cache_behavior}; Prefix: ${params.s3_prefix || 'None'}`;
            
            // Determine button class and action based on status
            let buttonHtml;
            if (run.status === 'Running' && run.run_id === currentRunId) {
                // Special button/class to reopen live modal
                buttonHtml = `<button class="admin-button view-live-log-button" data-run-id="${run.run_id}">View Live Status</button>`;
            } else {
                // Standard button to view historical log
                buttonHtml = `<button class="admin-button view-log-button" data-run-id="${run.run_id}" ${run.status === 'Running' ? 'disabled' : ''}>View Log</button>`;
            }

            html += `
                <tr>
                    <td>${startTime}</td>
                    <td>${duration}</td>
                    <td><span class="${statusClass}" style="padding: 2px 5px; border-radius: 3px;">${statusText}</span></td>
                    <td title="${run.command}">${paramsSummary}</td>
                    <td>${buttonHtml}</td>
                </tr>
            `;
        }
        
        html += `
                </tbody>
            </table>
        `;
        
        processingHistory.innerHTML = html;
        
        // Add event listeners to the history action buttons
        processingHistory.querySelectorAll('.view-log-button, .view-live-log-button').forEach(button => {
            button.addEventListener('click', function() {
                const clickedRunId = this.dataset.runId;
                if (this.classList.contains('view-live-log-button')) {
                    // Reopen the live modal if it matches the current run
                    if (clickedRunId === currentRunId && currentEventSource) {
                        liveStatusModal.style.display = 'block';
                        liveStatusModalOverlay.style.display = 'block';
                    } else {
                        // Edge case: Button says live, but stream is no longer active? Show log.
                        alert("Live stream for this run is no longer active. Showing historical log instead.");
                        viewRunLog(clickedRunId);
                    }
                } else {
                    // Fetch and show historical log
                    viewRunLog(clickedRunId);
                }
            });
        });
    }
    
    // Function to view a specific run log
    function viewRunLog(runId) {
        const logModal = document.getElementById('log-modal');
        const logContent = document.getElementById('log-content');
        const logModalTitle = document.getElementById('log-modal-title');
        const logCloseButton = document.getElementById('log-close-button');
        const modalOverlay = document.getElementById('log-modal-overlay');

        if (!logModal || !logContent || !logModalTitle || !logCloseButton || !modalOverlay) {
            console.error("Log modal elements not found!");
            alert("Error: Could not display log modal.");
            return;
        }
        
        logModalTitle.textContent = `Log for Run: ${runId.substring(0, 8)}...`;
        logContent.textContent = 'Loading log...';
        logModal.style.display = 'block';
        modalOverlay.style.display = 'block';

        fetch(`/api/admin/run_log/${runId}`)
            .then(response => {
                if (!response.ok) {
                    return response.text().then(text => {
                        throw new Error(`Failed to load log (${response.status}): ${text}`);
                    });
                }
                return response.text();
            })
            .then(logData => {
                logContent.textContent = logData;
            })
            .catch(error => {
                logContent.textContent = `Error loading log:\n${error.message}`;
                logContent.style.color = 'var(--accent-color)'; // Use accent color for error
            });
    }

    // Add event listener to close the log modal
    const logCloseButton = document.getElementById('log-close-button');
    const logModalOverlay = document.getElementById('log-modal-overlay');
    if (logCloseButton && logModalOverlay) {
        const logModal = document.getElementById('log-modal');
        logCloseButton.addEventListener('click', () => {
            logModal.style.display = 'none';
            logModalOverlay.style.display = 'none';
            // Reset potential error styling
            const logContent = document.getElementById('log-content');
            if(logContent) logContent.style.color = ''; 
        });
        logModalOverlay.addEventListener('click', () => {
            logModal.style.display = 'none';
            logModalOverlay.style.display = 'none';
            const logContent = document.getElementById('log-content');
             if(logContent) logContent.style.color = '';
        });
    } else {
        console.warn("Log modal close button or overlay not found during initial setup.");
    }
    
    // ============================
    // File Management Tab
    // ============================
    
    const uploadButton = document.getElementById('upload-button');
    const uploadStatus = document.getElementById('upload-status');
    const loadPdfsButton = document.getElementById('load-pdfs-button');
    const pdfList = document.getElementById('pdf-list');
    const fileInput = document.getElementById('pdf-upload');
    const dropZone = document.getElementById('drop-zone');
    const fileListContainer = document.getElementById('file-list');
    const browseLink = document.getElementById('browse-link');
    
    let selectedFile = null; // Store the selected file
    
    // --- Drag and Drop --- 

    // Prevent default drag behaviors
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
        document.body.addEventListener(eventName, preventDefaults, false); // Prevent accidental drops outside the zone
    });
    
    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }
    
    // Highlight drop zone when item is dragged over
    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, highlight, false);
    });
    
    // Remove highlight when item leaves drop zone
    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, unhighlight, false);
    });
    
    function highlight(e) {
        dropZone.classList.add('dragover');
    }
    
    function unhighlight(e) {
        dropZone.classList.remove('dragover');
    }
    
    // Handle dropped files
    dropZone.addEventListener('drop', handleDrop, false);
    
    function handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        handleFiles(files);
    }
    
    // Handle file selection via browse link
    browseLink.addEventListener('click', (e) => {
        e.preventDefault();
        fileInput.click();
    });
    
    // Handle file selection via input
    fileInput.addEventListener('change', function() {
        handleFiles(this.files);
    });
    
    // Process selected/dropped files
    function handleFiles(files) {
        if (files.length > 1) {
            showStatus(uploadStatus, 'Please upload only one file at a time.', 'warning');
            return;
        }
        
        if (files.length === 0) {
            return; // No file selected/dropped
        }
        
        const file = files[0];
        
        if (!file.name.toLowerCase().endsWith('.pdf')) {
            showStatus(uploadStatus, 'Only PDF files are supported', 'error');
            clearSelectedFile();
            return;
        }
        
        selectedFile = file;
        displaySelectedFile(file);
        showStatus(uploadStatus, '', ''); // Clear previous status
    }
    
    // Display the selected file in the list
    function displaySelectedFile(file) {
        fileListContainer.innerHTML = ''; // Clear previous file
        const fileItem = document.createElement('div');
        fileItem.classList.add('file-list-item');
        fileItem.innerHTML = `
            <span>${file.name} (${formatFileSize(file.size)})</span>
            <button class="remove-file-btn" title="Remove file">&times;</button>
        `;
        fileListContainer.appendChild(fileItem);
        
        // Add event listener to remove button
        fileItem.querySelector('.remove-file-btn').addEventListener('click', clearSelectedFile);
    }
    
    // Clear the selected file display
    function clearSelectedFile() {
        selectedFile = null;
        fileInput.value = ''; // Reset the file input
        fileListContainer.innerHTML = '';
    }

    // Upload PDF to S3
    uploadButton.addEventListener('click', function() {
        // const fileInput = document.getElementById('pdf-upload'); // Removed - using selectedFile now
        const prefix = document.getElementById('upload-prefix').value.trim();
        
        // Use the stored selectedFile instead of fileInput.files
        if (!selectedFile) {
            showStatus(uploadStatus, 'Please select or drop a PDF file to upload', 'error');
            return;
        }
        
        // Removed file type check here as it's done in handleFiles
        // const file = fileInput.files[0];
        // if (!file.name.toLowerCase().endsWith('.pdf')) {
        //     showStatus(uploadStatus, 'Only PDF files are supported', 'error');
        //     return;
        // }
        
        const formData = new FormData();
        formData.append('file', selectedFile);
        if (prefix) {
            formData.append('prefix', prefix);
        }
        
        // Update UI
        uploadButton.disabled = true;
        showStatus(uploadStatus, 'Uploading file...', 'info');
        
        // Send request to API
        fetch('/api/admin/upload', {
            method: 'POST',
            body: formData
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => {
                    throw new Error(err.error || 'Failed to upload file');
                });
            }
            return response.json();
        })
        .then(data => {
            showStatus(uploadStatus, `Upload complete. File saved as: ${data.key}`, 'success');
            clearSelectedFile(); // Clear the selected file display
        })
        .catch(error => {
            showStatus(uploadStatus, `Error: ${error.message}`, 'error');
        })
        .finally(() => {
            uploadButton.disabled = false;
        });
    });
    
    // List PDFs from S3
    loadPdfsButton.addEventListener('click', function() {
        loadPdfsButton.disabled = true;
        pdfList.innerHTML = '<p>Loading PDFs from S3...</p>';
        
        fetch('/api/admin/list-pdfs')
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => {
                    throw new Error(err.error || 'Failed to list PDFs');
                });
            }
            return response.json();
        })
        .then(data => {
            displayPdfList(data.pdfs);
        })
        .catch(error => {
            pdfList.innerHTML = `<p class="admin-error">Error: ${error.message}</p>`;
        })
        .finally(() => {
            loadPdfsButton.disabled = false;
        });
    });
    
    // Display PDF list
    function displayPdfList(pdfs) {
        if (!pdfs || pdfs.length === 0) {
            pdfList.innerHTML = '<p>No PDFs found in S3.</p>';
            return;
        }
        
        let html = `
            <table class="admin-table">
                <thead>
                    <tr>
                        <th>Filename</th>
                        <th>S3 Key</th>
                        <th>Size</th>
                        <th>Last Modified</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
        `;
        
        for (const pdf of pdfs) {
            const filename = pdf.key.split('/').pop();
            const size = formatFileSize(pdf.size);
            const lastModified = new Date(pdf.last_modified).toLocaleString();
            
            html += `
                <tr>
                    <td>${filename}</td>
                    <td>${pdf.key}</td>
                    <td>${size}</td>
                    <td>${lastModified}</td>
                    <td>
                        <button class="admin-button" onclick="deletePdf('${pdf.key}')">Delete</button>
                    </td>
                </tr>
            `;
        }
        
        html += `
                </tbody>
            </table>
        `;
        
        pdfList.innerHTML = html;
    }
    
    // Format file size
    function formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }
    
    // Delete PDF from S3
    window.deletePdf = function(key) {
        if (!confirm(`Are you sure you want to delete this PDF?\n\n${key}`)) {
            return;
        }
        
        fetch('/api/admin/delete-pdf', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ key })
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => {
                    throw new Error(err.error || 'Failed to delete PDF');
                });
            }
            return response.json();
        })
        .then(data => {
            alert(`PDF deleted: ${key}`);
            // Refresh PDF list
            loadPdfsButton.click();
        })
        .catch(error => {
            alert(`Error: ${error.message}`);
        });
    };
    
    // ============================
    // Vector DB Tab
    // ============================
    
    const loadCollectionsButton = document.getElementById('load-collections-button');
    const collectionsStats = document.getElementById('collections-stats');
    const collectionSelect = document.getElementById('collection-select');
    const loadPointsButton = document.getElementById('load-points-button');
    const collectionPoints = document.getElementById('collection-points');
    
    // Load collections
    loadCollectionsButton.addEventListener('click', function() {
        loadCollectionsButton.disabled = true;
        collectionsStats.innerHTML = '<p>Loading collections...</p>';
        
        fetch('/api/admin/collections')
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => {
                    throw new Error(err.error || 'Failed to load collections');
                });
            }
            return response.json();
        })
        .then(data => {
            displayCollectionsStats(data.collections);
        })
        .catch(error => {
            collectionsStats.innerHTML = `<p class="admin-error">Error: ${error.message}</p>`;
        })
        .finally(() => {
            loadCollectionsButton.disabled = false;
        });
    });
    
    // Display collections stats
    function displayCollectionsStats(collections) {
        if (!collections || collections.length === 0) {
            collectionsStats.innerHTML = '<p>No collections found.</p>';
            return;
        }
        
        let html = `
            <table class="admin-table">
                <thead>
                    <tr>
                        <th>Collection Name</th>
                        <th>Vector Size</th>
                        <th>Points Count</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
        `;
        
        for (const collection of collections) {
            html += `
                <tr>
                    <td>${collection.name}</td>
                    <td>${collection.vector_size}</td>
                    <td>${collection.points_count.toLocaleString()}</td>
                    <td>${collection.status}</td>
                </tr>
            `;
        }
        
        html += `
                </tbody>
            </table>
        `;
        
        collectionsStats.innerHTML = html;
    }
    
    // Load sample points from collection
    loadPointsButton.addEventListener('click', function() {
        const collectionName = collectionSelect.value;
        
        loadPointsButton.disabled = true;
        collectionPoints.innerHTML = '<p>Loading points...</p>';
        
        fetch(`/api/admin/points?collection=${collectionName}`)
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => {
                    throw new Error(err.error || 'Failed to load points');
                });
            }
            return response.json();
        })
        .then(data => {
            displayCollectionPoints(data.points);
        })
        .catch(error => {
            collectionPoints.innerHTML = `<p class="admin-error">Error: ${error.message}</p>`;
        })
        .finally(() => {
            loadPointsButton.disabled = false;
        });
    });
    
    // Display collection points
    function displayCollectionPoints(points) {
        if (!points || points.length === 0) {
            collectionPoints.innerHTML = '<p>No points found in this collection.</p>';
            return;
        }
        
        let html = `<h4>Sample Points (${points.length})</h4>`;
        
        for (let i = 0; i < points.length; i++) {
            const point = points[i];
            html += `
                <div class="admin-section">
                    <h5>Point ${i+1} (ID: ${point.id})</h5>
                    <div class="admin-form-group">
                        <label>Text</label>
                        <textarea readonly rows="3">${point.payload.text}</textarea>
                    </div>
                    <div class="admin-form-group">
                        <label>Metadata</label>
                        <pre>${JSON.stringify(point.payload.metadata, null, 2)}</pre>
                    </div>
                </div>
            `;
        }
        
        collectionPoints.innerHTML = html;
    }
    
    // ============================
    // API Costs Tab
    // ============================
    
    const loadApiCostsButton = document.getElementById('load-api-costs-button');
    const apiCosts = document.getElementById('api-costs');
    
    // Load API costs
    loadApiCostsButton.addEventListener('click', function() {
        loadApiCostsButton.disabled = true;
        apiCosts.innerHTML = '<p>Loading API usage statistics...</p>';
        
        fetch('/api/admin/api-costs')
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => {
                    throw new Error(err.error || 'Failed to load API costs');
                });
            }
            return response.json();
        })
        .then(data => {
            displayApiCosts(data);
        })
        .catch(error => {
            apiCosts.innerHTML = `<p class="admin-error">Error: ${error.message}</p>`;
        })
        .finally(() => {
            loadApiCostsButton.disabled = false;
        });
    });
    
    // Display API costs
    function displayApiCosts(data) {
        if (!data || !data.usage) {
            apiCosts.innerHTML = '<p>No API usage data available.</p>';
            return;
        }
        
        let html = '';
        
        // Add disclaimer if this is mock data
        if (data.is_mock_data) {
            html += `
                <div class="admin-status warning" style="margin-bottom: 20px;">
                    <strong>Demo Data:</strong> This is sample data for demonstration purposes only. 
                    To track actual API usage, please implement one of the approaches described in the server-side code.
                </div>
            `;
        }
        
        html += `
            <div class="admin-section">
                <h4>Current Cost Summary</h4>
                <table class="admin-table">
                    <tr>
                        <th>Period</th>
                        <td>${data.period}</td>
                    </tr>
                    <tr>
                        <th>Total Cost</th>
                        <td>$${data.total_cost.toFixed(2)}</td>
                    </tr>
                </table>
            </div>
            
            <div class="admin-section">
                <h4>Usage Breakdown</h4>
                <table class="admin-table">
                    <thead>
                        <tr>
                            <th>Model</th>
                            <th>Request Count</th>
                            <th>Input Tokens</th>
                            <th>Output Tokens</th>
                            <th>Cost</th>
                        </tr>
                    </thead>
                    <tbody>
        `;
        
        for (const model of data.usage) {
            html += `
                <tr>
                    <td>${model.name}</td>
                    <td>${model.requests.toLocaleString()}</td>
                    <td>${model.input_tokens.toLocaleString()}</td>
                    <td>${model.output_tokens.toLocaleString()}</td>
                    <td>$${model.cost.toFixed(2)}</td>
                </tr>
            `;
        }
        
        html += `
                    </tbody>
                </table>
            </div>
        `;
        
        apiCosts.innerHTML = html;
    }
    
    // ============================
    // Configuration Tab
    // ============================
    
    const systemPrompt = document.getElementById('system-prompt');
    const savePromptButton = document.getElementById('save-prompt-button');
    const promptStatus = document.getElementById('prompt-status');
    const envVars = document.getElementById('env-vars');
    
    // Load system prompt
    function loadSystemPrompt() {
        systemPrompt.value = 'Loading...';
        systemPrompt.disabled = true;
        
        fetch('/api/admin/config?key=system_prompt')
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => {
                    throw new Error(err.error || 'Failed to load system prompt');
                });
            }
            return response.json();
        })
        .then(data => {
            systemPrompt.value = data.value || '';
            systemPrompt.disabled = false;
        })
        .catch(error => {
            systemPrompt.value = '';
            systemPrompt.disabled = false;
            showStatus(promptStatus, `Error: ${error.message}`, 'error');
        });
    }
    
    // Save system prompt
    savePromptButton.addEventListener('click', function() {
        const prompt = systemPrompt.value.trim();
        
        if (!prompt) {
            showStatus(promptStatus, 'System prompt cannot be empty', 'error');
            return;
        }
        
        savePromptButton.disabled = true;
        showStatus(promptStatus, 'Saving system prompt...', 'info');
        
        fetch('/api/admin/config', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                key: 'system_prompt',
                value: prompt
            })
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => {
                    throw new Error(err.error || 'Failed to save system prompt');
                });
            }
            return response.json();
        })
        .then(data => {
            showStatus(promptStatus, 'System prompt saved successfully', 'success');
        })
        .catch(error => {
            showStatus(promptStatus, `Error: ${error.message}`, 'error');
        })
        .finally(() => {
            savePromptButton.disabled = false;
        });
    });
    
    // Load environment variables
    function loadEnvironmentVars() {
        envVars.innerHTML = '<p>Loading environment variables...</p>';
        
        fetch('/api/admin/env')
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => {
                    throw new Error(err.error || 'Failed to load environment variables');
                });
            }
            return response.json();
        })
        .then(data => {
            displayEnvironmentVars(data.env);
        })
        .catch(error => {
            envVars.innerHTML = `<p class="admin-error">Error: ${error.message}</p>`;
        });
    }
    
    // Display environment variables
    function displayEnvironmentVars(env) {
        if (!env || Object.keys(env).length === 0) {
            envVars.innerHTML = '<p>No environment variables available.</p>';
            return;
        }
        
        let html = `
            <table class="admin-table">
                <thead>
                    <tr>
                        <th>Variable</th>
                        <th>Value</th>
                    </tr>
                </thead>
                <tbody>
        `;
        
        // Safe variables that can be shown without masking
        const safeVars = [
            'DEFAULT_VECTOR_STORE',
            'AWS_REGION',
            'AWS_S3_BUCKET_NAME',
            'AWS_S3_PDF_PREFIX',
            'LLM_PROVIDER',
            'LLM_MODEL_NAME',
            'OPENAI_EMBEDDING_MODEL',
            'HAYSTACK_STORE_TYPE',
            'FLASK_DEBUG',
            'FLASK_ENV'
        ];
        
        // Sort variables alphabetically
        const sortedKeys = Object.keys(env).sort();
        
        for (const key of sortedKeys) {
            const value = safeVars.includes(key) ? env[key] : '********';
            
            html += `
                <tr>
                    <td>${key}</td>
                    <td>${value}</td>
                </tr>
            `;
        }
        
        html += `
                </tbody>
            </table>
        `
    }
    
    // ============================
    // Helper Functions
    // ============================
    
    // Show status message with appropriate styling
    function showStatus(element, message, type) {
        element.textContent = message;
        element.className = 'admin-status'; // Reset class
        if (type) {
            element.classList.add(type);
            element.style.display = message ? 'block' : 'none'; // Show only if message exists
        } else {
            element.style.display = 'none'; // Hide if no type/message
        }
        
        // Ensure visibility by scrolling to the element only if there's a message
        if (message && element.style.display !== 'none') { // Check if it's actually visible
            element.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    }
    
});