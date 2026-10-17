import asyncio, os
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
router = Router()

def main_menu():
    rows = [[KeyboardButton(text="🎮 Играть", web_app=WebAppInfo(url=WEBAPP_URL))],
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🎁 Бонус")],
            [KeyboardButton(text="🏆 Топ игроков"), KeyboardButton(text="ℹ️ Помощь")]]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

@router.message(CommandStart())
async def start(message: Message):
    name = message.from_user.first_name if message.from_user else "Игрок"
    await message.answer(
        f"🏁 <b>Добро пожаловать в PLATE CLUB, {name}!</b>\n\n"
        "Собирай государственные номера, открывай кейсы, ищи редкие комбинации и торгуй на рынке.\n\n"
        "Нажми «🎮 Играть», чтобы открыть клуб. Аккаунт и прогресс будут привязаны к твоему Telegram.",
        reply_markup=main_menu(), parse_mode="HTML")

@router.message(Command("help"))
@router.message(lambda m: m.text == "ℹ️ Помощь")
async def help_message(message: Message):
    await message.answer("🎮 Играй через кнопку в меню.\n🔐 Вход выполняется через Telegram.\n💾 Прогресс сохраняется на игровом сервере.", reply_markup=main_menu())

@router.message(lambda m: m.text == "👤 Профиль")
async def profile(message: Message):
    await message.answer("Открой игру кнопкой «🎮 Играть» — там доступны твой профиль, гараж, баланс и достижения.", reply_markup=main_menu())

@router.message(lambda m: m.text == "🎁 Бонус")
async def bonus(message: Message):
    await message.answer("Ежедневный бонус доступен в игре: нажми «🎮 Играть» и забери награду в разделе бонусов.", reply_markup=main_menu())

@router.message(lambda m: m.text == "🏆 Топ игроков")
async def leaderboard(message: Message):
    await message.answer("Рейтинг игроков находится внутри PLATE CLUB. Нажми «🎮 Играть», затем открой таблицу лидеров.", reply_markup=main_menu())

async def main():
    if not TOKEN:
        raise SystemExit("Не задан TELEGRAM_BOT_TOKEN. Заполни .env по образцу .env.example")
    if not WEBAPP_URL.startswith("https://"):
        raise SystemExit("WEBAPP_URL должен быть публичным HTTPS-адресом Mini App")
    bot = Bot(TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    print("PLATE CLUB bot is polling. Stop with Ctrl+C.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
