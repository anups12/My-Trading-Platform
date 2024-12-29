import logging
import os
import threading
from logging.handlers import RotatingFileHandler

from tabulate import tabulate


class TabularLogFormatter(logging.Formatter):
    def format(self, record):
        if isinstance(record.msg, list) and all(isinstance(row, dict) for row in record.msg):
            headers = record.msg[0].keys()
            rows = [row.values() for row in record.msg]
            table = tabulate(rows, headers=headers, tablefmt="grid")
            return f"{self.formatTime(record)} [{record.levelname}] {table}"
        elif isinstance(record.msg, dict):
            table = tabulate([record.msg.values()], headers=record.msg.keys(), tablefmt="grid")
            return f"{self.formatTime(record)} [{record.levelname}] {table}"
        else:
            return super().format(record)


def get_strategy_logger(strategy_name):
    """
    Get a logger for a specific strategy, isolated for each thread.
    """
    log_dir = os.path.join('logs', 'strategies')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{strategy_name}.log")

    # Use a thread-local storage to avoid logging clashes between threads
    thread_id = threading.get_ident()
    logger_name = f"{strategy_name}_thread_{thread_id}"
    logger = logging.getLogger(logger_name)

    # Prevent adding duplicate handlers
    if any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        return logger

    logger.setLevel(logging.DEBUG)
    handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3)
    formatter = TabularLogFormatter('%(asctime)s [%(levelname)s] %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    return logger
