from django.contrib import admin

from .models import Customer, PriceQuantityTable, OrderLevel, Orders, OrderStrategy, AccessToken


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'phone_number']


@admin.register(Orders)
class OrdersAdmin(admin.ModelAdmin):
    list_display = ['id', 'level', 'entry_order_id', 'entry_order_status', 'entry_price', 'entry_time', 'is_main', 'exit_order_id', 'exit_order_status', 'exit_price', 'is_complete', 'exit_time']


@admin.register(OrderStrategy)
class OrderStrategyAdmin(admin.ModelAdmin):
    list_display = ['id', 'is_active', 'user', 'is_hedging', 'main_instrument', 'hedging_instrument']


@admin.register(PriceQuantityTable)
class PriceQuantityModelAdmin(admin.ModelAdmin):
    list_display = ['name']

    def has_add_permission(self, request):
        return True

    def has_delete_permission(self, request, obj=None):
        return True


@admin.register(OrderLevel)
class OrderLevelAdmin(admin.ModelAdmin):
    list_display = ['id', 'level_number', 'timestamp_created', 'strategy', 'main_percentage', 'main_quantity', 'main_target', 'percentage_down', 'hedging_quantity', 'hedging_limit_price', 'hedging_limit_quantity', ]

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
