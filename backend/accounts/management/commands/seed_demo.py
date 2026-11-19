from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from django.contrib.auth.hashers import make_password

from accounts.models import BankAccountType, User, UserAddress, UserBankAccount
from api.kyc import aadhaar_hash
from api.more import issue_card
from services.models import KYCProfile
from transactions.constants import DEPOSIT, WITHDRAWAL
from transactions.models import Transaction


class Command(BaseCommand):
    help = 'Create account types and a demo customer (demo@securebank.in / Demo@1234).'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Allow seeding well-known demo passwords even when DEBUG=False (throwaway servers only).')

    def handle(self, *args, **opts):
        if not settings.DEBUG and not opts.get('force'):
            raise CommandError('seed_demo creates accounts with publicly known passwords and is blocked when DEBUG=False. Use --force only on a throwaway server.')
        types = {}
        for name, rate, per_year, limit in [('Savings', 4, 4, 50000), ('Current', 0, 1, 200000), ('Fixed Saver', 7, 2, 20000)]:
            types[name], _ = BankAccountType.objects.get_or_create(
                name=name, defaults=dict(annual_interest_rate=rate, interest_calculation_per_year=per_year,
                                         maximum_withdrawal_amount=limit))
        if not User.objects.filter(email='admin@securebank.in').exists():
            User.objects.create_superuser(email='admin@securebank.in', password='Admin@1234', first_name='Bank', last_name='Admin')
            self.stdout.write('Admin: admin@securebank.in / Admin@1234')
        if User.objects.filter(email='demo@securebank.in').exists():
            return self.stdout.write('Demo user already exists.')
        u = User.objects.create_user(email='demo@securebank.in', password='Demo@1234', first_name='Aarav', last_name='Sharma')
        acc = UserBankAccount.objects.create(user=u, account_type=types['Savings'], gender='M', birth_date=date(1998, 5, 14),
                                             account_no=u.id + settings.ACCOUNT_NUMBER_START_FROM,
                                             initial_deposit_date=date.today(), interest_start_date=date.today() + timedelta(days=90))
        UserAddress.objects.create(user=u, street_address='12 MG Road', city='Lucknow', postal_code=226001, country='India')
        KYCProfile.objects.create(user=u, phone='9876543210', phone_verified=True, aadhaar_last4='9012',
                                  aadhaar_hash=aadhaar_hash('DEMO-NOT-A-REAL-AADHAAR'), aadhaar_consent_at=timezone.now(),
                                  mpin_hash=make_password('2468'), kyc_status='VERIFIED')
        card = issue_card(acc)
        c = acc.card
        c.pin_hash = make_password('2580')
        c.save()
        self.stdout.write(f"Demo card {card['number']} exp {card['expiry']} cvv {card['cvv']} | ATM PIN 2580 | mPIN 2468 | phone 9876543210")
        bal = Decimal('0')
        for days, amount, kind, note in [(20, 25000, DEPOSIT, 'Salary credit'), (14, 3200, WITHDRAWAL, 'ATM withdrawal'),
                                         (9, 1500, DEPOSIT, 'Refund'), (3, 800, WITHDRAWAL, 'Groceries')]:
            amount = Decimal(amount)
            bal += amount if kind == DEPOSIT else -amount
            t = Transaction.objects.create(account=acc, amount=amount, balance_after_transaction=bal,
                                           transaction_type=kind, description=note)
            Transaction.objects.filter(pk=t.pk).update(timestamp=timezone.now() - timedelta(days=days))
        acc.balance = bal
        acc.save()
        self.stdout.write(self.style.SUCCESS('Seeded demo@securebank.in / Demo@1234'))
