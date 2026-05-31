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
<meta name="theme-color" content="#07070c">
<title>PS5 Remote</title>
<style>
  :root {
    --bg0:#07070c; --bg1:#0d0d16;
    --glass:rgba(255,255,255,0.045); --glass-brd:rgba(255,255,255,0.09);
    --txt:#eef0f7; --muted:#8d92a8;
    --accent:#3b82f6; --accent2:#7c5cff;
    --ok:#34d399; --bad:#fb7185;
    --tri:#46e0a8; --cir:#ff6b7d; --sqr:#ef72d2; --cro:#7aa6ff;
    --r:18px;
  }
  * { box-sizing:border-box; -webkit-tap-highlight-color:transparent;
      -webkit-user-select:none; user-select:none; -webkit-touch-callout:none; }
  html,body { margin:0; min-height:100%; }
  body {
    min-height:100dvh; color:var(--txt); overscroll-behavior:none;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Inter,sans-serif;
    background:
      radial-gradient(70% 55% at 18% 0%, rgba(124,92,255,0.16), transparent 60%),
      radial-gradient(65% 50% at 100% 8%, rgba(59,130,246,0.18), transparent 55%),
      radial-gradient(90% 60% at 50% 100%, rgba(59,130,246,0.07), transparent 60%),
      linear-gradient(180deg, var(--bg1), var(--bg0));
    background-attachment:fixed;
    display:flex; flex-direction:column; align-items:center;
    padding:calc(env(safe-area-inset-top) + 10px) 14px calc(env(safe-area-inset-bottom) + 14px);
  }
  .wrap { width:100%; max-width:470px; flex:1; display:flex; flex-direction:column; gap:14px;
    animation:rise .5s cubic-bezier(.2,.8,.2,1) both; }
  @keyframes rise { from { opacity:0; transform:translateY(14px) scale(.98); } }

  header { display:flex; align-items:center; gap:10px; }
  .brand { font-weight:800; letter-spacing:.04em; font-size:15px; white-space:nowrap;
    background:linear-gradient(90deg,#fff,#c7d2fe); -webkit-background-clip:text;
    background-clip:text; color:transparent; }
  .brand b { font-weight:800; }
  .pill { margin-left:auto; display:flex; align-items:center; gap:8px; min-width:0;
    padding:7px 12px; border-radius:999px; background:var(--glass);
    border:1px solid var(--glass-brd); backdrop-filter:blur(10px); -webkit-backdrop-filter:blur(10px); }
  #dot { width:9px; height:9px; border-radius:50%; background:#6b7080; flex:0 0 auto;
    box-shadow:0 0 0 0 rgba(0,0,0,0); transition:background .25s, box-shadow .25s; }
  #dot.on  { background:var(--ok);  box-shadow:0 0 10px 1px rgba(52,211,153,.7); }
  #dot.off { background:var(--bad); box-shadow:0 0 10px 1px rgba(251,113,133,.6); }
  #stat { font-size:12.5px; color:var(--muted); overflow:hidden; text-overflow:ellipsis;
    white-space:nowrap; max-width:46vw; }

  .actions { display:flex; gap:10px; }
  .sys { flex:1; appearance:none; cursor:pointer; color:var(--txt);
    background:var(--glass); border:1px solid var(--glass-brd); border-radius:14px;
    padding:11px 12px; font-size:13.5px; font-weight:600; letter-spacing:.02em;
    backdrop-filter:blur(10px); -webkit-backdrop-filter:blur(10px);
    transition:transform .12s, background .18s, border-color .18s, box-shadow .18s; }
  .sys:hover { border-color:rgba(255,255,255,0.18); }
  .sys:active { transform:scale(.97); }
  .sys:disabled { opacity:.5; cursor:default; }
  .sys.busy { background:linear-gradient(165deg,var(--accent),var(--accent2)); border-color:transparent; }
  #link.linked { background:linear-gradient(165deg,var(--accent),var(--accent2)); border-color:transparent;
    box-shadow:0 6px 22px rgba(59,130,246,.35); }

  .controls { flex:1; display:flex; flex-direction:column; justify-content:center; gap:16px; }

  .btn { appearance:none; cursor:pointer; color:var(--txt); border:1px solid rgba(255,255,255,0.2);
    background:linear-gradient(165deg, rgba(255,255,255,0.17), rgba(255,255,255,0.06));
    box-shadow:inset 0 1px 0 rgba(255,255,255,0.16), 0 6px 16px rgba(0,0,0,0.45);
    display:flex; align-items:center; justify-content:center; font-weight:700;
    touch-action:none; -webkit-backdrop-filter:blur(4px); backdrop-filter:blur(4px);
    transition:transform .11s cubic-bezier(.2,.8,.2,1), box-shadow .16s, background .16s, color .16s; }
  .btn:active, .btn.active {
    transform:scale(.9);
    background:linear-gradient(165deg, var(--accent), var(--accent2));
    box-shadow:inset 0 0 0 1px rgba(255,255,255,.25), 0 0 26px rgba(59,130,246,.6);
    color:#fff; }

  /* shoulders */
  .shoulders { display:flex; gap:10px; }
  .shoulders .btn { flex:1; height:clamp(42px,11vw,54px); border-radius:14px;
    font-size:clamp(13px,3.6vw,15px); letter-spacing:.03em; }

  /* clusters */
  .main { display:flex; justify-content:space-between; align-items:center; gap:12px; }
  .well { padding:clamp(7px,2vw,11px); border-radius:28px; border:1px solid var(--glass-brd);
    background:radial-gradient(120% 120% at 50% 30%, rgba(255,255,255,0.06), rgba(255,255,255,0.012));
    box-shadow:inset 0 2px 14px rgba(0,0,0,0.55), 0 8px 24px rgba(0,0,0,0.35); }
  .cluster { display:grid; gap:clamp(6px,1.8vw,9px);
    grid-template-columns:repeat(3, clamp(40px,11.5vw,62px));
    grid-template-rows:repeat(3, clamp(40px,11.5vw,62px)); }
  .cluster .c { display:flex; align-items:center; justify-content:center; }
  .cluster .c::after { content:""; width:8px; height:8px; border-radius:50%;
    background:rgba(255,255,255,0.10); }

  .dpad .btn { border-radius:14px; font-size:clamp(14px,4.2vw,20px); color:#e7eaf6; }
  .dpad .u { grid-area:1/2; } .dpad .l { grid-area:2/1; }
  .dpad .r { grid-area:2/3; } .dpad .d { grid-area:3/2; }
  .dpad .c { grid-area:2/2; }

  .faces .btn { border-radius:50%; font-size:clamp(22px,6.2vw,30px); }
  .faces .t { grid-area:1/2; color:var(--tri); }
  .faces .s { grid-area:2/1; color:var(--sqr); }
  .faces .o { grid-area:2/3; color:var(--cir); }
  .faces .x { grid-area:3/2; color:var(--cro); }
  .faces .c { grid-area:2/2; }
  .faces .btn:active, .faces .btn.active { color:#fff; }

  /* system row */
  .system { display:flex; gap:9px; }
  .system .btn { flex:1; height:clamp(40px,10.5vw,48px); border-radius:14px;
    font-size:clamp(11.5px,3.1vw,13.5px); letter-spacing:.02em; padding:0 6px; }
  .system .ps { font-weight:800; letter-spacing:.06em;
    background:linear-gradient(165deg, var(--accent), var(--accent2)); border-color:transparent;
    box-shadow:0 8px 24px rgba(59,130,246,.4), inset 0 1px 0 rgba(255,255,255,.25);
    color:#fff; }

  .hint { display:none; text-align:center; color:var(--muted); font-size:11.5px; letter-spacing:.02em; }
  .hint kbd { font:inherit; padding:1px 6px; border-radius:6px; background:var(--glass);
    border:1px solid var(--glass-brd); }
  @media (hover:hover) and (pointer:fine) { .hint { display:block; } }

  #feedback { position:fixed; top:50%; left:50%; z-index:99; pointer-events:none;
    transform:translate(-50%,-50%) scale(.7); opacity:0;
    font-size:clamp(48px,16vw,84px); font-weight:800; color:#fff;
    text-shadow:0 6px 40px rgba(59,130,246,.65), 0 2px 10px rgba(0,0,0,.6);
    transition:opacity .12s, transform .12s; }
  #feedback.show { opacity:.95; transform:translate(-50%,-50%) scale(1); }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">PS5&nbsp;<b>Remote</b></div>
    <div class="pill"><span id="dot"></span><span id="stat">connecting…</span></div>
  </header>

  <div class="actions">
    <button class="sys" id="link">Link</button>
    <button class="sys" id="wake">Wake</button>
  </div>

  <div class="controls">
    <div class="shoulders">
      <button class="btn" data-btn="L1">L1</button>
      <button class="btn" data-btn="L2">L2</button>
      <button class="btn" data-btn="R2">R2</button>
      <button class="btn" data-btn="R1">R1</button>
    </div>

    <div class="main">
      <div class="well">
        <div class="cluster dpad">
          <button class="btn u" data-btn="UP">▲</button>
          <button class="btn l" data-btn="LEFT">◀</button>
          <span class="c"></span>
          <button class="btn r" data-btn="RIGHT">▶</button>
          <button class="btn d" data-btn="DOWN">▼</button>
        </div>
      </div>
      <div class="well">
        <div class="cluster faces">
          <button class="btn t" data-btn="TRIANGLE">△</button>
          <button class="btn s" data-btn="SQUARE">□</button>
          <span class="c"></span>
          <button class="btn o" data-btn="CIRCLE">○</button>
          <button class="btn x" data-btn="CROSS">✕</button>
        </div>
      </div>
    </div>

    <div class="system">
      <button class="btn" data-btn="SHARE">Create</button>
      <button class="btn ps" data-btn="PS">PS</button>
      <button class="btn" data-btn="TOUCHPAD">Pad</button>
      <button class="btn" data-btn="OPTIONS">Options</button>
    </div>

    <div class="hint">
      <kbd>↑↓←→</kbd> d-pad · <kbd>↵</kbd> ✕ · <kbd>⌫</kbd> ○ · <kbd>`</kbd> PS
    </div>
  </div>
</div>

<div id="feedback"></div>

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
  const fb = document.getElementById('feedback');
  let linked = false, busy = false, fbTimer;

  // Prettier glyphs for the center flash.
  const GLYPH = { CROSS:'✕', CIRCLE:'○', SQUARE:'□', TRIANGLE:'△',
                  UP:'▲', DOWN:'▼', LEFT:'◀', RIGHT:'▶', PS:'PS' };
  function flash(name) {
    fb.textContent = GLYPH[name] || name;
    fb.classList.add('show');
    clearTimeout(fbTimer);
    fbTimer = setTimeout(() => fb.classList.remove('show'), 220);
  }

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
      if (!busy) {                          // don't clobber the in-flight state
        linkBtn.textContent = linked ? 'Unlink' : 'Link';
        linkBtn.classList.toggle('linked', linked);
        const base = s.on ? (s.app ? s.app : (s.status || 'on')) : 'rest mode';
        stat.textContent = base + (s.on ? (linked ? ' · linked' : ' · idle') : '');
      }
    } catch (_) {}
  }
  setInterval(refreshStatus, 5000);

  // --- button press/release wiring ---
  function bind(el) {
    const btn = el.dataset.btn;
    let down = false;
    const press = (ev) => { ev.preventDefault(); if (down) return; down = true; el.classList.add('active');
      if (navigator.vibrate) navigator.vibrate(8); flash(btn); send({ action: 'press', button: btn }); };
    const release = () => { if (!down) return; down = false; el.classList.remove('active'); send({ action: 'release', button: btn }); };
    el.addEventListener('pointerdown', press);
    el.addEventListener('pointerup', release);
    el.addEventListener('pointerleave', release);
    el.addEventListener('pointercancel', release);
    el.addEventListener('contextmenu', (e) => e.preventDefault());
  }
  document.querySelectorAll('.btn[data-btn]').forEach(bind);

  // --- physical keyboard control (press/release, so holds repeat) ---
  const KEYMAP = {
    ArrowUp: 'UP', ArrowDown: 'DOWN', ArrowLeft: 'LEFT', ArrowRight: 'RIGHT',
    Enter: 'CROSS', Backspace: 'CIRCLE', '`': 'PS', '~': 'PS',
  };
  const held = new Set();
  const btnEl = (name) => document.querySelector('.btn[data-btn="' + name + '"]');
  window.addEventListener('keydown', (e) => {
    const b = KEYMAP[e.key];
    if (!b) return;
    e.preventDefault();                 // stop Backspace=back, arrows=scroll
    if (e.repeat || held.has(e.key)) return;
    held.add(e.key);
    const el = btnEl(b); if (el) el.classList.add('active');
    flash(b);
    send({ action: 'press', button: b });
  });
  window.addEventListener('keyup', (e) => {
    const b = KEYMAP[e.key];
    if (!b) return;
    e.preventDefault();
    held.delete(e.key);
    const el = btnEl(b); if (el) el.classList.remove('active');
    send({ action: 'release', button: b });
  });

  // POST a control endpoint and return the parsed JSON (throws on HTTP/app error).
  async function api(path) {
    const r = await fetch(path, { method: 'POST', headers: { 'Authorization': 'Bearer ' + token } });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.error) throw new Error(j.error || ('HTTP ' + r.status));
    return j;
  }

  const wakeBtn = document.getElementById('wake');
  let wakeBusy = false;
  wakeBtn.addEventListener('click', async () => {
    if (wakeBusy) return;
    wakeBusy = true; wakeBtn.disabled = true; stat.textContent = 'waking…';
    try { await api('/api/wake'); }
    catch (e) { stat.textContent = '⚠ ' + e.message; }
    finally { wakeBusy = false; wakeBtn.disabled = false; refreshStatus(); }
  });

  // Link/Unlink: awaits the real result, shows progress, can't be spam-clicked.
  async function setLink(doConnect) {
    if (busy) return;
    busy = true;
    linkBtn.disabled = true;
    linkBtn.classList.add('busy');
    linkBtn.textContent = doConnect ? 'Linking…' : 'Unlinking…';
    stat.textContent = doConnect ? 'linking…' : 'unlinking…';
    try {
      await api(doConnect ? '/api/connect' : '/api/disconnect');
    } catch (e) {
      stat.textContent = '⚠ ' + e.message;
    } finally {
      busy = false;
      linkBtn.disabled = false;
      linkBtn.classList.remove('busy');
      refreshStatus();
    }
  }
  linkBtn.addEventListener('click', () => setLink(!linked));

  connect();
})();
</script>
</body>
</html>
"""
