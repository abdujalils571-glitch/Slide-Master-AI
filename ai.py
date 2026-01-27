import os
import re
import json
import sys
import time
import asyncio
import logging
import aiosqlite
import html
import traceback
from datetime import datetime

# Tashqi kutubxonalar
from groq import AsyncGroq
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup,
                           InlineKeyboardButton, FSInputFile, CallbackQuery)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web

# PPTX va Dizayn uchun
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
import pypdf
from docx import Document

# --- 1. KONFIGURATSIYA ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

API_TOKEN = os.getenv('BOT_TOKEN')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
ADMIN_ID = os.getenv('ADMIN_ID', '0')
CHANNEL_ID = os.getenv('CHANNEL_ID', "@abdujalils")

if not API_TOKEN or not GROQ_API_KEY:
    logger.critical("❌ XATOLIK: Tokenlar topilmadi!")
    sys.exit(1)

try:
    ADMIN_ID = int(ADMIN_ID)
except:
    ADMIN_ID = 0

client = AsyncGroq(api_key=GROQ_API_KEY)
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
DB_PATH = 'slide_master.db'

# --- 2. MULTILINGUAL CONTENT ---
LANGS = {
    'uz': {
        'welcome': "🚀 <b>Slide Master AI 2.0</b>\n\nProfessional slaydlar va testlar yaratuvchi eng kuchli yordamchi.\n\nQuyidagi menyudan foydalaning:",
        'btns': ["💎 Tariflar", "📊 Kabinet", "🤝 Taklif qilish", "❓ Quiz Test", "🌐 Til"],
        'sub_err': "🔒 <b>Botdan foydalanish uchun kanalga a'zo bo'ling:</b>",
        'tarif': "💎 <b>TARIFLAR:</b>\n\n⚡ 1 Slayd: 990 so'm\n🔥 5 Slayd: 2,999 so'm\n👑 VIP (Cheksiz): 5,999 so'm\n\n💳 Karta: <code>9860230107924485</code>\n📸 To'lovdan so'ng chekni yuboring:",
        'wait': "🎨 <b>Dizayn chizilmoqda...</b>\n<i>AI ma'lumotlarni tahlil qilib, eng zamonaviy dizaynda slayd tayyorlamoqda.</i>",
        'done': "✅ <b>Slayd Tayyor!</b>\n<i>Premium dizayn va sifatli ma'lumotlar bilan.</i>",
        'no_bal': "⚠️ <b>Balans yetarli emas!</b>",
        'cancel': "❌ Bekor qilish",
        'gen_prompt': "📝 <b>Mavzu:</b> {topic}\n\nNechta slayd kerak?",
        'quiz_prompt': "📂 <b>Fayl yuboring (PDF/DOCX/TXT):</b>",
        'payment_sent': "✅ Chek qabul qilindi, kuting.",
        'package_btns': ["1️⃣ 1 ta Slayd", "5️⃣ 5 ta Slayd", "👑 VIP Premium"],
        'referral': "🎁 <b>Sizning havolangiz:</b>\n",
        'error': "❌ Xatolik yuz berdi."
    },
    'ru': {
        'welcome': "🚀 <b>Slide Master AI 2.0</b>\n\nМощный помощник для создания профессиональных слайдов.",
        'btns': ["💎 Тарифы", "📊 Кабинет", "🤝 Пригласить", "❓ Quiz Test", "🌐 Til"],
        'sub_err': "🔒 <b>Подпишитесь на канал:</b>",
        'tarif': "💎 <b>ТАРИФЫ:</b>\n\n⚡ 1 Слайд: 990 сум\n🔥 5 Слайдов: 2,999 сум\n👑 VIP: 5,999 сум",
        'wait': "🎨 <b>Создаем дизайн...</b>\n<i>AI анализирует данные и рисует слайды.</i>",
        'done': "✅ <b>Готово!</b>",
        'no_bal': "⚠️ <b>Недостаточно баланса!</b>",
        'cancel': "❌ Отмена",
        'gen_prompt': "📝 <b>Тема:</b> {topic}\n\nСколько слайдов?",
        'quiz_prompt': "📂 <b>Отправьте файл:</b>",
        'payment_sent': "✅ Чек получен.",
        'package_btns': ["1️⃣ 1 Слайд", "5️⃣ 5 Слайдов", "👑 VIP Premium"],
        'referral': "🎁 Ваша ссылка:\n",
        'error': "❌ Ошибка."
    },
    'en': {
        'welcome': "🚀 <b>Slide Master AI 2.0</b>\n\nProfessional slide & quiz generator.",
        'btns': ["💎 Pricing", "📊 Profile", "🤝 Invite", "❓ Quiz Test", "🌐 Til"],
        'sub_err': "🔒 <b>Subscribe to channel:</b>",
        'tarif': "💎 <b>PRICING:</b>\n\n⚡ 1 Slide: 990 UZS\n🔥 5 Slides: 2,999 UZS\n👑 VIP: 5,999 UZS",
        'wait': "🎨 <b>Designing...</b>\n<i>AI is crafting a modern presentation.</i>",
        'done': "✅ <b>Done!</b>",
        'no_bal': "⚠️ Insufficient balance!",
        'cancel': "❌ Cancel",
        'gen_prompt': "📝 <b>Topic:</b> {topic}\n\nHow many slides?",
        'quiz_prompt': "📂 <b>Send file:</b>",
        'payment_sent': "✅ Receipt received.",
        'package_btns': ["1️⃣ 1 Slide", "5️⃣ 5 Slides", "👑 VIP Premium"],
        'referral': "🎁 Invite link:\n",
        'error': "❌ Error."
    }
}

def get_text(lang, key):
    return LANGS.get(lang, LANGS['uz']).get(key, LANGS['uz'][key])

# --- 3. DATABASE ---
class Database:
    def __init__(self, path): self.path = path
    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("CREATE TABLE IF NOT EXISTS users (id BIGINT PRIMARY KEY, username TEXT, lang TEXT DEFAULT 'uz', is_premium INTEGER DEFAULT 0, balance INTEGER DEFAULT 2, invited_by BIGINT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            await db.execute("CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id BIGINT, amount INTEGER, package_type TEXT, screenshot_id TEXT, status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            await db.commit()
    async def get_user(self, uid):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            return await (await db.execute("SELECT * FROM users WHERE id = ?", (uid,))).fetchone()
    async def add_user(self, uid, username, ref_id=None):
        async with aiosqlite.connect(self.path) as db:
            try:
                await db.execute("INSERT INTO users (id, username, invited_by) VALUES (?, ?, ?)", (uid, username, ref_id))
                if ref_id: await db.execute("UPDATE users SET balance = balance + 1 WHERE id = ?", (ref_id,))
                await db.commit()
                return True
            except: return False
    async def update_balance(self, uid, amount):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, uid))
            await db.commit()
    async def set_lang(self, uid, lang):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE users SET lang = ? WHERE id = ?", (lang, uid))
            await db.commit()
    async def add_payment(self, uid, amount, pkg, photo):
        async with aiosqlite.connect(self.path) as db:
            c = await db.execute("INSERT INTO payments (user_id, amount, package_type, screenshot_id) VALUES (?, ?, ?, ?)", (uid, amount, pkg, photo))
            await db.commit()
            return c.lastrowid
    async def approve_payment(self, pid):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            p = await (await db.execute("SELECT * FROM payments WHERE id = ?", (pid,))).fetchone()
            if p and p['status'] == 'pending':
                await db.execute("UPDATE payments SET status = 'approved' WHERE id = ?", (pid,))
                if p['package_type'] == 'vip_premium' or p['amount'] >= 999:
                    await db.execute("UPDATE users SET is_premium = 1 WHERE id = ?", (p['user_id'],))
                else:
                    await db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (p['amount'], p['user_id']))
                await db.commit()
                return p['user_id']
            return None

db = Database(DB_PATH)

# --- 4. ENGINE (PPTX GENERATION) ---
class UserStates(StatesGroup):
    choosing_pkg = State()
    waiting_pay = State()
    waiting_quiz = State()

def clean_json_response(content):
    content = re.sub(r'```json\s*', '', content)
    content = re.sub(r'```', '', content)
    start, end = content.find('{'), content.rfind('}') + 1
    return content[start:end] if start != -1 and end != -1 else content

# Matn sig'ishini tekshiruvchi funksiya
def fit_text(text_frame, text, max_size=24, is_bold=False):
    p = text_frame.add_paragraph()
    p.text = text
    p.font.bold = is_bold
    p.font.color.rgb = RGBColor(255, 255, 255)
    
    # Avtomatik shrift o'lchamini tanlash (uzunlikka qarab)
    length = len(text)
    if length < 50: p.font.size = Pt(max_size)
    elif length < 100: p.font.size = Pt(max_size - 4)
    elif length < 200: p.font.size = Pt(max_size - 8)
    else: p.font.size = Pt(max_size - 10) # Juda uzun matnlar uchun kichik shrift

def create_pptx(topic, json_data, uid):
    try:
        data = json.loads(clean_json_response(json_data))
        prs = Presentation()
        prs.slide_width, prs.slide_height = Inches(13.33), Inches(7.5) # 16:9 HD

        for s_data in data.get('slides', []):
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            
            # --- 1. ZAMONAVIY ORQA FON (Gradient effekt) ---
            bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
            bg.fill.solid()
            bg.fill.fore_color.rgb = RGBColor(15, 23, 42) # Deep Navy (Zamonaviy Dark mode)
            bg.line.fill.background()

            # Dekorativ element (O'ng burchakdagi rangli shar)
            circle = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(10), Inches(-1), Inches(5), Inches(5))
            circle.fill.solid()
            circle.fill.fore_color.rgb = RGBColor(6, 182, 212) # Cyan
            circle.fill.transparency = 0.85 # Shaffof
            circle.line.fill.background()

            # --- 2. SARLAVHA (Chap tomonda, yirik) ---
            tb = slide.shapes.add_textbox(Inches(0.5), Inches(0.4), Inches(12), Inches(1.2))
            tp = tb.text_frame.paragraphs[0]
            tp.text = s_data.get('title', topic).upper()
            tp.font.bold = True
            tp.font.size = Pt(36)
            tp.font.name = 'Arial Black'
            tp.font.color.rgb = RGBColor(255, 255, 255) # Oq

            # Ostki chiziq (Accent)
            line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.5), Inches(1.5), Inches(2), Inches(0.05))
            line.fill.solid()
            line.fill.fore_color.rgb = RGBColor(249, 115, 22) # Orange
            line.line.fill.background()

            # --- 3. ASOSIY KONTENT (Glassmorphism karta ichida) ---
            # Matnlar ustma-ust tushmasligi uchun maxsus joy ajratamiz
            cb = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.5), Inches(1.8), Inches(8), Inches(5))
            cb.fill.solid()
            cb.fill.fore_color.rgb = RGBColor(30, 41, 59) # Slate 800
            cb.fill.transparency = 0.1
            cb.line.color.rgb = RGBColor(71, 85, 105) # Chegara rangi
            cb.line.width = Pt(1)

            tf = cb.text_frame
            tf.word_wrap = True
            tf.margin_top = Inches(0.2)
            
            # Smart Content joylashtirish
            content_list = s_data.get('content', [])
            # Agar kontent juda ko'p bo'lsa, faqat birinchilarini olamiz (sig'maslikni oldini olish)
            if len(content_list) > 6: content_list = content_list[:6]
            
            for point in content_list:
                # Har bir bullet uchun alohida paragraf emas, bitta ro'yxat
                p = tf.add_paragraph()
                p.text = f"• {point}"
                p.font.color.rgb = RGBColor(226, 232, 240) # Oq-kulrang
                p.space_after = Pt(14) # Qatorlar orasi ochiqroq
                # Shrift o'lchami ro'yxat uzunligiga qarab o'zgaradi
                if len(content_list) <= 3: p.font.size = Pt(22)
                elif len(content_list) <= 5: p.font.size = Pt(18)
                else: p.font.size = Pt(16)

            # --- 4. INSIGHT (Alohida ajralib turuvchi blok) ---
            if s_data.get('insight'):
                ib = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(8.8), Inches(1.8), Inches(4), Inches(5))
                ib.fill.solid()
                ib.fill.fore_color.rgb = RGBColor(15, 23, 42)
                ib.line.color.rgb = RGBColor(6, 182, 212) # Cyan Border
                ib.line.width = Pt(2)

                itf = ib.text_frame
                itf.word_wrap = True
                ip = itf.paragraphs[0]
                ip.text = "💡 MUHIM FAKT"
                ip.font.bold = True
                ip.font.size = Pt(18)
                ip.font.color.rgb = RGBColor(6, 182, 212)
                ip.alignment = PP_ALIGN.CENTER
                
                ip2 = itf.add_paragraph()
                ip2.text = s_data['insight']
                ip2.font.size = Pt(16)
                ip2.font.color.rgb = RGBColor(255, 255, 255)
                ip2.space_before = Pt(20)
                ip2.alignment = PP_ALIGN.LEFT

        path = f"slides/S_{uid}_{int(time.time())}.pptx"
        os.makedirs("slides", exist_ok=True)
        prs.save(path)
        return path
    except Exception as e:
        logger.error(f"PPTX Error: {e}")
        return None

# --- 5. HANDLERS ---
async def check_sub(uid):
    try:
        if not CHANNEL_ID or CHANNEL_ID == "@abdujalils": return True
        m = await bot.get_chat_member(CHANNEL_ID, uid)
        return m.status in ['member', 'administrator', 'creator']
    except: return True

async def main_menu(msg, lang):
    b = get_text(lang, 'btns')
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=b[0]), KeyboardButton(text=b[1])], [KeyboardButton(text=b[2]), KeyboardButton(text=b[3])], [KeyboardButton(text=b[4])]], resize_keyboard=True)
    await msg.answer(get_text(lang, 'welcome'), reply_markup=kb)

@dp.message(Command("start"))
async def cmd_start(msg: types.Message, cmd: CommandObject, state: FSMContext):
    await state.clear()
    uid = msg.from_user.id
    ref = int(cmd.args) if cmd.args and cmd.args.isdigit() and int(cmd.args) != uid else None
    await db.add_user(uid, msg.from_user.username, ref)
    u = await db.get_user(uid)
    if not await check_sub(uid):
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📢 Kanal", url=f"https://t.me/{CHANNEL_ID[1:]}")], [InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")]])
        return await msg.answer(get_text(u['lang'], 'sub_err'), reply_markup=kb)
    await main_menu(msg, u['lang'])

@dp.callback_query(F.data == "check_sub")
async def cb_sub(cb: CallbackQuery):
    if await check_sub(cb.from_user.id):
        await cb.message.delete()
        u = await db.get_user(cb.from_user.id)
        await main_menu(cb.message, u['lang'])
    else: await cb.answer("❌ Obuna bo'ling!", show_alert=True)

@dp.callback_query(F.data.startswith("setlang_"))
async def cb_lang(cb: CallbackQuery):
    await db.set_lang(cb.from_user.id, cb.data.split("_")[1])
    await cb.message.delete()
    await main_menu(cb.message, cb.data.split("_")[1])

@dp.message(F.text)
async def handle_text(msg: types.Message, state: FSMContext):
    u = await db.get_user(msg.from_user.id)
    if not u: await db.add_user(msg.from_user.id, msg.from_user.username); u = await db.get_user(msg.from_user.id)
    l, txt = u['lang'], msg.text
    
    # Menyu
    btns = LANGS[l]['btns']
    if txt == btns[0]: # Tarif
        pkgs = get_text(l, 'package_btns')
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=pkgs[0]), KeyboardButton(text=pkgs[1])], [KeyboardButton(text=pkgs[2])], [KeyboardButton(text=get_text(l, 'cancel'))]], resize_keyboard=True)
        await msg.answer(get_text(l, 'tarif'), reply_markup=kb)
        await state.set_state(UserStates.choosing_pkg)
    elif txt == btns[1]: # Kabinet
        st = "👑 VIP" if u['is_premium'] else "🆓 Basic"
        await msg.answer(f"👤 <b>ID:</b> {u['id']}\n💰 <b>Balans:</b> {u['balance']} slayd\n🏷 <b>Status:</b> {st}")
    elif txt == btns[2]: # Invite
        await msg.answer(f"{get_text(l, 'referral')}https://t.me/{(await bot.get_me()).username}?start={u['id']}")
    elif txt == btns[3]: # Quiz
        await msg.answer(get_text(l, 'quiz_prompt'), reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=get_text(l, 'cancel'))]], resize_keyboard=True))
        await state.set_state(UserStates.waiting_quiz)
    elif txt == btns[4]: # Lang
        await msg.answer("Til / Language:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="UZ 🇺🇿", callback_data="setlang_uz"), InlineKeyboardButton(text="RU 🇷🇺", callback_data="setlang_ru"), InlineKeyboardButton(text="EN 🇺🇸", callback_data="setlang_en")]]))
    elif txt in [LANGS['uz']['cancel'], LANGS['ru']['cancel'], LANGS['en']['cancel']]:
        await state.clear(); await main_menu(msg, l)
    else:
        if not u['is_premium'] and u['balance'] <= 0: return await msg.answer(get_text(l, 'no_bal'))
        await state.update_data(topic=txt)
        await msg.answer(get_text(l, 'gen_prompt').format(topic=html.escape(txt)), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="5", callback_data="gen:5"), InlineKeyboardButton(text="7", callback_data="gen:7"), InlineKeyboardButton(text="10", callback_data="gen:10")]]))

@dp.callback_query(F.data.startswith("gen:"))
async def cb_gen(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    u = await db.get_user(uid)
    if not u['is_premium'] and u['balance'] <= 0: return await cb.answer(get_text(u['lang'], 'no_bal'), show_alert=True)
    
    count, topic = cb.data.split(":")[1], (await state.get_data()).get('topic')
    await cb.message.delete()
    wm = await cb.message.answer(get_text(u['lang'], 'wait'))
    
    try:
        # KUCHAYTIRILGAN PROMPT
        sys_p = """You are an Elite Presentation Designer & Researcher. 
        Create content that is HIGHLY ENGAGING, ORIGINAL, and FACT-BASED. Avoid generic fluff.
        Constraint 1: Keep bullet points SHORT (max 10-12 words) to fit the design.
        Constraint 2: Provide unique insights or rare facts for the 'insight' field.
        Structure: {"slides": [{"title": "Catchy Title", "content": ["Punchy Point 1", "Data-driven Point 2", "Clear Point 3"], "insight": "Did you know? [Interesting Fact]"}]}"""
        
        prompt = f"Topic: {topic}. Slides: {count}. Language: {u['lang']}. Tone: Professional & Inspiring."
        res = await client.chat.completions.create(messages=[{"role":"system","content":sys_p}, {"role":"user","content":prompt}], model="llama-3.3-70b-versatile", response_format={"type": "json_object"})
        
        path = await asyncio.to_thread(create_pptx, topic, res.choices[0].message.content, uid)
        if path:
            await bot.send_document(uid, FSInputFile(path), caption=get_text(u['lang'], 'done'))
            if not u['is_premium']: await db.update_balance(uid, -1)
            os.remove(path)
        else: raise Exception("File error")
    except Exception as e:
        logger.error(f"Gen err: {e}")
        await cb.message.answer(get_text(u['lang'], 'error'))
    finally: await wm.delete(); await state.clear()

# Quiz & To'lov handlers (o'zgarishsiz qoldi, chunki ular to'g'ri ishlayapti)
@dp.message(UserStates.waiting_quiz, F.document)
async def quiz_doc(msg: types.Message, state: FSMContext):
    u = await db.get_user(msg.from_user.id)
    wm = await msg.answer(get_text(u['lang'], 'wait'))
    path = f"temp_{msg.from_user.id}"
    await bot.download(msg.document, destination=path)
    try:
        ext = msg.document.file_name.split('.')[-1].lower()
        if ext == 'pdf': txt = "\n".join([p.extract_text() for p in pypdf.PdfReader(path).pages])
        elif ext == 'docx': txt = "\n".join([p.text for p in Document(path).paragraphs])
        else: txt = open(path, 'r', encoding='utf-8').read()
        res = await client.chat.completions.create(messages=[{"role":"user","content":f"Create 10 hard multiple choice questions from this text in {u['lang']}:\n{txt[:10000]}"}], model="llama-3.3-70b-versatile")
        if len(res.choices[0].message.content) > 4000:
             for x in range(0, len(res.choices[0].message.content), 4000): await msg.answer(res.choices[0].message.content[x:x+4000])
        else: await msg.answer(res.choices[0].message.content)
    except: await msg.answer("❌ Error")
    finally: 
        if os.path.exists(path): os.remove(path)
        await wm.delete(); await state.clear(); await main_menu(msg, u['lang'])

@dp.message(UserStates.choosing_pkg)
async def pkg_sel(msg: types.Message, state: FSMContext):
    u = await db.get_user(msg.from_user.id)
    p = get_text(u['lang'], 'package_btns')
    amt = 1 if msg.text == p[0] else 5 if msg.text == p[1] else 999
    await state.update_data(amt=amt, pkg=msg.text)
    await msg.answer(get_text(u['lang'], 'tarif').split('📸')[1])
    await state.set_state(UserStates.waiting_pay)

@dp.message(UserStates.waiting_pay, F.photo)
async def pay_photo(msg: types.Message, state: FSMContext):
    d = await state.get_data()
    pid = await db.add_payment(msg.from_user.id, d['amt'], d['pkg'], msg.photo[-1].file_id)
    if ADMIN_ID: await bot.send_photo(ADMIN_ID, msg.photo[-1].file_id, caption=f"Pay ID: {pid}\nUser: {msg.from_user.id}\nPkg: {d['pkg']}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅", callback_data=f"p_ok_{pid}"), InlineKeyboardButton(text="❌", callback_data=f"p_no_{pid}")]]))
    await msg.answer(get_text((await db.get_user(msg.from_user.id))['lang'], 'payment_sent'))
    await state.clear(); await main_menu(msg, (await db.get_user(msg.from_user.id))['lang'])

@dp.callback_query(F.data.startswith("p_"))
async def adm_p(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    act, pid = cb.data.split("_")[1], int(cb.data.split("_")[2])
    if act == "ok":
        uid = await db.approve_payment(pid)
        if uid: await bot.send_message(uid, "✅ Payment Approved!")
        await cb.message.edit_caption(caption="✅ Approved")
    else: await cb.message.edit_caption(caption="❌ Rejected")

# --- 6. SERVER ---
async def health(req): return web.Response(text="OK")
async def start_srv():
    app = web.Application(); app.router.add_get('/', health)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.getenv("PORT", 8080))).start()

async def main():
    await db.init()
    asyncio.create_task(start_srv())
    await dp.start_polling(bot)

if __name__ == "__main__": asyncio.run(main())
