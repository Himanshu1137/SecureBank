"""Real SMS + WhatsApp senders. Configure one provider in .env (SMS_PROVIDER=msg91|fast2sms|twilio).
Without a provider (dev), OTPs are only logged and returned in the API response (OTP_DEV_MODE)."""
import base64
import json
import logging
import urllib.parse
import urllib.request

from django.conf import settings

log = logging.getLogger('securebank')


def _call(url, data=None, headers=None, form=False, basic=None):
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json', **(headers or {})})
    if basic:
        req.add_header('Authorization', 'Basic ' + base64.b64encode(f'{basic[0]}:{basic[1]}'.encode()).decode())
    with urllib.request.urlopen(req, timeout=12) as r:
        raw = r.read().decode() or '{}'
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def send_otp_sms(phone, code):
    """Sends an OTP via the configured provider. Returns True on success."""
    prov = settings.SMS_PROVIDER
    try:
        if prov == 'msg91':      # MSG91 OTP API (needs DLT-approved template with ##OTP## variable)
            q = urllib.parse.urlencode({'template_id': settings.MSG91_TEMPLATE_ID, 'mobile': '91' + phone,
                                        'authkey': settings.MSG91_AUTHKEY, 'otp': code, 'otp_expiry': 5})
            return _call('https://control.msg91.com/api/v5/otp?' + q, {}).get('type') == 'success'
        if prov == 'fast2sms':
            r = _call('https://www.fast2sms.com/dev/bulkV2', {'route': 'otp', 'variables_values': code, 'numbers': phone},
                      {'authorization': settings.FAST2SMS_KEY})
            return bool(r.get('return'))
        if prov == 'twilio':
            r = _call(f'https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_SID}/Messages.json',
                      {'To': '+91' + phone, 'From': settings.TWILIO_FROM,
                       'Body': f'{code} is your SecureBank OTP. Valid for 5 minutes. Do not share it with anyone.'},
                      form=True, basic=(settings.TWILIO_SID, settings.TWILIO_TOKEN))
            return bool(r.get('sid'))
    except Exception as e:  # noqa: BLE001
        log.error('SMS provider %s failed: %s', prov, e)
        return False
    log.warning('DEV OTP for +91%s: %s', phone, code)  # no provider configured
    return True


def send_whatsapp(to, text):
    if not (settings.WHATSAPP_TOKEN and settings.WHATSAPP_PHONE_ID):
        log.warning('WhatsApp to %s: %s', to, text)
        return False
    try:
        _call(f'https://graph.facebook.com/v20.0/{settings.WHATSAPP_PHONE_ID}/messages',
              {'messaging_product': 'whatsapp', 'to': to, 'type': 'text', 'text': {'body': text}},
              {'Authorization': f'Bearer {settings.WHATSAPP_TOKEN}'})
        return True
    except Exception as e:  # noqa: BLE001
        log.error('WhatsApp send failed: %s', e)
        return False
