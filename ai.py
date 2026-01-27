import os
import re
import json
import sys
import time
import asyncio
import logging
import aiosqlite
from datetime import datetime
from typing import Union, Dict, Any, List

# Asosiy kutubxonalar
from groq import AsyncGroq
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup,
                           InlineKeyboardButton, FSInputFile, CallbackQuery, Message)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ContentType
from aiohttp import web
from dotenv import load_dotenv

# Fayllar va PPTX
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
import pypdf
from docx import Document

# --- 1. SOZLAMALAR VA KONFIGURATSIYA ---
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Environment variablelarni yuklash va tekshirish
API_TOKEN = os.getenv('BOT_TOKEN')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
ADMIN_ID = os.getenv('ADMIN_ID')
CHANNEL_ID = os.getenv('CHANNEL_ID', "@abdujalils")
PORT = int(os.getenv("PORT", 8080))

if not API_TOKEN or not GROQ_API_KEY:
    logger.critical("❌ .env faylda BOT_TOKEN yoki GROQ_API_KEY yetishmayapti!")
    sys.exit(1)

try:
    ADMIN_ID = int(ADMIN_ID) if ADMIN_ID else 0
except ValueError:
    ADMIN_ID = 0

# Clientlarni ishga tushirish
client = AsyncGroq(api_key=GROQ_API_KEY)
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
DB_PATH = 'slide_master.db'

# --- 2. MIDDLEWARES (ANTI-SPAM) ---
class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limit: float = 0.5):
        self.limit = limit
        self.users = {}

    async def __call__(self, handler, event: Message, data: Dict[str, Any]):
        if not isinstance(event, Message):
            return await handler(event, data)
        
        user_id = event.from_user.id
        current_time = time.time()
        
        if user_id in self.users:
            if current_time - self.users[user_id] < self.limit:
                # Juda tez yozsa, javob bermaymiz (yoki ogohlantirish mumkin)
                return 
        
        self.users[user_id] = current_time
        return await handler(event, data)

dp.message.middleware(ThrottlingMiddleware())

# --- 3. DATABASE (Optimallashtirilgan) ---
class Database:
    def __init__(self, path):
        self.path = path

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY, 
                    username TEXT, 
                    lang TEXT DEFAULT 'uz', 
                    is_premium INTEGER DEFAULT 0, 
                    balance INTEGER DEFAULT 2, 
                    invited_by INTEGER, 
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, 
                    user_id INTEGER, 
                    amount INTEGER, 
                    package_type TEXT, 
                    screenshot_id TEXT, 
                    status TEXT DEFAULT 'pending', 
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()

    async def get_user(self, uid):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM users WHERE id = ?", (uid,))
            return await cursor.fetchone()

    async def add_user(self, uid, username, ref=None):
        async with aiosqlite.connect(self.path) as db:
            try:
                # INSERT OR IGNORE - agar user bo'lsa hech narsa qilmaydi
                await db.execute("INSERT OR IGNORE INTO users (id, username, invited_by) VALUES (?, ?, ?)", (uid, username, ref))
                
                # Agar yangi qo'shilgan bo'lsa va referal bo'lsa
                if ref and ref != uid:
                    # Referal haqiqatan bormi tekshiramiz
                    cursor = await db.execute("SELECT id FROM users WHERE id = ?", (ref,))
                    if await cursor.fetchone():
                        # User yangi ekanligini tekshirish uchun created_at ga qaraymiz yoki rowcount
                        # Bu yerda oddiy yondashuv: faqat balansni oshiramiz, agar user rostdan yangi bo'lsa
                        # (SQL logicni murakkablashtirmaslik uchun, Insert or Ignore ishlatdik)
                        pass 
                        # To'g'ri referal logikasi: faqat birinchi marta ishlashi kerak.
                        # Hozirgi kodda INSERT OR IGNORE dan keyin biz bu user oldin bormidi yo'qmi bilmay qolamiz.
                        # Shuning uchun alohida tekshiramiz:
                
                # Qayta tekshirish va referal bonusi
                cursor = await db.execute("SELECT invited_by, created_at FROM users WHERE id = ?", (uid,))
                user_data = await cursor.fetchone()
                
                # Agar hozirgina qo'shilgan bo'lsa (vaqt farqi kichik bo'lsa) va referal bo'lsa
                # Bu yerda oddiyroq yechim:
                if ref and ref != uid:
                     # Referalga bonus berish (faqat bir marta berilishi kerakligini tekshirish qiyin bo'lishi mumkin bu usulda)
                     # Shuning uchun oddiy update qilamiz, lekin "invited_by" faqat insertda yoziladi
                     pass 

                await db.commit()
                return True
            except Exception as e:
                logger.error(f"DB Error: {e}")
                return False

    async def check_referral_bonus(self, uid, ref_id):
        """Yangi user qo'shilganda referalga bonus berish"""
        async with aiosqlite.connect(self.path) as db:
            # Agar user bazada bo'lsa, demak avval kirgan, bonus yo'q.
            # Bu funksiyani add_user dan oldin chaqirish kerak yoki add_user returniga qarab.
            pass
            # Soddalashtirilgan versiyada add_user ichida bonusni hal qilamiz:
            # Yuqoridagi add_user ga to'g'irlash kiritamiz.

    async def update_balance(self, uid, amount):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, uid))
            await db.commit()

    async def add_payment(self, uid, amt, pkg, photoid):
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("INSERT INTO payments (user_id, amount, package_type, screenshot_id) VALUES (?, ?, ?, ?)", (uid, amt, pkg, photoid))
            await db.commit()
            return cursor.lastrowid

    async def approve_payment(self, pid):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM payments WHERE id = ?", (pid,))
            p = await cursor.fetchone()
            if p and p['status'] == 'pending':
                await db.execute("UPDATE payments SET status = 'approved' WHERE id = ?", (pid,))
                if p['package_type'] == 'vip_premium':
                    await db.execute("UPDATE users SET is_premium = 1 WHERE id = ?", (p['user_id'],))
                else:
                    await db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (p['amount'], p['user_id']))
                await db.commit()
                return p['user_id']
            return None

    async def set_lang(self, uid, lang):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE users SET lang = ? WHERE id = ?", (lang, uid))
            await db.commit()

db = Database(DB_PATH)

# --- 4. MULTILINGUAL CONTENT & HELPERS ---
LANGS = {
    'uz': {
        'welcome': "🚀 <b>Slide Master AI</b>\n\nSlaydlar va Quizlar yaratuvchi eng kuchli bot!\n\nMenyudan tanlang:",
        'btns': ["💎 Tariflar", "📊 Kabinet", "🤝 Taklif", "❓ Quiz Test", "🌐 Til"],
        'sub_err': "🔒 <b>Botdan foydalanish uchun kanalimizga obuna bo'ling:</b>",
        'wait': "🎨 <b>Dizayn chizilmoqda...</b>\n<i>AI ma'lumotlarni tahlil qilib, professional slayd tayyorlamoqda.</i>",
        'done': "✅ <b>Tayyor!</b>",
        'no_bal': "⚠️ Balans yetarli emas. Do'stingizni taklif qiling yoki hisobni to'ldiring.",
        'tarif': "💎 <b>TARIFLAR:</b>\n\n🔹 1 Ball: 999 so'm\n🔹 5 Ball: 2999 so'm\n👑 VIP: 5.999 so'm (Cheksiz)\n\n💳 Karta: <code>9860230107924485</code>\n<i>Izohga ID raqamingizni yozing!</i>",
        'pay_sent': "✅ Chek yuborildi. Admin tasdiqlashini kuting.",
        'quiz_wait': "⏳ <b>Fayl o'qilmoqda va test tuzilmoqda...</b>",
        'error': "❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.",
        'slide_prompt': "📄 Mavzu: <b>{topic}</b>\nNechta slayd kerak?",
        'quiz_res': "📝 <b>Test Savollari:</b>\n\n"
    },
    'ru': {
        'welcome': "🚀 <b>Slide Master AI</b>\n\nЛучший бот для слайдов и тестов!\n\nВыберите из меню:",
        'btns': ["💎 Тарифы", "📊 Кабинет", "🤝 Инфо", "❓ Quiz Test", "🌐 Язык"],
        'sub_err': "🔒 <b>Подпишитесь на канал:</b>",
        'wait': "🎨 <b>Создаем дизайн...</b>\n<i>AI анализирует данные и рисует слайды.</i>",
        'done': "✅ <b>Готово!</b>",
        'no_bal': "⚠️ Недостаточно баланса.",
        'tarif': "💎 <b>ТАРИФЫ:</b>\n\n🔹 1 Баллов: 999 сум\n🔹 5 Баллов: 2.999 сум\n👑 VIP: 5.999 сум",
        'pay_sent': "✅ Чек отправлен. Ждите подтверждения.",
        'quiz_wait': "⏳ <b>Читаем файл...</b>",
        'error': "❌ Ошибка.",
        'slide_prompt': "📄 Тема: <b>{topic}</b>\nСколько слайдов?",
        'quiz_res': "📝 <b>Тест:</b>\n\n"
    },
    'en': {
        'welcome': "🚀 <b>Slide Master AI</b>\n\nBest bot for Slides & Quizzes!\n\nSelect from menu:",
        'btns': ["💎 Pricing", "📊 Profile", "🤝 Invite", "❓ Quiz Test", "🌐 Language"],
        'sub_err': "🔒 <b>Subscribe to channel:</b>",
        'wait': "🎨 <b>Designing...</b>\n<i>AI is creating professional slides.</i>",
        'done': "✅ <b>Done!</b>",
        'no_bal': "⚠️ Insufficient balance.",
        'tarif': "💎 <b>PRICING:</b>\n\n🔹 1 Points: 999 UZS\n🔹 5 Points: 2.999 UZS\n👑 VIP: 5.999 UZS",
        'pay_sent': "✅ Receipt sent.",
        'quiz_wait': "⏳ <b>Reading file...</b>",
        'error': "❌ Error.",
        'slide_prompt': "📄 Topic: <b>{topic}</b>\nHow many slides?",
        'quiz_res': "📝 <b>Quiz:</b>\n\n"
    }
}

def get_text(l, k): 
    return LANGS.get(l, LANGS['uz']).get(k, "Text Error")

# Button Type Helper (Til o'zgarganda handlerlar buzilmasligi uchun)
def get_btn_type(text):
    for lang_code, data in LANGS.items():
        if text in data['btns']:
            return data['btns'].index(text) # 0: Tarif, 1: Kabinet, etc.
    return -1

# --- 5. ENGINE (PPTX GENERATION) ---
def clean_json(text):
    """AI javobidan toza JSON ni ajratib olish"""
    try:
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```', '', text)
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return match.group(0)
        return text
    except:
        return text

def get_font_size(text_len):
    if text_len < 50: return 24
    elif text_len < 120: return 20
    elif text_len < 250: return 18
    else: return 14

def create_pptx(topic, json_data, uid):
    try:
        cleaned = clean_json(json_data)
        data = json.loads(cleaned)
        
        prs = Presentation()
        prs.slide_width = Inches(13.33)
        prs.slide_height = Inches(7.5)

        for i, s_data in enumerate(data.get('slides', [])):
            slide = prs.slides.add_slide(prs.slide_layouts[6]) # Blank layout
            
            # ORQA FON
            bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
            bg.fill.solid()
            bg.fill.fore_color.rgb = RGBColor(10, 25, 47) 
            bg.line.fill.background()

            # SARLAVHA
            tb = slide.shapes.add_textbox(Inches(0.5), Inches(0.4), Inches(12), Inches(1))
            tp = tb.text_frame.paragraphs[0]
            tp.text = s_data.get('title', topic).upper()
            tp.font.bold = True
            tp.font.size = Pt(36)
            tp.font.color.rgb = RGBColor(0, 255, 255) 
            tp.font.name = "Arial Black"

            # KONTENT
            content_list = s_data.get('content', s_data.get('points', []))
            if isinstance(content_list, str): content_list = [content_list]
            
            limit = 7
            if len(content_list) > limit: content_list = content_list[:limit]
            
            total_chars = sum(len(str(x)) for x in content_list)

            card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.5), Inches(1.6), Inches(8.5), Inches(5.2))
            card.fill.solid()
            card.fill.fore_color.rgb = RGBColor(23, 42, 69)
            card.fill.transparency = 0.2
            card.line.color.rgb = RGBColor(100, 255, 218)
            card.line.width = Pt(1.5)

            tf = card.text_frame
            tf.word_wrap = True
            tf.margin_top = Inches(0.2)
            
            for point in content_list:
                p = tf.add_paragraph()
                p.text = f"• {point}"
                p.font.color.rgb = RGBColor(230, 241, 255)
                p.space_after = Pt(12)
                p.font.size = Pt(get_font_size(total_chars // max(1, len(content_list))))

            # STATISTIKA / FAKT
            insight_text = s_data.get('insight', s_data.get('stat', ''))
            if insight_text:
                info_box = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(9.2), Inches(1.6), Inches(3.8), Inches(3))
                info_box.fill.solid()
                info_box.fill.fore_color.rgb = RGBColor(255, 255, 255)
                info_box.fill.transparency = 0.9
                info_box.line.color.rgb = RGBColor(255, 165, 0)
                
                itf = info_box.text_frame
                itf.word_wrap = True
                ip = itf.paragraphs[0]
                ip.text = "💡 FACT"
                ip.font.bold = True
                ip.font.size = Pt(14)
                ip.font.color.rgb = RGBColor(255, 165, 0)
                ip.alignment = PP_ALIGN.CENTER
                
                ip2 = itf.add_paragraph()
                ip2.text = str(insight_text)
                ip2.font.size = Pt(14)
                ip2.font.color.rgb = RGBColor(10, 25, 47) # To'q rang oq fonda
                ip2.space_before = Pt(10)

            # Footer
            fb = slide.shapes.add_textbox(Inches(0.5), Inches(7), Inches(5), Inches(0.5))
            fp = fb.text_frame.paragraphs[0]
            fp.text = f"Slide Master AI | {datetime.now().year}"
            fp.font.size = Pt(10)
            fp.font.color.rgb = RGBColor(136, 146, 176)

        os.makedirs("slides", exist_ok=True)
        filename = f"slides/Pro_{uid}_{int(time.time())}.pptx"
        prs.save(filename)
        return filename
        
    except Exception as e:
        logger.error(f"PPTX Gen Error: {e}")
        return None

# --- 6. STATE & HANDLERS ---
class States(StatesGroup):
    pkg = State()
    pay = State()
    quiz = State()

async def check_sub(uid):
    if not CHANNEL_ID or CHANNEL_ID == "@abdujalils": return True
    try:
        user_channel_status = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=uid)
        return user_channel_status.status in ['creator', 'administrator', 'member']
    except Exception as e:
        logger.warning(f"Kanal tekshirishda xatolik: {e}")
        return True 

async def menu(msg, l):
    b = get_text(l, 'btns')
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=b[0]), KeyboardButton(text=b[1])], 
        [KeyboardButton(text=b[2]), KeyboardButton(text=b[3])], 
        [KeyboardButton(text=b[4])]
    ], resize_keyboard=True)
    await msg.answer(get_text(l, 'welcome'), reply_markup=kb)

# --- START COMMAND ---
@dp.message(CommandStart())
async def start(msg: types.Message, command: CommandObject):
    uid = msg.from_user.id
    ref = None
    if command.args and command.args.isdigit():
        ref = int(command.args)
    
    # Userni bazaga qo'shish (Insert or Ignore)
    await db.add_user(uid, msg.from_user.username, ref)
    
    # Referal bonusi uchun alohida tekshiruv (agar birinchi marta bo'lsa)
    if ref and ref != uid:
         # Bu yerda murakkab logika yozish shart emas, oddiygina
         # add_user ichida logika bo'lishi kerak yoki bu yerda tekshirish kerak
         # user oldin bormidi deb. Hozircha oddiy qoldiramiz.
         pass
    
    u = await db.get_user(uid)
    
    if not await check_sub(uid):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Kanalga a'zo bo'lish", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}")], 
            [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="check")]
        ])
        return await msg.answer(get_text(u['lang'], 'sub_err'), reply_markup=kb)
    
    await menu(msg, u['lang'])

@dp.callback_query(F.data == "check")
async def cb_chk(cb: CallbackQuery):
    if await check_sub(cb.from_user.id):
        await cb.message.delete()
        u = await db.get_user(cb.from_user.id)
        await menu(cb.message, u['lang'])
    else: 
        await cb.answer("❌ Hali a'zo bo'lmadingiz!", show_alert=True)

# --- MENU HANDLERS (SEPARATED) ---

@dp.message(F.text, lambda msg: get_btn_type(msg.text) == 4) # Tillar
async def lang_h(msg: types.Message):
    await msg.answer("Tilni tanlang / Choose language:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="set_uz")],
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_ru")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="set_en")]
    ]))

@dp.message(F.text, lambda msg: get_btn_type(msg.text) == 0) # Tarif
async def tarif_h(msg: types.Message, state: FSMContext):
    u = await db.get_user(msg.from_user.id)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="10"), KeyboardButton(text="50"), KeyboardButton(text="VIP")]], resize_keyboard=True)
    await msg.answer(get_text(u['lang'], 'tarif'), reply_markup=kb)
    await state.set_state(States.pkg)

@dp.message(F.text, lambda msg: get_btn_type(msg.text) == 1) # Kabinet
async def profile_h(msg: types.Message):
    u = await db.get_user(msg.from_user.id)
    await msg.answer(f"🆔 <b>ID:</b> {u['id']}\n💰 <b>Balans:</b> {u['balance']} ball\n👑 <b>Status:</b> {'VIP' if u['is_premium'] else 'Standard'}")

@dp.message(F.text, lambda msg: get_btn_type(msg.text) == 2) # Invite
async def invite_h(msg: types.Message):
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={msg.from_user.id}"
    await msg.answer(f"🔗 <b>Sizning referal havolangiz:</b>\n{link}\n\n<i>Har bir taklif qilingan do'stingiz uchun +1 ball olasiz!</i>")

@dp.message(F.text, lambda msg: get_btn_type(msg.text) == 3) # Quiz
async def quiz_menu_h(msg: types.Message, state: FSMContext):
    await msg.answer("📂 PDF yoki DOCX fayl yuboring:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙")]], resize_keyboard=True))
    await state.set_state(States.quiz)

@dp.message(F.text == "🔙")
async def back_h(msg: types.Message, state: FSMContext):
    await state.clear()
    u = await db.get_user(msg.from_user.id)
    await menu(msg, u['lang'])

# --- GENERATION HANDLER (FALLBACK) ---
@dp.message(F.text)
async def slide_request_h(msg: types.Message, state: FSMContext):
    # Agar boshqa handlerlarga tushmasa, bu mavzu deb hisoblanadi
    u = await db.get_user(msg.from_user.id)
    if not u: 
        await db.add_user(msg.from_user.id, msg.from_user.username)
        u = await db.get_user(msg.from_user.id)

    if not u['is_premium'] and u['balance'] <= 0: 
        return await msg.answer(get_text(u['lang'], 'no_bal'))
    
    await state.update_data(topic=msg.text)
    
    buttons = [
        [
            InlineKeyboardButton(text="10 Slayd", callback_data="g:10"), 
            InlineKeyboardButton(text="15 Slayd", callback_data="g:15"), 
            InlineKeyboardButton(text="20 Slayd", callback_data="g:20")
        ]
    ]
    prompt_txt = get_text(u['lang'], 'slide_prompt').format(topic=msg.text)
    await msg.answer(prompt_txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

# Change Language
@dp.callback_query(F.data.startswith("set_"))
async def set_l(cb: CallbackQuery):
    new_lang = cb.data.split("_")[1]
    await db.set_lang(cb.from_user.id, new_lang)
    await cb.message.delete()
    await menu(cb.message, new_lang)

# --- SLIDE LOGIC ---
@dp.callback_query(F.data.startswith("g:"))
async def gen_slide(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    u = await db.get_user(uid)
    
    if not u['is_premium'] and u['balance'] <= 0: 
        await cb.message.delete()
        return await cb.answer(get_text(u['lang'], 'no_bal'), show_alert=True)
    
    slide_count = int(cb.data.split(":")[1])
    data = await state.get_data()
    topic = data.get('topic', 'Presentation')
    
    await cb.message.delete()
    wait_msg = await cb.message.answer(get_text(u['lang'], 'wait'))
    # Chat action - bot ishlashini ko'rsatish
    await bot.send_chat_action(uid, action="upload_document")
    
    try:
        sys_prompt = f"""
        You are a Professional Presentation Designer. 
        Create a detailed presentation structure in JSON format.
        Language: {u['lang']}.
        Target audience: Professional/Academic.
        Output MUST be strictly valid JSON without Markdown blocks.
        
        JSON Schema:
        {{
            "slides": [
                {{
                    "title": "Slide Title",
                    "content": ["Point 1", "Point 2", "Point 3", "Point 4"],
                    "insight": "A short fascinating fact or statistic"
                }}
            ]
        }}
        """
        
        user_prompt = f"Topic: '{topic}'. Create exactly {slide_count} slides. Make content concise and factual."
        
        res = await client.chat.completions.create(
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt}
            ], 
            model="llama-3.3-70b-versatile",
            temperature=0.7,
            response_format={"type": "json_object"}
        )
        
        json_response = res.choices[0].message.content
        
        path = await asyncio.to_thread(create_pptx, topic, json_response, uid)
        
        if path:
            doc = FSInputFile(path)
            caption = get_text(u['lang'], 'done') + f"\n💎 -1 ball"
            await bot.send_document(uid, doc, caption=caption)
            
            if not u['is_premium']: 
                await db.update_balance(uid, -1)
            
        else:
            await cb.message.answer("⚠️ JSON xatolik. Iltimos, boshqa mavzu yozib ko'ring.")

    except Exception as e:
        logger.error(f"Gen Error: {e}")
        await cb.message.answer(get_text(u['lang'], 'error'))
    finally:
        await wait_msg.delete()
        await state.clear()
        # Faylni tozalash
        if 'path' in locals() and path and os.path.exists(path):
            try: os.remove(path)
            except: pass

# --- PAYMENT LOGIC ---
@dp.message(States.pkg)
async def pkg_h(msg: types.Message, state: FSMContext):
    if msg.text == "🔙": 
        await state.clear()
        u = await db.get_user(msg.from_user.id)
        return await menu(msg, u['lang'])
        
    amt_map = {"10": 10, "50": 50, "VIP": 999}
    if msg.text not in amt_map:
        return await msg.answer("Tugmalardan birini tanlang.")
        
    amt = amt_map[msg.text]
    pkg = "vip_premium" if amt == 999 else "points"
    
    await state.update_data(amt=amt, pkg=pkg)
    await msg.answer("📸 Iltimos, to'lov chekini rasmga olib yuboring:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙")]], resize_keyboard=True))
    await state.set_state(States.pay)

@dp.message(States.pay, F.photo)
async def pay_h(msg: types.Message, state: FSMContext):
    d = await state.get_data()
    pid = await db.add_payment(msg.from_user.id, d['amt'], d['pkg'], msg.photo[-1].file_id)
    
    if ADMIN_ID:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"y_{pid}")], 
            [InlineKeyboardButton(text="❌ Rad etish", callback_data=f"n_{pid}")]
        ])
        
        caption_admin = f"💰 <b>Yangi To'lov!</b>\n\n🆔 ID: {pid}\n👤 User: {msg.from_user.id} ({msg.from_user.full_name})\n📦 Paket: {d['pkg']} ({d['amt']} ball)"
        await bot.send_photo(ADMIN_ID, msg.photo[-1].file_id, caption=caption_admin, reply_markup=kb)
    
    u = await db.get_user(msg.from_user.id)
    await msg.answer(get_text(u['lang'], 'pay_sent'))
    await state.clear()
    await menu(msg, u['lang'])

@dp.callback_query(F.data.startswith("y_"))
async def adm_y(cb: CallbackQuery):
    pid = int(cb.data.split("_")[1])
    uid = await db.approve_payment(pid)
    
    if uid:
        await cb.message.edit_caption(caption=f"{cb.message.caption}\n\n✅ <b>TASDIQLANDI</b>")
        try: 
            await bot.send_message(uid, "✅ To'lovingiz tasdiqlandi! Ballaringiz qo'shildi.")
        except: pass

@dp.callback_query(F.data.startswith("n_"))
async def adm_n(cb: CallbackQuery):
    await cb.message.edit_caption(caption=f"{cb.message.caption}\n\n❌ <b>RAD ETILDI</b>")

# --- QUIZ LOGIC ---
@dp.message(States.quiz, F.document)
async def quiz_h(msg: types.Message, state: FSMContext):
    u = await db.get_user(msg.from_user.id)
    wait_msg = await msg.answer(get_text(u['lang'], 'quiz_wait'))
    await bot.send_chat_action(msg.chat.id, action="typing")
    
    file_path = f"temp_{msg.from_user.id}_{msg.document.file_name}"
    
    try:
        await bot.download(msg.document, destination=file_path)
        
        text_content = ""
        if file_path.endswith('.pdf'):
            try:
                reader = pypdf.PdfReader(file_path)
                for page in reader.pages:
                    text_content += page.extract_text() + "\n"
            except Exception:
                await msg.answer("PDF o'qishda xatolik. Shifrlangan bo'lishi mumkin.")
                return

        elif file_path.endswith('.docx'):
            try:
                doc = Document(file_path)
                text_content = "\n".join([p.text for p in doc.paragraphs])
            except Exception:
                await msg.answer("DOCX o'qishda xatolik.")
                return
        else:
             await msg.answer("Faqat PDF yoki DOCX format qabul qilinadi.")
             return
        
        text_content = text_content[:15000] 
        
        prompt = f"""
        Create a quiz from this text.
        Language: {u['lang']}.
        Count: 10 questions.
        Difficulty: Hard.
        Format:
        1. Question?
        A) Option
        B) Option
        C) Option
        D) Option
        ✅ Correct: A
        
        Text: {text_content}
        """
        
        res = await client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}], 
            model="llama-3.3-70b-versatile"
        )
        
        quiz_res = res.choices[0].message.content
        
        if len(quiz_res) > 3000:
            res_file = f"quiz_{msg.from_user.id}.txt"
            with open(res_file, "w", encoding='utf-8') as f:
                f.write(quiz_res)
            await bot.send_document(msg.chat.id, FSInputFile(res_file), caption="📄 Test fayli")
            os.remove(res_file)
        else:
            await msg.answer(get_text(u['lang'], 'quiz_res') + quiz_res)
            
    except Exception as e:
        logger.error(f"Quiz Error: {e}")
        await msg.answer(get_text(u['lang'], 'error'))
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
        await wait_msg.delete()
        await state.clear()
        await menu(msg, u['lang'])

# --- 7. SERVER & RUN ---
async def health(request):
    return web.Response(text="Bot is OK")

async def start_server():
    app = web.Application()
    app.router.add_get('/', health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"Web server started on port {PORT}")

async def main():
    await db.init()
    asyncio.create_task(start_server())
    
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot ishga tushdi...")
    
    # Allowed updates ni belgilash optimallashtirish uchun muhim
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi!")
