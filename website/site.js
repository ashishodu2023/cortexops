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
