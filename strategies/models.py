from django.db import models

# Create your models here.
from django.db import models


class TradingStrategy(models.Model):
    base_price = models.DecimalField(max_digits=10, decimal_places=2, default=100.00)
    percentage_change = models.DecimalField(max_digits=5, decimal_places=2,
                                            default=10.00)  # Percentage for price movement (10%)

    api_key = models.CharField(max_length=255, blank=True, null=True)
    api_secret = models.CharField(max_length=255, blank=True, null=True)
    trading_symbol = models.CharField(max_length=50, blank=True, null=True)

    is_running = models.BooleanField(default=False)
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Strategy {self.id} - Running: {self.is_running}"


class DynamicLevel(models.Model):
    strategy = models.ForeignKey(TradingStrategy, related_name='levels', on_delete=models.CASCADE)
    level_number = models.IntegerField()  # Level number (1-10)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    lot_size = models.IntegerField()

    def __str__(self):
        return f"Level {self.level_number}: Price {self.price}, Lot Size {self.lot_size}"
