import logging
from logging.handlers import RotatingFileHandler
import os

def get_strategy_logger(strategy_name):
    """
    Creates and returns a logger for a specific strategy.
    Ensures logs are written to a file only.
    """
    log_dir = os.path.join('logs', 'strategies')
    os.makedirs(log_dir, exist_ok=True)  # Ensure the log directory exists
    log_file = os.path.join(log_dir, f"{strategy_name}.log")

    # Create a custom logger
    logger = logging.getLogger(strategy_name)

    # Avoid duplicate handlers
    if not logger.hasHandlers():
        logger.setLevel(logging.DEBUG)

        # Create a file handler
        handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3)
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        handler.setFormatter(formatter)

        # Add the file handler to the logger
        logger.addHandler(handler)

        # Disable propagation to prevent logs from appearing in the console
        logger.propagate = False

    return logger
