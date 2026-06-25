const API = window.location.origin;

async function runAction(action) {
    const output = document.getElementById('output');
    const progressContainer = document.getElementById('progressContainer');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');
    
    // Clear previous output
    output.innerHTML = '';
    
    // Show progress
    progressContainer.style.display = 'flex';
    progressFill.style.width = '0%';
    progressText.textContent = '0%';
    
    // Reset layers
    document.querySelectorAll('.layer').forEach(el => {
        el.className = 'layer';
    });
    
    // Add status message
    addLog(`🚀 Running ${action}...`, 'info');
    
    try {
        const response = await fetch(`${API}/api/${action}`);
        const data = await response.json();
        
        if (data.ok) {
            // Parse the output line by line
            const lines = data.output.split('\n');
            let layerCount = 0;
            
            lines.forEach((line, index) => {
                if (line.trim() === '') return;
                
                // Determine status
                let status = 'info';
                if (line.includes('✅')) status = 'pass';
                else if (line.includes('❌')) status = 'fail';
                else if (line.includes('⚠️')) status = 'warn';
                else if (line.includes('Connected')) status = 'pass';
                else if (line.includes('Internet')) status = 'pass';
                
                addLog(line.trim(), status);
                
                // Update progress
                const progress = Math.min(((index + 1) / lines.length) * 100, 100);
                progressFill.style.width = progress + '%';
                progressText.textContent = Math.round(progress) + '%';
                
                // Update layer status
                if (line.includes('LAYER') || line.includes('=== LAYER')) {
                    const layerMatch = line.match(/LAYER\s+(\d+)/);
                    if (layerMatch) {
                        const layerNum = parseInt(layerMatch[1]);
                        const layerEl = document.querySelector(`.layer[data-layer="${layerNum}"]`);
                        if (layerEl) {
                            layerEl.className = 'layer active';
                        }
                    }
                }
            });
            
            // Final progress
            progressFill.style.width = '100%';
            progressText.textContent = '100%';
            
            if (data.exit_code === 0) {
                addLog('✅ Action completed successfully!', 'success');
            } else {
                addLog(`⚠️ Action completed with exit code: ${data.exit_code}`, 'warn');
            }
        } else {
            addLog(`❌ Error: ${data.error || 'Unknown error'}`, 'fail');
        }
    } catch (error) {
        addLog(`❌ Connection error: ${error.message}`, 'fail');
    }
    
    // Hide progress after delay
    setTimeout(() => {
        progressContainer.style.display = 'none';
    }, 3000);
}

function addLog(message, type = 'info') {
    const output = document.getElementById('output');
    const div = document.createElement('div');
    div.className = `log-line ${type}`;
    div.textContent = message;
    output.appendChild(div);
    output.scrollTop = output.scrollHeight;
}

function clearOutput() {
    const output = document.getElementById('output');
    output.innerHTML = '<div class="placeholder">Click an action to begin</div>';
    document.querySelectorAll('.layer').forEach(el => {
        el.className = 'layer';
    });
}

async function checkStatus() {
    try {
        const response = await fetch(`${API}/api/status`);
        const data = await response.json();
        const dot = document.getElementById('statusDot');
        const text = document.getElementById('statusText');
        
        if (data.ok && data.output.includes('Connected')) {
            dot.className = 'dot online';
            text.textContent = 'Online';
        } else {
            dot.className = 'dot offline';
            text.textContent = 'Offline';
        }
    } catch (error) {
        const dot = document.getElementById('statusDot');
        const text = document.getElementById('statusText');
        dot.className = 'dot offline';
        text.textContent = 'Connection Error';
    }
}

// Check status every 30 seconds
checkStatus();
setInterval(checkStatus, 30000);