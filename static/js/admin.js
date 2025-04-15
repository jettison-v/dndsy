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
        // Reset login form
        adminPassword.value = '';
        adminLoginError.textContent = '';
    });
    
    // Close admin modal
    adminCloseButton.addEventListener('click', function() {
        adminModal.style.display = 'none';
    });
    
    // Close modal when clicking outside
    adminModal.addEventListener('click', function(event) {
        if (event.target === adminModal) {
            adminModal.style.display = 'none';
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
            
            // Load initial data for active tab
            loadTabData(document.querySelector('.admin-tab-button.active').dataset.tab);
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
            document.getElementById(`${tabName}-tab`).classList.add('active');
            
            // Load tab-specific data
            loadTabData(tabName);
        });
    });
    
    // Load data based on active tab
    function loadTabData(tabName) {
        switch(tabName) {
            case 'data-processing':
                // Nothing to load initially
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
    
    // ============================
    // Data Processing Tab
    // ============================
    
    const processButton = document.getElementById('process-button');
    const processStatus = document.getElementById('process-status');
    const loadHistoryButton = document.getElementById('load-history-button');
    const processingHistory = document.getElementById('processing-history');
    
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
        const cacheBehavior = document.querySelector('input[name="cache-behavior"]:checked').value;
        
        // Get S3 prefix (optional)
        const s3Prefix = document.getElementById('s3-prefix').value.trim();
        
        // Prepare request data
        const requestData = {
            store_types: storeTypes,
            cache_behavior: cacheBehavior
        };
        
        if (s3Prefix) {
            requestData.s3_prefix = s3Prefix;
        }
        
        // Confirm with user
        const confirmMessage = `Process documents with the following settings?\n\n` +
            `Vector Stores: ${storeTypes.join(', ')}\n` +
            `Cache Behavior: ${cacheBehavior}\n` +
            (s3Prefix ? `S3 Prefix: ${s3Prefix}\n` : '') +
            `\nThis operation may take several minutes.`;
        
        if (!confirm(confirmMessage)) {
            return;
        }
        
        // Update UI
        processButton.disabled = true;
        showStatus(processStatus, 'Processing started. This may take several minutes...', 'info');
        
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
            showStatus(processStatus, `Processing complete. ${data.message}`, 'success');
        })
        .catch(error => {
            showStatus(processStatus, `Error: ${error.message}`, 'error');
        })
        .finally(() => {
            processButton.disabled = false;
        });
    });
    
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
        if (!data || Object.keys(data).length === 0) {
            processingHistory.innerHTML = '<p>No processing history available.</p>';
            return;
        }
        
        let html = `
            <table class="admin-table">
                <thead>
                    <tr>
                        <th>PDF</th>
                        <th>Last Modified</th>
                        <th>Last Processed</th>
                        <th>Stores Processed</th>
                    </tr>
                </thead>
                <tbody>
        `;
        
        for (const [pdfKey, pdfInfo] of Object.entries(data)) {
            const filename = pdfKey.split('/').pop();
            const lastModified = new Date(pdfInfo.last_modified).toLocaleString();
            const lastProcessed = new Date(pdfInfo.processed).toLocaleString();
            const storesProcessed = pdfInfo.processed_stores.join(', ') || 'None';
            
            html += `
                <tr>
                    <td title="${pdfKey}">${filename}</td>
                    <td>${lastModified}</td>
                    <td>${lastProcessed}</td>
                    <td>${storesProcessed}</td>
                </tr>
            `;
        }
        
        html += `
                </tbody>
            </table>
        `;
        
        processingHistory.innerHTML = html;
    }
    
    // ============================
    // File Management Tab
    // ============================
    
    const uploadButton = document.getElementById('upload-button');
    const uploadStatus = document.getElementById('upload-status');
    const loadPdfsButton = document.getElementById('load-pdfs-button');
    const pdfList = document.getElementById('pdf-list');
    
    // Upload PDF to S3
    uploadButton.addEventListener('click', function() {
        const fileInput = document.getElementById('pdf-upload');
        const prefix = document.getElementById('upload-prefix').value.trim();
        
        if (!fileInput.files || fileInput.files.length === 0) {
            showStatus(uploadStatus, 'Please select a PDF file to upload', 'error');
            return;
        }
        
        const file = fileInput.files[0];
        if (!file.name.toLowerCase().endsWith('.pdf')) {
            showStatus(uploadStatus, 'Only PDF files are supported', 'error');
            return;
        }
        
        const formData = new FormData();
        formData.append('file', file);
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
            fileInput.value = ''; // Clear the file input
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
        
        let html = `
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
        `;
        
        envVars.innerHTML = html;
    }
    
    // ============================
    // Helper Functions
    // ============================
    
    // Show status message with appropriate styling
    function showStatus(element, message, type) {
        element.textContent = message;
        element.className = 'admin-status';
        if (type) {
            element.classList.add(type);
        }
    }
}); 