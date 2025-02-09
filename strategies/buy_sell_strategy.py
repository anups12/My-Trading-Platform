import random
import threading
import time
from queue import Queue

from django.conf import settings
from fyers_apiv3 import fyersModel
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.logging_setup import get_strategy_logger
from accounts.models import OrderStrategy
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
                click1 = self.click_queue.get()
                click2 = self.click_queue.get()

                # Process clicks
                self.logger.debug('Both clicks received and processing')
                first_order = self.place_order(self.call_instrument, quantity=75, order_type=1, side=1, price=160)
                second_order = self.place_order(self.put_instrument, quantity=75, order_type=1, side=1, price=130)

                self.wait_for_order_confirmation(first_order, second_order)

            # Mark as completed
            with self.condition:
                self.is_processing = False  # Allow new clicks
                self.click_queue.queue.clear()  # Ensure queue is empty before new clicks

            self.logger.debug("Processing Completed. Ready for new commands.")

    def _get_message_from_queue(self, entry_order, exit_order):
        """
        Helper function to retrieve and identify a message for the specified orders.

        Args:
            entry_order (str): Order ID for the entry order.
            exit_order (str): Order ID for the exit order.

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
            if order_id == entry_order:
                self._clear_queue()
                return order_id, status, "entry"
            elif order_id == exit_order:
                self._clear_queue()
                return order_id, status, "exit"
            else:
                self.logger.debug(f"Order ID {order_id} does not match entry or exit order.")

        except Exception as e:
            self.logger.error(f"Error retrieving or parsing message from queue: {e}")
            return random.choice([(entry_order, 'ok', "exit"), (exit_order, 'ok', "entry")])

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



    def wait_for_order_confirmation(self, entry_order_id, exit_order_id):
        """Wait until the status of the specified orders is confirmed."""

        while not self.stop_event.is_set():
            try:
                # Retrieve message from the queue
                order_info = self._get_message_from_queue(entry_order_id, exit_order_id)
                if order_info:

                    order_id, status, order_type = order_info

                    self.logger.info(
                        f"Order confirmed: order_id={order_id}, status={status}, type={order_type}"
                    )

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
        fyers = fyersModel.FyersModel(client_id=settings.FYERS_CLIENT_ID, token=self.access_token, is_async=False, log_path="")

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
            self.logger.debug(f'response {response}' )
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

