import json

import websocket
import ssl
import threading
import queue
import logging
import time


class WebSocketClient(threading.Thread):
    """
    WebSocket client running in a separate thread.
    """
    def __init__(self, url):
        super().__init__(daemon=True)
        self.url = url
        self.message_queue = queue.Queue()
        self.ws = None
        self.running = False

    def run(self):
        """
        Starts the WebSocket connection and listens for messages.
        """
        self.running = True
        self.ws = websocket.WebSocketApp(
            url=self.url,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
        )
        self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})

    def stop(self):
        """
        Stops the WebSocket connection and thread.
        """
        self.running = False
        if self.ws:
            self.ws.close()

    def on_message(self, ws, message):
        if isinstance(message, bytes):
            message = message.decode('utf-8')
        if "status" in message:
            self.message_queue.put(message)

    def on_error(self, ws, error):
        """
        Handles WebSocket errors.
        """
        print('on error', error)

    def on_close(self, ws, close_status_code, close_msg):
        """
        Handles WebSocket closure.
        """
        print('close', close_msg)

    def on_open(self, ws):
        """
        Handles WebSocket opening.
        """
        self.subscribe()
        print('websocket opened')

    def unsubscribe(self):
        print("websocket unsubscribed")
        self.ws.send("uor+{}")

    def subscribe(self):
        time.sleep(3)
        print('websocket subscribed instantly')
        self.ws.send('sor+{}')