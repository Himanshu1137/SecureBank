/* SecureBank React app (no build step: React + htm tagged templates). */
const { useState, useEffect, useRef, useCallback } = React;
/* htm -> React bridge: accepts `class` and CSS strings in style="..." */
const cssObj = s => Object.fromEntries(s.split(';').filter(r => r.includes(':')).map(r => { const i = r.indexOf(':'); return [r.slice(0, i).trim().replace(/-([a-z])/g, (_, c) => c.toUpperCase()), r.slice(i + 1).trim()]; }));
const h = (type, props, ...kids) => {
  if (props) {
    if (typeof props.style === 'string') props = { ...props, style: cssObj(props.style) };
    if (props.class !== undefined) { const { class: c, ...rest } = props; props = { ...rest, className: c }; }
  }
  return React.createElement(type, props, ...kids);
};
const html = htm.bind(h);

const fmt = n => '₹' + Number(n || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const dt = s => new Date(s).toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
const LABEL = { 1: 'Deposit', 2: 'Withdrawal', 3: 'Interest' };
const BADGE = { 1: 'd', 2: 'w', 3: '' };

function Field({ label, error, ...p }) {
  return html`<label class="field"><span>${label}</span><input ...${p} />${error && html`<small class="err">${error}</small>`}</label>`;
}

/* ---------- Step 1: Login + 4-step account opening (details -> mobile OTP -> Aadhaar KYC -> account) ---------- */
const STEP_OF = { first_name: 1, last_name: 1, email: 1, password: 1, phone: 2, code: 2, phone_token: 2, aadhaar: 3, consent: 3, mpin: 3 };
function Auth({ onAuth }) {
  const [mode, setMode] = useState('login');
  const [step, setStep] = useState(1);
  const [types, setTypes] = useState([]);
  const [err, setErr] = useState({});
  const [busy, setBusy] = useState(false);
  const [otpSent, setOtpSent] = useState(false);
  const [verified, setVerified] = useState(false);
  const [devOtp, setDevOtp] = useState('');
  const [lo, setLo] = useState(null);
  const [docs, setDocs] = useState({ AADHAAR: null, PAN: null, PHOTO: null });
  const [f, setF] = useState({ email: 'demo@securebank.in', password: 'Demo@1234', first_name: '', last_name: '', gender: 'M', birth_date: '', account_type: '',
    street_address: '', city: '', postal_code: '', country: 'India', phone: '', code: '', phone_token: '', aadhaar: '', consent: false, mpin: '' });
  useEffect(() => { API.accountTypes().then(t => { setTypes(t); setF(x => ({ ...x, account_type: t[0] ? t[0].id : '' })); }).catch(() => {}); }, []);
  const set = k => e => setF({ ...f, [k]: e.target.value });
  const digits = (k, n) => e => setF({ ...f, [k]: e.target.value.replace(/\D/g, '').slice(0, n) });
  const swap = m => { setMode(m); setStep(1); setErr({}); setLo(null); setF(x => ({ ...x, email: m === 'login' ? 'demo@securebank.in' : '', password: m === 'login' ? 'Demo@1234' : '' })); };
  const fail = e => { const fl = e.fields || {}; setErr({ ...fl, _: e.message }); const st = Object.keys(fl).map(k => STEP_OF[k]).filter(Boolean); if (st.length) setStep(Math.min(...st)); };
  const run = async fn => { setBusy(true); setErr({}); try { const r = await fn(); onAuth(r); } catch (e) { fail(e); } setBusy(false); };
  const act = async fn => { setBusy(true); setErr({}); try { await fn(); } catch (e) { setErr({ ...e.fields, _: e.message }); } setBusy(false); };
  const doLogin = e => { e.preventDefault(); setBusy(true); setErr({});
    API.login(f.email, f.password).then(r => { if (r && r.otp_required) setLo({ ...r, code: '' }); else onAuth(); }).catch(fail).then(() => setBusy(false)); };
  const doVerify = e => { e.preventDefault(); run(() => API.loginVerify(lo.otp_token, lo.code)); };
  const next1 = e => { e.preventDefault(); const m = {}; if (!f.first_name) m.first_name = 'Required'; if (!f.last_name) m.last_name = 'Required';
    if (!f.email.includes('@')) m.email = 'Enter a valid email'; if (f.password.length < 8) m.password = 'At least 8 characters';
    if (Object.keys(m).length) return setErr(m); setErr({}); setStep(2); };
  const sendOtp = () => act(async () => { const r = await API.otpSend(f.phone); setOtpSent(true); setDevOtp(r.dev_otp || ''); });
  const verify = () => act(async () => { const r = await API.otpVerify(f.phone, f.code); setF(x => ({ ...x, phone_token: r.phone_token })); setVerified(true); });
  const pick = kind => e => { const file = e.target.files[0]; if (!file) return setDocs({ ...docs, [kind]: null });
    if (!['image/jpeg', 'image/png', 'application/pdf'].includes(file.type)) { e.target.value = ''; return setErr({ docs: 'Only JPG, PNG or PDF files are allowed.' }); }
    if (file.size > 2 * 1024 * 1024) { e.target.value = ''; return setErr({ docs: 'File is too large (maximum 2 MB).' }); }
    setErr({}); setDocs({ ...docs, [kind]: file }); };
  const doRegister = e => { e.preventDefault(); run(async () => { await API.register(f); const failed = [];
    for (const k of Object.keys(docs)) if (docs[k]) { try { await API.uploadDoc(k, docs[k]); } catch (x) { failed.push(k.toLowerCase() + ' (' + x.message + ')'); } }
    return { registered: true, failed }; }); };
  const next3 = e => { e.preventDefault(); const m = {}; if (!docs.AADHAAR) m.docs = 'Please upload a photo or scan of your Aadhaar card.'; if (f.aadhaar.length !== 12) m.aadhaar = 'Aadhaar must be 12 digits';
    if (!/^\d{4,6}$/.test(f.mpin)) m.mpin = 'mPIN must be 4-6 digits'; if (!f.consent) m.consent = 'Consent is required';
    if (Object.keys(m).length) return setErr(m); setErr({}); setStep(4); };
  const E = k => err[k];
  const T = ['', 'Personal details', 'Verify mobile number', 'Aadhaar KYC & mPIN', 'Account & address'];
  return html`<div class="auth">
    <div class="auth-art"><h1>Secure<span>Bank</span></h1>
      <p class="sub">Digital banking for India with a private AI assistant.</p>
      <ul><li>Open an account with mobile OTP + Aadhaar KYC</li><li>RuPay-style debit card, ATM PIN and ATM banking</li><li>UPI id, IFSC, transfers, Fixed Deposits</li><li>WhatsApp banking and an AI assistant</li></ul></div>
    <div class="card">
      ${mode === 'login' ? html`
        <h2>Welcome back</h2><p class="sub">${lo ? 'Enter the OTP sent to your mobile' : 'Login to your account'}</p>
        ${err._ && html`<div class="alert">${err._}</div>`}
        ${!lo ? html`<form onSubmit=${doLogin}>
          <${Field} label="Email" type="email" value=${f.email} onInput=${set('email')} required />
          <${Field} label="Password" type="password" value=${f.password} onInput=${set('password')} required />
          <button class="btn" style="width:100%" disabled=${busy}>${busy ? 'Please wait…' : 'Login'}</button></form>
          <p class="hint">Demo customer: demo@securebank.in / Demo@1234 (OTP step follows). Bank admin: admin@securebank.in / Admin@1234.</p>`
        : html`<form onSubmit=${doVerify}><p class="hint" style="margin:0 0 10px">${lo.message}</p>
          <${Field} label="6-digit OTP" inputmode="numeric" value=${lo.code} onInput=${e => setLo({ ...lo, code: e.target.value.replace(/\D/g, '').slice(0, 6) })} error=${E('code')} required />
          ${lo.dev_otp && html`<p class="hint">Demo mode: your OTP is <b>${lo.dev_otp}</b> (real SMS is used once an SMS provider is configured).</p>`}
          <button class="btn" style="width:100%" disabled=${busy || lo.code.length !== 6}>${busy ? 'Verifying…' : 'Verify & login'}</button></form>`}
        <button class="link" onClick=${() => swap('register')}>New here? Open an account →</button>`
      : html`
        <h2>Open your account</h2><p class="sub">Step ${step} of 4 · ${T[step]}</p>
        <div class="steps">${[1, 2, 3, 4].map(n => html`<i class=${n <= step ? 'on' : ''}></i>`)}</div>
        ${err._ && html`<div class="alert">${err._}</div>`}
        ${step === 1 && html`<form onSubmit=${next1}>
          <div class="row2"><${Field} label="First name" value=${f.first_name} onInput=${set('first_name')} error=${E('first_name')} />
          <${Field} label="Last name" value=${f.last_name} onInput=${set('last_name')} error=${E('last_name')} /></div>
          <${Field} label="Email" type="email" value=${f.email} onInput=${set('email')} error=${E('email')} />
          <${Field} label="Password (min 8 chars)" type="password" value=${f.password} onInput=${set('password')} error=${E('password')} />
          <button class="btn" style="width:100%">Continue</button></form>`}
        ${step === 2 && html`<div>
          <${Field} label="Mobile number (+91)" inputmode="numeric" placeholder="10-digit mobile" value=${f.phone} onInput=${digits('phone', 10)} error=${E('phone')} disabled=${verified} />
          ${!verified && html`<button class="btn ghost" disabled=${busy || f.phone.length !== 10} onClick=${sendOtp}>${otpSent ? 'Resend OTP' : 'Send OTP'}</button>`}
          ${otpSent && !verified && html`<div style="margin-top:12px"><${Field} label="Enter 6-digit OTP" inputmode="numeric" value=${f.code} onInput=${digits('code', 6)} error=${E('code')} />
            ${devOtp && html`<p class="hint">Demo mode: your OTP is <b>${devOtp}</b> (a real SMS gateway sends this in production).</p>`}
            <button class="btn" disabled=${busy || f.code.length !== 6} onClick=${verify}>Verify OTP</button></div>`}
          ${verified && html`<p class="up" style="font-weight:700;margin:10px 0">✔ Mobile number verified</p>`}
          <div class="actions"><button class="btn ghost" onClick=${() => setStep(1)}>Back</button>
          <button class="btn" disabled=${!verified} onClick=${() => setStep(3)}>Continue</button></div></div>`}
        ${step === 3 && html`<form onSubmit=${next3}>
          <${Field} label="Aadhaar number" inputmode="numeric" placeholder="XXXX XXXX XXXX" value=${f.aadhaar.replace(/(\d{4})(?=\d)/g, '$1 ')} onInput=${digits('aadhaar', 12)} error=${E('aadhaar')} />
          ${API.mode === 'mock' && html`<p class="hint">Demo test Aadhaar (not a real person): 2345 6789 0124</p>`}
          <${Field} label="Set mPIN (4-6 digits) — used for transfers, card & FD actions" type="password" inputmode="numeric" value=${f.mpin} onInput=${digits('mpin', 6)} error=${E('mpin')} />
          <div class="docbox"><b>Upload KYC documents</b><small class="hint" style="display:block;margin:2px 0 8px">JPG, PNG or PDF · max 2 MB each · reviewed by the bank</small>
            ${[['AADHAAR', 'Aadhaar card (front/back) *'], ['PAN', 'PAN card (optional)'], ['PHOTO', 'Passport-size photo (optional)']].map(([k, l]) => html`<label class="field" key=${k}><span>${l}</span>
              <input type="file" accept=".jpg,.jpeg,.png,.pdf,image/jpeg,image/png,application/pdf" onChange=${pick(k)} />${docs[k] && html`<small class="up">✔ ${docs[k].name} (${Math.max(1, Math.round(docs[k].size / 1024))} KB)</small>`}</label>`)}
            ${E('docs') && html`<small class="err">${E('docs')}</small>`}</div>
          <label class="check"><input type="checkbox" checked=${f.consent} onChange=${e => setF({ ...f, consent: e.target.checked })} />
            <span>I consent to SecureBank using my Aadhaar number for KYC. Only the last 4 digits are stored; the full number is never saved.</span></label>
          ${E('consent') && html`<small class="err">${E('consent')}</small>`}
          <div class="actions"><button type="button" class="btn ghost" onClick=${() => setStep(2)}>Back</button><button class="btn">Continue</button></div></form>`}
        ${step === 4 && html`<form onSubmit=${doRegister}>
          <label class="field"><span>Account type</span><select value=${f.account_type} onChange=${set('account_type')}>
            ${types.map(t => html`<option value=${t.id}>${t.name} · ${t.annual_interest_rate}% p.a. · limit ${fmt(t.maximum_withdrawal_amount)}</option>`)}</select></label>
          <div class="row2"><label class="field"><span>Gender</span><select value=${f.gender} onChange=${set('gender')}><option value="M">Male</option><option value="F">Female</option></select></label>
          <${Field} label="Date of birth" type="date" value=${f.birth_date} onInput=${set('birth_date')} error=${E('birth_date')} /></div>
          <${Field} label="Street address" value=${f.street_address} onInput=${set('street_address')} error=${E('street_address')} />
          <div class="row2"><${Field} label="City" value=${f.city} onInput=${set('city')} error=${E('city')} />
          <${Field} label="PIN code" inputmode="numeric" value=${f.postal_code} onInput=${digits('postal_code', 6)} error=${E('postal_code')} /></div>
          <div class="actions"><button type="button" class="btn ghost" onClick=${() => setStep(3)}>Back</button>
          <button class="btn" disabled=${busy}>${busy ? 'Creating…' : 'Create account'}</button></div></form>`}
        <button class="link" onClick=${() => swap('login')}>← I already have an account</button>`}
    </div></div>`;
}

/* ---------- Step 2: Dashboard ---------- */
function Dashboard({ user, go, toast, refresh }) {
  const [tx, setTx] = useState([]);
  useEffect(() => { API.transactions().then(setTx).catch(() => {}); }, [user.balance]);
  const sum = k => tx.filter(x => x.type === k).reduce((a, x) => a + Number(x.amount), 0);
  const last = tx.slice(0, 8).reverse(), max = Math.max(1, ...last.map(x => Number(x.balance_after)));
  return html`<div>
    <div class="hero grad"><div><small>Available balance</small><div class="bal">${fmt(user.balance)}</div>
      <small>${user.account_type.name} account · ${user.account_type.annual_interest_rate}% p.a.</small></div>
      <div class="acc"><small>Account number</small><div style="font-size:22px;font-weight:700">${user.account_no}</div><small>IFSC ${user.ifsc} · UPI ${user.upi_id}</small></div></div>
    <div class="actions"><button class="btn" onClick=${() => go('deposit')}>＋ Deposit</button><button class="btn" onClick=${() => go('withdraw')}>− Withdraw</button>
      <button class="btn" onClick=${() => go('transfer')}>⇄ Transfer</button></div>
    <div class="grid"><div class="card stat"><small>Total deposits</small><b class="up">${fmt(sum(1))}</b></div>
      <div class="card stat"><small>Total withdrawals</small><b class="down">${fmt(sum(2))}</b></div>
      <div class="card stat"><small>Interest earned</small><b>${fmt(sum(3))}</b></div></div>
    <div class="grid" style="margin-top:16px"><div class="card"><b style="color:var(--ink)">Balance trend</b><div class="bars">
      ${last.map(x => html`<i title=${fmt(x.balance_after)} style=${'height:' + Math.max(4, Number(x.balance_after) / max * 100) + '%'}></i>`)}</div></div>
      <div class="card"><b style="color:var(--ink)">Recent activity</b>
      ${tx.slice(0, 4).map(x => html`<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--bd)"><span>${x.description || LABEL[x.type]}</span>
        <b class=${x.type === 2 ? 'down' : 'up'}>${x.type === 2 ? '−' : '+'}${fmt(x.amount)}</b></div>`)}
      ${!tx.length && html`<p class="sub">No transactions yet.</p>`}<button class="link" onClick=${() => go('history')}>View all →</button></div></div></div>`;
}

/* ---------- Step 3: Deposit / Withdraw / Transfer (beneficiaries + OTP for high-value) ---------- */
function Money({ kind, user, toast, refresh, go }) {
  const empty = { amount: '', to_account_no: '', note: '', otp: '' };
  const [v, setV] = useState(empty);
  const [err, setErr] = useState({});
  const [busy, setBusy] = useState(false);
  const [otp, setOtp] = useState(null);
  const [bens, setBens] = useState([]);
  const loadBens = () => { if (kind === 'transfer') API.beneficiaries().then(setBens).catch(() => {}); };
  useEffect(() => { setV(empty); setErr({}); setOtp(null); loadBens(); }, [kind]);
  const T = { deposit: ['Deposit money', 'Add funds to your account. Minimum ₹10.'],
    withdraw: ['Withdraw money', 'Limit per withdrawal: ' + fmt(user.account_type.maximum_withdrawal_amount)],
    transfer: ['Transfer money', 'Instant transfer to any SecureBank account. Transfers above ₹10,000 need an SMS OTP.'] }[kind];
  const set = k => e => setV({ ...v, [k]: e.target.value });
  const submit = async e => {
    e.preventDefault(); setBusy(true); setErr({});
    try { const r = await API[kind](v); if (r.otp_required) { setOtp(r); } else { toast(r.message); await refresh(); go('history'); } }
    catch (x) { setErr({ ...x.fields, _: x.message }); }
    setBusy(false);
  };
  const saveBen = async () => { try { const r = await API.beneficiaryAdd({ identifier: v.to_account_no }); toast(r.message); loadBens(); } catch (x) { setErr({ to_account_no: x.message }); } };
  const delBen = async b => { await API.beneficiaryDelete({ id: b.id }); loadBens(); };
  return html`<div style="max-width:480px"><h2>${T[0]}</h2><p class="sub">${T[1]} · Balance ${fmt(user.balance)}</p>
    <form class="card" onSubmit=${submit}>${err._ && html`<div class="alert">${err._}</div>`}
      ${kind === 'transfer' && html`<div>
        ${bens.length > 0 && html`<div class="bens">${bens.map(b => html`<span key=${b.id}><button type="button" onClick=${() => setV({ ...v, to_account_no: b.identifier })}>${b.name}</button><button type="button" title="Remove" onClick=${() => delBen(b)}>×</button></span>`)}</div>`}
        <${Field} label="Account no. / mobile number / UPI id" value=${v.to_account_no} onInput=${set('to_account_no')} error=${err.to_account_no} required />
        <button type="button" class="link" style="margin:-6px 0 10px" onClick=${saveBen}>＋ Save as beneficiary</button></div>`}
      <${Field} label="Amount (₹)" type="number" step="0.01" min="1" value=${v.amount} onInput=${set('amount')} error=${err.amount} required />
      <${Field} label="Note (optional)" maxlength="60" value=${v.note} onInput=${set('note')} />
      ${otp && html`<div><p class="hint" style="margin:0 0 8px">${otp.message}</p><${Field} label="SMS OTP" inputmode="numeric" value=${v.otp} onInput=${set('otp')} error=${err.code} required />
        ${otp.dev_otp && html`<p class="hint">Demo mode: your OTP is <b>${otp.dev_otp}</b></p>`}</div>`}
      <button class="btn" style="width:100%" disabled=${busy}>${busy ? 'Processing…' : otp ? 'Confirm with OTP' : T[0]}</button></form></div>`;
}

/* ---------- Step 4: Transaction history + statement ---------- */
function History({ toast }) {
  const [tx, setTx] = useState([]);
  const [type, setType] = useState('');
  const [q, setQ] = useState('');
  useEffect(() => { const p = {}; if (type) p.type = type; if (q) p.q = q; const h = setTimeout(() => API.transactions(p).then(setTx).catch(() => {}), 200); return () => clearTimeout(h); }, [type, q]);
  const csv = () => {
    if (API.demo) return toast('CSV download works in the full project (run locally).');
    const rows = [['Date', 'Type', 'Description', 'Amount', 'Balance After'], ...tx.map(x => [dt(x.timestamp), LABEL[x.type], x.description || '', x.amount, x.balance_after])];
    const text = rows.map(r => r.map(c => '"' + String(c).replace(/"/g, '""') + '"').join(',')).join('\n');
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv' })); a.download = 'securebank-statement.csv'; a.click();
  };
  return html`<div><h2>Transactions</h2><p class="sub">Search, filter and download your statement.</p>
    <div class="card"><div class="filters"><input placeholder="Search description…" value=${q} onInput=${e => setQ(e.target.value)} />
      <select value=${type} onChange=${e => setType(e.target.value)}><option value="">All types</option><option value="1">Deposits</option><option value="2">Withdrawals</option><option value="3">Interest</option></select>
      <button class="btn ghost" onClick=${csv}>⬇ CSV</button><button class="btn ghost" onClick=${() => API.pdf().catch(e => toast(e.message))}>⬇ PDF statement</button></div>
      <div class="wrap"><table class="tbl"><thead><tr><th>Date</th><th>Type</th><th>Description</th><th>Amount</th><th>Balance</th></tr></thead><tbody>
      ${tx.map(x => html`<tr key=${x.id}><td>${dt(x.timestamp)}</td><td><span class=${'badge ' + BADGE[x.type]}>${LABEL[x.type]}</span></td><td>${x.description} <small class="hint">[${x.channel || 'APP'}]</small></td>
        <td class=${x.type === 2 ? 'down' : 'up'}><b>${x.type === 2 ? '−' : '+'}${fmt(x.amount)}</b></td><td>${fmt(x.balance_after)}</td></tr>`)}</tbody></table>
      ${!tx.length && html`<p class="sub" style="margin-top:12px">No transactions found.</p>`}</div></div></div>`;
}

/* ---------- Step 5: Profile ---------- */
function Profile({ user }) {
  const a = user.address || {}, row = (k, v) => html`<div style="display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--bd)"><span>${k}</span><b style="color:var(--ink)">${v}</b></div>`;
  return html`<div style="max-width:560px"><h2>Profile & security</h2><p class="sub">Your account details.</p><div class="card">
    ${row('Name', user.first_name + ' ' + user.last_name)}${row('Email', user.email)}${row('Mobile', '+91 ' + user.phone)}${row('Aadhaar (masked)', user.aadhaar_masked)}${row('KYC status', user.kyc_status)}${row('Account number', user.account_no)}${row('IFSC', user.ifsc)}${row('UPI id', user.upi_id)}
    ${row('Account type', user.account_type.name)}${row('Interest rate', user.account_type.annual_interest_rate + '% p.a.')}${row('Withdrawal limit', fmt(user.account_type.maximum_withdrawal_amount))}
    ${row('Date of birth', user.birth_date || '-')}${row('Address', [a.street_address, a.city, a.postal_code].filter(Boolean).join(', ') || '-')}
    <p class="hint">Security tip: never share your password or OTP with anyone.</p></div></div>`;
}

/* ---------- Step 6: AI assistant ---------- */
function Assistant({ go }) {
  const [open, setOpen] = useState(false);
  const [v, setV] = useState('');
  const [msgs, setMsgs] = useState([{ w: 'bot', t: 'Hi! I can answer questions about your balance, transactions, interest and security.' }]);
  const end = useRef();
  useEffect(() => { if (end.current) end.current.scrollIntoView(); }, [msgs, open]);
  const ask = async t => {
    t = t.trim(); if (!t) return; setV(''); setMsgs(m => [...m, { w: 'me', t }]);
    try { const r = await API.assistant(t, msgs.slice(-6).map(m => ({ role: m.w === 'me' ? 'user' : 'assistant', text: m.t }))); setMsgs(m => [...m, { w: 'bot', t: r.message, a: r.action }]); }
    catch (e) { setMsgs(m => [...m, { w: 'bot', t: 'Sorry, I could not process that. ' + e.message }]); }
  };
  return html`<div>
    ${open && html`<div class="card chat"><header class="grad">SecureBank AI Assistant<small>Private · answers from your account only</small></header>
      <div class="msgs">${msgs.map(m => html`<div class=${'b ' + m.w}>${m.t}${m.a && html`<div><button class="link" style="margin:4px 0 0" onClick=${() => { go(m.a); setOpen(false); }}>Open ${m.a} →</button></div>`}</div>`)}<div ref=${end}></div></div>
      <div class="chips">${['My balance', 'Recent transactions', 'Interest rate', 'Account summary', 'Security tips'].map(c => html`<button onClick=${() => ask(c)}>${c}</button>`)}</div>
      <form onSubmit=${e => { e.preventDefault(); ask(v); }}><input value=${v} onInput=${e => setV(e.target.value)} placeholder="Ask about your account…" /><button class="btn">Send</button></form></div>`}
    <button class="chat-btn grad" aria-label="AI assistant" onClick=${() => setOpen(!open)}>${open ? '✕' : '✦'}</button></div>`;
}

/* ---------- Step 7: Debit card + ATM banking ---------- */
function ATM({ card, refresh }) {
  const [v, setV] = useState({ card_no: card.number, pin: '', action: 'balance', amount: '', new_pin: '' });
  const [out, setOut] = useState(null);
  const set = k => e => setV({ ...v, [k]: e.target.value });
  const go = async e => { e.preventDefault(); try { setOut(await API.atm(v)); refresh(); } catch (x) { setOut({ error: x.message }); } setV({ ...v, pin: '' }); };
  return html`<div class="card"><h3 style="color:var(--ink)">ATM simulator</h3><p class="sub">Works like a real ATM: card number + PIN. 3 wrong PINs block the card.</p>
    <form onSubmit=${go}><${Field} label="Card number" value=${v.card_no} onInput=${set('card_no')} />
      <div class="row2"><${Field} label="ATM PIN" type="password" inputmode="numeric" maxlength="4" value=${v.pin} onInput=${set('pin')} />
      <label class="field"><span>Service</span><select value=${v.action} onChange=${set('action')}><option value="balance">Balance enquiry</option><option value="withdraw">Cash withdrawal</option><option value="statement">Mini statement</option><option value="change_pin">Change PIN</option></select></label></div>
      ${v.action === 'withdraw' && html`<${Field} label="Amount (multiples of ₹100, max ₹10,000)" type="number" value=${v.amount} onInput=${set('amount')} />`}
      ${v.action === 'change_pin' && html`<${Field} label="New PIN" type="password" inputmode="numeric" maxlength="4" value=${v.new_pin} onInput=${set('new_pin')} />`}
      <button class="btn" style="width:100%">Insert card & continue</button></form>
    ${out && html`<div class=${'atm ' + (out.error ? 'bad' : '')}>${out.error || out.message}${(out.lines || []).map(l => html`<div>${l}</div>`)}</div>`}</div>`;
}

function CardApply({ app, toast, refresh, reload }) {
  const [v, setV] = useState({ variant: 'CLASSIC', mpin: '' });
  const [err, setErr] = useState({});
  const submit = async e => { e.preventDefault(); setErr({}); try { const r = await API.cardApply(v); toast(r.message); setV({ ...v, mpin: '' }); reload(); refresh(); } catch (x) { setErr({ ...x.fields, _: x.message }); } };
  const NAMES = { CLASSIC: 'RuPay Classic · ATM limit ₹20,000/day', PLATINUM: 'RuPay Platinum · ATM limit ₹50,000/day' };
  if (app && app.status === 'PENDING') return html`<div class="card"><b style="color:var(--ink)">⏳ Card application under review</b>
    <p class="sub" style="margin-top:6px">You applied for a <b>${NAMES[app.variant]}</b> debit card on ${dt(app.created)}. Your card is created and the ATM service starts only after the bank approves the application.</p></div>`;
  return html`<form class="card" onSubmit=${submit}><b style="color:var(--ink)">Apply for a debit card</b>
    <p class="sub" style="margin:4px 0 12px">Choose a card and apply. The bank reviews your application — the card and ATM service are activated only after approval.</p>
    ${app && app.status === 'REJECTED' && html`<div class="alert">Your last application was rejected: ${app.note || 'no reason given'}. You can apply again.</div>`}
    ${err._ && html`<div class="alert">${err._}</div>`}
    <label class="field"><span>Card type</span><select value=${v.variant} onChange=${e => setV({ ...v, variant: e.target.value })}>${Object.keys(NAMES).map(k => html`<option value=${k}>${NAMES[k]}</option>`)}</select></label>
    <${Field} label="Your mPIN" type="password" inputmode="numeric" value=${v.mpin} onInput=${e => setV({ ...v, mpin: e.target.value.replace(/\D/g, '').slice(0, 6) })} error=${err.mpin} required />
    <button class="btn" style="width:100%">Apply for debit card</button></form>`;
}

function CardPage({ user, toast, refresh }) {
  const [c, setC] = useState(null);
  const [mpin, setMpin] = useState('');
  const [pin, setPin] = useState('');
  const [lim, setLim] = useState('');
  const load = () => API.card().then(setC).catch(e => toast(e.message));
  useEffect(() => { load(); }, []);
  const run = async fn => { try { const r = await fn(); toast(r.message); if (r.card) setC(r.card); setPin(''); setLim(''); } catch (e) { toast(e.message); } };
  if (!c) return html`<p class="sub">Loading card…</p>`;
  if (c.issued === false && user.kyc_status !== 'VERIFIED') return html`<div style="max-width:520px"><h2>Card & ATM banking</h2><div class="card"><b style="color:var(--ink)">Debit card not available yet</b>
    <p class="sub" style="margin-top:6px">You can apply for a debit card after the bank approves your KYC documents (status: ${user.kyc_status}).</p></div></div>`;
  if (c.issued === false) return html`<div style="max-width:520px"><h2>Card & ATM banking</h2><p class="sub">Apply for your debit card. ATM banking starts after the bank approves.</p><${CardApply} app=${c.application} toast=${toast} refresh=${refresh} reload=${load} /></div>`;
  const blocked = c.status !== 'ACTIVE';
  return html`<div><h2>Card & ATM banking</h2><p class="sub">Manage your debit card, ATM PIN and limits. Sensitive actions need your mPIN.</p>
    ${c.cvv && html`<div class="banner" style="background:#d1fae5;color:#065f46">🎉 Your debit card has been issued! Card ${c.number.replace(/(\d{4})(?=\d)/g, '$1 ')} · CVV <b>${c.cvv}</b> · valid thru ${c.expiry}. The CVV is shown only once — note it now, then set your ATM PIN below.</div>`}
    <div class="grid"><div>
      <div class=${'ccard grad ' + (blocked ? 'off' : '')}><small>SecureBank Debit</small><div class="num">${c.masked_number}</div>
        <div style="display:flex;justify-content:space-between"><span>${user.first_name} ${user.last_name}</span><span>${c.expiry}</span></div><b>${blocked ? '🔒 BLOCKED' : '● ACTIVE'}</b></div>
      <div class="card" style="margin-top:16px"><${Field} label="Your mPIN (to confirm actions)" type="password" inputmode="numeric" value=${mpin} onInput=${e => setMpin(e.target.value.replace(/\D/g, '').slice(0, 6))} />
        <div class="actions"><button class="btn" onClick=${() => run(() => API.cardAction({ action: blocked ? 'unblock' : 'block', mpin }))}>${blocked ? 'Unblock card' : 'Block card'}</button>
          <button class="btn ghost" onClick=${() => run(() => API.cardAction({ action: 'online', value: !c.online_enabled, mpin }))}>Online payments: ${c.online_enabled ? 'ON' : 'OFF'}</button></div>
        <div class="row2"><${Field} label=${c.pin_set ? 'Change ATM PIN (4 digits)' : 'Set ATM PIN (4 digits)'} type="password" inputmode="numeric" maxlength="4" value=${pin} onInput=${e => setPin(e.target.value.replace(/\D/g, ''))} />
          <${Field} label=${'Daily ATM limit (now ' + fmt(c.daily_atm_limit) + ')'} type="number" value=${lim} onInput=${e => setLim(e.target.value)} /></div>
        <div class="actions"><button class="btn" disabled=${pin.length !== 4} onClick=${() => run(() => API.setPin({ pin, mpin }))}>Save PIN</button>
          <button class="btn ghost" disabled=${!lim} onClick=${() => run(() => API.cardAction({ action: 'limit', value: lim, mpin }))}>Update limit</button></div></div></div>
      <${ATM} card=${c} refresh=${refresh} /></div></div>`;
}

/* ---------- Step 8: Fixed deposits ---------- */
function FDPage({ user, toast, refresh }) {
  const [list, setList] = useState([]);
  const [v, setV] = useState({ amount: '', months: '12', mpin: '' });
  const [err, setErr] = useState({});
  const load = () => API.fdList().then(setList).catch(() => {});
  useEffect(() => { load(); }, []);
  const act = async fn => { setErr({}); try { const r = await fn(); toast(r.message); await refresh(); load(); } catch (e) { setErr({ ...e.fields, _: e.message }); } };
  const set = k => e => setV({ ...v, [k]: e.target.value });
  const rate = m => m <= 6 ? 6 : m <= 12 ? 6.8 : m <= 24 ? 7 : 7.25;
  const mat = v.amount && v.months >= 3 ? Number(v.amount) * Math.pow(1 + rate(+v.months) / 400, v.months / 3) : 0;
  return html`<div><h2>Fixed deposit</h2><p class="sub">Earn up to 7.25% p.a. · quarterly compounding · min ₹1,000 · 3–120 months</p>
    <div class="grid"><form class="card" onSubmit=${e => { e.preventDefault(); act(() => API.fdOpen(v)); }}>${err._ && html`<div class="alert">${err._}</div>`}
      <${Field} label="Amount (₹)" type="number" value=${v.amount} onInput=${set('amount')} error=${err.amount} required />
      <${Field} label="Tenure (months)" type="number" min="3" max="120" value=${v.months} onInput=${set('months')} error=${err.months} required />
      <${Field} label="mPIN" type="password" inputmode="numeric" value=${v.mpin} onInput=${set('mpin')} error=${err.mpin} required />
      ${mat > 0 && html`<p class="hint">Rate ${rate(+v.months)}% → maturity about <b>${fmt(mat)}</b></p>`}
      <button class="btn" style="width:100%">Open FD</button></form>
    <div class="card"><b style="color:var(--ink)">Your deposits</b>
      ${list.map(f => html`<div key=${f.id} style="padding:10px 0;border-bottom:1px solid var(--bd)"><div style="display:flex;justify-content:space-between"><b>FD #${f.id} · ${fmt(f.principal)}</b>
        <span class=${'badge ' + (f.status === 'OPEN' ? 'd' : '')}>${f.status}</span></div><small>${f.rate}% · ${f.months} months · matures ${f.maturity_date} · ${fmt(f.maturity_amount)}</small>
        ${f.status === 'OPEN' && html`<div><button class="link" style="margin:4px 0 0" onClick=${() => act(() => API.fdClose({ id: f.id, mpin: v.mpin }))}>Close FD (enter mPIN on the left)</button></div>`}</div>`)}
      ${!list.length && html`<p class="sub">No fixed deposits yet.</p>`}</div></div></div>`;
}

/* ---------- Step 9: WhatsApp banking ---------- */
function WhatsApp({ user, refresh }) {
  const [msgs, setMsgs] = useState([{ w: 'bot', t: 'Send "Hi" to start banking on WhatsApp.' }]);
  const [v, setV] = useState('');
  const end = useRef();
  useEffect(() => { if (end.current) end.current.scrollIntoView(); }, [msgs]);
  const send = async t => { t = t.trim(); if (!t) return; setV(''); setMsgs(m => [...m, { w: 'me', t }]);
    try { const r = await API.whatsapp(t); setMsgs(m => [...m, { w: 'bot', t: r }]); refresh(); } catch (e) { setMsgs(m => [...m, { w: 'bot', t: '❌ ' + e.message }]); } };
  return html`<div style="max-width:520px"><h2>WhatsApp banking</h2><p class="sub">Simulator for your registered number +91 ${user.phone}. Live setup: connect Meta WhatsApp Cloud API to /api/whatsapp/webhook/.</p>
    <div class="card wa"><header>🏦 SecureBank <small>verified business · +91 ${user.phone}</small></header><div class="wamsgs">
      ${msgs.map(m => html`<div class=${'wab ' + m.w}>${m.t}</div>`)}<div ref=${end}></div></div>
      <div class="chips">${['Hi', 'Balance', 'Statement', 'My UPI', 'FD rates', 'Block card'].map(c => html`<button onClick=${() => send(c)}>${c}</button>`)}</div>
      <form onSubmit=${e => { e.preventDefault(); send(v); }}><input value=${v} onInput=${e => setV(e.target.value)} placeholder="Type a message" /><button class="btn">Send</button></form></div></div>`;
}

function CardReveal({ onClose }) {
  return html`<div class="modal"><div class="card" style="max-width:440px"><h2>🎉 Application submitted!</h2><p class="sub">Your account is created and your KYC documents are with the bank for review.</p>
    <ul style="margin:0 0 10px 18px;font-size:14px"><li>Until the bank approves your documents you can log in and view your account.</li><li>Deposits, withdrawals, transfers, payments and every other transaction stay locked.</li>
    <li>Your debit card / ATM card is created only after approval.</li></ul><button class="btn" style="width:100%" onClick=${onClose}>Go to dashboard</button></div></div>`;
}

/* ---------- Step 10: Bill payments & recharge ---------- */
const CATS = [['MOBILE', '📱 Mobile recharge'], ['DTH', '📡 DTH'], ['ELECTRICITY', '💡 Electricity'], ['WATER', '🚰 Water'], ['GAS', '🔥 Gas'], ['BROADBAND', '🌐 Broadband']];
function Payments({ user, toast, refresh }) {
  const [data, setData] = useState({ billers: {}, plans: [] });
  const [cat, setCat] = useState('MOBILE');
  const [list, setList] = useState([]);
  const [v, setV] = useState({ biller: '', consumer_no: '', amount: '', mpin: '' });
  const [err, setErr] = useState({});
  const load = () => API.payments().then(setList).catch(() => {});
  useEffect(() => { API.billers().then(setData).catch(() => {}); load(); }, []);
  useEffect(() => { setV(x => ({ ...x, biller: (data.billers[cat] || [])[0] || '', consumer_no: '', amount: '' })); setErr({}); }, [cat, data]);
  const set = k => e => setV({ ...v, [k]: e.target.value });
  const submit = async e => { e.preventDefault(); setErr({}); try { const r = await API.pay({ ...v, category: cat }); toast(r.message); setV({ ...v, amount: '', mpin: '' }); await refresh(); load(); } catch (x) { setErr({ ...x.fields, _: x.message }); } };
  return html`<div><h2>Pay bills & recharge</h2><p class="sub">Balance ${fmt(user.balance)} · mPIN required for every payment.</p>
    <div class="tabs" style="margin-bottom:14px">${CATS.map(([k, l]) => html`<button class=${cat === k ? 'on' : ''} onClick=${() => setCat(k)}>${l}</button>`)}</div>
    <div class="grid"><form class="card" onSubmit=${submit}>${err._ && html`<div class="alert">${err._}</div>`}
      <label class="field"><span>Operator / biller</span><select value=${v.biller} onChange=${set('biller')}>${(data.billers[cat] || []).map(b => html`<option value=${b}>${b}</option>`)}</select></label>
      <${Field} label=${cat === 'MOBILE' ? 'Mobile number' : 'Consumer / subscriber number'} value=${v.consumer_no} onInput=${set('consumer_no')} error=${err.consumer_no} required />
      ${cat === 'MOBILE' && html`<div class="bens">${data.plans.map(p => html`<button type="button" title=${p.info} onClick=${() => setV({ ...v, amount: String(p.amount) })}>₹${p.amount} · ${p.info}</button>`)}</div>`}
      <${Field} label="Amount (₹)" type="number" step="0.01" value=${v.amount} onInput=${set('amount')} error=${err.amount} required />
      <${Field} label="mPIN" type="password" inputmode="numeric" value=${v.mpin} onInput=${set('mpin')} error=${err.mpin} required />
      <button class="btn" style="width:100%">Pay now</button></form>
    <div class="card"><b style="color:var(--ink)">Recent payments</b>
      ${list.slice(0, 8).map(p => html`<div key=${p.id} style="padding:9px 0;border-bottom:1px solid var(--bd)"><div style="display:flex;justify-content:space-between"><span>${p.biller} · ${p.consumer_no}</span><b class="down">−${fmt(p.amount)}</b></div><small class="hint">${dt(p.timestamp)} · Ref ${p.reference}</small></div>`)}
      ${!list.length && html`<p class="sub">No payments yet.</p>`}</div></div></div>`;
}

/* ---------- Step 11: Loans & EMI ---------- */
function Loans({ user, toast, refresh }) {
  const [d, setD] = useState({ rules: {}, loans: [] });
  const [v, setV] = useState({ kind: 'PERSONAL', amount: '', months: '24', income: '', mpin: '' });
  const [err, setErr] = useState({});
  const load = () => API.loans().then(setD).catch(() => {});
  useEffect(() => { load(); }, []);
  const set = k => e => setV({ ...v, [k]: e.target.value });
  const R = d.rules[v.kind], rate = R ? Number(R.rate) : 0;
  const emi = (p, n) => { const i = rate / 1200, k = Math.pow(1 + i, n); return p * i * k / (k - 1); };
  const e = v.amount > 0 && v.months > 0 && rate ? emi(Number(v.amount), Number(v.months)) : 0;
  const act = async fn => { setErr({}); try { const r = await fn(); toast(r.message); await refresh(); load(); } catch (x) { setErr({ ...x.fields, _: x.message }); } };
  const badge = s => s === 'ACTIVE' ? 'd' : s === 'REJECTED' ? 'w' : '';
  return html`<div><h2>Loans & EMI</h2><p class="sub">Apply online · a bank officer approves · money is credited to your account · pay EMIs from here.</p>
    <div class="grid"><form class="card" onSubmit=${ev => { ev.preventDefault(); act(() => API.loanApply(v)); }}>${err._ && html`<div class="alert">${err._}</div>`}
      <label class="field"><span>Loan type</span><select value=${v.kind} onChange=${set('kind')}>${Object.keys(d.rules).map(k => html`<option value=${k}>${k[0] + k.slice(1).toLowerCase()} · ${d.rules[k].rate}% p.a.</option>`)}</select></label>
      <${Field} label=${'Loan amount (₹)' + (R ? ' · ₹' + Number(R.min).toLocaleString('en-IN') + ' to ₹' + Number(R.max).toLocaleString('en-IN') : '')} type="number" value=${v.amount} onInput=${set('amount')} error=${err.amount} required />
      <${Field} label=${'Tenure (months)' + (R ? ' · ' + R.min_months + '-' + R.max_months : '')} type="number" value=${v.months} onInput=${set('months')} error=${err.months} required />
      <${Field} label="Monthly income (₹)" type="number" value=${v.income} onInput=${set('income')} error=${err.income} required />
      <${Field} label="mPIN" type="password" inputmode="numeric" value=${v.mpin} onInput=${set('mpin')} error=${err.mpin} required />
      ${e > 0 && html`<p class="hint">Estimated EMI: <b>${fmt(e)}</b> / month · total ${fmt(e * v.months)}</p>`}
      <button class="btn" style="width:100%">Apply for loan</button></form>
    <div class="card"><b style="color:var(--ink)">Your loans</b>
      ${d.loans.map(l => html`<div key=${l.id} style="padding:10px 0;border-bottom:1px solid var(--bd)"><div style="display:flex;justify-content:space-between"><b>#${l.id} ${l.kind[0] + l.kind.slice(1).toLowerCase()} · ${fmt(l.principal)}</b><span class=${'badge ' + badge(l.status)}>${l.status}</span></div>
        <small>${l.rate}% · ${l.months} months · EMI ${fmt(l.emi)}${l.status === 'ACTIVE' ? ' · paid ' + l.paid_emis + '/' + l.months + ' · outstanding ' + fmt(l.outstanding) : ''}</small>
        ${l.status === 'ACTIVE' && html`<div><button class="link" style="margin:4px 0 0" onClick=${() => act(() => API.loanEmi({ id: l.id, mpin: v.mpin }))}>Pay EMI ${fmt(l.emi)} (enter mPIN on the left)</button></div>`}</div>`)}
      ${!d.loans.length && html`<p class="sub">No loans yet.</p>`}</div></div></div>`;
}

/* ---------- Step 12: Services (cheque book, PDF statement) ---------- */
function Services({ toast }) {
  const [list, setList] = useState([]);
  const [v, setV] = useState({ leaves: '25', mpin: '' });
  const [err, setErr] = useState({});
  const load = () => API.cheques().then(setList).catch(() => {});
  useEffect(() => { load(); }, []);
  const submit = async e => { e.preventDefault(); setErr({}); try { const r = await API.chequeRequest(v); toast(r.message); load(); } catch (x) { setErr({ ...x.fields, _: x.message }); } };
  return html`<div><h2>Services</h2><p class="sub">Cheque book and statements.</p><div class="grid">
    <form class="card" onSubmit=${submit}><b style="color:var(--ink)">Request cheque book</b>${err._ && html`<div class="alert" style="margin-top:8px">${err._}</div>`}
      <label class="field" style="margin-top:10px"><span>Leaves</span><select value=${v.leaves} onChange=${e => setV({ ...v, leaves: e.target.value })}><option>25</option><option>50</option></select></label>
      <${Field} label="mPIN" type="password" inputmode="numeric" value=${v.mpin} onInput=${e => setV({ ...v, mpin: e.target.value })} error=${err.mpin} required />
      <button class="btn" style="width:100%">Request</button>
      ${list.map(c => html`<p key=${c.id} class="hint">#${c.id} · ${c.leaves} leaves · ${c.requested} · <b>${c.status}</b></p>`)}</form>
    <div class="card"><b style="color:var(--ink)">Account statement</b><p class="sub">Download a PDF statement of all your transactions.</p>
      <button class="btn" onClick=${() => API.pdf().catch(e => toast(e.message))}>⬇ Download PDF statement</button></div></div></div>`;
}

/* ---------- Step 13: Admin dashboard (bank staff) ---------- */
const cap = k => k[0] + k.slice(1).toLowerCase();
function Admin({ user, onLogout, toast }) {
  const [tab, setTab] = useState('overview');
  const [armed, setArmed] = useState('');
  const [sum, setSum] = useState(null), [cards, setCards] = useState([]), [kyc, setKyc] = useState([]), [loans, setLoans] = useState([]), [chq, setChq] = useState([]), [cust, setCust] = useState([]);
  const [detail, setDetail] = useState(null), [viewer, setViewer] = useState(null), [q, setQ] = useState('');
  const load = () => { API.adminSummary().then(setSum).catch(e => toast(e.message)); API.adminLoans().then(setLoans); API.adminCheques().then(setChq); API.adminCustomers().then(setCust); API.adminKyc().then(setKyc); API.adminCards().then(setCards); };
  const reload = id => { load(); if (id) API.adminCustomer(id).then(setDetail).catch(() => {}); };
  useEffect(() => { load(); }, []);
  const act = async (fn, id) => { try { const r = await fn(); toast(r.message); reload(id); } catch (e) { toast(e.message); } };
  const openDoc = async (d, id) => { try { const url = await API.adminDocUrl(d.id); setViewer({ url, type: d.type, name: d.kind }); reload(id); } catch (e) { toast(e.message); } };
  const openDetail = id => API.adminCustomer(id).then(setDetail).catch(e => toast(e.message));
  const closeViewer = () => { if (viewer) URL.revokeObjectURL(viewer.url); setViewer(null); };
  const Bulk = (key, label, fn, n) => html`<button class=${'btn' + (armed === key ? ' danger' : '')} disabled=${!n} onClick=${() => { if (armed === key) { setArmed(''); act(fn); } else { setArmed(key); setTimeout(() => setArmed(a => a === key ? '' : a), 4000); } }}>${armed === key ? 'Click again to confirm' : label + ' (' + n + ')'}</button>`;
  const Docs = (docs, id) => docs.length ? docs.map(d => html`<button class="link" key=${d.id} style="margin:0 10px 0 0" title=${d.viewed ? 'Reviewed' : 'Not opened yet'} onClick=${() => openDoc(d, id)}>${cap(d.kind)} ${d.viewed ? '✔' : '↗'}</button>`) : html`<small class="err">none uploaded</small>`;
  const pk = kyc.filter(k => k.status === 'PENDING').length, pcard = cards.filter(a => a.status === 'PENDING').length, pl = loans.filter(l => l.status === 'PENDING').length, pc = chq.filter(c => c.status === 'REQUESTED').length;
  const S = (l, x) => html`<div class="card stat"><small>${l}</small><b>${x}</b></div>`;
  const KB = st => html`<span class=${'badge ' + (st === 'VERIFIED' ? 'd' : st === 'REJECTED' ? 'w' : '')}>${st}</span>`;
  const R = (l, v) => html`<div class="kv"><span>${l}</span><b>${v}</b></div>`;
  const ql = q.trim().toLowerCase(), shown = cust.filter(c => !ql || [c.name, c.email, c.phone, String(c.account_no)].some(x => String(x).toLowerCase().includes(ql)));

  const DetailView = d => { const c = d.customer, k = d.kyc, a = d.account, cd = d.card, ad = c.address || {};
    return html`<div><button class="link" style="margin:0 0 10px" onClick=${() => setDetail(null)}>← Back</button><h2>${c.name}</h2>
      <p class="sub">A/c ${a.account_no} · ${a.type} · customer since ${dt(c.joined)} ${k && KB(k.status)}</p>
      <div class="grid">
        <div class="card"><b>Customer</b>${R('Name', c.name)}${R('Email', c.email)}${R('Mobile', k ? '+91 ' + k.phone : '-')}${R('Gender', c.gender === 'F' ? 'Female' : 'Male')}${R('Date of birth', c.birth_date || '-')}
          ${R('Address', [ad.street_address, ad.city, ad.postal_code, ad.country].filter(Boolean).join(', ') || '-')}${R('Login', c.active ? 'Active' : 'FROZEN')}</div>
        <div class="card"><b>KYC & documents</b>${k && R('Status', k.status)}${R('Aadhaar', k ? k.aadhaar_masked : '-')}${R('Aadhaar consent', k ? dt(k.consent_at) : '-')}${R('Mobile verified', k && k.phone_verified ? 'Yes (SMS OTP)' : 'No')}${k && k.note && R('Note', k.note)}
          <div style="margin-top:10px"><small class="hint">Open each document to review it (✔ = reviewed)</small><div style="margin-top:4px">${Docs(d.documents, c.id)}</div></div>
          ${k && k.status !== 'VERIFIED' && html`<div class="actions"><button class="btn" onClick=${() => act(() => API.adminKycDecide({ id: k.id, action: 'approve' }), c.id)}>Approve KYC</button>
            ${k.status === 'PENDING' && html`<button class="btn ghost" onClick=${() => act(() => API.adminKycDecide({ id: k.id, action: 'reject' }), c.id)}>Reject</button>`}</div>`}</div>
        <div class="card"><b>Account</b>${R('Balance', fmt(a.balance))}${R('Interest', a.interest_rate + '% p.a.')}${R('UPI id', a.upi_id || '-')}${R('Withdrawal limit', fmt(a.withdraw_limit))}${R('Total deposits', fmt(a.total_deposits))}
          ${R('Total withdrawals', fmt(a.total_withdrawals))}${R('Interest earned', fmt(a.total_interest))}${R('Transactions', a.transactions)}${R('Bill payments', d.payments_count)}${R('Beneficiaries', d.beneficiaries_count)}</div>
        <div class="card"><b>Debit card</b>${cd ? html`<div>${R('Type', cap(cd.variant || 'CLASSIC'))}${R('Number', cd.masked_number)}${R('Expiry', cd.expiry)}${R('Status', cd.status)}${R('ATM PIN set', cd.pin_set ? 'Yes' : 'No')}${R('Daily ATM limit', fmt(cd.daily_atm_limit))}${R('Online payments', cd.online_enabled ? 'ON' : 'OFF')}</div>`
          : html`<p class="sub">${d.card_application ? 'Application ' + d.card_application.status + ' (' + cap(d.card_application.variant) + ')' + (d.card_application.note ? ' — ' + d.card_application.note : '') : 'No card yet. The customer has not applied.'}</p>
            ${d.card_application && d.card_application.status === 'PENDING' && html`<div class="actions"><button class="btn" onClick=${() => act(() => API.adminCardDecide({ id: d.card_application.id, action: 'approve' }), c.id)}>Approve card</button><button class="btn ghost" onClick=${() => act(() => API.adminCardDecide({ id: d.card_application.id, action: 'reject' }), c.id)}>Reject</button></div>`}`}</div></div>
      <div class="grid" style="margin-top:16px">
        <div class="card"><b>Fixed deposits (${d.fixed_deposits.length})</b>${d.fixed_deposits.map(f => html`<div key=${f.id} class="kv"><span>#${f.id} · ${f.rate}% · ${f.months}m · ${f.status}</span><b>${fmt(f.principal)}</b></div>`)}${!d.fixed_deposits.length && html`<p class="sub">None</p>`}</div>
        <div class="card"><b>Loans (${d.loans.length})</b>${d.loans.map(l => html`<div key=${l.id} class="kv"><span>#${l.id} ${cap(l.kind)} · EMI ${fmt(l.emi)} · ${l.status}</span><b>${fmt(l.principal)}</b></div>`)}${!d.loans.length && html`<p class="sub">None</p>`}</div>
        <div class="card"><b>Cheque books (${d.cheque_requests.length})</b>${d.cheque_requests.map(c => html`<div key=${c.id} class="kv"><span>#${c.id} · ${c.requested}</span><b>${c.leaves} leaves · ${c.status}</b></div>`)}${!d.cheque_requests.length && html`<p class="sub">None</p>`}</div></div>
      <div class="card wrap" style="margin-top:16px"><b>Recent transactions</b><table class="tbl"><thead><tr><th>Date</th><th>Type</th><th>Description</th><th>Channel</th><th>Amount</th><th>Balance</th></tr></thead><tbody>
        ${d.recent_transactions.map(t => html`<tr key=${t.id}><td>${dt(t.timestamp)}</td><td>${t.type}</td><td>${t.description}</td><td>${t.channel}</td><td>${fmt(t.amount)}</td><td>${fmt(t.balance_after)}</td></tr>`)}</tbody></table>
        ${!d.recent_transactions.length && html`<p class="sub">No transactions yet.</p>`}</div></div>`; };

  const T = [['overview', 'Overview'], ['kyc', 'KYC approvals'], ['customers', 'Customers'], ['cards', 'Card approvals'], ['loans', 'Loan approvals'], ['cheques', 'Cheque books']];
  return html`<div><div class="top"><div class="brand">Secure<span>Bank</span> <small class="badge">ADMIN</small></div>
    <div class="tabs">${T.map(([k, l]) => html`<button class=${tab === k && !detail ? 'on' : ''} onClick=${() => { setTab(k); setDetail(null); }}>${l}</button>`)}</div>
    <button class="btn ghost" onClick=${onLogout}>Logout</button></div>
    <main>${detail ? DetailView(detail) : html`<div>
      ${tab === 'overview' && sum && html`<div><h2>Bank overview</h2><p class="sub">Live numbers across all customers.</p><div class="grid">
        ${S('Accounts opened', sum.accounts_opened)}${S('Opened today', sum.new_accounts_today)}${S('KYC pending', sum.kyc_pending)}${S('KYC verified', sum.kyc_verified)}${S('KYC rejected', sum.kyc_rejected)}${S('Debit cards issued', sum.cards_issued)}${S('Card applications pending', sum.card_applications_pending)}
        ${S('Total deposits', fmt(sum.total_deposits))}${S('Transactions today', sum.transactions_today)}${S('Volume today', fmt(sum.volume_today))}${S('Pending loans', sum.pending_loans)}${S('Active loans', sum.active_loans)}
        ${S('Cheque requests', sum.pending_cheques)}${S('Blocked cards', sum.blocked_cards)}${S('FD book', fmt(sum.fd_total))}${S('Bill payments', sum.bill_payments)}</div></div>`}
      ${tab === 'kyc' && html`<div><h2>KYC approvals</h2><p class="sub">Open the Aadhaar document to review it, then approve. Approved customers can then apply for a debit card. Approve-all only approves customers whose Aadhaar document has been opened.</p>
        <div class="actions">${Bulk('kyc', 'Approve all reviewed', () => API.adminKycApproveAll(), pk)}</div>
        <div class="card wrap"><table class="tbl"><thead><tr><th>Name</th><th>Mobile</th><th>Aadhaar</th><th>Documents</th><th>Status</th><th></th></tr></thead><tbody>
        ${kyc.map(k => html`<tr key=${k.id}><td>${k.name}<br /><small class="hint">${k.email}</small></td><td>${k.phone}</td><td>${k.aadhaar_masked}</td><td>${Docs(k.docs)}</td>
          <td>${KB(k.status)}${k.note && html`<br /><small class="hint">${k.note}</small>`}</td>
          <td><button class="link" style="margin:0 8px 0 0" onClick=${() => openDetail(k.user_id || k.id)}>Details</button>${k.status !== 'VERIFIED' && html`<button class="link" style="margin:0 8px 0 0" onClick=${() => act(() => API.adminKycDecide({ id: k.id, action: 'approve' }))}>Approve</button>`}
            ${k.status === 'PENDING' && html`<button class="link" style="margin:0" onClick=${() => act(() => API.adminKycDecide({ id: k.id, action: 'reject' }))}>Reject</button>`}</td></tr>`)}</tbody></table>
        ${!kyc.length && html`<p class="sub">No customers yet.</p>`}</div></div>`}
      ${tab === 'customers' && html`<div><h2>Customers (${cust.length})</h2><p class="sub">Search and open any account to see every detail.</p>
        <div class="filters"><input placeholder="Search name, email, mobile or account no…" value=${q} onInput=${e => setQ(e.target.value)} style="min-width:280px" /></div>
        <div class="card wrap"><table class="tbl"><thead><tr><th>Name</th><th>Mobile</th><th>A/c</th><th>Balance</th><th>KYC</th><th>Card</th><th>Opened</th><th></th></tr></thead><tbody>
        ${shown.map(c => html`<tr key=${c.id}><td>${c.name}<br /><small class="hint">${c.email}</small></td><td>${c.phone}</td><td>${c.account_no}</td><td>${fmt(c.balance)}</td><td>${KB(c.kyc_status)}</td><td>${c.card_status === 'ISSUED' ? 'Issued' : c.card_status === 'PENDING' ? 'Applied' : '—'}</td><td>${c.opened}</td>
          <td><button class="link" style="margin:0 8px 0 0" onClick=${() => openDetail(c.id)}>Details</button><button class="link" style="margin:0" onClick=${() => act(() => API.adminToggle({ id: c.id }))}>${c.active ? 'Freeze' : 'Unfreeze'}</button></td></tr>`)}</tbody></table>
        ${!shown.length && html`<p class="sub">No matching customers.</p>`}</div></div>`}
      ${tab === 'cards' && html`<div><h2>Debit card applications</h2><p class="sub">Customers apply for a card; the card is created and ATM service starts only when you approve.</p>
        <div class="actions">${Bulk('cards', 'Approve all pending', () => API.adminCardsApproveAll(), pcard)}</div>
        <div class="card wrap"><table class="tbl"><thead><tr><th>Customer</th><th>Mobile</th><th>A/c</th><th>Card type</th><th>Applied</th><th>Status</th><th></th></tr></thead><tbody>
        ${cards.map(a => html`<tr key=${a.id}><td>${a.name}<br /><small class="hint">${a.email}</small></td><td>${a.phone}</td><td>${a.account_no}</td><td>${cap(a.variant)}</td><td>${a.applied}</td>
          <td><span class=${'badge ' + (a.status === 'APPROVED' ? 'd' : a.status === 'REJECTED' ? 'w' : '')}>${a.status}</span>${a.note && html`<br /><small class="hint">${a.note}</small>`}</td>
          <td><button class="link" style="margin:0 8px 0 0" onClick=${() => openDetail(a.user_id)}>Details</button>${a.status === 'PENDING' && html`<span><button class="link" style="margin:0 8px 0 0" onClick=${() => act(() => API.adminCardDecide({ id: a.id, action: 'approve' }))}>Approve</button><button class="link" style="margin:0" onClick=${() => act(() => API.adminCardDecide({ id: a.id, action: 'reject' }))}>Reject</button></span>`}</td></tr>`)}</tbody></table>
        ${!cards.length && html`<p class="sub">No card applications yet.</p>`}</div></div>`}
      ${tab === 'loans' && html`<div><h2>Loan applications</h2><div class="actions">${Bulk('loans', 'Approve all pending', () => API.adminLoansApproveAll(), pl)}</div>
        <div class="card wrap"><table class="tbl"><thead><tr><th>#</th><th>A/c</th><th>Type</th><th>Amount</th><th>EMI</th><th>Income</th><th>Status</th><th></th></tr></thead><tbody>
        ${loans.map(l => html`<tr key=${l.id}><td>${l.id}</td><td>${l.account_no}</td><td>${l.kind}</td><td>${fmt(l.principal)}</td><td>${fmt(l.emi)}</td><td>${fmt(l.income)}</td><td><span class=${'badge ' + (l.status === 'ACTIVE' ? 'd' : l.status === 'REJECTED' ? 'w' : '')}>${l.status}</span></td>
          <td>${l.status === 'PENDING' && html`<span><button class="link" onClick=${() => act(() => API.adminDecide({ id: l.id, action: 'approve' }))}>Approve</button> <button class="link" onClick=${() => act(() => API.adminDecide({ id: l.id, action: 'reject' }))}>Reject</button></span>`}</td></tr>`)}</tbody></table>
        ${!loans.length && html`<p class="sub">No applications.</p>`}</div></div>`}
      ${tab === 'cheques' && html`<div><h2>Cheque book requests</h2><div class="actions">${Bulk('chq', 'Dispatch all pending', () => API.adminChequesDispatchAll(), pc)}</div><div class="card wrap"><table class="tbl"><thead><tr><th>#</th><th>A/c</th><th>Leaves</th><th>Requested</th><th>Status</th><th></th></tr></thead><tbody>
        ${chq.map(c => html`<tr key=${c.id}><td>${c.id}</td><td>${c.account_no}</td><td>${c.leaves}</td><td>${c.requested}</td><td>${c.status}</td><td>${c.status === 'REQUESTED' && html`<button class="link" onClick=${() => act(() => API.adminDispatch({ id: c.id }))}>Mark dispatched</button>`}</td></tr>`)}</tbody></table>
        ${!chq.length && html`<p class="sub">No requests.</p>`}</div></div>`}</div>`}</main>
    ${viewer && html`<div class="modal" onClick=${closeViewer}><div class="card viewer" style="max-width:780px;width:100%" onClick=${e => e.stopPropagation()}><div style="display:flex;justify-content:space-between;margin-bottom:8px"><b style="color:var(--ink)">${cap(viewer.name)} document</b><button class="link" style="margin:0" onClick=${closeViewer}>Close ✕</button></div>
      ${viewer.type === 'application/pdf' ? html`<iframe src=${viewer.url} title="document"></iframe>` : html`<img src=${viewer.url} alt="document" />`}</div></div>`}</div>`;
}

/* ---------- KYC documents (customer) ---------- */
function KycDocs({ user, toast, refresh }) {
  const [d, setD] = useState({ documents: [], kyc_status: user.kyc_status });
  const [kind, setKind] = useState('AADHAAR');
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => API.docs().then(setD).catch(() => {});
  useEffect(() => { load(); }, []);
  const L = { AADHAAR: 'Aadhaar card', PAN: 'PAN card', PHOTO: 'Passport photo' };
  const up = async e => { e.preventDefault(); if (!file) return toast('Choose a file first.'); setBusy(true);
    try { const r = await API.uploadDoc(kind, file); toast(r.message); setFile(null); e.target.reset(); await refresh(); load(); } catch (x) { toast(x.message); } setBusy(false); };
  const locked = d.kyc_status === 'VERIFIED';
  return html`<div class="card" style="max-width:560px;margin-top:16px"><b style="color:var(--ink)">KYC documents</b>
    <p class="sub" style="margin-bottom:8px">Status: <span class=${'badge ' + (d.kyc_status === 'VERIFIED' ? 'd' : d.kyc_status === 'REJECTED' ? 'w' : '')}>${d.kyc_status}</span>${d.kyc_note ? ' · ' + d.kyc_note : ''}</p>
    ${d.documents.map(x => html`<div key=${x.id} style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--bd)"><span>${L[x.kind]} · ${x.name}</span><small class="hint">${Math.max(1, Math.round(x.size / 1024))} KB</small></div>`)}
    ${!d.documents.length && html`<p class="hint">No documents uploaded yet.</p>`}
    ${!locked && html`<form onSubmit=${up} style="margin-top:12px"><div class="row2"><label class="field"><span>Document</span><select value=${kind} onChange=${e => setKind(e.target.value)}>${Object.keys(L).map(k => html`<option value=${k}>${L[k]}</option>`)}</select></label>
      <label class="field"><span>File (JPG/PNG/PDF, max 2 MB)</span><input type="file" accept=".jpg,.jpeg,.png,.pdf,image/jpeg,image/png,application/pdf" onChange=${e => setFile(e.target.files[0] || null)} /></label></div>
      <button class="btn" disabled=${busy}>${busy ? 'Uploading…' : 'Upload / replace'}</button></form>`}</div>`;
}

/* ---------- Root ---------- */
function App() {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);
  const [page, setPage] = useState('dashboard');
  const [msg, setMsg] = useState('');
  const [reveal, setReveal] = useState(null);
  const toast = useCallback(m => { setMsg(m); setTimeout(() => setMsg(''), 3200); }, []);
  const refresh = useCallback(async () => { try { setUser(await API.me()); } catch (e) { setUser(null); } }, []);
  useEffect(() => { (API.isAuthed() ? refresh() : Promise.resolve()).then(() => setReady(true)); }, []);
  if (!ready) return html`<p style="padding:40px">Loading…</p>`;
  if (!user) return html`<${Auth} onAuth=${r => { setPage('dashboard'); if (r && r.registered) setReveal(true); if (r && r.failed && r.failed.length) toast('Some documents could not be uploaded: ' + r.failed.join(', ') + '. Upload them from Profile.'); refresh(); }} />`;
  if (user.is_staff) return html`<div><${Admin} user=${user} toast=${toast} onLogout=${() => { API.logout(); setUser(null); }} />${msg && html`<div class="toast">${msg}</div>`}</div>`;
  const NAV = [['dashboard', 'Dashboard'], ['deposit', 'Deposit'], ['withdraw', 'Withdraw'], ['transfer', 'Transfer'], ['payments', 'Pay & Recharge'], ['loans', 'Loans'], ['history', 'Transactions'], ['card', 'Card & ATM'], ['fd', 'Fixed Deposit'], ['whatsapp', 'WhatsApp'], ['services', 'Services'], ['profile', 'Profile']];
  const body = page === 'dashboard' ? html`<${Dashboard} user=${user} go=${setPage} toast=${toast} refresh=${refresh} />`
    : page === 'history' ? html`<${History} toast=${toast} />`
    : page === 'card' ? html`<${CardPage} user=${user} toast=${toast} refresh=${refresh} />`
    : page === 'fd' ? html`<${FDPage} user=${user} toast=${toast} refresh=${refresh} />`
    : page === 'whatsapp' ? html`<${WhatsApp} user=${user} refresh=${refresh} />`
    : page === 'payments' ? html`<${Payments} user=${user} toast=${toast} refresh=${refresh} />`
    : page === 'loans' ? html`<${Loans} user=${user} toast=${toast} refresh=${refresh} />`
    : page === 'services' ? html`<${Services} toast=${toast} />`
    : page === 'profile' ? html`<div><${Profile} user=${user} /><${KycDocs} user=${user} toast=${toast} refresh=${refresh} /></div>`
    : html`<${Money} kind=${page} user=${user} toast=${toast} refresh=${refresh} go=${setPage} />`;
  return html`<div>
    <div class="top"><div class="brand">Secure<span>Bank</span></div>
      <div class="tabs">${NAV.map(([k, l]) => html`<button class=${page === k ? 'on' : ''} onClick=${() => setPage(k)}>${l}</button>`)}</div>
      <button class="btn ghost" onClick=${() => { API.logout(); setUser(null); }}>Logout</button></div>
    <main>${user.kyc_status === 'PENDING' && html`<div class="banner">⏳ Your KYC documents are under review. You can view your account, but deposits, withdrawals, transfers, payments and your debit card unlock only after the bank approves. <button class="link" style="margin:0" onClick=${() => setPage('profile')}>Check / upload documents</button></div>`}
      ${user.kyc_status === 'VERIFIED' && user.card_issued === false && user.card_application !== 'PENDING' && html`<div class="banner info">💳 You do not have a debit card yet. <button class="link" style="margin:0" onClick=${() => setPage('card')}>Apply for one in Card & ATM →</button></div>`}
      ${user.kyc_status === 'REJECTED' && html`<div class="banner bad">❌ KYC rejected: ${user.kyc_note || 'documents not valid'}. Upload correct documents from Profile.</div>`}${body}</main><${Assistant} go=${setPage} />${msg && html`<div class="toast">${msg}</div>`}${reveal && html`<${CardReveal} onClose=${() => { setReveal(null); setPage('dashboard'); }} />`}</div>`;
}
ReactDOM.createRoot(document.getElementById('root')).render(html`<${App} />`);
