import os
import asyncio
import uvicorn
import sounddevice
from loguru import logger
from datetime import datetime
from fastapi import FastAPI, WebSocket
from fastapi.websockets import WebSocketDisconnect
from amazon_transcribe.model import TranscriptEvent
from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.handlers import TranscriptResultStreamHandler
from amazon_transcribe.exceptions import (
    UnknownServiceException,
    BadRequestException,
    LimitExceededException,
    InternalFailureException,
    ConflictException,
    ServiceUnavailableException,
    SerializationException
)

# FastAPI Configuration
app = FastAPI()

# Log Configuration
log_path = "aistudio/apps/logs/app.log"
os.makedirs(os.path.dirname(log_path), exist_ok=True)
logger.add(log_path, rotation="10 MB", retention="30 days", compression="zip")

# Txt Configuration
file_name = datetime.now().strftime('%d-%m-%Y %H.%M.%S')
txt_dir_name = "aistudio/apps/output/"
txt_path = f"{txt_dir_name}{file_name}.txt"


class AWSTranscription(TranscriptResultStreamHandler):
    def __init__(self, stream, websocket: WebSocket):
        super().__init__(stream)
        self.ws = websocket
        self.output = ""
        # Txt Output
        os.makedirs(os.path.dirname(txt_dir_name), exist_ok=True)
        self.txt_file = open(txt_path, "a", encoding="utf-8")
        logger.info("Txt output file has been created")

    async def handle_transcript_event(self, event: TranscriptEvent):
        try:
            for result in event.transcript.results:
                if result.is_partial:
                    for alt in result.alternatives:
                        self.output = alt.transcript.strip().lower()
                        if self.ws:
                            await self.ws.send_text("listening")
                else:
                    if self.ws:
                        await self.ws.send_text(f"transcription: {self.output}. ")
                    await self.handle_txt_output()
                    self.output = ""
        except Exception as e:
            logger.exception(f"Error while handling transcript event")

    async def handle_db_output(self):
        time = datetime.now().strftime('%H:%M:%S')

        data = {
            "time": time,
            "transcript": self.output
        }

        # sending 'data' to mongoDB here
        

    async def handle_txt_output(self):
        try:
            self.txt_file.write(self.output + "\n")
            self.txt_file.flush()
        except Exception as e:
            self.txt_file.close()
            logger.exception(f"Error while writing transcript to txt file")
        
    def close_txt_output(self):
        try:
            self.txt_file.close()
            logger.info("Txt output file has been closed")
        except Exception as e:
            logger.exception(f"Error while closing txt file")


async def audio_transcription(websocket: WebSocket, source: str = "mic"):
    client = TranscribeStreamingClient(region="us-east-1")

    try:
        stream = await client.start_stream_transcription(
            language_code="id-ID",
            media_sample_rate_hz=16000,
            media_encoding="pcm",
        )
        logger.info(f"Started transcription stream for source: {source}")
    except (UnknownServiceException, BadRequestException, LimitExceededException, InternalFailureException, 
            ConflictException, ServiceUnavailableException, SerializationException) as e:
        logger.error(f"Error starting transcription stream")
        return

    handler = AWSTranscription(stream.output_stream, websocket)

    try:
        if source == "mic":
            async def audio_source():
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
                try:
                    with stream:
                        while True:
                            indata, status = await input_queue.get()
                            yield indata, status
                except Exception as e:
                    logger.error(f"Microphone input error")
                    raise

            async def send_audio():
                async for chunk, status in audio_source():
                    try:
                        await stream.input_stream.send_audio_event(audio_chunk=chunk)
                    except Exception as e:
                        logger.error(f"Error sending audio from mic")
                        raise
                await stream.input_stream.end_stream()

        elif source == "browser":
            async def send_audio():
                try:
                    while True:
                        audio_chunk = await websocket.receive_bytes()
                        try:
                            await stream.input_stream.send_audio_event(audio_chunk=audio_chunk)
                        except Exception as e:
                            logger.error(f"Error sending browser audio chunk")
                            raise
                except WebSocketDisconnect:
                    logger.warning("WebSocket disconnected")
                    await stream.input_stream.end_stream()
                except Exception as e:
                    logger.error(f"Browser audio stream error")
                    raise

        await asyncio.gather(send_audio(), handler.handle_events())
    except Exception as e:
        logger.exception(f"Unexpected error during transcription")
        handler.close_txt_output()


# Root Endpoints (Testing)
@app.get("/")
def root():
    logger.info("Root endpoint accessed")
    return {"message": "Hello, World!"}


# # Event Startup
# @app.on_event("startup")
# async def startup_event():
#     logger.info("Server started. Listening for requests...")


# # Event Shutdown
# @app.on_event("shutdown")
# async def shutdown_event():
#     logger.warning("Server is shutting down...")
#     logger.info("Cleaning up resources...")
#     logger.info("Shutdown process complete.")


# Microphone Audio Inputs Endpoints
@app.websocket("/mic-transcribe")
async def mic_transcription(websocket: WebSocket):
    await websocket.accept()
    try:
        logger.info("Client connected for microphone transcription")
        await audio_transcription(websocket, source="mic")
    except WebSocketDisconnect:
        logger.warning("Client disconnected (microphone transcription)")
    except Exception as e:
        logger.error(f"Unexpected error in mic transcription")


# Browser Audio Inputs Endpoints
@app.websocket("/browser-transcribe")
async def browser_transcription(websocket: WebSocket):
    await websocket.accept()
    try:
        logger.info("Client connected for browser transcription")
        await audio_transcription(websocket, source="browser")
    except WebSocketDisconnect:
        logger.warning("Client disconnected (browser transcription)")
    except Exception as e:
        logger.error(f"Unexpected error in browser transcription")


# Main Start
if __name__ == "__main__":
    try:
        logger.info("Starting server...")
        uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
    except Exception as e:
        logger.error(f"An unexpected error occurred")


# MASUKIN OUTPUT TXT
# URUS SUMMARIZER