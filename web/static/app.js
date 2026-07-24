// Network Recovery Tool - Web UI
// Version 2.0.0

// ============================================================
// Configuration
// ============================================================
const API_BASE = '/api';
const AUTO_REFRESH_INTERVAL = 10000; // 10 seconds

let currentAction = null;
let statusCheckInterval = null;

// ============================================================
// Core Actions
// ============================================================
async function runAction(action) {
    const output = document.getElementById('output');
    const progressContainer = document.getElementById('progressContainer');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');
    
    // Hide dashboard if visible
    document.getElementById('dashboard').style.display = 'none';
    document.getElementById('layers').style.display = 'flex';
    output.style.display = 'block';
    progressContainer.style.display = 'flex';
    
    output.innerHTML = `<div class="log-line info">⏳ Running ${action}...</div>`;
    progressFill.style.width = '0%';
    progressText.textContent = '0%';
    currentAction = action;
    
    try {
        const response = await fetch(`${API_BASE}/action`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: action })
        });
        
        const data = await response.json();
        
        if (data.output) {
            const lines = data.output.split('\n').filter(line => line.trim());
            let html = '';
            let progress = 0;
            
            lines.forEach(line => {
                if (line.includes('✅') || line.includes('PASS')) {
                    html += `<div class="log-line pass">${escapeHtml(line)}</div>`;
                    progress = Math.min(progress + 10, 100);
                } else if (line.includes('❌') || line.includes('FAIL')) {
                    html += `<div class="log-line fail">${escapeHtml(line)}</div>`;
                    progress = Math.min(progress + 5, 100);
                } else if (line.includes('⚠️') || line.includes('WARN')) {
                    html += `<div class="log-line warn">${escapeHtml(line)}</div>`;
                    progress = Math.min(progress + 5, 100);
                } else if (line.includes('LAYER')) {
                    html += `<div class="log-line info">${escapeHtml(line)}</div>`;
                    progress = Math.min(progress + 8, 100);
                } else if (line.includes('REPAIR') || line.includes('repair')) {
                    html += `<div class="log-line warn">${escapeHtml(line)}</div>`;
                    progress = Math.min(progress + 10, 100);
                } else if (line.includes('Complete') || line.includes('OK')) {
                    html += `<div class="log-line success">${escapeHtml(line)}</div>`;
                    progress = 100;
                } else if (line.trim()) {
                    html += `<div class="log-line">${escapeHtml(line)}</div>`;
                }
                
                // Update progress
                progressFill.style.width = progress + '%';
                progressText.textContent = progress + '%';
            });
            
            output.innerHTML = html;
            output.scrollTop = output.scrollHeight;
            
            // Update layer indicators
            updateLayers(lines);
        } else if (data.error) {
            output.innerHTML = `<div class="log-line fail">❌ Error: ${escapeHtml(data.error)}</div>`;
        } else {
            output.innerHTML = `<div class="log-line fail">❌ Command failed (exit code: ${data.exit_code || 'unknown'})</div>`;
        }
    } catch (e) {
        output.innerHTML = `<div class="log-line fail">❌ Request failed: ${escapeHtml(e.message)}</div>`;
    }
    
    progressFill.style.width = '100%';
    progressText.textContent = '100%';
    
    setTimeout(() => {
        progressContainer.style.display = 'none';
    }, 3000);
}

// ============================================================
// Layer Updates
// ============================================================
function updateLayers(lines) {
    const layers = document.querySelectorAll('.layer');
    const layerMap = {
        'LAYER 1': 0,
        'LAYER 2': 1,
        'LAYER 3': 2,
        'LAYER 4': 3,
        'LAYER 5': 4,
        'LAYER 6': 5,
        'LAYER 7': 6,
        'LAYER 8': 7,
        'LAYER 9': 8,
        'LAYER 10': 9,
        'LAYER 11': 10
    };
    
    // Reset all layers
    layers.forEach(l => {
        l.className = 'layer';
    });
    
    let currentLayer = -1;
    
    lines.forEach(line => {
        for (const [key, index] of Object.entries(layerMap)) {
            if (line.includes(key)) {
                currentLayer = index;
                layers[index].classList.add('active');
            }
        }
        
        if (currentLayer >= 0) {
            if (line.includes('✅') || line.includes('PASS')) {
                layers[currentLayer].classList.remove('active');
                layers[currentLayer].classList.add('pass');
            } else if (line.includes('❌') || line.includes('FAIL')) {
                layers[currentLayer].classList.remove('active');
                layers[currentLayer].classList.add('fail');
            } else if (line.includes('⚠️') || line.includes('WARN')) {
                layers[currentLayer].classList.remove('active');
                layers[currentLayer].classList.add('warn');
            }
        }
    });
}

// ============================================================
// Status / Health
// ============================================================
async function checkStatus() {
    try {
        const response = await fetch(`${API_BASE}/status`);
        const data = await response.json();
        
        const dot = document.getElementById('statusDot');
        const text = document.getElementById('statusText');
        
        if (data.ok) {
            dot.className = 'dot online';
            text.textContent = 'Connected';
        } else {
            dot.className = 'dot offline';
            text.textContent = 'Error';
        }
    } catch (e) {
        const dot = document.getElementById('statusDot');
        dot.className = 'dot offline';
        document.getElementById('statusText').textContent = 'Offline';
    }
}

// ============================================================
// Utils
// ============================================================
function clearOutput() {
    document.getElementById('output').innerHTML = '<div class="placeholder">Click an action to begin</div>';
    document.querySelectorAll('.layer').forEach(l => {
        l.className = 'layer';
    });
    document.getElementById('progressContainer').style.display = 'none';
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ============================================================
// Init
// ============================================================
document.addEventListener('DOMContentLoaded', function() {
    checkStatus();
    
    // Auto-refresh status
    if (statusCheckInterval) {
        clearInterval(statusCheckInterval);
    }
    statusCheckInterval = setInterval(checkStatus, AUTO_REFRESH_INTERVAL);
});

// Handle window close
window.addEventListener('beforeunload', function() {
    if (statusCheckInterval) {
        clearInterval(statusCheckInterval);
    }
});