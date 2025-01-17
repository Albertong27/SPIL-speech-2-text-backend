import asyncio
import websockets

async def listen():
    uri = "ws://localhost:8000/ws/audio"
    async with websockets.connect(uri) as websocket:
        print("Connected to WebSocket server")
        try:
            while True:
                message = await websocket.recv()
                print("Listener: ", message)
        except websockets.ConnectionClosed:
            print("Connection closed")



if __name__ == "__main__":
    asyncio.run(listen())
