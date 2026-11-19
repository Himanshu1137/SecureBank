import json
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views import View

from transactions.constants import DEPOSIT, WITHDRAWAL


class AssistantView(LoginRequiredMixin, View):
    """A privacy-first banking assistant that answers using the user's own account data."""

    def post(self, request, *args, **kwargs):
        try:
            payload = json.loads(request.body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            payload = {}

        message = str(payload.get('message', '')).strip().lower()
        account = request.user.account
        transactions = account.transactions.all().order_by('-timestamp')

        if not message:
            return self.reply('Please type a question. I can help with balance, transactions, deposits, withdrawals, interest, and account help.')

        balance = account.balance
        recent = transactions[:5]
        deposits = sum((t.amount for t in transactions if t.transaction_type == DEPOSIT), Decimal('0'))
        withdrawals = sum((t.amount for t in transactions if t.transaction_type == WITHDRAWAL), Decimal('0'))

        if any(k in message for k in ('balance', 'how much', 'available money', 'available balance')):
            return self.reply(f'Your current available balance is ₹{balance:,.2f}.')

        if any(k in message for k in ('account number', 'account no', 'account id')):
            return self.reply(f'Your bank account number is {account.account_no}. For security, do not share it publicly.')

        if any(k in message for k in ('interest', 'rate', 'saving')):
            rate = account.account_type.annual_interest_rate
            return self.reply(f'Your {account.account_type.name} account has an annual interest rate of {rate}%. Interest is calculated {account.account_type.interest_calculation_per_year} time(s) per year.')

        if any(k in message for k in ('deposit', 'add money', 'put money')):
            return self.reply('You can add money using the Deposit option. The minimum deposit is ₹10. Your balance updates after a successful transaction.', 'deposit')

        if any(k in message for k in ('withdraw', 'take money', 'cash')):
            return self.reply(f'You can withdraw from your account if the amount is within your available balance and account limit. Current balance: ₹{balance:,.2f}.', 'withdraw')

        if any(k in message for k in ('transaction', 'history', 'statement', 'recent')):
            if not recent:
                return self.reply('You do not have any transactions yet. Use Deposit to make your first transaction.', 'deposit')
            lines = []
            for tx in recent:
                label = tx.get_transaction_type_display()
                sign = '+' if tx.transaction_type == DEPOSIT else '-'
                lines.append(f'{label}: {sign}₹{tx.amount:,.2f}')
            return self.reply('Here are your latest transactions: ' + ' • '.join(lines), 'transactions')

        if any(k in message for k in ('summary', 'overview', 'spending', 'activity')):
            return self.reply(f'Account overview: balance ₹{balance:,.2f}, total deposits ₹{deposits:,.2f}, total withdrawals ₹{withdrawals:,.2f}, and {transactions.count()} transaction(s).', 'transactions')

        if any(k in message for k in ('security', 'safe', 'secure', 'fraud')):
            return self.reply('Security tips: never share your password or OTP, verify transaction details before submitting, and contact your bank immediately if you notice an unauthorized transaction.')

        return self.reply('I can help with your balance, account number, interest rate, recent transactions, deposits, withdrawals, account summary, or basic security guidance. Try: “What is my balance?”')

    def reply(self, message, action=None):
        return JsonResponse({'message': message, 'action': action})
