from flask import Flask, request, render_template_string, send_file
import os
import subprocess
import uuid

app = Flask(__name__)

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Clip Helper</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: #111;
            color: white;
            max-width: 700px;
            margin: 40px auto;
            padding: 20px;
        }

        .box {
            background: #1c1c1c;
            padding: 25px;
            border-radius: 15px;
        }

        h1 {
            margin-top: 0;
        }

        input, select, button {
            width: 100%;
            padding: 12px;
            margin-top: 10px;
            margin-bottom: 18px;
            border-radius: 8px;
            border: none;
            box-sizing: border-box;
        }

        button {
            background: #fff;
            cursor: pointer;
            font-weight: bold;
        }

        label {
            display: block;
            margin-top: 10px;
        }
    </style>
</head>

<body>
    <div class="box">
        <h1>🎬 Clip Helper</h1>
        <p>Помощник для создания нарезок</p>

        <form action="/process" method="post" enctype="multipart/form-data">

            <label>Видео:</label>
            <input type="file" name="video" accept="video/*" required>

            <label>Качество:</label>
            <select name="quality">
                <option value="144">144p</option>
                <option value="360">360p</option>
                <option value="480">480p</option>
                <option value="720" selected>720p HD</option>
                <option value="1080">1080p Full HD</option>
            </select>

            <label>Субтитры:</label>
            <select name="subtitles">
                <option value="none">Без субтитров</option>
                <option value="basic" selected>Обычные</option>
                <option value="bold">Жирные</option>
            </select>

            <label>
                <input type="checkbox" name="ai_enhance">
                🤖 AI-улучшение качества
            </label>

            <label>
                <input type="checkbox" name="vertical" checked>
                📱 Формат 9:16
            </label>

            <button type="submit">🚀 Обработать видео</button>
        </form>
    </div>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/process", methods=["POST"])
def process():
    video = request.files.get("video")

    if not video:
        return "Видео не загружено", 400

    quality = request.form.get("quality", "720")
    subtitles = request.form.get("subtitles", "none")
    ai_enhance = request.form.get("ai_enhance") == "on"
    vertical = request.form.get("vertical") == "on"

    job_id = str(uuid.uuid4())

    input_path = os.path.join(
        UPLOAD_DIR,
        job_id + os.path.splitext(video.filename)[1]
    )

    output_path = os.path.join(
        OUTPUT_DIR,
        job_id + ".mp4"
    )

    video.save(input_path)

    try:
        create_video(
            input_path,
            output_path,
            quality,
            subtitles,
            ai_enhance,
            vertical
        )

        return send_file(
            output_path,
            as_attachment=True,
            download_name="clip.mp4"
        )

    except Exception as e:
        return f"Ошибка обработки: {str(e)}", 500


def create_video(
    input_path,
    output_path,
    quality,
    subtitles,
    ai_enhance,
    vertical
):
    height = int(quality)

    if vertical:
        width = round(height * 9 / 16)
        scale = f"scale={width}:{height}:force_original_aspect_ratio=decrease"
        pad = f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
    else:
        scale = f"scale=-2:{height}"
        pad = None

    filters = [scale]

    if pad:
        filters.append(pad)

    # Улучшение изображения.
    # Позже сюда подключим полноценный AI upscaler.
    if ai_enhance:
        filters.append("unsharp=5:5:1.0:5:5:0.0")

    video_filter = ",".join(filters)

    command = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-vf", video_filter,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        output_path
    ]

    subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
