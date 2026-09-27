import os
import json
import uuid
import asyncio
import threading
import subprocess
from pathlib import Path

from flask import Flask, request, jsonify

from telegram import (
    Update,
    LabeledPrice,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
    Bot,
)

from telegram.ext import (
    Application,
    CommandHandler,
    PreCheckoutQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# =========================================================
# НАСТРОЙКИ
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")

OWNER_USERNAME = "youcoid"

PREMIUM_PRICE = 50


# =========================================================
# ПАПКИ
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
SUBTITLES_DIR = BASE_DIR / "subtitles"

UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)
SUBTITLES_DIR.mkdir(exist_ok=True)

DATA_FILE = BASE_DIR / "data.json"


# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)


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

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(file)

    except Exception:

        return {
            "users": {}
        }


def save_data(data):

    temp_file = DATA_FILE.with_suffix(
        ".tmp"
    )

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )

    temp_file.replace(
        DATA_FILE
    )


def ensure_user(
    chat_id,
    username=""
):

    chat_id = str(chat_id)

    username = (
        username or ""
    ).replace(
        "@",
        ""
    ).strip()

    with data_lock:

        data = load_data()

        users = data.setdefault(
            "users",
            {}
        )

        if chat_id not in users:

            users[chat_id] = {

                "chat_id":
                    chat_id,

                "username":
                    username,

                "premium":
                    False,

                "processed":
                    0,

                "processing":
                    [],

                "history":
                    []

            }

        else:

            if username:

                users[chat_id][
                    "username"
                ] = username


        # Владелец всегда Premium

        if (
            username.lower()
            ==
            OWNER_USERNAME.lower()
        ):

            users[chat_id][
                "premium"
            ] = True


        save_data(data)

        return users[chat_id]


def get_user(chat_id):

    data = load_data()

    return data.get(
        "users",
        {}
    ).get(
        str(chat_id)
    )


def is_owner(username):

    return (
        str(username or "")
        .replace("@", "")
        .lower()
        ==
        OWNER_USERNAME.lower()
    )


# =========================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================================================

def safe_name(name):

    name = Path(name).name

    allowed = (
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789"
        "._-"
    )

    return "".join(
        char
        if char in allowed
        else "_"
        for char in name
    )


def quality_height(quality):

    try:

        quality = int(quality)

    except Exception:

        quality = 1080


    allowed = [
        144,
        360,
        480,
        720,
        1080,
        1440,
        2160
    ]


    if quality not in allowed:

        quality = 1080


    return quality


def update_processing(
    chat_id,
    job_id,
    status
):

    with data_lock:

        data = load_data()

        user = data[
            "users"
        ].get(
            str(chat_id)
        )

        if not user:

            return


        for item in user.get(
            "processing",
            []
        ):

            if (
                item.get("id")
                ==
                job_id
            ):

                item["status"] = status


        save_data(data)


def remove_processing(
    chat_id,
    job_id
):

    with data_lock:

        data = load_data()

        user = data[
            "users"
        ].get(
            str(chat_id)
        )

        if not user:

            return


        user["processing"] = [

            item

            for item in user.get(
                "processing",
                []
            )

            if item.get("id")
            !=
            job_id

        ]


        save_data(data)


def add_history(
    chat_id,
    filename,
    status="Готово"
):

    with data_lock:

        data = load_data()

        user = data[
            "users"
        ].get(
            str(chat_id)
        )

        if not user:

            return


        user["processed"] = (
            user.get(
                "processed",
                0
            )
            + 1
        )


        user.setdefault(
            "history",
            []
        ).append({

            "filename":
                filename,

            "status":
                status

        })


        user["history"] = user[
            "history"
        ][-50:]


        save_data(data)


# =========================================================
# FFMPEG
# =========================================================

def run_command(
    command,
    timeout=3600
):

    process = subprocess.Popen(

        command,

        stdout=subprocess.PIPE,

        stderr=subprocess.PIPE,

        text=True

    )


    try:

        stdout, stderr = (
            process.communicate(
                timeout=timeout
            )
        )

    except subprocess.TimeoutExpired:

        process.kill()

        stdout, stderr = (
            process.communicate()
        )

        raise RuntimeError(
            "Обработка видео превысила допустимое время."
        )


    if process.returncode != 0:

        error = (
            stderr[-5000:]
            if stderr
            else
            "FFmpeg завершился с ошибкой."
        )

        raise RuntimeError(
            error
        )


    return stdout


# =========================================================
# WHISPER СУБТИТРЫ
# =========================================================

def create_subtitles(
    video_path,
    subtitle_path,
    bold=False
):

    try:

        from faster_whisper import (
            WhisperModel
        )

    except Exception as error:

        raise RuntimeError(
            f"Whisper недоступен: {error}"
        )


    model = WhisperModel(

        "small",

        device="cpu",

        compute_type="int8"

    )


    segments, info = (
        model.transcribe(

            str(video_path),

            beam_size=5,

            vad_filter=True

        )
    )


    bold_value = 1 if bold else 0


    lines = [

        "[Script Info]\n",

        "ScriptType: v4.00+\n",

        "PlayResX: 1080\n",

        "PlayResY: 1920\n\n",

        "[V4+ Styles]\n",

        "Format: Name, Fontname, Fontsize, "
        "PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, "
        "Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding\n",

        "Style: Default,Arial,58,"
        "&H00FFFFFF,&H00FFFFFF,"
        "&H00000000,&H80000000,"
        f"{bold_value},0,0,0,100,100,0,0,1,3,1,2,40,40,120,1\n",

        "\n[Events]\n",

        "Format: Layer, Start, End, Style, "
        "Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"

    ]


    def ass_time(seconds):

        total = max(
            0,
            int(seconds)
        )

        hours = total // 3600

        minutes = (
            total % 3600
        ) // 60

        secs = total % 60

        centiseconds = int(
            (
                seconds
                -
                int(seconds)
            )
            * 100
        )


        return (
            f"{hours}:"
            f"{minutes:02d}:"
            f"{secs:02d}."
            f"{centiseconds:02d}"
        )


    for segment in segments:

        text = (
            segment.text
            .strip()
            .replace(
                "\n",
                " "
            )
            .replace(
                "{",
                ""
            )
            .replace(
                "}",
                ""
            )
        )


        if not text:

            continue


        start = ass_time(
            segment.start
        )

        end = ass_time(
            segment.end
        )


        lines.append(

            f"Dialogue: 0,"
            f"{start},"
            f"{end},"
            f"Default,,0,0,0,,"
            f"{text}\n"

        )


    with open(
        subtitle_path,
        "w",
        encoding="utf-8"
    ) as file:

        file.writelines(
            lines
        )


# =========================================================
# ОТПРАВКА ГОТОВОГО ВИДЕО
# =========================================================

async def send_result(
    chat_id,
    output_path
):

    try:

        bot = Bot(
            token=BOT_TOKEN
        )


        with open(
            output_path,
            "rb"
        ) as video:

            await bot.send_video(

                chat_id=int(
                    chat_id
                ),

                video=video,

                supports_streaming=True,

                caption=
                    "🔥 Артем хуесос 6767\n\n"
                    "✅ Видео успешно обработано!"

            )


    except Exception as error:

        print(
            "SEND ERROR:",
            repr(error)
        )


# =========================================================
# ОБРАБОТКА ВИДЕО
# =========================================================

def process_video(

    chat_id,

    job_id,

    input_path,

    output_path,

    quality,

    video_format,

    subtitles,

    ai

):

    subtitle_path = None


    try:

        update_processing(

            chat_id,

            job_id,

            "Подготавливаем видео..."

        )


        quality = quality_height(
            quality
        )


        # -------------------------------------------------
        # СУБТИТРЫ
        # -------------------------------------------------

        if subtitles != "off":

            update_processing(

                chat_id,

                job_id,

                "🎤 Распознаём речь..."

            )


            subtitle_path = (

                SUBTITLES_DIR
                /
                f"{job_id}.ass"

            )


            create_subtitles(

                input_path,

                subtitle_path,

                subtitles == "bold"

            )


        # -------------------------------------------------
        # ФИЛЬТРЫ
        # -------------------------------------------------

        filters_list = []


        if video_format == "9:16":

            target_height = int(
                quality * 16 / 9
            )


            filters_list.append(

                "scale="
                f"{quality}:"
                f"{target_height}:"
                "force_original_aspect_ratio=increase"

            )


            filters_list.append(

                "crop="
                f"{quality}:"
                f"{target_height}"

            )

        else:

            filters_list.append(

                "scale="
                f"min({quality}\\,iw):"
                f"min({quality}\\,ih):"
                "force_original_aspect_ratio=decrease"

            )


        # -------------------------------------------------
        # УЛУЧШЕНИЕ
        # -------------------------------------------------

        if ai:

            filters_list.append(
                "hqdn3d=1.5:1.5:6:6"
            )

            filters_list.append(
                "unsharp=5:5:1.0:5:5:0.0"
            )


        # -------------------------------------------------
        # СУБТИТРЫ
        # -------------------------------------------------

        if subtitle_path:

            subtitle_file = (
                str(
                    subtitle_path
                )
                .replace(
                    "\\",
                    "/"
                )
                .replace(
                    ":",
                    "\\:"
                )
                .replace(
                    "'",
                    "\\'"
                )
            )


            filters_list.append(

                f"ass='{subtitle_file}'"

            )


        filter_complex = ",".join(
            filters_list
        )


        # -------------------------------------------------
        # КОДИРОВАНИЕ
        # -------------------------------------------------

        update_processing(

            chat_id,

            job_id,

            "🔥 Улучшаем качество..."

        )


        command = [

            "ffmpeg",

            "-y",

            "-i",
            str(input_path),

            "-vf",
            filter_complex,

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


        run_command(
            command,
            timeout=3600
        )


        # -------------------------------------------------
        # УСПЕШНО
        # -------------------------------------------------

        update_processing(

            chat_id,

            job_id,

            "Артем хуесос 6767"

        )


        add_history(

            chat_id,

            output_path.name,

            "Артем хуесос 6767"

        )


        # Отправляем готовый файл

        asyncio.run(

            send_result(

                chat_id,

                output_path

            )

        )


    except Exception as error:

        print(
            "PROCESS ERROR:",
            repr(error)
        )


        update_processing(

            chat_id,

            job_id,

            "❌ Ошибка обработки"

        )


        add_history(

            chat_id,

            output_path.name,

            f"Ошибка: {str(error)[:150]}"

        )


    finally:

        remove_processing(

            chat_id,

            job_id

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


        if subtitle_path:

            try:

                subtitle_path.unlink(
                    missing_ok=True
                )

            except Exception:
                pass


# =========================================================
# API USER
# =========================================================

@app.get("/api/user")
def api_user():

    chat_id = request.args.get(
        "chat_id"
    )

    username = request.args.get(
        "username",
        ""
    )


    if not chat_id:

        return jsonify({
            "error":
                "chat_id required"
        }), 400


    user = ensure_user(

        chat_id,

        username

    )


    return jsonify(
        user
    )


# =========================================================
# API UPLOAD
# =========================================================

@app.post("/api/upload")
def api_upload():

    try:

        video = request.files.get(
            "video"
        )


        if not video:

            return jsonify({
                "error":
                    "Видео не найдено"
            }), 400


        chat_id = request.form.get(
            "chat_id"
        )

        username = request.form.get(
            "username",
            ""
        )


        if not chat_id:

            return jsonify({
                "error":
                    "Telegram ID не найден"
            }), 400


        user = ensure_user(

            chat_id,

            username

        )


        quality = quality_height(

            request.form.get(
                "quality",
                "1080"
            )

        )


        if (
            quality > 1080
            and not user["premium"]
        ):

            return jsonify({

                "error":
                    "2K и 4K доступны только Premium."

            }), 403


        video_format = request.form.get(

            "format",

            "9:16"

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
            ==
            "true"

        )


        job_id = str(
            uuid.uuid4()
        )


        original_name = safe_name(

            video.filename
            or
            "video.mp4"

        )


        input_path = (

            UPLOADS_DIR
            /
            f"{job_id}_{original_name}"

        )


        output_path = (

            OUTPUTS_DIR
            /
            f"{job_id}_clip.mp4"

        )


        video.save(
            input_path
        )


        with data_lock:

            data = load_data()

            user = data[
                "users"
            ][
                str(chat_id)
            ]


            user.setdefault(
                "processing",
                []
            ).append({

                "id":
                    job_id,

                "filename":
                    original_name,

                "status":
                    "В очереди..."

            })


            save_data(data)


        thread = threading.Thread(

            target=process_video,

            args=(

                chat_id,

                job_id,

                input_path,

                output_path,

                quality,

                video_format,

                subtitles,

                ai

            ),

            daemon=True

        )


        thread.start()


        return jsonify({

            "success":
                True,

            "job_id":
                job_id,

            "message":
                "Видео отправлено на обработку."

        })


    except Exception as error:

        print(
            "UPLOAD ERROR:",
            repr(error)
        )


        return jsonify({

            "error":
                str(error)

        }), 500


# =========================================================
# PREMIUM
# =========================================================

@app.post("/api/create-premium-invoice")
def create_premium_invoice():

    try:

        body = request.get_json(
            silent=True
        ) or {}


        chat_id = body.get(
            "chat_id"
        )

        username = body.get(
            "username",
            ""
        )


        if not chat_id:

            return jsonify({

                "error":
                    "Telegram ID не найден"

            }), 400


        user = ensure_user(

            chat_id,

            username

        )


        if user["premium"]:

            return jsonify({

                "error":
                    "Premium уже активен"

            }), 400


        async def create_invoice():

            bot = Bot(
                token=BOT_TOKEN
            )


            return await bot.create_invoice_link(

                title=
                    "ClipForge Premium",

                description=
                    "Premium: 2K, 4K и дополнительные возможности.",

                payload=
                    f"premium:{chat_id}",

                currency=
                    "XTR",

                prices=[

                    LabeledPrice(

                        "ClipForge Premium",

                        PREMIUM_PRICE

                    )

                ]

            )


        invoice_link = asyncio.run(
            create_invoice()
        )


        return jsonify({

            "invoice_link":
                invoice_link

        })


    except Exception as error:

        print(
            "INVOICE ERROR:",
            repr(error)
        )


        return jsonify({

            "error":
                str(error)

        }), 500


# =========================================================
# ADMIN
# =========================================================

@app.get("/api/admin")
def api_admin():

    username = request.args.get(
        "username",
        ""
    )


    if not is_owner(
        username
    ):

        return jsonify({

            "error":
                "Доступ запрещён"

        }), 403


    data = load_data()

    users = data.get(
        "users",
        {}
    )


    premium_list = []

    total_processed = 0


    for user in users.values():

        total_processed += int(

            user.get(
                "processed",
                0
            )

        )


        if user.get(
            "premium",
            False
        ):

            premium_list.append({

                "chat_id":
                    user.get(
                        "chat_id"
                    ),

                "username":
                    user.get(
                        "username",
                        ""
                    )

            })


    return jsonify({

        "total_users":
            len(users),

        "total_processed":
            total_processed,

        "premium_users":
            len(premium_list),

        "premium_list":
            premium_list

    })


@app.post("/api/admin/premium")
def api_admin_premium():

    try:

        body = request.get_json(
            silent=True
        ) or {}


        admin_username = body.get(
            "admin_username",
            ""
        )


        username = (

            body.get(
                "username",
                ""
            )

            .replace(
                "@",
                ""
            )

            .strip()

        )


        action = body.get(
            "action"
        )


        if not is_owner(
            admin_username
        ):

            return jsonify({

                "error":
                    "Доступ запрещён"

            }), 403


        if not username:

            return jsonify({

                "error":
                    "Username не указан"

            }), 400


        data = load_data()

        target = None


        for user in data.get(
            "users",
            {}
        ).values():

            if (

                user.get(
                    "username",
                    ""
                ).lower()

                ==

                username.lower()

            ):

                target = user

                break


        if not target:

            return jsonify({

                "error":
                    "Пользователь ещё не запускал бота."

            }), 404


        if action == "grant":

            target["premium"] = True

            message = (
                f"Premium выдан @{username}"
            )


        elif action == "remove":

            target["premium"] = False

            message = (
                f"Premium снят с @{username}"
            )


        else:

            return jsonify({

                "error":
                    "Неизвестное действие"

            }), 400


        save_data(data)


        return jsonify({

            "success":
                True,

            "message":
                message

        })


    except Exception as error:

        return jsonify({

            "error":
                str(error)

        }), 500


# =========================================================
# START BOT
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user


    if not user:

        return


    ensure_user(

        user.id,

        user.username or ""

    )


    if not WEBAPP_URL:

        await update.message.reply_text(

            "❌ WEBAPP_URL не настроен."

        )

        return


    keyboard = InlineKeyboardMarkup([

        [

            InlineKeyboardButton(

                "🚀 Открыть ClipForge",

                web_app=WebAppInfo(
                    WEBAPP_URL
                )

            )

        ]

    ])


    await update.message.reply_text(

        "🎬 ClipForge\n\n"
        "Нажми кнопку ниже, "
        "чтобы открыть приложение.",

        reply_markup=keyboard

    )


# =========================================================
# PAYMENT
# =========================================================

async def precheckout(

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

                error_message=
                    "Неверный платёж."

            )

            return


        chat_id = payload.split(
            ":",
            1
        )[1]


        if str(
            query.from_user.id
        ) != str(
            chat_id
        ):

            await query.answer(

                ok=False,

                error_message=
                    "Платёж создан для другого пользователя."

            )

            return


        if (

            query.currency
            !=
            "XTR"

            or

            query.total_amount
            !=
            PREMIUM_PRICE

        ):

            await query.answer(

                ok=False,

                error_message=
                    "Неверная сумма."

            )

            return


        await query.answer(
            ok=True
        )


    except Exception as error:

        print(
            "PRECHECKOUT ERROR:",
            repr(error)
        )


        await query.answer(

            ok=False,

            error_message=
                "Ошибка проверки платежа."

        )


async def successful_payment(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE

):

    payment = (
        update
        .message
        .successful_payment
    )


    chat_id = (
        update
        .effective_user
        .id
    )


    if payment.currency != "XTR":

        return


    with data_lock:

        data = load_data()


        user = data[
            "users"
        ].get(
            str(chat_id)
        )


        if user:

            user[
                "premium"
            ] = True

            save_data(data)


    await update.message.reply_text(

        "🎉 Оплата получена!\n\n"
        "⭐ Premium активирован."

    )


# =========================================================
# HEALTH
# =========================================================

@app.get("/")
def index():

    return (
        "ClipForge is running."
    )


@app.get("/health")
def health():

    return jsonify({

        "status":
            "ok"

    })


# =========================================================
# FLASK
# =========================================================

def run_flask():

    port = int(

        os.getenv(
            "PORT",
            "10000"
        )

    )


    app.run(

        host="0.0.0.0",

        port=port

    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(

            "BOT_TOKEN не установлен."

        )


    flask_thread = threading.Thread(

        target=run_flask,

        daemon=True

    )


    flask_thread.start()


    application = (

        Application
        .builder()
        .token(
            BOT_TOKEN
        )
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
            precheckout
        )

    )


    application.add_handler(

        MessageHandler(

            filters.SUCCESSFUL_PAYMENT,

            successful_payment

        )

    )


    print(
        "ClipForge bot started."
    )


    application.run_polling(

        drop_pending_updates=True

    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()
