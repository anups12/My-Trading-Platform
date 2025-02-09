from django.contrib.auth.hashers import make_password, check_password
from django.db import models
from django.utils import timezone


class Customer(models.Model):
    phone_number = models.CharField(max_length=15, unique=True, null=True, blank=True)
    email = models.EmailField(unique=True, null=True, blank=True)
    name = models.CharField(max_length=255)
    password = models.CharField(max_length=255)

    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)

    def __str__(self):
        return self.name


class OrderStrategy(models.Model):
    user = models.ForeignKey(Customer, on_delete=models.CASCADE)
    main_instrument = models.CharField(max_length=255, null=True, blank=True)
    original_price = models.DecimalField(max_digits=6, decimal_places=3, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_hedging = models.BooleanField(default=False)
    hedging_instrument = models.CharField(max_length=255, null=True, blank=True)
    hedging_strike_distance = models.IntegerField(default=0, null=True, blank=True)
    hedging_quantity = models.IntegerField(null=True, blank=True)
    hedging_limit_price = models.DecimalField(max_digits=6, null=True, blank=True, decimal_places=3)
    hedging_limit_quantity = models.IntegerField(null=True, blank=True)
    hedge_limit_order_time_for_convert_from_lo_to_mo = models.CharField(max_length=50, null=True, blank=True)
    table = models.ForeignKey('PriceQuantityTable', on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        """
        Return a human-readable representation of the object.

        This representation will be used in the admin interface when displaying
        the object.

        Returns:
            str: A string with the format "Strategy <id> by <user.name>".
        """
        return f"Strategy {self.id} by {self.user.name}"


class OrderLevel(models.Model):
    timestamp_created = models.DateTimeField(default=timezone.now)
    strategy = models.ForeignKey(OrderStrategy, related_name='order_levels', on_delete=models.CASCADE)
    level_number = models.PositiveIntegerField()  # Starts from 0, increment for each level

    # Fields from the form
    main_percentage = models.DecimalField(max_digits=6, null=True, blank=True, decimal_places=3)
    main_quantity = models.PositiveIntegerField(null=True, blank=True)
    main_target = models.DecimalField(max_digits=6, null=True, blank=True, decimal_places=3)
    percentage_down = models.DecimalField(max_digits=6, null=True, blank=True, decimal_places=3)
    hedging_quantity = models.IntegerField(null=True, blank=True)
    hedging_limit_price = models.DecimalField(max_digits=6, null=True, blank=True, decimal_places=3)
    hedging_limit_quantity = models.IntegerField(null=True, blank=True)
    is_skip = models.BooleanField(default=False)

    def __str__(self):
        return f"Level {self.level_number} | {self.main_percentage} | {self.strategy.id}"


class Orders(models.Model):
    order_status_choices = [
        (0, 'None'),
        (1, 'COMPLETED'),
        (2, 'PENDING'),
        (3, 'CANCELLED')
    ]

    level = models.ForeignKey(OrderLevel, on_delete=models.CASCADE)
    entry_order_id = models.CharField(max_length=100, null=True, blank=True)
    entry_order_status = models.IntegerField(choices=order_status_choices, default=0)
    order_side = models.CharField(max_length=10, null=True, blank=True)  # 'buy' or 'sell'
    exit_order_id = models.CharField(max_length=100, null=True, blank=True)
    exit_order_status = models.IntegerField(choices=order_status_choices, default=0)
    is_entry = models.BooleanField(default=False)
    is_complete = models.BooleanField(default=False)
    order_quantity = models.IntegerField(null=True, blank=True)
    entry_price = models.DecimalField(max_digits=6, null=True, blank=True, decimal_places=3)
    exit_price = models.DecimalField(max_digits=6, null=True, blank=True, decimal_places=3)  # Price at which it was sold
    entry_time = models.DateTimeField(default=timezone.now)
    exit_time = models.DateTimeField(null=True, blank=True)
    is_main = models.BooleanField(default=True)


def __str__(self):
    return f"{self.level} | {self.exit_order_id} | {self.entry_order_id}"


class PriceQuantityTable(models.Model):
    name = models.CharField(max_length=255)
    price_quantity_data = models.TextField()  # Storing the dictionary as a string
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name}"


class AccessToken(models.Model):
    timestamp_created = models.DateTimeField(default=timezone.now)
    access_token = models.CharField(max_length=1000)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.timestamp_created} | {self.is_active}"
