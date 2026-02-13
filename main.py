import asyncio
import logging
import json
import aiosqlite
from datetime import datetime
from pathlib import Path

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters.callback_data import CallbackData

from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
PAYMENT_DETAILS = "Сбербанк 2202208214031917 Завкиддин А"
NOTIFY_CHAT_ID = -1003551675540  # твой канал

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DB_PATH = Path("bot_data.db")

# ─── Callback Data ───────────────────────────────────────────────
class TournamentCallback(CallbackData, prefix="trn"):
    action: str
    t_id: int

# ─── States ──────────────────────────────────────────────────────
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

class Registration(StatesGroup):
    nickname = State()
    payment_photo = State()

class FinishTournamentState(StatesGroup):
    tournament_id = State()

# ─── Инициализация БД ───────────────────────────────────────────
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
                prizes TEXT NOT NULL,           -- json string: "[100, 70, 30]"
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
        await db.commit()
    logger.info("База данных готова")

# ─── Меню ────────────────────────────────────────────────────────
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
            [KeyboardButton(text="Завершить турнир")],
            [KeyboardButton(text="Вернуться в главное меню")],
        ],
        resize_keyboard=True,
    )

# ─── Start & Back ────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message):
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer("Привет! Это бот турниров 🔥", reply_markup=main_menu(is_admin))

@dp.message(F.text == "Вернуться в главное меню")
async def back_to_main(message: Message, state: FSMContext):
    await state.clear()
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer("Главное меню", reply_markup=main_menu(is_admin))

# ─── Список активных турниров ───────────────────────────────────
@dp.message(F.text == "🏆 Турниры")
async def show_active_tournaments(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT id, game, mode, max_players, entry_fee 
            FROM tournaments 
            WHERE status = 'active'
            ORDER BY created_at DESC
        """)
        tournaments = await cursor.fetchall()

    if not tournaments:
        await message.answer("Пока нет активных турниров 😔")
        return

    builder = InlineKeyboardBuilder()

    for row in tournaments:
        t_id, game, mode, max_p, fee = row
        builder.button(
            text=f"#{t_id} | {game} {mode} | {fee}₽",
            callback_data=TournamentCallback(action="show", t_id=t_id).pack()
        )

    builder.adjust(1)  # по одной кнопке в ряд

    await message.answer("Активные турниры:", reply_markup=builder.as_markup())

@dp.callback_query(TournamentCallback.filter(F.action == "show"))
async def show_tournament_detail(callback: CallbackQuery, callback_data: TournamentCallback):
    t_id = callback_data.t_id

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT game, mode, max_players, entry_fee, prize_places, prizes, map_photo, description, link 
            FROM tournaments 
            WHERE id = ? AND status = 'active'
        """, (t_id,))
        row = await cursor.fetchone()

        if not row:
            await callback.message.edit_text("Турнир не найден или завершён.")
            await callback.answer()
            return

        game, mode, max_p, fee, prize_places, prizes_json, photo, desc, link = row
        prizes = json.loads(prizes_json)

        text = (
            f"<b>Турнир #{t_id}</b> 🔥\n\n"
            f"🎮 Игра: <b>{game}</b>\n"
            f"⚔️ Режим: <b>{mode}</b>\n"
            f"💰 Взнос: <b>{fee} ₽</b>\n"
            f"👥 Макс. участников: <b>{max_p}</b>\n"
            f"🏆 Призы:\n" + "\n".join(f"  {i+1} место → {p} ₽" for i, p in enumerate(prizes)) +
            f"\n\nРеквизиты: <code>{PAYMENT_DETAILS}</code>"
        )

        if desc:
            text += f"\n\n📢 <i>{desc}</i>"
        if link:
            text += f"\n\n🔗 Ссылка: {link}"

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Зарегистрироваться", callback_data=TournamentCallback(action="register", t_id=t_id).pack())],
            [InlineKeyboardButton(text="Назад к списку", callback_data=TournamentCallback(action="back", t_id=0).pack())],
        ])

        if photo:
            await callback.message.delete()
            await callback.message.answer_photo(photo=photo, caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

    await callback.answer()

@dp.callback_query(TournamentCallback.filter(F.action == "back"))
async def back_to_tournaments(callback: CallbackQuery, callback_data: TournamentCallback):
    await show_active_tournaments(callback.message)
    await callback.message.delete()
    await callback.answer()

# ─── Регистрация ─────────────────────────────────────────────────
@dp.callback_query(TournamentCallback.filter(F.action == "register"))
async def begin_registration(callback: CallbackQuery, callback_data: TournamentCallback, state: FSMContext):
    t_id = callback_data.t_id
    await state.update_data(t_id=t_id)
    await state.set_state(Registration.nickname)
    await callback.message.edit_text("Введи свой ник в Brawl Stars:")
    await callback.answer()

@dp.message(Registration.nickname)
async def process_nickname(message: Message, state: FSMContext):
    nick = message.text.strip()
    if len(nick) < 2 or len(nick) > 30:
        await message.answer("Ник должен быть от 2 до 30 символов. Попробуй ещё раз.")
        return

    await state.update_data(nickname=nick)
    await state.set_state(Registration.payment_photo)

    data = await state.get_data()
    t_id = data['t_id']

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT entry_fee FROM tournaments WHERE id = ?", (t_id,))
        fee_row = await cursor.fetchone()
        fee = fee_row[0] if fee_row else 0

    await message.answer(
        f"Оплати <b>{fee} ₽</b> на\n<code>{PAYMENT_DETAILS}</code>\n\n"
        f"Пришли скриншот оплаты 👇",
        parse_mode="HTML"
    )

@dp.message(Registration.payment_photo, F.photo)
async def process_payment_screenshot(message: Message, state: FSMContext):
    data = await state.get_data()
    t_id = data.get('t_id')
    nickname = data.get('nickname')

    if not t_id:
        await message.answer("Сессия истекла. Начни регистрацию заново.")
        await state.clear()
        return

    photo_id = message.photo[-1].file_id
    user_id = message.from_user.id
    now = datetime.utcnow().isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO participants 
            (tournament_id, user_id, nickname, payment_photo, joined_at) 
            VALUES (?, ?, ?, ?, ?)""",
            (t_id, user_id, nickname, photo_id, now)
        )
        await db.commit()

    await message.answer("✅ Заявка принята! Ожидай подтверждения от админа.")
    await state.clear()

    # Уведомление админу
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(
                admin_id,
                photo=photo_id,
                caption=f"Новая заявка на турнир #{t_id}\nНик: {nickname}\nПользователь: {user_id}"
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить админа {admin_id}: {e}")

# ─── Создание турнира ────────────────────────────────────────────
@dp.message(F.text == "Создать турнир", lambda m: m.from_user.id in ADMIN_IDS)
async def start_create_tournament(message: Message, state: FSMContext):
    await state.set_state(CreateTournament.game)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Brawl Stars")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("Выбери игру:", reply_markup=kb)

# Здесь нужно добавить остальные шаги создания турнира (mode, max_players, entry_fee, prize_places, prizes, map_photo, description)
# Для краткости оставляю только финальную часть — остальное аналогично предыдущим версиям

@dp.message(CreateTournament.description)
async def process_tournament_description(message: Message, state: FSMContext):
    desc = message.text.strip()
    if desc.lower() in ("нет", "не нужно", "пропустить"):
        desc = None

    data = await state.get_data()
    data['description'] = desc

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
                data.get('map_photo'), desc, now
            )
        )
        t_id = cursor.lastrowid
        await db.commit()

    # Сообщение админу
    admin_msg = (
        f"✅ Турнир #{t_id} успешно создан!\n\n"
        f"🎮 {data.get('game')} • {data.get('mode')}\n"
        f"💰 Взнос: {data.get('entry_fee')} ₽\n"
        f"👥 До {data.get('max_players')} игроков\n"
        f"🏆 Призы: {' • '.join(f'{i+1} — {p}₽' for i, p in enumerate(prizes))}\n"
    )
    if desc:
        admin_msg += f"\n📢 {desc}\n"

    if photo := data.get('map_photo'):
        await message.answer_photo(photo, caption=admin_msg, reply_markup=admin_menu())
    else:
        await message.answer(admin_msg, reply_markup=admin_menu())

    # Уведомление в канал
    notify_text = (
        f"🔥 Новый турнир #{t_id} открыт! 🔥\n\n"
        f"🎮 {data.get('game')} • {data.get('mode')}\n"
        f"💰 Взнос: {data.get('entry_fee')} ₽\n"
        f"👥 Макс: {data.get('max_players')}\n"
        f"🏆 Призы: {' • '.join(f'{i+1} — {p}₽' for i, p in enumerate(prizes))}\n"
    )
    if desc:
        notify_text += f"\n📢 {desc}\n"
    notify_text += "\nЗаходи в бота и регистрируйся! 👉 @твой_бот"

    try:
        if photo := data.get('map_photo'):
            await bot.send_photo(NOTIFY_CHAT_ID, photo, caption=notify_text)
        else:
            await bot.send_message(NOTIFY_CHAT_ID, notify_text)
    except Exception as e:
        logger.error(f"Ошибка уведомления канала: {e}")
        await message.answer("Уведомление в канал не отправилось (проверь права бота)")

    await state.clear()

# ─── Запуск ──────────────────────────────────────────────────────
async def main():
    await init_db()
    logger.info("Бот запускается...")
    try:
        await dp.start_polling(
            bot,
            drop_pending_updates=True,
            polling_timeout=25
        )
    except Exception as e:
        logger.exception("Polling упал")
        await asyncio.sleep(10)
        await main()

if __name__ == "__main__":
    asyncio.run(main())
