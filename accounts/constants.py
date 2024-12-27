
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
