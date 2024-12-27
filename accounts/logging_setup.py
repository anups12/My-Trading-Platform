import logging
import os
from logging.handlers import RotatingFileHandler

from tabulate import tabulate

class TabularLogFormatter(logging.Formatter):
    def format(self, record):
        # Check if the original message is a dict or a list of dicts
        if isinstance(record.msg, list) and all(isinstance(row, dict) for row in record.msg):
            # Use the first dictionary's keys as the table headers
            headers = record.msg[0].keys()
            rows = [row.values() for row in record.msg]
            table = tabulate(rows, headers=headers, tablefmt="grid")
            return f"{self.formatTime(record)} [{record.levelname}] {table}"
        elif isinstance(record.msg, dict):
            # Single dictionary message (existing functionality)
            table = tabulate([record.msg.values()], headers=record.msg.keys(), tablefmt="grid")
            return f"{self.formatTime(record)} [{record.levelname}] {table}"
        else:
            # Fallback for unstructured messages
            return super().format(record)

def get_strategy_logger(strategy_name, console_handler=False):
    log_dir = os.path.join('logs', 'strategies')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{strategy_name}.log")

    logger = logging.getLogger(strategy_name)

    # Prevent duplicate file handlers
    if any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        return logger

    logger.setLevel(logging.DEBUG)

    # Create a file handler
    handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3)
    formatter = TabularLogFormatter('%(asctime)s [%(levelname)s] %(message)s')
    handler.setFormatter(formatter)

    logger.addHandler(handler)

    # Add console handler if requested
    if console_handler:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        logger.addHandler(console)

    logger.propagate = False
    return logger
