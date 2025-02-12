import queue
import threading
import time

from django.conf import settings
from fyers_apiv3.FyersWebsocket import order_ws


class FyersWebSocketManager:
    def __init__(self, access_token, logger, max_retries=5, reconnect_delay=5):
        self.access_token = access_token
        self.logger = logger
        self.q = queue.Queue()
        self.thread = None
        self.running = False
        self.reconnect_attempts = 0
        self.max_retries = max_retries
        self.reconnect_delay = reconnect_delay
        self.fyers = None

    def onOrder(self, message):
        """Handles incoming WebSocket messages."""
        self.q.put(message)

    def onError(self, message):
        """Handles WebSocket errors."""
        self.logger.error(f"WebSocket Error: {message}")
        self._handle_disconnection()

    def onClose(self, message):
        """Handles WebSocket closure and attempts reconnection."""
        self.logger.warning(f"WebSocket Closed: {message}")
        self._handle_disconnection()

    def onOpen(self):
        """Handles WebSocket connection and subscription."""
        self.logger.info("WebSocket Connected")
        self.reconnect_attempts = 0  # Reset retry counter on successful connection
        try:
            data_type = "OnOrders"  # Adjust this based on your subscription needs
            self.fyers.subscribe(data_type=data_type)
            self.fyers.keep_running()
        except Exception as e:
            self.logger.error(f"Error during subscription: {e}")
            self._handle_disconnection()

    def start(self):
        """Starts the WebSocket in a separate thread."""
        if self.running:
            self.logger.warning("WebSocket is already running.")
            return

        self.logger.info("Starting WebSocket...")
        self.running = True
        self.thread = threading.Thread(target=self._connect, daemon=True)
        self.thread.start()

    def _connect(self):
        """Connects to the WebSocket and handles reconnections."""
        while self.running:
            try:
                self.fyers = order_ws.FyersOrderSocket(
                    access_token=f"{settings.FYERS_CLIENT_ID}:{self.access_token}",
                    write_to_file=False,
                    log_path="",
                    on_connect=self.onOpen,
                    on_close=self.onClose,
                    on_error=self.onError,
                    on_orders=self.onOrder,
                )
                self.fyers.connect()
                break  # Connection successful, exit loop

            except Exception as e:
                self.logger.error(f"WebSocket connection error: {e}")
                self._handle_disconnection()

    def _handle_disconnection(self):
        """Handles reconnection attempts when the WebSocket disconnects."""
        if not self.running:
            return

        if self.reconnect_attempts >= self.max_retries:
            self.logger.error("Max WebSocket reconnect attempts reached. Stopping...")
            self.running = False
            return

        self.reconnect_attempts += 1
        self.logger.warning(
            f"Reconnecting WebSocket ({self.reconnect_attempts}/{self.max_retries}) in {self.reconnect_delay} seconds..."
        )
        time.sleep(self.reconnect_delay)

        # Restart WebSocket connection
        self._connect()

    def stop(self):
        """Stops the WebSocket connection gracefully."""
        self.logger.info("Stopping WebSocket...")
        self.running = False
        if self.fyers:
            try:
                self.fyers.close()
            except Exception as e:
                self.logger.error(f"Error closing WebSocket: {e}")
