import json

from django.contrib.auth.password_validation import validate_password
from django.core.validators import validate_email
from rest_framework import serializers
from .models import Customer, PriceQuantityTable
from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import serializers
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError

from rest_framework import serializers
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError

from rest_framework.exceptions import ValidationError


class CustomerRegistrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ['phone_number', 'email', 'name', 'password']

    def validate_phone_number(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("Phone number must contain only digits.")
        if len(value) != 10:  # Assuming a standard 10-digit phone number.
            raise serializers.ValidationError("Phone number must be 10 digits long.")
        return value

    def validate_email(self, value):
        try:
            validate_email(value)
        except DjangoValidationError:
            raise serializers.ValidationError("Enter a valid email address.")
        return value

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)
        return value

    def validate(self, attrs):
        # You can customize the order of validation
        if Customer.objects.filter(phone_number=attrs['phone_number']).exists():
            raise serializers.ValidationError({"phone_number": "A customer with this phone number already exists."})

        if Customer.objects.filter(email=attrs['email']).exists():
            raise serializers.ValidationError({"email": "A customer with this email already exists."})

        return attrs

    def create(self, validated_data):
        customer = Customer(
            phone_number=validated_data.get('phone_number'),
            email=validated_data.get('email'),
            name=validated_data.get('name')
        )
        customer.set_password(validated_data.get('password'))
        customer.save()
        return customer


class CustomerLoginSerializer(serializers.Serializer):
    email_or_phone = serializers.CharField()
    password = serializers.CharField()

    def validate(self, data):
        email_or_phone = data.get('email_or_phone')
        password = data.get('password')

        # Check if user provided email or phone
        if '@' in email_or_phone:
            customer = Customer.objects.filter(email=email_or_phone).first()
        else:
            customer = Customer.objects.filter(phone_number=email_or_phone).first()

        # Validate credentials
        if customer and customer.check_password(password):
            return customer
        raise serializers.ValidationError("Invalid email/phone number or password.")


class PriceQuantitySerializer(serializers.ModelSerializer):
    price_quantity_data = serializers.JSONField()

    class Meta:
        model = PriceQuantityTable
        fields = ['name', 'price_quantity_data']

    def create(self, validated_data):
        print('validated data', validated_data)
        # Save the dictionary as a JSON string in the model
        validated_data['price_quantity_data'] = json.dumps(validated_data['price_quantity_data'])
        return super().create(validated_data)


import queue
import threading
import time

import requests
from fyers_apiv3 import fyersModel

from accounts.logging_setup import get_strategy_logger
from accounts.models import Orders, OrderLevel
from accounts.utils import client_id, get_instrument, create_table, access_token, OrderPlacementError, retry_on_exception
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

        self.logger.info(f"Initialized TradingStrategy1 with ID: {self.strategy.id}")

        # Strategy configurations
        self.stop_event = threading.Event()
        self.current_level_index = 0  # Start at the first level
        self.ws_client = None
        self.current_level = None
        self.previous_level = None
        self.next_level = None
        self.levels_length = None
        self.fyers = fyersModel.FyersModel(client_id=client_id, token=self.access_token, is_async=False, log_path="")
        self.is_active = self.strategy.is_active

    def run_strategy(self):
        """Starts the strategy."""
        try:
            while self.is_active and not self.stop_event.is_set():
                self.logger.info(f"Strategy started for strategy id: {self.strategy.id}")

                # Create and start the shared WebSocket client
                self.ws_client = FyersWebSocketManager(access_token)
                try:
                    self.ws_client.start()
                    self.logger.info('websocket started')
                except Exception as e:
                    self.logger.error("Websocket connection failed...")
                    self.stop_strategy()
                    return

                self.fetch_levels()

                try:
                    # Place the initial market order
                    self.place_initial_market_order(self.current_level)
                except RuntimeError:
                    self.logger.error("Initial market order failed. Stopping strategy.")
                    self.stop_strategy()
                    return

                self.logger.info(f"Processing next Level Index: {self.current_level_index}")

                # Begin processing from the next level
                self.process_next_level()

        except Exception as e:
            self.logger.error(f"Error in strategy: {e}")

    def process_next_level(self):
        """Processes the next level in the strategy."""
        self.logger.info('reached here second time')
        try:
            if self.current_level_index >= self.levels_length:
                print('strategy is stopped here', self.current_level_index, self.levels_length)
                self.stop_strategy()
                return

            # Fetch levels for the current index
            self.fetch_levels(self.current_level_index)
            self.logger.debug(f"Processing Level: {self.current_level_index}, "
                              f"Current: {self.current_level}, Previous: {self.previous_level}, Next: {self.next_level}")

            # Place orders for the current and next levels
            entry_order = self._place_entry_order()
            exit_order = self._place_exit_order()

            self.logger.info(f"Both orders sent for level {self.current_level_index}: Entry={entry_order}, Exit={exit_order}")

            # Wait for confirmation of the orders
            self.wait_for_order_confirmation(entry_order, exit_order)

        except ValueError as ve:
            print(f"Configuration error: {ve}")
        except OrderPlacementError as ope:
            print(f"Order placement failed for level {self.current_level_index}: {ope}")
        except Exception as e:
            print(f"Unexpected error processing level {self.current_level_index}: {e}")

    def wait_for_order_confirmation(self, entry_order, exit_order):
        """Wait until the status of the specified orders is confirmed."""
        with self.ws_client.q.mutex:
            self.ws_client.q.queue.clear()

        self.ws_client.subscribe()

        while not self.stop_event.is_set():
            try:
                # Attempt to retrieve a message from the queue
                message = self._get_message_from_queue()
                if message:
                    order_id = message.get('orders', {}).get('id')
                    status = message.get('s')  # Use get() to avoid KeyError

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
            self.ws_client.unsubscribe()
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
        self.logger.info(f'Inside handle entry order: Order placed from websocket {message}')
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
                    self.logger.debug('Placing Hedging Order')

            self.cancel_orders(exit_order)
            self.current_level_index += 1
            self.logger.info(f'Processing next level... {self.current_level_index}')
            self.process_next_level()
        except Exception as ex:
            self.logger.debug(f'Exception happened inside handle_entry_order: {ex}')

    def _handle_exit_order(self, message, entry_order, exit_order, status):
        """Handles exit order-specific logic."""
        self.logger.info(f'Inside handle entry order: Order placed from websocket {message}')
        try:

            self.ws_client.unsubscribe()
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

                # TODO: implement this later
                if self.strategy.is_hedging:
                    self.logger.debug('Place exit order for hedging')

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
        self.close_all_open_orders()
        self.cancel_orders()
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
        """Places a market order for the first level."""
        self.logger.info(f"Initial Order placing for level: {level}")

        try:
            response_data = self.place_order(
                order_type=2,
                side=1,
                order_role="entry",
                level=level
            )

            order_id = self._handle_order_response(response, order_role, level, price, quantity)


        except Exception as e:
            self.logger.critical(f"Error placing initial market order: {e}")

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

            for _ in levels_queryset:
                print('Logging levels', _.strategy.id, self.strategy.id)
                print('instruments', _.strategy.main_instrument, self.instrument)

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

    def _place_entry_order(self):
        """Places the entry (buy) order for the next level."""
        try:
            print("Placing entry order...")
            return self.place_order(
                order_type=1,
                side=1,
                order_role="entry",
                level=self.next_level
            )
        except Exception as e:
            raise OrderPlacementError(f"Failed to place entry order for next level: {e}")

    def _place_exit_order(self):
        """Places the exit (sell) order for the current level."""
        try:
            self.logger.debug(f"Placing exit order... {self.current_level}")
            return self.place_order(
                order_type=1,
                side=-1,
                order_role="exit",
                level=self.current_level
            )
        except Exception as e:
            raise OrderPlacementError(f"Failed to place exit order for current level: {e}")

    def cleanup(self):
        self.logger.info("Cleaning up resources...")
        if self.ws_client:
            self.ws_client.unsubscribe()
        self.close_all_open_orders()
        self.cancel_orders()
        self.logger.info("Cleanup complete.")

    def place_order(self, order_type, side, order_role, level):
        """Places an order and handles errors."""
        try:
            if not level:
                self.logger.error("Level information is missing.")
                return self._create_response(success=False, error="Level information is required.")

            price, quantity = self._calculate_order_price_and_quantity(side, level)
            self.logger.debug(f"Prepared order data: Price={price}, Quantity={quantity}")

            order_data = self._prepare_order_data(order_type, side, quantity, price)
            self.logger.info(f"Placing order: {order_data}")

            response = self._send_order_request(order_data)

            self.logger.info(f'Order placed successfully {response}')

            order_id = self._handle_order_response(response, order_role, level, price, quantity)
            return response
        except OrderPlacementError as ope:
            self.logger.error(f"Order placement error: {ope}", exc_info=True)
            return self._create_response(success=False, error=ope, details=ope.order_details)
        except Exception as e:
            self.logger.error(f"Unexpected error during order placement: {str(e)}", exc_info=True)
            return self._create_response(success=False, error="Unexpected error occurred.")

    @retry_on_exception(exceptions=(requests.RequestException,))
    def _send_order_request(self, order_data):
        """Sends the order request to the API with retry logic."""
        return self.fyers.place_order(order_data)

    def _calculate_order_price_and_quantity(self, side, level):
        """Calculates the order price and quantity based on the side and level."""
        try:
            price = level.main_percentage if side == 1 else level.main_target
            quantity = level.main_quantity
            price = self._round_to_tick_size(price, tick_size=0.05)
            self.logger.debug(f"Calculated order price: {price}, quantity: {quantity}")
            return price, quantity
        except AttributeError as e:
            self.logger.error("Invalid level data structure.", exc_info=True)
            raise ValueError("Invalid level data structure.") from e

    def _prepare_order_data(self, order_type, side, quantity, price):
        """Prepares the order data payload for the API request."""
        return {
            "symbol": self.instrument,
            "qty": quantity,
            "type": order_type,  # Market or Limit
            "side": side,  # Buy or Sell
            "productType": "INTRADAY",
            "limitPrice": price if order_type == 1 else None,
            "validity": "DAY",
        }

    def _handle_order_response(self, response, order_role, level, price, quantity):
        """Processes the API response and updates the database."""
        if response.get('s') != 'ok':
            self.logger.error(f"Order placement failed. Response: {response}")
            return None

        order_id = response.get("id")
        with self.lock:
            if order_role == "entry":
                Orders.objects.create(
                    level=level,
                    entry_price=price,
                    order_quantity=quantity,
                    entry_order_id=order_id,
                    entry_order_status=1,
                    is_entry=True
                )
                self.logger.debug("Entry order record created.")
            else:
                order = Orders.objects.filter(level=self.current_level, is_entry=True).first()
                if not order:
                    raise OrderPlacementError(f"No entry order found for level: {'level': self.current_level, 'order_role': order_role}")
                order.exit_order_status = 1
                order.exit_order_id = order_id
                order.is_completed = True
                order.save()
                self.logger.debug("Exit order record updated.")
        return order_id

    @staticmethod
    def _round_to_tick_size(price, tick_size):
        """Rounds a price to the nearest tick size."""
        return round(float(price) / tick_size) * tick_size

    @staticmethod
    def _create_response(success, error=None, order_id=None, details=None):
        """Creates a structured response."""
        return {
            "success": success,
            "error": error,
            "order_id": order_id,
            "details": details
        }
