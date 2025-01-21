import json
import time
from datetime import datetime
from functools import wraps

from django.db import transaction
from fyers_apiv3 import fyersModel

from .constants import OPTION_MAPPING, RETRY_ATTEMPTS
from .models import Customer, OrderLevel, AccessToken
from django.conf import settings

redirect_uri = "http://127.0.0.1:8000/fyers_login"


def get_access_token():
    today_date = datetime.now()
    access_tokens = AccessToken.objects.filter(timestamp_created__date=today_date, is_active=True)
    AccessToken.objects.filter(timestamp_created__date__lt=today_date).delete()
    if access_tokens.exists():
        return access_tokens.first().access_token
    else:
        return None


access_token = get_access_token()


def get_customer(request):
    # Retrieve customer information to pass to the template
    customer_id = request.session.get('customer_id')
    customer = None
    if customer_id:
        try:
            customer = Customer.objects.get(id=customer_id)
        except Customer.DoesNotExist:
            customer = None
    return customer


def get_balance(request):
    fyers = fyersModel.FyersModel(client_id=settings.CLIENT_ID, token=access_token, is_async=False, log_path="")
    total_balance, utilised_balance, realised_profit_loss, limit_at_start_of_day, available_balance = 0, 0, 0, 0, 0
    if "fund_limit" in fyers.funds():
        funds = fyers.funds()['fund_limit']
        total_balance = funds[0]['equityAmount']
        utilised_balance = funds[1]['equityAmount']
        realised_profit_loss = funds[3]['equityAmount']
        available_balance = funds[9]['equityAmount']

    return total_balance, utilised_balance, realised_profit_loss, limit_at_start_of_day, available_balance


def process_option_data(data):
    data = data[1:]
    try:
        # Separate calls and puts
        calls, puts = [], []
        for item in data:
            option_type = item.get('option_type')
            if option_type == 'CE':
                calls.append(item)
            elif option_type == 'PE':
                puts.append(item)
            else:
                raise ValueError(f"Invalid option type: {option_type}")

        if len(calls) != len(puts):
            raise ValueError("Mismatched call/put data count.")

        # Determine middle index
        middle_index = len(calls) // 2

        call_dict = {}
        put_dict = {}

        # Process both calls and puts
        for i in range(len(calls)):
            put_index = i - middle_index  # middle = 0, above = positive, below = negative
            call_index = middle_index - i  # middle = 0, above = negative, below = positive

            # Assign index in dictionaries
            call_dict[str(call_index)] = calls[i]
            put_dict[str(put_index)] = puts[i]

        return call_dict, put_dict

    except ValueError as e:
        print(f"Error: {e}")
        return {}, {}


def get_instrument(index, expiry, strike_distance, strike_direction):
    """
    Fetches the instrument and its price based on the index, expiry, strike distance, and strike direction.

    Args:
        index (str): The index symbol.
        expiry (str): The expiry date.
        strike_distance (int): The strike distance from the underlying price.
        strike_direction (str): 'CALL' or 'PUT'.

    Returns:
        tuple: Instrument symbol and its price.

    Raises:
        InvalidStrikeDirectionError: If the strike direction is invalid.
        ExpiryNotFoundError: If the specified expiry is not found.
        OptionChainDataError: If the options chain data is missing or invalid.
        Exception: For other unexpected issues.
    """

    try:
        # Validate strike direction
        strike_direction = OPTION_MAPPING.get(strike_direction.upper())
        if not strike_direction:
            raise InvalidStrikeDirectionError("Invalid strike direction. Must be 'CALL' or 'PUT'.")

        # Initialize Fyers client
        fyers = fyersModel.FyersModel(
            client_id=settings.client_id,
            token=access_token,
            is_async=False,
            log_path=""
        )

        # Prepare request data
        data = {
            "symbol": index,
            "strikecount": abs(strike_distance) + 1,
            "timestamp": ""
        }

        # Fetch initial option chain data
        initial_response = fyers.optionchain(data=data)
        if not (initial_response.get('data') and initial_response['data'].get('expiryData')):
            raise OptionChainDataError("Invalid response or missing expiry data. Regenerate access token.")

        response_expiry = initial_response['data']['expiryData']

        # Handle expiry-specific data
        if expiry:
            if expiry not in response_expiry:
                raise ExpiryNotFoundError(f"Specified expiry '{expiry}' not found.")
            data['timestamp'] = response_expiry[expiry]
            response = fyers.optionchain(data=data)
        else:
            response = initial_response

        # Validate options chain data
        if not (response.get('data') and response['data'].get('optionsChain')):
            raise OptionChainDataError("Invalid response or missing options chain data.")

        # Process options chain data
        option_chain_data = response['data']['optionsChain']
        call_options, put_options = process_option_data(option_chain_data)

        # Retrieve the relevant option
        option = call_options.get(str(strike_distance)) if strike_direction == "CE" else put_options.get(str(strike_distance))
        if not option:
            raise ValueError("Specified strike distance not found in the options chain.")

        instrument = option['symbol']
        price = option['ltp']
        return instrument, price

    except (InvalidStrikeDirectionError, ExpiryNotFoundError, OptionChainDataError, ValueError) as known_error:
        raise
    except Exception as e:
        raise


def get_lot_size(symbol):
    """Return the lot of size based on the instrument name."""
    if 'BANKNIFTY' in symbol:
        return 15  # Lot size for Bank Nifty
    elif 'NIFTY' in symbol:
        return 75  # Lot size for Nifty
    elif 'FINNIFTY' in symbol:
        return 25  # Lot size for Fin Nifty
    elif 'MIDCAP' in symbol:
        return 50  # Lot size for Midcap
    else:
        return 1  # Default lot size for other instruments


def round_to_tick_size(price, tick_size):
    return round(float(price) / tick_size) * tick_size


def get_order_status_value(order_status):
    if order_status == "PreSubmitted":
        order_status = 2
    elif order_status == "Submitted":
        order_status = 2
    elif order_status == "PendingSubmit":
        order_status = 2
    elif order_status == 'Filled':
        order_status = 1
    return order_status


def create_table(main_price, target, strategy, hedging_limit_price, quantity=None, table=None, hedging_quantity=None, hedging_limit_quantity=None):
    try:
        # Parse the JSON data safely
        parsed_data = json.loads(table.price_quantity_data)

        # Fetch existing order levels
        existing_levels = OrderLevel.objects.filter(strategy=strategy).order_by("level_number")

        if existing_levels.exists():
            # Update existing levels
            with transaction.atomic():
                for level in existing_levels:
                    if level.level_number == 0:
                        # Update the first order (base level)
                        level.main_percentage = main_price
                        level.main_target = (1 + float(target) / 100) * main_price
                        if hedging_limit_price:
                            level.hedging_limit_price = (1 - float(hedging_limit_price) / 100) * main_price
                    else:
                        # Update other levels based on table data
                        key = str(level.level_number)
                        if key in parsed_data:
                            data = parsed_data[key]
                            level.main_percentage = (1 - float(data.get('main_percentage')) / 100) * main_price
                            level.main_target = (1 - float(data.get('main_percentage')) / 100) * (1 + float(data.get('main_target')) / 100) * main_price
                            if 'hedge_percentage' in data:
                                level.hedging_limit_price = (1 - float(data['hedge_percentage']) / 100) * main_price
                    # Save updated level
                    level.save()
            return  # Exit early after updating existing levels

        # Prepare a list for bulk_create if no existing levels
        order_levels = [OrderLevel(
            strategy=strategy,
            main_percentage=main_price,
            main_quantity=quantity,
            main_target=(1 + float(target) / 100) * main_price,
            hedging_quantity=hedging_quantity if hedging_quantity else None,
            hedging_limit_price=(1 - float(hedging_limit_price) / 100) * main_price if hedging_limit_price else None,
            hedging_limit_quantity=hedging_limit_quantity if hedging_limit_quantity else None,
            level_number=0,  # Base level
        )]

        # Add levels from table data
        for key, data in parsed_data.items():
            order_levels.append(OrderLevel(
                strategy=strategy,
                main_percentage=(1 - float(data.get('main_percentage')) / 100) * main_price,
                main_quantity=float(data.get('main_quantity')),
                main_target=(1 - float(data.get('main_percentage')) / 100) * (1 + float(data.get('main_target')) / 100) * main_price,
                hedging_quantity=float(data.get('hedge_market_quantity')),
                hedging_limit_price=float(data.get('hedge_percentage')),
                hedging_limit_quantity=float(data.get('hedge_limit_quantity')),
                level_number=int(key),
            ))

        # Bulk create the new order levels
        if order_levels:
            with transaction.atomic():
                OrderLevel.objects.bulk_create(order_levels)

    except json.JSONDecodeError:
        print("Error decoding JSON data.")
    except Exception as e:
        print(f"An error occurred: {e}")


def retry_on_exception(max_retries=RETRY_ATTEMPTS, delay=2, exceptions=(Exception,)):
    """Decorator for retrying a function if specified exceptions occur."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    retries += 1
                    if retries >= max_retries:
                        raise
                    time.sleep(delay)

        return wrapper

    return decorator


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


class InvalidStrikeDirectionError(Exception):
    """Raised when the strike direction is invalid."""
    pass


class ExpiryNotFoundError(Exception):
    """Raised when the specified expiry is not found."""
    pass


class OptionChainDataError(Exception):
    """Raised when there is an issue with the options chain data."""
    pass
