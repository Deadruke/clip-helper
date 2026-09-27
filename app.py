import os
import asyncio
import subprocess
import uuid
import threading

from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------------- WEB SERVER ----------------

web_app = Flask(__name__)


@web_app.route("/")
def home():
    return "Clip Helper Bot is running!"


def start_web_server():
    port = int(os.getenv("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)


# ---------------- USER SETTINGS ----------------

users = {}


def get_user(user_id):
    if user_id not in users:
        users[user_id] = {
            "quality": "720",
            "subtitles": "basic",
            "ai": False,
            "vertical": True,
        }

    return users[user_id]


# ---------------- MENU ----------------

def main_menu(user_id):
    settings = get_user(user_id)

    quality = settings["quality"]
    ai = "ВКЛ" if settings["ai"] else "ВЫКЛ"
    vertical = "9:16" if settings["vertical"] else "Оригинал"

    keyboard = [
        [
            InlineKeyboardButton(
                f"🎥 Качество: {quality}p",
                callback_data="quality"
            )
        ],
        [
            InlineKeyboardButton(
                f"📝 Субтитры: {settings['subtitles']}",
                callback_data="subtitles"
            )
        ],
        [
            InlineKeyboardButton(
                f"🤖 AI улучшение: {ai}",
                callback_data="ai"
            )
        ],
        [
            InlineKeyboardButton(
                f"📱 Формат: {vertical}",
                callback_data="format"
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# ---------------- START ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_user(user_id)

    await update.message.reply_text(
        "🎬 Clip Helper\n\n"
        "Отправь мне видео — я обработаю его.\n\n"
        "Перед отправкой можешь настроить параметры:",
        reply_markup=main_menu(user_id)
    )


# ---------------- SETTINGS ----------------

async def settings_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    settings = get_user(user_id)

    if query.data == "quality":
        keyboard = [
            [
                InlineKeyboardButton("144p", callback_data="q_144"),
                InlineKeyboardButton("360p", callback_data="q_360"),
            ],
            [
                InlineKeyboardButton("480p", callback_data="q_480"),
                InlineKeyboardButton("720p HD", callback_data="q_720"),
            ],
            [
                InlineKeyboardButton("1080p Full HD", callback_data="q_1080"),
            ],
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="back"),
            ],
        ]

        await query.edit_message_text(
            "🎥 Выбери качество:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("q_"):
        quality = query.data.split("_")[1]
        settings["quality"] = quality

        await query.edit_message_text(
            f"✅ Качество установлено: {quality}p",
            reply_markup=main_menu(user_id)
        )

    elif query.data == "subtitles":
        keyboard = [
            [
                InlineKeyboardButton(
                    "🚫 Без субтитров",
                    callback_data="sub_none"
                )
            ],
            [
                InlineKeyboardButton(
                    "📝 Обычные",
                    callback_data="sub_basic"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔥 Жирные",
                    callback_data="sub_bold"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Назад",
                    callback_data="back"
                )
            ],
        ]

        await query.edit_message_text(
            "📝 Выбери стиль субтитров:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("sub_"):
        style = query.data.split("_")[1]
        settings["subtitles"] = style

        await query.edit_message_text(
            f"✅ Субтитры: {style}",
            reply_markup=main_menu(user_id)
        )

    elif query.data == "ai":
        settings["ai"] = not settings["ai"]

        status = "ВКЛЮЧЕНО 🤖" if settings["ai"] else "ВЫКЛЮЧЕНО"

        await query.edit_message_text(
            f"🤖 AI улучшение: {status}",
            reply_markup=main_menu(user_id)
        )

    elif query.data == "format":
        settings["vertical"] = not settings["vertical"]

        format_name = "9:16" if settings["vertical"] else "Оригинал"

        await query.edit_message_text(
            f"📱 Формат: {format_name}",
            reply_markup=main_menu(user_id)
        )

    elif query.data == "back":
        await query.edit_message_text(
            "⚙️ Настройки Clip Helper:",
            reply_markup=main_menu(user_id)
        )


# ---------------- VIDEO ----------------

async def video_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id
    settings = get_user(user_id)

    video = update.message.video

    await update.message.reply_text(
        "⏳ Видео получил.\n"
        "Начинаю обработку..."
    )

    job_id = str(uuid.uuid4())

    input_path = os.path.join(
        UPLOAD_DIR,
        f"{job_id}.mp4"
    )

    output_path = os.path.join(
        OUTPUT_DIR,
        f"{job_id}.mp4"
    )

    try:
        telegram_file = await context.bot.get_file(video.file_id)

        await telegram_file.download_to_drive(input_path)

        await update.message.reply_text(
            "📥 Видео скачано.\n"
            "⚙️ Обрабатываю..."
        )

        await asyncio.to_thread(
            process_video,
            input_path,
            output_path,
            settings
        )

        await update.message.reply_text(
            "✅ Готово! Отправляю видео..."
        )

        with open(output_path, "rb") as output:
            await update.message.reply_video(
                video=output,
                caption="🎬 Готово — Clip Helper"
            )

    except Exception as e:
        print("ERROR:", e)

        await update.message.reply_text(
            "❌ Произошла ошибка при обработке.\n\n"
            f"{str(e)[:500]}"
        )

    finally:
        if os.path.exists(input_path):
            os.remove(input_path)

        if os.path.exists(output_path):
            os.remove(output_path)


# ---------------- PROCESSING ----------------

def process_video(
    input_path,
    output_path,
    settings
):
    quality = int(settings["quality"])
    vertical = settings["vertical"]
    ai = settings["ai"]

    filters = []

    if vertical:
        width = int(quality * 9 / 16)

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

    # Пока это улучшение изображения.
    # Реальный AI-upscaler подключим отдельным этапом.
    if ai:
        filters.append(
            "unsharp=5:5:1.0:5:5:0.0"
        )

    filter_string = ",".join(filters)

    command = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vf",
        filter_string,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        output_path,
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr[-2000:]
        )


# ---------------- RUN BOT ----------------

async def run_bot():
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CallbackQueryHandler(
            settings_callback
        )
    )

    application.add_handler(
        MessageHandler(
            filters.VIDEO,
            video_handler
        )
    )

    print("Telegram bot started")

    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    while True:
        await asyncio.sleep(3600)


def start_bot():
    asyncio.run(run_bot())


if __name__ == "__main__":
    web_thread = threading.Thread(
        target=start_web_server,
        daemon=True
    )

    web_thread.start()

    start_bot()
