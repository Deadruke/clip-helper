import os
import asyncio
import threading
from flask import Flask, send_from_directory
from telegram import BotCommand, MenuButtonWebApp, WebAppInfo
from telegram.ext import Application, CommandHandler

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")

app_web = Flask(__name__, static_folder="templates")


@app_web.route("/")
def index():
    return send_from_directory("templates", "index.html")


def run_web():
    port = int(os.getenv("PORT", 10000))
    app_web.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )


async def start(update, context):
    await update.message.reply_text(
        "🎬 ClipForge готов.\n\n"
        "Открой меню бота снизу слева и нажми ClipForge."
    )


async def setup_bot(application):
    await application.bot.set_my_commands([
        BotCommand("start", "Запустить ClipForge")
    ])

    if WEBAPP_URL:
        await application.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="ClipForge",
                web_app=WebAppInfo(url=WEBAPP_URL)
            )
        )

        print("Mini App URL:", WEBAPP_URL)
    else:
        print("WARNING: WEBAPP_URL не задан")


def main():

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не найден")

    if not WEBAPP_URL:
        raise RuntimeError("WEBAPP_URL не найден")

    # Запускаем сайт Mini App
    web_thread = threading.Thread(
        target=run_web,
        daemon=True
    )

    web_thread.start()

    # Запускаем Telegram бота
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
    print("Mini App:", WEBAPP_URL)

    application.run_polling()


if __name__ == "__main__":
    main()
