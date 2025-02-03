import os
import asyncio
import httpx
import uvicorn
import sounddevice
import markdown
from pymongo.errors import ConnectionFailure
from loguru import logger
from bson import ObjectId
from pymongo import MongoClient
from datetime import datetime
from dotenv import load_dotenv
from pymongo.server_api import ServerApi
from fastapi import FastAPI, WebSocket, Form
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

load_dotenv()

# MongoDB Configuration
# For cloud
# mongo_key = os.getenv("DB_HOST")     # insert the mongo key
# client = MongoClient(mongo_key, server_api=ServerApi('1'))
# db = client.spil    # this 'spil' is the database names
# db_table = db.data  # this 'data' is the collection names of db

# For local connectiom
client = MongoClient("mongodb://localhost:27017/")
db = client.spil    # this 'spil' is the database names
db_table = db.data  # this 'data' is the collection names of db
db_table1 = db.summary  # Hasil Summarize

# Log Configuration
log_path = "FILE_PATH/app.log"
os.makedirs(os.path.dirname(log_path), exist_ok=True)
logger.add(log_path, rotation="10 MB", retention="30 days", compression="zip")

# Txt Configuration
file_name = datetime.now().strftime('%d-%m-%Y %H.%M')
txt_dir_name = "FILE_PATH/"
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
                    if self.output != '':
                        if self.ws:
                            time = datetime.now().strftime('%d-%m-%Y %H:%M')
                            await self.ws.send_json({
                                "datetime": time,
                                "transcription": self.output
                            })
                        await self.handle_db_output()
                        await self.handle_txt_output()
                        self.output = ""
        except Exception as e:
            logger.exception(f"Error while handling transcript event")

    async def handle_db_output(self):
        date = datetime.now().strftime('%d-%m-%Y')
        time = datetime.now().strftime('%H:%M')

        db_table.insert_one({"date": date,
                             "time": time,
                             "transcript": self.output})

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
                    loop.call_soon_threadsafe(
                        input_queue.put_nowait, (bytes(indata), status))

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


# Root Endpoints (Testing)
@app.get("/")
def root():
    logger.info("Root endpoint accessed")
    return {"message": "Hello, World!"}


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
@app.websocket("/aws-browser-transcribe")
async def browser_transcription(websocket: WebSocket):
    await websocket.accept()
    try:
        logger.info("Client connected for browser transcription")
        await audio_transcription(websocket, source="browser")
    except WebSocketDisconnect:
        logger.warning("Client disconnected (browser transcription)")
    except Exception as e:
        logger.error(f"Unexpected error in browser transcription")

# preview Endpoints


@app.post("/preview")
async def preview_ws(
    start_datetime: str = Form(...),
    end_datetime: str = Form(...)
):
    # await websocket.accept()
    try:
        if True:
            # data = await websocket.receive_json()
            # start_datetime = data.get("start_datetime")
            # end_datetime = data.get("end_datetime")
            try:
                start_datetime = datetime.strptime(
                    start_datetime, '%d-%m-%Y %H:%M')
                end_datetime = datetime.strptime(
                    end_datetime, '%d-%m-%Y %H:%M')
                date = start_datetime.strftime('%d-%m-%Y')
            except ValueError as e:
                logger.error(f"Invalid datetime format: {e}")
                return {
                    "status": "error",
                    "message": "Invalid datetime format. Use 'DD-MM-YYYY HH:MM'."
                }
                # continue
            transcripts = db_table.find({
                "date": date, "time": {"$gte": start_datetime.strftime('%H:%M:%S'), "$lte": end_datetime.strftime('%H:%M:%S')}
            }, {"_id": 0, "transcript": 1})
            transcript_list = list(transcripts)

            if not transcript_list:
                logger.warning(
                    f"No data found for time range {start_datetime} - {end_datetime}")
                return {
                    "status": "no_data",
                    "message": "No transcripts found within the provided time range."
                }
                # continue

            # Gabungkan transkripsi menjadi satu teks
            transcript = " ".join([doc["transcript"]
                                  for doc in transcript_list])
            return {
                "status": "success",
                "transcript": transcript
            }
    except Exception as e:
        pass

# Summarizer Endpoints


@app.websocket("/summarizer")
async def summarizer_websocket(websocket: WebSocket):
    await websocket.accept()
    summarizer_url = "http://192.168.1.50:19110/api/sac/summarize"
    try:
        logger.info("Client connected to summarizer endpoint")

        while True:

            data = await websocket.receive_json()
            start_datetime = data.get("start_datetime")
            end_datetime = data.get("end_datetime")

            # start_datetime = "01-02-2025 10:23"
            # end_datetime = "01-02-2025 10:25"

            try:
                start_datetime = datetime.strptime(
                    start_datetime, '%d-%m-%Y %H:%M')
                end_datetime = datetime.strptime(
                    end_datetime, '%d-%m-%Y %H:%M')
            except ValueError as e:
                logger.error(f"Invalid datetime format: {e}")
                await websocket.send_json({
                    "status": "error",
                    "message": "Invalid datetime format. Use 'DD-MM-YYYY HH:MM'."
                })
                continue

            try:
                date = start_datetime.strftime('%d-%m-%Y')
                transcripts = db_table.find({
                    "date": date, "time": {"$gte": start_datetime.strftime('%H:%M:%S'), "$lte": end_datetime.strftime('%H:%M:%S')}
                }, {"_id": 0, "transcript": 1})
                transcript_list = list(transcripts)

                if not transcript_list:
                    logger.warning(
                        f"No data found for time range {start_datetime} - {end_datetime}")
                    await websocket.send_json({
                        "status": "no_data",
                        "message": "No transcripts found within the provided time range."
                    })
                    continue

                # Gabungkan transkripsi menjadi satu teks
                transcript = " ".join([doc["transcript"]
                                      for doc in transcript_list])
                # await websocket.send_json({
                #     "status": "success",
                #     "transcript": transcript
                # })

                prompt_indo = "Tolong buatlah kesimpulan dari kalimat ini menggunakan bahasa indonesia :"

                async with httpx.AsyncClient() as client:  # Transkrip tidak keluar coba tambahkan timeout=30.0
                    # Format data API
                    data = {
                        "raw_input": (None, prompt_indo + transcript),
                        "id_room": (None, "0"),
                        "raw_start": (None, start_datetime.strftime('%d-%m-%Y %H:%M')),
                        "raw_end": (None, end_datetime.strftime('%d-%m-%Y %H:%M'))
                    }

                    try:
                        response = await client.post(summarizer_url, files=data)
                        response.raise_for_status()

                        result = response.json()
                        summary = result.get('result', {}).get(
                            'response', "Summary not found")

                        formatmd = summary.replace("\n", "").replace("\t", "")
                        save = {
                            "timestamp": datetime.now().strftime('%d-%m-%Y'),
                            "summary": formatmd
                        }
                        db_table1.insert_one(save)

                        formathtml = summary.replace(
                            "\n", "<br>").replace("\t", "<br>")
                        htmlsummary = markdown.markdown(formathtml)

                        # Kirim Transkrip
                        await websocket.send_json({
                            "status": "success",
                            "summary": htmlsummary
                        })
                    except httpx.HTTPStatusError as e:
                        # Tangani error HTTP (misalnya, 422 Unprocessable Entity)
                        logger.error(f"Error sending data to summarizer: {e}")
                        # Log response dari API
                        logger.error(f"Response content: {e.response.text}")
                        await websocket.send_json({
                            "status": "error",
                            "message": f"Summarizer API error: {e.response.text}"
                        })
                    except Exception as e:
                        # Tangani error lainnya
                        logger.exception("Unexpected error in summarizer")
                        await websocket.send_json({
                            "status": "error",
                            "message": "An unexpected error occurred."
                        })
            except ValueError as ve:
                logger.error(f"Error: {ve}")
                await websocket.send_json({
                    "status": "error",
                    "message": str(ve)
                })
            except ConnectionFailure as e:
                logger.error(f'Error saving data to mongoDB: {e}')
                await websocket.send_json({
                    "status": "error",
                    "message": str(e)
                })
            except httpx.HTTPStatusError as e:
                logger.error(f"Error sending data to summarizer: {e}")
                await websocket.send_json({
                    "status": "error",
                    "message": str(e)
                })
            except Exception as e:
                logger.exception(
                    "Error querying MongoDB or summarizing transcript")
                await websocket.send_json({
                    "status": "error",
                    "message": "Internal server error. Please try again later."
                })

    except WebSocketDisconnect:
        logger.warning("Client disconnected from summarizer endpoint")
    except Exception as e:
        logger.error(f"Unexpected error in summarizer: {e}")
        await websocket.send_json({
            "status": "error",
            "message": "An unexpected error occurred."
        })

if __name__ == "__main__":
    try:
        logger.info("Starting server...")
        uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
    except Exception as e:
        logger.error(f"An unexpected error occurred")


# MongoDB Installation
# https://youtu.be/MyIiM7z_j_Y?si=uU7Hx9E5nOaf3eyG
# MongoDB Tutorial
# https://youtu.be/qWYx5neOh2s?si=ph4MEtIXQLa94DPf
