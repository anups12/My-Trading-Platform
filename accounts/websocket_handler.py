import queue
import threading
from fyers_apiv3.FyersWebsocket import order_ws
from accounts.utils import client_id


class FyersWebSocketManager:

    def __init__(self, access_token, logger):
        self.access_token = access_token
        self.ws = None
        self.q = queue.Queue()
        self.thread = None  # For managing the WebSocket thread
        self.logger = logger
        
    def on_order(self, message):
        """Callback for order updates."""
        try:
            if message:
                self.q.put(message)
        except Exception as ex:
            self.logger.debug("Exception inside On order function")

    def on_error(self, message):
        """Callback for WebSocket errors."""
        self.logger.error(f"WebSocket Error: {message}", )
        self.logger.info("Attempting to reconnect...")
        self.start()  # Restart the WebSocket connection

    def on_close(self, message):
        """Callback for WebSocket disconnections."""
        self.logger.error(f'WebSocket Closed: {message}', )
        self.logger.info("Attempting to reconnect...")
        self.start()  # Restart the WebSocket connection

    def on_open(self):
        """Callback for WebSocket connection."""
        self.logger.info('WebSocket Open and Ready to Subscribe')

    def start(self):
        """Starts the WebSocket connection in a separate thread."""
        if self.thread and self.thread.is_alive():
            self.logger.debug("WebSocket is already running.")
            return

        # Define the thread target
        def run_ws():
            self.ws = order_ws.FyersOrderSocket(
                access_token=f"{client_id}:{self.access_token}",
                write_to_file=False,
                log_path="",
                on_connect=self.on_open,
                on_close=self.on_close,
                on_error=self.on_error,
                on_orders=self.on_order,
            )
            self.ws.connect()

        # Start the thread
        self.thread = threading.Thread(target=run_ws, daemon=True)
        self.thread.start()
        self.logger.debug("WebSocket thread started.")

    def subscribe(self):
        """Subscribe to 'OnOrders'."""
        if self.ws:
            self.logger.debug("Subscribing to OnOrders...")
            self.ws.subscribe(data_type="OnOrders")
        else:
            self.logger.debug("WebSocket connection is not active. Start it first.")

    def unsubscribe(self):
        """Unsubscribe from 'OnOrders'."""
        if self.ws:
            self.logger.debug("Unsubscribing from OnOrders...")
            self.ws.unsubscribe("OnOrders")
        else:
            self.logger.debug("WebSocket connection is not active.")

    def stop(self):
        """Stops the WebSocket connection."""
        if self.ws:
            self.unsubscribe()  # Unsubscribe before closing
            self.logger.debug("Stopping WebSocket connection...")
        if self.thread and self.thread.is_alive():
            self.logger.debug("Stopping WebSocket thread.")
            self.thread.join(timeout=2)
        self.logger.debug("WebSocket thread stopped.")

    def check_and_start(self):
        """Checks if the WebSocket is active and starts it if not."""
        if not self.thread or not self.thread.is_alive():
            self.logger.debug("WebSocket is not active. Starting WebSocket...")
            self.start()
        else:
            self.logger.debug("WebSocket is already active.")