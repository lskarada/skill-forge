// Skill-Forge dashboard — SSE consumer + slide-over wiring.
// Keep this small. Phase-2/3 OOB swaps are handled by htmx; we only
// glue the SSE endpoint to htmx and wire the slide-over click handler.

(function () {
  // ---- SSE → htmx OOB swap ----------------------------------------
  // Each event arrives as data:{json}\n\n. The server emits HTML
  // fragments tagged with hx-swap-oob; we feed them straight to htmx
  // by inserting the HTML into a hidden sink and calling process.
  function attachSSE() {
    const sink = document.getElementById('sse-sink') || (function () {
      const d = document.createElement('div');
      d.id = 'sse-sink';
      d.hidden = true;
      document.body.appendChild(d);
      return d;
    })();

    let es = null;
    let reconnectTimer = null;

    function connect() {
      es = new EventSource('/events');
      es.addEventListener('html', (e) => {
        sink.innerHTML = e.data;
        if (window.htmx) {
          window.htmx.process(sink);
        }
      });
      es.onerror = () => {
        // Native EventSource auto-reconnects, but if the browser tab
        // was throttled or the server restarted, we want a deterministic
        // re-open. Force-close and re-create after 1s.
        if (es && es.readyState === 2 /* CLOSED */ && !reconnectTimer) {
          reconnectTimer = setTimeout(() => {
            reconnectTimer = null;
            connect();
          }, 1000);
        }
      };
    }

    connect();
    // Also poll visibility — when the tab is foregrounded after being
    // backgrounded for a while, browsers sometimes keep the EventSource
    // suspended. Force a reconnect so the snapshot heartbeat re-runs.
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && es && es.readyState !== 1) {
        try { es.close(); } catch (_) {}
        connect();
      }
    });
  }

  // ---- Slide-over (Phase 4) ---------------------------------------
  function attachSlide() {
    const dlg = document.getElementById('slide');
    if (!dlg) return;
    const close = document.getElementById('slide-close');
    if (close) {
      close.addEventListener('click', () => dlg.close());
    }
    document.addEventListener('click', (e) => {
      const tr = e.target.closest && e.target.closest('tr.worker-row');
      if (!tr || !tr.dataset.workerId) return;
      const wid = tr.dataset.workerId;
      const title = document.getElementById('slide-title');
      if (title) title.textContent = wid;
      const tabs = document.getElementById('slide-tabs');
      tabs.innerHTML = '';
      ['diff', 'transcript', 'tests'].forEach((kind, i) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'tab' + (i === 0 ? ' active' : '');
        b.textContent = kind;
        b.addEventListener('click', () => loadTab(wid, kind, b));
        tabs.appendChild(b);
      });
      loadTab(wid, 'diff', tabs.querySelector('.tab'));
      if (typeof dlg.showModal === 'function') {
        dlg.showModal();
      } else {
        dlg.setAttribute('open', '');
      }
    });

    function loadTab(wid, kind, btn) {
      tabs.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
      if (btn) btn.classList.add('active');
      const body = document.getElementById('slide-body');
      body.innerHTML = '<div class="empty">loading…</div>';
      fetch(`/workers/${encodeURIComponent(wid)}/${kind}`)
        .then((r) => r.text())
        .then((html) => { body.innerHTML = html; })
        .catch(() => { body.innerHTML = '<div class="empty">failed to load</div>'; });
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    attachSlide();
    attachSSE();
  });
})();
