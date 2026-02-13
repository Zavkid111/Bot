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
PAYMENT_DETAILS = "Сбербанк 2202208214031917 Завкиддин А"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

tournaments = {}  # {t_id: {'game': ..., 'mode': ..., 'max_players': ..., 'entry_fee': ..., 'prize_places': ..., 'prizes': [...], 'map_photo': ..., 'link': None, 'status': 'active'/'finished'}}
participants = {}  # {t_id: [user_ids]}
payments = {}  # {t_id: {user_id: {'status': 'pending'/'confirmed', 'photo_id': ..., 'requisites': ..., 'comment': ...}}}
results = {}  # {t_id: {user_id: {'won': True/False, 'place': int, 'result_photo': ..., 'requisites': ..., 'comment': ...}}}
active_users = {}  # {user_id: t_id}  # текущий турнир юзера

tournament_counter = 0
all_users = set()  # симуляция списка всех пользователей (добавляем при /start)

class CreateTournament(StatesGroup):
    game = State()
    mode = State()
    max_players = State()
    entry_fee = State()
    prize_places = State()
    prizes = State()
    map_photo = State()

class Registration(StatesGroup):
    nickname = State()
    payment_photo = State()

class ResultSubmission(StatesGroup):
    won = State()
    requisites = State()
    comment = State()
    result_photo = State()

class AdminFinishTournament(StatesGroup):
    tournament_id = State()

class AdminSendLink(StatesGroup):
    tournament_id = State()
    link = State()

# ─── МЕНЮ ────────────────────────────────────────────────────────────────
def get_main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="🏆 Турниры")],
        [KeyboardButton(text="👤 Мои турниры")],
        [KeyboardButton(text="ℹ️ О нас и поддержка")],
    ]
    if is_admin:
        buttons.append([KeyboardButton(text="🔧 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_admin_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Создать турнир")],
            [KeyboardButton(text="Мои турниры")],
            [KeyboardButton(text="Уведомить всех")],
            [KeyboardButton(text="Завершить турнир")],
            [KeyboardButton(text="Отправить ссылку на турнир")],
            [KeyboardButton(text="Вернуться в главное меню")],
        ],
        resize_keyboard=True,
    )

def get_tournament_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Зарегистрироваться")],
            [KeyboardButton(text="Отправить скрин оплаты")],
            [KeyboardButton(text="Вернуться в главное меню")],
        ],
        resize_keyboard=True,
    )

def get_result_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Я выиграл"), KeyboardButton(text="Я проиграл")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

# ─── START ───────────────────────────────────────────────────────────────
@dp.message(CommandStart())
async def start(message: Message):
    all_users.add(message.from_user.id)
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer("Добро пожаловать!", reply_markup=get_main_menu(is_admin))

# ─── ПОДДЕРЖКА ───────────────────────────────────────────────────────────
@dp.message(F.text == "ℹ️ О нас и поддержка")
async def support(message: Message):
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer("Поддержка: @чат\nКанал: @канал\nПравила: ...", reply_markup=get_main_menu(is_admin))

# ─── АДМИН-ПАНЕЛЬ ────────────────────────────────────────────────────────
@dp.message(F.text == "🔧 Админ-панель", lambda m: m.from_user.id in ADMIN_IDS)
async def admin_panel(message: Message):
    await message.answer("Админ-панель:", reply_markup=get_admin_menu())

# ─── ТУРНИРЫ ─────────────────────────────────────────────────────────────
@dp.message(F.text == "🏆 Турниры")
async def list_tournaments(message: Message):
    if not tournaments:
        await message.answer("Пока нет доступных турниров.")
        return
    text = "Доступные турниры:\n"
    for t_id, data in tournaments.items():
        if data.get('status', 'active') == 'active':
            text += f"#{t_id}: {data['game']} - {data['mode']} (мест: {data['max_players']}, взнос: {data['entry_fee']} ₽)\n"
            if link := data.get('link'):
                text += f"Ссылка: {link}\n"
    await message.answer(text, reply_markup=get_tournament_menu())

# ─── МОИ ТУРНИРЫ ─────────────────────────────────────────────────────────
@dp.message(F.text == "👤 Мои турниры")
async def my_tournaments(message: Message):
    user_id = message.from_user.id
    text = "Твои турниры:\n"
    found = False
    for t_id in participants:
        if user_id in participants[t_id]:
            data = tournaments[t_id]
            status = 'активен' if data.get('status') == 'active' else 'завершён'
            text += f"#{t_id}: {data['game']} - {data['mode']} ({status})\n"
            found = True
    if not found:
        text = "Ты не участвуешь ни в одном турнире."
    await message.answer(text)

# ─── СОЗДАНИЕ ТУРНИРА ────────────────────────────────────────────────────
@dp.message(F.text == "Создать турнир", lambda m: m.from_user.id in ADMIN_IDS)
async def start_create(message: Message, state: FSMContext):
    await state.set_state(CreateTournament.game)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Brawl Stars"), KeyboardButton(text="Standoff 2")]],
        resize_keyboard=True,
    )
    await message.answer("Игра:", reply_markup=kb)

@dp.message(CreateTournament.game)
async def process_game(message: Message, state: FSMContext):
    await state.update_data(game=message.text)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Solo Showdown"), KeyboardButton(text="1v1"), KeyboardButton(text="3v3")]],
        resize_keyboard=True,
    )
    await state.set_state(CreateTournament.mode)
    await message.answer("Режим:", reply_markup=kb)

@dp.message(CreateTournament.mode)
async def process_mode(message: Message, state: FSMContext):
    await state.update_data(mode=message.text)
    await state.set_state(CreateTournament.max_players)
    await message.answer("Кол-во платящих игроков:")

@dp.message(CreateTournament.max_players)
async def process_max_players(message: Message, state: FSMContext):
    try:
        num = int(message.text)
        if num < 1:
            raise ValueError
        await state.update_data(max_players=num)
        await state.set_state(CreateTournament.entry_fee)
        await message.answer("Взнос (₽):")
    except:
        await message.answer("Введи число >0")

@dp.message(CreateTournament.entry_fee)
async def process_entry_fee(message: Message, state: FSMContext):
    try:
        fee = int(message.text)
        if fee < 0:
            raise ValueError
        await state.update_data(entry_fee=fee)
        await state.set_state(CreateTournament.prize_places)
        await message.answer("Призовых мест (1-5):")
    except:
        await message.answer("Введи число >=0")

@dp.message(CreateTournament.prize_places)
async def process_prize_places(message: Message, state: FSMContext):
    try:
        places = int(message.text)
        if not 1 <= places <= 5:
            raise ValueError
        await state.update_data(prize_places=places, prizes=[], current_prize=1)
        await state.set_state(CreateTournament.prizes)
        await message.answer("Приз для 1 места (₽):")
    except:
        await message.answer("1-5")

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
            await message.answer(f"Приз для {current} места (₽):")
        else:
            kb = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="Да"), KeyboardButton(text="Нет")]],
                resize_keyboard=True,
            )
            await state.set_state(CreateTournament.map_photo)
            await message.answer("Фото карты? (Да/Нет):", reply_markup=kb)
    except:
        await message.answer("Число")

@dp.message(CreateTournament.map_photo)
async def process_map_photo_choice(message: Message, state: FSMContext):
    if message.text == "Да":
        await message.answer("Пришли фото:")
    elif message.text == "Нет":
        await state.update_data(map_photo=None)
        await create_tournament_summary(message, state)
    else:
        await message.answer("Да/Нет")

@dp.message(CreateTournament.map_photo, F.photo)
async def process_map_photo(message: Message, state: FSMContext):
    await state.update_data(map_photo=message.photo[-1].file_id)
    await create_tournament_summary(message, state)

async def create_tournament_summary(message: Message, state: FSMContext):
    global tournament_counter
    data = await state.get_data()
    tournament_counter += 1
    t_id = tournament_counter
    data['status'] = 'active'
    data['link'] = None  # ссылка по умолчанию None
    tournaments[t_id] = data
    participants[t_id] = []
    payments[t_id] = {}
    results[t_id] = {}
    text = f"Турнир #{t_id} создан!\nИгра: {data['game']}\nРежим: {data['mode']}\nМест: {data['max_players']}\nВзнос: {data['entry_fee']} ₽\nПризы:\n"
    for i, prize in enumerate(data['prizes'], 1):
        text += f"{i} место — {prize} ₽\n"
    text += f"Реквизиты оплаты: {PAYMENT_DETAILS}"
    if map_photo := data.get('map_photo'):
        await message.answer_photo(photo=map_photo, caption=text)
    else:
        await message.answer(text)
    await state.clear()
    await message.answer("Вернись в админ-панель.", reply_markup=get_admin_menu())
    # Уведомление всем
    await notify_all(f"Новый турнир #{t_id} создан! Зарегистрируйся: /tournament_{t_id}")

# ─── ОТПРАВИТЬ ССЫЛКУ ПОЗЖЕ ──────────────────────────────────────────────
@dp.message(F.text == "Отправить ссылку на турнир", lambda m: m.from_user.id in ADMIN_IDS)
async def start_send_link(message: Message, state: FSMContext):
    await state.set_state(AdminSendLink.tournament_id)
    await message.answer("Введи ID активного турнира:")

@dp.message(AdminSendLink.tournament_id)
async def process_send_link_id(message: Message, state: FSMContext):
    try:
        t_id = int(message.text)
        if t_id not in tournaments or tournaments[t_id]['status'] != 'active':
            raise ValueError
        await state.update_data(t_id=t_id)
        await state.set_state(AdminSendLink.link)
        await message.answer("Введи ссылку:")
    except:
        await message.answer("Неверный ID или турнир не активен.")

@dp.message(AdminSendLink.link)
async def process_send_link_text(message: Message, state: FSMContext):
    data = await state.get_data()
    t_id = data['t_id']
    link = message.text
    tournaments[t_id]['link'] = link
    await state.clear()
    await message.answer(f"Ссылка для #{t_id} обновлена: {link}")
    # Уведомление всем о ссылке
    await notify_all(f"Ссылка на турнир #{t_id}: {link}")

# ─── РЕГИСТРАЦИЯ ─────────────────────────────────────────────────────────
@dp.message(F.text == "Зарегистрироваться")
async def start_registration(message: Message, state: FSMContext):
    await state.set_state(Registration.nickname)
    await message.answer("Введи никнейм:")

@dp.message(Registration.nickname)
async def process_nickname(message: Message, state: FSMContext):
    await state.update_data(nickname=message.text)
    await state.set_state(Registration.payment_photo)
    await message.answer("Отправь скрин оплаты:")

@dp.message(Registration.payment_photo, F.photo)
async def process_payment_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    t_id = active_users.get(message.from_user.id)  # assuming user selected tournament
    if t_id not in payments:
        await message.answer("Сначала выбери турнир.")
        await state.clear()
        return
    payments[t_id][message.from_user.id] = {'status': 'pending', 'photo_id': message.photo[-1].file_id}
    participants[t_id].append(message.from_user.id)
    await state.clear()
    await message.answer("Оплата на проверке. Жди подтверждения.")
    # Уведомление админу (симуляция)
    for admin in ADMIN_IDS:
        await bot.send_message(admin, f"Новая оплата в #{t_id} от {message.from_user.username}")

# ─── ЗАВЕРШЕНИЕ ТУРНИРА ──────────────────────────────────────────────────
@dp.message(F.text == "Завершить турнир", lambda m: m.from_user.id in ADMIN_IDS)
async def start_finish_tournament(message: Message, state: FSMContext):
    await state.set_state(AdminFinishTournament.tournament_id)
    await message.answer("Введи ID турнира для завершения:")

@dp.message(AdminFinishTournament.tournament_id)
async def process_finish_id(message: Message, state: FSMContext):
    try:
        t_id = int(message.text)
        if t_id not in tournaments or tournaments[t_id]['status'] != 'active':
            raise ValueError
        tournaments[t_id]['status'] = 'finished'
        await state.clear()
        await message.answer(f"Турнир #{t_id} завершён.")
        # Уведомление участникам
        for user_id in participants.get(t_id, []):
            await bot.send_message(user_id, f"Турнир #{t_id} завершён! Укажи результат:", reply_markup=get_result_menu())
    except:
        await message.answer("Неверный ID или уже завершён.")

@dp.message(F.text == "Я выиграл")
async def handle_won(message: Message, state: FSMContext):
    t_id = active_users.get(message.from_user.id)  # assume
    if t_id and tournaments[t_id]['status'] == 'finished':
        await state.set_state(ResultSubmission.requisites)
        await message.answer("Отправь реквизиты для выплаты:")
    else:
        await message.answer("Нет активного завершённого турнира.")

@dp.message(ResultSubmission.requisites)
async def process_requisites(message: Message, state: FSMContext):
    await state.update_data(requisites=message.text)
    await state.set_state(ResultSubmission.comment)
    await message.answer("Комментарий:")

@dp.message(ResultSubmission.comment)
async def process_comment(message: Message, state: FSMContext):
    await state.update_data(comment=message.text)
    await state.set_state(ResultSubmission.result_photo)
    await message.answer("Скрин результатов:")

@dp.message(ResultSubmission.result_photo, F.photo)
async def process_result_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    t_id = active_users.get(message.from_user.id)
    results[t_id][message.from_user.id] = {
        'won': True,
        'requisites': data['requisites'],
        'comment': data['comment'],
        'result_photo': message.photo[-1].file_id
    }
    await state.clear()
    await message.answer("Результат принят. Жди выплаты.")
    # Уведомление админу
    for admin in ADMIN_IDS:
        await bot.send_message(admin, f"Результат от {message.from_user.username} в #{t_id}: выиграл")

@dp.message(F.text == "Я проиграл")
async def handle_lost(message: Message):
    t_id = active_users.get(message.from_user.id)
    if t_id:
        results[t_id][message.from_user.id] = {'won': False}
        await message.answer("Спасибо за участие!")

# ─── УВЕДОМЛЕНИЯ ─────────────────────────────────────────────────────────
@dp.message(F.text == "Уведомить всех", lambda m: m.from_user.id in ADMIN_IDS)
async def notify_all_handler(message: Message):
    await message.answer("Введи текст уведомления:")
    # Следующий message — текст, отправляем всем

@dp.message()  # catch all for notify
async def send_notify(message: Message):
    if message.from_user.id in ADMIN_IDS:  # only if after notify
        text = message.text
        for user_id in all_users:
            try:
                await bot.send_message(user_id, text)
            except:
                pass
        await message.answer("Уведомление отправлено.")

async def notify_all(text: str):
    for user_id in all_users:
        try:
            await bot.send_message(user_id, text)
        except:
            pass

# ─── CANCEL ──────────────────────────────────────────────────────────────
@dp.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer("Отменено.", reply_markup=get_main_menu(is_admin))

# ─── MAIN ────────────────────────────────────────────────────────────────
async def main():
    logger.info("Бот запускается...")
    while True:
        try:
            await dp.start_polling(bot, drop_pending_updates=True, polling_timeout=20)
        except Exception as e:
            logger.exception("Polling crashed")
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
