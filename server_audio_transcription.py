from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import asyncio
import sounddevice
from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.handlers import TranscriptResultStreamHandler
from amazon_transcribe.model import TranscriptEvent

app = FastAPI()

class MyEventHandler(TranscriptResultStreamHandler):

    def __init__(self, stream, websocket: WebSocket):
        super().__init__(stream)
        self.websocket = websocket

    async def handle_transcript_event(self, transcript_event: TranscriptEvent):
        """
        Handle the transcription event and send results to the WebSocket client.
        """
        results = transcript_event.transcript.results
        for result in results:
            if result.is_partial:
                continue
            for alt in result.alternatives:
                transcript = alt.transcript.strip()
                print(f"Speaker: {transcript}")
                if self.websocket:
                    await self.websocket.send_text(transcript)


async def mic_stream():
    """
    Stream audio input from the microphone and forward it to the transcription client.
    """
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


async def write_chunks(transcribe_stream):
    """
    Send audio chunks from the microphone to the transcription stream.
    """
    async for chunk, status in mic_stream():
        await transcribe_stream.input_stream.send_audio_event(audio_chunk=chunk)
    await transcribe_stream.input_stream.end_stream()


async def transcribe(websocket: WebSocket):
    """
    Handle real-time transcription and send results via WebSocket.
    """
    client = TranscribeStreamingClient(region="us-east-1")

    stream = await client.start_stream_transcription(
        language_code="id-ID",
        media_sample_rate_hz=16000,
        media_encoding="pcm",
    )

    handler = MyEventHandler(stream.output_stream, websocket)
    await asyncio.gather(write_chunks(stream), handler.handle_events())


@app.websocket("/ws/audio")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint to handle real-time transcription.
    """
    await websocket.accept()
    try:
        print("Client connected")
        await transcribe(websocket)
    except WebSocketDisconnect:
        print("Client disconnected")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server_audio_transcription:app", host="0.0.0.0", port=8000, reload=True)

