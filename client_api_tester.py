import asyncio
import websockets
import json

async def listen():
    uri = "ws://localhost:8000/summarizer"
    async with websockets.connect(uri) as websocket:
        print("Connected to WebSocket server")
        
        # Data yang akan dikirim ke server
        data = {
            "start_datetime": "01-02-2025 10:55",  # Ganti dengan tanggal dan waktu yang sesuai
            "end_datetime": "01-02-2025 11:03"    # Ganti dengan tanggal dan waktu yang sesuai
        }
        
        # Kirim data ke server
        await websocket.send(json.dumps(data))
        print("Data sent to server:", data)

        try:
            while True:
                # Terima pesan dari server
                message = await websocket.recv()
                print("Received from server:", message)
        except websockets.ConnectionClosed:
            print("Connection closed")

if __name__ == "__main__":
    asyncio.run(listen())
