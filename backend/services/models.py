from django.conf import settings
from django.db import models

from accounts.models import UserBankAccount


class KYCProfile(models.Model):
    """Phone + Aadhaar KYC. The full Aadhaar number is NEVER stored: only a salted hash and the last 4 digits."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, related_name='kyc', on_delete=models.CASCADE)
    phone = models.CharField(max_length=10, unique=True)
    phone_verified = models.BooleanField(default=False)
    aadhaar_last4 = models.CharField(max_length=4)
    aadhaar_hash = models.CharField(max_length=64, unique=True)
    aadhaar_consent_at = models.DateTimeField()
    mpin_hash = models.CharField(max_length=128)
    kyc_status = models.CharField(max_length=12, default='PENDING')  # PENDING -> VERIFIED / REJECTED after staff review
    kyc_note = models.CharField(max_length=160, blank=True, default='')

    def __str__(self):
        return self.phone


class PhoneOTP(models.Model):
    phone = models.CharField(max_length=10, db_index=True)
    purpose = models.CharField(max_length=10, default='register')  # register / login / transfer
    code_hash = models.CharField(max_length=64)
    created = models.DateTimeField(auto_now_add=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    used = models.BooleanField(default=False)


class DebitCard(models.Model):
    account = models.OneToOneField(UserBankAccount, related_name='card', on_delete=models.CASCADE)
    number = models.CharField(max_length=16, unique=True)
    expiry = models.CharField(max_length=5)
    cvv_hash = models.CharField(max_length=128)
    variant = models.CharField(max_length=8, default='CLASSIC')  # CLASSIC / PLATINUM
    reveal_cvv = models.CharField(max_length=3, blank=True, default='')  # simulation only: shown once to the customer, then cleared
    pin_hash = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=8, default='ACTIVE')  # ACTIVE / BLOCKED
    wrong_pin_count = models.PositiveSmallIntegerField(default=0)
    daily_atm_limit = models.DecimalField(max_digits=10, decimal_places=2, default=20000)
    online_enabled = models.BooleanField(default=True)


class FixedDeposit(models.Model):
    account = models.ForeignKey(UserBankAccount, related_name='fds', on_delete=models.CASCADE)
    principal = models.DecimalField(max_digits=12, decimal_places=2)
    rate = models.DecimalField(max_digits=5, decimal_places=2)
    months = models.PositiveSmallIntegerField()
    opened = models.DateField(auto_now_add=True)
    maturity_date = models.DateField()
    maturity_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=6, default='OPEN')  # OPEN / CLOSED


class Beneficiary(models.Model):
    account = models.ForeignKey(UserBankAccount, related_name='beneficiaries', on_delete=models.CASCADE)
    name = models.CharField(max_length=60)
    identifier = models.CharField(max_length=40)  # account no / mobile / UPI id
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('account', 'identifier')


class Payment(models.Model):
    """Bill payments and mobile / DTH recharges."""
    account = models.ForeignKey(UserBankAccount, related_name='payments', on_delete=models.CASCADE)
    category = models.CharField(max_length=12)
    biller = models.CharField(max_length=40)
    consumer_no = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(max_length=16, unique=True)
    created = models.DateTimeField(auto_now_add=True)


class Loan(models.Model):
    account = models.ForeignKey(UserBankAccount, related_name='loans', on_delete=models.CASCADE)
    kind = models.CharField(max_length=10)  # PERSONAL / HOME / EDUCATION / VEHICLE
    principal = models.DecimalField(max_digits=12, decimal_places=2)
    rate = models.DecimalField(max_digits=5, decimal_places=2)
    months = models.PositiveSmallIntegerField()
    emi = models.DecimalField(max_digits=12, decimal_places=2)
    monthly_income = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=8, default='PENDING')  # PENDING / ACTIVE / REJECTED / CLOSED
    paid_emis = models.PositiveSmallIntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)


class ChequeBookRequest(models.Model):
    account = models.ForeignKey(UserBankAccount, related_name='cheque_requests', on_delete=models.CASCADE)
    leaves = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=10, default='REQUESTED')  # REQUESTED / DISPATCHED
    created = models.DateTimeField(auto_now_add=True)


class KYCDocument(models.Model):
    """Uploaded KYC proof. The file lives outside any public folder and is only served to staff / the owner."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='kyc_docs', on_delete=models.CASCADE)
    kind = models.CharField(max_length=8)  # AADHAAR / PAN / PHOTO
    stored_name = models.CharField(max_length=64, unique=True)
    original_name = models.CharField(max_length=120)
    content_type = models.CharField(max_length=30)
    size = models.PositiveIntegerField()
    uploaded = models.DateTimeField(auto_now_add=True)
    viewed_at = models.DateTimeField(null=True, blank=True)  # set when bank staff open the document


class CardApplication(models.Model):
    """Customer applies for a debit card; the card is created only when staff approve the application."""
    account = models.ForeignKey(UserBankAccount, related_name='card_applications', on_delete=models.CASCADE)
    variant = models.CharField(max_length=8, default='CLASSIC')
    status = models.CharField(max_length=8, default='PENDING')  # PENDING / APPROVED / REJECTED
    note = models.CharField(max_length=160, blank=True, default='')
    created = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
