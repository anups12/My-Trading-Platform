import logging
import queue
import threading
from fyers_apiv3.FyersWebsocket import order_ws
from accounts.utils import client_id


class FyersWebSocketManager:

    def __init__(self, access_token):
        self.access_token = access_token
        self.ws = None
        self.q = queue.Queue()
        self.thread = None  # For managing the WebSocket thread

    def on_order(self, message):
        """Callback for order updates."""
        if message:
            print('Message in WebSocket:', message)
            self.q.put(message)

    def on_error(self, message):
        """Callback for WebSocket errors."""
        print("WebSocket Error:", message)

    def on_close(self, message):
        """Callback for WebSocket disconnections."""
        print('WebSocket Closed:', message)

    def on_open(self):
        """Callback for WebSocket connection."""
        print('WebSocket Open and Ready to Subscribe')

    def start(self):
        """Starts the WebSocket connection in a separate thread."""
        if self.thread and self.thread.is_alive():
            logging.debug("WebSocket is already running.")
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
        logging.debug("WebSocket thread started.")

    def subscribe(self):
        """Subscribe to 'OnOrders'."""
        if self.ws:
            logging.debug("Subscribing to OnOrders...")
            self.ws.subscribe(data_type="OnOrders")
        else:
            logging.debug("WebSocket connection is not active. Start it first.")

    def unsubscribe(self):
        """Unsubscribe from 'OnOrders'."""
        if self.ws:
            logging.debug("Unsubscribing from OnOrders...")
            self.ws.unsubscribe("OnOrders")
        else:
            logging.debug("WebSocket connection is not active.")

    def stop(self):
        """Stops the WebSocket connection."""
        if self.ws:
            self.unsubscribe()  # Unsubscribe before closing
            logging.debug("Stopping WebSocket connection...")
        if self.thread and self.thread.is_alive():
            logging.debug("Stopping WebSocket thread.")
            self.thread.join(timeout=2)
        logging.debug("WebSocket thread stopped.")