import os
import uuid
import asyncio
import subprocess
from pathlib import Path

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# =========================
# CONFIG
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")

UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# Настройки пользователей
user_settings = {}


# =========================
# DEFAULT SETTINGS
# =========================

def get_settings(user_id):
    if user_id not in user_settings:
        user_settings[user_id] = {
            "quality": 720,
            "format": "vertical",
            "subtitles": "off",
            "ai": False,
        }

    return user_settings[user_id]


# =========================
# SETTINGS TEXT
# =========================

def settings_text(settings):
    quality = settings["quality"]

    format_text = {
        "vertical": "9:16",
        "original": "Оригинал",
    }.get(settings["format"], "9:16")

    subtitles_text = {
        "off": "Выкл",
        "normal": "Обычные",
        "bold": "Жирные",
    }.get(settings["subtitles"], "Выкл")

    ai_text = "Вкл" if settings["ai"] else "Выкл"

    return (
        "🎬 <b>ClipForge</b>\n\n"
        "⚙️ <b>Текущие настройки:</b>\n\n"
        f"📺 Качество: <b>{quality}p</b>\n"
        f"📱 Формат: <b>{format_text}</b>\n"
        f"💬 Субтитры: <b>{subtitles_text}</b>\n"
        f"🤖 AI улучшение: <b>{ai_text}</b>\n\n"
        "Загрузи видео после настройки."
    )


# =========================
# MAIN MENU
# =========================

def main_keyboard(settings):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"📺 Качество: {settings['quality']}p",
                callback_data="quality"
            )
        ],
        [
            InlineKeyboardButton(
                f"📱 Формат: {'9:16' if settings['format'] == 'vertical' else 'Оригинал'}",
                callback_data="format"
            )
        ],
        [
            InlineKeyboardButton(
                f"💬 Субтитры: {settings['subtitles']}",
                callback_data="subtitles"
            )
        ],
        [
            InlineKeyboardButton(
                f"🤖 AI: {'Вкл' if settings['ai'] else 'Выкл'}",
                callback_data="ai"
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 Сбросить настройки",
                callback_data="reset"
            )
        ],
    ])


# =========================
# QUALITY MENU
# =========================

def quality_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("144p", callback_data="quality_144"),
            InlineKeyboardButton("360p", callback_data="quality_360"),
        ],
        [
            InlineKeyboardButton("480p", callback_data="quality_480"),
            InlineKeyboardButton("720p", callback_data="quality_720"),
        ],
        [
            InlineKeyboardButton("1080p", callback_data="quality_1080"),
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="back"),
        ],
    ])


# =========================
# FORMAT MENU
# =========================

def format_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📱 9:16", callback_data="format_vertical"),
            InlineKeyboardButton("🎞 Оригинал", callback_data="format_original"),
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="back"),
        ],
    ])


# =========================
# SUBTITLE MENU
# =========================

def subtitles_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❌ Выкл", callback_data="sub_off"),
        ],
        [
            InlineKeyboardButton("💬 Обычные", callback_data="sub_normal"),
            InlineKeyboardButton("🔥 Жирные", callback_data="sub_bold"),
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="back"),
        ],
    ])


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    settings = get_settings(user_id)

    await update.message.reply_text(
        settings_text(settings),
        parse_mode="HTML",
        reply_markup=main_keyboard(settings),
    )


# =========================
# SETTINGS CALLBACKS
# =========================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    settings = get_settings(user_id)

    data = query.data

    # -------------------------
    # QUALITY
    # -------------------------

    if data == "quality":
        await query.edit_message_text(
            "📺 <b>Выбери качество:</b>",
            parse_mode="HTML",
            reply_markup=quality_keyboard(),
        )
        return

    if data.startswith("quality_"):
        quality = int(data.split("_")[1])
        settings["quality"] = quality

        await query.edit_message_text(
            settings_text(settings),
            parse_mode="HTML",
            reply_markup=main_keyboard(settings),
        )
        return

    # -------------------------
    # FORMAT
    # -------------------------

    if data == "format":
        await query.edit_message_text(
            "📱 <b>Выбери формат:</b>",
            parse_mode="HTML",
            reply_markup=format_keyboard(),
        )
        return

    if data == "format_vertical":
        settings["format"] = "vertical"

        await query.edit_message_text(
            settings_text(settings),
            parse_mode="HTML",
            reply_markup=main_keyboard(settings),
        )
        return

    if data == "format_original":
        settings["format"] = "original"

        await query.edit_message_text(
            settings_text(settings),
            parse_mode="HTML",
            reply_markup=main_keyboard(settings),
        )
        return

    # -------------------------
    # SUBTITLES
    # -------------------------

    if data == "subtitles":
        await query.edit_message_text(
            "💬 <b>Выбери субтитры:</b>",
            parse_mode="HTML",
            reply_markup=subtitles_keyboard(),
        )
        return

    if data == "sub_off":
        settings["subtitles"] = "off"

    elif data == "sub_normal":
        settings["subtitles"] = "normal"

    elif data == "sub_bold":
        settings["subtitles"] = "bold"

    if data in ["sub_off", "sub_normal", "sub_bold"]:
        await query.edit_message_text(
            settings_text(settings),
            parse_mode="HTML",
            reply_markup=main_keyboard(settings),
        )
        return

    # -------------------------
    # AI
    # -------------------------

    if data == "ai":
        settings["ai"] = not settings["ai"]

        await query.edit_message_text(
            settings_text(settings),
            parse_mode="HTML",
            reply_markup=main_keyboard(settings),
        )
        return

    # -------------------------
    # RESET
    # -------------------------

    if data == "reset":
        user_settings[user_id] = {
            "quality": 720,
            "format": "vertical",
            "subtitles": "off",
            "ai": False,
        }

        settings = user_settings[user_id]

        await query.edit_message_text(
            settings_text(settings),
            parse_mode="HTML",
            reply_markup=main_keyboard(settings),
        )
        return

    # -------------------------
    # BACK
    # -------------------------

    if data == "back":
        await query.edit_message_text(
            settings_text(settings),
            parse_mode="HTML",
            reply_markup=main_keyboard(settings),
        )
        return


# =========================
# DOWNLOAD VIDEO
# =========================

async def download_video(message):
    file_id = None
    extension = ".mp4"

    if message.video:
        file_id = message.video.file_id

    elif message.document:
        file_id = message.document.file_id

        filename = message.document.file_name or ""

        if "." in filename:
            extension = "." + filename.split(".")[-1]

    if not file_id:
        raise Exception("Видео не найдено")

    tg_file = await message.get_bot().get_file(file_id)

    filename = f"{uuid.uuid4().hex}{extension}"
    path = UPLOAD_DIR / filename

    await tg_file.download_to_drive(custom_path=str(path))

    if not path.exists():
        raise Exception("Файл не скачался")

    if path.stat().st_size == 0:
        raise Exception("Скачанный файл пустой")

    return path


# =========================
# CHECK VIDEO
# =========================

def check_video(input_path):
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(input_path),
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        raise Exception(
            "FFprobe error: " + result.stderr[-1000:]
        )

    return result.stdout.strip()


# =========================
# PROCESS VIDEO
# =========================

def process_video(input_path, output_path, settings):

    quality = int(settings["quality"])
    vertical = settings["format"] == "vertical"
    ai = settings["ai"]

    filters = []

    # -------------------------
    # 9:16
    # -------------------------

    if vertical:

        width = int(quality * 9 / 16)

        # Чётное число пикселей
        width = width - (width % 2)

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

    # -------------------------
    # AI / ENHANCEMENT
    # -------------------------

    if ai:
        # Это пока не нейросеть.
        # Используем улучшение резкости/детализации FFmpeg.
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

        str(output_path),
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:

        error = result.stderr[-3000:]

        raise Exception(
            f"FFmpeg error:\n{error}"
        )

    if not output_path.exists():
        raise Exception("FFmpeg не создал выходной файл")

    if output_path.stat().st_size == 0:
        raise Exception("Выходной файл пустой")


# =========================
# HANDLE VIDEO
# =========================

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = update.message
    user_id = update.effective_user.id

    settings = get_settings(user_id)

    status = await message.reply_text(
        "📥 Скачиваю видео..."
    )

    input_path = None
    output_path = None

    try:

        # -------------------------
        # DOWNLOAD
        # -------------------------

        input_path = await download_video(message)

        await status.edit_text(
            "🔍 Проверяю видео..."
        )

        # Проверяем, что FFmpeg вообще понимает файл
        check_video(input_path)

        # -------------------------
        # PROCESS
        # -------------------------

        await status.edit_text(
            "⚙️ Обрабатываю видео...\n\n"
            f"📺 Качество: {settings['quality']}p\n"
            f"📱 Формат: {'9:16' if settings['format'] == 'vertical' else 'Оригинал'}\n"
            f"💬 Субтитры: {settings['subtitles']}\n"
            f"🤖 AI: {'Вкл' if settings['ai'] else 'Выкл'}"
        )

        output_name = f"{uuid.uuid4().hex}.mp4"
        output_path = OUTPUT_DIR / output_name

        await asyncio.to_thread(
            process_video,
            input_path,
            output_path,
            settings,
        )

        # -------------------------
        # SEND
        # -------------------------

        await status.edit_text(
            "📤 Загружаю готовое видео..."
        )

        with open(output_path, "rb") as video_file:

            await message.reply_video(
                video=video_file,
                supports_streaming=True,
                caption="✅ Готово!"
            )

        await status.delete()

    except Exception as error:

        print("\n========== VIDEO ERROR ==========")
        print(error)
        print("=================================\n")

        try:
            await status.edit_text(
                "❌ Не удалось обработать видео.\n\n"
                "Попробуй другое видео или отправь его как файл."
            )
        except Exception:
            pass

    finally:

        # -------------------------
        # CLEANUP
        # -------------------------

        try:
            if input_path and input_path.exists():
                input_path.unlink()
        except Exception:
            pass

        try:
            if output_path and output_path.exists():
                output_path.unlink()
        except Exception:
            pass


# =========================
# TEXT
# =========================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🎬 Отправь мне видео.\n\n"
        "Перед этим можешь открыть /start "
        "и настроить качество, формат и другие параметры."
    )


# =========================
# ERROR HANDLER
# =========================

async def error_handler(update, context):

    print("BOT ERROR:")
    print(context.error)


# =========================
# MAIN
# =========================

def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN не найден в переменных окружения"
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
            filters.VIDEO | filters.Document.VIDEO,
            handle_video
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text
        )
    )

    app.add_error_handler(error_handler)

    print("ClipForge запущен!")

    app.run_polling()


if __name__ == "__main__":
    main()
