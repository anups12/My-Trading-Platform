import json
import threading

from django.conf import settings
from django.shortcuts import render, redirect
from fyers_apiv3 import fyersModel
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import PriceQuantityTable, OrderStrategy
from accounts.utils import get_customer, get_instrument, retry_on_exception, get_access_token
from strategies.buy_sell_strategy import BackgroundProcessor

# Shared state to track orders
order_status = {}
order_lock = threading.Lock()  # To ensure thread-safe updates to the shared state


class StrategyBuySell(APIView):

    def get(self, request, *args, **kwargs):
        customer = get_customer(request)
        table = PriceQuantityTable.objects.filter(is_active=True).last()
        data = json.loads(table.price_quantity_data)
        return render(request, 'strategy_buy_sell.html', {'my_list': data, "customer": customer, "table_id": table.id})

    def post(self, request, *args, **kwargs):
        customer = get_customer(request)
        index = request.POST.get('indexSelect')
        call_strike = int(request.POST.get('callStrike'))
        put_strike = int(request.POST.get('putStrike'))
        percentage_down = float(request.POST.get('percentageDown'))
        levels_count = int(request.POST.get('levelsCount'))
        call_instrument_symbol, call_instrument_price = get_instrument(index, call_strike, 'call', expiry=None)
        put_instrument_symbol, put_instrument_price = get_instrument(index, put_strike, 'put', expiry=None)
        call_base_quantity = request.POST.get('callBaseQuantity')
        put_base_quantity = request.POST.get('putBaseQuantity')
        price_factor = 1 - (percentage_down / 100)
        table_name = request.POST.get('tableName')
        levels = {
            f"{i}": {"call_quantity": 100, "put_quantity": 50, "call_price": round(call_instrument_price * (1 - percentage_down / 100) * (price_factor ** (i - 1)), 2)}
            for i in range(1, levels_count + 1)
        }

        levels.update({
            f"-{i}": {"put_quantity": 100, "call_quantity": 50, "put_price": round(put_instrument_price * (1 - percentage_down / 100) * (price_factor ** (i - 1)), 2)}
            for i in range(1, levels_count + 1)
        })

        # Add Level 0
        levels["0"] = {"put_quantity": call_base_quantity, "call_quantity": put_base_quantity, "call_price": round(call_instrument_price, 2), "put_price": round(put_instrument_price, 2)}

        sorted_table_data = {k: levels[k] for k in sorted(levels, key=lambda x: int(x), reverse=True)}
        table = PriceQuantityTable.objects.create(name=table_name, price_quantity_data=json.dumps(sorted_table_data))
        OrderStrategy.objects.create(user=customer, main_instrument=call_instrument_symbol, hedging_instrument=put_instrument_symbol, table=table)
        return redirect('strategy_buy_sell')


# class PlaceBuySellOrders(APIView):
#
#     def post(self, request, *args, **kwargs):
#         """Handles Buy/Sell order placement."""
#         user_id = request.user.id
#         side = request.data.get("action")
#         price = request.data.get("callPrice") or request.data.get("callPrice")
#         print('request ', request.data)
#         quantity = request.data.get("call_quantity")
#         order_type = "Limit"
#         order_details = {
#             "type": side,  # 'buy' or 'sell'
#             "price": price,
#         }
#         instrument = "ABCDEF"  #TODO: Replace with actual instrument symbol
#         order_id = place_order(instrument, quantity, order_type, side, price)
#         key = f"user_orders_{user_id}"
#         active_orders = cache.get(key, [])
#
#         if len(active_orders) < 2:
#             active_orders.append({"order_id": order_id, **order_details})
#             cache.set(key, active_orders, timeout=600)  # Store for 10 minutes
#
#         if len(active_orders) == 2:
#             processor = OrderProcessor(user_id)
#             processor.start_tracking()
#
#         return JsonResponse({"message": "Order placed", "active_orders": active_orders})

@retry_on_exception()
def place_order(instrument, quantity, order_type, side, price=None):
    """
    Places an order via the Fyers API and handles errors properly.

    :param fyers: Fyers API client instance
    :param instrument: Symbol of the stock or instrument
    :param quantity: Quantity of the order
    :param order_type: Order type (1 = Limit, others = Market)
    :param side: Order side (BUY or SELL)
    :param price: Limit price (only required for limit orders)
    :return: Order ID if successful, raises an exception otherwise
    """
    access_token = get_access_token()
    fyers = fyersModel.FyersModel(client_id=settings.FYERS_CLIENT_ID, token=access_token, is_async=False, log_path="")

    # Prepare order data
    order_data = {
        "symbol": instrument,
        "qty": quantity,
        "type": order_type,  # Market (2) or Limit (1)
        "side": side,  # "BUY" or "SELL"
        "productType": "INTRADAY",
        "limitPrice": price if order_type == 1 else None,  # Apply only for limit orders
        "validity": "DAY",
    }

    try:
        response = fyers.place_order(order_data)  # API Call

        # Check if API response exists
        if not response:
            raise RuntimeError("No response received from the order placement API.")

        # Validate API success
        if response.get("s") != "ok":
            error_message = response.get("message", "Unknown error occurred")
            raise RuntimeError(f"Order placement failed: {error_message}")

        # Extract Order ID
        order_id = response.get("id")
        if not order_id:
            raise RuntimeError("Order processing failed: Order ID is None.")

        return order_id

    except Exception as e:
        raise RuntimeError(f"Order placement error: {str(e)}")


# Global dictionary to store workers by table_id
worker_instances = {}


class PlaceBuySellOrders(APIView):
    def post(self, request, *args, **kwargs):
        """Handles Buy/Sell order placement per table."""
        print('worker instances', worker_instances)
        table_id = request.data.get("table_id")  # Get table_id from request
        new_click = request.data  # Expecting {"table_id": "123", "button": "buy", "symbol": "AAPL"}
        print('table id ', table_id, new_click)
        if not table_id:
            return Response({"error": "table_id is required"}, status=400)

        # Check if worker exists, otherwise create a new one
        if table_id not in worker_instances:
            worker_instances[table_id] = BackgroundProcessor(table_id)

        # Send click to the corresponding worker
        response_message = worker_instances[table_id].add_click(new_click)
        print('response message', response_message)
        return Response(response_message, status=200)
