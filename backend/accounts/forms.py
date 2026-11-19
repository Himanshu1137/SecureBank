from django import forms
from django.conf import settings
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction

from .models import User, BankAccountType, UserBankAccount, UserAddress
from .constants import GENDER_CHOICE


class UserAddressForm(forms.ModelForm):

    postal_code = forms.CharField(
        label="PIN Code",
        max_length=6,
        min_length=6,
        required=True,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Enter 6-digit PIN Code",
                "maxlength": "6",
                "inputmode": "numeric",
                "pattern": "[0-9]{6}"
            }
        )
    )

    class Meta:
        model = UserAddress
        fields = [
            'street_address',
            'city',
            'postal_code',
            'country'
        ]

    def clean_postal_code(self):
        postal_code = self.cleaned_data['postal_code']

        if not postal_code.isdigit():
            raise forms.ValidationError(
                "PIN Code must contain only numbers."
            )

        if len(postal_code) != 6:
            raise forms.ValidationError(
                "PIN Code must be exactly 6 digits."
            )

        return postal_code

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields:
            self.fields[field].widget.attrs.update({
                'class': (
                    'appearance-none block w-full bg-gray-200 '
                    'text-gray-700 border border-gray-200 rounded '
                    'py-3 px-4 leading-tight focus:outline-none '
                    'focus:bg-white focus:border-gray-500'
                )
            })


class UserRegistrationForm(UserCreationForm):

    account_type = forms.ModelChoiceField(
        queryset=BankAccountType.objects.all(),
        empty_label="Select Account Type",
        required=True
    )

    gender = forms.ChoiceField(
        choices=GENDER_CHOICE,
        required=True
    )

    birth_date = forms.DateField(
        required=True,
        widget=forms.DateInput(
            attrs={'type': 'date'}
        )
    )

    class Meta:
        model = User
        fields = [
            'first_name',
            'last_name',
            'email',
            'password1',
            'password2',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields:
            self.fields[field].widget.attrs.update({
                'class': (
                    'appearance-none block w-full bg-gray-200 '
                    'text-gray-700 border border-gray-200 '
                    'rounded py-3 px-4 leading-tight '
                    'focus:outline-none focus:bg-white '
                    'focus:border-gray-500'
                )
            })

        self.fields['account_type'].widget.attrs.update({
            'class': (
                'block w-full bg-gray-200 text-gray-700 '
                'border border-gray-200 rounded py-3 px-4 '
                'leading-tight focus:outline-none '
                'focus:bg-white focus:border-blue-500'
            )
        })

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)

        user.set_password(self.cleaned_data["password1"])

        if commit:
            user.save()

            account_type = self.cleaned_data.get('account_type')
            gender = self.cleaned_data.get('gender')
            birth_date = self.cleaned_data.get('birth_date')

            UserBankAccount.objects.create(
                user=user,
                gender=gender,
                birth_date=birth_date,
                account_type=account_type,
                account_no=(
                    user.id +
                    settings.ACCOUNT_NUMBER_START_FROM
                )
            )

        return user