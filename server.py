import asyncio
import websockets
from google.cloud import speech
import os
import queue
import numpy as np
from concurrent.futures import ThreadPoolExecutor

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'aiproject-itdev-0190cfc63da2.json'

RATE = 44100
CHANNELS = 1

def responseFunc(response, websocket, loop):
    if not response.results:
        return

    result = response.results[0]
    if not result.alternatives:
        return

    transcript = result.alternatives[0].transcript

    if result.is_final:
        print(f"final: {transcript}")
        asyncio.run_coroutine_threadsafe(websocket.send(f"final: {transcript}"), loop)
    else:
        print(f"Interim: {transcript}")
        asyncio.run_coroutine_threadsafe(websocket.send(transcript), loop)

async def echoFunc(websocket, path):
    print("Client connected")
    loop = asyncio.get_event_loop()

    client = speech.SpeechClient()
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE,
        language_code="id-ID",
        audio_channel_count=CHANNELS,
    )

    streaming_config = speech.StreamingRecognitionConfig(config=config, interim_results=True)

    audio_queue = queue.Queue()

    def request():
        while True:
            try:
                chunk = audio_queue.get()
                if chunk is None: 
                    break
                yield speech.StreamingRecognizeRequest(audio_content=chunk.tobytes())
            except Exception as e:
                print(f"Error in request function: {e}")
                break

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            def recognition():
                requests = request()
                response = client.streaming_recognize(streaming_config, requests)
                try:
                    for r in response:
                        responseFunc(r, websocket, loop)
                except Exception as e:
                    print(f"Error in recognition: {e}")

            future = executor.submit(recognition)
            
            async for message in websocket:
                try:
                    audio_data = np.frombuffer(message, dtype=np.int16)
                    audio_queue.put(audio_data)
                except Exception as e:
                    print(f"Error processing message: {e}")
                    break

    except websockets.exceptions.ConnectionClosed:
        print("Client disconnected")
        
    finally:
        audio_queue.put(None)

async def startFunc():
    server = await websockets.serve(echoFunc, "localhost", 8080)
    print("WebSocket server started at ws://localhost:8080")
    await server.wait_closed()

if __name__ == "__main__":
    asyncio.run(startFunc())
    