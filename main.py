import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
COMMISSION_PERCENT = 30
PAYMENT_DETAILS = "Сбербанк 2202208214031917 Завкиддин А"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

tournaments = {}
participants = {}
payments = {}
results = {}
active_users = {}

tournament_counter = 0

class CreateTournament(StatesGroup):
    game = State()
    mode = State()
    max_players = State()
    entry_fee = State()
    prize_places = State()
    prizes = State()
    map_photo = State()


# ─── МЕНЮ ────────────────────────────────────────────────────────────────
def get_main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="🏆 Турниры")],
        [KeyboardButton(text="👤 Мои турниры")],
        [KeyboardButton(text="ℹ️ О нас и поддержка")],
    ]
    if is_admin:
        buttons.append([KeyboardButton(text="🔧 Админ-панель")])

    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        row_width=2,
    )


def get_admin_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Создать турнир")],
            [KeyboardButton(text="Мои турниры")],
            [KeyboardButton(text="Вернуться в главное меню")],
        ],
        resize_keyboard=True,
        row_width=2,
    )


# ─── ХЕНДЛЕРЫ ────────────────────────────────────────────────────────────
@dp.message(CommandStart())
async def start(message: Message):
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer(
        "Добро пожаловать в турнирного бота по Brawl Stars!",
        reply_markup=get_main_menu(is_admin)
    )


@dp.message(lambda m: m.text == "ℹ️ О нас и поддержка")
async def support(message: Message):
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer(
        "Поддержка: @твой_ник\nКанал: @твой_канал\nПравила: ...",
        reply_markup=get_main_menu(is_admin)
    )


@dp.message(lambda m: m.text == "🔧 Админ-панель" and m.from_user.id in ADMIN_IDS)
async def admin_panel(message: Message):
    await message.answer("Админ-панель открыта", reply_markup=get_admin_menu())


# ─── СОЗДАНИЕ ТУРНИРА ────────────────────────────────────────────────────
@dp.message(lambda m: m.text == "Создать турнир" and m.from_user.id in ADMIN_IDS)
async def start_create(message: Message, state: FSMContext):
    await state.set_state(CreateTournament.game)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Brawl Stars"), KeyboardButton(text="Standoff 2")],
        ],
        resize_keyboard=True,
        row_width=2,
    )
    await message.answer("Выбери игру:", reply_markup=kb)


@dp.message(CreateTournament.game)
async def process_game(message: Message, state: FSMContext):
    await state.update_data(game=message.text)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Solo Showdown"), KeyboardButton(text="1v1"), KeyboardButton(text="3v3")],
        ],
        resize_keyboard=True,
        row_width=3,
    )
    await state.set_state(CreateTournament.mode)
    await message.answer("Выбери режим:", reply_markup=kb)


@dp.message(CreateTournament.mode)
async def process_mode(message: Message, state: FSMContext):
    await state.update_data(mode=message.text)
    await state.set_state(CreateTournament.max_players)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="8"), KeyboardButton(text="16"), KeyboardButton(text="32")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer("Макс. кол-во платящих игроков:", reply_markup=kb)


@dp.message(CreateTournament.max_players)
async def process_max_players(message: Message, state: FSMContext):
    try:
        num = int(message.text)
        if num < 2 or num > 128:
            raise ValueError
        await state.update_data(max_players=num)
    except ValueError:
        await message.answer("Введи число от 2 до 128")
        return

    await state.set_state(CreateTournament.entry_fee)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="50"), KeyboardButton(text="100"), KeyboardButton(text="200")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer("Взнос за участие (₽):", reply_markup=kb)


@dp.message(CreateTournament.entry_fee)
async def process_entry_fee(message: Message, state: FSMContext):
    try:
        fee = int(message.text)
        if fee < 10:
            raise ValueError
        await state.update_data(entry_fee=fee)
    except ValueError:
        await message.answer("Введи сумму от 10 ₽")
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=str(i)) for i in range(1, 6)],
        ],
        resize_keyboard=True,
        row_width=5,
    )
    await state.set_state(CreateTournament.prize_places)
    await message.answer("Сколько призовых мест (1–5):", reply_markup=kb)


@dp.message(CreateTournament.prize_places)
async def process_prize_places(message: Message, state: FSMContext):
    try:
        places = int(message.text)
        if not 1 <= places <= 5:
            raise ValueError
        await state.update_data(prize_places=places, prizes=[], current_prize=1)
    except ValueError:
        await message.answer("Выбери от 1 до 5")
        return

    await state.set_state(CreateTournament.prizes)
    await message.answer("Приз за 1 место (₽):", reply_markup=ReplyKeyboardRemove())


@dp.message(CreateTournament.prizes)
async def process_prizes(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        prize = int(message.text)
        if prize < 0:
            raise ValueError
        prizes: list[int] = data.get("prizes", [])
        prizes.append(prize)
        current = data.get("current_prize", 1) + 1
        await state.update_data(prizes=prizes, current_prize=current)

        if current <= data["prize_places"]:
            await message.answer(f"Приз за {current} место (₽):")
        else:
            kb = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="Да"), KeyboardButton(text="Нет")],
                ],
                resize_keyboard=True,
                one_time_keyboard=True,
            )
            await state.set_state(CreateTournament.map_photo)
            await message.answer("Хочешь прикрепить фото карты/сетки? (Да/Нет)", reply_markup=kb)
    except ValueError:
        await message.answer("Введи нормальное число")


@dp.message(CreateTournament.map_photo)
async def process_map_photo_choice(message: Message, state: FSMContext):
    if message.text == "Да":
        await message.answer("Пришли одно фото:")
    elif message.text == "Нет":
        await state.update_data(map_photo=None)
        await create_tournament_summary(message, state)
    else:
        await message.answer("Нажми «Да» или «Нет»")


@dp.message(CreateTournament.map_photo, F.photo)
async def process_map_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(map_photo=photo_id)
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

    max_p = data["max_players"]
    fee = data["entry_fee"]
    fund = max_p * fee
    prizes_sum = sum(data["prizes"])
    commission = fund * COMMISSION_PERCENT // 100

    text = (
        f"Турнир #{t_id} успешно создан!\n"
        f"Игра: {data['game']}\n"
        f"Режим: {data['mode']}\n"
        f"Макс. участников: {max_p}\n"
        f"Взнос: {fee} ₽\n"
        f"Призовые места: {data['prize_places']}\n"
        f"Призы:\n" + "\n".join(f"  {i} — {p} ₽" for i, p in enumerate(data['prizes'], 1)) +
        f"\n\nФонд: {fund} ₽\nВыплата призов: {prizes_sum} ₽\nКомиссия: {commission} ₽\n"
        f"Реквизиты оплаты: {PAYMENT_DETAILS}"
    )

    if map_photo := data.get("map_photo"):
        await message.answer_photo(photo=map_photo, caption=text)
    else:
        await message.answer(text)

    await state.clear()
    await message.answer("Турнир создан. Что дальше?", reply_markup=get_admin_menu())


@dp.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нечего отменять.")
        return

    await state.clear()
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer("Действие отменено.", reply_markup=get_main_menu(is_admin))


async def main():
    logger.info("Бот стартует...")
    while True:
        try:
            await dp.start_polling(
                bot,
                drop_pending_updates=True,
                polling_timeout=20,
            )
        except Exception as e:
            logger.exception(f"Polling упал: {e}")
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
