import random
import threading
import time
from queue import Queue

from django.conf import settings
from fyers_apiv3 import fyersModel

from accounts.logging_setup import get_strategy_logger
from accounts.models import OrderStrategy, Orders
from accounts.utils import get_access_token, retry_on_exception
from accounts.websocket_handler import FyersWebSocketManager


class BackgroundProcessor:
    """
    A class to handle background processing of Buy/Sell button clicks.
    It waits for two clicks, processes them, and only then accepts new ones.
    """

    def __init__(self, table_id):
        self.table_id = table_id
        self.strategy = OrderStrategy.objects.get(table__id=table_id)
        self.click_queue = Queue()  # Queue for storing clicks
        self.lock = threading.Lock()  # Prevents new data when processing
        self.condition = threading.Condition()  # Controls waiting and signaling
        self.is_processing = False  # Tracks if a task is running
        self.thread = threading.Thread(target=self.process_clicks_worker, daemon=True)
        self.thread.start()  # Start background processing thread
        self.logger = get_strategy_logger(f"Strategy-{self.table_id}")
        self.access_token = get_access_token()
        self.ws_client = FyersWebSocketManager(self.access_token, self.logger)
        self.ws_client.start()
        self.call_instrument = self.strategy.main_instrument
        self.put_instrument = self.strategy.hedging_instrument
        self.stop_event = threading.Event()
        self.first_order_values = None
        self.second_order_values = None
        self.fyers = fyersModel.FyersModel(client_id=settings.FYERS_CLIENT_ID, token=self.access_token, is_async=False, log_path="")

    @staticmethod
    def _round_to_tick_size(price, tick_size):
        """Rounds a price to the nearest tick size."""
        return round(float(price) / tick_size) * tick_size

    def add_click(self, click_data):
        self.logger.info(f"Strategy started for strategy id: {self.strategy.id}")

        """Adds a click to the queue and wakes up the worker if needed."""
        with self.condition:
            if self.is_processing:
                return {"message": "Processing in progress. Please wait."}

            self.click_queue.put(click_data)

            if self.click_queue.qsize() >= 2:  # If two clicks are available, notify worker
                self.condition.notify()

        return {"message": "Click received. Waiting for second click."}

    def process_clicks_worker(self):
        """Runs in the background, waits for two clicks, processes them, and loops."""
        while True:
            with self.condition:
                while self.click_queue.qsize() < 2:
                    self.condition.wait()  # Wait for two clicks

                # Start processing
                self.is_processing = True

                # Retrieve two click commands
                self.first_order_values = self.click_queue.get()
                self.second_order_values = self.click_queue.get()

                # Process clicks
                self.logger.debug(f'Both clicks received and processing {self.first_order_values}, {self.second_order_values}')
                self.logger.info(self.first_order_values)
                self.logger.info(self.second_order_values)

                if self.first_order_values.get('callPrice') not in [None, '']:
                    quantity = self.first_order_values.get('callBuyQty') if self.first_order_values.get('action') == 'buy' else self.first_order_values.get('callSellQty')
                    price = self.first_order_values.get('callPrice')
                    instrument = self.call_instrument
                elif self.first_order_values.get('putPrice') not in [None, '']:
                    quantity = self.first_order_values.get('putBuyQty') if self.first_order_values.get('action') == 'buy' else self.first_order_values.get('putSellQty')
                    price = self.first_order_values.get('putPrice')
                    instrument = self.put_instrument
                price = self._round_to_tick_size(price, 0.05)
                side = 1 if self.first_order_values.get('action') == 'buy' else -1

                first_order = self.place_order(instrument, quantity=int(quantity), order_type=1, side=side, price=float(price))
                if first_order:
                    Orders.objects.create(entry_order_id=first_order, entry_order_status=2, order_side='buy', is_entry=True, order_quantity=quantity, entry_price=price)
                    order_id = self.place_order(self.put_instrument if instrument == self.call_instrument else self.call_instrument, quantity=int(quantity), order_type=2, side=1)
                    if order_id:
                        Orders.objects.create(entry_order_id=order_id, entry_order_status=1, order_side='buy', is_entry=True, order_quantity=quantity)
                if self.second_order_values.get('callPrice') not in [None, '']:
                    quantity = self.second_order_values.get('callBuyQty') if self.second_order_values.get('action') == 'buy' else self.second_order_values.get('callSellQty')
                    price = self.second_order_values.get('callPrice')
                elif self.second_order_values.get('putPrice') not in [None, '']:
                    quantity = self.second_order_values.get('putBuyQty') if self.second_order_values.get('action') == 'buy' else self.second_order_values.get('putSellQty')
                    price = self.second_order_values.get('putPrice')

                price = self._round_to_tick_size(price, 0.05)
                side = 1 if self.second_order_values.get('action') == 'buy' else -1

                second_order = self.place_order(self.put_instrument, quantity=int(quantity), order_type=1, side=side, price=float(price))
                if second_order:
                    Orders.objects.create(entry_order_id=second_order, entry_order_status=2, order_side='buy', is_entry=True, order_quantity=price, entry_price=quantity)
                    order_id = self.place_order(self.put_instrument if instrument == self.call_instrument else self.call_instrument, quantity=int(quantity), order_type=2, side=1)
                    if order_id:
                        Orders.objects.create(entry_order_id=order_id, entry_order_status=1, order_side='buy', is_entry=True, order_quantity=quantity)

                self.wait_for_order_confirmation(first_order, second_order)

            # Mark as completed
            with self.condition:
                self.is_processing = False  # Allow new clicks
                self.click_queue.queue.clear()  # Ensure queue is empty before new clicks

            self.logger.debug("Processing Completed. Ready for new commands.")

    def _get_message_from_queue(self, first_order, second_order):
        """
        Helper function to retrieve and identify a message for the specified orders.

        Args:
            first_order (str): Order ID for the entry order.
            second_order (str): Order ID for the exit order.

        Returns:
            tuple: A tuple (order_id, status, order_type), where `order_type` is either
                   "entry" or "exit". Returns None if no matching message is found.
        """
        try:
            # Fetch message from the queue with a timeout
            message = self.ws_client.q.get(timeout=1)

            # Validate and parse the message structure
            if message.get("s") != "ok":
                self.logger.warning(f"Invalid WebSocket message status: {message.get('s')}")
                return None

            # Extract order details
            orders = message.get("orders", {})
            order_id = orders.get("id")
            status = message.get("s")  # This corresponds to the order status

            # Determine if the message matches the entry or exit order
            if order_id == first_order:
                self._clear_queue()
                return order_id, status, "first_order"
            elif order_id == second_order:
                self._clear_queue()
                return order_id, status, "second_order"
            else:
                self.logger.debug(f"Order ID {order_id} does not match entry or exit order.")

        except Exception as e:
            self.logger.error(f"Error retrieving or parsing message from queue: {e}")
            return random.choice([(first_order, 'ok', "exit"), (second_order, 'ok', "entry")])

        return None  # Default return if no matching message is found

    def _clear_queue(self):
        """
        Helper function to clear all remaining messages in the queue.
        """
        try:
            while not self.ws_client.q.empty():
                self.ws_client.q.get_nowait()  # Non-blocking removal of messages
            self.logger.debug("Queue cleared.")
        except Exception as e:
            self.logger.error(f"Error while clearing the queue: {e}")

    def wait_for_order_confirmation(self, first_order, second_order):
        """Wait until the status of the specified orders is confirmed."""

        while not self.stop_event.is_set():
            try:
                # Retrieve message from the queue
                order_info = self._get_message_from_queue(first_order, second_order)
                if order_info:
                    order_id, status, order_type = order_info

                    self.logger.info(
                        f"Order confirmed: order_id={order_id}, status={status}, type={order_type}"
                    )
                    if order_type == 'first_order':
                        Orders.objects.filter(entry_order_id=order_id).update(entry_order_status=1)
                        self.logger.debug(f"Order {order_id} updated to status 1")
                        self.cancel_orders(second_order)
                    elif order_type == 'second_order':
                        Orders.objects.filter(entry_order_id=order_id).update(entry_order_status=1)
                        self.logger.debug(f"Order {order_id} updated to status 1 second")
                        self.cancel_orders(first_order)

                    self.stop_event.set()
            except Exception as e:
                self.logger.error(f"Unexpected error while retrieving or processing message: {e}")
            finally:
                time.sleep(0.1)  # Prevent high CPU usage during polling

    @retry_on_exception()
    def place_order(self, instrument, quantity, order_type, side, price=None):
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
            response = self.fyers.place_order(order_data)  # API Call
            self.logger.debug(f'response {response}')
            # Check if API response exists
            if not response:
                raise RuntimeError("No response received from the order placement API.")

            # Validate API success
            if response.get("s") == "ok":
                error_message = response.get("message", "Unknown error occurred")
                raise RuntimeError(f"Order placement failed: {error_message}")

            # Extract Order ID
            order_id = response.get("id")
            if not order_id:
                raise RuntimeError("Order processing failed: Order ID is None.")

            return order_id

        except Exception as e:
            raise RuntimeError(f"Order placement error: {str(e)}")

    def cancel_orders(self, order_id=None):
        """
        Cancel a specific order or all incomplete orders for the current strategy.

        Args:
            order_id (str, optional): The ID of the order to cancel.
                                      If None, cancels all incomplete orders for the current strategy.

        Returns:
            list: A list of responses from the cancel order API.
        """
        cancelled_orders = []

        try:
            if order_id:
                self.logger.info(f"Attempting to cancel order: {order_id}")
                data = {"id": order_id}
                response = self.fyers.cancel_order(data=data)

                if response.get('s') != "ok":
                    order = Orders.objects.filter(entry_order_id=order_id, is_complete=False).first()
                    self.logger.info(f"Cancelling order for Order id {order_id} | {order.id}")
                    if order:
                        if order.entry_order_id == order_id:
                            order.entry_order_status = 3
                            order.entry_order_id = None
                            order.entry_price = None
                        elif order.exit_order_id == order_id:
                            order.exit_order_status = 3
                            order.exit_order_id = None
                            order.exit_price = None

                        order.is_complete = True
                        order.save()
                        self.logger.info(f"Order {order_id} successfully updated to 'cancelled'.")
                    else:
                        self.logger.warning(f"Order {order_id} not found in the database.")
                else:
                    self.logger.error(f"Failed to cancel order {order_id}. Response: {response}")

                cancelled_orders.append(response)
            else:
                orders = Orders.objects.filter(
                    level__strategy=self.strategy,
                    entry_order_status=2,
                    is_complete=False,
                    exit_order_id__isnull=True
                )
                self.logger.debug(f"Found {orders.count()} pending orders to cancel.")

                for order in orders:
                    try:
                        data = {"id": order.entry_order_id}  # Assuming entry_order_id is the correct field
                        self.logger.info(f"Attempting to cancel order: {data['id']}")
                        response = self.fyers.cancel_order(data=data)
                        order_id = response.get('id')

                        if response.get('s') == "ok":
                            if order.entry_order_id == order_id:
                                self.logger.debug(f"Updating entry order id {order.entry_order_id}")
                                order.entry_order_status = 3
                                order.entry_order_id = None
                                order.entry_price = None
                            elif order.exit_order_id == order_id:
                                self.logger.debug(f"Updating exit order id {order.exit_order_id}")
                                order.exit_order_status = 3
                                order.exit_order_id = None
                                order.exit_price = None

                            order.is_complete = True
                            order.save()
                            self.logger.debug(f"Order {data['id']} successfully updated to 'cancelled'.")
                        else:
                            self.logger.error(f"Failed to cancel order {data['id']}. Response: {response}")

                        cancelled_orders.append(response)
                    except Exception as e:
                        self.logger.error(f"Error while cancelling order {order.entry_order_id}: {e}")
                        continue  # Log the error and move to the next order

        except Exception as e:
            self.logger.error(f"Unexpected error in cancel_orders: {e}")

        return cancelled_orders
