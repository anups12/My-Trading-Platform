from enum import Enum

# Define constants for the option types
OPTION_CALL = "CALL"
OPTION_PUT = "PUT"
CE = "CE"  # Call Option
PE = "PE"  # Put Option

# Mapping between option type and its value
OPTION_MAPPING = {
    OPTION_CALL: CE,
    OPTION_PUT: PE
}
hedging_strike_level_mapping = {
    'ATM': 0,
    'ITM': 1,
    'OTM': 2
}

hedging_strike_direction_mapping = {
    'CALL': 0,
    'PUT': 1,
}

RETRY_ATTEMPTS = 10


class OrderTypeEnum(Enum):
    MARKET_ORDER = 2
    LIMIT_ORDER = 1

class TransactionTypeEnum(Enum):
    BUY = 1
    SELL = -1

class OrderRoleEnum(Enum):
    ENTRY = 'entry'
    EXIT = 'exit'