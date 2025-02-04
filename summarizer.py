import uvicorn
import markdown
import requests
from datetime import datetime
from pydantic import BaseModel
from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from pymongo.errors import ConnectionFailure

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

client = MongoClient("", server_api=ServerApi('1'))         # MongoDB atlas     (cloud)
# client = MongoClient("mongodb://localhost:27017/")        # MongoDB compass   (local)

db = client.spil
coll_data = db.data
coll_summary = db.summary

# Requests Variable 
class Time(BaseModel):
    start_datetime: str
    end_datetime: str

# Variable
id_room = 0
start_datetime = " "
end_datetime   = " "
transcript     = " "

# Preview Endpoints 
@app.post("/preview")
def preview_request(time_data: Time):
    try:
        global start_datetime, end_datetime, transcript

        start_time = time_data.start_datetime
        end_time = time_data.end_datetime

        start_datetime = datetime.strptime(start_time, '%d-%m-%Y %H:%M')
        end_datetime = datetime.strptime(end_time, '%d-%m-%Y %H:%M')

        date = start_datetime.strftime('%d-%m-%Y')
        transcripts = coll_data.find({
            "date": date,
            "time": {"$gte": start_datetime.strftime('%H:%M:%S'), "$lte": end_datetime.strftime('%H:%M:%S')}
            }, {"_id": 0, "transcript": 1})

        transcript_list = list(transcripts)

        if not transcript_list:
            return {
                "status": "empty",
                "message": "No transcripts found within the provided time range."
            }
        
        transcript = " ".join([doc["transcript"] for doc in transcript_list])

        return {
            "status": "success",
            "transcript": transcript
        }
    
    except ConnectionFailure as e:
        return {
            "status": "error",
            "massage": f"Database error : {e}"
        }

    except Exception as e:
        return {
            "status": "error",
            "massage": f"Unexpected error : {e}"
        }

# Summarizer Endpoints
@app.post("/summarizer")
def summarizer_request():
    summarizer_url = "http://192.168.1.50:19110/api/sac/summarize"  
    try:
        global transcript, start_datetime, end_datetime, id_room
        prompt_indo = "Tolong buatlah kesimpulan dari kalimat berikut menggunakan bahasa indonesia : \n"

        data = {
                "raw_input": (None, prompt_indo + transcript),  
                "id_room": (None, str(id_room)), 
                "raw_start": (None, start_datetime.strftime('%d-%m-%Y %H:%M')),  
                "raw_end": (None, end_datetime.strftime('%d-%m-%Y %H:%M'))  
            }

        response = requests.post(summarizer_url, data=data)
        response.raise_for_status()

        result = response.json()
        summary = result.get('result', {}).get('response', "Summary not found")

        formathtml = summary.replace("\n", "<br>").replace("\t", "<br>")
        htmlsummary = markdown.markdown(formathtml)

        formatmd = summary.replace("\n", "").replace("\t", "")
        save = {
            "timestamp": datetime.now().strftime('%d-%m-%Y'),
            "summary": formatmd
        }
        coll_summary.insert_one(save)

        return {
            "status": "success",
            "summary": htmlsummary
        }
    
    except ConnectionFailure as e:
        return {
            "status": "error",
            "massage": f"Database error : {e}"
        }

    except Exception as e:
        return {
            "status": "error",
            "massage": f"Unexpected error : {e}"
        }


if __name__ == '__main__':
    uvicorn.run("server_summarizer:app", host="127.0.0.1", port=8001)