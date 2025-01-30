import asyncio
import websockets

async def listen():
    uri = "ws://localhost:8000/mic-transcribe"
    async with websockets.connect(uri) as websocket:
        print("Connected to WebSocket")
        while True:
            message = await websocket.recv()
            print("Message: ", message)

asyncio.run(listen())
