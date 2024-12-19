import json
import logging
import queue
import re
import threading
import time

import requests
from fyers_apiv3 import fyersModel

from accounts.models import Orders, OrderLevel
from accounts.utils import client_id, round_to_tick_size, account_id, get_order_status_value, get_instrument, create_table
from ib_websocket import WebSocketClient

baseUrl = "https://localhost:5000/v1/api"

symbol_for_Placing_order = 674993368


class TradingStrategy1:
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
        self.ws_client = None
        self.current_level = None
        self.previous_level = None
        self.next_level = None
        self.levels_length = None
        self.fyers = fyersModel.FyersModel(client_id=client_id, token=self.access_token, is_async=False, log_path="")

    def run_strategy(self):
        """Starts the strategy."""
        try:
            logging.info(f"Strategy started for strategy id: {self.strategy.id}")
            # Websocket Setup
            websocket_url = "wss://localhost:5000/v1/api/ws"
            # Create and start the shared WebSocket client
            self.ws_client = WebSocketClient(websocket_url)
            try:
                self.ws_client.start()
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

    def process_next_level(self):
        """Processes the next level in the strategy."""
        logging.info('reached here second time')
        try:
            if self.current_level_index >= self.levels_length:
                print('strategu is stopped here', self.current_level_index, self.levels_length)
                self.stop_strategy()
                return

            # Fetch levels for the current index
            self.fetch_levels(self.current_level_index)
            logging.debug(f"Processing Level: {self.current_level_index}, "
                          f"Current: {self.current_level}, Previous: {self.previous_level}, Next: {self.next_level}")

            # Place orders for the current and next levels
            entry_order = self._place_entry_order()
            exit_order = self._place_exit_order()

            logging.info(f"Both orders sent for level {self.current_level_index}: Entry={entry_order}, Exit={exit_order}")

            # Wait for confirmation of the orders
            self.wait_for_order_confirmation(entry_order, exit_order)

        except ValueError as ve:
            print(f"Configuration error: {ve}")
        except OrderPlacementError as ope:
            print(f"Order placement failed for level {self.current_level_index}: {ope}")
        except Exception as e:
            print(f"Unexpected error processing level {self.current_level_index}: {e}")

    # Helper methods
    def _place_entry_order(self):
        """Places the entry (buy) order for the next level."""
        try:
            print("Placing entry order...")
            return self.place_order(
                order_type="LMT",
                side="buy",
                order_role="entry",
                level=self.next_level
            )
        except Exception as e:
            raise OrderPlacementError(f"Failed to place entry order for next level: {e}")

    def _place_exit_order(self):
        """Places the exit (sell) order for the current level."""
        try:
            print("Placing exit order...")
            return self.place_order(
                order_type="LMT",
                side="sell",
                order_role="exit",
                level=self.current_level
            )
        except Exception as e:
            raise OrderPlacementError(f"Failed to place exit order for current level: {e}")

    def wait_for_order_confirmation(self, entry_order, exit_order):

        """Waits until the status of all orders is confirmed."""
        self.ws_client.subscribe()

        while not self.stop_event.is_set():
            try:
                # Attempt to retrieve a message non-blocking
                message = self._get_message_from_queue()
                time.sleep(1)
                if message:
                    # Process entry order updates
                    if entry_order in message:
                        message_data = json.loads(message)
                        status = message_data['args'][0]['status']
                        if status == "Filled":
                            self.ws_client.unsubscribe()
                            self._handle_entry_order(message, entry_order, exit_order, status)

                    # Process exit order updates
                    elif exit_order in message:
                        message_data = json.loads(message)
                        status = message_data['args'][0]['status']
                        if status == "Filled":
                            self.ws_client.unsubscribe()
                            self._handle_exit_order(message, entry_order, exit_order, status)

            except queue.Empty:
                print("Queue timeout while waiting for message.")
            except Orders.DoesNotExist:
                print(f"No matching order found for exit_order_id: {exit_order}")
            except json.JSONDecodeError as e:
                print(f"Error decoding JSON message: {e}")
            except Exception as e:
                print(f"Unexpected error: {e}")
            finally:
                # Prevent high CPU usage
                time.sleep(0.1)

    def _get_message_from_queue(self):
        """Helper function to retrieve a message from the WebSocket queue."""
        with self.lock:
            if not self.ws_client.message_queue.empty():
                return self.ws_client.message_queue.get(timeout=1)
        return None

    def _handle_entry_order(self, message, entry_order, exit_order, status):
        """Handles entry order-specific logic."""
        logging.info(f'Inside entry order placed {message}')
        try:
            with self.lock:
                order = Orders.objects.filter(entry_order_id=entry_order).first()
                logging.debug(f'Entry order received for next level {order}')
                if not order:
                    logging.error(f"Order not found for Entry order:{entry_order} Level {self.current_level}")
                    raise Orders.DoesNotExist

                # Update order details
                order.entry_order_status = get_order_status_value(status)
                order.is_entry = True
                order.save()
                logging.info(f"Order Updated successfully: Entry Order:{entry_order} Level {self.current_level}")
            self.cancel_an_order(exit_order)
            self.current_level_index += 1
            logging.info(f'Processing next level... {self.current_level_index}')
            self.process_next_level()
        except:
            pass

    def _handle_exit_order(self, message, entry_order, exit_order, status):
        """Handles exit order-specific logic."""
        print('Inside exit order placed', type(message))
        try:

            self.ws_client.unsubscribe()
            with self.lock:
                order = Orders.objects.filter(level=self.current_level, exit_order_id=exit_order).first()
                if not order:
                    raise Orders.DoesNotExist

                logging.info(f"Updating Exit order: Order Level: {exit_order}, Level: {self.current_level_index}")
                # Update order details
                order.exit_order_status = get_order_status_value(status)
                order.is_completed = True
                order.save()
                logging.info(f"Exit Order updated successfully: {exit_order}")

            # Strategy logic
            if self.current_level_index == 0:
                logging.info('Exit strategy logic triggered')
                self._execute_exit_strategy()
            else:
                self.current_level_index -= 1
                self.cancel_an_order(entry_order)
                logging.info('Processing next level...')
                self.process_next_level()

        except Orders.DoesNotExist:
            logging.error(f"No matching order found for exit_order_id: {exit_order}")
        except Exception as e:
            logging.error(f"Error while handling exit order: {e}")

    def _execute_exit_strategy(self):
        """Executes the strategy exit logic and resets for a new instrument."""
        self.close_all_open_orders()
        instrument_symbol, instrument_price = get_instrument(
            self.index, self.expiry, self.strike_distance, self.strike_direction
        )
        create_table(instrument_price, self.main_target, self.strategy, self.hedging_limit_price)
        self.instrument = instrument_symbol
        self.run_strategy()

    def place_initial_market_order(self, level):
        """Places a market order for the first level."""
        logging.info(f"Placing initial market order...{level}")

        try:
            order_id = self.place_order(
                order_type="market",
                side="buy",
                order_role="entry",
                level=level
            )
            if order_id:
                max_attempts = 20
                attempt_interval = 1  # in seconds

                for attempt in range(max_attempts):
                    status = self.get_order_status(order_id)
                    logging.info(f'Order ID {order_id}: Checking status (Attempt {attempt + 1}/{max_attempts}) - Status: {status}')

                    if status == 'Filled':
                        order = Orders.objects.get(entry_order_id=order_id, level=self.current_level)
                        order.entry_order_status = get_order_status_value(status)
                        order.is_entry = True
                        order.save()
                        break
                    elif attempt < max_attempts - 1:
                        time.sleep(attempt_interval)
                else:
                    logging.debug(f'Order ID {order_id}: Status check failed after {max_attempts} attempts')
        except Exception as e:
            logging.error(f"Error placing initial market order: {e}")

    def stop_strategy(self):
        """Stops the strategy."""
        logging.info("Stopping strategy")
        self.stop_event.set()

    def place_order(self, order_type, side, order_role, level):
        """Places an order and handles errors."""
        try:
            # Validate input arguments
            if not level:
                raise ValueError("Level information is required to place an order.")

            # Prepare order data
            price, quantity = self._calculate_order_price_and_quantity(side, level)
            order_data = self._prepare_order_data(order_type, side, quantity, price, level)

            # Send order request
            place_order_url = f"{baseUrl}/iserver/account/{account_id}/orders"
            logging.debug(f"Placing {order_role} order: {order_data}")
            response = requests.post(url=place_order_url, json=order_data, verify=False)
            print('response', response.json())
            # Handle response
            self._handle_order_response(response, order_role, level, price, quantity)

            # Parse and return order ID
            response_data = response.json()[0]
            logging.info('outside order resposne', response_data)
            order_id = response_data.get("order_id")
            logging.debug(f"Order placed successfully: {order_id}")
            return order_id

        except requests.RequestException as re:
            raise OrderPlacementError(
                message="Failed to connect to the order placement API.",
                order_details={"side": side, "price": price, "quantity": quantity}
            ) from re
        except ValueError as ve:
            raise OrderPlacementError(
                message=f"Validation error: {ve}",
                order_details={"side": side, "level": level}
            ) from ve
        except Exception as e:
            raise OrderPlacementError(
                message=f"Unexpected error during order placement: {e}",
                order_details={"side": side, "level": level}
            ) from e

    # Helper Methods
    def _calculate_order_price_and_quantity(self, side, level):
        """Calculates the order price and quantity based on the side and level."""
        price = level.main_percentage if side == "buy" else level.main_target
        quantity = level.main_quantity
        price = round_to_tick_size(price, tick_size=0.05)
        logging.debug(f"Order Price: {price}, Quantity: {quantity}")
        return price, quantity

    def _prepare_order_data(self, order_type, side, quantity, price):
        """Prepares the order data payload for the API request."""
        return {
            "orders": [
                {
                    'conid': symbol_for_Placing_order,
                    'orderType': order_type,
                    'side': side.upper(),
                    'tif': 'DAY',
                    'quantity': quantity,
                    'price': price
                }
            ]
        }

    def _handle_order_response(self, response, order_role, level, price, quantity):
        """Processes the API response and updates the database."""
        if response.status_code != 200:
            raise OrderPlacementError(
                message=f"Order placement failed with status code {response.status_code}.",
                order_details=response.json()
            )
        response_data = response.json()[0]
        order_id = response_data.get("order_id")
        order_status = get_order_status_value(response_data.get("order_status"))

        with self.lock:
            if order_role == "entry":
                # Create entry order record
                Orders.objects.create(
                    level=level,
                    entry_price=price,
                    order_quantity=quantity,
                    entry_order_id=order_id,
                    entry_order_status=order_status,
                    is_entry=True if order_status == 1 else False
                )
                logging.debug("Entry order object created:.....")
            else:
                # Update existing order record for exit
                order = Orders.objects.filter(level=self.current_level, is_entry=True).first()
                if not order:
                    raise OrderPlacementError(
                        message="No matching entry order found for the current level.",
                        order_details={"level": self.current_level, "order_role": order_role}
                    )
                order.exit_order_status = order_status
                order.exit_order_id = order_id
                order.is_completed = True if order_status == 1 else False
                order.save()
                logging.debug("Exit order object created:.....")

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
                self.next_level = next((level for level in levels if level.level_number == self.current_level_index + 1), None)
            else:
                self.next_level = None  # No next level exists
            logging.info(f'New Levels, Current: {self.current_level}, Next: {self.next_level}, Previous: {self.previous_level}', )

    def get_conid_instrument(self, instrument):
        print('instrument inside conid')
        request_url = f"{baseUrl}/iserver/secdef/search?symbol=NIFTY50"
        resp = requests.get(url=request_url, verify=False)
        print("response", resp.json())
        expiry_month = None
        for _ in resp.json()[0].get("sections"):
            if _['secType'].lower() == "opt":
                expiry_month = _['months']
        return resp.json()[0]['conid'], expiry_month

    def get_conid(self, instrument):
        conid, expiry_month = self.get_conid_instrument(instrument)
        strike_price, option_type = self.extract_option_details(instrument)
        right = "C" if option_type == "CE" else "P"
        request_url = f"{baseUrl}/iserver/secdef/info?conid={conid}&secType=OPT&month={expiry_month}&strike=24150&right={right}&exchange=NSE"
        resp = requests.get(url=request_url, verify=False)
        print(' get conid', resp.json())
        return resp.json()['conid']

    def extract_option_details(self, instrument):
        pattern = r"CE|PE"
        ce_pe = re.search(pattern, instrument).group()

        strike_price_pattern = r"\d+(?=CE|PE)"
        strike_price = re.search(strike_price_pattern, instrument).group()
        print('strike price', strike_price, ce_pe)
        return ce_pe, strike_price

    def get_all_orders(self, order_id):
        request_url = f'{baseUrl}/iserver/accounts'
        response = requests.get(url=request_url, verify=False)
        for _ in response.json():
            print("checking status", _)
        print('response', response, response.text)
        return response.json()

    def cancel_an_order(self, order_id, fyers=None):
        # Cancel an order
        request_url = f'{baseUrl}/iserver/account/{account_id}/order/{order_id}'
        response = requests.delete(url=request_url, verify=False)
        logging.info(f'Order cancel accepted {response.text}')

        if fyers:
            data = {"id": order_id}
            response = fyers.cancel_order(data=data)
            print(response)

        return response

    def get_all_orders_and_cancel(self):
        request_url = f'{baseUrl}/iserver/account/orders'
        response = requests.get(url=request_url, verify=False)
        for _ in response.json()['orders']:
            request_url = f"{baseUrl}/iserver/account/DUA498440/order/{_['orderId']}"
            response = requests.delete(url=request_url, verify=False)
            print(response.text)

    def get_order_status(self, order_id):
        request_url = f"{baseUrl}/iserver/account/order/status/{order_id}"
        response = requests.get(url=request_url, verify=False)

        return response.json().get('order_status')

    def close_all_open_orders(self):
        data = {}
        response = self.fyers.exit_positions(data=data)

        return response


class OrderPlacementError(Exception):
    """Custom exception for errors during order placement."""

    def __init__(self, message=None, order_details=None):
        super().__init__(message)
        self.order_details = order_details

    def __str__(self):
        base_message = super().__str__()
        if self.order_details:
            return f"{base_message} | Order Details: {self.order_details}"
        return base_message
