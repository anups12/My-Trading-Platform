import json
from channels.generic.websocket import AsyncWebsocketConsumer


class DataConsumer(AsyncWebsocketConsumer):
    print('this is called')
    async def connect(self):
        self.group_name = 'data_group'

        # Join the group
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        # Leave the group
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        # Receive message from WebSocket
        data = json.loads(text_data)

        # Process incoming data and send to group
        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'send_data',
                'data': data
            }
        )

    async def send_data(self, event):
        # Example of data structure sent to the WebSocket
        await self.send(text_data=json.dumps({
            'symbol': event['data']['symbol'],  # The instrument symbol
            'price': event['data']['price'],  # The current price
        }))
