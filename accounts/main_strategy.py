import queue
import random
import threading
import time

import requests
from fyers_apiv3 import fyersModel

from accounts.constants import OrderTypeEnum, TransactionTypeEnum, OrderRoleEnum
from accounts.logging_setup import get_strategy_logger
from accounts.models import Orders, OrderLevel
from accounts.utils import client_id, get_instrument, create_table, OrderPlacementError, retry_on_exception
from accounts.websocket_handler import FyersWebSocketManager


class TradingStrategy1:
    lock = threading.Lock()

    def __init__(self, strategy_parameters):

        # Validate required parameters
        required_params = ["strategy", "target", "hedging_limit_price", "access_token", "index", "expiry"]
        for param in required_params:
            if param not in strategy_parameters:
                raise ValueError(f"Missing required parameter: {param}")

        # Strategy Parameters
        self.strategy_parameters = strategy_parameters
        self.strike_distance = self.strategy_parameters.get("strike_distance", 0)
        self.strike_direction = self.strategy_parameters.get("strike_direction", 'call')
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

        self.logger = get_strategy_logger(f"Strategy-{self.strategy.id}")

        # Strategy configurations
        self.stop_event = threading.Event()
        self.current_level_index = 0  # Start at the first level
        self.ws_client = FyersWebSocketManager(self.access_token)
        self.current_level = None
        self.previous_level = None
        self.next_level = None
        self.levels_length = None
        self.fyers = fyersModel.FyersModel(client_id=client_id, token=self.access_token, is_async=False, log_path="")
        self.is_active = self.strategy.is_active

    def run_strategy(self):
        """Starts the strategy."""
        self.logger.info(f"Strategy started for strategy id: {self.strategy.id}")

        # Initialize and start WebSocket client
        try:
            self.ws_client.start()
            self.ws_client.subscribe()

            self.logger.info("WebSocket started successfully.")
        except Exception as e:
            self.logger.error(f"WebSocket connection failed: {e}")
            self.stop_strategy()
            return  # Stop further execution

        # Fetch levels needed for the strategy
        try:
            self.fetch_levels()
            self.logger.info("Levels fetched successfully.")
        except Exception as e:
            self.logger.error(f"Failed to fetch levels: {e}")
            self.stop_strategy()
            return  # Stop further execution

        # Place the initial market order
        try:
            self.place_initial_market_order(self.current_level)
            self.logger.info("Initial market order placed successfully.")
        except Exception as e:
            self.logger.error(f"Initial market order failed: {e}")
            self.stop_strategy()
            return  # Stop further execution

        # Process subsequent levels
        try:
            self.logger.info(f"Processing next Level Index: {self.current_level_index}")
            self.process_next_level()
        except Exception as e:
            self.logger.error(f"Error while processing next level: {e}")
            self.stop_strategy()

    def process_next_level(self):
        """Processes the next level in the strategy."""
        try:
            if self.current_level_index >= self.levels_length:
                self.logger.debug("All levels processed. Stopping strategy.")
                self.stop_strategy()
                return

            # Fetch levels for the current index
            self.fetch_levels(self.current_level_index)
            self.logger.debug(f"Processing Level: {self.current_level_index}, "
                              f"Current: {self.current_level}, Previous: {self.previous_level}, Next: {self.next_level}")

            # Place orders for the current and next levels
            entry_order = self._place_and_process_order(
                order_type=OrderTypeEnum.LIMIT_ORDER.value,
                side=TransactionTypeEnum.BUY.value,
                order_role=OrderRoleEnum.ENTRY.value,
                level=self.next_level,
                is_hedging_order=False,
            )
            exit_order = self._place_and_process_order(
                order_type=OrderTypeEnum.LIMIT_ORDER.value,
                side=TransactionTypeEnum.SELL.value,
                order_role=OrderRoleEnum.EXIT.value,
                level=self.next_level,
                is_hedging_order=False,
            )

            self.logger.info(f"Both orders sent for level {self.current_level_index}: Entry={entry_order}, Exit={exit_order}")

            # Wait for confirmation of the orders
            self.wait_for_order_confirmation(entry_order, exit_order)

        except ValueError as ve:
            self.logger.debug(f"Configuration error: {ve}")
        except OrderPlacementError as ope:
            self.logger.debug(f"Order placement failed for level {self.current_level_index}: {ope}")
        except Exception as e:
            self.logger.debug(f"Unexpected error processing level {self.current_level_index}: {e}")

    def wait_for_order_confirmation(self, entry_order, exit_order):
        """Wait until the status of the specified orders is confirmed."""
        while not self.stop_event.is_set():
            try:
                # Attempt to retrieve a message from the queue
                message = self._get_message_from_queue()  # TODO: changes this later
                time.sleep(10)
                message = random.choice([{'id': entry_order}, {'id': exit_order}])
                if message:
                    order_id = message.get('id')  # TODO: changes this later
                    self.logger.debug(f'Order id received {order_id}')
                    # status = message.get('s')
                    status = 'ok'  # TODO: change this later

                    self.logger.debug(f"Message received: {message}")
                    self.logger.debug(f"Orders checking: entry_order={entry_order}, exit_order={exit_order}")

                    if order_id == entry_order:
                        self.logger.info(f"Processing entry order: {entry_order}")
                        self._process_order(entry_order, exit_order, status, "entry")
                        break  # Ensure the loop stops

                    elif order_id == exit_order:
                        self.logger.info(f"Processing exit order: {exit_order}")
                        self._process_order(entry_order, exit_order, status, "exit")
                        break  # Ensure the loop stops

                    else:
                        self.logger.debug(f"Order ID {order_id} does not match entry or exit orders.")

            except queue.Empty:
                self.logger.debug("Queue timeout while waiting for message.")

            except Exception as e:
                self.logger.error(f"Unexpected error while retrieving or processing message: {e}")

            finally:
                time.sleep(0.1)  # Prevent high CPU usage during polling

        # Stop event was triggered or an order was processed
        self.logger.info("Exiting order confirmation loop.")

    def _process_order(self, entry_order, exit_order, status, order_type):
        """Processes the order confirmation based on its type."""
        if status == 'ok':
            if order_type == "entry":
                self._handle_entry_order({}, entry_order, exit_order, status)
            elif order_type == "exit":
                self._handle_exit_order({}, entry_order, exit_order, status)
        else:
            self.logger.error(f"{order_type} order failed with status: {status}")

    def _get_message_from_queue(self):
        """Helper function to retrieve a message from the WebSocket queue."""
        with self.lock:
            if not self.ws_client.q.empty():
                return self.ws_client.q.get(timeout=1)
        return None

    def _handle_entry_order(self, message, entry_order, exit_order, status):
        """Handles entry order-specific logic."""
        self.logger.info(f'Entry Order placed from websocket {entry_order}')
        try:
            with self.lock:
                order = Orders.objects.filter(entry_order_id=entry_order).first()
                self.logger.debug(f'Entry order received for next level {order}, Level: {self.current_level}')
                if not order:
                    self.logger.error(f"Order not found for Entry order:{entry_order} Level {self.current_level}")
                    raise Orders.DoesNotExist

                # Update order details
                order.entry_order_status = 1 if status == 'ok' else 2
                order.is_entry = True
                order.save()
                self.logger.info(f"Order Updated successfully: Entry Order:{entry_order} Level {self.current_level}")

            if self.strategy.is_hedging:
                # Place hedging orders if the strategy requires it
                hedging_order = self._place_and_process_order(
                    order_type=OrderTypeEnum.MARKET_ORDER.value,
                    side=TransactionTypeEnum.BUY.value,
                    order_role=OrderRoleEnum.ENTRY.value,
                    level=self.current_level,
                    is_hedging_order=True,
                )
                self.logger.info(f"Hedging market order placed successfully. Order ID: {hedging_order}")

            self.cancel_orders(exit_order)
            self.current_level_index += 1
            self.logger.info(f'Processing next level... {self.current_level_index}')
            self.process_next_level()
        except Exception as ex:
            self.logger.debug(f'Exception happened inside handle_entry_order: {ex}')

    def _handle_exit_order(self, message, entry_order, exit_order, status):
        """Handles exit order-specific logic."""
        self.logger.info(f'Exit Order placed from websocket {exit_order}')
        try:
            with self.lock:
                order = Orders.objects.filter(level=self.current_level, exit_order_id=exit_order).first()
                self.logger.debug(f'Exit order found Order: {order}')
                if not order:
                    self.logger.debug(f"Exit Order Not found for Order ID: {exit_order}, Level: {self.current_level}")
                    raise Orders.DoesNotExist

                self.logger.info(f"Updating Exit order: Order Level: {exit_order}, Level: {self.current_level_index}")
                # Update order details
                order.exit_order_status = 1 if status == 'ok' else 2
                order.is_completed = True
                order.save()
                self.logger.info(f"Exit Order updated successfully: {exit_order}")

            if self.strategy.is_hedging:
                self.logger.debug("Exiting hedging order ")
                if self.strategy.is_hedging:
                    # Place hedging orders if the strategy requires it
                    hedging_order = self._place_and_process_order(
                        order_type=OrderTypeEnum.MARKET_ORDER.value,
                        side=TransactionTypeEnum.SELL.value,
                        order_role=OrderRoleEnum.EXIT.value,
                        level=self.current_level,
                        is_hedging_order=True,
                    )
                    self.logger.info(f"Hedging market order placed successfully. Order ID: {hedging_order}")

            # Strategy logic
            if self.current_level_index == 0:
                self.logger.info('Exit strategy logic triggered')
                self._execute_exit_strategy()
            else:
                self.current_level_index -= 1
                self.cancel_orders(entry_order)
                self.logger.info('Processing next level...')
                self.process_next_level()

        except Orders.DoesNotExist:
            self.logger.error(f"No matching order found for exit_order_id: {exit_order}")
        except Exception as e:
            self.logger.error(f"Error while handling exit order: {e}")

    def _execute_exit_strategy(self):
        """Executes the strategy exit logic and resets for a new instrument."""

        # Todo: Add logic for hedging instrument also
        self.logger.debug('Exit strategy mechanism triggered')
        self.cancel_orders()
        self.close_all_open_orders()
        self.strike_direction = 'call' if self.strike_direction == 'put' else 'put'
        instrument_symbol, instrument_price = get_instrument(
            self.index, self.expiry, self.strike_distance, self.strike_direction
        )
        create_table(instrument_price, self.main_target, self.strategy, self.hedging_limit_price)
        self.instrument = instrument_symbol
        self.strategy.main_instrument = self.instrument
        self.strategy.save()
        self.run_strategy()

    def place_initial_market_order(self, level):
        """Places a market order for the first level and optional hedging orders."""
        try:
            # Validate level
            if not level:
                self.logger.error("Level information is missing.")
                raise ValueError("Level information is required.")

            # Place the initial market order
            initial_order = self._place_and_process_order(
                order_type=OrderTypeEnum.MARKET_ORDER.value,
                side=TransactionTypeEnum.BUY.value,
                order_role=OrderRoleEnum.ENTRY.value,
                level=level,
                is_hedging_order=False,
            )
            self.logger.info(f"Initial market order placed successfully. Order ID: {initial_order}")

            # Place hedging orders if the strategy requires it
            if self.strategy.is_hedging:
                hedging_order = self._place_and_process_order(
                    order_type=OrderTypeEnum.MARKET_ORDER.value,
                    side=TransactionTypeEnum.BUY.value,
                    order_role=OrderRoleEnum.ENTRY.value,
                    level=level,
                    is_hedging_order=True,
                )
                self.logger.info(f"Hedging market order placed successfully. Order ID: {hedging_order}")

        except Exception as e:
            self.logger.critical(f"Error while placing initial market order: {e}", exc_info=True)
            raise

    def _place_and_process_order(self, order_type, side, order_role, level, is_hedging_order):
        """Places an order and processes the response."""
        response, price, quantity = self.place_order(
            order_type=order_type,
            side=side,
            order_role=order_role,
            level=level,
            is_hedging_order=is_hedging_order,
        )

        # Validate API response
        if response.get('s') != 'error':
            self.logger.error(f"Order placement failed. Response: {response}")
            raise RuntimeError(f"Order placement failed: {response}")

        order_id = response.get("id")

        if not order_id:
            self.logger.error("Failed to process the order: Order ID is None.")
            raise RuntimeError("Order processing failed: Order ID is None.")

        # Handle order response
        self._handle_order_response(order_id, order_role, level, price, quantity, order_type, is_hedge=is_hedging_order)
        return order_id

    def stop_strategy(self):
        """Stops the strategy."""
        self.logger.info("Stopping strategy")
        self.stop_event.set()
        self.cleanup()

    def fetch_levels(self, current_level=None):
        """Fetch levels from the OrderLevels model."""
        with self.lock:

            # Initialize index based on provided current_level
            self.current_level_index = current_level if current_level is not None else 0

            # Fetch all levels for the strategy at once
            levels_queryset = OrderLevel.objects.filter(strategy=self.strategy, strategy__main_instrument=self.instrument).order_by('level_number')

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
                self.next_level = next((level for level in levels if level.level_number == self.current_level_index + 1), None)
            else:
                self.next_level = None  # No next level exists
            self.logger.info(f'New Levels, Current: {self.current_level}, Next: {self.next_level}, Previous: {self.previous_level}', )

    def get_all_orders(self, order_id):
        return

    def cancel_orders(self, order_id=None):
        """Cancel a specific order or all incomplete orders for the current strategy."""
        cancelled_orders = []

        if order_id:
            self.logger.debug(f"Cancelling order {order_id}")
            data = {"id": order_id}
            response = self.fyers.cancel_order(data=data)
            self.logger.debug(f"Cancelled order response: {response}")
            cancelled_orders.append(response)
        else:
            orders = Orders.objects.filter(level__strategy=self.strategy, entry_order_status=2, is_complete=False, exit_order_id=None)

            for order in orders:
                data = {"id": order.entry_order_id}  # Assuming entry_order_id is the correct field
                self.logger.debug(f"Cancelling order {data['id']}")
                response = self.fyers.cancel_order(data=data)
                self.logger.debug(f"Cancelled order response: {response}")
                cancelled_orders.append(response)

        return cancelled_orders

    def close_all_open_orders(self):
        data = {}
        response = self.fyers.exit_positions(data=data)
        self.logger.info(f'All Open orders closed. Closed Orders {response}')
        return response

        # Helper methods

    def cleanup(self):
        self.logger.info("Cleaning up resources...")
        self.close_all_open_orders()
        self.cancel_orders()
        self.logger.info("Cleanup complete.")

    def place_order(self, order_type, side, order_role, level, is_hedging_order=False):
        """Places an order and returns the response."""
        try:
            if not level:
                raise ValueError("Level information is required.")

            # Prepare order details
            price, quantity, order_data = self._prepare_and_calculate_order(
                side, level, order_type, is_hedging_order=is_hedging_order
            )

            # Send order request
            response = self._send_order_request(order_data)
            return response, price, quantity
        except Exception as e:
            self.logger.error(f"Error during order placement: {e}", exc_info=True)
            raise

    @retry_on_exception(exceptions=(requests.RequestException,))
    def _send_order_request(self, order_data):
        """Sends the order request to the API with retry logic."""
        return self.fyers.place_order(order_data)

    def _prepare_and_calculate_order(self, side, level, order_type, is_hedging_order=False):
        """Calculates the order price and quantity, and prepares the order data."""
        try:
            if is_hedging_order:
                # Calculate the price and quantity for hedging order
                price = ''
                quantity = level.hedging_quantity
                instrument = self.hedging_instrument
            else:
                # Calculate the price and quantity
                price = level.main_percentage if side == 1 else level.main_target
                quantity = level.main_quantity

                # Round price to the nearest tick size
                price = self._round_to_tick_size(price, tick_size=0.05)
                instrument = self.instrument
            self.logger.debug(f"Calculated order price: {price}, quantity: {quantity}")

            # Prepare order data for API request
            order_data = {
                "symbol": instrument,
                "qty": quantity,
                "type": order_type,  # Market or Limit
                "side": side,  # Buy or Sell
                "productType": "INTRADAY",
                "limitPrice": price if order_type == 1 else None,
                "validity": "DAY",
            }

            self.logger.debug(f"Prepared order data: {order_data}")
            return price, quantity, order_data

        except AttributeError as e:
            self.logger.error("Invalid level data structure.", exc_info=True)
            raise ValueError("Invalid level data structure.") from e
        except Exception as e:
            self.logger.error(f"Error preparing order: {e}", exc_info=True)
            raise RuntimeError(f"Error preparing order for level {level}: {e}")

    def _handle_order_response(self, order_id, order_role, level, price, quantity, order_type, is_hedge=False):
        """Handles the response after an order is placed."""
        self.logger.debug(f'Inside handle order response {order_id} Level: {level} Price: {price} IS Hedging {is_hedge} Order Role {order_role}')
        try:
            with self.lock:
                if order_role == "entry":
                    self._create_entry_order(level, price, quantity, order_id, order_type, is_hedge=is_hedge)
                elif order_role == "exit":
                    self._update_exit_order(order_id, price, is_hedge=is_hedge)
                else:
                    raise ValueError(f"Invalid order role: {order_role}")
        except Exception as e:
            self.logger.error(f"Error processing order response: {e}", exc_info=True)
            self.stop_thread = True
            raise

    def _create_entry_order(self, level, price, quantity, order_id, order_type, is_hedge=False):
        try:
            Orders.objects.create(
                level=level,
                entry_price=price if price else None,
                order_quantity=quantity,
                entry_order_id=order_id,
                entry_order_status=1 if order_type == 2 else 2,
                is_entry=True,
                is_main=False if is_hedge else True
            )
            self.logger.debug("Entry order record successfully created.")
        except Exception as e:
            self.logger.error(f"Failed to create entry order record for level {level}: {e}")
            self.stop_thread = True  # Stop the thread if an error occurs
            raise RuntimeError(f"Error creating entry order for level {level}: {e}")

    def _update_exit_order(self, order_id, price, is_hedge=False):
        try:
            is_main = False if is_hedge else True
            self.logger.debug(f"Update exit order Is hedging {is_main}")
            order = Orders.objects.filter(level=self.current_level, is_entry=True, is_main=is_main).first()
            self.logger.debug(f"Order for Exit Order Level {self.current_level} Is main order : {is_main} | Order: {order}")
            if not order:
                raise RuntimeError(f"No entry order found for level {self.current_level} to update exit order.")

            # Update the exit order details
            order.exit_order_status = 1  # Assuming '1' signifies completed exit
            order.exit_order_id = order_id
            order.is_completed = True
            order.exit_price = price
            order.save()
            self.logger.debug("Exit order record successfully updated.")
        except RuntimeError as re:
            self.logger.error(f"Critical error updating exit order: {re}")
            self.stop_thread = True  # Stop the thread if an error occurs
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error while updating exit order: {e}")
            self.stop_thread = True  # Stop the thread if an error occurs
            raise RuntimeError(f"Error updating exit order for level {self.current_level}: {e}")

    @staticmethod
    def _round_to_tick_size(price, tick_size):
        """Rounds a price to the nearest tick size."""
        return round(float(price) / tick_size) * tick_size
