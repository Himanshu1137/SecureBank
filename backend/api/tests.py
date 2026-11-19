"""Automated test suite for SecureBank. Run with:  python manage.py test api
Each test's docstring starts with its ID and the requirement it covers (FR1-FR8, SEC)."""
import json
import tempfile
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import BankAccountType, UserBankAccount
from services.models import CardApplication, DebitCard, KYCProfile, PhoneOTP
from transactions.models import Transaction

from . import kyc
from .more import luhn_digit, whatsapp_reply
from .views import resolve_target

User = get_user_model()
TMP = tempfile.mkdtemp()
JPG = b'\xff\xd8\xff\xe0' + b'0' * 100
FAST = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], KYC_DOC_DIR=TMP)  # fast hashing, temp upload folder


@FAST
class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        BankAccountType.objects.create(name='Savings', annual_interest_rate=4, interest_calculation_per_year=4, maximum_withdrawal_amount=50000)
        User.objects.create_superuser(email='admin@t.in', password='Adm1n#Pass', first_name='Ad', last_name='Min')

    def setUp(self):
        cache.clear()
        self.c = Client()
        self.admin = self.login_staff()

    # ---- helpers ----
    def req(self, method, path, data=None, token=None, raw=None):
        h = {'HTTP_AUTHORIZATION': 'Bearer ' + token} if token else {}
        if method == 'GET':
            r = self.c.get('/api/' + path, **h)
        elif raw is not None:
            r = self.c.post('/api/' + path, raw, **h)
        else:
            r = self.c.post('/api/' + path, json.dumps(data or {}), content_type='application/json', **h)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, r

    def post(self, p, d=None, t=None): return self.req('POST', p, d, t)
    def get(self, p, t=None): return self.req('GET', p, None, t)
    def age(self): PhoneOTP.objects.update(created=timezone.now() - timedelta(seconds=60))

    def login_staff(self):
        return self.post('login/', {'email': 'admin@t.in', 'password': 'Adm1n#Pass'})[1]['token']

    def otp_token(self, phone):
        self.age()
        code = self.post('otp/send/', {'phone': phone})[1]['dev_otp']
        return self.post('otp/verify/', {'phone': phone, 'code': code})[1]['phone_token']

    def reg_data(self, i, **over):
        phone = f'91234{i:05d}'
        base = f'2345678{i:04d}'
        d = dict(first_name=f'User{i}', last_name='T', email=f'u{i}@t.in', password='Str0ng#Pass91', phone=phone, aadhaar=base + kyc.verhoeff_check_digit(base),
                 consent=True, mpin='2468', account_type=str(BankAccountType.objects.first().id), gender='F', birth_date='2000-01-01',
                 street_address='1 Road', city='Lucknow', postal_code='226001')
        d['phone_token'] = self.otp_token(d['phone'])
        d.update(over)
        return d

    def signup(self, i, docs=True, **over):
        d = self.reg_data(i, **over)
        s, r = self.post('register/', d)
        assert s == 201, r
        u = {'i': i, 'token': r['token'], 'user': r['user'], 'phone': d['phone'], 'email': d['email'], 'mpin': d['mpin'], 'acc_no': r['user']['account_no'], 'uid': r['user']['id']}
        if docs:
            self.upload(u['token'], 'AADHAAR', 'a.jpg', JPG)
        return u

    def upload(self, token, kind, name, content):
        r = self.c.post('/api/documents/upload/', {'kind': kind, 'file': SimpleUploadedFile(name, content)}, HTTP_AUTHORIZATION='Bearer ' + token)
        return r.status_code, r.json()

    def kyc_row(self, u):
        return [x for x in self.get('admin/kyc/', self.admin)[1] if x['email'] == u['email']][0]

    def open_doc(self, u):
        row = self.kyc_row(u)
        return self.c.get(f"/api/admin/documents/{row['docs'][0]['id']}/", HTTP_AUTHORIZATION='Bearer ' + self.admin).status_code

    def verified(self, i, **over):
        u = self.signup(i, **over)
        self.open_doc(u)
        self.post('admin/kyc/decide/', {'id': self.kyc_row(u)['id'], 'action': 'approve'}, self.admin)
        return u

    def fund(self, u, amount): UserBankAccount.objects.filter(account_no=u['acc_no']).update(balance=Decimal(amount))
    def balance(self, u): return UserBankAccount.objects.get(account_no=u['acc_no']).balance

    def with_card(self, i, variant='CLASSIC', pin='4682'):
        u = self.verified(i)
        self.post('card/apply/', {'variant': variant, 'mpin': u['mpin']}, u['token'])
        app = CardApplication.objects.filter(account__account_no=u['acc_no']).last()
        self.post('admin/cards/decide/', {'id': app.id, 'action': 'approve'}, self.admin)
        card = self.get('card/', u['token'])[1]
        self.post('card/set-pin/', {'pin': pin, 'mpin': u['mpin']}, u['token'])
        u['card'] = card['number']
        return u


# ============================ FR1: onboarding and KYC ============================
class OnboardingTests(Base):
    def test_01(self):
        """TC-01 | FR1 | OTP request rejects an invalid mobile number"""
        self.assertEqual(self.post('otp/send/', {'phone': '12345'})[0], 400)

    def test_02(self):
        """TC-02 | FR1 | OTP request succeeds for a valid number and returns the OTP in development mode"""
        s, r = self.post('otp/send/', {'phone': '9123400001'})
        self.assertEqual(s, 200); self.assertEqual(len(r['dev_otp']), 6)

    def test_03(self):
        """TC-03 | FR1 | A wrong OTP is rejected"""
        self.post('otp/send/', {'phone': '9123400001'})
        self.assertEqual(self.post('otp/verify/', {'phone': '9123400001', 'code': '000000'})[0], 400)

    def test_04(self):
        """TC-04 | FR1 | A correct OTP returns a phone-verification token"""
        code = self.post('otp/send/', {'phone': '9123400001'})[1]['dev_otp']
        self.assertIn('phone_token', self.post('otp/verify/', {'phone': '9123400001', 'code': code})[1])

    def test_05(self):
        """TC-05 | FR1 | An OTP expires after five minutes"""
        code = self.post('otp/send/', {'phone': '9123400001'})[1]['dev_otp']
        PhoneOTP.objects.update(created=timezone.now() - timedelta(minutes=6))
        self.assertEqual(self.post('otp/verify/', {'phone': '9123400001', 'code': code})[0], 400)

    def test_06(self):
        """TC-06 | FR1 | An OTP stops working after five wrong attempts"""
        code = self.post('otp/send/', {'phone': '9123400001'})[1]['dev_otp']
        for _ in range(6): self.post('otp/verify/', {'phone': '9123400001', 'code': '111111'})
        self.assertEqual(self.post('otp/verify/', {'phone': '9123400001', 'code': code})[0], 400)

    def test_07(self):
        """TC-07 | FR1 | A second OTP for the same purpose within 30 seconds is refused (HTTP 429)"""
        self.post('otp/send/', {'phone': '9123400001'})
        self.assertEqual(self.post('otp/send/', {'phone': '9123400001'})[0], 429)

    def test_08(self):
        """TC-08 | FR1 | No more than ten OTPs per hour are sent to one number"""
        for _ in range(10):
            self.age(); self.post('otp/send/', {'phone': '9123400001'})
        self.age()
        self.assertEqual(self.post('otp/send/', {'phone': '9123400001'})[0], 429)

    def test_09(self):
        """TC-09 | FR1 | Registration rejects an Aadhaar number with a wrong check digit"""
        d = self.reg_data(1); d['aadhaar'] = d['aadhaar'][:-1] + str((int(d['aadhaar'][-1]) + 1) % 10)
        s, r = self.post('register/', d); self.assertEqual(s, 400); self.assertIn('aadhaar', r['fields'])

    def test_10(self):
        """TC-10 | FR1 | Registration requires Aadhaar consent"""
        s, r = self.post('register/', self.reg_data(1, consent=False)); self.assertIn('consent', r['fields'])

    def test_11(self):
        """TC-11 | FR1 | Registration rejects an applicant younger than 18"""
        s, r = self.post('register/', self.reg_data(1, birth_date=str(timezone.now().year - 10) + '-01-01')); self.assertIn('birth_date', r['fields'])

    def test_12(self):
        """TC-12 | FR1 | Registration requires a verified phone token"""
        s, r = self.post('register/', self.reg_data(1, phone_token='bad')); self.assertIn('phone', r['fields'])

    def test_13(self):
        """TC-13 | FR1 | Registration creates an account in PENDING KYC state with no debit card"""
        u = self.signup(1, docs=False)
        self.assertEqual(KYCProfile.objects.get(user_id=u['uid']).kyc_status, 'PENDING')
        self.assertFalse(DebitCard.objects.filter(account__account_no=u['acc_no']).exists())

    def test_14(self):
        """TC-14 | FR1 | A second account on the same Aadhaar number is refused"""
        a = self.signup(1, docs=False)
        base = '2345678' + '0001'
        d = self.reg_data(2, aadhaar=base + kyc.verhoeff_check_digit(base))  # same Aadhaar as user 1
        s, r = self.post('register/', d); self.assertIn('aadhaar', r['fields'])

    def test_15(self):
        """TC-15 | SEC | The full Aadhaar number is never stored (only last 4 digits and a hash)"""
        d = self.reg_data(3); self.post('register/', d)
        k = KYCProfile.objects.get(phone=d['phone'])
        stored = ' '.join(str(getattr(k, f.name)) for f in k._meta.fields)
        self.assertNotIn(d['aadhaar'], stored); self.assertEqual(k.aadhaar_last4, d['aadhaar'][-4:])

    def test_16(self):
        """TC-16 | FR1 | Customer login requires a second step (OTP)"""
        u = self.signup(1, docs=False); self.age()
        s, r = self.post('login/', {'email': u['email'], 'password': 'Str0ng#Pass91'})
        self.assertTrue(r.get('otp_required')); self.assertNotIn('token', r)

    def test_17(self):
        """TC-17 | FR1 | Login succeeds with the correct OTP"""
        u = self.signup(1, docs=False); self.age()
        r = self.post('login/', {'email': u['email'], 'password': 'Str0ng#Pass91'})[1]
        self.assertIn('token', self.post('login/verify/', {'otp_token': r['otp_token'], 'code': r['dev_otp']})[1])

    def test_18(self):
        """TC-18 | FR1 | Login with a wrong password is refused (HTTP 401)"""
        u = self.signup(1, docs=False)
        self.assertEqual(self.post('login/', {'email': u['email'], 'password': 'wrong'})[0], 401)

    def test_19(self):
        """TC-19 | SEC | A protected endpoint refuses a request without a valid token (HTTP 401)"""
        self.assertEqual(self.get('me/')[0], 401); self.assertEqual(self.get('me/', 'forged')[0], 401)


# ============================ documents ============================
class DocumentTests(Base):
    def test_20(self):
        """TC-20 | FR1 | A valid JPEG document is accepted"""
        u = self.signup(1, docs=False); self.assertEqual(self.upload(u['token'], 'AADHAAR', 'a.jpg', JPG)[0], 200)

    def test_21(self):
        """TC-21 | SEC | A program renamed to .jpg is rejected (content check, not extension)"""
        u = self.signup(1, docs=False); self.assertEqual(self.upload(u['token'], 'AADHAAR', 'virus.jpg', b'MZ\x90\x00 evil')[0], 400)

    def test_22(self):
        """TC-22 | SEC | A file larger than 2 MB is rejected"""
        u = self.signup(1, docs=False); self.assertEqual(self.upload(u['token'], 'AADHAAR', 'big.jpg', JPG + b'0' * (2 * 1024 * 1024))[0], 400)

    def test_23(self):
        """TC-23 | FR1 | An unknown document type is rejected"""
        u = self.signup(1, docs=False); self.assertEqual(self.upload(u['token'], 'LICENSE', 'a.jpg', JPG)[0], 400)

    def test_24(self):
        """TC-24 | FR1 | Uploading the same document type again replaces the earlier file"""
        u = self.signup(1); self.upload(u['token'], 'AADHAAR', 'b.png', b'\x89PNG\r\n\x1a\n' + b'0' * 20)
        self.assertEqual(len(self.get('documents/', u['token'])[1]['documents']), 1)

    def test_25(self):
        """TC-25 | SEC | A customer cannot open the staff document endpoint (HTTP 403)"""
        u = self.signup(1); row = self.kyc_row(u)
        self.assertEqual(self.c.get(f"/api/admin/documents/{row['docs'][0]['id']}/", HTTP_AUTHORIZATION='Bearer ' + u['token']).status_code, 403)


# ============================ FR2: gating until approval ============================
class GateTests(Base):
    def setUp(self):
        super().setUp(); self.p = self.signup(1)  # pending customer with a document
        self.fund(self.p, 5000)

    def blocked(self, s_r): self.assertEqual(s_r[0], 403); self.assertIn('under review', s_r[1]['error'])

    def test_26(self):
        """TC-26 | FR2 | A pending customer can still log in and view the account and transactions"""
        self.assertEqual(self.get('me/', self.p['token'])[0], 200); self.assertEqual(self.get('transactions/', self.p['token'])[0], 200)
    def test_27(self): """TC-27 | FR2 | Deposit is blocked while KYC is pending"""; self.blocked(self.post('deposit/', {'amount': '500'}, self.p['token']))
    def test_28(self): """TC-28 | FR2 | Withdrawal is blocked while KYC is pending"""; self.blocked(self.post('withdraw/', {'amount': '100'}, self.p['token']))
    def test_29(self):
        """TC-29 | FR2 | A pending customer cannot transfer money"""
        v = self.verified(2); self.blocked(self.post('transfer/', {'to_account_no': str(v['acc_no']), 'amount': '100'}, self.p['token']))
    def test_30(self):
        """TC-30 | FR2 | Nobody can transfer money to a pending account"""
        v = self.verified(2); self.fund(v, 5000)
        s, r = self.post('transfer/', {'to_account_no': str(self.p['acc_no']), 'amount': '100'}, v['token']); self.assertEqual(s, 400); self.assertIn('not active', r['error'])
    def test_31(self): """TC-31 | FR2 | Bill payment is blocked while KYC is pending"""; self.blocked(self.post('pay/', {'category': 'MOBILE', 'biller': 'Jio', 'consumer_no': '9812345678', 'amount': '299', 'mpin': '2468'}, self.p['token']))
    def test_32(self): """TC-32 | FR2 | Opening a fixed deposit is blocked while KYC is pending"""; self.blocked(self.post('fd/open/', {'amount': '5000', 'months': 12, 'mpin': '2468'}, self.p['token']))
    def test_33(self): """TC-33 | FR2 | Applying for a loan is blocked while KYC is pending"""; self.blocked(self.post('loans/apply/', {'kind': 'PERSONAL', 'amount': '20000', 'months': 12, 'income': '50000', 'mpin': '2468'}, self.p['token']))
    def test_34(self): """TC-34 | FR2 | Requesting a cheque book is blocked while KYC is pending"""; self.blocked(self.post('cheque/request/', {'leaves': 25, 'mpin': '2468'}, self.p['token']))
    def test_35(self): """TC-35 | SEC | The customer-callable interest endpoint no longer exists (interest is credited by the Celery task only)"""; self.assertEqual(self.post('interest/', {}, self.p['token'])[0], 404)
    def test_36(self): """TC-36 | FR4 | Applying for a debit card is blocked while KYC is pending"""; self.blocked(self.post('card/apply/', {'variant': 'CLASSIC', 'mpin': '2468'}, self.p['token']))


# ============================ staff review ============================
class StaffReviewTests(Base):
    def test_37(self):
        """TC-37 | FR2 | Approval is refused until staff have opened the Aadhaar document"""
        u = self.signup(1); s, r = self.post('admin/kyc/decide/', {'id': self.kyc_row(u)['id'], 'action': 'approve'}, self.admin)
        self.assertEqual(s, 400); self.assertIn('Open and review', r['error'])
    def test_38(self):
        """TC-38 | FR2 | Approval succeeds after the document was opened and unlocks transactions"""
        u = self.verified(1); self.assertEqual(self.post('deposit/', {'amount': '500'}, u['token'])[0], 200)
    def test_39(self):
        """TC-39 | FR2 | Rejection stores a reason; re-uploading a document returns the account to PENDING"""
        u = self.signup(1); self.post('admin/kyc/decide/', {'id': self.kyc_row(u)['id'], 'action': 'reject', 'reason': 'Blurry'}, self.admin)
        self.assertEqual(self.get('me/', u['token'])[1]['kyc_status'], 'REJECTED')
        self.upload(u['token'], 'AADHAAR', 'a.jpg', JPG); self.assertEqual(self.get('me/', u['token'])[1]['kyc_status'], 'PENDING')
    def test_40(self):
        """TC-40 | FR2 | Approve-all approves only customers whose document was opened"""
        a = self.signup(1); b = self.signup(2); self.open_doc(a)
        self.post('admin/kyc/approve-all/', {}, self.admin)
        self.assertEqual(self.get('me/', a['token'])[1]['kyc_status'], 'VERIFIED'); self.assertEqual(self.get('me/', b['token'])[1]['kyc_status'], 'PENDING')
    def test_41(self):
        """TC-41 | SEC | Staff endpoints refuse a customer token (HTTP 403)"""
        u = self.verified(1); self.assertEqual(self.get('admin/kyc/', u['token'])[0], 403); self.assertEqual(self.get('admin/summary/', u['token'])[0], 403)
    def test_42(self):
        """TC-42 | FR4 | No debit card is created at KYC approval"""
        u = self.verified(1); self.assertFalse(self.get('me/', u['token'])[1]['card_issued']); self.assertFalse(self.get('card/', u['token'])[1]['issued'])


# ============================ FR3: money ============================
class MoneyTests(Base):
    def setUp(self):
        super().setUp(); self.a = self.verified(1); self.b = self.verified(2); self.fund(self.a, 100000)

    def test_43(self):
        """TC-43 | FR3 | A deposit raises the balance and writes a ledger entry with the balance after"""
        b0 = self.balance(self.b); self.post('deposit/', {'amount': '1000'}, self.b['token'])
        t = Transaction.objects.filter(account__account_no=self.b['acc_no']).latest('id'); self.assertEqual(self.balance(self.b), b0 + 1000); self.assertEqual(t.balance_after_transaction, b0 + 1000)
    def test_44(self): """TC-44 | FR3 | The minimum deposit (Rs. 10) is enforced"""; self.assertEqual(self.post('deposit/', {'amount': '5'}, self.b['token'])[0], 400)
    def test_45(self): """TC-45 | FR3 | The account-type withdrawal limit is enforced"""; self.assertEqual(self.post('withdraw/', {'amount': '60000'}, self.a['token'])[0], 400)
    def test_46(self): """TC-46 | FR3 | Withdrawal above the balance is rejected"""; self.assertEqual(self.post('withdraw/', {'amount': '100'}, self.b['token'])[0], 400)
    def test_47(self):
        """TC-47 | FR3 | Transfer by account number moves the money"""
        s, r = self.post('transfer/', {'to_account_no': str(self.b['acc_no']), 'amount': '1200'}, self.a['token']); self.assertEqual(s, 200); self.assertEqual(self.balance(self.b), 1200)
    def test_48(self):
        """TC-48 | FR3 | Transfer by mobile number moves the money"""
        self.assertEqual(self.post('transfer/', {'to_account_no': self.b['phone'], 'amount': '300'}, self.a['token'])[0], 200); self.assertEqual(self.balance(self.b), 300)
    def test_49(self):
        """TC-49 | FR3 | Transfer by UPI-style id (mobile@securebank) moves the money"""
        self.assertEqual(self.post('transfer/', {'to_account_no': self.b['phone'] + '@securebank', 'amount': '200'}, self.a['token'])[0], 200); self.assertEqual(self.balance(self.b), 200)
    def test_50(self): """TC-50 | FR3 | Transfer to one's own account is rejected"""; self.assertEqual(self.post('transfer/', {'to_account_no': str(self.a['acc_no']), 'amount': '100'}, self.a['token'])[0], 400)
    def test_51(self):
        """TC-51 | SEC | A transfer above Rs. 10,000 first asks for an SMS OTP (HTTP 202) and moves no money"""
        self.age(); s, r = self.post('transfer/', {'to_account_no': str(self.b['acc_no']), 'amount': '15000'}, self.a['token'])
        self.assertEqual(s, 202); self.assertTrue(r['otp_required']); self.assertEqual(self.balance(self.b), 0)
    def test_52(self):
        """TC-52 | SEC | The large transfer completes only with the correct OTP"""
        self.age(); r = self.post('transfer/', {'to_account_no': str(self.b['acc_no']), 'amount': '15000'}, self.a['token'])[1]
        self.assertEqual(self.post('transfer/', {'to_account_no': str(self.b['acc_no']), 'amount': '15000', 'otp': '000000'}, self.a['token'])[0], 400)
        self.assertEqual(self.post('transfer/', {'to_account_no': str(self.b['acc_no']), 'amount': '15000', 'otp': r['dev_otp']}, self.a['token'])[0], 200)
    def test_53(self):
        """TC-53 | FR3 | A transfer conserves the total amount of money in the system"""
        total = lambda: sum(x.balance for x in UserBankAccount.objects.all())
        t0 = total(); self.post('transfer/', {'to_account_no': str(self.b['acc_no']), 'amount': '777.77'}, self.a['token']); self.assertEqual(total(), t0)
    def test_54(self):
        """TC-54 | FR3 | A ten-digit number starting with 1 is an account number, one starting with 6-9 is a mobile number"""
        self.assertEqual(resolve_target(str(self.b['acc_no'])).account_no, self.b['acc_no']); self.assertEqual(resolve_target(self.b['phone']).account_no, self.b['acc_no'])


# ============================ FR4: card and ATM ============================
class CardTests(Base):
    def test_55(self):
        """TC-55 | FR4 | Card application requires the correct mPIN"""
        u = self.verified(1); self.assertEqual(self.post('card/apply/', {'variant': 'CLASSIC', 'mpin': '0000'}, u['token'])[0], 403)
    def test_56(self):
        """TC-56 | FR4 | An application becomes PENDING and a second pending application is refused"""
        u = self.verified(1); self.assertEqual(self.post('card/apply/', {'variant': 'CLASSIC', 'mpin': '2468'}, u['token'])[0], 200)
        self.assertEqual(self.post('card/apply/', {'variant': 'CLASSIC', 'mpin': '2468'}, u['token'])[0], 400)
    def test_57(self):
        """TC-57 | FR4 | Staff approval creates the card with the variant's limit and shows the CVV exactly once"""
        u = self.verified(1); self.post('card/apply/', {'variant': 'PLATINUM', 'mpin': '2468'}, u['token'])
        self.post('admin/cards/decide/', {'id': CardApplication.objects.last().id, 'action': 'approve'}, self.admin)
        c1 = self.get('card/', u['token'])[1]; c2 = self.get('card/', u['token'])[1]
        self.assertTrue(c1['issued']); self.assertEqual(Decimal(c1['daily_atm_limit']), 50000); self.assertEqual(len(c1['cvv']), 3); self.assertNotIn('cvv', c2)
    def test_58(self):
        """TC-58 | FR4 | A rejected application can be submitted again"""
        u = self.verified(1); self.post('card/apply/', {'variant': 'CLASSIC', 'mpin': '2468'}, u['token'])
        self.post('admin/cards/decide/', {'id': CardApplication.objects.last().id, 'action': 'reject'}, self.admin)
        self.assertEqual(self.post('card/apply/', {'variant': 'CLASSIC', 'mpin': '2468'}, u['token'])[0], 200)
    def test_59(self):
        """TC-59 | FR4 | An obvious ATM PIN (1111, 1234) is refused"""
        u = self.with_card(1); self.assertEqual(self.post('card/set-pin/', {'pin': '1234', 'mpin': '2468'}, u['token'])[0], 400)
    def test_60(self):
        """TC-60 | FR4 | ATM balance enquiry works with the correct PIN"""
        u = self.with_card(1); self.fund(u, 900); self.assertIn('900', self.post('atm/', {'card_no': u['card'], 'pin': '4682', 'action': 'balance'})[1]['message'])
    def test_61(self):
        """TC-61 | FR4 | Three wrong PINs block the card"""
        u = self.with_card(1)
        for _ in range(3): self.post('atm/', {'card_no': u['card'], 'pin': '9999', 'action': 'balance'})
        self.assertEqual(self.post('atm/', {'card_no': u['card'], 'pin': '4682', 'action': 'balance'})[0], 403)
    def test_62(self):
        """TC-62 | FR4 | ATM cash must be a multiple of Rs. 100 and at most Rs. 10,000 per transaction"""
        u = self.with_card(1); self.fund(u, 50000)
        self.assertEqual(self.post('atm/', {'card_no': u['card'], 'pin': '4682', 'action': 'withdraw', 'amount': 150})[0], 400)
        self.assertEqual(self.post('atm/', {'card_no': u['card'], 'pin': '4682', 'action': 'withdraw', 'amount': 10100})[0], 400)
        self.assertEqual(self.post('atm/', {'card_no': u['card'], 'pin': '4682', 'action': 'withdraw', 'amount': 500})[0], 200)
    def test_63(self):
        """TC-63 | FR4 | The card's daily ATM limit is enforced"""
        u = self.with_card(1); self.fund(u, 100000)
        self.assertEqual(self.post('atm/', {'card_no': u['card'], 'pin': '4682', 'action': 'withdraw', 'amount': 10000})[0], 200)
        self.assertEqual(self.post('atm/', {'card_no': u['card'], 'pin': '4682', 'action': 'withdraw', 'amount': 10000})[0], 200)
        self.assertEqual(self.post('atm/', {'card_no': u['card'], 'pin': '4682', 'action': 'withdraw', 'amount': 100})[0], 400)
    def test_64(self):
        """TC-64 | FR4 | The issued card number passes the Luhn check"""
        n = self.with_card(1)['card']; self.assertEqual(luhn_digit(n[:-1]), n[-1])


# ============================ FR5: WhatsApp ============================
class WhatsAppTests(Base):
    def test_65(self): """TC-65 | FR5 | An unregistered number is told to open an account"""; self.assertIn('not registered', whatsapp_reply('919999999999', 'hi'))
    def test_66(self):
        """TC-66 | FR5 | BALANCE returns the available balance"""
        u = self.verified(1); self.fund(u, 4321); self.assertIn('4,321.00', whatsapp_reply(u['phone'], 'balance'))
    def test_67(self):
        """TC-67 | FR5 | SEND asks for confirmation and completes only after PIN + mPIN"""
        a = self.verified(1); b = self.verified(2); self.fund(a, 5000)
        self.assertIn('Reply *PIN', whatsapp_reply(a['phone'], f"send 500 to {b['acc_no']}")); self.assertEqual(self.balance(b), 0)
        self.assertIn('sent', whatsapp_reply(a['phone'], 'pin 2468')); self.assertEqual(self.balance(b), 500)
    def test_68(self):
        """TC-68 | SEC | A wrong mPIN does not complete the WhatsApp transfer"""
        a = self.verified(1); b = self.verified(2); self.fund(a, 5000); whatsapp_reply(a['phone'], f"send 500 to {b['acc_no']}")
        self.assertIn('Incorrect mPIN', whatsapp_reply(a['phone'], 'pin 9999')); self.assertEqual(self.balance(b), 0)
    def test_69(self):
        """TC-69 | SEC | A WhatsApp transfer above Rs. 10,000 is refused"""
        a = self.verified(1); b = self.verified(2); self.fund(a, 50000); self.assertIn('limited', whatsapp_reply(a['phone'], f"send 20000 to {b['acc_no']}"))
    def test_70(self): """TC-70 | FR5 | BLOCK CARD for a customer without a card does not claim success"""; u = self.verified(1); self.assertIn('do not have', whatsapp_reply(u['phone'], 'block card'))
    def test_71(self):
        """TC-71 | FR5 | The webhook answers the Meta verification challenge"""
        r = self.c.get('/api/whatsapp/webhook/?hub.verify_token=securebank-verify&hub.challenge=abc123'); self.assertEqual(r.content, b'abc123')
    @override_settings(WHATSAPP_APP_SECRET='topsecret')
    def test_72(self):
        """TC-72 | SEC | The webhook rejects a payload with a bad signature"""
        r = self.c.post('/api/whatsapp/webhook/', '{}', content_type='application/json', HTTP_X_HUB_SIGNATURE_256='sha256=bad'); self.assertEqual(r.status_code, 403)


# ============================ FR6: services ============================
class ServiceTests(Base):
    def setUp(self):
        super().setUp(); self.u = self.verified(1); self.fund(self.u, 100000)

    def test_73(self):
        """TC-73 | FR6 | A fixed deposit debits the account and computes the quarterly-compounded maturity"""
        s, r = self.post('fd/open/', {'amount': '50000', 'months': 12, 'mpin': '2468'}, self.u['token'])
        self.assertEqual(s, 200); self.assertEqual(Decimal(r['fd']['maturity_amount']), (Decimal(50000) * (1 + Decimal('6.8') / 400) ** 4).quantize(Decimal('0.01'))); self.assertEqual(self.balance(self.u), 50000)
    def test_74(self):
        """TC-74 | FR6 | Closing a deposit on the day it is opened returns the principal without interest"""
        fd = self.post('fd/open/', {'amount': '50000', 'months': 12, 'mpin': '2468'}, self.u['token'])[1]['fd']
        self.post('fd/close/', {'id': fd['id'], 'mpin': '2468'}, self.u['token']); self.assertEqual(self.balance(self.u), 100000)
    def test_75(self):
        """TC-75 | FR6 | A bill payment debits the account and returns a reference number"""
        s, r = self.post('pay/', {'category': 'ELECTRICITY', 'biller': 'UPPCL', 'consumer_no': 'KNP-12345', 'amount': '1450.50', 'mpin': '2468'}, self.u['token'])
        self.assertEqual(s, 200); self.assertTrue(r['payment']['reference'].startswith('SB')); self.assertEqual(self.balance(self.u), Decimal('98549.50'))
    def test_76(self): """TC-76 | FR6 | A mobile recharge to an invalid number is rejected"""; self.assertEqual(self.post('pay/', {'category': 'MOBILE', 'biller': 'Jio', 'consumer_no': '123', 'amount': '299', 'mpin': '2468'}, self.u['token'])[0], 400)
    def test_77(self):
        """TC-77 | FR6 | The EMI of Rs. 1,00,000 at 11.5 percent for 24 months is Rs. 4,684.03"""
        r = self.post('loans/apply/', {'kind': 'PERSONAL', 'amount': '100000', 'months': 24, 'income': '60000', 'mpin': '2468'}, self.u['token'])[1]; self.assertEqual(Decimal(r['loan']['emi']), Decimal('4684.03'))
    def test_78(self): """TC-78 | FR6 | A loan whose EMI exceeds half of the income is rejected"""; self.assertEqual(self.post('loans/apply/', {'kind': 'PERSONAL', 'amount': '400000', 'months': 12, 'income': '20000', 'mpin': '2468'}, self.u['token'])[0], 400)
    def test_79(self):
        """TC-79 | FR6 | Approval disburses the loan and an EMI payment reduces the balance and counts the instalment"""
        lid = self.post('loans/apply/', {'kind': 'PERSONAL', 'amount': '100000', 'months': 24, 'income': '60000', 'mpin': '2468'}, self.u['token'])[1]['loan']['id']
        self.post('admin/loans/decide/', {'id': lid, 'action': 'approve'}, self.admin); self.assertEqual(self.balance(self.u), 200000)
        self.post('loans/emi/', {'id': lid, 'mpin': '2468'}, self.u['token']); self.assertEqual(self.balance(self.u), Decimal('200000') - Decimal('4684.03'))
    def test_80(self):
        """TC-80 | FR6 | Only one cheque-book request can be open at a time"""
        self.assertEqual(self.post('cheque/request/', {'leaves': 25, 'mpin': '2468'}, self.u['token'])[0], 200); self.assertEqual(self.post('cheque/request/', {'leaves': 25, 'mpin': '2468'}, self.u['token'])[0], 400)
    def test_81(self):
        """TC-81 | FR6 | The PDF statement is a well-formed PDF file"""
        r = self.get('statement.pdf', self.u['token'])[1]; self.assertTrue(r.content.startswith(b'%PDF-1.4')); self.assertTrue(r.content.rstrip().endswith(b'%%EOF'))


# ============================ FR7: staff console ============================
class AdminTests(Base):
    def test_82(self):
        """TC-82 | FR7 | The overview counters match the database"""
        self.signup(1); self.verified(2); s = self.get('admin/summary/', self.admin)[1]
        self.assertEqual((s['accounts_opened'], s['kyc_pending'], s['kyc_verified']), (2, 1, 1))
    def test_83(self):
        """TC-83 | FR7 | The customer detail page returns every section"""
        u = self.verified(1); d = self.get(f"admin/customers/{u['uid']}/", self.admin)[1]
        for k in ('customer', 'kyc', 'documents', 'account', 'card_application', 'fixed_deposits', 'loans', 'cheque_requests', 'recent_transactions'): self.assertIn(k, d)
    def test_84(self):
        """TC-84 | FR7 | A frozen customer cannot log in"""
        u = self.verified(1); self.post('admin/customers/toggle/', {'id': u['uid']}, self.admin); self.assertEqual(self.post('login/', {'email': u['email'], 'password': 'Str0ng#Pass91'})[0], 401)
    def test_85(self):
        """TC-85 | FR7 | Approve-all loans disburses every pending loan"""
        u = self.verified(1); self.fund(u, 0)
        for k in ('PERSONAL', 'VEHICLE'): self.post('loans/apply/', {'kind': k, 'amount': '100000', 'months': 36, 'income': '90000', 'mpin': '2468'}, u['token'])
        self.assertEqual(self.post('admin/loans/approve-all/', {}, self.admin)[1]['count'], 2); self.assertEqual(self.balance(u), 200000)


# ============================ FR8: assistant and SMS ============================
class FakeResp:
    def __init__(self, body): self.b = json.dumps(body).encode()
    def read(self): return self.b
    def __enter__(self): return self
    def __exit__(self, *a): pass


class AssistantTests(Base):
    def test_86(self):
        """TC-86 | FR8 | The rule-based assistant answers a balance question"""
        u = self.verified(1); self.fund(u, 777); self.assertIn('777.00', self.post('assistant/', {'message': 'what is my balance'}, u['token'])[1]['message'])
    @override_settings(ANTHROPIC_API_KEY='sk-test')
    def test_87(self):
        """TC-87 | FR8 | The AI path sends only the customer's own data and strips the action tag from the reply"""
        u = self.verified(1); seen = {}
        def fake(req, timeout=0): seen['b'] = json.loads(req.data); return FakeResp({'content': [{'type': 'text', 'text': 'Your balance is low. [[action:deposit]]'}]})
        with mock.patch('api.assistant.urllib.request.urlopen', fake):
            r = self.post('assistant/', {'message': 'balance?'}, u['token'])[1]
        self.assertEqual(r['action'], 'deposit'); self.assertNotIn('[[', r['message']); self.assertIn('ACCOUNT DATA', seen['b']['system']); self.assertNotIn('password', seen['b']['system'].lower().split('account data')[1])
    @override_settings(ANTHROPIC_API_KEY='sk-test')
    def test_88(self):
        """TC-88 | FR8 | When the AI service fails the rule-based assistant answers instead"""
        u = self.verified(1); self.fund(u, 55)
        with mock.patch('api.assistant.urllib.request.urlopen', side_effect=OSError('down')):
            self.assertIn('55.00', self.post('assistant/', {'message': 'what is my balance'}, u['token'])[1]['message'])


class SmsTests(Base):
    def run_provider(self, prov, resp, **kw):
        seen = []
        def fake(req, timeout=0): seen.append((req.full_url, req.data, req.headers)); return FakeResp(resp)
        with override_settings(SMS_PROVIDER=prov, OTP_DEV_MODE=False, **kw), mock.patch('api.sms.urllib.request.urlopen', fake):
            self.age(); s, r = self.post('otp/send/', {'phone': '9123400001'})
        return s, r, seen

    def test_89(self):
        """TC-89 | FR1 | MSG91, Fast2SMS and Twilio requests are built correctly and the OTP is not returned"""
        for prov, resp, kw, frag in [('msg91', {'type': 'success'}, dict(MSG91_AUTHKEY='k', MSG91_TEMPLATE_ID='t'), 'control.msg91.com'), ('fast2sms', {'return': True}, dict(FAST2SMS_KEY='k'), 'fast2sms.com'),
                                     ('twilio', {'sid': 'SM1'}, dict(TWILIO_SID='AC1', TWILIO_TOKEN='x', TWILIO_FROM='+1555'), 'api.twilio.com')]:
            s, r, seen = self.run_provider(prov, resp, **kw); self.assertEqual(s, 200); self.assertNotIn('dev_otp', r); self.assertIn(frag, seen[0][0])
    @override_settings(SMS_PROVIDER='', OTP_DEV_MODE=False)
    def test_90(self):
        """TC-90 | SEC | With no SMS provider and development mode off, the server answers 503 instead of faking an OTP"""
        self.assertEqual(self.post('otp/send/', {'phone': '9123400001'})[0], 503)


# ============================ SEC ============================
class SecurityTests(Base):
    def test_91(self):
        """TC-91 | SEC | Five wrong mPIN attempts lock mPIN-protected actions"""
        u = self.verified(1)
        for _ in range(5): self.post('card/apply/', {'variant': 'CLASSIC', 'mpin': '0000'}, u['token'])
        self.assertEqual(self.post('card/apply/', {'variant': 'CLASSIC', 'mpin': '2468'}, u['token'])[0], 429)


# ============================ gate coverage for the remaining call sites ============================
class GateCoverageTests(Base):
    """Operations that a customer can only reach after approval; the gate must still stop them if KYC is later rejected."""
    def reject(self, u): self.post('admin/kyc/decide/', {'id': self.kyc_row(u)['id'], 'action': 'reject', 'reason': 'Re-check'}, self.admin)

    def test_92(self):
        """TC-92 | FR2 | Paying a loan EMI is blocked after the customer's KYC is rejected"""
        u = self.verified(1); self.fund(u, 100000)
        lid = self.post('loans/apply/', {'kind': 'PERSONAL', 'amount': '100000', 'months': 24, 'income': '60000', 'mpin': '2468'}, u['token'])[1]['loan']['id']
        self.post('admin/loans/decide/', {'id': lid, 'action': 'approve'}, self.admin); self.reject(u)
        self.assertEqual(self.post('loans/emi/', {'id': lid, 'mpin': '2468'}, u['token'])[0], 403)

    def test_93(self):
        """TC-93 | FR2 | Closing a fixed deposit is blocked after the customer's KYC is rejected"""
        u = self.verified(1); self.fund(u, 100000)
        fid = self.post('fd/open/', {'amount': '50000', 'months': 12, 'mpin': '2468'}, u['token'])[1]['fd']['id']; self.reject(u)
        self.assertEqual(self.post('fd/close/', {'id': fid, 'mpin': '2468'}, u['token'])[0], 403)

    def test_94(self):
        """TC-94 | FR2 | ATM cash withdrawal is blocked after the customer's KYC is rejected"""
        u = self.with_card(1); self.fund(u, 50000); self.reject(u)
        self.assertEqual(self.post('atm/', {'card_no': u['card'], 'pin': '4682', 'action': 'withdraw', 'amount': 500})[0], 403)


class HardeningTests(Base):
    """TC-100.. | SEC | Regression tests for the security fixes."""
    def legacy_user(self):
        u = User.objects.create_user(email='legacy@t.in', password='Str0ng#Pass91', first_name='L', last_name='U')
        UserBankAccount.objects.create(user=u, account_type=BankAccountType.objects.first(), account_no=u.id + 1000000000, gender='M', balance=Decimal('1000'))
        return u

    def test_100(self):
        """TC-100 | SEC | An account without a KYC profile cannot deposit through the API"""
        self.legacy_user()
        token = self.post('login/', {'email': 'legacy@t.in', 'password': 'Str0ng#Pass91'})[1]['token']
        self.assertEqual(self.post('deposit/', {'amount': '500'}, token)[0], 403)

    def test_101(self):
        """TC-101 | SEC | The old Django registration form redirects to the KYC app"""
        r = self.c.get('/accounts/register/'); self.assertEqual(r.status_code, 302); self.assertEqual(r['Location'], '/app/')

    def test_102(self):
        """TC-102 | SEC | The old Django deposit page is blocked without verified KYC"""
        u = self.legacy_user(); self.c.force_login(u)
        r = self.c.post('/transactions/deposit/', {'amount': '500'}); self.assertEqual(r.status_code, 302)
        self.assertEqual(UserBankAccount.objects.get(user=u).balance, Decimal('1000'))

    def test_103(self):
        """TC-103 | SEC | Ten wrong passwords lock further login attempts (HTTP 429)"""
        self.legacy_user()
        for _ in range(10): self.post('login/', {'email': 'legacy@t.in', 'password': 'wrong'})
        self.assertEqual(self.post('login/', {'email': 'legacy@t.in', 'password': 'Str0ng#Pass91'})[0], 429)

    @override_settings(WHATSAPP_APP_SECRET='', DEBUG=False)
    def test_104(self):
        """TC-104 | SEC | The WhatsApp webhook rejects unsigned requests when no app secret is configured"""
        r = self.c.post('/api/whatsapp/webhook/', '{}', content_type='application/json'); self.assertEqual(r.status_code, 403)

    def test_105(self):
        """TC-105 | SEC | The assistant is rate limited to 20 questions per minute"""
        u = self.verified(1)
        codes = [self.post('assistant/', {'message': 'balance'}, u['token'])[0] for _ in range(21)]
        self.assertEqual(codes[-1], 429)
