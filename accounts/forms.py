from django import forms
from .models import OrderLevel, OrderStrategy

class OrderLevelForm(forms.ModelForm):
    class Meta:
        model = OrderLevel
        fields = [
            'main_percentage', 'main_quantity', 'main_target',
            'hedging_quantity', 'hedging_limit_price',
            'hedging_limit_quantity', 'is_skip'
        ]
        widgets = {
            'main_percentage': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001'}),
            'main_quantity': forms.NumberInput(attrs={'class': 'form-control'}),
            'main_target': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001'}),
            'hedging_quantity': forms.NumberInput(attrs={'class': 'form-control'}),
            'hedging_limit_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001'}),
            'hedging_limit_quantity': forms.NumberInput(attrs={'class': 'form-control'}),
            'is_skip': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class OrderStrategyForm(forms.ModelForm):
    class Meta:
        model = OrderStrategy
        fields = ['is_hedging']
        widgets = {
            'is_hedging': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
