"""JSON REST API consumed by the React frontend.

Auth: stateless signed token (django.core.signing) sent as `Authorization: Bearer <token>`.
All money movements run inside atomic transactions with row locks.
"""
import csv
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import wraps

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth import get_user_model, password_validation
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction as db
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from accounts.models import BankAccountType, UserAddress, UserBankAccount
from transactions.constants import DEPOSIT, INTEREST, WITHDRAWAL
from transactions.models import Transaction

from services.models import KYCProfile

from .assistant import answer
from .errors import ApiError
from .otp import issue_otp, otp_payload, verify_otp

User = get_user_model()
SALT = 'securebank.api.token'
MAX_AMOUNT = Decimal('10000000')


def api(methods):
    def deco(fn):
        @csrf_exempt
        @require_http_methods(methods)
        @wraps(fn)
        def inner(request, *a, **k):
            try:
                return fn(request, *a, **k)
            except ApiError as e:
                return JsonResponse({'error': e.msg, 'fields': e.fields}, status=e.status)
        return inner
    return deco


def token_user(request):
    header = request.headers.get('Authorization', '')
    try:
        uid = signing.loads(header.split(' ', 1)[1], salt=SALT, max_age=settings.API_TOKEN_MAX_AGE)['uid']
        return User.objects.get(pk=uid, is_active=True)
    except (IndexError, KeyError, signing.BadSignature, User.DoesNotExist):
        raise ApiError('Please login again.', 401)


def auth(fn):
    @wraps(fn)
    def inner(request, *a, **k):
        u = token_user(request)
        try:
            request.api_user = User.objects.select_related('account__account_type').get(pk=u.pk)
            request.api_user.account
        except UserBankAccount.DoesNotExist:
            raise ApiError('Please login again.', 401)
        return fn(request, *a, **k)
    return inner


def staff_auth(fn):
    @wraps(fn)
    def inner(request, *a, **k):
        request.api_user = token_user(request)
        if not request.api_user.is_staff:
            raise ApiError('Staff access only.', 403)
        return fn(request, *a, **k)
    return inner


def body(request):
    try:
        data = json.loads(request.body.decode() or '{}')
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def money(value, minimum):
    try:
        amount = Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        amount = None
    if amount is None or not amount.is_finite() or amount <= 0:
        raise ApiError('Enter a valid amount.', fields={'amount': 'Enter a valid amount.'})
    if amount < minimum:
        raise ApiError(f'Minimum amount is ₹{minimum}.', fields={'amount': f'Minimum is ₹{minimum}'})
    if amount > MAX_AMOUNT:
        raise ApiError('Amount is too large.', fields={'amount': 'Too large'})
    return amount


# ---------- serializers ----------
def type_json(t):
    return {'id': t.id, 'name': t.name, 'annual_interest_rate': str(t.annual_interest_rate),
            'maximum_withdrawal_amount': str(t.maximum_withdrawal_amount),
            'interest_calculation_per_year': t.interest_calculation_per_year}


def user_json(u):
    a, addr, k = u.account, getattr(u, 'address', None), getattr(u, 'kyc', None)
    return {'is_staff': False, 'card_issued': hasattr(a, 'card'), 'card_application': (lambda x: x.status if x else None)(a.card_applications.order_by('-id').first()), 'phone': k.phone if k else None, 'aadhaar_masked': f'XXXX XXXX {k.aadhaar_last4}' if k else None,
            'upi_id': f'{k.phone}@securebank' if k else None, 'ifsc': settings.BANK_IFSC, 'kyc_status': k.kyc_status if k else None, 'kyc_note': k.kyc_note if k else '',
            'id': u.id, 'first_name': u.first_name, 'last_name': u.last_name, 'email': u.email,
            'account_no': a.account_no, 'balance': str(a.balance), 'gender': a.gender,
            'birth_date': a.birth_date.isoformat() if a.birth_date else None,
            'account_type': type_json(a.account_type),
            'address': {'street_address': addr.street_address, 'city': addr.city,
                        'postal_code': addr.postal_code, 'country': addr.country} if addr else None}


def tx_json(t):
    return {'id': t.id, 'amount': str(t.amount), 'type': t.transaction_type,
            'type_label': t.get_transaction_type_display(), 'balance_after': str(t.balance_after_transaction),
            'timestamp': t.timestamp.isoformat(), 'description': t.description, 'channel': t.channel}


def require_kyc(user):
    k = getattr(user, 'kyc', None)
    if not k:  # fail closed: an account without a KYC profile (e.g. created through the old Django UI) must not move money
        raise ApiError('KYC is not complete for this account. Please register through the SecureBank app so the bank can verify your documents.', 403)
    if k.kyc_status != 'VERIFIED':
        raise ApiError('Your account is under review. Deposits, transactions and your debit card unlock after the bank approves your KYC documents.' if k.kyc_status == 'PENDING'
                       else 'Your KYC was rejected. Please upload correct documents from Profile.', 403)


def lock(*accounts):
    ids = sorted({a.pk for a in accounts})
    return {a.pk: a for a in UserBankAccount.objects.select_for_update().select_related('account_type').filter(pk__in=ids).order_by('pk')}  # fixed lock order avoids deadlocks


def record(acc, amount, kind, description='', channel='APP'):
    return Transaction.objects.create(account=acc, amount=amount, balance_after_transaction=acc.balance,
                                      transaction_type=kind, description=description[:120], channel=channel)


def token_for(user):
    return signing.dumps({'uid': user.pk}, salt=SALT)


# ---------- endpoints ----------
@api(['GET'])
def account_types(request):
    return JsonResponse([type_json(t) for t in BankAccountType.objects.all()], safe=False)


@api(['POST'])
def login(request):
    d = body(request)
    email = str(d.get('email', '')).strip()
    ip = request.META.get('REMOTE_ADDR', '')
    k_pair, k_ip = f'login-fail:{email.lower()}:{ip}', f'login-fail-ip:{ip}'
    if cache.get(k_pair, 0) >= 10 or cache.get(k_ip, 0) >= 50:
        raise ApiError('Too many failed login attempts. Try again in 15 minutes.', 429)
    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if not user or not user.check_password(str(d.get('password', ''))):
        for key in (k_pair, k_ip):
            cache.add(key, 0, 900)
            cache.incr(key)
        raise ApiError('Invalid email or password.', 401)
    cache.delete(k_pair)
    if user.is_staff and not hasattr(user, 'account'):
        return JsonResponse({'token': token_for(user), 'user': {'is_staff': True, 'first_name': user.first_name or 'Admin'}})
    if not hasattr(user, 'account'):
        raise ApiError('Invalid email or password.', 401)
    if settings.LOGIN_OTP and hasattr(user, 'kyc'):
        out = otp_payload(user.kyc.phone, issue_otp(user.kyc.phone, 'login'))
        return JsonResponse({'otp_required': True, 'otp_token': signing.dumps({'uid': user.pk}, salt=SALT + '.login'), **out})
    return JsonResponse({'token': token_for(user), 'user': user_json(user)})


@api(['POST'])
def login_verify(request):
    d = body(request)
    try:
        uid = signing.loads(str(d.get('otp_token', '')), salt=SALT + '.login', max_age=600)['uid']
        user = User.objects.select_related('account__account_type', 'kyc').get(pk=uid, is_active=True)
    except (signing.BadSignature, KeyError, User.DoesNotExist):
        raise ApiError('Login session expired. Please login again.', 401)
    verify_otp(user.kyc.phone, d.get('code'), 'login')
    return JsonResponse({'token': token_for(user), 'user': user_json(user)})


@api(['GET'])
def me(request):
    u = token_user(request)
    if u.is_staff and not hasattr(u, 'account'):
        return JsonResponse({'is_staff': True, 'first_name': u.first_name or 'Admin', 'last_name': u.last_name, 'email': u.email})
    return JsonResponse(user_json(User.objects.select_related('account__account_type').get(pk=u.pk)))


@api(['GET'])
@auth
def transactions(request):
    qs = request.api_user.account.transactions.order_by('-timestamp', '-id')
    if request.GET.get('type') in ('1', '2', '3'):
        qs = qs.filter(transaction_type=int(request.GET['type']))
    if request.GET.get('q'):
        qs = qs.filter(description__icontains=request.GET['q'].strip())
    return JsonResponse([tx_json(t) for t in qs[:500]], safe=False)


@api(['GET'])
@auth
def statement(request):
    resp = HttpResponse(content_type='text/csv')
    resp['Content-Disposition'] = 'attachment; filename="securebank-statement.csv"'
    w = csv.writer(resp)
    w.writerow(['Date', 'Type', 'Description', 'Amount', 'Balance After'])
    for t in request.api_user.account.transactions.order_by('-timestamp', '-id'):
        w.writerow([t.timestamp.strftime('%Y-%m-%d %H:%M'), t.get_transaction_type_display(),
                    t.description, f'{t.amount:.2f}', f'{t.balance_after_transaction:.2f}'])
    return resp


@api(['POST'])
@auth
def deposit(request):
    d = body(request)
    require_kyc(request.api_user)
    amount = money(d.get('amount'), Decimal(settings.MINIMUM_DEPOSIT_AMOUNT))
    with db.atomic():
        acc = lock(request.api_user.account)[request.api_user.account.pk]
        if not acc.initial_deposit_date:
            acc.initial_deposit_date = date.today()
            acc.interest_start_date = date.today() + relativedelta(months=12 // acc.account_type.interest_calculation_per_year)
        acc.balance += amount
        acc.save()
        t = record(acc, amount, DEPOSIT, str(d.get('note', '')) or 'Cash deposit')
    return JsonResponse({'message': f'₹{amount:,.2f} deposited successfully.', 'transaction': tx_json(t)})


@api(['POST'])
@auth
def withdraw(request):
    d = body(request)
    require_kyc(request.api_user)
    amount = money(d.get('amount'), Decimal(settings.MINIMUM_WITHDRAWAL_AMOUNT))
    with db.atomic():
        acc = lock(request.api_user.account)[request.api_user.account.pk]
        limit = acc.account_type.maximum_withdrawal_amount
        if amount > limit:
            raise ApiError(f'Maximum withdrawal is ₹{limit:,.2f}.', fields={'amount': f'Max ₹{limit:,.2f}'})
        if amount > acc.balance:
            raise ApiError('Insufficient balance.', fields={'amount': 'Insufficient balance'})
        acc.balance -= amount
        acc.save()
        t = record(acc, amount, WITHDRAWAL, str(d.get('note', '')) or 'Cash withdrawal')
    return JsonResponse({'message': f'₹{amount:,.2f} withdrawn successfully.', 'transaction': tx_json(t)})


def resolve_target(ident):
    """Find a receiving account by account number, 10-digit mobile number, or UPI id (mobile@securebank).
    Mobile numbers start with 6-9; our 10-digit account numbers start with 1, so the two never clash."""
    s = str(ident).strip().lower()
    if s.endswith('@securebank'):
        s = s.split('@')[0]
    if not s.isdigit():
        return None
    if len(s) == 10 and s[0] in '6789':
        k = KYCProfile.objects.select_related('user__account').filter(phone=s).first()
        return k.user.account if k else None
    return UserBankAccount.objects.filter(account_no=int(s)).first()


def perform_transfer(me_acc, target, amount, note='', channel='APP'):
    require_kyc(me_acc.user)
    tk = getattr(target.user, 'kyc', None)
    if not tk or tk.kyc_status != 'VERIFIED':
        raise ApiError('The recipient account is not active yet.', fields={'to_account_no': 'Recipient not active'})
    if target.pk == me_acc.pk:
        raise ApiError('You cannot transfer to your own account.', fields={'to_account_no': 'Choose another account'})
    with db.atomic():
        locked = lock(me_acc, target)
        src, dst = locked[me_acc.pk], locked[target.pk]
        limit = src.account_type.maximum_withdrawal_amount
        if amount > limit:
            raise ApiError(f'Maximum per transfer is ₹{limit:,.2f}.', fields={'amount': f'Max ₹{limit:,.2f}'})
        if amount > src.balance:
            raise ApiError('Insufficient balance.', fields={'amount': 'Insufficient balance'})
        src.balance -= amount
        dst.balance += amount
        src.save()
        dst.save()
        n = f' · {note}' if note else ''
        t = record(src, amount, WITHDRAWAL, f'Transfer to A/c {dst.account_no}{n}', channel)
        record(dst, amount, DEPOSIT, f'Transfer from A/c {src.account_no}{n}', channel)
    return t


@api(['POST'])
@auth
def transfer(request):
    d = body(request)
    amount = money(d.get('amount'), Decimal(settings.MINIMUM_WITHDRAWAL_AMOUNT))
    target = resolve_target(d.get('to_account_no', ''))
    if not target:
        raise ApiError('Recipient not found. Use account number, mobile number or UPI id.',
                       fields={'to_account_no': 'Recipient not found'})
    if amount > Decimal(settings.HIGH_VALUE_TRANSFER):  # high-value transfers need a fresh SMS OTP
        phone = request.api_user.kyc.phone
        if not d.get('otp'):
            out = otp_payload(phone, issue_otp(phone, 'transfer'))
            out['message'] = 'OTP required for transfers above ₹10,000. ' + out['message']
            return JsonResponse({'otp_required': True, **out}, status=202)
        verify_otp(phone, d.get('otp'), 'transfer')
    t = perform_transfer(request.api_user.account, target, amount, str(d.get('note', '')).strip())
    return JsonResponse({'message': f'₹{amount:,.2f} sent to {target.user.first_name} (A/c {target.account_no}).',
                         'transaction': tx_json(t)})


@api(['POST'])
@auth
def assistant(request):
    d = body(request)
    key = f'assistant:{request.api_user.pk}'  # 20 questions / minute / customer (protects the Claude API bill)
    cache.add(key, 0, 60)
    if cache.incr(key) > 20:
        raise ApiError('Too many questions. Please wait a minute.', 429)
    text, action = answer(request.api_user.account, d.get('message'), d.get('history'))
    return JsonResponse({'message': text, 'action': action})
