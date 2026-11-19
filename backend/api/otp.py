"""Real SMS OTP service: hashed codes, 5-minute expiry, 5 attempts, 30 s resend gap, 10 per hour per number."""
import hashlib
import hmac
import random
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from services.models import PhoneOTP

from .errors import ApiError
from .sms import send_otp_sms


def _hash(phone, purpose, code):
    return hashlib.sha256(f'{settings.SECRET_KEY}{phone}{purpose}{code}'.encode()).hexdigest()


def masked(phone):
    return f'+91 {phone[:2]}XXXXXX{phone[-2:]}'


def issue_otp(phone, purpose):
    now = timezone.now()
    recent = PhoneOTP.objects.filter(phone=phone, created__gte=now - timedelta(hours=1))
    if recent.count() >= 10:
        raise ApiError('Too many OTP requests. Try again after an hour.', 429)
    last = recent.filter(purpose=purpose).order_by('-created').first()  # resend gap is per purpose (login / transfer / register)
    if last and (now - last.created).total_seconds() < 30:
        raise ApiError('Please wait 30 seconds before requesting another OTP.', 429)
    if not settings.SMS_PROVIDER and not settings.OTP_DEV_MODE:
        raise ApiError('SMS service is not configured on the server (set SMS_PROVIDER in .env).', 503)
    code = f'{random.SystemRandom().randint(0, 999999):06d}'
    if not send_otp_sms(phone, code):
        raise ApiError('Could not send the SMS right now. Please try again.', 503)
    PhoneOTP.objects.create(phone=phone, purpose=purpose, code_hash=_hash(phone, purpose, code))
    return code


def otp_payload(phone, code):
    out = {'message': f'OTP sent to {masked(phone)}'}
    if settings.OTP_DEV_MODE:
        out['dev_otp'] = code  # dev only: never returned once a real SMS provider is configured
    return out


def verify_otp(phone, code, purpose):
    otp = PhoneOTP.objects.filter(phone=phone, purpose=purpose, used=False).order_by('-created').first() if phone else None
    if not otp or (timezone.now() - otp.created).total_seconds() > 300:
        raise ApiError('OTP expired. Request a new one.', fields={'code': 'OTP expired'})
    if otp.attempts >= 5:  # check BEFORE comparing, so a 6th guess can never succeed
        otp.used = True
        otp.save()
        raise ApiError('Too many wrong attempts. Request a new OTP.', fields={'code': 'OTP expired'})
    otp.attempts += 1
    if not hmac.compare_digest(otp.code_hash, _hash(phone, purpose, str(code).strip())):
        otp.save()
        raise ApiError('Incorrect OTP.', fields={'code': 'Incorrect OTP'})
    otp.used = True
    otp.save()
