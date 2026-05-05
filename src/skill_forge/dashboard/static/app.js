// Skill-Forge dashboard — SSE consumer + slide-over wiring.
//
// The server emits HTML fragments tagged `hx-swap-oob="true"` via SSE.
// htmx's OOB pipeline only fires for fragments delivered via its own
// AJAX response handling — `htmx.process()` does NOT execute OOB swaps
// on innerHTML insertions. So we apply OOB swaps manually: parse the
// fragment, find `[hx-swap-oob][id]` elements, replace document
// elements with matching `id`s.

(function () {
  // ---- Elapsed clock — 1s client tick, server-authoritative -------
  // The server emits `data-elapsed-secs` + `data-running` on the
  // #stat-elapsed tile every SSE event (≈5s). We tick every 1s on the
  // client by extrapolating from a local epoch base, and re-sync the
  // base whenever a fresh server value arrives. The displayed value is
  // never ahead of reality by more than 1s and snaps back on each
  // server update — so no drift even if the tab sleeps.

  const elapsedTicker = {
    baseEpochMs: null,  // Date.now() - serverSecs*1000
    running: false,
    interval: null,
    format(secs) {
      if (secs < 60) return `${secs}s`;
      const m = Math.floor(secs / 60);
      const s = secs % 60;
      return `${m}m${s.toString().padStart(2, '0')}s`;
    },
    sync() {
      const tile = document.getElementById('stat-elapsed');
      if (!tile) return;
      const secs = parseInt(tile.getAttribute('data-elapsed-secs') || '0', 10);
      const running = tile.getAttribute('data-running') === '1';
      this.baseEpochMs = Date.now() - secs * 1000;
      this.running = running;
      this.render();
    },
    render() {
      if (this.baseEpochMs == null) return;
      const secs = Math.max(0, Math.floor((Date.now() - this.baseEpochMs) / 1000));
      const valEl = document.getElementById('elapsed-value');
      if (valEl) valEl.textContent = this.format(secs);
    },
    start() {
      if (this.interval) return;
      this.interval = setInterval(() => {
        if (this.running) this.render();
      }, 1000);
    },
  };

  // ---- Bracket pan/zoom with transform persistence ---------------
  // The bracket SVG is replaced wholesale on every SSE update. To keep
  // the user's pan/zoom across re-renders we own the transform in JS
  // state and re-apply it to whichever <g id="bracket-viewport"> is
  // currently in the DOM after each OOB swap.

  const bracket = {
    state: { x: 0, y: 0, scale: 1 },
    drag: { active: false, lastX: 0, lastY: 0 },
    initOnce() {
      window.addEventListener('mousemove', (e) => {
        if (!this.drag.active) return;
        this.state.x += e.clientX - this.drag.lastX;
        this.state.y += e.clientY - this.drag.lastY;
        this.drag.lastX = e.clientX;
        this.drag.lastY = e.clientY;
        this.applyToCurrent();
      });
      window.addEventListener('mouseup', () => {
        if (this.drag.active) {
          this.drag.active = false;
          document.body.classList.remove('bracket-panning');
        }
      });
    },
    attach(root) {
      // root is the live #bracket element (initial render or post-swap).
      const svg = root.querySelector('svg.bracket-svg');
      if (!svg) return;
      this.applyToCurrent();
      svg.addEventListener('mousedown', (e) => {
        // Don't hijack clicks on a node — those open the drawer.
        if (e.target.closest('[data-worker-id]')) return;
        this.drag.active = true;
        this.drag.lastX = e.clientX;
        this.drag.lastY = e.clientY;
        document.body.classList.add('bracket-panning');
        e.preventDefault();
      });
      svg.addEventListener('wheel', (e) => {
        e.preventDefault();
        const delta = e.deltaY > 0 ? 0.92 : 1.08;
        this.state.scale = Math.max(0.4, Math.min(3, this.state.scale * delta));
        this.applyToCurrent();
      }, { passive: false });
    },
    applyToCurrent() {
      const vp = document.getElementById('bracket-viewport');
      if (!vp) return;
      vp.setAttribute(
        'transform',
        `translate(${this.state.x}, ${this.state.y}) scale(${this.state.scale})`,
      );
    },
  };

  // ---- Manual OOB-swap applier ------------------------------------

  function applyOobFragment(html) {
    if (!html) return;
    const tpl = document.createElement('template');
    tpl.innerHTML = html;
    const oobs = tpl.content.querySelectorAll('[hx-swap-oob]');
    oobs.forEach((node) => {
      const id = node.id;
      if (!id) return;
      const target = document.getElementById(id);
      if (!target) return;
      // Strip the marker so re-applying snapshots is idempotent.
      node.removeAttribute('hx-swap-oob');
      target.replaceWith(node);
      if (id === 'bracket') {
        // Re-bind pan/zoom and re-apply persisted transform to the fresh SVG.
        bracket.attach(node);
      }
      if (id === 'stat-elapsed') {
        // Re-sync the local ticker base from the new authoritative value.
        elapsedTicker.sync();
      }
    });
  }

  // ---- SSE wiring -------------------------------------------------

  function attachSSE() {
    let es = null;
    let reconnectTimer = null;

    function connect() {
      es = new EventSource('/events');
      es.addEventListener('html', (e) => {
        applyOobFragment(e.data);
      });
      es.onerror = () => {
        if (es && es.readyState === 2 /* CLOSED */ && !reconnectTimer) {
          reconnectTimer = setTimeout(() => {
            reconnectTimer = null;
            connect();
          }, 1000);
        }
      };
    }

    connect();
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && es && es.readyState !== 1) {
        try { es.close(); } catch (_) {}
        connect();
      }
    });
  }

  // ---- Slide-over (Phase 4) ---------------------------------------
  // Click any element with `data-worker-id` (table row OR SVG bracket
  // node) → open the dialog with the four-tab drilldown.

  function attachSlide() {
    const dlg = document.getElementById('slide');
    if (!dlg) return;
    const close = document.getElementById('slide-close');
    if (close) {
      close.addEventListener('click', () => dlg.close());
    }
    let tabsEl = null;
    document.addEventListener('click', (e) => {
      const target = e.target.closest && e.target.closest('[data-worker-id]');
      if (!target) return;
      const wid = target.getAttribute('data-worker-id');
      if (!wid) return;
      const title = document.getElementById('slide-title');
      if (title) title.textContent = wid;
      tabsEl = document.getElementById('slide-tabs');
      tabsEl.innerHTML = '';
      ['why', 'diff', 'transcript', 'tests'].forEach((kind, i) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'tab' + (i === 0 ? ' active' : '');
        b.textContent = kind;
        b.addEventListener('click', () => loadTab(wid, kind, b));
        tabsEl.appendChild(b);
      });
      loadTab(wid, 'why', tabsEl.querySelector('.tab'));
      // Non-modal `show()` so the bracket / table behind the drawer stay
      // interactive (matches evo's right-drawer pattern). Escape still
      // closes — handled below.
      if (typeof dlg.show === 'function') {
        if (!dlg.open) dlg.show();
      } else {
        dlg.setAttribute('open', '');
      }
    });

    // Non-modal dialogs don't auto-close on Escape; wire it up.
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && dlg.open) dlg.close();
    });

    function loadTab(wid, kind, btn) {
      if (tabsEl) {
        tabsEl.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
      }
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
    bracket.initOnce();
    const initBracket = document.getElementById('bracket');
    if (initBracket) bracket.attach(initBracket);
    elapsedTicker.sync();
    elapsedTicker.start();
    attachSSE();
  });
})();
