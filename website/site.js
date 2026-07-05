const API = 'https://api.getcortexops.com';

window.setPricingCycle = function(cycle) {
  const monthly = document.getElementById('cycle-monthly');
  const yearly = document.getElementById('cycle-yearly');
  const price = document.getElementById('pro-price');
  if (!monthly || !yearly || !price) return;
  monthly.setAttribute('aria-pressed', cycle === 'monthly' ? 'true' : 'false');
  yearly.setAttribute('aria-pressed', cycle === 'yearly' ? 'true' : 'false');
  price.textContent = cycle === 'yearly' ? '$490 / yr' : '$49 / mo';
};

window.openModal = function() {
  const modal = document.getElementById('modal');
  if (!modal) return;
  modal.classList.add('open');
  document.body.style.overflow = 'hidden';
  setTimeout(() => {
    const el = document.getElementById('checkout-email');
    if (el) el.focus();
  }, 100);
};

window.closeModal = function(e) {
  const modal = document.getElementById('modal');
  if (!modal) return;
  if (e && e.target !== modal) return;
  modal.classList.remove('open');
  document.body.style.overflow = '';
};

window.showError = function(msg) {
  const el = document.getElementById('modal-error');
  if (!el) return;
  el.textContent = msg;
  el.style.display = 'block';
};

window.startPayPalCheckout = async function() {
  const email = (document.getElementById('checkout-email').value || '').trim();
  const project = (document.getElementById('checkout-project').value || '').trim();
  document.getElementById('modal-error').style.display = 'none';
  if (!email || !email.includes('@')) return window.showError('Please enter a valid email address.');
  if (!project || project.length < 2) return window.showError('Please enter a project name (min 2 chars).');
  const btn = document.getElementById('paypal-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Connecting to PayPal…'; }
  try {
    const r = await fetch(`${API}/v1/billing/paypal/checkout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ email, project }),
    });
    if (!r.ok) {
      let msg = 'Server error (' + r.status + ')';
      try { const err = await r.json(); msg = err.detail || msg; } catch (e) {}
      throw new Error(msg);
    }
    const data = await r.json();
    if (!data.approval_url) throw new Error('No PayPal approval URL returned');
    window.location.href = data.approval_url;
  } catch (err) {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = 'Pay with PayPal';
    }
    window.showError(err.message + ' — email contact@getcortexops.com if this persists.');
    console.error('PayPal checkout error:', err);
  }
};

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') window.closeModal();
});

function initObsBg() {
  if (document.querySelector('.obs-bg') || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const tickerItems = [
    'trace.ingest OK · 142ms',
    'eval.gate PASS · 98.2%',
    'node.tool_lookup · 890ms',
    'span.PaymentAgent active',
    'webhook.alert queued',
    'p95 latency · 1.2s',
    'quota.used · 12%',
    'ci.gate blocking deploy',
    'replay.trace matched',
    'metric.error_rate · 0.4%',
  ];
  const tickerHtml = [...tickerItems, ...tickerItems].map((t) => `<span>${t}</span>`).join('');

  const wavePath = 'M0,20 Q25,5 50,18 T100,12 T150,20 T200,8 L200,40 L0,40 Z';

  const el = document.createElement('div');
  el.className = 'obs-bg';
  el.setAttribute('aria-hidden', 'true');
  el.innerHTML = `
    <div class="obs-glow"></div>
    <div class="obs-grid"></div>
    <div class="obs-scan-v"></div>
    <div class="obs-scan-h"></div>
    <svg class="obs-svg" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="none" viewBox="0 0 100 100">
      <path class="obs-trace obs-trace-1" d="M0,22 C18,8 32,38 52,18 S82,32 100,14"/>
      <path class="obs-trace obs-trace-2" d="M0,68 C22,82 44,54 66,72 S88,58 100,76"/>
      <path class="obs-trace obs-trace-3" d="M0,44 L28,36 L52,50 L76,38 L100,46"/>
      <path class="obs-trace obs-trace-4" d="M0,58 C30,48 55,62 78,52 S95,60 100,55"/>
    </svg>
    <div class="obs-node" style="--x:11%;--y:20%;--c:var(--blue);--d:0s"></div>
    <div class="obs-node" style="--x:78%;--y:28%;--c:var(--green);--d:-1.2s"></div>
    <div class="obs-node" style="--x:62%;--y:68%;--c:var(--brand);--d:-2.4s"></div>
    <div class="obs-node" style="--x:24%;--y:72%;--c:var(--purple);--d:-.8s"></div>
    <div class="obs-node" style="--x:88%;--y:58%;--c:var(--cyan);--d:-1.8s"></div>
    <div class="obs-node" style="--x:42%;--y:14%;--c:var(--amber);--d:-3s"></div>
    <div class="obs-ring" style="--x:30%;--y:38%;--d:0s"></div>
    <div class="obs-ring obs-ring-2" style="--x:70%;--y:62%;--d:-3.5s"></div>
    <div class="obs-beacon" style="--x:18%;--y:48%;--c:var(--green);--d:0s"></div>
    <div class="obs-beacon" style="--x:55%;--y:32%;--c:var(--blue);--d:-2s"></div>
    <div class="obs-beacon" style="--x:92%;--y:42%;--c:var(--brand);--d:-4s"></div>
    <div class="obs-spark obs-spark-tl"><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div>
    <div class="obs-spark obs-spark-br"><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div>
    <div class="obs-spark obs-spark-mr"><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div>
    <div class="obs-spark obs-spark-bl"><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div>
    <div class="obs-wave obs-wave-top"><svg viewBox="0 0 200 40" preserveAspectRatio="none"><path d="${wavePath}" fill="rgba(59,130,246,.35)"/></svg></div>
    <div class="obs-wave obs-wave-btm"><svg viewBox="0 0 200 40" preserveAspectRatio="none"><path d="${wavePath}" fill="rgba(220,38,38,.28)"/></svg></div>
    <div class="obs-ticker"><div class="obs-ticker-track">${tickerHtml}</div></div>
  `;
  document.body.prepend(el);
}

document.querySelectorAll('a[href^="#"]').forEach((a) => {
  a.addEventListener('click', (e) => {
    const id = a.getAttribute('href');
    if (!id || id === '#') return;
    const t = document.querySelector(id);
    if (t) {
      e.preventDefault();
      t.scrollIntoView({ behavior: 'smooth' });
    }
  });
});

function startHeroLiveDemo() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const nodes = ['running...', 'classify_intent', 'tool: lookup', 'evaluate_policy', 'running...'];
  const latencies = ['updating...', '1.18s', '890ms', '2.01s', 'updating...'];
  const health = ['changing...', 'stable', 'degraded', 'recovering', 'changing...'];
  const tools = ['tool call animated...', 'tool: lookup_policy', 'tool: issue_refund', 'tool call animated...'];
  const alerts = [
    'Trace expanding... PaymentGatewayTimeout after tool call',
    'Trace expanding... tool branch active',
    'Trace expanding... failure context attached',
  ];

  let i = 0;
  const nodeEl = document.getElementById('metric-node');
  const latEl = document.getElementById('metric-latency');
  const healthEl = document.getElementById('metric-health');
  const toolEl = document.getElementById('tool-call-label');
  const barEl = document.getElementById('tool-call-bar');
  const alertEl = document.getElementById('trace-alert');
  if (!nodeEl || !latEl || !healthEl) return;

  setInterval(() => {
    i = (i + 1) % nodes.length;
    nodeEl.textContent = nodes[i];
    latEl.textContent = latencies[i];
    healthEl.textContent = health[i];
    if (toolEl) toolEl.textContent = tools[i % tools.length];
    if (barEl) {
      const widths = ['32%', '48%', '64%', '40%'];
      barEl.style.width = widths[i % widths.length];
    }
    if (alertEl) alertEl.textContent = alerts[i % alerts.length];
  }, 1600);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initObsBg);
} else {
  initObsBg();
}

window.addEventListener('load', async () => {
  startHeroLiveDemo();
  try {
    const r = await fetch(`${API}/health`, { signal: AbortSignal.timeout(5000) });
    if (!r.ok) console.warn('CortexOps API health check failed:', r.status);
  } catch (e) {
    console.warn('CortexOps API unreachable:', e.message);
  }

  const params = new URLSearchParams(window.location.search);
  if (params.get('paypal') === 'success' || params.get('checkout') === 'success') {
    const b = document.getElementById('success-banner');
    if (b) {
      b.style.display = 'block';
      b.textContent = 'PayPal subscription active — check your email for your CortexOps Pro API key.';
    }
  }
  if (params.get('trial') === '1') window.openModal();
});
