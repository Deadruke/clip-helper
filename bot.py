import os
import json
import uuid
import asyncio
import threading
import subprocess
from pathlib import Path

from flask import Flask, send_from_directory, request, jsonify

from telegram import (
    Bot,
    BotCommand,
    MenuButtonWebApp,
    WebAppInfo,
    LabeledPrice,
    Update,
)

from telegram.ext import (
    Application,
    CommandHandler,
    PreCheckoutQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")

UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
DATA_FILE = Path("data.json")

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

web = Flask(__name__, static_folder="templates")

# =========================================================
# DATA
# =========================================================

data_lock = threading.Lock()


def load_data():
    if not DATA_FILE.exists():
        return {
            "users": {}
        }

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "users": {}
        }


def save_data(data):
    temp_file = Path("data.json.tmp")

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    temp_file.replace(DATA_FILE)


def ensure_user(user_id):
    user_id = str(user_id)

    with data_lock:
        data = load_data()

        if user_id not in data["users"]:
            data["users"][user_id] = {
                "premium": False,
                "processed": 0,
                "processing": [],
                "history": []
            }

            save_data(data)

        return data["users"][user_id]


def add_processing(user_id, job_id, filename):
    user_id = str(user_id)

    with data_lock:
        data = load_data()

        ensure = data["users"].setdefault(
            user_id,
            {
                "premium": False,
                "processed": 0,
                "processing": [],
                "history": []
            }
        )

        ensure["processing"].append({
            "id": job_id,
            "filename": filename,
            "status": "processing"
        })

        save_data(data)


def finish_processing(
    user_id,
    job_id,
    filename,
    success=True
):
    user_id = str(user_id)

    with data_lock:
        data = load_data()

        user = data["users"].setdefault(
            user_id,
            {
                "premium": False,
                "processed": 0,
                "processing": [],
                "history": []
            }
        )

        user["processing"] = [
            item
            for item in user.get("processing", [])
            if item.get("id") != job_id
        ]

        if success:
            user["processed"] = user.get("processed", 0) + 1

            user.setdefault("history", []).insert(
                0,
                {
                    "id": job_id,
                    "filename": filename
                }
            )

            user["history"] = user["history"][:20]

        save_data(data)


# =========================================================
# MAIN PAGE
# =========================================================

@web.route("/")
def index():
    return send_from_directory(
        "templates",
        "index.html"
    )


# =========================================================
# USER INFO
# =========================================================

@web.route("/api/user", methods=["GET"])
def get_user():

    try:
        user_id = request.args.get("user_id")

        if not user_id:
            return jsonify({
                "ok": False,
                "error": "User ID не получен"
            }), 400

        user = ensure_user(user_id)

        return jsonify({
            "ok": True,
            "user_id": user_id,
            "premium": user.get("premium", False),
            "processed": user.get("processed", 0),
            "processing": user.get("processing", []),
            "history": user.get("history", [])
        })

    except Exception as e:

        print("USER ERROR:", e)

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


# =========================================================
# UPLOAD
# =========================================================

@web.route("/api/upload", methods=["POST"])
def upload_video():

    try:

        video = request.files.get("video")
        chat_id = request.form.get("chat_id")

        quality = int(
            request.form.get(
                "quality",
                720
            )
        )

        video_format = request.form.get(
            "format",
            "vertical"
        )

        subtitles = request.form.get(
            "subtitles",
            "off"
        )

        ai = (
            request.form.get(
                "ai",
                "false"
            ) == "true"
        )

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

        # -------------------------------------------------
        # CHECK USER
        # -------------------------------------------------

        user = ensure_user(chat_id)

        premium = user.get(
            "premium",
            False
        )

        # -------------------------------------------------
        # QUALITY LIMITS
        # -------------------------------------------------

        allowed_normal = [
            144,
            360,
            480,
            720,
            1080
        ]

        allowed_premium = [
            144,
            360,
            480,
            720,
            1080,
            1440,
            2160
        ]

        if premium:

            if quality not in allowed_premium:
                quality = 720

        else:

            if quality not in allowed_normal:
                quality = 720

            # Нельзя обычному пользователю
            # выбрать 2K/4K
            if quality > 1080:
                quality = 1080

        # -------------------------------------------------
        # SAVE VIDEO
        # -------------------------------------------------

        job_id = uuid.uuid4().hex

        input_path = (
            UPLOAD_DIR /
            f"{job_id}.mp4"
        )

        output_path = (
            OUTPUT_DIR /
            f"{job_id}_out.mp4"
        )

        original_filename = (
            video.filename
            or "video.mp4"
        )

        video.save(input_path)

        if not input_path.exists():
            raise Exception(
                "Не удалось сохранить видео"
            )

        add_processing(
            chat_id,
            job_id,
            original_filename
        )

        # -------------------------------------------------
        # START PROCESSING
        # -------------------------------------------------

        threading.Thread(
            target=process_and_send,
            args=(
                input_path,
                output_path,
                chat_id,
                quality,
                video_format,
                subtitles,
                ai,
                job_id,
                original_filename
            ),
            daemon=True
        ).start()

        return jsonify({
            "ok": True,
            "job_id": job_id,
            "message": "Видео отправлено на обработку"
        })

    except Exception as e:

        print("\n===== UPLOAD ERROR =====")
        print(e)
        print("========================\n")

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


# =========================================================
# PROCESS VIDEO
# =========================================================

def process_and_send(
    input_path,
    output_path,
    chat_id,
    quality,
    video_format,
    subtitles,
    ai,
    job_id,
    original_filename
):

    success = False

    try:

        filters_list = []

        # -------------------------------------------------
        # FORMAT
        # -------------------------------------------------

        if video_format == "vertical":

            width = int(
                quality * 9 / 16
            )

            width -= width % 2

            filters_list.append(
                f"scale={width}:{quality}:"
                "force_original_aspect_ratio=decrease"
            )

            filters_list.append(
                f"pad={width}:{quality}:"
                "(ow-iw)/2:(oh-ih)/2"
            )

        else:

            filters_list.append(
                f"scale=-2:{quality}"
            )

        # -------------------------------------------------
        # AI ENHANCEMENT
        # -------------------------------------------------

        if ai:

            # Пока это улучшение через FFmpeg.
            # Настоящий AI upscale будет отдельным модулем.
            filters_list.append(
                "unsharp=5:5:0.8:5:5:0.0"
            )

        filter_string = ",".join(
            filters_list
        )

        # -------------------------------------------------
        # FFMPEG
        # -------------------------------------------------

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

        # -------------------------------------------------
        # SEND TO TELEGRAM
        # -------------------------------------------------

        asyncio.run(
            send_video_to_user(
                chat_id,
                output_path,
                quality
            )
        )

        success = True

        print(
            f"Видео {job_id} успешно обработано"
        )

    except Exception as e:

        print("\n===== PROCESS ERROR =====")
        print(e)
        print("=========================\n")

        try:

            asyncio.run(
                send_error_to_user(
                    chat_id,
                    str(e)
                )
            )

        except Exception as send_error:

            print(
                "SEND ERROR:",
                send_error
            )

    finally:

        finish_processing(
            chat_id,
            job_id,
            original_filename,
            success
        )

        try:
            input_path.unlink(
                missing_ok=True
            )
        except Exception:
            pass

        try:
            output_path.unlink(
                missing_ok=True
            )
        except Exception:
            pass


# =========================================================
# SEND VIDEO
# =========================================================

async def send_video_to_user(
    chat_id,
    output_path,
    quality
):

    bot = Bot(
        BOT_TOKEN
    )

    with open(
        output_path,
        "rb"
    ) as video:

        await bot.send_video(
            chat_id=int(chat_id),
            video=video,
            supports_streaming=True,
            caption=(
                f"✅ ClipForge готов!\n"
                f"Качество: {quality}p"
            )
        )


# =========================================================
# SEND ERROR
# =========================================================

async def send_error_to_user(
    chat_id,
    error
):

    bot = Bot(
        BOT_TOKEN
    )

    await bot.send_message(
        chat_id=int(chat_id),
        text=(
            "❌ Не удалось обработать видео.\n\n"
            "Попробуй ещё раз."
        )
    )


# =========================================================
# PREMIUM PAYMENT
# =========================================================

@web.route(
    "/api/create-premium-invoice",
    methods=["POST"]
)
def create_premium_invoice():

    try:

        body = request.get_json(
            silent=True
        ) or {}

        user_id = body.get(
            "user_id"
        )

        if not user_id:

            return jsonify({
                "ok": False,
                "error": "User ID не получен"
            }), 400

        user = ensure_user(
            user_id
        )

        if user.get(
            "premium",
            False
        ):

            return jsonify({
                "ok": False,
                "error": "Premium уже активирован"
            }), 400

        async def create_invoice():

            bot = Bot(
                BOT_TOKEN
            )

            payload = (
                f"premium:{user_id}:"
                f"{uuid.uuid4().hex}"
            )

            prices = [
                LabeledPrice(
                    label="ClipForge Premium",
                    amount=50
                )
            ]

            invoice_link = (
                await bot.create_invoice_link(
                    title="ClipForge Premium",
                    description=(
                        "Premium доступ к 2K и 4K "
                        "обработке видео."
                    ),
                    payload=payload,
                    currency="XTR",
                    prices=prices
                )
            )

            return invoice_link

        invoice_link = asyncio.run(
            create_invoice()
        )

        return jsonify({
            "ok": True,
            "invoice_url": invoice_link
        })

    except Exception as e:

        print("\n===== INVOICE ERROR =====")
        print(e)
        print("=========================\n")

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


# =========================================================
# TELEGRAM PAYMENT
# =========================================================

async def pre_checkout(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.pre_checkout_query

    try:

        payload = query.invoice_payload

        if not payload.startswith(
            "premium:"
        ):

            await query.answer(
                ok=False,
                error_message=(
                    "Неизвестный платёж."
                )
            )

            return

        parts = payload.split(":")

        if len(parts) < 2:

            await query.answer(
                ok=False,
                error_message=(
                    "Некорректный платёж."
                )
            )

            return

        payload_user_id = str(
            parts[1]
        )

        telegram_user_id = str(
            query.from_user.id
        )

        if payload_user_id != telegram_user_id:

            await query.answer(
                ok=False,
                error_message=(
                    "Этот платёж создан "
                    "для другого пользователя."
                )
            )

            return

        if query.currency != "XTR":

            await query.answer(
                ok=False,
                error_message=(
                    "Некорректная валюта."
                )
            )

            return

        if query.total_amount != 50:

            await query.answer(
                ok=False,
                error_message=(
                    "Некорректная сумма."
                )
            )

            return

        await query.answer(
            ok=True
        )

    except Exception as e:

        print(
            "PRECHECKOUT ERROR:",
            e
        )

        await query.answer(
            ok=False,
            error_message=(
                "Не удалось проверить платёж."
            )
        )


async def successful_payment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    payment = (
        update.message.successful_payment
    )

    user_id = str(
        update.effective_user.id
    )

    if (
        payment.currency != "XTR"
        or payment.total_amount != 50
    ):
        return

    with data_lock:

        data = load_data()

        user = data["users"].setdefault(
            user_id,
            {
                "premium": False,
                "processed": 0,
                "processing": [],
                "history": []
            }
        )

        user["premium"] = True

        save_data(data)

    await update.message.reply_text(
        "⭐ Premium успешно активирован!\n\n"
        "Теперь тебе доступны:\n"
        "• 2K\n"
        "• 4K\n"
        "• Premium-режим\n\n"
        "Приятного использования 🔥"
    )


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = str(
        update.effective_user.id
    )

    ensure_user(
        user_id
    )

    await update.message.reply_text(
        "🎬 ClipForge\n\n"
        "Открой Mini App через кнопку "
        "ClipForge в меню Telegram."
    )


# =========================================================
# BOT SETUP
# =========================================================

async def setup_bot(
    application
):

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

    print(
        "Mini App:",
        WEBAPP_URL
    )


# =========================================================
# FLASK
# =========================================================

def run_web():

    port = int(
        os.getenv(
            "PORT",
            10000
        )
    )

    web.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN не найден"
        )

    if not WEBAPP_URL:

        raise RuntimeError(
            "WEBAPP_URL не найден"
        )

    # Flask
    threading.Thread(
        target=run_web,
        daemon=True
    ).start()

    # Telegram bot
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(setup_bot)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    # ⭐ Telegram Stars
    application.add_handler(
        PreCheckoutQueryHandler(
            pre_checkout
        )
    )

    application.add_handler(
        MessageHandler(
            filters.SUCCESSFUL_PAYMENT,
            successful_payment
        )
    )

    print(
        "ClipForge запущен!"
    )

    application.run_polling()


if __name__ == "__main__":
    main()
