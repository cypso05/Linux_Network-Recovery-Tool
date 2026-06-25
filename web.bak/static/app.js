const API = window.location.origin;
let es = null;

async function checkStatus() {
    try {
        const r = await fetch(`${API}/api/status`);
        const d = await r.json();
        const dot = document.getElementById('statusDot');
        const txt = document.getElementById('statusText');
        if (d.ok && d.out.includes('Connected')) {
            dot.className = 'status-dot on'; txt.textContent = 'Connected';
        } else {
            dot.className = 'status-dot off'; txt.textContent = 'Disconnected';
        }
    } catch(e) {}
}

function resetUI() {
    document.getElementById('log').innerHTML = '';
    document.querySelectorAll('.layer').forEach(l => l.className = 'layer');
    document.getElementById('progressWrap').style.display = 'flex';
    document.getElementById('progressFill').style.width = '0%';
    document.getElementById('progressPct').textContent = '0%';
}

function addLog(msg, status) {
    const log = document.getElementById('log');
    const div = document.createElement('div');
    div.className = `log-line ${status || ''}`;
    div.textContent = msg;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
}

function setProgress(pct) {
    document.getElementById('progressFill').style.width = pct + '%';
    document.getElementById('progressPct').textContent = Math.round(pct) + '%';
    if (pct >= 100) setTimeout(() => {
        document.getElementById('progressWrap').style.display = 'none';
    }, 1500);
}

function setLayer(layer, status) {
    const el = document.querySelector(`.layer[data-l="${layer}"]`);
    if (el) { el.classList.add('active', status || ''); }
}

async function doAction(action) {
    if (action === 'repair' && !confirm('⚠️ Repair may disrupt connections. Continue?')) return;
    resetUI();
    
    if (action === 'status' || action === 'snapshot') {
        addLog(`Running ${action}...`, 'info');
        const r = await fetch(`${API}/api/${action}`);
        const d = await r.json();
        if (d.ok) {
            d.out.split('\n').forEach(line => {
                if (!line.trim()) return;
                let s = 'info';
                if (line.includes('✅')) s = 'pass';
                if (line.includes('❌')) s = 'fail';
                if (line.includes('⚠️')) s = 'warn';
                addLog(line.trim(), s);
            });
        } else {
            addLog(d.err || 'Error', 'fail');
        }
        setProgress(100);
        return;
    }
    
    // Stream actions
    if (es) es.close();
    es = new EventSource(`${API}/api/stream/${action}`);
    let progress = 0;
    
    es.onmessage = (e) => {
        const d = JSON.parse(e.data);
        if (d.type === 'log') {
            addLog(d.msg, d.status || 'info');
            progress = Math.min(progress + 1, 90);
            setProgress(progress);
        }
        if (d.type === 'layer') {
            setLayer(d.layer, d.status || 'active');
            progress = Math.floor((d.layer / 11) * 95);
            setProgress(progress);
        }
        if (d.type === 'done') {
            setProgress(100);
            es.close(); es = null;
            addLog(d.code === 0 ? '✅ Complete!' : `⚠️ Exit code: ${d.code}`, d.code === 0 ? 'pass' : 'fail');
        }
    };
    es.onerror = () => { if (es) { addLog('Connection lost', 'fail'); es.close(); es = null; } };
}

document.addEventListener('DOMContentLoaded', () => {
    checkStatus();
    setInterval(checkStatus, 30000);
});