from flask import Flask, request, jsonify
from yt_dlp import YoutubeDL
import os

app = Flask(__name__)

class YouTubeToMp3Converter:
    def __init__(self, output_path):
        """
        Initialize the converter with a specific output path.

        Args:
            output_path (string): Path where MP3 files will be saved.
        """
        self.output_path = output_path

        # Ensure the output directory exists
        if not os.path.exists(self.output_path):
            os.makedirs(self.output_path)

    def download_as_mp3(self, url):
        """
        Download a YouTube video as an MP3 file.

        Args:
            url (string): YouTube video URL
        """
        options = {
            'format': 'bestaudio/best',
            'keepvideo': False,
            'outtmpl': f'{self.output_path}/%(title)s.%(ext)s',
            'noplaylist': True,  # Ensure only a single video is downloaded
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            # Add headers to mimic a browser request
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
            },
        }

        with YoutubeDL(options) as ydl:
            ydl.download([url])

@app.route('/converttomp3', methods=['POST'])
def convert_video():
    """
    Flask route to convert YouTube video to MP3.
    """
    data = request.form
    video_url = data.get('url')

    if not video_url:
        return jsonify({"error": "URL tidak disediakan"}), 400

    output_directory = '/home/magang/MAGANG2/convertvidtomp3'
    converter = YouTubeToMp3Converter(output_directory)

    try:
        converter.download_as_mp3(video_url)
        return jsonify({"message": "Download selesai!", "output_directory": output_directory}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host='127.0.0.1', port=5000)
