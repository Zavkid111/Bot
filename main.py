import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardRemove

from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
COMMISSION_PERCENT = 30
PAYMENT_DETAILS = "Сбербанк 2202208214031917 Завкиддин А"

# Настройка логирования — важно для Bothost (логи видно в панели)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Хранилище в памяти (слетает при рестарте — это норма на бесплатном)
tournaments = {}       # {t_id: dict}
participants = {}      # {t_id: [user_ids]}
payments = {}          # {t_id: {user_id: {'status': ..., 'photo_id': ...}}}
results = {}           # {t_id: {user_id: ...}}
active_users = {}      # {user_id: t_id}

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

# ─── МЕНЮ ────────────────────────────────────────────────────────────────
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

# ─── START & SUPPORT ─────────────────────────────────────────────────────
@dp.message(CommandStart())
async def start(message: Message):
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer("Добро пожаловать в турнирного бота!", reply_markup=get_main_menu(is_admin))

@dp.message(lambda m: m.text == "ℹ️ О нас и поддержка")
async def support(message: Message):
    await message.answer(
        "Поддержка: @твой_ник\nКанал: @твой_канал\nПравила: ...",
        reply_markup=get_main_menu(message.from_user.id in ADMIN_IDS)
    )

@dp.message(lambda m: m.text == "🔧 Админ-панель" and m.from_user.id in ADMIN_IDS)
async def admin_panel(message: Message):
    await message.answer("Админ-панель открыта", reply_markup=get_admin_menu())

# ─── СОЗДАНИЕ ТУРНИРА ────────────────────────────────────────────────────
@dp.message(lambda m: m.text == "Создать турнир" and m.from_user.id in ADMIN_IDS)
async def start_create(message: Message, state: FSMContext):
    await state.set_state(CreateTournament.game)
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(KeyboardButton("Brawl Stars"), KeyboardButton("Standoff 2"))
    await message.answer("Выбери игру:", reply_markup=kb)

@dp.message(CreateTournament.game)
async def process_game(message: Message, state: FSMContext):
    await state.update_data(game=message.text)
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(KeyboardButton("Solo Showdown"), KeyboardButton("1v1"), KeyboardButton("3v3"))
    await state.set_state(CreateTournament.mode)
    await message.answer("Выбери режим:", reply_markup=kb)

@dp.message(CreateTournament.mode)
async def process_mode(message: Message, state: FSMContext):
    await state.update_data(mode=message.text)
    await state.set_state(CreateTournament.max_players)
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(KeyboardButton("8"), KeyboardButton("16"), KeyboardButton("32"))
    await message.answer("Макс. кол-во платящих игроков:", reply_markup=kb)

@dp.message(CreateTournament.max_players)
async def process_max_players(message: Message, state: FSMContext):
    try:
        num = int(message.text)
        if num < 2 or num > 128:
            raise ValueError
        await state.update_data(max_players=num)
    except:
        await message.answer("Введи нормальное число (2–128)")
        return
    await state.set_state(CreateTournament.entry_fee)
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(KeyboardButton("50"), KeyboardButton("100"), KeyboardButton("200"))
    await message.answer("Взнос за участие (₽):", reply_markup=kb)

@dp.message(CreateTournament.entry_fee)
async def process_entry_fee(message: Message, state: FSMContext):
    try:
        fee = int(message.text)
        if fee < 10:
            raise ValueError
        await state.update_data(entry_fee=fee)
    except:
        await message.answer("Введи нормальную сумму (от 10 ₽)")
        return
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    kb.add(*[KeyboardButton(str(i)) for i in range(1, 6)])
    await state.set_state(CreateTournament.prize_places)
    await message.answer("Сколько призовых мест (1–5):", reply_markup=kb)

@dp.message(CreateTournament.prize_places)
async def process_prize_places(message: Message, state: FSMContext):
    try:
        places = int(message.text)
        if not 1 <= places <= 5:
            raise ValueError
        await state.update_data(prize_places=places, prizes=[], current_prize=1)
    except:
        await message.answer("Выбери от 1 до 5")
        return
    await state.set_state(CreateTournament.prizes)
    await message.answer(f"Приз за 1 место (₽):", reply_markup=ReplyKeyboardRemove())

@dp.message(CreateTournament.prizes)
async def process_prizes(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        prize = int(message.text)
        if prize < 0:
            raise ValueError
        prizes = data.get("prizes", [])
        prizes.append(prize)
        current = data.get("current_prize", 1) + 1
        await state.update_data(prizes=prizes, current_prize=current)
        if current <= data["prize_places"]:
            await message.answer(f"Приз за {current} место (₽):")
        else:
            kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            kb.add(KeyboardButton("Да"), KeyboardButton("Нет"))
            await state.set_state(CreateTournament.map_photo)
            await message.answer("Хочешь прикрепить фото карты/сетки? (Да/Нет)", reply_markup=kb)
    except:
        await message.answer("Введи нормальное число")

@dp.message(CreateTournament.map_photo)
async def process_map_photo_choice(message: Message, state: FSMContext):
    if message.text == "Да":
        await message.answer("Пришли фото (одно):")
        # состояние остаётся тем же → ждём фото
    else:
        await state.update_data(map_photo=None)
        await create_tournament_summary(message, state)

@dp.message(CreateTournament.map_photo, content_types=types.ContentType.PHOTO)
async def process_map_photo(message: Message, state: FSMContext):
    await state.update_data(map_photo=message.photo[-1].file_id)
    await create_tournament_summary(message, state)

async def create_tournament_summary(message: Message, state: FSMContext):
    global tournament_counter
    data = await state.get_data()
    tournament_counter += 1
    t_id = tournament_counter

    tournaments[t_id] = data
    participants[t_id] = []
    payments[t_id] = {}
    results[t_id] = {}

    fund = data["max_players"] * data["entry_fee"]
    prizes_sum = sum(data["prizes"])
    commission = fund * COMMISSION_PERCENT // 100

    text = (
        f"Турнир #{t_id} успешно создан!\n"
        f"Игра: {data['game']}\n"
        f"Режим: {data['mode']}\n"
        f"Макс. участников: {data['max_players']}\n"
        f"Взнос: {data['entry_fee']} ₽\n"
        f"Призовые места: {data['prize_places']}\n"
        f"Призы:\n" + "\n".join(f"{i} — {p} ₽" for i, p in enumerate(data['prizes'], 1)) +
        f"\n\nФонд: {fund} ₽\nВыплата призов: {prizes_sum} ₽\nКомиссия: {commission} ₽\n"
        f"Реквизиты: {PAYMENT_DETAILS}"
    )

    if data.get("map_photo"):
        await message.answer_photo(photo=data["map_photo"], caption=text)
    else:
        await message.answer(text)

    await state.clear()
    await message.answer("Турнир создан. Что дальше?", reply_markup=get_admin_menu())

# ─── CANCEL для всех состояний ───────────────────────────────────────────
@dp.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нечего отменять.", reply_markup=get_main_menu(message.from_user.id in ADMIN_IDS))
        return
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=get_main_menu(message.from_user.id in ADMIN_IDS))

# ─── MAIN с защитой от падений ───────────────────────────────────────────
async def main():
    logger.info("Бот запускается...")
    while True:
        try:
            await dp.start_polling(
                bot,
                drop_pending_updates=True,
                polling_timeout=20,
                allowed_updates=types.AllowedUpdates.MESSAGE + types.AllowedUpdates.CALLBACK_QUERY
            )
        except Exception as e:
            logger.exception("Polling упал, перезапускаем через 10 сек")
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
