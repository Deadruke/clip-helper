import os
import uuid
import asyncio
import threading
import subprocess
from pathlib import Path

from flask import Flask, send_from_directory, request, jsonify
from telegram import BotCommand, MenuButtonWebApp, WebAppInfo
from telegram.ext import Application, CommandHandler

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")

UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

web = Flask(__name__, static_folder="templates")


@web.route("/")
def index():
    return send_from_directory("templates", "index.html")


@web.route("/api/upload", methods=["POST"])
def upload_video():

    try:
        video = request.files.get("video")
        chat_id = request.form.get("chat_id")

        quality = int(request.form.get("quality", 720))
        video_format = request.form.get("format", "vertical")
        ai = request.form.get("ai", "false") == "true"

        if not video:
            return jsonify({
                "ok": False,
                "error": "Видео не получено"
            }), 400

        if not chat_id:
            return jsonify({
                "ok": False,
                "error": "Chat ID не получен"
            }), 400

        file_id = uuid.uuid4().hex

        input_path = UPLOAD_DIR / f"{file_id}.mp4"
        output_path = OUTPUT_DIR / f"{file_id}_out.mp4"

        video.save(input_path)

        if not input_path.exists():
            raise Exception("Не удалось сохранить видео")

        # Обрабатываем в отдельном потоке,
        # чтобы Flask не зависал
        threading.Thread(
            target=process_and_send,
            args=(
                input_path,
                output_path,
                chat_id,
                quality,
                video_format,
                ai
            ),
            daemon=True
        ).start()

        return jsonify({
            "ok": True,
            "message": "Видео отправлено на обработку"
        })

    except Exception as e:

        print("UPLOAD ERROR:", e)

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


def process_and_send(
    input_path,
    output_path,
    chat_id,
    quality,
    video_format,
    ai
):

    try:

        filters = []

        # 9:16
        if video_format == "vertical":

            width = int(quality * 9 / 16)
            width -= width % 2

            filters.append(
                f"scale={width}:{quality}:"
                "force_original_aspect_ratio=decrease"
            )

            filters.append(
                f"pad={width}:{quality}:(ow-iw)/2:(oh-ih)/2"
            )

        else:

            filters.append(
                f"scale=-2:{quality}"
            )

        # Улучшение
        if ai:
            filters.append(
                "unsharp=5:5:0.8:5:5:0.0"
            )

        filter_string = ",".join(filters)

        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",

            "-i",
            str(input_path),

            "-vf",
            filter_string,

            "-c:v",
            "libx264",

            "-preset",
            "veryfast",

            "-crf",
            "20",

            "-pix_fmt",
            "yuv420p",

            "-c:a",
            "aac",

            "-b:a",
            "128k",

            "-movflags",
            "+faststart",

            str(output_path)
        ]

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if result.returncode != 0:

            raise Exception(
                result.stderr[-3000:]
            )

        if not output_path.exists():
            raise Exception(
                "FFmpeg не создал видео"
            )

        # Отправляем обратно в Telegram
        asyncio.run(
            send_video_to_user(
                chat_id,
                output_path
            )
        )

    except Exception as e:

        print("\n===== PROCESS ERROR =====")
        print(e)
        print("=========================\n")

    finally:

        try:
            input_path.unlink(missing_ok=True)
        except Exception:
            pass

        try:
            output_path.unlink(missing_ok=True)
        except Exception:
            pass


async def send_video_to_user(chat_id, output_path):

    from telegram import Bot

    bot = Bot(BOT_TOKEN)

    with open(output_path, "rb") as video:

        await bot.send_video(
            chat_id=int(chat_id),
            video=video,
            supports_streaming=True,
            caption="✅ ClipForge готов!"
        )


async def start(update, context):

    await update.message.reply_text(
        "🎬 Открой ClipForge через кнопку меню "
        "и загрузи видео."
    )


async def setup_bot(application):

    await application.bot.set_my_commands([
        BotCommand(
            "start",
            "Запустить ClipForge"
        )
    ])

    await application.bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="ClipForge",
            web_app=WebAppInfo(
                url=WEBAPP_URL
            )
        )
    )

    print("Mini App:", WEBAPP_URL)


def run_web():

    port = int(
        os.getenv("PORT", 10000)
    )

    web.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )


def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN не найден"
        )

    if not WEBAPP_URL:
        raise RuntimeError(
            "WEBAPP_URL не найден"
        )

    threading.Thread(
        target=run_web,
        daemon=True
    ).start()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(setup_bot)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    print("ClipForge запущен!")

    application.run_polling()


if __name__ == "__main__":
    main()
