import asyncio
import logging
import json
from datetime import datetime
from pathlib import Path

import aiosqlite
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters.callback_data import CallbackData

from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
PAYMENT_DETAILS = "Сбербанк 2202208214031917 Завкиддин А"
NOTIFY_CHAT_ID = -1003551675540

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DB_PATH = Path("bot_data.db")

class TournamentCallback(CallbackData, prefix="trn"):
    action: str
    t_id: int

class CreateTournament(StatesGroup):
    game = State()
    mode = State()
    max_players = State()
    entry_fee = State()
    prize_places = State()
    prizes = State()
    map_photo = State()
    description = State()

class SendLinkState(StatesGroup):
    tournament_id = State()
    link = State()

class BanUserState(StatesGroup):
    user_id = State()

class Registration(StatesGroup):
    nickname = State()
    payment_photo = State()

class FinishTournamentState(StatesGroup):
    tournament_id = State()

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS tournaments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game TEXT NOT NULL,
                mode TEXT NOT NULL,
                max_players INTEGER NOT NULL,
                entry_fee INTEGER NOT NULL,
                prize_places INTEGER NOT NULL,
                prizes TEXT NOT NULL,
                map_photo TEXT,
                description TEXT,
                link TEXT,
                status TEXT DEFAULT 'active',
                created_at TEXT NOT NULL
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS participants (
                tournament_id INTEGER,
                user_id INTEGER,
                nickname TEXT,
                payment_status TEXT DEFAULT 'pending',
                payment_photo TEXT,
                joined_at TEXT,
                PRIMARY KEY (tournament_id, user_id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id INTEGER PRIMARY KEY,
                banned_at TEXT,
                reason TEXT
            )
        ''')
        await db.commit()
    logger.info("База данных готова")

def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="🏆 Турниры")],
        [KeyboardButton(text="👤 Мои турниры")],
        [KeyboardButton(text="ℹ️ О нас и поддержка")],
    ]
    if is_admin:
        kb.append([KeyboardButton(text="🔧 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def admin_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Создать турнир")],
            [KeyboardButton(text="Отправить ссылку")],
            [KeyboardButton(text="Забанить пользователя")],
            [KeyboardButton(text="Завершить турнир")],
            [KeyboardButton(text="Вернуться в главное меню")],
        ],
        resize_keyboard=True,
    )

@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM banned_users WHERE user_id = ?", (user_id,))
        if await cursor.fetchone():
            await message.answer("Ты забанен в боте. Обратитесь к администратору.")
            return
    is_admin = user_id in ADMIN_IDS
    await message.answer("Добро пожаловать в бот турниров Brawl Stars 🎮🔥", reply_markup=main_menu(is_admin))

@dp.message(F.text == "Вернуться в главное меню")
async def back_to_main(message: Message, state: FSMContext):
    await state.clear()
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer("Главное меню", reply_markup=main_menu(is_admin))

@dp.message(F.text == "ℹ️ О нас и поддержка")
async def support_info(message: Message):
    await message.answer(
        "📌 Поддержка и информация\n\n"
        "Бот создан для организации турниров по Brawl Stars\n"
        "Админ: @zavkiddin (пиши напрямую)\n"
        "Канал с анонсами: @твой_канал\n\n"
        "Правила:\n"
        "• Честная игра без читов\n"
        "• Оплата только после регистрации\n"
        "• Решение админа окончательное"
    )

@dp.message(F.text == "👤 Мои турниры")
async def my_tournaments(message: Message):
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT t.id, t.game, t.mode, t.entry_fee, p.payment_status
            FROM participants p
            JOIN tournaments t ON p.tournament_id = t.id
            WHERE p.user_id = ? AND t.status = 'active'
        """, (user_id,))
        rows = await cursor.fetchall()

    if not rows:
        await message.answer("У тебя нет активных регистраций.")
        return

    text = "Твои турниры:\n\n"
    for row in rows:
        t_id, game, mode, fee, status = row
        status_emoji = {"pending": "⏳ Ожидание", "confirmed": "✅ Подтверждено"}.get(status, status)
        text += f"#{t_id} • {game} {mode} • {fee}₽ • {status_emoji}\n"
    await message.answer(text)

@dp.message(F.text == "🔧 Админ-панель", lambda m: m.from_user.id in ADMIN_IDS)
async def admin_panel(message: Message):
    await message.answer("Админ-панель открыта", reply_markup=admin_menu())

# ─── СОЗДАНИЕ ТУРНИРА ────────────────────────────────────────────────
@dp.message(F.text == "Создать турнир", lambda m: m.from_user.id in ADMIN_IDS)
async def start_create(message: Message, state: FSMContext):
    await state.set_state(CreateTournament.game)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Brawl Stars")]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer("Выбери игру:", reply_markup=kb)

@dp.message(CreateTournament.game)
async def process_game(message: Message, state: FSMContext):
    await state.update_data(game=message.text)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="1v1"), KeyboardButton(text="3v3"), KeyboardButton(text="Showdown")]], resize_keyboard=True)
    await state.set_state(CreateTournament.mode)
    await message.answer("Выбери режим:", reply_markup=kb)

@dp.message(CreateTournament.mode)
async def process_mode(message: Message, state: FSMContext):
    await state.update_data(mode=message.text)
    await state.set_state(CreateTournament.max_players)
    await message.answer("Макс. количество игроков (число):")

@dp.message(CreateTournament.max_players)
async def process_max_players(message: Message, state: FSMContext):
    try:
        num = int(message.text)
        if num < 2:
            raise ValueError
        await state.update_data(max_players=num)
        await state.set_state(CreateTournament.entry_fee)
        await message.answer("Взнос за участие (₽):")
    except:
        await message.answer("Введи нормальное число ≥ 2")

@dp.message(CreateTournament.entry_fee)
async def process_entry_fee(message: Message, state: FSMContext):
    try:
        fee = int(message.text)
        if fee < 10:
            raise ValueError
        await state.update_data(entry_fee=fee)
        await state.set_state(CreateTournament.prize_places)
        await message.answer("Количество призовых мест (1–5):")
    except:
        await message.answer("Введи сумму ≥ 10")

@dp.message(CreateTournament.prize_places)
async def process_prize_places(message: Message, state: FSMContext):
    try:
        places = int(message.text)
        if not 1 <= places <= 5:
            raise ValueError
        await state.update_data(prize_places=places, prizes=[], current_prize=1)
        await state.set_state(CreateTournament.prizes)
        await message.answer("Приз за 1 место (₽):", reply_markup=ReplyKeyboardRemove())
    except:
        await message.answer("Введи от 1 до 5")

@dp.message(CreateTournament.prizes)
async def process_prizes(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        prize = int(message.text)
        prizes = data.get("prizes", [])
        prizes.append(prize)
        current = data.get("current_prize", 1) + 1
        await state.update_data(prizes=prizes, current_prize=current)

        if current <= data["prize_places"]:
            await message.answer(f"Приз за {current} место (₽):")
        else:
            kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Да"), KeyboardButton(text="Нет")]], resize_keyboard=True)
            await state.set_state(CreateTournament.map_photo)
            await message.answer("Прикрепить фото карты? (Да/Нет)", reply_markup=kb)
    except:
        await message.answer("Введи число")

@dp.message(CreateTournament.map_photo)
async def process_map_photo_choice(message: Message, state: FSMContext):
    if message.text == "Да":
        await message.answer("Пришли фото карты:")
        return
    elif message.text == "Нет":
        await state.update_data(map_photo=None)
        await state.set_state(CreateTournament.description)
        await message.answer("Описание / анонс турнира? (можно написать 'нет')")
    else:
        await message.answer("Выбери Да или Нет")

@dp.message(CreateTournament.map_photo, F.photo)
async def process_map_photo_upload(message: Message, state: FSMContext):
    await state.update_data(map_photo=message.photo[-1].file_id)
    await state.set_state(CreateTournament.description)
    await message.answer("Описание / анонс турнира? (можно 'нет')")

@dp.message(CreateTournament.description)
async def process_description(message: Message, state: FSMContext):
    text = message.text.strip()
    description = None if text.lower() in ("нет", "не нужно", "пропустить") else text
    await state.update_data(description=description)

    data = await state.get_data()
    prizes = data.get('prizes', [])
    prizes_json = json.dumps(prizes)
    now = datetime.utcnow().isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO tournaments 
            (game, mode, max_players, entry_fee, prize_places, prizes, map_photo, description, created_at) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data.get('game'), data.get('mode'), data.get('max_players'),
                data.get('entry_fee'), data.get('prize_places'), prizes_json,
                data.get('map_photo'), description, now
            )
        )
        t_id = cursor.lastrowid
        await db.commit()

    # Сообщение админу
    admin_text = (
        f"✅ Турнир #{t_id} создан!\n\n"
        f"🎮 {data.get('game')} • {data.get('mode')}\n"
        f"💰 Взнос: {data.get('entry_fee')} ₽\n"
        f"👥 До {data.get('max_players')} игроков\n"
        f"🏆 Призы: {' • '.join(f'{i+1} — {p}₽' for i, p in enumerate(prizes))}\n"
    )
    if description:
        admin_text += f"\n📢 {description}\n"

    if photo := data.get('map_photo'):
        await message.answer_photo(photo, caption=admin_text, reply_markup=admin_menu())
    else:
        await message.answer(admin_text, reply_markup=admin_menu())

    # Уведомление в канал
    notify_text = (
        f"🔥 Новый турнир #{t_id} открыт! 🔥\n\n"
        f"🎮 {data.get('game')} • {data.get('mode')}\n"
        f"💰 Взнос: {data.get('entry_fee')} ₽\n"
        f"👥 Макс: {data.get('max_players')}\n"
        f"🏆 Призы: {' • '.join(f'{i+1} — {p}₽' for i, p in enumerate(prizes))}\n"
    )
    if description:
        notify_text += f"\n📢 {description}\n"
    notify_text += "\nРегистрация в боте 👉 @твой_бот"

    try:
        if photo := data.get('map_photo'):
            await bot.send_photo(NOTIFY_CHAT_ID, photo, caption=notify_text)
        else:
            await bot.send_message(NOTIFY_CHAT_ID, notify_text)
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления в канал: {e}")

    await state.clear()

# ─── ОТПРАВКА ССЫЛКИ ─────────────────────────────────────────────────
@dp.message(F.text == "Отправить ссылку", lambda m: m.from_user.id in ADMIN_IDS)
async def start_send_link(message: Message, state: FSMContext):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id FROM tournaments WHERE status = 'active'")
        active = await cursor.fetchall()
    if not active:
        await message.answer("Нет активных турниров.")
        return

    text = "Введи ID активного турнира:\nАктивные: " + ", ".join(str(row[0]) for row in active)
    await state.set_state(SendLinkState.tournament_id)
    await message.answer(text)

@dp.message(SendLinkState.tournament_id)
async def process_link_tournament_id(message: Message, state: FSMContext):
    try:
        t_id = int(message.text)
        await state.update_data(t_id=t_id)
        await state.set_state(SendLinkState.link)
        await message.answer("Введи ссылку (на лобби, чат и т.д.):")
    except:
        await message.answer("Неверный ID. Попробуй снова.")

@dp.message(SendLinkState.link)
async def process_link_text(message: Message, state: FSMContext):
    data = await state.get_data()
    t_id = data['t_id']
    link = message.text.strip()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tournaments SET link = ? WHERE id = ?", (link, t_id))
        await db.commit()

    await message.answer(f"Ссылка для турнира #{t_id} установлена: {link}")
    await state.clear()

    # Можно сразу отправить в канал или участникам — если нужно, добавь здесь

# ─── БАН ПОЛЬЗОВАТЕЛЯ ────────────────────────────────────────────────
@dp.message(F.text == "Забанить пользователя", lambda m: m.from_user.id in ADMIN_IDS)
async def start_ban_user(message: Message, state: FSMContext):
    await state.set_state(BanUserState.user_id)
    await message.answer("Введи ID пользователя для бана:")

@dp.message(BanUserState.user_id)
async def process_ban_user_id(message: Message, state: FSMContext):
    try:
        user_id = int(message.text)
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO banned_users (user_id, banned_at, reason) VALUES (?, ?, ?)",
                (user_id, now, "Забанен админом")
            )
            await db.commit()
        await message.answer(f"Пользователь {user_id} забанен.")
    except:
        await message.answer("Неверный ID. Введи число.")
    await state.clear()

# ─── Запуск ──────────────────────────────────────────────────────────
async def main():
    await init_db()
    logger.info("Бот стартует...")
    while True:
        try:
            await dp.start_polling(bot, drop_pending_updates=True, polling_timeout=25)
        except Exception as e:
            logger.exception("Polling упал")
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
