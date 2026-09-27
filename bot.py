import os
import uuid
import asyncio
import subprocess

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

# Настройки пользователей
users = {}


def get_settings(user_id):
    if user_id not in users:
        users[user_id] = {
            "quality": 720,
            "subtitles": "none",
            "ai": False,
            "vertical": True,
        }

    return users[user_id]


def main_menu(user_id):
    settings = get_settings(user_id)

    ai = "ВКЛ" if settings["ai"] else "ВЫКЛ"
    fmt = "9:16" if settings["vertical"] else "Оригинал"

    keyboard = [
        [
            InlineKeyboardButton(
                f"🎥 Качество: {settings['quality']}p",
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
                f"📱 Формат: {fmt}",
                callback_data="format"
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_settings(user_id)

    await update.message.reply_text(
        "🎬 Clip Helper\n\n"
        "Отправь мне видео, и я обработаю его.\n\n"
        "Сначала выбери настройки:",
        reply_markup=main_menu(user_id)
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    settings = get_settings(user_id)

    # Выбор качества
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
                InlineKeyboardButton("⬅️ Назад", callback_data="back")
            ],
        ]

        await query.edit_message_text(
            "🎥 Выбери качество:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("q_"):
        settings["quality"] = int(query.data.split("_")[1])

        await query.edit_message_text(
            f"✅ Качество: {settings['quality']}p",
            reply_markup=main_menu(user_id)
        )

    # Субтитры
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
        settings["subtitles"] = query.data[4:]

        await query.edit_message_text(
            "✅ Настройки субтитров сохранены.",
            reply_markup=main_menu(user_id)
        )

    # AI
    elif query.data == "ai":
        settings["ai"] = not settings["ai"]

        await query.edit_message_text(
            "🤖 AI улучшение: "
            + ("ВКЛЮЧЕНО" if settings["ai"] else "ВЫКЛЮЧЕНО"),
            reply_markup=main_menu(user_id)
        )

    # Формат
    elif query.data == "format":
        settings["vertical"] = not settings["vertical"]

        await query.edit_message_text(
            "📱 Формат: "
            + ("9:16" if settings["vertical"] else "Оригинал"),
            reply_markup=main_menu(user_id)
        )

    elif query.data == "back":
        await query.edit_message_text(
            "⚙️ Настройки:",
            reply_markup=main_menu(user_id)
        )


async def video_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id
    settings = get_settings(user_id)

    await update.message.reply_text(
        "📥 Видео получил. Начинаю обработку..."
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
        telegram_file = await context.bot.get_file(
            update.message.video.file_id
        )

        await telegram_file.download_to_drive(input_path)

        await update.message.reply_text(
            "⚙️ Обрабатываю видео..."
        )

        await asyncio.to_thread(
            process_video,
            input_path,
            output_path,
            settings
        )

        with open(output_path, "rb") as video:
            await update.message.reply_video(
                video=video,
                caption="✅ Готово! — Clip Helper"
            )

    except Exception as error:
        print(error)

        await update.message.reply_text(
            "❌ Ошибка при обработке видео."
        )

    finally:
        if os.path.exists(input_path):
            os.remove(input_path)

        if os.path.exists(output_path):
            os.remove(output_path)


def process_video(input_path, output_path, settings):
    quality = settings["quality"]

    if settings["vertical"]:
        width = int(quality * 9 / 16)

        video_filter = (
            f"scale={width}:{quality}:"
            "force_original_aspect_ratio=decrease,"
            f"pad={width}:{quality}:(ow-iw)/2:(oh-ih)/2"
        )
    else:
        video_filter = f"scale=-2:{quality}"

    # Временное улучшение изображения.
    # Настоящий AI-upscaler подключим следующим этапом.
    if settings["ai"]:
        video_filter += ",unsharp=5:5:1.0:5:5:0.0"

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
        "-movflags", "+faststart",
        output_path,
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:])


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN не найден в Environment Variables"
        )

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CallbackQueryHandler(button_handler)
    )

    app.add_handler(
        MessageHandler(
            filters.VIDEO,
            video_handler
        )
    )

    print("Clip Helper Bot запущен!")

    app.run_polling()


if __name__ == "__main__":
    main()
