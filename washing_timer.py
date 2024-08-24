import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)
import asyncio

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# Функция, которая будет обрабатывать команду /start
async def start(update: Update, context) -> None:
    logger.info(
        "Пользователь %s вызвал команду /" "start", update.effective_user.first_name
    )
    # Приветственное сообщение при запуске бота
    await update.message.reply_text(
        "👋 Привет!\n\n"
        "Я помогу тебе напомнить о завершении стирки 🧺\n\n"
        "Введи время в формате *ЧЧММ* "
        "(например, 0320 для 3 часов и 20 минут) ⏱️",
        parse_mode="Markdown",
    )


# Функция, которая будет обрабатывать текстовые сообщения с вводом времени
async def handle_time(update: Update, context) -> None:
    try:
        # Получаем текст сообщения от пользователя
        time_str = update.message.text
        logger.info(
            "Пользователь %s ввел время: %s", update.effective_user.first_name, time_str
        )

        # Преобразуем введенное время в часы и минуты
        hours = int(time_str[:2])
        minutes = int(time_str[2:])
        logger.info("Преобразованное время: %d часов и %d минут", hours, minutes)

        # Вычисляем общее время в секундах
        total_time_seconds = hours * 3600 + minutes * 60

        # Сообщаем пользователю, что таймер установлен и начался отсчет
        await update.message.reply_text(
            f"⏳ Таймер запущен на *{hours} часов и {minutes} минут* 🕰️\n\n"
            "Я напомню тебе, когда стирка будет завершена 😉",
            parse_mode="Markdown",
        )
        logger.info("Таймер запущен на %d секунд", total_time_seconds)

        # Ждем окончания заданного времени
        await asyncio.sleep(total_time_seconds)

        # Напоминание пользователю об окончании времени
        await update.message.reply_text(
            "✅ *Время стирки подошло к концу!* "
            "Можешь забирать белье из стиральной машины 🧼",
            parse_mode="Markdown",
        )
        logger.info(
            "Отправлено напоминание пользователю %s о завершении стирки",
            update.effective_user.first_name,
        )

    except ValueError:
        # Сообщение об ошибке, если формат времени введен неправильно
        await update.message.reply_text(
            "❌ *Неверный формат времени* 😅\n\n"
            "Пожалуйста, введи время в формате *ЧЧММ* 🕰️\n\n"
            "Например, 0320 для 3 часов и 20 минут ⏱️",
            parse_mode="Markdown",
        )
        logger.error(
            "Ошибка формата времени: %s от пользователя %s",
            time_str,
            update.effective_user.first_name,
        )


# Основная функция для запуска бота
def main() -> None:
    # Создаем экземпляр приложения и добавляем токен вашего бота
    application = (
        Application.builder()
        .token("6843156829:AAFc9qweDJUQFkCxZk-SZ7QW087tBlg5_Oc")
        .build()
    )

    # Обработка команды /start: добавляем команду, которая будет вызвана
    # при вводе /start
    application.add_handler(CommandHandler("start", start))

    # Обработка текстовых сообщений, которые не являются командами
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_time)
    )

    # Сообщаем пользователю, что бот готов к работе, и запускаем его
    logger.info("🚀 Бот запущен и готов к приему сообщений")
    print("🚀 Бот запущен и готов к приему сообщений")

    # Запуск метода polling, который будет опрашивать сервер Telegram
    # на наличие новых сообщений
    application.run_polling(timeout=0)
    # Увеличиваем время ожидания до 60 секунд


if __name__ == "__main__":
    main()
