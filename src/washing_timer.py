"""
Washing Timer Bot - Основной модуль

Telegram бот для установки множественных таймеров стирки с уведомлениями.
Поддерживает до 10 одновременных таймеров на пользователя.

Версия: 2.0.0
Совместимость: python-telegram-bot v20+
"""

import logging
import os
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Any

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# Настройки бота
MAX_TIMERS_PER_USER = 10

# Определяем пути проекта
project_root = Path(__file__).parent.parent
logs_dir = project_root / "logs"
config_dir = project_root / "config"

# Создаём папку logs если её нет
logs_dir.mkdir(exist_ok=True)

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(logs_dir / "bot.log"),
        logging.StreamHandler()
    ]
)

# Установка уровней логирования для внешних библиотек (Context7 рекомендации)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING) 
logging.getLogger('apscheduler').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Новая структура для хранения множественных таймеров
# Формат: {user_id: {timer_id: {"description": str, "end_time": datetime, "job": Job}}}
active_timers: Dict[int, Dict[str, Dict[str, Any]]] = {}

def get_user_timers(user_id: int) -> Dict[str, Dict[str, Any]]:
    """Получить все таймеры пользователя"""
    return active_timers.setdefault(user_id, {})

def add_timer(user_id: int, timer_id: str, description: str, end_time: datetime, job: Any) -> None:
    """Добавить новый таймер для пользователя"""
    user_timers = get_user_timers(user_id)
    user_timers[timer_id] = {
        "description": description,
        "end_time": end_time,
        "job": job,
        "created_at": datetime.now()
    }

def remove_timer(user_id: int, timer_id: str) -> bool:
    """Удалить таймер пользователя. Возвращает True если таймер был найден и удален"""
    user_timers = get_user_timers(user_id)
    if timer_id in user_timers:
        # Отменяем job если он еще активен
        job = user_timers[timer_id].get("job")
        if job:
            try:
                job.schedule_removal()
            except Exception as e:
                logger.warning(f"Не удалось отменить job {timer_id}: {e}")
        
        del user_timers[timer_id]
        
        # Если у пользователя не осталось таймеров, удаляем его из словаря
        if not user_timers:
            active_timers.pop(user_id, None)
            
        return True
    return False

def get_timer_count(user_id: int) -> int:
    """Получить количество активных таймеров пользователя"""
    return len(get_user_timers(user_id))

def format_timer_list(user_id: int, page: int = 0, items_per_page: int = 5) -> Tuple[str, List[List[InlineKeyboardButton]]]:
    """
    Форматирует список таймеров для отображения с пагинацией
    Возвращает (текст_сообщения, клавиатура)
    """
    user_timers = get_user_timers(user_id)
    
    if not user_timers:
        return "ℹ️ У вас нет активных таймеров", [[InlineKeyboardButton("➕ Создать таймер", callback_data="new_timer")]]
    
    # Сортируем таймеры по времени создания
    sorted_timers = sorted(
        user_timers.items(), 
        key=lambda x: x[1]["created_at"]
    )
    
    total_count = len(sorted_timers)
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_timers = sorted_timers[start_idx:end_idx]
    
    # Формируем текст
    message_parts = [f"⏰ *Активных таймеров: {total_count}*\n"]
    
    for i, (timer_id, timer_info) in enumerate(page_timers, start_idx + 1):
        description = timer_info["description"]
        end_time = timer_info["end_time"]
        now = datetime.now()
        
        if end_time > now:
            remaining = end_time - now
            remaining_str = f"{remaining.seconds // 60}мин {remaining.seconds % 60}сек"
            status = f"⏳ осталось {remaining_str}"
        else:
            status = "⏰ должен был завершиться"
            
        message_parts.append(f"{i}. *#{timer_id}*: {description}")
        message_parts.append(f"   {status}")
    
    # Формируем клавиатуру
    keyboard = []
    
    # Кнопки управления таймерами (по 2 в ряд)
    timer_buttons = []
    for timer_id, _ in page_timers:
        timer_buttons.append(InlineKeyboardButton(f"❌ #{timer_id}", callback_data=f"cancel_timer_{timer_id}"))
        
        if len(timer_buttons) == 2:
            keyboard.append(timer_buttons)
            timer_buttons = []
    
    if timer_buttons:  # Добавляем оставшиеся кнопки
        keyboard.append(timer_buttons)
    
    # Кнопки пагинации
    pagination_buttons = []
    if page > 0:
        pagination_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"timers_page_{page-1}"))
    if end_idx < total_count:
        pagination_buttons.append(InlineKeyboardButton("➡️ Далее", callback_data=f"timers_page_{page+1}"))
    
    if pagination_buttons:
        keyboard.append(pagination_buttons)
    
    # Кнопки действий
    keyboard.append([
        InlineKeyboardButton("❌ Отменить все", callback_data="cancel_all_timers"),
        InlineKeyboardButton("➕ Новый", callback_data="new_timer")
    ])
    
    return "\n".join(message_parts), keyboard


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    username = update.effective_user.first_name or "Пользователь"
    
    logger.info(f"Пользователь {username} (ID: {user_id}) вызвал команду /start")
    
    keyboard = [
        [InlineKeyboardButton("📖 Помощь", callback_data="help")],
        [InlineKeyboardButton("⏱️ Примеры времени", callback_data="examples")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Показываем количество активных таймеров пользователя
    timer_count = get_timer_count(user_id)
    max_timers = MAX_TIMERS_PER_USER
    
    status_text = ""
    if timer_count > 0:
        status_text = f"⏰ У вас {timer_count}/{max_timers} активных таймеров\n\n"
    
    await update.message.reply_text(
        "🧺 *Washing Timer Bot - Множественные таймеры!*\n\n"
        f"{status_text}"
        "Я помогу отследить несколько процессов стирки одновременно.\n\n"
        "📝 *Как использовать:*\n"
        "• Для времени до часа: просто введите минуты (`35`, `90`)\n"
        "• Для времени больше часа: формат *ЧЧММ* (`0145`, `0200`)\n"
        f"• Можно создать до {max_timers} таймеров одновременно\n\n"
        "🆕 *Новые возможности:*\n"
        "• Множественные таймеры\n"
        "• Индивидуальная отмена\n"
        "• Удобное управление списком\n\n"
        "💡 Используйте кнопки ниже для получения дополнительной информации",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /help"""
    user_id = update.effective_user.id
    timer_count = get_timer_count(user_id)
    max_timers = MAX_TIMERS_PER_USER
    
    help_text = (
        "🤖 *Washing Timer Bot - Справка (Множественные таймеры)*\n\n"
        f"📊 *Ваши таймеры:* {timer_count}/{max_timers}\n\n"
        "*Доступные команды:*\n"
        "/start - Запустить бота\n"
        "/help - Показать эту справку\n"
        "/cancel - Отменить ВСЕ активные таймеры\n"
        "/status - Показать все активные таймеры\n\n"
        "*🆕 Новые возможности:*\n"
        f"• До {max_timers} одновременных таймеров\n"
        "• Индивидуальная отмена таймеров\n"
        "• Удобный список с пагинацией\n"
        "• Уникальные ID для каждого таймера\n\n"
        "*Форматы времени:*\n"
        "• *Минуты:* 1-999 (для времени до 16+ часов)\n"
        "• *ЧЧММ:* 4 цифры (ЧЧ: часы 00-23, ММ: минуты 00-59)\n\n"
        "*Примеры использования:*\n"
        "• `30` = 30 минут\n"
        "• `90` = 1 час 30 минут\n"
        "• `0145` = 1 час 45 минут\n"
        "• `0200` = 2 часа\n\n"
        "*💡 Сценарии применения:*\n"
        "• Несколько стиральных машин\n"
        "• Разные этапы стирки (стирка + сушка)\n"
        "• Параллельные процессы в доме"
    )
    
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def cancel_timer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отмена всех активных таймеров пользователя"""
    user_id = update.effective_user.id
    
    timer_count = get_timer_count(user_id)
    
    if timer_count > 0:
        # Отменяем все таймеры пользователя
        user_timers = get_user_timers(user_id).copy()  # Копируем для безопасной итерации
        
        cancelled_count = 0
        for timer_id in user_timers:
            if remove_timer(user_id, timer_id):
                cancelled_count += 1
        
        keyboard = [[InlineKeyboardButton("➕ Новый таймер", callback_data="new_timer")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"❌ *Отменено таймеров: {cancelled_count}*\n\n"
            "Вы можете установить новые таймеры: введите минуты (35) или время в формате ЧЧММ (0135)",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        logger.info(f"Пользователь {user_id} отменил {cancelled_count} таймеров")
    else:
        keyboard = [[InlineKeyboardButton("➕ Создать таймер", callback_data="new_timer")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "ℹ️ У вас нет активных таймеров для отмены",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )


async def status_timer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Проверка статуса всех активных таймеров"""
    user_id = update.effective_user.id
    user_timers = get_user_timers(user_id)
    
    if user_timers:
        # Формируем список таймеров
        timer_list = []
        for timer_id, timer_info in user_timers.items():
            description = timer_info["description"]
            timer_list.append(f"⏰ #{timer_id}: {description}")
        
        timers_text = "\n".join(timer_list)
        timer_count = len(user_timers)
        
        keyboard = [
            [InlineKeyboardButton("📋 Управление таймерами", callback_data="list_timers")],
            [InlineKeyboardButton("❌ Отменить все", callback_data="cancel_all_timers")],
            [InlineKeyboardButton("➕ Новый таймер", callback_data="new_timer")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"⏳ *Активных таймеров: {timer_count}*\n\n"
            f"{timers_text}\n\n"
            "Я уведомлю вас о завершении каждого таймера! 🔔",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    else:
        keyboard = [[InlineKeyboardButton("➕ Создать таймер", callback_data="new_timer")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "ℹ️ У вас нет активных таймеров\n\n"
            "Введите минуты (35) или время в формате ЧЧММ (0135), чтобы запустить новый таймер",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )


def validate_time_format(time_str: str) -> Optional[Tuple[int, int]]:
    """Валидация формата времени"""
    # Проверяем, что строка состоит только из цифр
    if not re.match(r'^\d+$', time_str):
        return None
    
    try:
        # Если 1-3 цифры, то это минуты
        if len(time_str) <= 3:
            minutes = int(time_str)
            
            # Проверяем разумные ограничения для минут (максимум 999 минут = ~16 часов)
            if not (1 <= minutes <= 999):
                return None
                
            # Конвертируем в часы и минуты
            hours = minutes // 60
            remaining_minutes = minutes % 60
            
            return hours, remaining_minutes
            
        # Если 4 цифры, то это формат ЧЧММ
        elif len(time_str) == 4:
            hours = int(time_str[:2])
            minutes = int(time_str[2:])
            
            # Проверяем диапазоны
            if not (0 <= hours <= 23):
                return None
            if not (0 <= minutes <= 59):
                return None
            
            # Проверяем, что время не равно 0
            if hours == 0 and minutes == 0:
                return None
                
            return hours, minutes
            
        # Более 4 цифр - неверный формат
        else:
            return None
            
    except ValueError:
        return None


async def timer_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Современный колбэк для завершения таймера
    Использует data для передачи информации о таймере
    """
    job = context.job
    user_id = job.user_id
    timer_data = job.data  # Содержит {timer_id, description}
    
    timer_id = timer_data["timer_id"]
    description = timer_data["description"]
    
    # Удаляем таймер из активных
    timer_removed = remove_timer(user_id, timer_id)
    
    try:
        # Проверяем количество оставшихся таймеров
        remaining_count = get_timer_count(user_id)
        
        # Формируем сообщение
        message_text = f"✅ *Таймер завершен!*\n\n"
        message_text += f"📝 Описание: {description}\n\n"
        message_text += "🧼 Можете забирать бельё из стиральной машины!\n\n"
        
        if remaining_count > 0:
            message_text += f"⏰ У вас еще {remaining_count} активных таймера(ов)\n\n"
            
        # Добавляем кнопки управления
        keyboard = []
        if remaining_count > 0:
            keyboard.append([InlineKeyboardButton("📋 Мои таймеры", callback_data="list_timers")])
        keyboard.append([InlineKeyboardButton("➕ Новый таймер", callback_data="new_timer")])
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        await context.bot.send_message(
            chat_id=user_id,
            text=message_text,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        
        logger.info(f"Отправлено уведомление о завершении таймера {timer_id} пользователю {user_id}")
        
    except Exception as e:
        logger.error(f"Ошибка отправки напоминания пользователю {user_id}: {e}")


async def handle_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка ввода времени - теперь поддерживает множественные таймеры"""
    user_id = update.effective_user.id
    username = update.effective_user.first_name or "Пользователь"
    time_str = update.message.text.strip()
    
    logger.info(f"Пользователь {username} (ID: {user_id}) ввел время: {time_str}")
    
    # Проверяем количество активных таймеров
    timer_count = get_timer_count(user_id)
    max_timers = MAX_TIMERS_PER_USER  # Ограничение из конфигурации
    
    if timer_count >= max_timers:
        keyboard = [
            [InlineKeyboardButton("📋 Мои таймеры", callback_data="list_timers")],
            [InlineKeyboardButton("❌ Отменить все", callback_data="cancel_all_timers")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"⚠️ *Достигнуто максимальное количество таймеров!*\n\n"
            f"У вас уже {timer_count}/{max_timers} активных таймеров.\n\n"
            "Отмените некоторые таймеры, чтобы создать новые.",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        return
    
    # Валидация времени
    time_data = validate_time_format(time_str)
    if time_data is None:
        await update.message.reply_text(
            "❌ *Неверный формат времени!*\n\n"
            "📝 *Правильные форматы:*\n"
            "• *Минуты:* 1-999 (например: `30`, `90`)\n"
            "• *ЧЧММ:* 4 цифры (например: `0145`, `0200`)\n\n"
            "*Примеры:*\n"
            "• `30` = 30 минут\n"
            "• `90` = 1 час 30 минут\n"
            "• `0145` = 1 час 45 минут\n"
            "• `0200` = 2 часа",
            parse_mode="Markdown"
        )
        logger.warning(f"Неверный формат времени от пользователя {user_id}: {time_str}")
        return
    
    hours, minutes = time_data
    total_seconds = hours * 3600 + minutes * 60
    
    # Создаем строку для отображения времени
    time_display = f"{hours} ч {minutes} мин" if hours > 0 else f"{minutes} мин"
    
    # Генерируем уникальный ID для таймера
    timer_id = str(uuid.uuid4())[:8]  # Короткий ID для удобства
    
    # Вычисляем время завершения
    end_time = datetime.now() + timedelta(seconds=total_seconds)
    end_time_str = end_time.strftime("%H:%M")
    
    # Создаем описание таймера
    description = f"{time_display} (до {end_time_str})"
    
    # Создаем джоб для напоминания с передачей данных
    job = context.job_queue.run_once(
        timer_callback,
        total_seconds,
        user_id=user_id,
        name=f"timer_{user_id}_{timer_id}",
        data={
            "timer_id": timer_id,
            "description": description,
            "duration": time_display
        }
    )
    
    # Сохраняем информацию о таймере
    add_timer(user_id, timer_id, description, end_time, job)
    
    # Создаем клавиатуру с кнопками управления
    new_timer_count = get_timer_count(user_id)
    keyboard = [
        [InlineKeyboardButton(f"📋 Мои таймеры ({new_timer_count})", callback_data="list_timers")],
        [InlineKeyboardButton("➕ Еще таймер", callback_data="new_timer")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"⏳ *Таймер #{timer_id} запущен!*\n\n"
        f"📅 Время: {time_display}\n"
        f"🕒 Завершится в: {end_time_str}\n"
        f"📊 Всего активных: {new_timer_count}/{max_timers}\n\n"
        "Я напомню вам, когда стирка будет готова! 🔔",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
    
    logger.info(f"Таймер {timer_id} установлен для пользователя {user_id} на {total_seconds} секунд")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработка нажатий на инлайн кнопки - расширено для множественных таймеров
    Соответствует современным практикам python-telegram-bot
    """
    query = update.callback_query
    
    # Всегда отвечаем на callback query для улучшения UX
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    logger.info(f"Пользователь {user_id} нажал кнопку: {data}")
    
    # === НОВЫЕ ОБРАБОТЧИКИ ДЛЯ МНОЖЕСТВЕННЫХ ТАЙМЕРОВ ===
    
    if data == "list_timers" or data.startswith("timers_page_"):
        # Показать список таймеров с пагинацией
        page = 0
        if data.startswith("timers_page_"):
            page = int(data.split("_")[-1])
            
        message_text, keyboard = format_timer_list(user_id, page)
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await query.edit_message_text(
                message_text,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        except Exception:
            await query.message.reply_text(
                message_text,
                parse_mode="Markdown", 
                reply_markup=reply_markup
            )
    
    elif data.startswith("cancel_timer_"):
        # Отменить конкретный таймер
        timer_id = data.replace("cancel_timer_", "")
        
        if remove_timer(user_id, timer_id):
            await query.answer(f"⏰ Таймер #{timer_id} отменен")
            
            # Обновляем список таймеров
            message_text, keyboard = format_timer_list(user_id, 0)
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.edit_message_text(
                    message_text,
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
            except Exception:
                await query.message.reply_text(
                    message_text,
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
            
            logger.info(f"Пользователь {user_id} отменил таймер {timer_id}")
        else:
            await query.answer("❌ Таймер не найден", show_alert=True)
    
    elif data == "cancel_all_timers":
        # Отменить все таймеры
        timer_count = get_timer_count(user_id)
        
        if timer_count > 0:
            user_timers = get_user_timers(user_id).copy()
            cancelled_count = 0
            
            for timer_id in user_timers:
                if remove_timer(user_id, timer_id):
                    cancelled_count += 1
            
            keyboard = [[InlineKeyboardButton("➕ Новый таймер", callback_data="new_timer")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.edit_message_text(
                    f"❌ *Отменено таймеров: {cancelled_count}*\n\n"
                    "Введите время для создания нового таймера",
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
            except Exception:
                await query.message.reply_text(
                    f"❌ *Отменено таймеров: {cancelled_count}*\n\n"
                    "Введите время для создания нового таймера",
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
            
            await query.answer(f"✅ Отменено {cancelled_count} таймеров")
            logger.info(f"Пользователь {user_id} отменил все таймеры ({cancelled_count})")
        else:
            await query.answer("У вас нет активных таймеров", show_alert=True)
    
    elif data == "new_timer":
        # Предложить создать новый таймер
        timer_count = get_timer_count(user_id)
        max_timers = MAX_TIMERS_PER_USER
        
        if timer_count >= max_timers:
            await query.answer(f"Максимум {max_timers} таймеров", show_alert=True)
        else:
            try:
                await query.edit_message_text(
                    f"⏰ *Создание нового таймера*\n\n"
                    f"Активных таймеров: {timer_count}/{max_timers}\n\n"
                    "📝 *Введите время:*\n"
                    "• Минуты: `30`, `45`, `90`\n"
                    "• ЧЧММ: `0130`, `0200`\n\n"
                    "Просто напишите время в чат!",
                    parse_mode="Markdown"
                )
            except Exception:
                await query.message.reply_text(
                    f"⏰ *Создание нового таймера*\n\n"
                    f"Активных таймеров: {timer_count}/{max_timers}\n\n"
                    "📝 *Введите время:*\n"
                    "• Минуты: `30`, `45`, `90`\n"
                    "• ЧЧММ: `0130`, `0200`\n\n"
                    "Просто напишите время в чат!",
                    parse_mode="Markdown"
                )
    
    # === СТАРЫЕ ОБРАБОТЧИКИ (ОБНОВЛЕННЫЕ) ===
    
    elif data == "help":
        help_text = (
            "🤖 *Washing Timer Bot - Справка*\n\n"
            "*Форматы времени:*\n"
            "• *Минуты:* 1-999 (например: `30`, `90`)\n"
            "• *ЧЧММ:* 4 цифры (ЧЧ: часы 00-23, ММ: минуты 00-59)\n\n"
            "*Команды:*\n"
            "/start - Запустить бота\n"
            "/help - Справка\n"
            "/cancel - Отменить таймер\n"
            "/status - Статус таймера"
        )
        try:
            await query.edit_message_text(help_text, parse_mode="Markdown")
        except Exception:
            await query.answer("Справка отправлена в чат")
            await query.message.reply_text(help_text, parse_mode="Markdown")
        
    elif data == "examples":
        examples_text = (
            "⏱️ *Примеры времени:*\n\n"
            "*Упрощённый формат (минуты):*\n"
            "`15` = 15 минут\n"
            "`30` = 30 минут\n"
            "`45` = 45 минут\n"
            "`60` = 1 час\n"
            "`90` = 1 час 30 минут\n"
            "`120` = 2 часа\n\n"
            "*Полный формат (ЧЧММ):*\n"
            "`0130` = 1 час 30 минут\n"
            "`0200` = 2 часа\n"
            "`0300` = 3 часа\n\n"
            "Просто введите время в чат! 💬"
        )
        try:
            await query.edit_message_text(examples_text, parse_mode="Markdown")
        except Exception:
            await query.answer("Примеры отправлены в чат")
            await query.message.reply_text(examples_text, parse_mode="Markdown")



async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик ошибок - обрабатывает все ошибки из любых обработчиков
    Соответствует актуальным практикам python-telegram-bot v20+
    """
    error = context.error
    error_msg = str(error)
    
    # Логируем информацию об ошибке для диагностики
    logger.error(
        f"Exception while handling an update: {error}",
        exc_info=error
    )
    
    # Игнорируем некритичные ошибки
    if "Message is not modified" in error_msg:
        logger.warning(f"Попытка изменить уже измененное сообщение")
        return
    
    if "Conflict: terminated by other getUpdates request" in error_msg:
        logger.warning("Обнаружен другой экземпляр бота. Завершение работы...")
        return
    
    # Для критичных ошибок отправляем уведомление пользователю
    if update and update.effective_message:
        try:
            error_text = (
                "😔 Произошла временная ошибка. "
                "Попробуйте ещё раз через несколько секунд.\n\n"
                f"ID ошибки для поддержки: {hash(str(error)) % 10000:04d}"
            )
            await update.effective_message.reply_text(error_text)
        except Exception as send_error:
            logger.error(f"Не удалось отправить сообщение об ошибке: {send_error}")
    
    # Если это критическая ошибка, можно добавить дополнительную логику
    # например, отправку в систему мониторинга


def main() -> None:
    """Основная функция запуска бота"""
    # Загружаем переменные окружения из .env файла в папке config
    env_path = config_dir / ".env"
    load_dotenv(env_path)
    
    # Получение токена из переменной окружения
    token = os.getenv('BOT_TOKEN')
    if not token:
        logger.error("Токен бота не найден! Установите переменную окружения BOT_TOKEN")
        print("❌ Ошибка: Токен бота не найден!")
        print("Установите переменную окружения BOT_TOKEN:")
        print("export BOT_TOKEN='ваш_токен_бота'")
        return
    
    # Создание приложения
    application = Application.builder().token(token).build()
    
    # Добавление обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cancel", cancel_timer))
    application.add_handler(CommandHandler("status", status_timer))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_time))
    
    # Добавление обработчика ошибок
    application.add_error_handler(error_handler)
    
    logger.info("🚀 Washing Timer Bot запущен и готов к работе!")
    print("🚀 Washing Timer Bot запущен и готов к работе!")
    print("📝 Логи сохраняются в файл logs/bot.log")
    print("⏹️  Для остановки нажмите Ctrl+C")
    
    # Запуск бота с современной обработкой завершения
    try:
        # Используем современные параметры для лучшей производительности
        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=['message', 'callback_query']  # Оптимизация: получаем только нужные обновления
        )
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки. Завершение работы бота...")
        print("\n👋 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}")
        print(f"❌ Критическая ошибка: {e}")
    finally:
        # Очищаем активные таймеры при завершении
        total_timers = sum(len(user_timers) for user_timers in active_timers.values())
        if total_timers > 0:
            logger.info(f"Очистка {total_timers} активных таймеров при завершении")
            active_timers.clear()
        
        logger.info("Бот завершил работу")
        print("✅ Бот корректно завершен")


if __name__ == "__main__":
    main()
