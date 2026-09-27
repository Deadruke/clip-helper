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

from faster_whisper import WhisperModel


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")

# Владелец
OWNER_USERNAME = "youcoid"

UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
SUBTITLE_DIR = Path("subtitles")

DATA_FILE = Path("data.json")

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
SUBTITLE_DIR.mkdir(exist_ok=True)

web = Flask(__name__)

data_lock = threading.Lock()


# =========================================================
# WHISPER
# =========================================================

WHISPER_MODEL = None
whisper_lock = threading.Lock()


def get_whisper():

    global WHISPER_MODEL

    with whisper_lock:

        if WHISPER_MODEL is None:

            print("Загрузка Whisper...")

            WHISPER_MODEL = WhisperModel(
                "small",
                device="cpu",
                compute_type="int8"
            )

            print("Whisper загружен!")

    return WHISPER_MODEL


# =========================================================
# DATA
# =========================================================

def load_data():

    if not DATA_FILE.exists():

        return {
            "users": {}
        }

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

        return {
            "users": {}
        }


def save_data(data):

    temp = Path(
        "data.json.tmp"
    )

    with open(
        temp,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    temp.replace(
        DATA_FILE
    )


def ensure_user(
    user_id,
    username=None
):

    user_id = str(user_id)

    with data_lock:

        data = load_data()

        if user_id not in data["users"]:

            data["users"][user_id] = {
                "username": username or "",
                "premium": False,
                "processed": 0,
                "processing": [],
                "history": []
            }

        else:

            if username:

                data["users"][user_id][
                    "username"
                ] = username

        save_data(data)

        return data["users"][user_id]


# =========================================================
# OWNER
# =========================================================

def is_owner_username(username):

    if not username:
        return False

    return (
        username.lower().lstrip("@")
        ==
        OWNER_USERNAME.lower()
    )


def is_owner_id(user_id):

    user_id = str(user_id)

    with data_lock:

        data = load_data()

        user = data["users"].get(
            user_id
        )

        if not user:
            return False

        return is_owner_username(
            user.get("username")
        )


# =========================================================
# ADMIN HELPERS
# =========================================================

def find_user_by_username(
    username
):

    username = (
        username
        .lower()
        .lstrip("@")
    )

    with data_lock:

        data = load_data()

        for user_id, user in data[
            "users"
        ].items():

            saved_username = (
                user.get(
                    "username",
                    ""
                )
                .lower()
                .lstrip("@")
            )

            if saved_username == username:

                return (
                    user_id,
                    user
                )

    return None, None


def premium_users():

    result = []

    with data_lock:

        data = load_data()

        for user_id, user in data[
            "users"
        ].items():

            if user.get(
                "premium",
                False
            ):

                result.append({
                    "user_id": user_id,
                    "username": user.get(
                        "username",
                        ""
                    ),
                    "processed": user.get(
                        "processed",
                        0
                    )
                })

    return result


# =========================================================
# PROCESSING DATA
# =========================================================

def add_processing(
    user_id,
    job_id,
    filename
):

    with data_lock:

        data = load_data()

        user = data["users"].setdefault(
            str(user_id),
            {
                "username": "",
                "premium": False,
                "processed": 0,
                "processing": [],
                "history": []
            }
        )

        user.setdefault(
            "processing",
            []
        ).append({
            "id": job_id,
            "filename": filename,
            "status": "processing"
        })

        save_data(data)


def finish_processing(
    user_id,
    job_id,
    filename,
    success
):

    with data_lock:

        data = load_data()

        user = data["users"].get(
            str(user_id)
        )

        if not user:
            return

        user["processing"] = [
            item
            for item in user.get(
                "processing",
                []
            )
            if item.get("id") != job_id
        ]

        if success:

            user["processed"] = (
                user.get(
                    "processed",
                    0
                ) + 1
            )

            user.setdefault(
                "history",
                []
            ).insert(
                0,
                {
                    "id": job_id,
                    "filename": filename
                }
            )

            user["history"] = (
                user["history"][:30]
            )

        save_data(data)


# =========================================================
# WEB
# =========================================================

@web.route("/")
def index():

    return send_from_directory(
        "templates",
        "index.html"
    )


# =========================================================
# USER API
# =========================================================

@web.route(
    "/api/user",
    methods=["GET"]
)
def api_user():

    try:

        user_id = request.args.get(
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

        return jsonify({
            "ok": True,
            "user_id": user_id,
            "premium": user.get(
                "premium",
                False
            ),
            "processed": user.get(
                "processed",
                0
            ),
            "processing": user.get(
                "processing",
                []
            ),
            "history": user.get(
                "history",
                []
            )
        })

    except Exception as e:

        print(
            "USER API ERROR:",
            e
        )

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


# =========================================================
# UPLOAD
# =========================================================

@web.route(
    "/api/upload",
    methods=["POST"]
)
def upload_video():

    try:

        video = request.files.get(
            "video"
        )

        chat_id = request.form.get(
            "chat_id"
        )

        username = request.form.get(
            "username",
            ""
        )

        quality = int(
            request.form.get(
                "quality",
                1080
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
            )
            == "true"
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

        user = ensure_user(
            chat_id,
            username
        )

        premium = user.get(
            "premium",
            False
        )

        # Владелец всегда Premium
        if is_owner_username(username):

            premium = True

            with data_lock:

                data = load_data()

                data["users"][
                    str(chat_id)
                ]["premium"] = True

                save_data(data)

        normal_quality = [
            144,
            360,
            480,
            720,
            1080
        ]

        premium_quality = [
            144,
            360,
            480,
            720,
            1080,
            1440,
            2160
        ]

        if premium:

            if quality not in premium_quality:

                quality = 1080

        else:

            if quality not in normal_quality:

                quality = 1080

            if quality > 1080:

                quality = 1080

        job_id = uuid.uuid4().hex

        input_path = (
            UPLOAD_DIR /
            f"{job_id}.mp4"
        )

        output_path = (
            OUTPUT_DIR /
            f"{job_id}_out.mp4"
        )

        filename = (
            video.filename
            or "video.mp4"
        )

        video.save(
            input_path
        )

        if not input_path.exists():

            raise Exception(
                "Видео не сохранилось"
            )

        add_processing(
            chat_id,
            job_id,
            filename
        )

        threading.Thread(
            target=process_video,
            args=(
                input_path,
                output_path,
                chat_id,
                quality,
                video_format,
                subtitles,
                ai,
                job_id,
                filename
            ),
            daemon=True
        ).start()

        return jsonify({
            "ok": True,
            "job_id": job_id,
            "message": (
                "Видео отправлено "
                "на обработку"
            )
        })

    except Exception as e:

        print(
            "UPLOAD ERROR:",
            e
        )

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


# =========================================================
# SUBTITLES
# =========================================================

def format_timestamp(seconds):

    milliseconds = int(
        (seconds % 1) * 1000
    )

    total = int(seconds)

    hours = total // 3600

    minutes = (
        total % 3600
    ) // 60

    secs = total % 60

    return (
        f"{hours:02d}:"
        f"{minutes:02d}:"
        f"{secs:02d},"
        f"{milliseconds:03d}"
    )


def create_subtitles(
    input_path,
    subtitle_path,
    style
):

    print(
        "Запускаю Whisper..."
    )

    model = get_whisper()

    segments, info = model.transcribe(
        str(input_path),
        beam_size=5,
        vad_filter=True
    )

    segments = list(
        segments
    )

    with open(
        subtitle_path,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "[Script Info]\n"
        )

        f.write(
            "ScriptType: v4.00+\n"
        )

        f.write(
            "PlayResX: 1080\n"
        )

        f.write(
            "PlayResY: 1920\n\n"
        )

        f.write(
            "[V4+ Styles]\n"
        )

        f.write(
            "Format: Name, Fontname, "
            "Fontsize, PrimaryColour, "
            "SecondaryColour, "
            "OutlineColour, BackColour, "
            "Bold, Italic, Underline, "
            "StrikeOut, ScaleX, ScaleY, "
            "Spacing, Angle, BorderStyle, "
            "Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, "
            "Encoding\n"
        )

        if style == "bold":

            bold = -1
            size = 58

        else:

            bold = 0
            size = 52

        f.write(
            f"Style: Default,"
            f"Arial,"
            f"{size},"
            f"&H00FFFFFF,"
            f"&H000000FF,"
            f"&H00000000,"
            f"&H80000000,"
            f"{bold},"
            f"0,0,0,100,100,0,0,1,3,1,2,"
            f"40,40,120,1\n\n"
        )

        f.write(
            "[Events]\n"
        )

        f.write(
            "Format: Layer, Start, End, "
            "Style, Name, MarginL, "
            "MarginR, MarginV, Effect, Text\n"
        )

        for segment in segments:

            start = (
                segment.start
            )

            end = (
                segment.end
            )

            text = (
                segment.text
                .strip()
                .replace(
                    "\n",
                    " "
                )
            )

            if not text:
                continue

            start_ass = (
                format_timestamp(
                    start
                )
                .replace(",", ".")
            )

            end_ass = (
                format_timestamp(
                    end
                )
                .replace(",", ".")
            )

            # ASS uses H:MM:SS.CC
            start_ass = (
                start_ass[:8]
                + "."
                + start_ass[9:11]
            )

            end_ass = (
                end_ass[:8]
                + "."
                + end_ass[9:11]
            )

            f.write(
                f"Dialogue: 0,"
                f"{start_ass},"
                f"{end_ass},"
                f"Default,"
                f",0,0,0,,"
                f"{text}\n"
            )

    print(
        "Субтитры созданы:",
        subtitle_path
    )


# =========================================================
# PROCESS
# =========================================================

def process_video(
    input_path,
    output_path,
    chat_id,
    quality,
    video_format,
    subtitles,
    ai,
    job_id,
    filename
):

    success = False

    subtitle_path = (
        SUBTITLE_DIR /
        f"{job_id}.ass"
    )

    try:

        # ---------------------------------------------
        # SUBTITLES
        # ---------------------------------------------

        subtitle_filter = None

        if subtitles in [
            "normal",
            "bold"
        ]:

            create_subtitles(
                input_path,
                subtitle_path,
                subtitles
            )

            subtitle_filter = (
                f"ass={subtitle_path}"
            )

        # ---------------------------------------------
        # VIDEO SCALE
        # ---------------------------------------------

        filters = []

        if video_format == "vertical":

            width = int(
                quality * 9 / 16
            )

            width -= (
                width % 2
            )

            filters.append(
                f"scale={width}:{quality}:"
                "force_original_aspect_ratio=decrease"
            )

            filters.append(
                f"pad={width}:{quality}:"
                "(ow-iw)/2:(oh-ih)/2"
            )

        else:

            filters.append(
                f"scale=-2:{quality}"
            )

        # ---------------------------------------------
        # QUALITY
        # ---------------------------------------------

        if ai:

            filters.append(
                "hqdn3d=1.2:1.2:6:6"
            )

            filters.append(
                "unsharp=5:5:0.65:5:5:0.0"
            )

        if subtitle_filter:

            filters.append(
                subtitle_filter
            )

        filter_string = ",".join(
            filters
        )

        # ---------------------------------------------
        # ENCODE
        # ---------------------------------------------

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
            "slow",

            "-crf",
            "16",

            "-pix_fmt",
            "yuv420p",

            "-c:a",
            "aac",

            "-b:a",
            "192k",

            "-movflags",
            "+faststart",

            str(output_path)
        ]

        print(
            "FFmpeg:",
            " ".join(command)
        )

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if result.returncode != 0:

            raise Exception(
                result.stderr[-5000:]
            )

        if not output_path.exists():

            raise Exception(
                "FFmpeg не создал файл"
            )

        # ---------------------------------------------
        # SEND
        # ---------------------------------------------

        asyncio.run(
            send_video(
                chat_id,
                output_path,
                quality,
                subtitles
            )
        )

        success = True

    except Exception as e:

        print(
            "\nPROCESS ERROR:"
        )

        print(e)

        print(
            "\n"
        )

        try:

            asyncio.run(
                send_error(
                    chat_id
                )
            )

        except Exception:
            pass

    finally:

        finish_processing(
            chat_id,
            job_id,
            filename,
            success
        )

        for path in [
            input_path,
            output_path,
            subtitle_path
        ]:

            try:

                path.unlink(
                    missing_ok=True
                )

            except Exception:
                pass


# =========================================================
# TELEGRAM SEND
# =========================================================

async def send_video(
    chat_id,
    output_path,
    quality,
    subtitles
):

    bot = Bot(
        BOT_TOKEN
    )

    subtitle_text = (
        " + субтитры"
        if subtitles != "off"
        else ""
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
                "✅ ClipForge готов!\n\n"
                f"Качество: {quality}p"
                f"{subtitle_text}"
            ),
            read_timeout=300,
            write_timeout=300,
            connect_timeout=30
        )


async def send_error(
    chat_id
):

    bot = Bot(
        BOT_TOKEN
    )

    await bot.send_message(
        chat_id=int(chat_id),
        text=(
            "❌ Во время обработки "
            "произошла ошибка.\n"
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
def create_invoice():

    try:

        body = (
            request.get_json(
                silent=True
            )
            or {}
        )

        user_id = str(
            body.get(
                "user_id",
                ""
            )
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
                "error": "Premium уже активен"
            }), 400

        async def make():

            bot = Bot(
                BOT_TOKEN
            )

            payload = (
                f"premium:"
                f"{user_id}:"
                f"{uuid.uuid4().hex}"
            )

            return await bot.create_invoice_link(
                title="ClipForge Premium",
                description=(
                    "2K и 4K обработка видео"
                ),
                payload=payload,
                currency="XTR",
                prices=[
                    LabeledPrice(
                        "Premium",
                        50
                    )
                ]
            )

        invoice = asyncio.run(
            make()
        )

        return jsonify({
            "ok": True,
            "invoice_url": invoice
        })

    except Exception as e:

        print(
            "INVOICE ERROR:",
            e
        )

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


# =========================================================
# PAYMENT CHECK
# =========================================================

async def pre_checkout(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = (
        update.pre_checkout_query
    )

    try:

        payload = (
            query.invoice_payload
        )

        if not payload.startswith(
            "premium:"
        ):

            await query.answer(
                ok=False,
                error_message=(
                    "Неверный платёж."
                )
            )

            return

        parts = payload.split(":")

        payload_user_id = str(
            parts[1]
        )

        actual_user_id = str(
            query.from_user.id
        )

        if (
            payload_user_id
            !=
            actual_user_id
        ):

            await query.answer(
                ok=False,
                error_message=(
                    "Платёж создан "
                    "для другого пользователя."
                )
            )

            return

        if query.currency != "XTR":

            await query.answer(
                ok=False,
                error_message=(
                    "Неверная валюта."
                )
            )

            return

        if query.total_amount != 50:

            await query.answer(
                ok=False,
                error_message=(
                    "Неверная сумма."
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


# =========================================================
# SUCCESS PAYMENT
# =========================================================

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
                "username": "",
                "premium": False,
                "processed": 0,
                "processing": [],
                "history": []
            }
        )

        user["premium"] = True

        save_data(data)

    await update.message.reply_text(
        "⭐ Premium активирован!\n\n"
        "Теперь тебе доступны 2K и 4K."
    )


# =========================================================
# ADMIN API
# =========================================================

def check_admin(
    user_id,
    username
):

    return is_owner_username(
        username
    ) or is_owner_id(
        user_id
    )


@web.route(
    "/api/admin",
    methods=["GET"]
)
def admin_data():

    try:

        user_id = request.args.get(
            "user_id"
        )

        username = request.args.get(
            "username",
            ""
        )

        if not check_admin(
            user_id,
            username
        ):

            return jsonify({
                "ok": False,
                "error": "Нет доступа"
            }), 403

        with data_lock:

            data = load_data()

            users = data.get(
                "users",
                {}
            )

            total_users = len(
                users
            )

            total_processed = sum(
                u.get(
                    "processed",
                    0
                )
                for u in users.values()
            )

        return jsonify({
            "ok": True,
            "users": total_users,
            "processed": total_processed,
            "premium": premium_users()
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


@web.route(
    "/api/admin/premium",
    methods=["POST"]
)
def admin_premium():

    try:

        body = (
            request.get_json(
                silent=True
            )
            or {}
        )

        admin_id = str(
            body.get(
                "admin_id",
                ""
            )
        )

        admin_username = body.get(
            "admin_username",
            ""
        )

        target_username = (
            body.get(
                "username",
                ""
            )
            .lstrip("@")
            .strip()
        )

        action = body.get(
            "action"
        )

        if not check_admin(
            admin_id,
            admin_username
        ):

            return jsonify({
                "ok": False,
                "error": "Нет доступа"
            }), 403

        target_id, target = (
            find_user_by_username(
                target_username
            )
        )

        if not target_id:

            return jsonify({
                "ok": False,
                "error": (
                    "Пользователь пока "
                    "не запускал бота."
                )
            }), 404

        with data_lock:

            data = load_data()

            if action == "grant":

                data["users"][
                    target_id
                ]["premium"] = True

            elif action == "remove":

                data["users"][
                    target_id
                ]["premium"] = False

            else:

                return jsonify({
                    "ok": False,
                    "error": "Неизвестное действие"
                }), 400

            save_data(data)

        return jsonify({
            "ok": True,
            "message": "Готово"
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = (
        update.effective_user
    )

    username = (
        user.username
        or ""
    )

    ensure_user(
        user.id,
        username
    )

    # Владелец автоматически Premium
    if is_owner_username(
        username
    ):

        with data_lock:

            data = load_data()

            data["users"][
                str(user.id)
            ]["premium"] = True

            save_data(data)

    await update.message.reply_text(
        "🎬 ClipForge\n\n"
        "Открой Mini App через кнопку "
        "ClipForge."
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
# WEB SERVER
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
        CommandHandler(
            "start",
            start
        )
    )

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
