from fastapi import FastAPI, WebSocket
from fastapi.websockets import WebSocketDisconnect
import asyncio
import uvicorn
import sounddevice
from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.handlers import TranscriptResultStreamHandler
from amazon_transcribe.model import TranscriptEvent

app = FastAPI()

class MyEventHandler(TranscriptResultStreamHandler):
    def __init__(self, stream, websocket):
        super().__init__(stream)
        self.websocket = websocket

    async def handle_transcript_event(self, transcript_event: TranscriptEvent):
        results = transcript_event.transcript.results
        for result in results:
            if result.is_partial:
                continue
            for alt in result.alternatives:
                transcript = alt.transcript.strip()
                print(f"Speaker: {transcript}")
                if self.websocket:
                    await self.websocket.send_text(transcript)


async def mic_audio_stream():
    loop = asyncio.get_event_loop()
    input_queue = asyncio.Queue()

    def callback(indata, frame_count, time_info, status):
        loop.call_soon_threadsafe(input_queue.put_nowait, (bytes(indata), status))

    stream = sounddevice.RawInputStream(
        channels=1,
        samplerate=16000,
        callback=callback,
        blocksize=512,
        dtype="int16",
    )

    with stream:
        while True:
            indata, status = await input_queue.get()
            yield indata, status


async def browser_audio_stream(websocket: WebSocket, transcribe_stream):
    try:
        while True:
            audio_chunk = await websocket.receive_bytes()
            await transcribe_stream.input_stream.send_audio_event(audio_chunk=audio_chunk)
    except WebSocketDisconnect:
        print("WebSocket disconnected")
        await transcribe_stream.input_stream.end_stream()


async def write_chunks(transcribe_stream):
    async for chunk, status in mic_audio_stream():
        await transcribe_stream.input_stream.send_audio_event(audio_chunk=chunk)
    await transcribe_stream.input_stream.end_stream()


async def mic_transcribe(websocket):
    client = TranscribeStreamingClient(region="us-east-1")
    stream = await client.start_stream_transcription(
        language_code="id-ID",
        media_sample_rate_hz=16000,
        media_encoding="pcm",
    )
    handler = MyEventHandler(stream.output_stream, websocket)
    await asyncio.gather(write_chunks(stream), handler.handle_events())
    

async def browser_transcribe(websocket):
    client = TranscribeStreamingClient(region="us-east-1")
    stream = await client.start_stream_transcription(
        language_code="id-ID",
        media_sample_rate_hz=16000,
        media_encoding="pcm",
    )
    handler = MyEventHandler(stream.output_stream, websocket)   
    await asyncio.gather(browser_audio_stream(websocket, stream), handler.handle_events())


@app.get("/")
def root():
    return {"Hola" : "SPIL"}


@app.websocket("/mic-transcribe")
async def websocket_handler_mic(websocket: WebSocket):
    await websocket.accept()
    try:
        print("Client connected")
        await mic_transcribe(websocket)
    except WebSocketDisconnect:
        print("Client disconnected")


@app.websocket("/browser-transcribe")
async def websocket_handler_browser(websocket: WebSocket):
    await websocket.accept()
    try:
        print("Client connected")
        await browser_transcribe(websocket)
    except WebSocketDisconnect:
        print("Client disconnected")



if __name__ == "__main__":
    uvicorn.run("server_api:app", host="0.0.0.0", port=8000, reload=True)
