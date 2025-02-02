import os
import asyncio
import httpx
import uvicorn
import sounddevice
import markdown
from loguru import logger
from bson import ObjectId
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from pymongo.errors import ConnectionFailure
from fastapi import FastAPI, WebSocket
from fastapi.websockets import WebSocketDisconnect
from amazon_transcribe.model import TranscriptEvent
from amazon_transcribe.client import TranscribeStreamingClient, TranscribeStreamingClientConfig
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

# MongoDB Atlas Configuration
load_dotenv()

# client = MongoClient("", server_api=ServerApi('1'))       # MongoDB atlas     (cloud)
# client = MongoClient("mongodb://localhost:27017/")        # MongoDB compass   (local)

db = client.spil
coll_data = db.data
coll_summary = db.summary

# Logging Configuration
log_name = "app.log"
log_dir  = "app/"
log_path = log_name+log_dir
os.makedirs(os.path.dirname(log_path), exist_ok=True)
logger.add(log_path, rotation="10 MB", retention="30 days", compression="zip")

# Txt Configuration
txt_name = datetime.now().strftime('%d-%m-%Y %H.%M')
txt_dir  = "txt/"
txt_path = f"{txt_dir}{txt_name}.txt"
os.makedirs(os.path.dirname(txt_path), exist_ok=True)


# Transcription Object Class
class AWSTranscription(TranscriptResultStreamHandler):                     
    def __init__(self, stream, websocket: WebSocket):
        super().__init__(stream)
        self.ws = websocket
        self.output = ""
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
            logger.exception(f"Error while handling transcript event {e}")

    async def handle_db_output(self):
        try:
            date = datetime.now().strftime('%d-%m-%Y')
            time = datetime.now().strftime('%H:%M')

            coll_data.insert_one({
                "date":date,
                "time": time,
                "transcript": self.output
            })

        except ConnectionFailure as e:
            logger.error(f'Error saving data to mongoDB: {e}')
       
    async def handle_txt_output(self):
        try:
            self.txt_file.write(self.output + "\n")
            self.txt_file.flush()
        except Exception as e:
            self.txt_file.close()
            logger.exception("Error while writing transcript to txt file {e}")

    def close_txt_output(self):
        try:
            self.txt_file.close()
            logger.info("Txt output file has been closed")
        except Exception as e:
            logger.exception("Error while closing txt file {e}")


# Audio Transcription
async def audio_transcription(websocket: WebSocket, source: str = "mic"):
    config = TranscribeStreamingClientConfig(connection_timeout=10, read_timeout=30)
    client = TranscribeStreamingClient(region="us-east-1", config=config)

    stream = await start_transcription_with_retries(client)

    if not stream:
        await websocket.send_json({"error": "Failed to connect to Amazon Transcribe service after multiple attempts."})
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

    except WebSocketDisconnect:
        logger.warning("WebSocket disconnected")
        await stream.input_stream.end_stream()

    except Exception as e:
        handler.close_txt_output()
        logger.exception(f"Unexpected error during transcription {e}")
        

async def reconnect(client, retries=5, delay=5):
    attempt = 0
    while attempt < retries:
        try:
            stream = await client.start_stream_transcription(
                language_code="id-ID",
                media_sample_rate_hz=16000,
                media_encoding="pcm",
            )
            logger.info(f"Started transcription stream successfully on attempt {attempt + 1}")
            return stream

        except ServiceUnavailableException as e:
            attempt += 1
            logger.warning(f"Service unavailable, retrying in {delay} seconds... Attempt {attempt}/{retries}")
            await asyncio.sleep(delay)

        except (UnknownServiceException, BadRequestException, 
                LimitExceededException, InternalFailureException,
                ConflictException, SerializationException) as e:
            logger.error(f"Error starting transcription stream {e}")
            raise

    logger.error("Failed to start transcription after multiple attempts.")
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
end_datetime   = " "
transcript     = " "


# Preview Endpoints
@app.websocket("/preview")
async def preview(websocket: WebSocket):
    await websocket.accept()
    logger.info("Client connected to summarizer endpoint")

    try:
        while True:
            global transcript, start_datetime, end_datetime

            data = await websocket.receive_json()
            start_time = data.get("start_datetime")
            end_time = data.get("end_datetime")

            start_datetime = datetime.strptime(start_time, '%d-%m-%Y %H:%M')
            end_datetime = datetime.strptime(end_time, '%d-%m-%Y %H:%M')

            date = start_datetime.strftime('%d-%m-%Y')
            transcripts = coll_data.find({
                "date": date,
                "time": {"$gte": start_datetime.strftime('%H:%M:%S'), "$lte": end_datetime.strftime('%H:%M:%S')}
                }, {"_id": 0, "transcript": 1})

            transcript_list = list(transcripts)

            if not transcript_list:
                logger.warning(f"No data found for time range {start_datetime} - {end_datetime}")
                await websocket.send_json({
                    "status": "empty",
                    "message": "No transcripts found within the provided time range."
                })
                continue
            
            transcript = " ".join([doc["transcript"] for doc in transcript_list])

            await websocket.send_json({
                "status": "success",
                "transcript": transcript
            })

    except WebSocketDisconnect:
        logger.warning("Client disconnected from summarizer endpoint")
    
    except ValueError as ve:
        logger.error(f"Error: {ve}")
        await websocket.send_json({
            "status": "error",
            "message": str(ve)
        })
    
    except Exception as e:
        logger.error(f"Unexpected error in summarizer {e}")
        await websocket.send_json({
            "status": "error",
            "message": "An unexpected error occurred."
        })


# Summarizer Endpoints
@app.websocket("/summarizer")
async def summarizer(websocket: WebSocket):
    summarizer_url = "http://192.168.1.50:19110/api/sac/summarize"  
    logger.info("Client connected to summarizer endpoint")
    try:
        global transcript, start_datetime, end_datetime
        prompt_indo = "Tolong buatlah kesimpulan dari kalimat berikut menggunakan bahasa indonesia : \n"
        
        async with httpx.AsyncClient(TimeoutError=30.0) as client:
            data = {
                "raw_input": (None, prompt_indo + transcript),  
                "id_room": (None, "0"), 
                "raw_start": (None, start_datetime.strftime('%d-%m-%Y %H:%M')),  
                "raw_end": (None, end_datetime.strftime('%d-%m-%Y %H:%M'))  
            }

            response = await client.post(summarizer_url, files=data)
            response.raise_for_status()  
            
            result = response.json()
            summary = result.get('result', {}).get('response', "Summary not found")

        # Send summary into Apps
        formathtml = summary.replace("\n", "<br>").replace("\t", "<br>")
        htmlsummary = markdown.markdown(formathtml)

        await websocket.send_json({
            "status": "success",
            "summary": htmlsummary
        })

        # Save summary into MongoDB
        formatmd = summary.replace("\n", "").replace("\t", "")
        save = {
            "timestamp": datetime.now().strftime('%d-%m-%Y'),
            "summary": formatmd
        }
        coll_summary.insert_one(save)

    except WebSocketDisconnect:
        logger.warning("Client disconnected from summarizer endpoint")

    except ConnectionFailure as e:
        logger.error(f'Error saving data to mongoDB: {e}')
        await websocket.send_json({
            "status": "error",
            "message": str(e)
        })
                
    except httpx.HTTPStatusError as e:
        logger.error(f"Error sending data to summarizer {e}")
        logger.error(f"Response content: {e.response.text}")  
        await websocket.send_json({
            "status": "error",
            "message": f"Summarizer API error: {e.response.text}"
        })
    
    except Exception as e:
        logger.error(f"Unexpected error in summarizer {e}")
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