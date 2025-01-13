import sounddevice as sd
import numpy as np
from google.cloud import speech
import os
import queue
import asyncio
import websockets
import io

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'aiproject-itdev-0190cfc63da2.json'

RATE = 44100
CHANNELS = 1
audio_queue = queue.Queue()

connected_clients = set()
transcription_active = False
transcript_buffer = ""

async def handler(websocket, path):
    global transcription_active, transcript_buffer

    connected_clients.add(websocket)
    try:
        async for message in websocket:
            if message.lower() == "start":
                print("client requested to start")
                await websocket.send("started!")
                transcription_active = True
                transcript_buffer = ""
                await start_speech_to_text(websocket)
            elif message.lower() == "stop":
                print("client requested to stop")
                transcription_active = False
                await websocket.send("stopped!")
                save_transcript_to_file(transcript_buffer)
            else:
                await websocket.send("no action")
    except Exception as e:
        print(f"error: {e}")
    finally:
        connected_clients.remove(websocket)

def audio_callback(indata, frames, time, status):
    if status:
        print(f"status: {status}")
    audio_queue.put(indata.copy())

def audio_generator():
    while True:
        chunk = audio_queue.get()
        if chunk is None:
            break
        yield chunk.tobytes()

async def send_transcript(websocket, transcript):
    try:
        await websocket.send(transcript)
    except Exception as e:
        print(f"sending error: {e}")

async def transcribe_streaming(websocket):
    global transcription_active, transcript_buffer

    client = speech.SpeechClient()

    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE,
        language_code="id-ID",
        audio_channel_count=CHANNELS,
    )

    streaming_config = speech.StreamingRecognitionConfig(
        config=config,
        interim_results=True,
    )

    requests = (
        speech.StreamingRecognizeRequest(audio_content=chunk)
        for chunk in audio_generator()
    )

    responses = client.streaming_recognize(config=streaming_config, requests=requests)

    print("listening...")
    try:
        for response in responses:
            if not transcription_active:
                break

            for result in response.results:
                transcript = result.alternatives[0].transcript
                if result.is_final:
                    print(f"final: {transcript}")
                    await asyncio.create_task(send_transcript(websocket, f"\nfinal: {transcript}"))
                    transcript_buffer += transcript + "\n"
                else:
                    print(f"interim: {transcript}")
                    await asyncio.create_task(send_transcript(websocket, transcript))

    except Exception as e:
        print(f"transcription error: {e}")
    finally:
        print("Closing WebSocket connection")
        await websocket.close()

async def start_speech_to_text(websocket):
    try:
        devices = sd.query_devices()
        loopback_device = 2

        for idx, device in enumerate(devices):
            if "loopback" in device['name'].lower():
                loopback_device = idx
                break

        if loopback_device is None:
            raise RuntimeError("no loopback device found")

        with sd.InputStream(
            samplerate=RATE,
            channels=CHANNELS,
            callback=audio_callback,
            dtype='int16',
            device=loopback_device
        ):
            await transcribe_streaming(websocket)

    except Exception as e:
        print(f"Error: {e}")

def save_transcript_to_file(transcript):
    with open("transcript.txt", "w") as file:
        file.write(transcript)
    print("transcript saved to transcript.txt")

async def start_websocket_server():
    server = await websockets.serve(handler, "localhost", 8765)
    print("WebSocket server started at ws://localhost:8765")
    await server.wait_closed()

if __name__ == "__main__":
    asyncio.run(start_websocket_server())
