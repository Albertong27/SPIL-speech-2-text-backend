from fastapi import FastAPI, WebSocket
from fastapi.websockets import WebSocketDisconnect
import asyncio
import uvicorn
from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.handlers import TranscriptResultStreamHandler
from amazon_transcribe.model import TranscriptEvent
from datetime import datetime

app = FastAPI()

class MyEventHandler(TranscriptResultStreamHandler):
    def __init__(self, stream, websocket: WebSocket, filepath: str):
        super().__init__(stream)
        self.websocket = websocket
        self.partial_sentence = []
        self.last_partial_transcript = ""
        self.filepath = filepath

    async def handle_transcript_event(self, transcript_event: TranscriptEvent):
        for sentence in transcript_event.transcript.results:
            if sentence.is_partial:
                current_partial = ""
                for alt in sentence.alternatives:
                    current_partial = alt.transcript.strip()
                
                if current_partial != self.last_partial_transcript:
                    self.last_partial_transcript = current_partial
                    print(f"Partial: {current_partial}")
                    if self.websocket:
                        await self.websocket.send_text(current_partial)
            else:
                for alt in sentence.alternatives:
                    self.partial_sentence.append(alt.transcript.strip())
                final_sentence = " ".join(self.partial_sentence).strip()
                print(f"Final: {final_sentence}")
                if self.websocket:
                    await self.websocket.send_text(f"final: {final_sentence}")
                    with open(self.filepath, mode='a', encoding='UTF-8') as output:
                        print(final_sentence, file=output)
                self.partial_sentence = []
                self.last_partial_transcript = ""

async def browser_audio_stream(websocket: WebSocket, transcribe_stream):
    try:
        while True:
            audio_chunk = await websocket.receive_bytes()
            await transcribe_stream.input_stream.send_audio_event(audio_chunk=audio_chunk)
    except WebSocketDisconnect:
        print("WebSocket disconnected")
        await transcribe_stream.input_stream.end_stream()

async def browser_transcribe(websocket, filepath):
    client = TranscribeStreamingClient(region="us-east-1")
    stream = await client.start_stream_transcription(
        language_code="id-ID",
        media_sample_rate_hz=16000,
        media_encoding="pcm",
    )
    handler = MyEventHandler(stream.output_stream, websocket, filepath)
    await asyncio.gather(browser_audio_stream(websocket, stream), handler.handle_events())

@app.get("/")
def root():
    return {"Hola": "SPIL"}

@app.websocket("/aws-browser-transcribe")
async def websocket_handler_browser(websocket: WebSocket):
    await websocket.accept()
    try:
        print("Client connected")
        filepath = datetime.now().strftime("%d-%m-%Y %H.%M.%S")
        await browser_transcribe(websocket, filepath)
    except WebSocketDisconnect:
        print("Client disconnected")

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
