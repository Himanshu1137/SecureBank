/* API layer. window.SB_CONFIG.mode = 'live' (Django REST) | 'mock' (browser-only demo bank). */
(function () {
  const cfg = window.SB_CONFIG || { mode: 'live', base: '' };
  const MIN = 10;
  const fail = (m, fields) => { const e = new Error(m); e.fields = fields || {}; throw e; };

  /* ---------------- LIVE: talks to Django ---------------- */
  let token = null;
  try { token = localStorage.getItem('sb_token'); } catch (e) {}
  const setToken = t => { token = t; try { t ? localStorage.setItem('sb_token', t) : localStorage.removeItem('sb_token'); } catch (e) {} };
  async function req(path, body) {
    const r = await fetch((cfg.base || '') + '/api/' + path, {
      method: body ? 'POST' : 'GET',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) },
      body: body ? JSON.stringify(body) : undefined
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { if (r.status === 401 && token && j.error === 'Please login again.') setToken(null); fail(j.error || 'Request failed', j.fields); }
    return j;
  }
  const live = {
    isAuthed: () => !!token,
    accountTypes: () => req('account-types/'),
    login: async (email, password) => { const r = await req('login/', { email, password }); if (r.otp_required) return r; setToken(r.token); return null; },
    loginVerify: async (otp_token, code) => setToken((await req('login/verify/', { otp_token, code })).token),
    register: async d => { const r = await req('register/', d); setToken(r.token); return r.card; },
    otpSend: phone => req('otp/send/', { phone }), otpVerify: (phone, code) => req('otp/verify/', { phone, code }),
    card: () => req('card/'), setPin: d => req('card/set-pin/', d), cardAction: d => req('card/action/', d), atm: d => req('atm/', d),
    fdList: () => req('fd/'), fdOpen: d => req('fd/open/', d), fdClose: d => req('fd/close/', d),
    whatsapp: message => req('whatsapp/simulate/', { message }).then(r => r.reply),
    logout: () => setToken(null),
    me: () => req('me/'),
    transactions: (p = {}) => req('transactions/?' + new URLSearchParams(p)),
    deposit: d => req('deposit/', d), withdraw: d => req('withdraw/', d),
    transfer: d => req('transfer/', d),
    beneficiaries: () => req('beneficiaries/'), beneficiaryAdd: d => req('beneficiaries/add/', d), beneficiaryDelete: d => req('beneficiaries/delete/', d),
    billers: () => req('billers/'), payments: () => req('payments/'), pay: d => req('pay/', d),
    loans: () => req('loans/'), loanApply: d => req('loans/apply/', d), loanEmi: d => req('loans/emi/', d),
    cheques: () => req('cheque/'), chequeRequest: d => req('cheque/request/', d),
    pdf: async () => { const r = await fetch((cfg.base || '') + '/api/statement.pdf', { headers: { Authorization: 'Bearer ' + token } });
      if (!r.ok) fail('Could not download the statement.'); const a = document.createElement('a'); a.href = URL.createObjectURL(await r.blob()); a.download = 'securebank-statement.pdf'; a.click(); },
    uploadDoc: async (kind, file) => { const fd = new FormData(); fd.append('kind', kind); fd.append('file', file);
      const r = await fetch((cfg.base || '') + '/api/documents/upload/', { method: 'POST', headers: token ? { Authorization: 'Bearer ' + token } : {}, body: fd });
      const j = await r.json().catch(() => ({})); if (!r.ok) fail(j.error || 'Upload failed', j.fields); return j; },
    docs: () => req('documents/'),
    adminKyc: s => req('admin/kyc/' + (s ? '?status=' + s : '')), adminKycDecide: d => req('admin/kyc/decide/', d), adminKycApproveAll: () => req('admin/kyc/approve-all/', {}),
    adminLoansApproveAll: () => req('admin/loans/approve-all/', {}), adminChequesDispatchAll: () => req('admin/cheques/dispatch-all/', {}),
    adminDocUrl: async id => { const r = await fetch((cfg.base || '') + '/api/admin/documents/' + id + '/', { headers: { Authorization: 'Bearer ' + token } });
      if (!r.ok) fail('Could not open the document.'); return URL.createObjectURL(await r.blob()); },
    cardApply: d => req('card/apply/', d), adminCards: s => req('admin/cards/' + (s ? '?status=' + s : '')), adminCardDecide: d => req('admin/cards/decide/', d), adminCardsApproveAll: () => req('admin/cards/approve-all/', {}),
    adminCustomer: id => req('admin/customers/' + id + '/'),
    adminSummary: () => req('admin/summary/'), adminLoans: s => req('admin/loans/' + (s ? '?status=' + s : '')), adminDecide: d => req('admin/loans/decide/', d),
    adminCheques: () => req('admin/cheques/'), adminDispatch: d => req('admin/cheques/dispatch/', d),
    adminCustomers: () => req('admin/customers/'), adminToggle: d => req('admin/customers/toggle/', d),
    assistant: (m, h) => req('assistant/', { message: m, history: h })
  };

  /* ---------------- MOCK: whole bank in the browser ---------------- */
  const TYPES = [
    { id: 1, name: 'Savings', annual_interest_rate: 4, maximum_withdrawal_amount: 50000, interest_calculation_per_year: 4 },
    { id: 2, name: 'Current', annual_interest_rate: 0, maximum_withdrawal_amount: 200000, interest_calculation_per_year: 1 },
    { id: 3, name: 'Fixed Saver', annual_interest_rate: 7, maximum_withdrawal_amount: 20000, interest_calculation_per_year: 2 }
  ];
  const KEY = 'sb_demo_v6';
  let db = null;
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(db)); } catch (e) {} };
  function load() {
    if (db) return db;
    try { db = JSON.parse(localStorage.getItem(KEY)); } catch (e) {}
    if (!db) { db = { users: [], txs: [], fds: [], otps: {}, payees: [], docs: [], cardApps: [], pays: [], loans: [], cheques: [], session: null }; seedDemo(); save(); }
    return db;
  }
  const r2 = n => Math.round(n * 100) / 100;
  function newUser(d) {
    const u = { id: db.users.length + 1, ...d, balance: 0, joined: new Date().toISOString() };
    u.account_no = 1000000000 + u.id; db.users.push(u); return u;
  }
  function tx(u, amount, type, description, ago, channel) {
    u.balance = r2(u.balance + (type === 1 || type === 3 ? amount : -amount));
    db.txs.push({ id: db.txs.length + 1, acc: u.account_no, amount, type, balance_after: u.balance, description, channel: channel || 'APP',
      timestamp: new Date(Date.now() - (ago || 0) * 864e5).toISOString() });
  }
  function seedDemo() {
    const u = newUser({ first_name: 'Aarav', last_name: 'Sharma', email: 'demo@securebank.in', password: 'Demo@1234', account_type: 1,
      gender: 'M', birth_date: '1998-05-14', address: { street_address: '12 MG Road', city: 'Lucknow', postal_code: 226001, country: 'India' } });
    [[20, 25000, 1, 'Salary credit'], [14, 3200, 2, 'ATM withdrawal'], [9, 1500, 1, 'Refund'], [3, 800, 2, 'Groceries']].forEach(a => tx(u, a[1], a[2], a[3], a[0]));
    Object.assign(u, { phone: '9876543210', aadhaar_last4: '9012', mpin: '2468',
      card: { number: '6521509377517435', expiry: '10/31', cvv: '185', pin: '2580', status: 'ACTIVE', wrong: 0, limit: 20000, online: true } });
  }
  function cur() { load(); const u = db.users.find(x => x.id === db.session); if (!u) fail('Please login again.'); return u; }
  const typeOf = u => TYPES.find(t => t.id === u.account_type);
  const view = u => { const { password, mpin, card, ...rest } = u; return { ...rest, account_type: typeOf(u), aadhaar_masked: 'XXXX XXXX ' + u.aadhaar_last4,
    upi_id: u.phone + '@securebank', ifsc: 'SECB0000001', kyc_status: u.kyc_status || 'VERIFIED', kyc_note: u.kyc_note || '', card_issued: !!u.card, card_application: (appOf(u) || {}).status || null, is_staff: false }; };
  function amt(v, min) {
    const a = r2(parseFloat(v));
    if (!(a > 0)) fail('Enter a valid amount.', { amount: 'Enter a valid amount.' });
    if (a < min) fail('Minimum amount is ₹' + min + '.', { amount: 'Minimum is ₹' + min });
    return a;
  }
  const out = (u, msg, t) => { save(); return { message: msg, transaction: t }; };
  const inr = n => '₹' + Number(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const delay = v => new Promise(res => setTimeout(() => res(v), 250));
  const wrap = fn => (...a) => new Promise((res, rej) => setTimeout(() => { try { res(fn(...a)); } catch (e) { rej(e); } }, 250));

  const mock = {
    isAuthed: () => { load(); return db.session != null; },
    accountTypes: wrap(() => TYPES),
    login: wrap((email, password) => {
      load(); const u = db.users.find(x => x.email === String(email).trim().toLowerCase());
      if (!u || u.password !== password) fail('Invalid email or password.');
      db.session = u.id; save();
    }),
    logout: () => { load(); db.session = null; save(); },
    me: wrap(() => { load(); return db.session === 'admin' ? { is_staff: true, first_name: 'Bank', last_name: 'Admin', email: 'admin@securebank.in' } : view(cur()); }),
    transactions: wrap((p = {}) => {
      const u = cur(); const q = (p.q || '').toLowerCase();
      return db.txs.filter(t => t.acc === u.account_no && (!p.type || t.type === Number(p.type)) && (!q || t.description.toLowerCase().includes(q)))
        .slice().reverse();
    }),
    deposit: wrap(d => { const u = cur(); needKyc(u); const a = amt(d.amount, MIN); tx(u, a, 1, d.note || 'Cash deposit'); return out(u, inr(a) + ' deposited successfully.'); }),
    withdraw: wrap(d => {
      const u = cur(); needKyc(u); const a = amt(d.amount, MIN), lim = typeOf(u).maximum_withdrawal_amount;
      if (a > lim) fail('Maximum withdrawal is ' + inr(lim) + '.', { amount: 'Max ' + inr(lim) });
      if (a > u.balance) fail('Insufficient balance.', { amount: 'Insufficient balance' });
      tx(u, a, 2, d.note || 'Cash withdrawal'); return out(u, inr(a) + ' withdrawn successfully.');
    }),
    assistantRule: m => {
      const u = cur(), t = typeOf(u), q = String(m).toLowerCase(), has = (...w) => w.some(x => q.includes(x));
      const mine = db.txs.filter(x => x.acc === u.account_no).reverse();
      if (has('card', 'atm', 'pin')) return { message: 'Manage your debit card, ATM PIN, limits and block/unblock from the Card & ATM page.', action: 'card' };
      if (has('fd', 'fixed deposit', 'invest')) return { message: 'Open or close a Fixed Deposit (6.00% - 7.25% p.a.) from the Fixed Deposit page.', action: 'fd' };
      if (has('whatsapp')) return { message: 'You can bank on WhatsApp too: send BALANCE, STATEMENT or SEND 500 TO <mobile> to the bank number.', action: 'whatsapp' };
      if (has('upi', 'ifsc')) return { message: 'Your UPI id is ' + u.phone + '@securebank and IFSC is SECB0000001.' };
      if (has('balance', 'how much', 'available', 'baki', 'paisa', 'kitna')) return { message: 'Your available balance is ' + inr(u.balance) + '.' };
      if (has('account number', 'account no')) return { message: 'Your account number is ' + u.account_no + '. Never share it publicly.' };
      if (has('interest', 'rate', 'saving')) return { message: 'Your ' + t.name + ' account earns ' + t.annual_interest_rate + '% per year, calculated ' + t.interest_calculation_per_year + ' time(s) a year.' };
      if (has('transfer', 'send money')) return { message: 'You can send money to any SecureBank account number from the Transfer page.', action: 'transfer' };
      if (has('deposit', 'add money')) return { message: 'Use the Deposit page to add money. Minimum deposit is ₹10.', action: 'deposit' };
      if (has('withdraw', 'cash')) return { message: 'You can withdraw up to ' + inr(t.maximum_withdrawal_amount) + ' per transaction, within your balance of ' + inr(u.balance) + '.', action: 'withdraw' };
      if (has('transaction', 'history', 'statement', 'recent'))
        return { message: mine.length ? 'Latest transactions: ' + mine.slice(0, 5).map(x => ['', 'Deposit +', 'Withdrawal -', 'Interest +'][x.type] + inr(x.amount)).join(' • ') : 'No transactions yet.', action: 'history' };
      if (has('summary', 'overview', 'spending', 'activity')) {
        const s = k => mine.filter(x => x.type === k).reduce((a, x) => a + x.amount, 0);
        return { message: 'Balance ' + inr(u.balance) + '; total deposits ' + inr(s(1)) + '; total withdrawals ' + inr(s(2)) + '; ' + mine.length + ' transaction(s).', action: 'history' };
      }
      if (has('security', 'safe', 'fraud', 'otp', 'password')) return { message: 'Never share your password or OTP, double-check account numbers before transferring, and report any unknown transaction immediately.' };
      return { message: 'I can help with balance, account number, interest, transfers, deposits, withdrawals, transactions, summary and security. Try: “What is my balance?”' };
    },
    assistant: m => new Promise(res => setTimeout(() => res(mock.assistantRule(m)), 250))
  };

  /* ---- India features (mock): OTP, Aadhaar KYC, card + ATM, UPI transfer, FD, WhatsApp ---- */
  const VD = ['0123456789', '1234067895', '2340178956', '3401289567', '4012395678', '5987604321', '6598710432', '7659821043', '8765932104', '9876543210'];
  const VP = ['0123456789', '1576283094', '5803796142', '8916043527', '9453126870', '4286573901', '2793806415', '7046913258'];
  const verhoeff = n => { let c = 0; [...n].reverse().forEach((ch, i) => { c = +VD[c][+VP[i % 8][+ch]]; }); return c === 0; };
  const okAadhaar = x => /^[2-9]\d{11}$/.test(x) && verhoeff(x);
  const luhn = b => { let t = 0; [...b].reverse().forEach((c, i) => { const n = +c * (i % 2 === 0 ? 2 : 1); t += n > 9 ? n - 9 : n; }); return String((10 - t % 10) % 10); };
  const rnd = n => Array.from({ length: n }, () => Math.floor(Math.random() * 10)).join('');
  const newCard = variant => { const b = '652150' + rnd(9), y = new Date().getFullYear() + 5;
    return { number: b + luhn(b), expiry: String(new Date().getMonth() + 1).padStart(2, '0') + '/' + String(y).slice(2), cvv: rnd(3), pin: '', status: 'ACTIVE', wrong: 0, limit: variant === 'PLATINUM' ? 50000 : 20000, online: true, variant: variant || 'CLASSIC' }; };
  const ph = v => String(v || '').replace(/\D/g, '').slice(-10);
  const mpinOk = (u, m) => { if (String(m) !== u.mpin) fail('Incorrect mPIN.', { mpin: 'Incorrect mPIN' }); };
  const noCard = u => { if (!u.card) fail('You do not have a debit card yet. Apply for one in Card & ATM; it works after the bank approves.'); };
  const appOf = u => db.cardApps.filter(a => a.user === u.id).slice(-1)[0] || null;
  const cardView = u => { if (!u.card) return { issued: false, application: appOf(u) }; const c = u.card; const out = { issued: true, variant: c.variant || 'CLASSIC', masked_number: 'XXXX XXXX XXXX ' + c.number.slice(-4), number: c.number, expiry: c.expiry, status: c.status, pin_set: !!c.pin, daily_atm_limit: c.limit, online_enabled: c.online }; if (u.cardReveal) { out.cvv = u.cardReveal; u.cardReveal = null; save(); } return out; };
  const weak = p => !/^\d{4}$/.test(p) || /^(\d)\1{3}$/.test(p) || ['1234', '4321', '0123'].includes(p);
  const fdRate = m => m <= 6 ? 6 : m <= 12 ? 6.8 : m <= 24 ? 7 : 7.25;
  const findTarget = id => { load(); let s = String(id).trim().toLowerCase().replace('@securebank', ''); if (!/^\d+$/.test(s)) return null;
    return db.users.find(x => (s.length === 10 && '6789'.includes(s[0])) ? x.phone === s : String(x.account_no) === s); };
  function xfer(u, to, a, note, ch) {
    needKyc(u);
    if ((to.kyc_status || 'VERIFIED') !== 'VERIFIED') fail('The recipient account is not active yet.', { to_account_no: 'Recipient not active' });
    if (to === u) fail('You cannot transfer to your own account.', { to_account_no: 'Choose another account' });
    if (a > typeOf(u).maximum_withdrawal_amount) fail('Amount exceeds your per-transfer limit.', { amount: 'Over limit' });
    if (a > u.balance) fail('Insufficient balance.', { amount: 'Insufficient balance' });
    const n = note ? ' · ' + note : '';
    tx(u, a, 2, 'Transfer to A/c ' + to.account_no + n, 0, ch); tx(to, a, 1, 'Transfer from A/c ' + u.account_no + n, 0, ch); save();
  }
  let waPending = null;
  Object.assign(mock, {
    otpSend: wrap(phone => { load(); const p = ph(phone);
      if (!/^[6-9]\d{9}$/.test(p)) fail('Enter a valid 10-digit Indian mobile number.', { phone: 'Invalid mobile number' });
      if (db.users.some(x => x.phone === p)) fail('This mobile number is already registered.', { phone: 'Already registered' });
      db.otps[p] = rnd(6); save(); return { message: 'OTP sent to +91 ' + p.slice(0, 2) + 'XXXXXX' + p.slice(-2), dev_otp: db.otps[p] }; }),
    otpVerify: wrap((phone, code) => { load(); const p = ph(phone); if (!db.otps[p] || db.otps[p] !== String(code).trim()) fail('Incorrect OTP.', { code: 'Incorrect OTP' });
      delete db.otps[p]; save(); return { phone_token: 'ok:' + p, message: 'Mobile number verified.' }; }),
    register: wrap(d => {
      load(); const f = {}, email = String(d.email || '').trim().toLowerCase(), p = ph(d.phone), aad = String(d.aadhaar || '').replace(/\s/g, '');
      if (!d.first_name) f.first_name = 'Required'; if (!d.last_name) f.last_name = 'Required';
      if (!/^\S+@\S+\.\S+$/.test(email)) f.email = 'Enter a valid email'; else if (db.users.some(x => x.email === email)) f.email = 'Email already registered';
      if (String(d.password || '').length < 8) f.password = 'At least 8 characters';
      if (d.phone_token !== 'ok:' + p) f.phone = 'Verify your mobile number with OTP';
      if (!okAadhaar(aad)) f.aadhaar = 'Enter a valid 12-digit Aadhaar number';
      if (d.consent !== true) f.consent = 'Consent is required to use your Aadhaar for KYC';
      if (!/^\d{4,6}$/.test(String(d.mpin))) f.mpin = 'mPIN must be 4-6 digits';
      if (!d.birth_date || new Date(d.birth_date) > new Date(Date.now() - 18 * 365.25 * 864e5)) f.birth_date = 'You must be 18 or older';
      if (!d.street_address) f.street_address = 'Required'; if (!d.city) f.city = 'Required';
      if (!/^\d{6}$/.test(String(d.postal_code))) f.postal_code = 'PIN must be 6 digits';
      if (Object.keys(f).length) fail('Please correct the highlighted fields.', f);
      const u = newUser({ first_name: d.first_name, last_name: d.last_name, email, password: d.password, account_type: Number(d.account_type), gender: d.gender,
        birth_date: d.birth_date, phone: p, kyc_status: 'PENDING', aadhaar_last4: aad.slice(-4), mpin: String(d.mpin), card: null,
        address: { street_address: d.street_address, city: d.city, postal_code: d.postal_code, country: 'India' } });
      db.session = u.id; save(); return { registered: true };
    }),
    transfer: wrap(d => { const u = cur(), a = amt(d.amount, MIN), to = findTarget(d.to_account_no);
      if (!to) fail('Recipient not found. Use account number, mobile number or UPI id.', { to_account_no: 'Recipient not found' });
      if (a > 10000) {
        if (!d.otp) { db.txOtp = rnd(6); save(); return { otp_required: true, message: 'OTP required for transfers above ₹10,000. OTP sent to +91 ' + u.phone.slice(0, 2) + 'XXXXXX' + u.phone.slice(-2), dev_otp: db.txOtp }; }
        if (String(d.otp).trim() !== db.txOtp) fail('Incorrect OTP.', { code: 'Incorrect OTP' }); db.txOtp = null;
      }
      xfer(u, to, a, d.note, 'APP'); return { message: inr(a) + ' sent to ' + to.first_name + ' (A/c ' + to.account_no + ').' }; }),
    card: wrap(() => cardView(cur())),
    setPin: wrap(d => { const u = cur(); noCard(u); mpinOk(u, d.mpin); if (weak(String(d.pin))) fail('Choose a 4-digit PIN that is not obvious (no 1111 / 1234).', { pin: 'Weak or invalid PIN' });
      u.card.pin = String(d.pin); u.card.wrong = 0; save(); return { message: 'ATM PIN set successfully.', card: cardView(u) }; }),
    cardAction: wrap(d => { const u = cur(); noCard(u); const c = u.card; mpinOk(u, d.mpin);
      if (d.action === 'block') c.status = 'BLOCKED'; else if (d.action === 'unblock') { c.status = 'ACTIVE'; c.wrong = 0; }
      else if (d.action === 'online') c.online = !!d.value;
      else if (d.action === 'limit') { const l = amt(d.value, 1000); if (l > 100000) fail('Maximum daily ATM limit is ₹1,00,000.'); c.limit = l; }
      save(); return { message: 'Card updated.', card: cardView(u) }; }),
    atm: wrap(d => {
      load(); const u = db.users.find(x => x.card && x.card.number === String(d.card_no).replace(/\s/g, '')); if (!u) fail('Card not recognised.');
      const c = u.card; if (c.status !== 'ACTIVE') fail('Card is blocked. Please unblock it from the SecureBank app.');
      if (!c.pin) fail('ATM PIN not set. Set your PIN in the app first.');
      if (String(d.pin) !== c.pin) { c.wrong++; if (c.wrong >= 3) c.status = 'BLOCKED'; save(); fail(c.wrong >= 3 ? 'Wrong PIN. Card blocked after 3 wrong attempts.' : 'Wrong PIN. ' + (3 - c.wrong) + ' attempt(s) left.'); }
      c.wrong = 0;
      if (d.action === 'balance') return { message: 'Available balance: ' + inr(u.balance) };
      if (d.action === 'statement') return { message: 'Mini statement', lines: db.txs.filter(x => x.acc === u.account_no).slice(-5).reverse().map(x => new Date(x.timestamp).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }) + ' ' + LBL[x.type] + ' ' + inr(x.amount)) };
      if (d.action === 'change_pin') { if (weak(String(d.new_pin))) fail('New PIN must be 4 digits and not obvious.'); c.pin = String(d.new_pin); save(); return { message: 'PIN changed successfully.' }; }
      needKyc(u); const a = amt(d.amount, 100); if (a % 100 || a > 10000) fail('ATM dispenses ₹100 notes. Enter a multiple of 100, up to ₹10,000 per transaction.');
      const today = db.txs.filter(x => x.acc === u.account_no && x.channel === 'ATM' && x.type === 2 && new Date(x.timestamp).toDateString() === new Date().toDateString()).reduce((s, x) => s + x.amount, 0);
      if (today + a > c.limit) fail('Daily ATM limit of ' + inr(c.limit) + ' exceeded.'); if (a > u.balance) fail('Insufficient balance.');
      tx(u, a, 2, 'ATM cash withdrawal', 0, 'ATM'); save(); return { message: 'Please collect your cash ' + inr(a) + '. Balance: ' + inr(u.balance) };
    }),
    fdList: wrap(() => { const u = cur(); return db.fds.filter(f => f.acc === u.account_no).slice().reverse(); }),
    fdOpen: wrap(d => { const u = cur(); needKyc(u); mpinOk(u, d.mpin); const a = amt(d.amount, 1000), m = parseInt(d.months, 10);
      if (!(m >= 3 && m <= 120)) fail('Tenure must be between 3 and 120 months.', { months: '3-120 months' });
      if (a > u.balance) fail('Insufficient balance.', { amount: 'Insufficient balance' });
      const r = fdRate(m), mat = r2(a * Math.pow(1 + r / 400, m / 3)), md = new Date(); md.setMonth(md.getMonth() + m);
      const fd = { id: db.fds.length + 1, acc: u.account_no, principal: a, rate: r, months: m, opened: new Date().toISOString().slice(0, 10), maturity_date: md.toISOString().slice(0, 10), maturity_amount: mat, status: 'OPEN' };
      db.fds.push(fd); tx(u, a, 2, 'Fixed deposit #' + fd.id + ' opened', 0, 'FD'); save();
      return { message: 'FD of ' + inr(a) + ' opened at ' + r + '% for ' + m + ' months. Maturity ' + inr(mat) + '.' }; }),
    fdClose: wrap(d => { const u = cur(); needKyc(u); mpinOk(u, d.mpin); const fd = db.fds.find(f => f.id === Number(d.id) && f.acc === u.account_no && f.status === 'OPEN'); if (!fd) fail('FD not found.');
      const days = Math.floor((Date.now() - new Date(fd.opened)) / 864e5), matured = new Date() >= new Date(fd.maturity_date);
      const pay = matured ? fd.maturity_amount : r2(fd.principal + (days < 7 ? 0 : fd.principal * Math.max(fd.rate - 1, 0) / 100 * days / 365));
      fd.status = 'CLOSED'; tx(u, pay, 1, 'Fixed deposit #' + fd.id + (matured ? ' matured' : ' closed early (1% penalty)'), 0, 'FD'); save();
      return { message: 'FD ' + (matured ? 'matured' : 'closed early (1% penalty)') + '. ' + inr(pay) + ' credited to your account.' }; }),
    whatsapp: wrap(text => {
      const u = cur(), low = String(text).trim().toLowerCase(), mine = db.txs.filter(x => x.acc === u.account_no).slice().reverse();
      if (['hi', 'hello', 'hey', 'help', 'menu', 'namaste'].includes(low)) return 'Namaste ' + u.first_name + '! 🙏\n🏦 SecureBank WhatsApp Banking\n• BALANCE\n• STATEMENT\n• SEND 500 TO 9876543210 (or account no / UPI id)\n• BLOCK CARD\n• MY UPI / IFSC\n• FD RATES\nOr just ask me anything about your account.';
      if (['balance', 'bal', 'check balance'].includes(low)) return '💰 Available balance: ' + inr(u.balance) + '\nA/c ' + u.account_no;
      if (['statement', 'mini statement', 'history'].includes(low)) return '🧾 Last 5 transactions\n' + (mine.slice(0, 5).map(x => new Date(x.timestamp).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }) + ' · ' + LBL[x.type] + ' ' + inr(x.amount) + ' [' + x.channel + ']').join('\n') || 'No transactions yet.');
      if (['my upi', 'upi', 'ifsc', 'account', 'my account'].includes(low)) return 'A/c: ' + u.account_no + '\nIFSC: SECB0000001\nUPI: ' + u.phone + '@securebank';
      if (low === 'fd rates') return '📈 FD rates p.a.: up to 6 months 6.00% · 7-12 months 6.80% · 13-24 months 7.00% · above 24 months 7.25%';
      if (low === 'block card') { if (!u.card) return 'No debit card has been issued yet.'; u.card.status = 'BLOCKED'; save(); return '🔒 Your debit card has been blocked. Unblock it from the SecureBank app with your mPIN.'; }
      if (low === 'cancel') { waPending = null; return 'Cancelled.'; }
      let m = low.match(/^send\s+(\d+(?:\.\d{1,2})?)\s+to\s+(\S+)$/);
      if (m) { const a = parseFloat(m[1]), to = findTarget(m[2]); if (a > 10000) return '❌ WhatsApp transfers are limited to ₹10,000. Please use the app (OTP protected).'; if (!(a >= MIN)) return '❌ Minimum amount is ₹' + MIN + '.'; if (!to || to === u) return '❌ Recipient not found (or same as your account).';
        waPending = { a, to: to.account_no }; return 'Send ' + inr(a) + ' to ' + to.first_name + ' (A/c ending ' + String(to.account_no).slice(-4) + ')?\nReply PIN <your mPIN> to confirm, or CANCEL.'; }
      m = low.match(/^pin\s+(\d{4,6})$/);
      if (m) { if (!waPending) return 'No pending request. Send e.g. SEND 500 TO 9876543210'; if (m[1] !== u.mpin) return '❌ Incorrect mPIN.';
        const to = db.users.find(x => x.account_no === waPending.to), a = waPending.a; waPending = null;
        try { xfer(u, to, a, 'via WhatsApp', 'WHATSAPP'); } catch (e) { return '❌ ' + e.message; }
        return '✅ ' + inr(a) + ' sent to ' + to.first_name + '.\nNew balance: ' + inr(u.balance); }
      return mock.assistantRule(text).message;
    })
  });
  const LBL = { 1: 'Deposit', 2: 'Withdrawal', 3: 'Interest' };

  /* ---- Login OTP, beneficiaries, bills & recharge, loans, cheque book, admin (mock) ---- */
  const BILLERS = { MOBILE: ['Jio', 'Airtel', 'Vi', 'BSNL'], DTH: ['Tata Play', 'Airtel Digital TV', 'Dish TV', 'Sun Direct'], ELECTRICITY: ['UPPCL', 'BSES Delhi', 'MSEDCL', 'TNEB', 'BESCOM'],
    WATER: ['Delhi Jal Board', 'BWSSB', 'MCGM Water'], GAS: ['Indane', 'HP Gas', 'Bharat Gas', 'Mahanagar Gas'], BROADBAND: ['Jio Fiber', 'Airtel Xstream', 'ACT Fibernet', 'BSNL Broadband'] };
  const PLANS = [{ amount: 199, info: '28 days · 1.5 GB/day' }, { amount: 299, info: '28 days · 2 GB/day' }, { amount: 479, info: '56 days · 1.5 GB/day' }, { amount: 719, info: '84 days · 1.5 GB/day' }];
  const RULES = { PERSONAL: { rate: 11.5, min: 10000, max: 500000, min_months: 6, max_months: 60 }, HOME: { rate: 8.5, min: 100000, max: 10000000, min_months: 60, max_months: 360 },
    EDUCATION: { rate: 9.5, min: 50000, max: 2000000, min_months: 12, max_months: 120 }, VEHICLE: { rate: 9.0, min: 50000, max: 1500000, min_months: 12, max_months: 84 } };
  const emiOf = (p, r, n) => { const i = r / 1200, k = Math.pow(1 + i, n); return r2(p * i * k / (k - 1)); };
  const lj = l => ({ ...l, remaining_emis: l.status === 'ACTIVE' ? l.months - l.paid_emis : 0, outstanding: l.status === 'ACTIVE' ? r2(l.emi * (l.months - l.paid_emis)) : 0 });
  const today = () => new Date().toISOString().slice(0, 10);
  const admin = () => { load(); if (db.session !== 'admin') fail('Staff access only.'); };
  Object.assign(mock, {
    login: wrap((email, password) => {
      load(); const e = String(email).trim().toLowerCase();
      if (e === 'admin@securebank.in' && password === 'Admin@1234') { db.session = 'admin'; save(); return null; }
      const u = db.users.find(x => x.email === e);
      if (!u || u.password !== password || u.frozen) fail('Invalid email or password.');
      db.loginOtp = { uid: u.id, code: rnd(6) }; save();
      return { otp_required: true, otp_token: String(u.id), message: 'OTP sent to +91 ' + u.phone.slice(0, 2) + 'XXXXXX' + u.phone.slice(-2), dev_otp: db.loginOtp.code };
    }),
    loginVerify: wrap((tok, code) => { load(); const o = db.loginOtp;
      if (!o || String(o.uid) !== String(tok) || o.code !== String(code).trim()) fail('Incorrect OTP.', { code: 'Incorrect OTP' });
      db.session = o.uid; db.loginOtp = null; save(); }),
    beneficiaries: wrap(() => { const u = cur(); return db.payees.filter(b => b.acc === u.account_no); }),
    beneficiaryAdd: wrap(d => { const u = cur(), id = String(d.identifier).trim().toLowerCase(), t = findTarget(id);
      if (!t) fail('No SecureBank account found for this account number / mobile / UPI id.', { identifier: 'Not found' }); if (t === u) fail('You cannot add your own account.');
      if (db.payees.some(b => b.acc === u.account_no && b.identifier === id)) return { message: 'Already in your beneficiaries.' };
      db.payees.push({ id: db.payees.length + 1, acc: u.account_no, name: d.name || t.first_name + ' ' + t.last_name, identifier: id }); save(); return { message: 'Beneficiary added.' }; }),
    beneficiaryDelete: wrap(d => { const u = cur(); db.payees = db.payees.filter(b => !(b.id === Number(d.id) && b.acc === u.account_no)); save(); return { message: 'Beneficiary removed.' }; }),
    billers: wrap(() => ({ billers: BILLERS, plans: PLANS })),
    payments: wrap(() => { const u = cur(); return db.pays.filter(p => p.acc === u.account_no).slice().reverse(); }),
    pay: wrap(d => { const u = cur(); needKyc(u); const cat = String(d.category).toUpperCase(), cno = String(d.consumer_no || '').trim();
      if (!BILLERS[cat] || !BILLERS[cat].includes(d.biller)) fail('Choose a valid category and biller.');
      if (cat === 'MOBILE' && !/^[6-9]\d{9}$/.test(cno)) fail('Enter a valid 10-digit mobile number.', { consumer_no: 'Invalid mobile number' });
      if (cat !== 'MOBILE' && !/^[A-Za-z0-9-]{5,20}$/.test(cno)) fail('Enter a valid consumer / subscriber number (5-20 letters or digits).', { consumer_no: 'Invalid number' });
      const a = amt(d.amount, cat === 'MOBILE' || cat === 'DTH' ? 10 : 1); if (a > 100000) fail('Maximum payment is ₹1,00,000.', { amount: 'Too high' });
      mpinOk(u, d.mpin); if (a > u.balance) fail('Insufficient balance.', { amount: 'Insufficient balance' });
      const ref = 'SB' + rnd(10); tx(u, a, 2, d.biller + ' ' + cat[0] + cat.slice(1).toLowerCase() + ' ' + cno, 0, 'BILL');
      db.pays.push({ id: db.pays.length + 1, acc: u.account_no, category: cat, biller: d.biller, consumer_no: cno, amount: a, reference: ref, timestamp: new Date().toISOString() }); save();
      return { message: inr(a) + ' paid to ' + d.biller + '. Ref ' + ref + '.' }; }),
    loans: wrap(() => { const u = cur(); return { rules: RULES, loans: db.loans.filter(l => l.account_no === u.account_no).slice().reverse().map(lj) }; }),
    loanApply: wrap(d => { const u = cur(); needKyc(u); const k = String(d.kind).toUpperCase(), R = RULES[k]; if (!R) fail('Choose a loan type.', { kind: 'Required' });
      const a = amt(d.amount, R.min); if (a > R.max) fail('Maximum ' + k.toLowerCase() + ' loan is ₹' + R.max.toLocaleString('en-IN') + '.', { amount: 'Max ₹' + R.max.toLocaleString('en-IN') });
      const m = parseInt(d.months, 10); if (!(m >= R.min_months && m <= R.max_months)) fail('Tenure must be ' + R.min_months + '-' + R.max_months + ' months.', { months: R.min_months + '-' + R.max_months + ' months' });
      const inc = amt(d.income, 1000); mpinOk(u, d.mpin);
      if (db.loans.some(l => l.account_no === u.account_no && l.kind === k && l.status === 'PENDING')) fail('You already have a pending ' + k.toLowerCase() + ' loan application.');
      const e = emiOf(a, R.rate, m); if (e > inc / 2) fail('EMI ' + inr(e) + ' is more than 50% of your monthly income. Reduce the amount or increase tenure.', { amount: 'EMI too high' });
      db.loans.push({ id: db.loans.length + 1, account_no: u.account_no, kind: k, principal: a, rate: R.rate, months: m, emi: e, income: inc, status: 'PENDING', paid_emis: 0, applied: today() }); save();
      return { message: 'Loan application submitted. EMI would be ' + inr(e) + '. A bank officer will review it.' }; }),
    loanEmi: wrap(d => { const u = cur(); needKyc(u); mpinOk(u, d.mpin); const l = db.loans.find(x => x.id === Number(d.id) && x.account_no === u.account_no && x.status === 'ACTIVE');
      if (!l) fail('Active loan not found.'); if (l.emi > u.balance) fail('Insufficient balance to pay the EMI.');
      l.paid_emis++; if (l.paid_emis >= l.months) l.status = 'CLOSED'; tx(u, l.emi, 2, 'Loan #' + l.id + ' EMI ' + l.paid_emis + '/' + l.months, 0, 'LOAN'); save();
      return { message: 'EMI of ' + inr(l.emi) + ' paid (' + l.paid_emis + '/' + l.months + ').' + (l.status === 'CLOSED' ? ' Loan fully repaid 🎉' : '') }; }),
    cheques: wrap(() => { const u = cur(); return db.cheques.filter(c => c.account_no === u.account_no).slice().reverse(); }),
    chequeRequest: wrap(d => { const u = cur(); needKyc(u); mpinOk(u, d.mpin); const n = parseInt(d.leaves, 10); if (![25, 50].includes(n)) fail('Choose 25 or 50 leaves.', { leaves: '25 or 50' });
      if (db.cheques.some(c => c.account_no === u.account_no && c.status === 'REQUESTED')) fail('You already have a cheque book request in progress.');
      db.cheques.push({ id: db.cheques.length + 1, account_no: u.account_no, leaves: n, status: 'REQUESTED', requested: today() }); save();
      return { message: 'Cheque book (' + n + ' leaves) requested. It will be posted to your registered address.' }; }),
    pdf: () => Promise.reject(new Error('PDF download works in the full project (run it locally).')),
    adminSummary: wrap(() => { admin(); const t = new Date().toDateString(), td = db.txs.filter(x => new Date(x.timestamp).toDateString() === t);
      return { customers: db.users.length, total_deposits: r2(db.users.reduce((s, u) => s + u.balance, 0)), transactions_today: td.length, volume_today: r2(td.reduce((s, x) => s + x.amount, 0)),
        pending_loans: db.loans.filter(l => l.status === 'PENDING').length, active_loans: db.loans.filter(l => l.status === 'ACTIVE').length, pending_cheques: db.cheques.filter(c => c.status === 'REQUESTED').length,
        pending_kyc: db.users.filter(u => u.kyc_status === 'PENDING').length, blocked_cards: db.users.filter(u => u.card && u.card.status === 'BLOCKED').length,
        accounts_opened: db.users.length, new_accounts_today: db.users.filter(u => (u.joined || '').slice(0, 10) === today()).length, kyc_pending: db.users.filter(u => u.kyc_status === 'PENDING').length,
        kyc_verified: db.users.filter(u => (u.kyc_status || 'VERIFIED') === 'VERIFIED').length, kyc_rejected: db.users.filter(u => u.kyc_status === 'REJECTED').length, cards_issued: db.users.filter(u => u.card).length, card_applications_pending: db.cardApps.filter(a => a.status === 'PENDING').length, fd_total: r2(db.fds.filter(f => f.status === 'OPEN').reduce((s, f) => s + f.principal, 0)), bill_payments: db.pays.length }; }),
    adminLoans: wrap(s => { admin(); return db.loans.filter(l => !s || l.status === s).slice().reverse().map(lj); }),
    adminDecide: wrap(d => { admin(); const l = db.loans.find(x => x.id === Number(d.id) && x.status === 'PENDING'); if (!l) fail('Pending loan not found.');
      if (d.action === 'approve') { const u = db.users.find(x => x.account_no === l.account_no); l.status = 'ACTIVE'; tx(u, l.principal, 1, 'Loan #' + l.id + ' (' + l.kind[0] + l.kind.slice(1).toLowerCase() + ') disbursed', 0, 'LOAN'); } else l.status = 'REJECTED';
      save(); return { message: 'Loan #' + l.id + ' ' + l.status.toLowerCase() + '.' }; }),
    adminCheques: wrap(() => { admin(); return db.cheques.slice().reverse(); }),
    adminDispatch: wrap(d => { admin(); const c = db.cheques.find(x => x.id === Number(d.id) && x.status === 'REQUESTED'); if (!c) fail('Request not found.'); c.status = 'DISPATCHED'; save(); return { message: 'Cheque book marked as dispatched.' }; }),
    adminCustomers: wrap(() => { admin(); return db.users.slice().reverse().map(u => ({ id: u.id, name: u.first_name + ' ' + u.last_name, email: u.email, phone: u.phone, account_no: u.account_no, balance: u.balance, active: !u.frozen, opened: (u.joined || today()).slice(0, 10), kyc_status: u.kyc_status || 'VERIFIED', card_issued: !!u.card, card_status: u.card ? 'ISSUED' : (appOf(u) && appOf(u).status === 'PENDING' ? 'PENDING' : 'NONE') })); }),
    adminToggle: wrap(d => { admin(); const u = db.users.find(x => x.id === Number(d.id)); if (!u) fail('Customer not found.'); u.frozen = !u.frozen; save(); return { message: 'Account ' + (u.frozen ? 'frozen' : 'unfrozen') + '.' }; })
  });

  /* ---- KYC documents + bulk approvals (mock) ---- */
  function needKyc(u) { const st = u.kyc_status || 'VERIFIED';
    if (st === 'PENDING') fail('Your account is under review. Deposits, transactions and your debit card unlock after the bank approves your KYC documents.');
    if (st === 'REJECTED') fail('Your KYC was rejected. Please upload correct documents from Profile.'); }
  const DK = ['AADHAAR', 'PAN', 'PHOTO'];
  const disburse = l => { const u = db.users.find(x => x.account_no === l.account_no); l.status = 'ACTIVE'; tx(u, l.principal, 1, 'Loan #' + l.id + ' (' + l.kind[0] + l.kind.slice(1).toLowerCase() + ') disbursed', 0, 'LOAN'); };
  const kycRow = u => ({ id: u.id, user_id: u.id, name: u.first_name + ' ' + u.last_name, email: u.email, phone: u.phone, aadhaar_masked: 'XXXX XXXX ' + u.aadhaar_last4, status: u.kyc_status || 'VERIFIED', note: u.kyc_note || '',
    applied: (u.joined || today()).slice(0, 10), docs: db.docs.filter(d => d.user === u.id).map(pub) });
  const kycDecide = (u, action, reason) => { if (action === 'approve') { const aad = db.docs.find(d => d.user === u.id && d.kind === 'AADHAAR');
      if (!aad) fail('Cannot approve: no Aadhaar document uploaded.'); if (!aad.viewed) fail('Open and review the Aadhaar document before approving.');
      u.kyc_status = 'VERIFIED'; u.kyc_note = ''; }
    else if (action === 'reject') { u.kyc_status = 'REJECTED'; u.kyc_note = (reason || 'Documents not clear / not valid. Please upload again.').slice(0, 160); } else fail('Action must be approve or reject.'); };
  const pub = d => { const { data, ...r } = d; return r; };
  const readData = f => new Promise(res => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = () => res(null); r.readAsDataURL(f); });
  Object.assign(mock, {
    uploadDoc: async (kind, file) => { load(); const u = cur(); if (!DK.includes(kind)) fail('Choose a document type: Aadhaar, PAN or Photo.', { kind: 'Required' }); if (!file) fail('Choose a file to upload.', { file: 'Required' });
      if (file.size > 2 * 1024 * 1024) fail('File is too large. Maximum size is 2 MB.', { file: 'Max 2 MB' });
      if (!['image/jpeg', 'image/png', 'application/pdf'].includes(file.type)) fail('Only JPG, PNG or PDF files are allowed.', { file: 'JPG, PNG or PDF only' });
      if ((u.kyc_status || 'VERIFIED') === 'VERIFIED') fail('Your KYC is already verified. Contact the bank to change documents.');
      const data = file.size <= 400 * 1024 ? await readData(file) : null;
      db.docs = db.docs.filter(d => !(d.user === u.id && d.kind === kind)); db.docs.push({ id: (db.docsSeq = (db.docsSeq || 0) + 1), user: u.id, kind, name: file.name, size: file.size, type: file.type, data, viewed: false });
      if (u.kyc_status === 'REJECTED') { u.kyc_status = 'PENDING'; u.kyc_note = ''; } save(); return { message: kind[0] + kind.slice(1).toLowerCase() + ' uploaded.' }; },
    docs: wrap(() => { const u = cur(); return { documents: db.docs.filter(d => d.user === u.id).map(pub), kyc_status: u.kyc_status || 'VERIFIED', kyc_note: u.kyc_note || '' }; }),
    adminKyc: wrap(s => { admin(); return db.users.filter(u => !s || (u.kyc_status || 'VERIFIED') === s).slice().reverse().map(kycRow); }),
    adminKycDecide: wrap(d => { admin(); const u = db.users.find(x => x.id === Number(d.id)); if (!u) fail('KYC record not found.'); kycDecide(u, d.action, d.reason); save(); return { message: 'KYC of ' + u.first_name + ' ' + u.kyc_status.toLowerCase() + '.' }; }),
    adminKycApproveAll: wrap(() => { admin(); let ok = 0, skip = 0; db.users.filter(u => u.kyc_status === 'PENDING').forEach(u => { try { kycDecide(u, 'approve'); ok++; } catch (e) { skip++; } }); save();
      return { message: ok + ' KYC approved' + (skip ? ', ' + skip + ' skipped (Aadhaar document missing or not opened for review yet).' : '.'), count: ok }; }),
    adminLoansApproveAll: wrap(() => { admin(); const L = db.loans.filter(l => l.status === 'PENDING'); L.forEach(disburse); save(); return { message: L.length + ' loan(s) approved and disbursed.', count: L.length }; }),
    adminChequesDispatchAll: wrap(() => { admin(); const C = db.cheques.filter(c => c.status === 'REQUESTED'); C.forEach(c => { c.status = 'DISPATCHED'; }); save(); return { message: C.length + ' cheque book request(s) marked as dispatched.', count: C.length }; }),
    adminDocUrl: async id => { admin(); const d = db.docs.find(x => x.id === Number(id)); if (!d) fail('Document not found.'); d.viewed = true; save();
      if (!d.data) fail('Preview is not stored for this large file in the demo.'); const bin = atob(d.data.split(',')[1]), arr = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
      return URL.createObjectURL(new Blob([arr], { type: d.type })); },
    adminCustomer: wrap(id => { admin(); const u = db.users.find(x => x.id === Number(id)); if (!u) fail('Customer not found.');
      const txs = db.txs.filter(x => x.acc === u.account_no), S = k => r2(txs.filter(x => x.type === k).reduce((a, x) => a + x.amount, 0)), t = typeOf(u);
      return { customer: { id: u.id, name: u.first_name + ' ' + u.last_name, email: u.email, active: !u.frozen, joined: u.joined || new Date().toISOString(), gender: u.gender, birth_date: u.birth_date, address: u.address },
        kyc: { id: u.id, status: u.kyc_status || 'VERIFIED', note: u.kyc_note || '', phone: u.phone, phone_verified: true, aadhaar_masked: 'XXXX XXXX ' + u.aadhaar_last4, consent_at: u.joined || new Date().toISOString() },
        documents: db.docs.filter(d => d.user === u.id).map(pub),
        account: { account_no: u.account_no, type: t.name, interest_rate: t.annual_interest_rate, balance: u.balance, withdraw_limit: t.maximum_withdrawal_amount, initial_deposit_date: null, upi_id: u.phone + '@securebank',
          total_deposits: S(1), total_withdrawals: S(2), total_interest: S(3), transactions: txs.length },
        card_application: appOf(u), card: u.card ? { variant: u.card.variant || 'CLASSIC', masked_number: 'XXXX XXXX XXXX ' + u.card.number.slice(-4), expiry: u.card.expiry, status: u.card.status, daily_atm_limit: u.card.limit, online_enabled: u.card.online, pin_set: !!u.card.pin } : null,
        fixed_deposits: db.fds.filter(f => f.acc === u.account_no).slice().reverse(), loans: db.loans.filter(l => l.account_no === u.account_no).slice().reverse().map(lj), cheque_requests: db.cheques.filter(c => c.account_no === u.account_no),
        payments_count: db.pays.filter(p => p.acc === u.account_no).length, beneficiaries_count: db.payees.filter(b => b.acc === u.account_no).length,
        recent_transactions: txs.slice(-25).reverse().map(x => ({ id: x.id, type: LBL[x.type], amount: x.amount, balance_after: x.balance_after, description: x.description, channel: x.channel, timestamp: x.timestamp })) }; })
  });

  /* ---- debit card applications (mock) ---- */
  const cardRow = a => { const u = db.users.find(x => x.id === a.user); return { id: a.id, user_id: u.id, name: u.first_name + ' ' + u.last_name, email: u.email, phone: u.phone, account_no: u.account_no,
    variant: a.variant, status: a.status, note: a.note || '', applied: a.created.slice(0, 10), kyc_status: u.kyc_status || 'VERIFIED' }; };
  const cardDecide = (a, action, reason) => { const u = db.users.find(x => x.id === a.user); if (a.status !== 'PENDING') fail('This application is already processed.');
    if (action === 'approve') { if ((u.kyc_status || 'VERIFIED') !== 'VERIFIED') fail('Customer KYC is not verified.'); if (u.card) fail('Customer already has a debit card.');
      u.card = newCard(a.variant); u.cardReveal = u.card.cvv; a.status = 'APPROVED'; }
    else if (action === 'reject') { a.status = 'REJECTED'; a.note = (reason || 'Application rejected by the bank.').slice(0, 160); } else fail('Action must be approve or reject.'); };
  Object.assign(mock, {
    cardApply: wrap(d => { const u = cur(); needKyc(u); if (u.card) fail('You already have a debit card.'); const v = String(d.variant || 'CLASSIC').toUpperCase();
      if (!['CLASSIC', 'PLATINUM'].includes(v)) fail('Choose a card type.', { variant: 'Required' }); mpinOk(u, d.mpin);
      if (db.cardApps.some(a => a.user === u.id && a.status === 'PENDING')) fail('Your card application is already under review.');
      const a = { id: db.cardApps.length + 1, user: u.id, variant: v, status: 'PENDING', note: '', created: new Date().toISOString() }; db.cardApps.push(a); save();
      return { message: 'Debit card application (' + v[0] + v.slice(1).toLowerCase() + ') submitted. Your card will be created after the bank approves it.', application: a }; }),
    adminCards: wrap(s => { admin(); return db.cardApps.filter(a => !s || a.status === s).slice().reverse().map(cardRow); }),
    adminCardDecide: wrap(d => { admin(); const a = db.cardApps.find(x => x.id === Number(d.id)); if (!a) fail('Application not found.'); cardDecide(a, d.action, d.reason); save();
      const u = db.users.find(x => x.id === a.user); return { message: 'Card application of ' + u.first_name + ' ' + a.status.toLowerCase() + '.' }; }),
    adminCardsApproveAll: wrap(() => { admin(); let ok = 0, skip = 0; db.cardApps.filter(a => a.status === 'PENDING').forEach(a => { try { cardDecide(a, 'approve'); ok++; } catch (e) { skip++; } }); save();
      return { message: ok + ' debit card(s) approved and created' + (skip ? ', ' + skip + ' skipped.' : '.'), count: ok }; })
  });

  window.API = Object.assign({ mode: cfg.mode, demo: !!cfg.demo }, cfg.mode === 'mock' ? mock : live);
})();
