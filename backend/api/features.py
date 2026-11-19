"""Bill payments & recharge, beneficiaries, loans/EMI, cheque book, PDF statement, admin dashboard."""
import random
import re
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction as db
from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
from django.utils import timezone

from accounts.models import UserBankAccount
from services.models import CardApplication, KYCProfile, Beneficiary, ChequeBookRequest, DebitCard, FixedDeposit, Loan, Payment
from transactions.constants import DEPOSIT, WITHDRAWAL
from transactions.models import Transaction

from .assistant import inr
from .errors import ApiError
from .more import check_mpin
from .pdfgen import make_pdf
from .views import api, auth, body, lock, money, record, require_kyc, resolve_target, staff_auth, tx_json

User = get_user_model()

# ---------------- Beneficiaries ----------------
def ben_json(b):
    return {'id': b.id, 'name': b.name, 'identifier': b.identifier}


@api(['GET'])
@auth
def beneficiaries(request):
    return JsonResponse([ben_json(b) for b in request.api_user.account.beneficiaries.order_by('name')], safe=False)


@api(['POST'])
@auth
def beneficiary_add(request):
    d = body(request)
    ident = str(d.get('identifier', '')).strip().lower()
    target = resolve_target(ident)
    if not target:
        raise ApiError('No SecureBank account found for this account number / mobile / UPI id.', fields={'identifier': 'Not found'})
    if target.pk == request.api_user.account.pk:
        raise ApiError('You cannot add your own account.', fields={'identifier': 'Own account'})
    b, created = Beneficiary.objects.get_or_create(account=request.api_user.account, identifier=ident,
                                                   defaults={'name': (str(d.get('name', '')).strip() or target.user.get_full_name() or target.user.first_name)[:60]})
    return JsonResponse({'message': f'{b.name} added to beneficiaries.' if created else 'Already in your beneficiaries.', 'beneficiary': ben_json(b)})


@api(['POST'])
@auth
def beneficiary_delete(request):
    Beneficiary.objects.filter(pk=body(request).get('id') or 0, account=request.api_user.account).delete()
    return JsonResponse({'message': 'Beneficiary removed.'})


# ---------------- Bill payments & recharge ----------------
BILLERS = {'MOBILE': ['Jio', 'Airtel', 'Vi', 'BSNL'], 'DTH': ['Tata Play', 'Airtel Digital TV', 'Dish TV', 'Sun Direct'],
           'ELECTRICITY': ['UPPCL', 'BSES Delhi', 'MSEDCL', 'TNEB', 'BESCOM'], 'WATER': ['Delhi Jal Board', 'BWSSB', 'MCGM Water'],
           'GAS': ['Indane', 'HP Gas', 'Bharat Gas', 'Mahanagar Gas'], 'BROADBAND': ['Jio Fiber', 'Airtel Xstream', 'ACT Fibernet', 'BSNL Broadband']}
PLANS = [{'amount': 199, 'info': '28 days · 1.5 GB/day'}, {'amount': 299, 'info': '28 days · 2 GB/day'},
         {'amount': 479, 'info': '56 days · 1.5 GB/day'}, {'amount': 719, 'info': '84 days · 1.5 GB/day'}]


def pay_json(p):
    return {'id': p.id, 'category': p.category, 'biller': p.biller, 'consumer_no': p.consumer_no, 'amount': str(p.amount),
            'reference': p.reference, 'timestamp': p.created.isoformat()}


@api(['GET'])
def billers(request):
    return JsonResponse({'billers': BILLERS, 'plans': PLANS})


@api(['GET'])
@auth
def payments(request):
    return JsonResponse([pay_json(p) for p in request.api_user.account.payments.order_by('-id')[:50]], safe=False)


@api(['POST'])
@auth
def pay(request):
    d = body(request)
    require_kyc(request.api_user)
    cat, biller, cno = str(d.get('category', '')).upper(), str(d.get('biller', '')), str(d.get('consumer_no', '')).strip()
    if cat not in BILLERS or biller not in BILLERS[cat]:
        raise ApiError('Choose a valid category and biller.')
    if cat == 'MOBILE' and not re.fullmatch(r'[6-9]\d{9}', cno):
        raise ApiError('Enter a valid 10-digit mobile number.', fields={'consumer_no': 'Invalid mobile number'})
    if cat != 'MOBILE' and not re.fullmatch(r'[A-Za-z0-9-]{5,20}', cno):
        raise ApiError('Enter a valid consumer / subscriber number (5-20 letters or digits).', fields={'consumer_no': 'Invalid number'})
    amount = money(d.get('amount'), Decimal('10') if cat in ('MOBILE', 'DTH') else Decimal('1'))
    if amount > 100000:
        raise ApiError('Maximum payment is ₹1,00,000.', fields={'amount': 'Too high'})
    check_mpin(request.api_user, d.get('mpin'))
    with db.atomic():
        acc = lock(request.api_user.account)[request.api_user.account.pk]
        if amount > acc.balance:
            raise ApiError('Insufficient balance.', fields={'amount': 'Insufficient balance'})
        acc.balance -= amount
        acc.save()
        ref = 'SB' + ''.join(random.SystemRandom().choice('0123456789') for _ in range(10))
        p = Payment.objects.create(account=acc, category=cat, biller=biller, consumer_no=cno, amount=amount, reference=ref)
        record(acc, amount, WITHDRAWAL, f'{biller} {cat.title()} {cno}', 'BILL')
    return JsonResponse({'message': f'{inr(amount)} paid to {biller}. Ref {ref}.', 'payment': pay_json(p)})


# ---------------- Loans ----------------
RULES = {'PERSONAL': (Decimal('11.5'), 10000, 500000, 6, 60), 'HOME': (Decimal('8.5'), 100000, 10000000, 60, 360),
         'EDUCATION': (Decimal('9.5'), 50000, 2000000, 12, 120), 'VEHICLE': (Decimal('9.0'), 50000, 1500000, 12, 84)}


def calc_emi(principal, rate, months):
    r = Decimal(rate) / 1200
    return (principal * r * (1 + r) ** months / ((1 + r) ** months - 1)).quantize(Decimal('0.01'))


def loan_json(l):
    left = l.months - l.paid_emis
    return {'id': l.id, 'kind': l.kind, 'principal': str(l.principal), 'rate': str(l.rate), 'months': l.months, 'emi': str(l.emi),
            'status': l.status, 'paid_emis': l.paid_emis, 'remaining_emis': left if l.status == 'ACTIVE' else 0,
            'outstanding': str((l.emi * left).quantize(Decimal('0.01'))) if l.status == 'ACTIVE' else '0.00',
            'applied': l.created.date().isoformat(), 'account_no': l.account.account_no}


@api(['GET'])
@auth
def loans(request):
    return JsonResponse({'rules': {k: {'rate': str(v[0]), 'min': v[1], 'max': v[2], 'min_months': v[3], 'max_months': v[4]} for k, v in RULES.items()},
                         'loans': [loan_json(l) for l in request.api_user.account.loans.order_by('-id')]})


@api(['POST'])
@auth
def loan_apply(request):
    d = body(request)
    require_kyc(request.api_user)
    kind = str(d.get('kind', '')).upper()
    if kind not in RULES:
        raise ApiError('Choose a loan type.', fields={'kind': 'Required'})
    rate, lo, hi, mlo, mhi = RULES[kind]
    amount = money(d.get('amount'), Decimal(lo))
    if amount > hi:
        raise ApiError(f'Maximum {kind.title()} loan is ₹{hi:,}.', fields={'amount': f'Max ₹{hi:,}'})
    try:
        months = int(d.get('months'))
    except (TypeError, ValueError):
        months = 0
    if not mlo <= months <= mhi:
        raise ApiError(f'Tenure must be {mlo}-{mhi} months.', fields={'months': f'{mlo}-{mhi} months'})
    income = money(d.get('income'), Decimal('1000'))
    check_mpin(request.api_user, d.get('mpin'))
    acc = request.api_user.account
    if acc.loans.filter(status='PENDING', kind=kind).exists():
        raise ApiError(f'You already have a pending {kind.title()} loan application.')
    emi = calc_emi(amount, rate, months)
    if emi > income / 2:
        raise ApiError(f'EMI {inr(emi)} is more than 50% of your monthly income. Reduce the amount or increase tenure.', fields={'amount': 'EMI too high'})
    loan = Loan.objects.create(account=acc, kind=kind, principal=amount, rate=rate, months=months, emi=emi, monthly_income=income)
    return JsonResponse({'message': f'Loan application submitted. EMI would be {inr(emi)}. A bank officer will review it.', 'loan': loan_json(loan)})


@api(['POST'])
@auth
def loan_emi(request):
    d = body(request)
    require_kyc(request.api_user)
    check_mpin(request.api_user, d.get('mpin'))
    with db.atomic():
        acc = lock(request.api_user.account)[request.api_user.account.pk]
        loan = Loan.objects.select_for_update().filter(pk=d.get('id') or 0, account=acc, status='ACTIVE').first()
        if not loan:
            raise ApiError('Active loan not found.', 404)
        if loan.emi > acc.balance:
            raise ApiError('Insufficient balance to pay the EMI.')
        acc.balance -= loan.emi
        acc.save()
        loan.paid_emis += 1
        if loan.paid_emis >= loan.months:
            loan.status = 'CLOSED'
        loan.save()
        record(acc, loan.emi, WITHDRAWAL, f'Loan #{loan.id} EMI {loan.paid_emis}/{loan.months}', 'LOAN')
    return JsonResponse({'message': f'EMI of {inr(loan.emi)} paid ({loan.paid_emis}/{loan.months}).' + (' Loan fully repaid 🎉' if loan.status == 'CLOSED' else '')})


# ---------------- Cheque book ----------------
def cheque_json(c):
    return {'id': c.id, 'leaves': c.leaves, 'status': c.status, 'requested': c.created.date().isoformat(), 'account_no': c.account.account_no}


@api(['GET'])
@auth
def cheques(request):
    return JsonResponse([cheque_json(c) for c in request.api_user.account.cheque_requests.order_by('-id')], safe=False)


@api(['POST'])
@auth
def cheque_request(request):
    d = body(request)
    require_kyc(request.api_user)
    check_mpin(request.api_user, d.get('mpin'))
    try:
        leaves = int(d.get('leaves'))
    except (TypeError, ValueError):
        leaves = 0
    if leaves not in (25, 50):
        raise ApiError('Choose 25 or 50 leaves.', fields={'leaves': '25 or 50'})
    acc = request.api_user.account
    if acc.cheque_requests.filter(status='REQUESTED').exists():
        raise ApiError('You already have a cheque book request in progress.')
    c = ChequeBookRequest.objects.create(account=acc, leaves=leaves)
    return JsonResponse({'message': f'Cheque book ({leaves} leaves) requested. It will be posted to your registered address.', 'cheque': cheque_json(c)})


# ---------------- PDF statement ----------------
@api(['GET'])
@auth
def statement_pdf(request):
    u, acc = request.api_user, request.api_user.account
    head = ['SECUREBANK - ACCOUNT STATEMENT', '=' * 91, f'Name     : {u.first_name} {u.last_name}', f'Account  : {acc.account_no} ({acc.account_type.name})',
            f'IFSC     : SECB0000001   Mobile: {getattr(getattr(u, "kyc", None), "phone", "-")}',
            f'Balance  : {inr(acc.balance)}   Generated: {timezone.localtime():%d-%b-%Y %H:%M}', '=' * 91,
            f'{"Date":<16} {"Type":<10} {"Channel":<8} {"Description":<28} {"Amount":>12} {"Balance":>12}', '-' * 91]
    rows = []
    for t in acc.transactions.order_by('-timestamp', '-id')[:1000]:
        sign = '-' if t.transaction_type == WITHDRAWAL else '+'
        rows.append(f'{timezone.localtime(t.timestamp):%d-%b-%y %H:%M}  {t.get_transaction_type_display()[:10]:<10} {t.channel[:8]:<8} {t.description[:28]:<28} '
                    f'{sign}{t.amount:>11,.2f} {t.balance_after_transaction:>12,.2f}')
    if not rows:
        rows = ['No transactions.']
    resp = HttpResponse(make_pdf(head, rows), content_type='application/pdf')
    resp['Content-Disposition'] = 'attachment; filename="securebank-statement.pdf"'
    return resp


# ---------------- Admin dashboard (staff only) ----------------
@api(['GET'])
@staff_auth
def admin_summary(request):
    today = timezone.localdate()
    return JsonResponse({
        'customers': UserBankAccount.objects.count(), 'accounts_opened': UserBankAccount.objects.count(),
        'new_accounts_today': User.objects.filter(is_staff=False, date_joined__date=today).count(),
        'kyc_pending': KYCProfile.objects.filter(kyc_status='PENDING').count(), 'kyc_verified': KYCProfile.objects.filter(kyc_status='VERIFIED').count(),
        'kyc_rejected': KYCProfile.objects.filter(kyc_status='REJECTED').count(), 'cards_issued': DebitCard.objects.count(), 'card_applications_pending': CardApplication.objects.filter(status='PENDING').count(),
        'total_deposits': str(UserBankAccount.objects.aggregate(s=Sum('balance'))['s'] or 0),
        'transactions_today': Transaction.objects.filter(timestamp__date=today).count(),
        'volume_today': str(Transaction.objects.filter(timestamp__date=today).aggregate(s=Sum('amount'))['s'] or 0),
        'pending_loans': Loan.objects.filter(status='PENDING').count(), 'pending_kyc': KYCProfile.objects.filter(kyc_status='PENDING').count(),
        'active_loans': Loan.objects.filter(status='ACTIVE').count(),
        'pending_cheques': ChequeBookRequest.objects.filter(status='REQUESTED').count(),
        'blocked_cards': DebitCard.objects.filter(status='BLOCKED').count(),
        'fd_total': str(FixedDeposit.objects.filter(status='OPEN').aggregate(s=Sum('principal'))['s'] or 0),
        'bill_payments': Payment.objects.count()})


@api(['GET'])
@staff_auth
def admin_loans(request):
    qs = Loan.objects.select_related('account').order_by('-id')
    if request.GET.get('status'):
        qs = qs.filter(status=request.GET['status'])
    return JsonResponse([{**loan_json(l), 'income': str(l.monthly_income)} for l in qs[:100]], safe=False)


def apply_loan_decision(loan, action):
    if action == 'approve':
        acc = lock(loan.account)[loan.account.pk]
        acc.balance += loan.principal
        acc.save()
        record(acc, loan.principal, DEPOSIT, f'Loan #{loan.id} ({loan.kind.title()}) disbursed', 'LOAN')
        loan.status = 'ACTIVE'
    elif action == 'reject':
        loan.status = 'REJECTED'
    else:
        raise ApiError('Action must be approve or reject.')
    loan.save()


@api(['POST'])
@staff_auth
def admin_loan_decide(request):
    d = body(request)
    with db.atomic():
        loan = Loan.objects.select_for_update().filter(pk=d.get('id') or 0, status='PENDING').first()
        if not loan:
            raise ApiError('Pending loan not found.', 404)
        apply_loan_decision(loan, d.get('action'))
    return JsonResponse({'message': f'Loan #{loan.id} {loan.status.lower()}.'})


@api(['GET'])
@staff_auth
def admin_cheques(request):
    return JsonResponse([cheque_json(c) for c in ChequeBookRequest.objects.select_related('account').order_by('-id')[:100]], safe=False)


@api(['POST'])
@staff_auth
def admin_cheque_dispatch(request):
    n = ChequeBookRequest.objects.filter(pk=body(request).get('id') or 0, status='REQUESTED').update(status='DISPATCHED')
    if not n:
        raise ApiError('Request not found.', 404)
    return JsonResponse({'message': 'Cheque book marked as dispatched.'})


@api(['GET'])
@staff_auth
def admin_customers(request):
    rows = UserBankAccount.objects.select_related('user', 'user__kyc').order_by('-id')[:500]
    return JsonResponse([{'id': a.user_id, 'name': f'{a.user.first_name} {a.user.last_name}', 'email': a.user.email,
                          'phone': getattr(getattr(a.user, 'kyc', None), 'phone', ''), 'account_no': a.account_no,
                          'balance': str(a.balance), 'active': a.user.is_active, 'opened': a.user.date_joined.date().isoformat(),
                          'kyc_status': getattr(getattr(a.user, 'kyc', None), 'kyc_status', ''),
                          'card_issued': hasattr(a, 'card'),
                          'card_status': 'ISSUED' if hasattr(a, 'card') else ('PENDING' if a.card_applications.filter(status='PENDING').exists() else 'NONE')} for a in rows], safe=False)


@api(['POST'])
@staff_auth
def admin_customer_toggle(request):
    u = User.objects.filter(pk=body(request).get('id') or 0, is_staff=False).first()
    if not u:
        raise ApiError('Customer not found.', 404)
    u.is_active = not u.is_active
    u.save()
    return JsonResponse({'message': f'Account {"unfrozen" if u.is_active else "frozen"}.'})
