import html
import logging
import asyncio
import os
import re
import json
import sys
import time
import aiosqlite
from groq import AsyncGroq
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup,
                           InlineKeyboardButton, FSInputFile, CallbackQuery)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# PPTX kutubxonalari
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN

# Fayllarni o'qish (ixtiyoriy, agar quiz kerak bo'lsa)
import pypdf
from docx import Document

# --- 1. SOZLAMALAR ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Environment variables
API_TOKEN = os.getenv('BOT_TOKEN')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
ADMIN_ID = os.getenv('ADMIN_ID')
CHANNEL_ID = "@abdujalils"  # Kanal usernameni shu yerda o'zgartiring

# Tekshiruv
if not API_TOKEN or not GROQ_API_KEY:
    logger.critical("❌ BOT_TOKEN yoki GROQ_API_KEY topilmadi!")
    sys.exit(1)

try:
    ADMIN_ID = int(ADMIN_ID) if ADMIN_ID else 0
except:
    ADMIN_ID = 0

# Obyektlar
client = AsyncGroq(api_key=GROQ_API_KEY)
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
DB_PATH = 'slide_master.db' # Renderda bu fayl restartdan keyin o'chadi (Persistent Disk bo'lmasa)

# --- 2. STATES ---
class UserStates(StatesGroup):
    waiting_package_choice = State()
    waiting_for_payment = State()
    waiting_for_quiz_file = State()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()

# --- 3. MATNLAR (LUG'AT) ---
LANGS = {
    'uz': {
        'welcome': "✨ <b>Slide Master AI Bot</b>\n\nProfessional taqdimotlar yaratuvchi sun'iy intellekt!\n\n👇 Quyidagi menyudan kerakli bo'limni tanlang:",
        'btns': ["💎 Tariflar", "📊 Kabinet", "🤝 Taklif qilish", "❓ Quiz Test", "🌐 Til / Language"],
        'sub_err': "🔒 <b>Botdan foydalanish cheklangan!</b>\n\nDavom etish uchun rasmiy kanalimizga obuna bo'ling:",
        'tarif': "💎 <b>TAQDIMOT NARXLARI:</b>\n\n⚡ <b>1 ta Slayd:</b> 990 so'm\n🔥 <b>5 ta Slayd:</b> 2,999 so'm\n👑 <b>VIP Premium (Cheksiz):</b> 5,999 so'm\n\n💳 <b>To'lov kartasi:</b> <code>9860230107924485</code>\n👤 <b>Karta egasi:</b> Abdujalil A.\n\n📸 <i>Paketni tanlang va keyin to'lov chekini yuboring:</i>",
        'choose_package': "🛒 <b>Paketni tanlang:</b>",
        'wait': "🧠 <b>AI ishlamoqda...</b>\n\nSlayd tuzilishi va dizayni generatsiya qilinmoqda. Bu jarayon 30-60 soniya vaqt oladi.",
        'done': "✅ <b>Taqdimot tayyor!</b>\n\nFaylni PowerPoint yoki WPS Office dasturida oching.",
        'no_bal': "⚠️ <b>Balans yetarli emas!</b>\n\nHisobni to'ldiring yoki do'stlaringizni taklif qiling.",
        'cancel': "❌ Bekor qilish",
        'gen_prompt': "Mavzu: {topic}. Nechta slayd kerak?",
        'btn_check': "✅ Obunani tekshirish",
        'btn_join': "📢 Kanalga qo'shilish",
        'error': "⚠️ Xatolik yuz berdi. Iltimos qayta urinib ko'ring.",
        'payment_sent': "✅ Chek adminga yuborildi. Tasdiqlangach balans qo'shiladi.",
        'package_btns': ["1️⃣ 1 ta Slayd", "5️⃣ 5 ta Slayd", "👑 VIP Premium"],
        'quiz_prompt': "📂 <b>Faylni yuboring!</b>\n\nPDF, DOCX yoki TXT fayl yuboring. Men undan test tuzib beraman.",
        'quiz_processing': "⏳ <b>Fayl o'qilmoqda...</b>",
        'quiz_error': "⚠️ Faylni o'qishda xatolik."
    },
    'ru': {
        'welcome': "✨ <b>Slide Master AI Bot</b>\n\nИИ для создания презентаций!",
        'btns': ["💎 Тарифы", "📊 Кабинет", "🤝 Пригласить", "❓ Quiz Test", "🌐 Til / Language"],
        'sub_err': "🔒 <b>Доступ ограничен!</b>\n\nПодпишитесь на канал:",
        'tarif': "💎 <b>ТАРИФЫ:</b>\n\n⚡ <b>1 Слайд:</b> 990 сум\n🔥 <b>5 Слайдов:</b> 2,999 сум\n👑 <b>VIP Premium:</b> 5,999 сум\n\n💳 <b>Карта:</b> <code>9860230107924485</code>\n👤 Abdujalil A.\n\n📸 <i>Выберите пакет и отправьте чек:</i>",
        'choose_package': "🛒 <b>Выберите пакет:</b>",
        'wait': "🧠 <b>AI думает...</b>\n\nГенерация может занять до 60 секунд.",
        'done': "✅ <b>Презентация готова!</b>",
        'no_bal': "⚠️ <b>Недостаточно средств!</b>",
        'cancel': "❌ Отмена",
        'gen_prompt': "Тема: {topic}. Сколько слайдов?",
        'btn_check': "✅ Проверить",
        'btn_join': "📢 Подписаться",
        'error': "⚠️ Ошибка. Попробуйте позже.",
        'payment_sent': "✅ Чек отправлен администратору.",
        'package_btns': ["1️⃣ 1 Слайд", "5️⃣ 5 Слайдов", "👑 VIP Premium"],
        'quiz_prompt': "📂 <b>Отправьте файл!</b>\n\nPDF, DOCX или TXT.",
        'quiz_processing': "⏳ <b>Обработка...</b>",
        'quiz_error': "⚠️ Ошибка чтения файла."
    },
    'en': {
        'welcome': "✨ <b>Slide Master AI Bot</b>\n\nAI powered presentation generator!",
        'btns': ["💎 Pricing", "📊 Profile", "🤝 Invite", "❓ Quiz Test", "🌐 Til / Language"],
        'sub_err': "🔒 <b>Access Restricted!</b>\n\nSubscribe to continue:",
        'tarif': "💎 <b>PRICING:</b>\n\n⚡ <b>1 Slide:</b> 990 UZS\n🔥 <b>5 Slides:</b> 2,999 UZS\n👑 <b>VIP Premium:</b> 5,999 UZS\n\n💳 <b>Card:</b> <code>9860230107924485</code>\n👤 Abdujalil A.\n\n📸 <i>Select package and send receipt:</i>",
        'choose_package': "🛒 <b>Choose package:</b>",
        'wait': "🧠 <b>AI is working...</b>\n\nPlease wait 30-60 seconds.",
        'done': "✅ <b>Ready!</b>",
        'no_bal': "⚠️ <b>Insufficient balance!</b>",
        'cancel': "❌ Cancel",
        'gen_prompt': "Topic: {topic}. How many slides?",
        'btn_check': "✅ Check Subscription",
        'btn_join': "📢 Join Channel",
        'error': "⚠️ Error occurred.",
        'payment_sent': "✅ Receipt sent to admin.",
        'package_btns': ["1️⃣ 1 Slide", "5️⃣ 5 Slides", "👑 VIP Premium"],
        'quiz_prompt': "📂 <b>Send file!</b>\n\nPDF, DOCX or TXT.",
        'quiz_processing': "⏳ <b>Processing...</b>",
        'quiz_error': "⚠️ Error reading file."
    }
}

def get_text(lang_code, key):
    return LANGS.get(lang_code, LANGS['uz']).get(key, LANGS['uz'].get(key, "Text not found"))

# --- 4. BAZA BILAN ISHLASH ---
class Database:
    def __init__(self, db_path):
        self.db_path = db_path

    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    lang TEXT DEFAULT 'uz',
                    is_premium INTEGER DEFAULT 0,
                    balance INTEGER DEFAULT 2,
                    invited_by BIGINT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id BIGINT,
                    amount INTEGER,
                    package_type TEXT,
                    status TEXT DEFAULT 'pending'
                )
            """)
            await db.commit()

    async def get_user(self, user_id):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cursor:
                return await cursor.fetchone()

    async def add_user(self, user_id, username, first_name, referrer_id=None):
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute(
                    "INSERT INTO users (id, username, first_name, invited_by, balance) VALUES (?, ?, ?, ?, 2)",
                    (user_id, username, first_name, referrer_id)
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def update_balance(self, user_id, amount):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user_id))
            await db.commit()

    async def set_premium(self, user_id):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE users SET is_premium = 1 WHERE id = ?", (user_id,))
            await db.commit()
            
    async def update_lang(self, user_id, lang):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE users SET lang = ? WHERE id = ?", (lang, user_id))
            await db.commit()

    async def add_payment(self, user_id, amount, package_type):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "INSERT INTO payments (user_id, amount, package_type) VALUES (?, ?, ?)",
                (user_id, amount, package_type)
            )
            await db.commit()
            return cursor.lastrowid
            
    async def get_all_users(self):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT id FROM users") as cursor:
                return await cursor.fetchall()
    
    async def get_stats(self):
         async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cur1:
                total = await cur1.fetchone()
            async with db.execute("SELECT COUNT(*) FROM users WHERE is_premium=1") as cur2:
                prem = await cur2.fetchone()
            return {'total': total[0], 'premium': prem[0]}

db = Database(DB_PATH)

# --- 5. PPTX GENERATOR (Optimize qilingan) ---
def clean_json_string(text):
    text = text.strip()
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match: return match.group(1)
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1: return text[start:end+1]
    return text

def create_pptx_sync(topic, json_data, uid):
    try:
        cleaned_json = clean_json_string(json_data)
        data = json.loads(cleaned_json)
        
        prs = Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)

        # Ranglar
        BG_COLOR = RGBColor(13, 17, 23)
        TEXT_WHITE = RGBColor(255, 255, 255)
        ACCENT_COLOR = RGBColor(0, 247, 255)

        for s_data in data.get('slides', []):
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            
            # Fon
            bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
            bg.fill.solid()
            bg.fill.fore_color.rgb = BG_COLOR
            bg.line.fill.background()

            # Sarlavha
            title_text = s_data.get('title', topic).upper()
            title_box = slide.shapes.add_textbox(Inches(0.5), Inches(0.5), Inches(12), Inches(1))
            p = title_box.text_frame.paragraphs[0]
            p.text = title_text
            p.font.bold = True
            p.font.size = Pt(36)
            p.font.color.rgb = TEXT_WHITE
            
            # Chiziq
            line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.5), Inches(1.5), Inches(3), Inches(0.05))
            line.fill.solid()
            line.fill.fore_color.rgb = ACCENT_COLOR
            line.line.fill.background()

            # Matn (Content)
            content_box = slide.shapes.add_textbox(Inches(0.5), Inches(2), Inches(12), Inches(4.5))
            tf = content_box.text_frame
            tf.word_wrap = True
            
            points = s_data.get('content', [])
            for point in points:
                p = tf.add_paragraph()
                if isinstance(point, dict):
                    bold_txt = point.get('bold', '')
                    norm_txt = point.get('text', '')
                    p.text = f"• {bold_txt}: {norm_txt}" if bold_txt else f"• {norm_txt}"
                else:
                    p.text = f"• {point}"
                
                p.font.size = Pt(18)
                p.font.color.rgb = RGBColor(200, 200, 200)
                p.space_after = Pt(14)

            # Footer
            footer = slide.shapes.add_textbox(Inches(10), Inches(7), Inches(3), Inches(0.4))
            fp = footer.text_frame.paragraphs[0]
            fp.text = "Slide Master AI"
            fp.font.size = Pt(10)
            fp.font.color.rgb = ACCENT_COLOR
            fp.alignment = PP_ALIGN.RIGHT

        os.makedirs("slides", exist_ok=True)
        filename = f"slides/Presentation_{uid}_{int(time.time())}.pptx"
        prs.save(filename)
        return filename

    except Exception as e:
        logger.error(f"PPTX Error: {e}")
        return None

# --- 6. UTILS ---
async def check_sub(user_id):
    if not CHANNEL_ID or CHANNEL_ID == "@abdujalils": return True # Test rejimi
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['creator', 'administrator', 'member']
    except:
        return True # Xatolik bo'lsa o'tkazib yuboramiz

async def show_main_menu(message: types.Message, lang):
    b = get_text(lang, 'btns')
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=b[0]), KeyboardButton(text=b[1])],
            [KeyboardButton(text=b[2]), KeyboardButton(text=b[3])],
            [KeyboardButton(text=b[4])]
        ], resize_keyboard=True
    )
    await message.answer(get_text(lang, 'welcome'), reply_markup=kb)

# --- 7. HANDLERS ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    ref_id = int(command.args) if command.args and command.args.isdigit() else None
    
    # O'zini o'zi taklif qilolmaydi
    if ref_id == uid: ref_id = None

    is_new = await db.add_user(uid, message.from_user.username, message.from_user.first_name, ref_id)
    
    if is_new and ref_id:
        await db.update_balance(ref_id, 1)
        try: await bot.send_message(ref_id, "🎉 <b>Yangi do'stingiz qo'shildi! Sizga +1 slayd berildi.</b>")
        except: pass

    user = await db.get_user(uid)
    lang = user['lang'] if user else 'uz'

    if not await check_sub(uid):
        btn = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_text(lang, 'btn_join'), url=f"https://t.me/{CHANNEL_ID.lstrip('@')}")],
            [InlineKeyboardButton(text=get_text(lang, 'btn_check'), callback_data="check_sub")]
        ])
        return await message.answer(get_text(lang, 'sub_err'), reply_markup=btn)

    await show_main_menu(message, lang)

@dp.callback_query(F.data == "check_sub")
async def callback_check_sub(callback: CallbackQuery):
    if await check_sub(callback.from_user.id):
        await callback.message.delete()
        user = await db.get_user(callback.from_user.id)
        await show_main_menu(callback.message, user['lang'])
    else:
        await callback.answer("❌ Hali a'zo bo'lmadingiz!", show_alert=True)

# Admin Panel
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Statistika", callback_data="adm_stats")],
        [InlineKeyboardButton(text="📢 Xabar yuborish", callback_data="adm_cast")]
    ])
    await message.answer("🛠 <b>Admin Panel</b>", reply_markup=kb)

@dp.message(F.text.startswith("/add_"))
async def admin_add_bal(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        _, uid, amt = message.text.split('_')
        await db.update_balance(int(uid), int(amt))
        await message.answer(f"✅ User {uid} balansiga +{amt} qo'shildi.")
    except:
        await message.answer("Format: /add_ID_AMOUNT")

@dp.message(F.text.startswith("/vip_"))
async def admin_set_vip(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        uid = int(message.text.split('_')[1])
        await db.set_premium(uid)
        await message.answer(f"✅ User {uid} VIP bo'ldi.")
    except:
        await message.answer("Format: /vip_ID")

# Menyular va Logika
@dp.message(F.text)
async def main_text_handler(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    user = await db.get_user(uid)
    if not user: return await message.answer("Iltimos /start ni bosing")
    
    l = user['lang']
    txt = message.text
    btns = get_text(l, 'btns')

    if txt == btns[0]: # Tariflar
        p_btns = get_text(l, 'package_btns')
        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text=p_btns[0]), KeyboardButton(text=p_btns[1])],
            [KeyboardButton(text=p_btns[2])],
            [KeyboardButton(text=get_text(l, 'cancel'))]
        ], resize_keyboard=True)
        await message.answer(get_text(l, 'tarif'), reply_markup=kb)
        await state.set_state(UserStates.waiting_package_choice)

    elif txt == btns[1]: # Kabinet
        status = "VIP PREMIUM 👑" if user['is_premium'] else "Oddiy 👤"
        await message.answer(
            f"📊 <b>KABINET</b>\n\n🆔 ID: <code>{uid}</code>\n💰 Balans: <b>{user['balance']} slayd</b>\n🏷 Status: <b>{status}</b>"
        )

    elif txt == btns[2]: # Taklif
        bot_usr = (await bot.get_me()).username
        link = f"https://t.me/{bot_usr}?start={uid}"
        await message.answer(
            f"🎁 <b>BONUS OLISH</b>\n\nHar bir do'stingiz uchun +1 slayd olasiz!\n\n🔗 Havola:\n`{link}`",
            parse_mode=ParseMode.MARKDOWN
        )

    elif txt == btns[3]: # Quiz
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=get_text(l, 'cancel'))]], resize_keyboard=True)
        await message.answer(get_text(l, 'quiz_prompt'), reply_markup=kb)
        await state.set_state(UserStates.waiting_for_quiz_file)

    elif txt == btns[4]: # Til
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🇺🇿 O'zbek", callback_data="lang_uz")],
            [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru")],
            [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")]
        ])
        await message.answer("Tilni tanlang / Select Language:", reply_markup=kb)
        
    elif txt == get_text(l, 'cancel'):
        await state.clear()
        await show_main_menu(message, l)
        
    else: # Generate Presentation Trigger
        if not user['is_premium'] and user['balance'] <= 0:
            return await message.answer(get_text(l, 'no_bal'))
            
        await state.update_data(topic=txt)
        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="5 Slayd", callback_data="gen:5"),
             InlineKeyboardButton(text="10 Slayd", callback_data="gen:10")]
        ])
        await message.answer(get_text(l, 'gen_prompt').format(topic=html.escape(txt)), reply_markup=ikb)

# --- Payment Handler ---
@dp.message(UserStates.waiting_package_choice)
async def package_choosen(message: types.Message, state: FSMContext):
    l = (await db.get_user(message.from_user.id))['lang']
    if message.text == get_text(l, 'cancel'):
        await state.clear()
        return await show_main_menu(message, l)
    
    # Mapping
    p_map = {
        "1️⃣": ("1_slide", 990), "1 ": ("1_slide", 990),
        "5️⃣": ("5_slides", 2999), "5 ": ("5_slides", 2999),
        "👑": ("vip", 5999)
    }
    
    choice = None
    for k, v in p_map.items():
        if k in message.text: choice = v
        
    if choice:
        await state.update_data(ptype=choice[0], amt=choice[1])
        await message.answer("📸 Endi to'lov chekini rasm qilib yuboring:")
        await state.set_state(UserStates.waiting_for_payment)
    else:
        await message.answer(get_text(l, 'choose_package'))

@dp.message(UserStates.waiting_for_payment, F.photo)
async def process_check(message: types.Message, state: FSMContext):
    data = await state.get_data()
    uid = message.from_user.id
    l = (await db.get_user(uid))['lang']
    
    pay_id = await db.add_payment(uid, data['amt'], data['ptype'])
    
    if ADMIN_ID:
        caption = (f"💰 <b>YANGI TO'LOV!</b>\n"
                   f"👤: {html.escape(message.from_user.full_name)}\n"
                   f"📦: {data['ptype']}\n"
                   f"💵: {data['amt']} so'm\n"
                   f"Commands: /add_{uid}_AMOUNT yoki /vip_{uid}")
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"confirm_{pay_id}"),
             InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_{pay_id}")]
        ])
        await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=caption, reply_markup=kb)
    
    await message.answer(get_text(l, 'payment_sent'))
    await state.clear()
    await show_main_menu(message, l)

# --- Admin Callbacks ---
@dp.callback_query(F.data.startswith("confirm_"))
async def approve_pay(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID: return
    pid = int(c.data.split("_")[1])
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        row = await (await conn.execute("SELECT * FROM payments WHERE id=?", (pid,))).fetchone()
        if row and row['status'] == 'pending':
            uid, ptype = row['user_id'], row['package_type']
            if ptype == 'vip': await db.set_premium(uid)
            elif ptype == '1_slide': await db.update_balance(uid, 1)
            elif ptype == '5_slides': await db.update_balance(uid, 5)
            
            await conn.execute("UPDATE payments SET status='approved' WHERE id=?", (pid,))
            await conn.commit()
            
            try: await bot.send_message(uid, "✅ To'lov tasdiqlandi! Hisobingiz to'ldirildi.")
            except: pass
            await c.message.edit_caption(caption=f"{c.message.caption}\n\n✅ TASDIQLANDI")

@dp.callback_query(F.data.startswith("reject_"))
async def reject_pay(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID: return
    pid = int(c.data.split("_")[1])
    # Shunchaki statusni o'zgartiramiz
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("UPDATE payments SET status='rejected' WHERE id=?", (pid,))
        await conn.commit()
    await c.message.edit_caption(caption=f"{c.message.caption}\n\n❌ RAD ETILDI")

# --- Language & Gen Callbacks ---
@dp.callback_query(F.data.startswith("lang_"))
async def set_language(c: CallbackQuery):
    lang = c.data.split("_")[1]
    await db.update_lang(c.from_user.id, lang)
    await c.message.delete()
    await show_main_menu(c.message, lang)

@dp.callback_query(F.data.startswith("gen:"))
async def generate_ppt_callback(c: CallbackQuery, state: FSMContext):
    await c.message.delete()
    uid = c.from_user.id
    user = await db.get_user(uid)
    l = user['lang']
    
    if not user['is_premium'] and user['balance'] <= 0:
        return await c.message.answer(get_text(l, 'no_bal'))

    count = c.data.split(":")[1]
    data = await state.get_data()
    topic = data.get('topic')
    
    wait_msg = await c.message.answer(get_text(l, 'wait'))
    await bot.send_chat_action(uid, 'upload_document')
    
    try:
        # Prompt yaratish
        sys_prompt = (
            f"You are a Presentation Expert. Language: {l}. "
            f"Create a JSON for a presentation with {count} slides. "
            "Format: {'slides': [{'title': 'Str', 'content': ['Str', 'Str']}]}."
            "Only return valid JSON."
        )
        
        resp = await client.chat.completions.create(
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": f"Topic: {topic}"}
            ],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"}
        )
        
        json_res = resp.choices[0].message.content
        
        # PPTXni thread da yasash (Blockingni oldini olish uchun)
        file_path = await asyncio.to_thread(create_pptx_sync, topic, json_res, uid)
        
        if file_path:
            await bot.send_document(uid, FSInputFile(file_path), caption=get_text(l, 'done'))
            if not user['is_premium']:
                await db.update_balance(uid, -1)
            
            # Faylni o'chirish (Tozalash)
            await asyncio.sleep(2)
            if os.path.exists(file_path): os.remove(file_path)
        else:
            await c.message.answer(get_text(l, 'error'))

    except Exception as e:
        logger.error(f"Gen Error: {e}")
        await c.message.answer(get_text(l, 'error'))
    finally:
        await state.clear()
        try: await wait_msg.delete()
        except: pass

# --- Main ---
async def main():
    await db.init()
    # Webhookni o'chirish (agar oldin sozlangan bo'lsa)
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot to'xtatildi")
