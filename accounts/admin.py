from django.contrib import admin
from .models import Customer, PriceQuantityTable, OrderLevel, Orders, OrderStrategy, AccessToken


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'phone_number']


@admin.register(Orders)
class OrdersAdmin(admin.ModelAdmin):
    list_display = ['entry_time', 'exit_time', 'level']

@admin.register(OrderStrategy)
class OrderStrategyAdmin(admin.ModelAdmin):
    list_display = ['id', 'is_active', 'user']

@admin.register(PriceQuantityTable)
class PriceQuantityModelAdmin(admin.ModelAdmin):
    list_display = ['name']

    def has_add_permission(self, request):
        return True

    def has_delete_permission(self, request, obj=None):
        return True


@admin.register(OrderLevel)
class OrderLevelAdmin(admin.ModelAdmin):
    list_display = ['level_number', 'timestamp_created', 'strategy','main_percentage', 'main_quantity', 'main_target', 'percentage_down', 'hedging_quantity','hedging_limit_price','hedging_limit_quantity',]

    def has_add_permission(self, request):
        return True

    def has_delete_permission(self, request, obj=None):
        return True


@admin.register(AccessToken)
class AccessTokenAdmin(admin.ModelAdmin):
    list_display = ['timestamp_created', 'access_token', 'is_active']

    def has_add_permission(self, request):
        return True

    def has_delete_permission(self, request, obj=None):
        return True

