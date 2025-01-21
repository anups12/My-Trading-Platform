import queue
import threading

from fyers_apiv3.FyersWebsocket import order_ws


class FyersWebSocketManager:
    def __init__(self, access_token, logger):
        self.access_token = access_token
        self.logger = logger
        self.q = queue.Queue()
        self.thread = None
        self.running = False

    def onOrder(self, message):
        """Handles incoming WebSocket messages."""
        self.logger.info(f"Order Message Received: {message}")
        self.q.put(message)

    def onError(self, message):
        """Handles WebSocket errors."""
        self.logger.error(f"WebSocket Error: {message}")

    def onClose(self, message):
        """Handles WebSocket closure."""
        self.logger.warning(f"WebSocket Closed: {message}")
        self.running = False

    def onOpen(self):
        """Handles WebSocket connection and subscription."""
        self.logger.info("WebSocket Connected")
        data_type = "OnOrders"  # Adjust this based on your subscription needs
        self.fyers.subscribe(data_type=data_type)
        self.fyers.keep_running()

    def start(self):
        """Starts the WebSocket in a separate thread."""
        self.running = True
        self.thread = threading.Thread(target=self._connect, daemon=True)
        self.thread.start()

    def _connect(self):
        """Connects to the WebSocket."""
        self.fyers = order_ws.FyersOrderSocket(
            access_token=self.access_token,
            write_to_file=False,
            log_path="",
            on_connect=self.onOpen,
            on_close=self.onClose,
            on_error=self.onError,
            on_orders=self.onOrder,
        )
        self.fyers.connect()

    def stop(self):
        """Stops the WebSocket connection."""
        self.running = False
        if self.fyers:
            self.fyers.close()
