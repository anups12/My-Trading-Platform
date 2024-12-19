from accounts.models import Orders

order_id = 741562587
order = Orders.objects.get(entry_order_id=order_id, is_entry=True)
print('orders', order)