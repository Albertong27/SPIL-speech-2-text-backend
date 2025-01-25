
from flask import Flask, request, jsonify
from moviepy.editor import VideoFileClip
import os

app = Flask(__name__)

class MP4ToMP3Converter:
    def __init__(self, work_path="/home/magang/MAGANG2/convertvidtomp3"):
        """
        Inisialisasi dengan path kerja untuk input dan output file.
        """
        os.makedirs(work_path, exist_ok=True)  # Membuat direktori jika belum ada
        self.work_path = work_path

    def convert(self, file_name):
        """
        Mengonversi file MP4 ke MP3.

        Args:
            file_name (str): Nama file MP4 (hanya nama, tanpa path).

        Returns:
            str: Path file MP3 yang dihasilkan.
        """
        try:
            input_path = os.path.join(self.work_path, file_name)
            output_path = os.path.join(self.work_path, os.path.splitext(file_name)[0] + ".mp3")

            # Validasi apakah file input ada
            if not os.path.exists(input_path):
                raise FileNotFoundError(f"File '{input_path}' tidak ditemukan.")

            if not file_name.lower().endswith(".mp4"):
                raise ValueError("File harus dalam format MP4.")

            # Proses konversi
            print(f"Mengonversi {file_name} ke {output_path}...")
            with VideoFileClip(input_path) as clip:
                with clip.audio as audio:
                    audio.write_audiofile(output_path, bitrate="320k")

            print(f"Audio berhasil disimpan di: {output_path}")
            return output_path
        except Exception as e:
            print(f"Error: {e}")
            return None

# Inisialisasi converter dengan direktori kerja
converter = MP4ToMP3Converter(work_path="/home/magang/MAGANG2/convertvidtomp3")

@app.route('/convert2', methods=['POST'])
def convert_mp4_to_mp3():
    """
    API endpoint untuk mengonversi file MP4 ke MP3.

    Request Body (form-data):
        - Key: file
        - Value: File MP4 yang akan dikonversi (dalam bentuk file upload).
        - Key: list
        - Value: "true" jika ingin mendapatkan daftar file output di direktori kerja.

    Returns:
        JSON response yang menunjukkan status sukses atau gagal.
    """
    is_list_requested = request.form.get('list', 'false').lower() == 'true'

    # Jika permintaan daftar file MP3, tampilkan daftar file MP3
    if is_list_requested:
        try:
            files = [f for f in os.listdir(converter.work_path) if f.endswith('.mp3')]
            return jsonify({"message": "Daftar file MP3:", "files": files}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    if 'file' not in request.files:
        return jsonify({"error": "File MP4 diperlukan."}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({"error": "Nama file tidak valid."}), 400

    try:
        # Simpan file ke direktori kerja
        file_path = os.path.join(converter.work_path, file.filename)
        file.save(file_path)

        # Konversi file MP4 ke MP3
        output_path = converter.convert(file.filename)

        # Ambil daftar file MP3 di direktori kerja
        files = [f for f in os.listdir(converter.work_path) if f.endswith('.mp3')]

        if output_path:
            return jsonify({
                "message": "Konversi berhasil.",
                "output_file": output_path,
                "files": files
            }), 200
        else:
            return jsonify({"error": "Gagal mengonversi file."}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host='127.0.0.1', port=5000)
