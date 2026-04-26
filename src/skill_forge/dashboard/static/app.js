// Skill-Forge dashboard — SSE consumer + slide-over wiring.
//
// htmx's hx-swap-oob processing only fires inside its own AJAX response
// pipeline, NOT when HTML is dropped via innerHTML from an EventSource.
// So we apply OOB swaps ourselves: parse the fragment, find every
// [id][hx-swap-oob] element, and replace the document element with the
// matching id. This is the live-update path; without it, the page shows
// only its initial server-rendered snapshot.

(function () {
  // ---- OOB swap applier ------------------------------------------
  function applyOobSwaps(html) {
    // The browser's HTML parser will drop bare <tr> elements unless they
    // sit inside <table>. Wrap fragments that look table-flavored so
    // worker-row swaps survive parsing.
    let wrapped = html;
    if (/<tr[\s>]/i.test(html) && !/<table/i.test(html)) {
      wrapped = '<table><tbody>' + html + '</tbody></table>';
    }
    const doc = new DOMParser().parseFromString(wrapped, 'text/html');
    const nodes = doc.querySelectorAll('[id][hx-swap-oob]');
    nodes.forEach((node) => {
      const target = document.getElementById(node.id);
      if (target) {
        // Standard OOB: replace the live element with the new one.
        target.replaceWith(document.adoptNode(node));
        return;
      }
      // Element doesn't exist yet (e.g. first WorkerSpawned for w0).
      // Append to the right container based on node type.
      let container = null;
      if (node.tagName === 'TR') {
        container = document.getElementById('workers-body');
        const empty = document.getElementById('workers-empty');
        if (empty) empty.remove();
      }
      if (container) {
        container.appendChild(document.adoptNode(node));
      }
    });
  }

  // ---- SSE → DOM update ------------------------------------------
  function attachSSE() {
    let es = null;
    let reconnectTimer = null;

    function connect() {
      es = new EventSource('/events');
      es.addEventListener('html', (e) => {
        applyOobSwaps(e.data);
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

  // ---- Slide-over (Phase 4) — covers both <tr> rows and SVG nodes -
  function attachSlide() {
    const dlg = document.getElementById('slide');
    if (!dlg) return;
    const close = document.getElementById('slide-close');
    if (close) {
      close.addEventListener('click', () => dlg.close());
    }
    document.addEventListener('click', (e) => {
      // Match ANY element carrying data-worker-id: <tr.worker-row> in
      // the table, <g data-worker-id> in the bracket SVG, etc.
      const tgt = e.target;
      const node = (tgt.closest && tgt.closest('[data-worker-id]'))
        || (tgt.getAttribute && tgt.getAttribute('data-worker-id') ? tgt : null);
      if (!node) return;
      const wid = node.dataset
        ? node.dataset.workerId
        : node.getAttribute('data-worker-id');
      if (!wid) return;
      const title = document.getElementById('slide-title');
      if (title) title.textContent = wid;
      const tabs = document.getElementById('slide-tabs');
      tabs.innerHTML = '';
      ['why', 'diff', 'transcript', 'tests'].forEach((kind, i) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'tab' + (i === 0 ? ' active' : '');
        b.textContent = kind;
        b.addEventListener('click', () => loadTab(wid, kind, b));
        tabs.appendChild(b);
      });
      loadTab(wid, 'why', tabs.querySelector('.tab'));
      if (typeof dlg.showModal === 'function') {
        dlg.showModal();
      } else {
        dlg.setAttribute('open', '');
      }
    });

    function loadTab(wid, kind, btn) {
      const tabs = document.getElementById('slide-tabs');
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
