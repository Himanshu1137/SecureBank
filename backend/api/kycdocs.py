"""KYC document upload (customer) + KYC review and bulk approvals (staff)."""
import uuid
from pathlib import Path

from django.conf import settings
from django.db import transaction as db
from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
from django.utils import timezone

from services.models import CardApplication, ChequeBookRequest, FixedDeposit, KYCDocument, KYCProfile, Loan

from .errors import ApiError
from .features import apply_loan_decision, cheque_json, loan_json
from .more import issue_card
from .views import api, auth, body, staff_auth

KINDS = {'AADHAAR': 'Aadhaar card', 'PAN': 'PAN card', 'PHOTO': 'Passport photo'}
MAGIC = [(b'\xff\xd8\xff', 'image/jpeg', '.jpg'), (b'\x89PNG\r\n\x1a\n', 'image/png', '.png'), (b'%PDF', 'application/pdf', '.pdf')]


def doc_json(d):
    return {'id': d.id, 'kind': d.kind, 'name': d.original_name, 'size': d.size, 'type': d.content_type, 'uploaded': d.uploaded.isoformat(), 'viewed': bool(d.viewed_at)}


def sniff(data):
    for sig, ctype, ext in MAGIC:
        if data.startswith(sig):
            return ctype, ext
    return None, None


@api(['POST'])
@auth
def upload_doc(request):
    kind = str(request.POST.get('kind', '')).upper()
    f = request.FILES.get('file')
    if kind not in KINDS:
        raise ApiError('Choose a document type: Aadhaar, PAN or Photo.', fields={'kind': 'Required'})
    if not f:
        raise ApiError('Choose a file to upload.', fields={'file': 'Required'})
    if f.size > settings.KYC_MAX_BYTES:
        raise ApiError('File is too large. Maximum size is 2 MB.', fields={'file': 'Max 2 MB'})
    data = f.read()
    ctype, ext = sniff(data)
    if not ctype:  # real content check, not just the file extension
        raise ApiError('Only JPG, PNG or PDF files are allowed.', fields={'file': 'JPG, PNG or PDF only'})
    k = getattr(request.api_user, 'kyc', None)
    if k and k.kyc_status == 'VERIFIED':
        raise ApiError('Your KYC is already verified. Contact the bank to change documents.', 403)
    folder = Path(settings.KYC_DOC_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex + ext
    (folder / name).write_bytes(data)
    with db.atomic():
        for old in KYCDocument.objects.filter(user=request.api_user, kind=kind):  # replace previous upload of same kind
            (folder / old.stored_name).unlink(missing_ok=True)
            old.delete()
        d = KYCDocument.objects.create(user=request.api_user, kind=kind, stored_name=name, content_type=ctype, size=len(data),
                                       original_name=''.join(c for c in Path(f.name).name if c.isalnum() or c in '._- ')[:120] or 'document' + ext)
        if k and k.kyc_status == 'REJECTED':  # re-submission goes back to review
            k.kyc_status, k.kyc_note = 'PENDING', ''
            k.save()
    return JsonResponse({'message': f'{KINDS[kind]} uploaded.', 'document': doc_json(d)})


@api(['GET'])
@auth
def my_docs(request):
    k = getattr(request.api_user, 'kyc', None)
    return JsonResponse({'documents': [doc_json(d) for d in request.api_user.kyc_docs.order_by('kind')],
                         'kyc_status': k.kyc_status if k else None, 'kyc_note': k.kyc_note if k else ''})


# ---------------- staff ----------------
def kyc_row(k, docs):
    u = k.user
    return {'id': k.id, 'user_id': u.pk, 'name': f'{u.first_name} {u.last_name}', 'email': u.email, 'phone': k.phone, 'aadhaar_masked': f'XXXX XXXX {k.aadhaar_last4}',
            'status': k.kyc_status, 'note': k.kyc_note, 'applied': u.date_joined.date().isoformat(), 'docs': [doc_json(d) for d in docs.get(u.pk, [])]}


@api(['GET'])
@staff_auth
def admin_kyc(request):
    qs = KYCProfile.objects.select_related('user').order_by('-id')
    if request.GET.get('status'):
        qs = qs.filter(kyc_status=request.GET['status'])
    rows = list(qs[:200])
    docs = {}
    for d in KYCDocument.objects.filter(user_id__in=[k.user_id for k in rows]):
        docs.setdefault(d.user_id, []).append(d)
    return JsonResponse([kyc_row(k, docs) for k in rows], safe=False)


def decide(k, action, reason=''):
    if action == 'approve':
        aad = KYCDocument.objects.filter(user=k.user, kind='AADHAAR').first()
        if not aad:
            raise ApiError('Cannot approve: no Aadhaar document uploaded.')
        if settings.KYC_REQUIRE_REVIEW and not aad.viewed_at:
            raise ApiError('Open and review the Aadhaar document before approving.')
        k.kyc_status, k.kyc_note = 'VERIFIED', ''
    elif action == 'reject':
        k.kyc_status, k.kyc_note = 'REJECTED', (reason or 'Documents not clear / not valid. Please upload again.')[:160]
    else:
        raise ApiError('Action must be approve or reject.')
    k.save()


@api(['POST'])
@staff_auth
def admin_kyc_decide(request):
    d = body(request)
    k = KYCProfile.objects.select_related('user').filter(pk=d.get('id') or 0).first()
    if not k:
        raise ApiError('KYC record not found.', 404)
    decide(k, d.get('action'), str(d.get('reason', '')).strip())
    return JsonResponse({'message': f'KYC of {k.user.first_name} {k.kyc_status.lower()}.'})


@api(['POST'])
@staff_auth
def admin_kyc_approve_all(request):
    ok = skipped = 0
    with db.atomic():
        for k in KYCProfile.objects.select_related('user').filter(kyc_status='PENDING'):
            try:
                with db.atomic():
                    decide(k, 'approve')
                ok += 1
            except ApiError:
                skipped += 1  # Aadhaar document missing or not opened by staff yet
    return JsonResponse({'message': f'{ok} KYC approved' + (f', {skipped} skipped (Aadhaar document missing or not opened for review yet).' if skipped else '.'), 'count': ok})


@api(['POST'])
@staff_auth
def admin_loans_approve_all(request):
    with db.atomic():
        loans = list(Loan.objects.select_for_update().filter(status='PENDING').order_by('id'))
        for l in loans:
            apply_loan_decision(l, 'approve')
    return JsonResponse({'message': f'{len(loans)} loan(s) approved and disbursed.', 'count': len(loans)})


@api(['POST'])
@staff_auth
def admin_cheques_dispatch_all(request):
    n = ChequeBookRequest.objects.filter(status='REQUESTED').update(status='DISPATCHED')
    return JsonResponse({'message': f'{n} cheque book request(s) marked as dispatched.', 'count': n})


@api(['GET'])
@staff_auth
def admin_doc_view(request, doc_id):
    d = KYCDocument.objects.filter(pk=doc_id).first()
    path = Path(settings.KYC_DOC_DIR) / (d.stored_name if d else 'missing')
    if not d or not path.is_file():
        raise ApiError('Document not found.', 404)
    if not d.viewed_at:
        d.viewed_at = timezone.now()
        d.save(update_fields=['viewed_at'])
    resp = HttpResponse(path.read_bytes(), content_type=d.content_type)
    resp['Content-Disposition'] = f'inline; filename="{d.kind.lower()}-{d.id}{path.suffix}"'
    resp['X-Content-Type-Options'] = 'nosniff'
    resp['Content-Security-Policy'] = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"
    return resp


@api(['GET'])
@staff_auth
def admin_customer_detail(request, user_id):
    """Everything the bank stores about one customer (the full Aadhaar number is never stored, only the last 4 digits)."""
    User = get_user_model()
    u = User.objects.select_related('account__account_type').filter(pk=user_id, is_staff=False).first()
    if not u or not hasattr(u, 'account'):
        raise ApiError('Customer not found.', 404)
    acc, k = u.account, getattr(u, 'kyc', None)
    addr, card = getattr(u, 'address', None), getattr(acc, 'card', None)
    tx = acc.transactions
    sums = {t: str(tx.filter(transaction_type=t).aggregate(s=Sum('amount'))['s'] or 0) for t in (1, 2, 3)}
    docs = {}
    for d in u.kyc_docs.all():
        docs.setdefault(u.pk, []).append(d)
    return JsonResponse({
        'customer': {'id': u.id, 'name': f'{u.first_name} {u.last_name}', 'email': u.email, 'active': u.is_active, 'joined': u.date_joined.isoformat(),
                     'gender': acc.gender, 'birth_date': acc.birth_date.isoformat() if acc.birth_date else None,
                     'address': {'street_address': addr.street_address, 'city': addr.city, 'postal_code': addr.postal_code, 'country': addr.country} if addr else None},
        'kyc': {'id': k.id, 'status': k.kyc_status, 'note': k.kyc_note, 'phone': k.phone, 'phone_verified': k.phone_verified, 'aadhaar_masked': f'XXXX XXXX {k.aadhaar_last4}',
                'consent_at': k.aadhaar_consent_at.isoformat()} if k else None,
        'documents': [doc_json(d) for d in u.kyc_docs.order_by('kind')],
        'account': {'account_no': acc.account_no, 'type': acc.account_type.name, 'interest_rate': str(acc.account_type.annual_interest_rate), 'balance': str(acc.balance),
                    'withdraw_limit': str(acc.account_type.maximum_withdrawal_amount), 'initial_deposit_date': acc.initial_deposit_date.isoformat() if acc.initial_deposit_date else None,
                    'upi_id': f'{k.phone}@securebank' if k else None, 'total_deposits': sums[1], 'total_withdrawals': sums[2], 'total_interest': sums[3], 'transactions': tx.count()},
        'card_application': (lambda x: {'id': x.id, 'variant': x.variant, 'status': x.status, 'note': x.note, 'created': x.created.isoformat()} if x else None)(acc.card_applications.order_by('-id').first()),
        'card': {'variant': card.variant, 'masked_number': f'XXXX XXXX XXXX {card.number[-4:]}', 'expiry': card.expiry, 'status': card.status, 'daily_atm_limit': str(card.daily_atm_limit),
                 'online_enabled': card.online_enabled, 'pin_set': bool(card.pin_hash)} if card else None,
        'fixed_deposits': [{'id': f.id, 'principal': str(f.principal), 'rate': str(f.rate), 'months': f.months, 'maturity_date': f.maturity_date.isoformat(), 'status': f.status}
                           for f in acc.fds.order_by('-id')],
        'loans': [loan_json(l) for l in acc.loans.order_by('-id')],
        'cheque_requests': [cheque_json(c) for c in acc.cheque_requests.order_by('-id')],
        'payments_count': acc.payments.count(), 'beneficiaries_count': acc.beneficiaries.count(),
        'recent_transactions': [{'id': t.id, 'type': t.get_transaction_type_display(), 'amount': str(t.amount), 'balance_after': str(t.balance_after_transaction),
                                 'description': t.description, 'channel': t.channel, 'timestamp': t.timestamp.isoformat()} for t in tx.order_by('-timestamp', '-id')[:25]]})


# ---------------- debit card applications ----------------
def card_row(a):
    u = a.account.user
    return {'id': a.id, 'user_id': u.pk, 'name': f'{u.first_name} {u.last_name}', 'email': u.email, 'phone': getattr(getattr(u, 'kyc', None), 'phone', ''),
            'account_no': a.account.account_no, 'variant': a.variant, 'status': a.status, 'note': a.note, 'applied': a.created.date().isoformat(),
            'kyc_status': getattr(getattr(u, 'kyc', None), 'kyc_status', '')}


def decide_card(app, action, reason=''):
    if app.status != 'PENDING':
        raise ApiError('This application is already processed.')
    if action == 'approve':
        k = getattr(app.account.user, 'kyc', None)
        if k and k.kyc_status != 'VERIFIED':
            raise ApiError('Customer KYC is not verified.')
        if hasattr(app.account, 'card'):
            raise ApiError('Customer already has a debit card.')
        issue_card(app.account, app.variant)  # the card is created only here
        app.status = 'APPROVED'
    elif action == 'reject':
        app.status, app.note = 'REJECTED', (reason or 'Application rejected by the bank.')[:160]
    else:
        raise ApiError('Action must be approve or reject.')
    app.decided_at = timezone.now()
    app.save()


@api(['GET'])
@staff_auth
def admin_cards(request):
    qs = CardApplication.objects.select_related('account__user').order_by('-id')
    if request.GET.get('status'):
        qs = qs.filter(status=request.GET['status'])
    return JsonResponse([card_row(a) for a in qs[:200]], safe=False)


@api(['POST'])
@staff_auth
def admin_card_decide(request):
    d = body(request)
    app = CardApplication.objects.select_related('account__user').filter(pk=d.get('id') or 0).first()
    if not app:
        raise ApiError('Application not found.', 404)
    with db.atomic():
        decide_card(app, d.get('action'), str(d.get('reason', '')).strip())
    return JsonResponse({'message': f'Card application of {app.account.user.first_name} {app.status.lower()}.'})


@api(['POST'])
@staff_auth
def admin_cards_approve_all(request):
    ok = skipped = 0
    for app in CardApplication.objects.select_related('account__user').filter(status='PENDING').order_by('id'):
        try:
            with db.atomic():
                decide_card(app, 'approve')
            ok += 1
        except ApiError:
            skipped += 1
    return JsonResponse({'message': f'{ok} debit card(s) approved and created' + (f', {skipped} skipped.' if skipped else '.'), 'count': ok})
