import csv
from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.db.models import Sum
from django.http import HttpResponse
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, ListView
from transactions.constants import DEPOSIT, WITHDRAWAL
from transactions.forms import DepositForm, TransactionDateRangeForm, WithdrawForm
from transactions.models import Transaction


class TransactionRepostView(LoginRequiredMixin, ListView):
    template_name = 'transactions/transaction_report.html'
    model = Transaction
    form_data = {}

    def get(self, request, *args, **kwargs):
        form = TransactionDateRangeForm(request.GET or None)
        if form.is_valid():
            self.form_data = form.cleaned_data
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset().filter(account=self.request.user.account)
        daterange = self.form_data.get('daterange')
        if daterange:
            queryset = queryset.filter(timestamp__date__range=daterange)
        transaction_type = self.request.GET.get('type')
        if transaction_type in ('1', '2'):
            queryset = queryset.filter(transaction_type=int(transaction_type))
        search = self.request.GET.get('q', '').strip()
        if search:
            # Search is intentionally limited to transaction type labels/amounts in the UI.
            if search.lower() in ('deposit', 'credit'):
                queryset = queryset.filter(transaction_type=DEPOSIT)
            elif search.lower() in ('withdraw', 'withdrawal', 'debit'):
                queryset = queryset.filter(transaction_type=WITHDRAWAL)
        return queryset.order_by('-timestamp').distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        account = self.request.user.account
        queryset = self.get_queryset()
        context.update({
            'account': account,
            'form': TransactionDateRangeForm(self.request.GET or None),
            'transaction_count': queryset.count(),
            'total_deposits': queryset.filter(transaction_type=DEPOSIT).aggregate(total=Sum('amount'))['total'] or 0,
            'total_withdrawals': queryset.filter(transaction_type=WITHDRAWAL).aggregate(total=Sum('amount'))['total'] or 0,
            'account_type': account.account_type.name,
            'interest_rate': account.account_type.annual_interest_rate,
            'withdrawal_limit': account.account_type.maximum_withdrawal_amount,
            'recent_transactions': list(account.transactions.all().order_by('-timestamp')[:5]),
        })
        return context


class TransactionExportView(LoginRequiredMixin, ListView):
    model = Transaction

    def get(self, request, *args, **kwargs):
        account = request.user.account
        transactions = account.transactions.all().order_by('-timestamp')
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="securebank-statement.csv"'
        writer = csv.writer(response)
        writer.writerow(['Date', 'Transaction Type', 'Amount', 'Balance After Transaction'])
        for tx in transactions:
            writer.writerow([tx.timestamp.strftime('%Y-%m-%d %H:%M'), tx.get_transaction_type_display(), f'{tx.amount:.2f}', f'{tx.balance_after_transaction:.2f}'])
        return response


class TransactionCreateMixin(LoginRequiredMixin, CreateView):
    template_name = 'transactions/transaction_form.html'
    model = Transaction
    title = ''
    success_url = reverse_lazy('transactions:transaction_report')

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:  # same KYC gate as the REST API
            k = getattr(request.user, 'kyc', None)
            if not k or k.kyc_status != 'VERIFIED':
                messages.error(request, 'Deposits and withdrawals unlock after the bank approves your KYC. Use the SecureBank app at /app/.')
                return redirect('transactions:transaction_report')
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update({'account': self.request.user.account})
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({'title': self.title, 'account': self.request.user.account})
        return context


class DepositMoneyView(TransactionCreateMixin):
    form_class = DepositForm
    title = 'Deposit Money to Your Account'

    def get_initial(self):
        return {'transaction_type': DEPOSIT}

    def form_valid(self, form):
        amount = form.cleaned_data['amount']
        account = self.request.user.account
        if not account.initial_deposit_date:
            now = timezone.now()
            next_interest_month = int(12 / account.account_type.interest_calculation_per_year)
            account.initial_deposit_date = now
            account.interest_start_date = now + relativedelta(months=+next_interest_month)
        account.balance += amount
        account.save(update_fields=['initial_deposit_date', 'balance', 'interest_start_date'])
        messages.success(self.request, f'₹{amount:,.2f} deposited successfully.')
        return super().form_valid(form)


class WithdrawMoneyView(TransactionCreateMixin):
    form_class = WithdrawForm
    title = 'Withdraw Money from Your Account'

    def get_initial(self):
        return {'transaction_type': WITHDRAWAL}

    def form_valid(self, form):
        amount = form.cleaned_data['amount']
        account = self.request.user.account
        account.balance -= amount
        account.save(update_fields=['balance'])
        messages.success(self.request, f'₹{amount:,.2f} withdrawn successfully.')
        return super().form_valid(form)
