"""The touch web UI served at ``/``.

Single self-contained HTML page: no build step, no external assets. Talks to the
daemon over a WebSocket using press/release pairs so buttons feel like a real
controller (hold to repeat-scroll, quick tap to select). The token is taken from
the ``?token=`` query the first time and cached in localStorage.
"""

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#0a0a0f">
<title>PS5 Remote</title>
<style>
  :root { --bg:#0a0a0f; --panel:#16161f; --btn:#23232f; --btn2:#2d2d3d; --accent:#2a6cf6; --txt:#e8e8f0; }
  * { box-sizing:border-box; -webkit-tap-highlight-color:transparent; -webkit-user-select:none; user-select:none; touch-action:manipulation; }
  html,body { margin:0; height:100%; background:var(--bg); color:var(--txt);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; overscroll-behavior:none; }
  body { display:flex; flex-direction:column; padding:env(safe-area-inset-top) 12px env(safe-area-inset-bottom); gap:10px; }
  header { display:flex; align-items:center; gap:10px; padding:10px 4px; }
  #dot { width:10px; height:10px; border-radius:50%; background:#888; flex:0 0 auto; }
  #dot.on { background:#33c264; } #dot.off { background:#e0556b; }
  #stat { font-size:13px; color:#aab; flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  button.sys { background:var(--panel); color:var(--txt); border:1px solid #2a2a38; border-radius:10px; padding:8px 12px; font-size:13px; }
  .pad { display:flex; flex-direction:column; gap:14px; flex:1; justify-content:center; }
  .row { display:flex; justify-content:space-between; align-items:center; gap:14px; }
  .shoulders { justify-content:space-between; }
  .shoulders .btn { flex:1; height:48px; border-radius:12px; font-size:15px; }
  .main { display:flex; justify-content:space-between; align-items:center; gap:10px; }
  .cluster { display:grid; grid-template-columns:repeat(3,64px); grid-template-rows:repeat(3,64px); gap:8px; }
  .btn { background:var(--btn); color:var(--txt); border:none; border-radius:16px; font-size:20px;
    display:flex; align-items:center; justify-content:center; font-weight:600; }
  .btn:active, .btn.active { background:var(--accent); transform:scale(0.94); }
  .btn.face { border-radius:50%; font-size:26px; }
  .dpad .u { grid-area:1/2; } .dpad .l { grid-area:2/1; } .dpad .r { grid-area:2/3; } .dpad .d { grid-area:3/2; }
  .dpad .c { grid-area:2/2; background:transparent; }
  .face-cluster .t { grid-area:1/2; } .face-cluster .s { grid-area:2/1; } .face-cluster .o { grid-area:2/3; } .face-cluster .x { grid-area:3/2; }
  .face-cluster .c { grid-area:2/2; background:transparent; }
  .syscol-tri { color:#43d39b; } .syscol-cir { color:#f0606e; } .syscol-sqr { color:#e573c7; } .syscol-cro { color:#7aa6ff; }
  .center { display:flex; justify-content:center; gap:12px; }
  .center .btn { width:auto; padding:0 18px; height:44px; border-radius:22px; font-size:14px; background:var(--btn2); }
  .ps { background:var(--accent)!important; }
</style>
</head>
<body>
<header>
  <span id="dot"></span>
  <span id="stat">connecting…</span>
  <button class="sys" id="link">Link</button>
  <button class="sys" id="wake">Wake</button>
</header>

<div class="pad">
  <div class="row shoulders">
    <button class="btn" data-btn="L1">L1</button>
    <button class="btn" data-btn="L2">L2</button>
    <button class="btn" data-btn="R2">R2</button>
    <button class="btn" data-btn="R1">R1</button>
  </div>

  <div class="main">
    <div class="cluster dpad">
      <button class="btn u" data-btn="UP">▲</button>
      <button class="btn l" data-btn="LEFT">◀</button>
      <span class="c"></span>
      <button class="btn r" data-btn="RIGHT">▶</button>
      <button class="btn d" data-btn="DOWN">▼</button>
    </div>
    <div class="cluster face-cluster">
      <button class="btn face t syscol-tri" data-btn="TRIANGLE">△</button>
      <button class="btn face s syscol-sqr" data-btn="SQUARE">□</button>
      <span class="c"></span>
      <button class="btn face o syscol-cir" data-btn="CIRCLE">○</button>
      <button class="btn face x syscol-cro" data-btn="CROSS">✕</button>
    </div>
  </div>

  <div class="center">
    <button class="btn" data-btn="SHARE">Create</button>
    <button class="btn ps" data-btn="PS">PS</button>
    <button class="btn" data-btn="TOUCHPAD">Pad</button>
    <button class="btn" data-btn="OPTIONS">Options</button>
  </div>
</div>

<script>
(function () {
  // --- token handling ---
  const params = new URLSearchParams(location.search);
  let token = params.get('token');
  if (token) { localStorage.setItem('ps5token', token); history.replaceState({}, '', location.pathname); }
  else { token = localStorage.getItem('ps5token') || ''; }

  const dot = document.getElementById('dot');
  const stat = document.getElementById('stat');
  const linkBtn = document.getElementById('link');
  let linked = false;

  // --- websocket with auto-reconnect ---
  let ws = null, reconnectTimer = null;
  function wsUrl() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    return `${proto}://${location.host}/ws?token=${encodeURIComponent(token)}`;
  }
  function connect() {
    ws = new WebSocket(wsUrl());
    ws.onopen = () => { stat.textContent = 'connected'; refreshStatus(); };
    ws.onclose = () => { stat.textContent = 'reconnecting…'; dot.className=''; scheduleReconnect(); };
    ws.onerror = () => { ws.close(); };
    ws.onmessage = (e) => { try { const m = JSON.parse(e.data); if (m.error) stat.textContent = '⚠ ' + m.error; } catch(_){} };
  }
  function scheduleReconnect() { clearTimeout(reconnectTimer); reconnectTimer = setTimeout(connect, 1200); }
  function send(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }

  // --- status polling ---
  async function refreshStatus() {
    try {
      const r = await fetch('/api/status', { headers: { 'Authorization': 'Bearer ' + token } });
      if (r.status === 401) { stat.textContent = '⚠ bad/no token'; return; }
      const s = await r.json();
      linked = !!s.session_ready;
      dot.className = s.on ? 'on' : 'off';
      linkBtn.textContent = linked ? 'Unlink' : 'Link';
      linkBtn.classList.toggle('ps', linked);
      const base = s.on ? (s.app ? s.app : (s.status || 'on')) : 'rest mode';
      stat.textContent = base + (s.on ? (linked ? ' · linked' : ' · idle') : '');
    } catch (_) {}
  }
  setInterval(refreshStatus, 5000);

  // --- button press/release wiring ---
  function bind(el) {
    const btn = el.dataset.btn;
    let down = false;
    const press = (ev) => { ev.preventDefault(); if (down) return; down = true; el.classList.add('active');
      if (navigator.vibrate) navigator.vibrate(8); send({ action: 'press', button: btn }); };
    const release = () => { if (!down) return; down = false; el.classList.remove('active'); send({ action: 'release', button: btn }); };
    el.addEventListener('pointerdown', press);
    el.addEventListener('pointerup', release);
    el.addEventListener('pointerleave', release);
    el.addEventListener('pointercancel', release);
  }
  document.querySelectorAll('.btn[data-btn]').forEach(bind);
  document.getElementById('wake').addEventListener('click', () => { send({ action: 'wake' }); stat.textContent = 'waking…'; setTimeout(refreshStatus, 3000); });
  linkBtn.addEventListener('click', () => {
    if (linked) { send({ action: 'disconnect' }); stat.textContent = 'unlinking…'; setTimeout(refreshStatus, 500); }
    else { send({ action: 'connect' }); stat.textContent = 'linking…'; setTimeout(refreshStatus, 3500); }
  });

  connect();
})();
</script>
</body>
</html>
"""
