"""Phone OTP, Aadhaar KYC registration, debit card + ATM, fixed deposits, WhatsApp banking."""
import hashlib
import hmac
import random
import re
from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.hashers import check_password, make_password
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction as db
from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
from django.utils import timezone

from accounts.models import BankAccountType, UserAddress, UserBankAccount
from services.models import CardApplication, DebitCard, FixedDeposit, KYCProfile, PhoneOTP
from transactions.constants import DEPOSIT, WITHDRAWAL
from transactions.models import Transaction

from . import kyc
from .assistant import answer, inr
from .otp import issue_otp, otp_payload, verify_otp
from .sms import send_whatsapp
from .errors import ApiError
from .views import (require_kyc, User, api, auth, body, lock, money, perform_transfer, record, resolve_target,
                    token_for, tx_json, user_json)

OTP_SALT = 'securebank.phone.verified'


# ---------------- Phone OTP (registration) ----------------
@api(['POST'])
def otp_send(request):
    phone = kyc.clean_phone(body(request).get('phone'))
    if not phone:
        raise ApiError('Enter a valid 10-digit Indian mobile number.', fields={'phone': 'Invalid mobile number'})
    if KYCProfile.objects.filter(phone=phone).exists():
        raise ApiError('This mobile number is already registered.', fields={'phone': 'Already registered'})
    return JsonResponse(otp_payload(phone, issue_otp(phone, 'register')))


@api(['POST'])
def otp_verify(request):
    d = body(request)
    phone = kyc.clean_phone(d.get('phone'))
    verify_otp(phone, d.get('code'), 'register')
    return JsonResponse({'phone_token': signing.dumps({'phone': phone}, salt=OTP_SALT), 'message': 'Mobile number verified.'})


# ---------------- Registration (phone + Aadhaar + card issue) ----------------
def luhn_digit(base):
    total = 0
    for i, ch in enumerate(reversed(base)):
        n = int(ch) * (2 if i % 2 == 0 else 1)
        total += n - 9 if n > 9 else n
    return str((10 - total % 10) % 10)


VARIANTS = {'CLASSIC': Decimal('20000'), 'PLATINUM': Decimal('50000')}  # card type -> default daily ATM limit


def issue_card(account, variant='CLASSIC'):
    rnd = random.SystemRandom()
    while True:
        base = '652150' + ''.join(str(rnd.randint(0, 9)) for _ in range(9))
        number = base + luhn_digit(base)
        if not DebitCard.objects.filter(number=number).exists():
            break
    cvv = f'{rnd.randint(0, 999):03d}'
    exp = date.today() + relativedelta(years=5)
    DebitCard.objects.create(account=account, number=number, expiry=exp.strftime('%m/%y'), cvv_hash=make_password(cvv), reveal_cvv=cvv, variant=variant,
                             daily_atm_limit=VARIANTS.get(variant, VARIANTS['CLASSIC']))
    return {'number': number, 'expiry': exp.strftime('%m/%y'), 'cvv': cvv}


@api(['POST'])
def register(request):
    d = body(request)
    s = lambda k: str(d.get(k, '')).strip()  # noqa: E731
    f = {}
    email = s('email').lower()
    if not s('first_name'): f['first_name'] = 'Required'
    if not s('last_name'): f['last_name'] = 'Required'
    if '@' not in email or '.' not in email.split('@')[-1]: f['email'] = 'Enter a valid email'
    elif User.objects.filter(email__iexact=email).exists(): f['email'] = 'Email already registered'
    try:
        password_validation.validate_password(str(d.get('password', '')))
    except ValidationError as e:
        f['password'] = ' '.join(e.messages)
    phone = kyc.clean_phone(s('phone'))
    try:
        ok = signing.loads(s('phone_token'), salt=OTP_SALT, max_age=1800)['phone'] == phone
    except (signing.BadSignature, KeyError):
        ok = False
    if not phone or not ok: f['phone'] = 'Verify your mobile number with OTP'
    elif KYCProfile.objects.filter(phone=phone).exists(): f['phone'] = 'Already registered'
    aadhaar = kyc.clean_aadhaar(s('aadhaar'))
    if not aadhaar: f['aadhaar'] = 'Enter a valid 12-digit Aadhaar number'
    elif KYCProfile.objects.filter(aadhaar_hash=kyc.aadhaar_hash(aadhaar)).exists(): f['aadhaar'] = 'Aadhaar already linked to an account'
    if d.get('consent') is not True: f['consent'] = 'Consent is required to use your Aadhaar for KYC'
    if not re.fullmatch(r'\d{4,6}', s('mpin')): f['mpin'] = 'mPIN must be 4-6 digits'
    acct_type = BankAccountType.objects.filter(pk=int(s('account_type'))).first() if s('account_type').isdigit() else None
    if not acct_type: f['account_type'] = 'Choose an account type'
    if s('gender') not in ('M', 'F'): f['gender'] = 'Choose gender'
    try:
        born = date.fromisoformat(s('birth_date'))
        if born > date.today() - relativedelta(years=18): f['birth_date'] = 'You must be 18 or older'
    except ValueError:
        born = None
        f['birth_date'] = 'Enter a valid date'
    if not s('street_address'): f['street_address'] = 'Required'
    if not s('city'): f['city'] = 'Required'
    if not (s('postal_code').isdigit() and len(s('postal_code')) == 6): f['postal_code'] = 'PIN must be 6 digits'
    if f:
        raise ApiError('Please correct the highlighted fields.', fields=f)
    with db.atomic():
        user = User.objects.create_user(email=email, password=d['password'], first_name=s('first_name'), last_name=s('last_name'))
        acc = UserBankAccount.objects.create(user=user, account_type=acct_type, gender=s('gender'), birth_date=born,
                                             account_no=user.id + settings.ACCOUNT_NUMBER_START_FROM)
        UserAddress.objects.create(user=user, street_address=s('street_address'), city=s('city'),
                                   postal_code=int(s('postal_code')), country=s('country') or 'India')
        KYCProfile.objects.create(user=user, phone=phone, phone_verified=True, kyc_status='PENDING', aadhaar_last4=aadhaar[-4:],
                                  aadhaar_hash=kyc.aadhaar_hash(aadhaar), aadhaar_consent_at=timezone.now(),
                                  mpin_hash=make_password(s('mpin')))
    user = User.objects.select_related('account__account_type', 'kyc').get(pk=user.pk)
    return JsonResponse({'token': token_for(user), 'user': user_json(user)}, status=201)


# ---------------- mPIN + Debit card ----------------
def check_mpin(user, mpin):
    key = f'mpin-fail:{user.pk}'
    if cache.get(key, 0) >= 5:
        raise ApiError('Too many wrong mPIN attempts. Try again in 15 minutes.', 429)
    if not check_password(str(mpin or ''), user.kyc.mpin_hash):
        cache.set(key, cache.get(key, 0) + 1, 900)
        raise ApiError('Incorrect mPIN.', 403, {'mpin': 'Incorrect mPIN'})
    cache.delete(key)


def card_json(c):
    return {'issued': True, 'variant': c.variant, 'masked_number': f'XXXX XXXX XXXX {c.number[-4:]}', 'number': c.number, 'expiry': c.expiry, 'status': c.status,
            'pin_set': bool(c.pin_hash), 'daily_atm_limit': str(c.daily_atm_limit), 'online_enabled': c.online_enabled}


def app_json(a):
    return {'id': a.id, 'variant': a.variant, 'status': a.status, 'note': a.note, 'created': a.created.isoformat()}


@api(['POST'])
@auth
def card_apply(request):
    d = body(request)
    require_kyc(request.api_user)
    acc = request.api_user.account
    if hasattr(acc, 'card'):
        raise ApiError('You already have a debit card.')
    variant = str(d.get('variant', 'CLASSIC')).upper()
    if variant not in VARIANTS:
        raise ApiError('Choose a card type.', fields={'variant': 'Required'})
    check_mpin(request.api_user, d.get('mpin'))
    if acc.card_applications.filter(status='PENDING').exists():
        raise ApiError('Your card application is already under review.')
    app = CardApplication.objects.create(account=acc, variant=variant)
    return JsonResponse({'message': f'Debit card application ({variant.title()}) submitted. Your card will be created after the bank approves it.', 'application': app_json(app)})


def my_card(user):
    c = getattr(user.account, 'card', None)
    if not c:
        raise ApiError('You do not have a debit card yet. Apply for one in Card & ATM; it works after the bank approves.', 403)
    return c


@api(['GET'])
@auth
def card(request):
    c = getattr(request.api_user.account, 'card', None)
    if not c:
        app = request.api_user.account.card_applications.order_by('-id').first()
        return JsonResponse({'issued': False, 'application': app_json(app) if app else None})
    out = card_json(c)
    if c.reveal_cvv:  # simulation: show the CVV exactly once, then forget it
        out['cvv'] = c.reveal_cvv
        c.reveal_cvv = ''
        c.save(update_fields=['reveal_cvv'])
    return JsonResponse(out)


@api(['POST'])
@auth
def card_set_pin(request):
    d = body(request)
    check_mpin(request.api_user, d.get('mpin'))
    pin = str(d.get('pin', ''))
    if not re.fullmatch(r'\d{4}', pin) or len(set(pin)) == 1 or pin in ('1234', '4321', '0123'):
        raise ApiError('Choose a 4-digit PIN that is not obvious (no 1111 / 1234).', fields={'pin': 'Weak or invalid PIN'})
    c = my_card(request.api_user)
    c.pin_hash, c.wrong_pin_count = make_password(pin), 0
    c.save()
    return JsonResponse({'message': 'ATM PIN set successfully.', 'card': card_json(c)})


@api(['POST'])
@auth
def card_action(request):
    d = body(request)
    check_mpin(request.api_user, d.get('mpin'))
    c, a = my_card(request.api_user), d.get('action')
    if a == 'block': c.status = 'BLOCKED'
    elif a == 'unblock': c.status, c.wrong_pin_count = 'ACTIVE', 0
    elif a == 'online': c.online_enabled = bool(d.get('value'))
    elif a == 'limit':
        lim = money(d.get('value'), Decimal('1000'))
        if lim > Decimal('100000'): raise ApiError('Maximum daily ATM limit is ₹1,00,000.', fields={'value': 'Too high'})
        c.daily_atm_limit = lim
    else: raise ApiError('Unknown action.')
    c.save()
    return JsonResponse({'message': 'Card updated.', 'card': card_json(c)})


@api(['POST'])
def atm(request):
    """Public endpoint like a real ATM: card number + PIN. Locks the card after 3 wrong PINs."""
    d = body(request)
    c = DebitCard.objects.select_related('account__account_type', 'account__user').filter(
        number=re.sub(r'\s', '', str(d.get('card_no', '')))).first()
    if not c:
        raise ApiError('Card not recognised.', 404)
    if c.status != 'ACTIVE':
        raise ApiError('Card is blocked. Please unblock it from the SecureBank app.', 403)
    if not c.pin_hash:
        raise ApiError('ATM PIN not set. Set your PIN in the app first.', 403)
    if not check_password(str(d.get('pin', '')), c.pin_hash):
        c.wrong_pin_count += 1
        left = 3 - c.wrong_pin_count
        if left <= 0:
            c.status = 'BLOCKED'
        c.save()
        raise ApiError('Wrong PIN. Card blocked after 3 wrong attempts.' if left <= 0 else f'Wrong PIN. {left} attempt(s) left.', 401)
    if c.wrong_pin_count:
        c.wrong_pin_count = 0
        c.save()
    action, acc = d.get('action', 'balance'), c.account
    if action == 'balance':
        return JsonResponse({'message': f'Available balance: {inr(acc.balance)}'})
    if action == 'statement':
        rows = [f"{t.timestamp:%d-%b} {t.get_transaction_type_display()[:3].upper()} {inr(t.amount)}"
                for t in acc.transactions.order_by('-timestamp', '-id')[:5]]
        return JsonResponse({'message': 'Mini statement', 'lines': rows, 'balance': str(acc.balance)})
    if action == 'change_pin':
        new = str(d.get('new_pin', ''))
        if not re.fullmatch(r'\d{4}', new) or len(set(new)) == 1:
            raise ApiError('New PIN must be 4 digits and not obvious.')
        c.pin_hash = make_password(new)
        c.save()
        return JsonResponse({'message': 'PIN changed successfully.'})
    if action == 'withdraw':
        require_kyc(acc.user)
        amount = money(d.get('amount'), Decimal('100'))
        if amount % 100 or amount > 10000:
            raise ApiError('ATM dispenses ₹100 notes. Enter a multiple of 100, up to ₹10,000 per transaction.')
        with db.atomic():
            a = lock(acc)[acc.pk]
            today = Transaction.objects.filter(account=a, channel='ATM', transaction_type=WITHDRAWAL,
                                               timestamp__date=timezone.localdate()).aggregate(s=Sum('amount'))['s'] or 0
            if today + amount > c.daily_atm_limit:
                raise ApiError(f'Daily ATM limit of {inr(c.daily_atm_limit)} exceeded.')
            if amount > a.balance:
                raise ApiError('Insufficient balance.')
            a.balance -= amount
            a.save()
            t = record(a, amount, WITHDRAWAL, 'ATM cash withdrawal', 'ATM')
        return JsonResponse({'message': f'Please collect your cash {inr(amount)}. Balance: {inr(a.balance)}', 'transaction': tx_json(t)})
    raise ApiError('Unknown ATM action.')


# ---------------- Fixed deposits ----------------
def fd_rate(months):
    return Decimal('6.00') if months <= 6 else Decimal('6.80') if months <= 12 else Decimal('7.00') if months <= 24 else Decimal('7.25')


def fd_json(f):
    return {'id': f.id, 'principal': str(f.principal), 'rate': str(f.rate), 'months': f.months, 'opened': f.opened.isoformat(),
            'maturity_date': f.maturity_date.isoformat(), 'maturity_amount': str(f.maturity_amount), 'status': f.status}


@api(['GET'])
@auth
def fd_list(request):
    return JsonResponse([fd_json(f) for f in request.api_user.account.fds.order_by('-id')], safe=False)


@api(['POST'])
@auth
def fd_open(request):
    d = body(request)
    require_kyc(request.api_user)
    check_mpin(request.api_user, d.get('mpin'))
    amount = money(d.get('amount'), Decimal('1000'))
    try:
        months = int(d.get('months'))
    except (TypeError, ValueError):
        months = 0
    if not 3 <= months <= 120:
        raise ApiError('Tenure must be between 3 and 120 months.', fields={'months': '3-120 months'})
    rate = fd_rate(months)
    maturity = (amount * (1 + rate / 400) ** (Decimal(months) / 3)).quantize(Decimal('0.01'))  # quarterly compounding
    with db.atomic():
        acc = lock(request.api_user.account)[request.api_user.account.pk]
        if amount > acc.balance:
            raise ApiError('Insufficient balance.', fields={'amount': 'Insufficient balance'})
        acc.balance -= amount
        acc.save()
        fd = FixedDeposit.objects.create(account=acc, principal=amount, rate=rate, months=months,
                                         maturity_date=date.today() + relativedelta(months=months), maturity_amount=maturity)
        record(acc, amount, WITHDRAWAL, f'Fixed deposit #{fd.id} opened', 'FD')
    return JsonResponse({'message': f'FD of {inr(amount)} opened at {rate}% for {months} months. Maturity {inr(maturity)}.', 'fd': fd_json(fd)})


@api(['POST'])
@auth
def fd_close(request):
    d = body(request)
    require_kyc(request.api_user)
    check_mpin(request.api_user, d.get('mpin'))
    with db.atomic():
        acc = lock(request.api_user.account)[request.api_user.account.pk]
        fd = FixedDeposit.objects.select_for_update().filter(pk=d.get('id') or 0, account=acc, status='OPEN').first()
        if not fd:
            raise ApiError('FD not found.', 404)
        days = (date.today() - fd.opened).days
        if date.today() >= fd.maturity_date:
            payout, note = fd.maturity_amount, 'matured'
        else:  # premature closure: 1% lower rate, no interest under 7 days
            r = max(fd.rate - 1, Decimal('0'))
            payout = fd.principal + (Decimal('0') if days < 7 else (fd.principal * r / 100 * days / 365))
            payout, note = payout.quantize(Decimal('0.01')), 'closed early (1% penalty)'
        acc.balance += payout
        acc.save()
        fd.status = 'CLOSED'
        fd.save()
        record(acc, payout, DEPOSIT, f'Fixed deposit #{fd.id} {note}', 'FD')
    return JsonResponse({'message': f'FD {note}. {inr(payout)} credited to your account.'})


# ---------------- WhatsApp banking ----------------
WA_HELP = ('🏦 *SecureBank WhatsApp Banking*\n• BALANCE\n• STATEMENT\n• SEND 500 TO 9876543210 (or account no / UPI id)\n'
           '• BLOCK CARD\n• MY UPI / IFSC\n• FD RATES\nOr just ask me anything about your account.')


def whatsapp_reply(phone, text):
    """Core WhatsApp bot. `phone` can be 10 digits or 91XXXXXXXXXX (Meta format)."""
    phone = phone[-10:]
    k = KYCProfile.objects.select_related('user__account__account_type').filter(phone=phone).first()
    if not k:
        return 'This number is not registered with SecureBank. Please open an account in the SecureBank app first.'
    user, acc = k.user, k.user.account
    t, low, pkey = text.strip(), text.strip().lower(), f'wa-pending:{phone}'
    if low in ('hi', 'hello', 'hey', 'help', 'menu', 'namaste'):
        return f'Namaste {user.first_name}! 🙏\n{WA_HELP}'
    if low in ('balance', 'bal', 'check balance'):
        return f'💰 Available balance: {inr(acc.balance)}\nA/c {acc.account_no}'
    if low in ('statement', 'mini statement', 'history'):
        rows = [f"{x.timestamp:%d %b} · {x.get_transaction_type_display()} {inr(x.amount)} [{x.channel}]"
                for x in acc.transactions.order_by('-timestamp', '-id')[:5]]
        return '🧾 Last 5 transactions\n' + ('\n'.join(rows) or 'No transactions yet.')
    if low in ('my upi', 'upi', 'ifsc', 'account', 'my account'):
        return f'A/c: {acc.account_no}\nIFSC: {settings.BANK_IFSC}\nUPI: {phone}@securebank'
    if low == 'fd rates':
        return '📈 FD rates p.a.: up to 6 months 6.00% · 7-12 months 6.80% · 13-24 months 7.00% · above 24 months 7.25%'
    if low in ('block card', 'block'):
        if not DebitCard.objects.filter(account=acc).update(status='BLOCKED'):
            return 'You do not have an active debit card yet. Apply for one in the app (Card & ATM).'
        return '🔒 Your debit card has been blocked. Unblock it from the SecureBank app with your mPIN.'
    if low == 'cancel':
        cache.delete(pkey)
        return 'Cancelled.'
    m = re.fullmatch(r'send\s+(\d+(?:\.\d{1,2})?)\s+to\s+(\S+)', low)
    if m:
        try:
            amount = money(m.group(1), Decimal(settings.MINIMUM_WITHDRAWAL_AMOUNT))
        except ApiError as e:
            return f'❌ {e.msg}'
        target = resolve_target(m.group(2))
        if not target or target.pk == acc.pk:
            return '❌ Recipient not found (or same as your account).'
        if amount > Decimal(settings.HIGH_VALUE_TRANSFER):
            return f'❌ WhatsApp transfers are limited to ₹{settings.HIGH_VALUE_TRANSFER:,}. Please use the SecureBank app (OTP protected).'
        cache.set(pkey, {'amount': str(amount), 'target': target.pk}, 300)
        return f'Send {inr(amount)} to {target.user.first_name} (A/c ending {str(target.account_no)[-4:]})?\nReply *PIN <your mPIN>* to confirm, or CANCEL.'
    m = re.fullmatch(r'pin\s+(\d{4,6})', low)
    if m:
        pending = cache.get(pkey)
        if not pending:
            return 'No pending request. Send e.g. SEND 500 TO 9876543210'
        try:
            check_mpin(user, m.group(1))
            target = UserBankAccount.objects.select_related('user').get(pk=pending['target'])
            perform_transfer(acc, target, Decimal(pending['amount']), 'via WhatsApp', 'WHATSAPP')
        except ApiError as e:
            return f'❌ {e.msg}'
        cache.delete(pkey)
        acc.refresh_from_db()
        return f'✅ {inr(pending["amount"])} sent to {target.user.first_name}.\nNew balance: {inr(acc.balance)}'
    return answer(acc, t)[0]


@api(['GET', 'POST'])
def whatsapp_webhook(request):
    if request.method == 'GET':  # Meta webhook verification
        if request.GET.get('hub.verify_token') == settings.WHATSAPP_VERIFY_TOKEN:
            return HttpResponse(request.GET.get('hub.challenge', ''))
        return HttpResponse(status=403)
    if not settings.WHATSAPP_APP_SECRET and not settings.DEBUG:
        return HttpResponse(status=403)  # fail closed: never accept unsigned webhooks outside development
    if settings.WHATSAPP_APP_SECRET:
        sig = request.headers.get('X-Hub-Signature-256', '')
        want = 'sha256=' + hmac.new(settings.WHATSAPP_APP_SECRET.encode(), request.body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, want):
            return HttpResponse(status=403)
    try:
        msg = body(request)['entry'][0]['changes'][0]['value']['messages'][0]
        sender, text = msg['from'], msg['text']['body']
    except (KeyError, IndexError, TypeError):
        return JsonResponse({'status': 'ignored'})
    send_whatsapp(sender, whatsapp_reply(sender, text))
    return JsonResponse({'status': 'ok'})


@api(['POST'])
@auth
def whatsapp_simulate(request):
    """In-app WhatsApp simulator (same bot logic as the real webhook)."""
    return JsonResponse({'reply': whatsapp_reply(request.api_user.kyc.phone, str(body(request).get('message', '')))})
