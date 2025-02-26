// src/index.ts
import express, { Express, Request, Response } from "express";
import dotenv from "dotenv";
import http from "http";
import path from "path";
import cors from "cors";
import {
  TranscribeStreamingClient,
  StartStreamTranscriptionCommand,
} from "@aws-sdk/client-transcribe-streaming";
import { Server } from "socket.io";

/*
 * Load up and parse configuration details from
 * the `.env` file to the `process.env`
 * object of Node.js
 */
dotenv.config();

/*
 * Create an Express application and get the
 * value of the PORT environment variable
 * from the `process.env`
 */
const app: Express = express();
app.use(cors({ origin: "*" }));

const server = http.createServer(app);
const io = new Server(server, {
  cors: {
    origin: "*",
    methods: ["GET", "POST"],
  },
});

// Set EJS as the view engine
app.set("view engine", "ejs");

// Define the directory where your HTML files (views) are located
app.set("views", path.join(__dirname, "fe"));

// Optionally, you can define a static files directory (CSS, JS, images, etc.)
app.use(express.static(path.join(__dirname, "fe")));

/* Define a route for the root path ("/")
 using the HTTP GET method */
app.get("/", (req: Request, res: Response) => {
  res.send("Express + Typescript Server");
});

const transcribeClient = new TranscribeStreamingClient({
  region: "us-east-1", // Ensure this matches your AWS region
});

io.of("aws-browser-transcribe").on("connection", (socket) => {
  console.log("A user connected");

  let audioStream;
  let lastTranscript = "";
  let isTranscribing = false;

  socket.on("startTranscription", async () => {
    console.log("Starting transcription");
    isTranscribing = true;
    let buffer = Buffer.from("");

    audioStream = async function* () {
      while (isTranscribing) {
        const chunk = await new Promise((resolve) =>
          socket.once("audioData", resolve),
        );
        if (chunk === null) break;
        buffer = Buffer.concat([buffer, Buffer.from(chunk as any)]);
        console.log("Received audio chunk, buffer size:", buffer.length);

        while (buffer.length >= 1024) {
          yield { AudioEvent: { AudioChunk: buffer.slice(0, 1024) } };
          buffer = buffer.slice(1024);
        }
      }
    };

    const command = new StartStreamTranscriptionCommand({
      LanguageCode: "id-ID",
      MediaSampleRateHertz: 44100,
      MediaEncoding: "pcm",
      AudioStream: audioStream(),
    });

    try {
      console.log("Sending command to AWS Transcribe");
      const response = await transcribeClient.send(command);
      console.log("Received response from AWS Transcribe");

      if (response.TranscriptResultStream) {
        for await (const event of response.TranscriptResultStream) {
          if (!isTranscribing) break;
          if (event.TranscriptEvent) {
            console.log(
              "Received TranscriptEvent:",
              JSON.stringify(event.TranscriptEvent),
            );
            const results = event?.TranscriptEvent?.Transcript?.Results as any;
            if (results) {
              if (results.length > 0 && results[0].Alternatives.length > 0) {
                const transcript = results[0].Alternatives[0].Transcript;
                const isFinal = !results[0].IsPartial;

                if (isFinal) {
                  console.log("Emitting final transcription:", transcript);
                  socket.emit("transcription", {
                    text: transcript,
                    isFinal: true,
                  });
                  lastTranscript = transcript;
                } else {
                  const newPart = transcript.substring(lastTranscript.length);
                  if (newPart.trim() !== "") {
                    console.log("Emitting partial transcription:", newPart);
                    socket.emit("transcription", {
                      text: newPart,
                      isFinal: false,
                    });
                  }
                }
              }
            }
          }
        }
      }
    } catch (error) {
      console.error("Transcription error:", error);
      if (error instanceof Error) {
        socket.emit("error", "Transcription error occurred: " + error.message);
      }
    }
  });

  socket.on("audioData", (data) => {
    if (isTranscribing) {
      console.log("Received audioData event, data size:", data.byteLength);
      socket.emit("audioData", data);
    }
  });

  socket.on("stopTranscription", () => {
    console.log("Stopping transcription");
    isTranscribing = false;
    audioStream = null;
    lastTranscript = "";
  });

  socket.on("disconnect", () => {
    console.log("User disconnected");
    isTranscribing = false;
    audioStream = null;
  });
});

const port = process.env.PORT || 8000;
/* Start the Express app and listen
 for incoming requests on the specified port */
server.listen(port, () => {
  console.log(`[server]: Server is running at http://localhost:${port}`);
});
