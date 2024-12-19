import logging
import threading
import time

from celery.platforms import strargv
from fyers_apiv3 import fyersModel
from accounts.models import Orders, OrderLevel
from accounts.utils import client_id, round_to_tick_size, get_order_status_value
from accounts.websocket_handler import FyersWebSocketManager


class TradingStrategy:
    lock = threading.Lock()

    def __init__(self, strategy_parameters):
        # Strategy Parameters
        self.strategy_parameters = strategy_parameters
        self.strike_distance = self.strategy_parameters.get("strike_distance")
        self.strike_direction = self.strategy_parameters.get("strike_direction")
        self.hedging_strike_distance = self.strategy_parameters.get("hedging_strike_distance")
        self.hedging_strike_direction = self.strategy_parameters.get("hedging_strike_direction")
        self.strategy = self.strategy_parameters.get("strategy")
        self.main_target = self.strategy_parameters.get("main_target")
        self.data_table = self.strategy_parameters.get("data_table")
        self.hedging_limit_price = self.strategy_parameters.get("hedging_limit_price")
        self.instrument = self.strategy.main_instrument
        self.hedging_instrument = self.strategy.hedging_instrument
        self.access_token = self.strategy_parameters.get("access_token")
        self.index = self.strategy_parameters.get("index")
        self.expiry = self.strategy_parameters.get("expiry")

        # Configure logging dynamically for the strategy
        log_filename = f"trading_strategy_{self.strategy.id}.log"
        logging.basicConfig(
            filename=log_filename,
            filemode='a',  # Append to the log file
            format='%(asctime)s - %(levelname)s - %(message)s',
            level=logging.DEBUG
        )

        logging.info(f"Initialized TradingStrategy1 with ID: {self.strategy.id}")

        # Strategy configurations
        self.stop_event = threading.Event()
        self.current_level_index = 0  # Start at the first level
        self.current_level = None
        self.previous_level = None
        self.next_level = None
        self.levels_length = None
        self.fyers = fyersModel.FyersModel(client_id=client_id, token=self.access_token, is_async=False, log_path="")
        self.ws = None


    def run_strategy(self):
        """Starts the strategy."""
        try:
            logging.info(f"Strategy started for strategy id: {self.strategy.id}")
            # Websocket Setup
            self.ws = FyersWebSocketManager(access_token=self.access_token)
            try:
                self.ws.start()
                logging.info('websocket started')
            except Exception as e:
                logging.error("Websocket connection failed...")
                raise

            self.fetch_levels()

            logging.info(f"Placing initial market order.. for level: {self.current_level}")
            # Place the initial market order
            self.place_initial_market_order(self.current_level)

            logging.info(f"Processing next Level Index: {self.current_level_index}")
            # Begin processing from the next level
            self.process_next_level()

        except Exception as e:
            logging.error(f"Error in strategy: {e}")

    def fetch_levels(self, current_level=None):
        """Fetch levels from the OrderLevels model."""
        with self.lock:
            # Initialize index based on provided current_level
            self.current_level_index = current_level if current_level is not None else 0

            # Fetch all levels for the strategy at once
            levels_queryset = OrderLevel.objects.filter(strategy=self.strategy).order_by('level_number')

            # Convert queryset to a list for easier indexing
            levels = list(levels_queryset)

            # Get current level
            self.current_level = next((level for level in levels if level.level_number == self.current_level_index), None)

            # Get previous level (if exists)
            if self.current_level_index > 0:
                self.previous_level = next((level for level in levels if level.level_number == self.current_level_index - 1), None)
            else:
                self.previous_level = None  # No previous level exists

            self.levels_length = max(levels, key=lambda x: x.level_number).level_number
            # Get next level (if exists)
            if self.current_level_index < self.levels_length:
                self.next_level  = next((level for level in levels if level.level_number == self.current_level_index + 1), None)
            else:
                self.next_level = None  # No next level exists

    def on_order_update(self, message):
        """Handles updates for orders via WebSocket."""

        fyers_order_id = message.get("id")
        status = message.get("status")
        print('order update is coming from websocket', fyers_order_id, status)
        if fyers_order_id and status:
            with self.lock:
                order = Orders.objects.filter(fyers_order_id=fyers_order_id).first()
                if order:
                    # Update the appropriate status field
                    if order.order_type == "entry":
                        order.entry_order_status = status.lower()
                    elif order.order_type == "exit":
                        order.exit_order_status = status.lower()
                    order.status = status.lower()
                    order.save()

                    # If the entry order is filled, move to the next level
                    if status.lower() == "filled" and order.order_type == "entry":
                        self.is_waiting_for_response = False
                        self.process_next_level()

    def process_next_level(self):
        """Processes the next level in the strategy."""
        if self.current_level_index >= self.levels_length:
            self.stop_strategy()
            return

        self.fetch_levels(self.current_level_index)
        print('cureent sads', self.current_level, self.previous_level, self.next_level)
        try:
            print('PLACE ORDERS SECOND ORDER')
            # Place entry order (buy) for the next level
            entry_order = self.place_order(
                order_type=1,
                side=1,
                order_role="entry",
                level=self.next_level
            )

            # Place exit order (sell) for the current level
            print('PLACE ORDERS FIRST ORDER')
            exit_order = self.place_order(
                order_type=1,
                side=-1,
                order_role="exit",
                level=self.current_level
            )
            print('both limit orders sent for level', self.current_level_index)
            self.wait_for_order_confirmation(entry_order, exit_order)

        except Exception as e:
            print(f"Error processing level {self.current_level}: {e}")

    def wait_for_order_confirmation(self, entry_order, exit_order):
        """Waits until the status of all orders is confirmed."""
        while not self.stop_event.is_set():
            try:
                # Non-blocking queue retrieval
                message = None
                with self.lock:
                    if not self.ws.q.empty():
                        message = self.ws.q.get(timeout=1)
                        print('message received', message)

                # Process the message if retrieved
                if message:
                    print('Message received from WebSocket:', message)
                    if entry_order in message or exit_order in message:
                        print("Strategy order submitted through WebSocket:", message)

            except self.ws.q.Empty:
                print("Queue timeout while waiting for message.")
            except Exception as e:
                print(f"Unexpected threading error: {e}")
            finally:
                # Sleep briefly to prevent high CPU usage
                time.sleep(0.1)

    def place_initial_market_order(self, level):
        """Places a market order for the first level."""
        print(f"Placing initial market order...{level}")

        try:
            order_id = self.place_order(
                order_type=2,
                side=1,
                order_role="entry",
                level=level
            )
            # if order_id:
            #     max_attempts = 20
            #     attempt_interval = 1  # in seconds
            #
            #     for attempt in range(max_attempts):
            #         status = self.get_order_status(order_id)
            #         print(f'Order ID {order_id}: Checking status (Attempt {attempt + 1}/{max_attempts}) - Status: {status}')
            #
            #         if status == 'Filled':
            #             print('reached here', order_id)
            #             order = Orders.objects.get(entry_order_id=order_id, level=self.current_level)
            #             print('getting order', order)
            #             order.entry_order_status = get_order_status_value(status)
            #             order.is_entry = True
            #             order.save()
            #             break
            #         elif attempt < max_attempts - 1:
            #             time.sleep(attempt_interval)
            #     else:
            #         print(f'Order ID {order_id}: Status check failed after {max_attempts} attempts')
        except Exception as e:
            print(f"Error placing initial market order: {e}")

    def stop_strategy(self):
        """Stops the strategy."""
        self.stop_event.set()
        if self.ws_manager:
            self.ws_manager.stop()

    def place_order(self, order_type, side, order_role, level):
        if side == 1:
            price = level.main_percentage
            quantity = level.main_quantity
            price = round_to_tick_size(price, tick_size=.05)
            fyers = fyersModel.FyersModel(client_id=client_id, token=self.access_token)
            order_data = {
                "symbol": self.instrument,
                "qty": quantity,
                "type": order_type,  # Market or Limit
                "side": side,  # Buy or Sell
                "productType": "INTRADAY",
                "limitPrice": price  if order_type == 1 else None,
                "validity": "DAY",
            }
        else:
            price = level.main_target
            quantity = level.main_quantity
            price = round_to_tick_size(price, tick_size=.05)
            fyers = fyersModel.FyersModel(client_id=client_id, token=self.access_token)
            order_data = {
                "symbol": self.instrument,
                "qty": quantity,
                "type": order_type,  # Market or Limit
                "side": side,  # Buy or Sell
                "productType": "INTRADAY",
                "limitPrice": price if order_type == 1 else None,
                "validity": "DAY",
            }

        response = fyers.place_order(order_data)
        if response.get("code") == 200:
            order_id = response["id"]
            status = "open"

            with self.lock:
                Orders.objects.create(
                    instrument=self.instrument,
                    level=level,
                    entry_price=price,
                    order_quantity=quantity,
                    entry_order_id=order_id if order_role == "entry" else None,
                    entry_order_status=status if order_role == "entry" else None,
                )
            return {"order_id": order_id, "status": status}
        else:
            raise Exception(f"Order placement failed: {response.get('message')}")
