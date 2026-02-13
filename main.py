import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, Message

from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
COMMISSION_PERCENT = 30  # твоя комиссия
PAYMENT_DETAILS = "Сбербанк 2202208214031917 Завкиддин А"  # твои реквизиты

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Хранилище в памяти
tournaments = {}  # {t_id: dict}
participants = {}  # {t_id: list user_ids}
payments = {}  # {t_id: {user_id: {'status': 'pending', 'photo_id': photo_id, 'comment': ''}}}
results = {}  # {t_id: {user_id: {'status': 'pending', 'photo_id': photo_id, 'place': None}}}
active_users = {}  # {user_id: t_id}

tournament_counter = 0

# Состояния
class CreateTournament(StatesGroup):
    game = State()
    mode = State()
    max_players = State()
    entry_fee = State()
    prize_places = State()
    prizes = State()
    map_photo = State()
    confirm = State()

class Registration(StatesGroup):
    nickname = State()
    payment_photo = State()

class ResultSubmission(StatesGroup):
    result_photo = State()

# Меню
def get_main_menu(is_admin=False):
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(KeyboardButton("🏆 Турниры"))
    kb.add(KeyboardButton("👤 Мои турниры"))
    kb.add(KeyboardButton("ℹ️ О нас и поддержка"))
    if is_admin:
        kb.add(KeyboardButton("🔧 Админ-панель"))
    return kb

def get_admin_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(KeyboardButton("Создать турнир"))
    kb.add(KeyboardButton("Мои турниры"))
    kb.add(KeyboardButton("Вернуться в главное меню"))
    return kb

def get_tournament_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(KeyboardButton("Зарегистрироваться"))
    kb.add(KeyboardButton("Отправить скрин оплаты"))
    kb.add(KeyboardButton("Отправить скрин результата"))
    kb.add(KeyboardButton("Я проиграл"))
    kb.add(KeyboardButton("Вернуться в главное меню"))
    return kb

# Старт
@dp.message(CommandStart())
async def start(message: Message):
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer("Добро пожаловать!", reply_markup=get_main_menu(is_admin))

# Поддержка
@dp.message(lambda m: m.text == "ℹ️ О нас и поддержка")
async def support(message: Message):
    await message.answer("Поддержка: @чат\nКанал: @канал\nПравила: ...", reply_markup=get_main_menu())

# Админ-панель
@dp.message(lambda m: m.text == "🔧 Админ-панель" and m.from_user.id in ADMIN_IDS)
async def admin_panel(message: Message):
    await message.answer("Админ-панель:", reply_markup=get_admin_menu())

# Создать турнир
@dp.message(lambda m: m.text == "Создать турнир" and m.from_user.id in ADMIN_IDS, state='*')
async def start_create(message: Message, state: FSMContext):
    await state.set_state(CreateTournament.game)
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(KeyboardButton("Brawl Stars"), KeyboardButton("Standoff 2"))
    await message.answer("Игра:", reply_markup=kb)

@dp.message(CreateTournament.game)
async def process_game(message: Message, state: FSMContext):
    await state.update_data(game=message.text)
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(KeyboardButton("Solo Showdown"), KeyboardButton("1v1"), KeyboardButton("3v3"))
    await state.set_state(CreateTournament.mode)
    await message.answer("Режим:", reply_markup=kb)

@dp.message(CreateTournament.mode)
async def process_mode(message: Message, state: FSMContext):
    await state.update_data(mode=message.text)
    await state.set_state(CreateTournament.max_players)
    await message.answer("Кол-во платящих игроков (9):", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("9")))

@dp.message(CreateTournament.max_players)
async def process_max_players(message: Message, state: FSMContext):
    await state.update_data(max_players=int(message.text))
    await state.set_state(CreateTournament.entry_fee)
    await message.answer("Взнос (100 ₽):", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("100")))

@dp.message(CreateTournament.entry_fee)
async def process_entry_fee(message: Message, state: FSMContext):
    await state.update_data(entry_fee=int(message.text))
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(KeyboardButton("1"), KeyboardButton("2"), KeyboardButton("3"), KeyboardButton("4"), KeyboardButton("5"))
    await state.set_state(CreateTournament.prize_places)
    await message.answer("Призовых мест (1–5):", reply_markup=kb)

@dp.message(CreateTournament.prize_places)
async def process_prize_places(message: Message, state: FSMContext):
    places = int(message.text)
    await state.update_data(prize_places=places, prizes=[], current_prize=1)
    await state.set_state(CreateTournament.prizes)
    await message.answer(f"Приз для 1 места (₽):")

@dp.message(CreateTournament.prizes)
async def process_prizes(message: Message, state: FSMContext):
    data = await state.get_data()
    prizes = data.get("prizes", [])
    prizes.append(int(message.text))
    current = data.get("current_prize", 1) + 1
    await state.update_data(prizes=prizes, current_prize=current)
    if current <= data["prize_places"]:
        await message.answer(f"Приз для {current} места (₽):")
    else:
        await state.set_state(CreateTournament.map_photo)
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(KeyboardButton("Да"), KeyboardButton("Нет"))
        await message.answer("Фото карты? (Да/Нет):", reply_markup=kb)

@dp.message(CreateTournament.map_photo)
async def process_map_photo_text(message: Message, state: FSMContext):
    if message.text == "Да":
        await message.answer("Пришли фото карты:")
        return
    await state.update_data(map_photo=None)
    await create_tournament_summary(message, state)

@dp.message(CreateTournament.map_photo, content_types=types.ContentType.PHOTO)
async def process_map_photo_photo(message: Message, state: FSMContext):
    await state.update_data(map_photo=message.photo[-1].file_id)
    await create_tournament_summary(message, state)

async def create_tournament_summary(message: Message, state: FSMContext):
    data = await state.get_data()
    global tournament_counter
    tournament_counter += 1
    t_id = tournament_counter
    tournaments[t_id] = data
    participants[t_id] = []
    payments[t_id] = {}
    results[t_id] = {}
    fund = data["max_players"] * data["entry_fee"]
    prizes_sum = sum(data["prizes"])
    commission = fund * COMMISSION_PERCENT // 100
    text = f"Турнир #{t_id} создан!\nИгра: {data['game']}\nРежим: {data['mode']}\nМест: {data['max_players']}\nВзнос: {data['entry_fee']} ₽\nПризы:\n"
    for i, prize in enumerate(data["prizes"], 1):
        text += f"{i} место — {prize} ₽\n"
    text += f"Фонд: {fund} ₽\nПризы: {prizes_sum} ₽\nКомиссия: {commission} ₽\nРеквизиты оплаты: {PAYMENT_DETAILS}"
    if data.get("map_photo"):
        await message.answer_photo(photo=data["map_photo"], caption=text)
    else:
        await message.answer(text)
    await state.clear()
    await message.answer("Вернись в админ-панель.", reply_markup=get_admin_menu())

# И другие handlers как в предыдущем коде (регистрация, оплата, результаты, выплаты и т.д. — они уже были, я не повторяю, чтобы не дублировать)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
