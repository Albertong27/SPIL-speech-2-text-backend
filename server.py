import os
import httpx
import requests
import asyncio
import uvicorn
import sounddevice
import markdown
from loguru import logger
from bson import ObjectId
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from fastapi import FastAPI, WebSocket, Form
from pymongo.errors import ConnectionFailure
from fastapi.middleware.cors import CORSMiddleware
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# MongoDB Configuration
load_dotenv()

# MongoDB Atlas     (cloud)
# client = MongoClient("", server_api=ServerApi('1'))

# MongoDB Compass   (local)
client = MongoClient("mongodb://localhost:27017/")

db = client.spil
coll_data = db.data
coll_summary = db.summary

# Logging Configuration
log_dir = "app/"
log_name = "app.log"
log_path = log_dir + log_name
os.makedirs(os.path.dirname(log_path), exist_ok=True)
logger.add(log_path, rotation="10 MB", retention="30 days", compression="zip")

# Txt Configuration
txt_name = datetime.now().strftime('%d-%m-%Y %H.%M')
txt_dir = "txt/"
txt_path = f"{txt_dir}{txt_name}.txt"
os.makedirs(os.path.dirname(txt_path), exist_ok=True)

# ID Room Configuration
id_room = 0

# Transcription Object Class


class AWSTranscription(TranscriptResultStreamHandler):
    def __init__(self, stream, websocket: WebSocket):
        super().__init__(stream)
        self.ws = websocket
        self.output = ""
        self.url_log = "http://192.168.1.50:19110/api/sac/log"
        self.txt_file = open(txt_path, "a", encoding="utf-8")
        logger.info("Txt output file has been created")

        self.prev_output = ""

        # TIMER
        self.marked_timer = datetime.now()
        logger.info(f"Marked timer : {self.marked_timer.strftime('%H:%M')}")

    async def handle_transcript_event(self, event: TranscriptEvent):
        try:
            for result in event.transcript.results:
                if result.is_partial:
                    for alt in result.alternatives:
                        self.output = alt.transcript.strip().lower()
                        if self.ws:
                            await self.ws.send_text("listening")
                else:
                    if self.output != "" and self.prev_output != self.output:
                        if self.ws:
                            time = datetime.now().strftime('%d-%m-%Y %H:%M')
                            await self.ws.send_json({
                                "datetime": time,
                                "transcription": self.output
                            })

                            if datetime.now() >= (self.marked_timer + timedelta(hours=3, minutes=30)):
                                logger.warning(
                                    "3 hours timer is on. Refreshing...")
                                self.marked_timer = datetime.now()
                                logger.info(
                                    f"Marked timer updated : {self.marked_timer.strftime('%H:%M')}")
                                await self.ws.send_json({
                                    "status": "warning",
                                    "massage": "3 hours timer is on. Refreshing..."
                                })

                        # Asynchronous
                        asyncio.create_task(
                            self.handle_db_logging(self.output))
                        asyncio.create_task(self.handle_db_output(self.output))

                        # Synchronous
                        # await self.handle_db_logging()
                        # await self.handle_db_output()

                        await self.handle_txt_output()

                        self.prev_output = self.output

        except ConnectionFailure as e:
            logger.error(f'Error saving data to mongoDB: {e}')
        except Exception as e:
            logger.exception(f"Error while handling transcript event {e}")
        except requests.exceptions.HTTPError as e:
            logger.warning(f"HTTP error occurred: {e}")
            pass
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Connection error occurred: {e}")
            pass
        except requests.exceptions.Timeout as e:
            logger.warning(f"Timeout error occurred: {e}")
            pass
        except requests.exceptions.RequestException as e:
            logger.warning(f"An error occurred: {e}")
            pass

    async def handle_db_logging(self, output):
        global id_room

        data = {
            "raw_input": output,
            "id_room": str(id_room)
        }

        response = requests.post(self.url_log, data=data, timeout=30.0)
        response.raise_for_status()

    async def handle_db_output(self, output):
        date = datetime.now().strftime('%d-%m-%Y')
        time = datetime.now().strftime('%H:%M:%S')

        coll_data.insert_one({
            "date": date,
            "time": time,
            "transcript": output
        })

    async def handle_txt_output(self):
        try:
            self.txt_file.write(self.output + "\n")
            self.txt_file.flush()
        except:
            self.txt_file.close()
            logger.error("Error while writing into Txt output.")

    def close_txt_output(self):
        self.txt_file.close()
        logger.info("Txt output file has been closed")


# Audio Transcription
async def audio_transcription(websocket: WebSocket, source: str = "mic"):
    client = TranscribeStreamingClient(region="us-east-1")

    stream = await aws_connection(client)

    while not stream:
        await websocket.send_json({"error": "Failed to connect to Amazon Transcribe service. Reconnecting..."})
        stream = await aws_connection(client)
        await asyncio.sleep(5)

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
                with stream:
                    while True:
                        indata, status = await input_queue.get()
                        yield indata, status

            async def send_audio():
                async for chunk, status in audio_source():
                    await stream.input_stream.send_audio_event(audio_chunk=chunk)
                await stream.input_stream.end_stream()

        elif source == "browser":
            async def send_audio():
                while True:
                    audio_chunk = await websocket.receive_bytes()
                    await stream.input_stream.send_audio_event(audio_chunk=audio_chunk)

        await asyncio.gather(send_audio(), handler.handle_events())

    except (ServiceUnavailableException, UnknownServiceException, BadRequestException,
            LimitExceededException, InternalFailureException,
            ConflictException, SerializationException) as e:
        logger.warning(f"Error starting transcription stream {e}")
        logger.warning(f"Restrarting connection...")
        await websocket.send_json({"error": "Transcription connection error"})

    except WebSocketDisconnect:
        logger.warning("WebSocket disconnected")
        await stream.input_stream.end_stream()

    except Exception as e:
        handler.close_txt_output()
        logger.exception(f"Unexpected error during transcription {e}")

# AWS Connection


async def aws_connection(client):
    try:
        stream = await client.start_stream_transcription(
            language_code="id-ID",
            media_sample_rate_hz=16000,
            media_encoding="pcm",
        )
        logger.info(
            f"Started transcription stream successfully on attempt {attempt + 1}")
        return stream

    except (ServiceUnavailableException, UnknownServiceException, BadRequestException,
            LimitExceededException, InternalFailureException,
            ConflictException, SerializationException) as e:
        logger.warning(f"Error starting transcription stream {e}")
        logger.warning(
            "Retrying in {delay} seconds... Attempt {attempt}/{retries}")
        return None


# Root Endpoints (Testing)
@app.get("/")
def root():
    logger.info("Root endpoint accessed")
    return {"message": "Hello, World!"}


# Microphone Audio Endpoints
@app.websocket("/mic-transcribe")
async def mic_transcription(websocket: WebSocket):
    await websocket.accept()
    try:
        logger.info("Client connected for microphone transcription")
        await audio_transcription(websocket, source="mic")
    except WebSocketDisconnect:
        logger.warning("Client disconnected (microphone transcription)")
    except Exception as e:
        logger.error(f"Unexpected error in mic transcription {e}")


# Browser Audio Endpoints
@app.websocket("/aws-browser-transcribe")
async def browser_transcription(websocket: WebSocket):
    await websocket.accept()
    try:
        logger.info("Client connected for browser transcription")
        await audio_transcription(websocket, source="browser")
    except WebSocketDisconnect:
        logger.warning("Client disconnected (browser transcription)")
    except Exception as e:
        logger.error(f"Unexpected error in browser transcription {e}")


# Summarizer Variable
start_datetime = " "
end_datetime = " "
transcript = " "

# Preview Endpoints


@app.post("/preview")
async def preview_ws(start_datetime: str = Form(...), end_datetime: str = Form(...)):
    try:
        if True:
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

            transcripts = coll_data.find({
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
                transcripts = coll_data.find({
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

                transcript = " ".join([doc["transcript"]
                                      for doc in transcript_list])

                prompt_indo = "Tolong buatlah kesimpulan dari kalimat ini menggunakan bahasa indonesia dengan struktur per poin : \n"

                async with httpx.AsyncClient() as client:
                    data = {
                        "raw_input": (None, prompt_indo + transcript),
                        "id_room": (None, "0"),
                        "raw_start": (None, start_datetime.strftime('%d-%m-%Y %H:%M')),
                        "raw_end": (None, end_datetime.strftime('%d-%m-%Y %H:%M'))
                    }

                    try:
                        response = await client.post(summarizer_url, data=data)
                        response.raise_for_status()

                        result = response.json()
                        summary = result.get('result', {}).get(
                            'response', "Summary not found")

                        formatmd = summary.replace("\n", "").replace("\t", "")
                        save = {
                            "timestamp": datetime.now().strftime('%d-%m-%Y'),
                            "summary": formatmd
                        }
                        coll_summary.insert_one(save)

                        formathtml = summary.replace(
                            "\n", "<br>").replace("\t", "<br>")
                        htmlsummary = markdown.markdown(formathtml)

                        await websocket.send_json({
                            "status": "success",
                            "summary": htmlsummary
                        })

                    except httpx.HTTPStatusError as e:
                        logger.error(f"Error sending data to summarizer: {e}")
                        logger.error(f"Response content: {e.response.text}")
                        await websocket.send_json({
                            "status": "error",
                            "message": f"Summarizer API error: {e.response.text}"
                        })

                    except Exception as e:
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
        logger.error(f"ERROR : \n {e}")
