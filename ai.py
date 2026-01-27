import os
import re
import json
import sys
import time
import asyncio
import logging
import aiosqlite
from datetime import datetime

# Asosiy kutubxonalar
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

# Fayllar va PPTX
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
import pypdf
from docx import Document

# --- 1. SOZLAMALAR ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

API_TOKEN = os.getenv('BOT_TOKEN')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
ADMIN_ID = os.getenv('ADMIN_ID', '0')
CHANNEL_ID = os.getenv('CHANNEL_ID', "@abdujalils")
PORT = int(os.getenv("PORT", 8080))

if not API_TOKEN or not GROQ_API_KEY:
    logger.critical("❌ Tokenlar topilmadi! .env faylni tekshiring.")
    sys.exit(1)

try:
    ADMIN_ID = int(ADMIN_ID)
except ValueError:
    ADMIN_ID = 0

client = AsyncGroq(api_key=GROQ_API_KEY)
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
DB_PATH = 'slide_master.db'

# --- 2. DATABASE (Optimallashtirilgan) ---
class Database:
    def __init__(self, path):
        self.path = path

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("CREATE TABLE IF NOT EXISTS users (id BIGINT PRIMARY KEY, username TEXT, lang TEXT DEFAULT 'uz', is_premium INTEGER DEFAULT 0, balance INTEGER DEFAULT 2, invited_by BIGINT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            await db.execute("CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id BIGINT, amount INTEGER, package_type TEXT, screenshot_id TEXT, status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            await db.commit()

    async def get_user(self, uid):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM users WHERE id = ?", (uid,))
            return await cursor.fetchone()

    async def add_user(self, uid, username, ref=None):
        async with aiosqlite.connect(self.path) as db:
            try:
                await db.execute("INSERT INTO users (id, username, invited_by) VALUES (?, ?, ?)", (uid, username, ref))
                if ref:
                    await db.execute("UPDATE users SET balance = balance + 1 WHERE id = ?", (ref,))
                await db.commit()
                return True
            except Exception as e:
                return False

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

# --- 3. MULTILINGUAL CONTENT ---
LANGS = {
    'uz': {
        'welcome': "🚀 <b>Slide Master AI</b>\n\nSlaydlar va Quizlar yaratuvchi eng kuchli bot!\n\nMenyudan tanlang:",
        'btns': ["💎 Tariflar", "📊 Kabinet", "🤝 Taklif", "❓ Quiz Test", "🌐 Til"],
        'sub_err': "🔒 <b>Kanalga a'zo bo'ling:</b>",
        'wait': "🎨 <b>Dizayn chizilmoqda...</b>\n<i>AI ma'lumotlarni tahlil qilib, professional slayd tayyorlamoqda.</i>",
        'done': "✅ <b>Tayyor!</b>",
        'no_bal': "⚠️ Balans yetarli emas.",
        'tarif': "💎 <b>TARIFLAR:</b>\n\n🔹 1 Slayd: 990 so'm\n🔹 5 Slayd: 2,999 so'm\n👑 VIP: 5,999 so'm\n\n💳 Karta: <code>9860230107924485</code>",
        'pay_sent': "✅ Chek yuborildi. Kuting.",
        'quiz_wait': "⏳ <b>Fayl o'qilmoqda...</b>",
        'error': "❌ Xatolik."
    },
    'ru': {
        'welcome': "🚀 <b>Slide Master AI</b>\n\nЛучший бот для слайдов и тестов!\n\nВыберите из меню:",
        'btns': ["💎 Тарифы", "📊 Кабинет", "🤝 Инфо", "❓ Quiz Test", "🌐 Язык"],
        'sub_err': "🔒 <b>Подпишитесь на канал:</b>",
        'wait': "🎨 <b>Создаем дизайн...</b>\n<i>AI анализирует данные и рисует слайды.</i>",
        'done': "✅ <b>Готово!</b>",
        'no_bal': "⚠️ Недостаточно баланса.",
        'tarif': "💎 <b>ТАРИФЫ:</b>\n\n🔹 1 Слайд: 990 сум\n🔹 5 Слайдов: 2,999 сум\n👑 VIP: 5,999 сум",
        'pay_sent': "✅ Чек отправлен.",
        'quiz_wait': "⏳ <b>Читаем файл...</b>",
        'error': "❌ Ошибка."
    },
    'en': {
        'welcome': "🚀 <b>Slide Master AI</b>\n\nBest bot for Slides & Quizzes!\n\nSelect from menu:",
        'btns': ["💎 Pricing", "📊 Profile", "🤝 Invite", "❓ Quiz Test", "🌐 Language"],
        'sub_err': "🔒 <b>Subscribe to channel:</b>",
        'wait': "🎨 <b>Designing...</b>\n<i>AI is creating professional slides.</i>",
        'done': "✅ <b>Done!</b>",
        'no_bal': "⚠️ Insufficient balance.",
        'tarif': "💎 <b>PRICING:</b>\n\n🔹 1 Slide: 990 UZS\n🔹 5 Slides: 2,999 UZS\n👑 VIP: 5,999 UZS",
        'pay_sent': "✅ Receipt sent.",
        'quiz_wait': "⏳ <b>Reading file...</b>",
        'error': "❌ Error."
    }
}
def get_text(l, k): return LANGS.get(l, LANGS['uz']).get(k, "Text")

# --- 4. ENGINE (PPTX GENERATION) ---
def clean_json(text):
    text = re.sub(r'```json\s*', '', text); text = re.sub(r'```', '', text)
    s, e = text.find('{'), text.rfind('}') + 1
    return text[s:e] if s!=-1 and e!=-1 else text

def get_font_size(text_len):
    if text_len < 50: return 24
    elif text_len < 120: return 20
    elif text_len < 250: return 16
    else: return 14

def create_pptx(topic, json_data, uid):
    try:
        data = json.loads(clean_json(json_data))
        prs = Presentation()
        prs.slide_width, prs.slide_height = Inches(13.33), Inches(7.5)

        for i, s_data in enumerate(data.get('slides', [])):
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            
            # 1. ORQA FON
            bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
            bg.fill.solid()
            bg.fill.fore_color.rgb = RGBColor(10, 25, 47) # Dark Navy
            bg.line.fill.background()

            # 2. SARLAVHA
            tb = slide.shapes.add_textbox(Inches(0.5), Inches(0.4), Inches(12), Inches(1))
            tp = tb.text_frame.paragraphs[0]
            tp.text = s_data.get('title', topic).upper()
            tp.font.bold = True; tp.font.size = Pt(36); tp.font.color.rgb = RGBColor(0, 255, 255)
            tp.font.name = "Arial Black"

            # 3. KONTENT
            content_list = s_data.get('content', [])
            total_chars = sum(len(str(x)) for x in content_list)
            if len(content_list) > 6: content_list = content_list[:6]

            card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.5), Inches(1.6), Inches(8.5), Inches(5.2))
            card.fill.solid(); card.fill.fore_color.rgb = RGBColor(23, 42, 69)
            card.fill.transparency = 0.2
            card.line.color.rgb = RGBColor(100, 255, 218)
            card.line.width = Pt(1.5)

            tf = card.text_frame; tf.word_wrap = True; tf.margin_top = Inches(0.2)
            
            for point in content_list:
                p = tf.add_paragraph()
                p.text = f"• {point}"
                p.font.color.rgb = RGBColor(230, 241, 255)
                p.space_after = Pt(12)
                p.font.size = Pt(get_font_size(total_chars // max(1, len(content_list))))

            # 4. STATISTIKA
            if s_data.get('insight') or s_data.get('stat'):
                info_box = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(9.2), Inches(1.6), Inches(3.8), Inches(3))
                info_box.fill.solid(); info_box.fill.fore_color.rgb = RGBColor(255, 255, 255)
                info_box.fill.transparency = 0.9
                info_box.line.color.rgb = RGBColor(255, 165, 0)
                
                itf = info_box.text_frame; itf.word_wrap = True
                ip = itf.paragraphs[0]
                ip.text = "💡 MUHIM FAKT"
                ip.font.bold = True; ip.font.size = Pt(14); ip.font.color.rgb = RGBColor(255, 165, 0)
                ip.alignment = PP_ALIGN.CENTER
                
                txt = s_data.get('insight', s_data.get('stat', ''))
                ip2 = itf.add_paragraph()
                ip2.text = txt
                ip2.font.size = Pt(14); ip2.font.color.rgb = RGBColor(255, 255, 255)
                ip2.space_before = Pt(10)

            # Footer
            fb = slide.shapes.add_textbox(Inches(0.5), Inches(7), Inches(5), Inches(0.5))
            fp = fb.text_frame.paragraphs[0]
            fp.text = f"Slide Master AI | {datetime.now().year}"
            fp.font.size = Pt(10); fp.font.color.rgb = RGBColor(136, 146, 176)

        path = f"slides/Pro_{uid}_{int(time.time())}.pptx"
        os.makedirs("slides", exist_ok=True)
        prs.save(path)
        return path
    except Exception as e:
        logger.error(f"PPTX Gen Error: {e}")
        return None

# --- 5. STATE & HANDLERS ---
class States(StatesGroup):
    pkg = State()
    pay = State()
    quiz = State()

async def check_sub(uid):
    if not CHANNEL_ID or CHANNEL_ID == "@abdujalils": return True
    try:
        m = await bot.get_chat_member(CHANNEL_ID, uid)
        return m.status in ['member', 'administrator', 'creator']
    except: return True

async def menu(msg, l):
    b = get_text(l, 'btns')
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=b[0]), KeyboardButton(text=b[1])], [KeyboardButton(text=b[2]), KeyboardButton(text=b[3])], [KeyboardButton(text=b[4])]], resize_keyboard=True)
    await msg.answer(get_text(l, 'welcome'), reply_markup=kb)

# !!! MUHIM TUZATISH SHU YERDA !!!
@dp.message(Command("start"))
async def start(msg: types.Message, command: CommandObject): # <-- 'cmd' emas, 'command' bo'lishi shart
    uid = msg.from_user.id
    # command.args - foydalanuvchi /start 123 deb yozganda "123" ni oladi
    ref = int(command.args) if command.args and command.args.isdigit() and int(command.args)!=uid else None
    
    await db.add_user(uid, msg.from_user.username, ref)
    u = await db.get_user(uid)
    
    if not await check_sub(uid):
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📢 Kanal", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}")], [InlineKeyboardButton(text="✅ Check", callback_data="check")]])
        return await msg.answer(get_text(u['lang'], 'sub_err'), reply_markup=kb)
    await menu(msg, u['lang'])

@dp.callback_query(F.data == "check")
async def cb_chk(cb: CallbackQuery):
    if await check_sub(cb.from_user.id):
        await cb.message.delete()
        u = await db.get_user(cb.from_user.id)
        await menu(cb.message, u['lang'])
    else: await cb.answer("❌ No!", show_alert=True)

@dp.message(F.text)
async def main_h(msg: types.Message, state: FSMContext):
    uid = msg.from_user.id
    u = await db.get_user(uid)
    if not u: await db.add_user(uid, msg.from_user.username); u = await db.get_user(uid)
    l, t = u['lang'], msg.text

    if t in [LANGS[k]['btns'][4] for k in LANGS]: # Lang
        await msg.answer("Til:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="UZ", callback_data="set_uz"), InlineKeyboardButton(text="RU", callback_data="set_ru"), InlineKeyboardButton(text="EN", callback_data="set_en")]]))
    elif t in [LANGS[k]['btns'][0] for k in LANGS]: # Tarif
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="1"), KeyboardButton(text="5"), KeyboardButton(text="VIP")]], resize_keyboard=True)
        await msg.answer(get_text(l, 'tarif'), reply_markup=kb)
        await state.set_state(States.pkg)
    elif t in [LANGS[k]['btns'][1] for k in LANGS]: # Kabinet
        await msg.answer(f"🆔 {uid}\n💰 Bal: {u['balance']}\n👑 VIP: {'✅' if u['is_premium'] else '❌'}")
    elif t in [LANGS[k]['btns'][2] for k in LANGS]: # Invite
        await msg.answer(f"🔗 https://t.me/{(await bot.get_me()).username}?start={uid}")
    elif t in [LANGS[k]['btns'][3] for k in LANGS]: # Quiz
        await msg.answer("📂 PDF/DOCX:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙")]], resize_keyboard=True))
        await state.set_state(States.quiz)
    elif t == "🔙": await state.clear(); await menu(msg, l)
    else: # Generate Slide
        if not u['is_premium'] and u['balance'] <= 0: return await msg.answer(get_text(l, 'no_bal'))
        await state.update_data(topic=t)
        
        # --- O'ZGARTIRILGAN QISM SHU YERDA ---
        # 10, 15, 20 tugmalari qo'yildi
        buttons = [
            [
                InlineKeyboardButton(text="10", callback_data="g:10"), 
                InlineKeyboardButton(text="15", callback_data="g:15"), 
                InlineKeyboardButton(text="20", callback_data="g:20")
            ]
        ]
        await msg.answer(f"📄 {t}\nSlayd soni:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
@dp.callback_query(F.data.startswith("set_"))
async def set_l(cb: CallbackQuery):
    await db.set_lang(cb.from_user.id, cb.data.split("_")[1])
    await cb.message.delete(); await menu(cb.message, cb.data.split("_")[1])

@dp.callback_query(F.data.startswith("g:"))
async def gen_slide(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    u = await db.get_user(uid)
    if not u['is_premium'] and u['balance'] <= 0: return await cb.answer(get_text(u['lang'], 'no_bal'), show_alert=True)
    
    cnt = cb.data.split(":")[1]
    topic = (await state.get_data()).get('topic')
    await cb.message.delete()
    w = await cb.message.answer(get_text(u['lang'], 'wait'))
    
    try:
        sys_prompt = "You are a Professional Presentation Designer. Content must be ORIGINAL, FACTUAL and ENGAGING. Return JSON only: {'slides': [{'title': '...', 'content': ['Point 1', 'Point 2'], 'insight': 'Fun Fact'}]}"
        pmt = f"Topic: {topic}. Slides: {cnt}. Lang: {u['lang']}. Keep text concise for slides."
        res = await client.chat.completions.create(messages=[{"role":"system","content":sys_prompt},{"role":"user","content":pmt}], model="llama-3.3-70b-versatile", response_format={"type":"json_object"})
        
        path = await asyncio.to_thread(create_pptx, topic, res.choices[0].message.content, uid)
        if path:
            await bot.send_document(uid, FSInputFile(path), caption=get_text(u['lang'], 'done'))
            if not u['is_premium']: await db.update_balance(uid, -1)
            os.remove(path)
    except Exception as e:
        logger.error(f"Gen Err: {e}")
        await cb.message.answer(get_text(u['lang'], 'error'))
    finally: await w.delete(); await state.clear()

@dp.message(States.pkg)
async def pkg_h(msg: types.Message, state: FSMContext):
    if msg.text == "🔙": await state.clear(); return await menu(msg, 'uz')
    amt = 1 if msg.text=="1" else 5 if msg.text=="5" else 999
    pkg = "vip_premium" if amt==999 else "slides"
    await state.update_data(amt=amt, pkg=pkg)
    await msg.answer("📸 Chek rasmini yuboring:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙")]], resize_keyboard=True))
    await state.set_state(States.pay)

@dp.message(States.pay, F.photo)
async def pay_h(msg: types.Message, state: FSMContext):
    d = await state.get_data()
    pid = await db.add_payment(msg.from_user.id, d['amt'], d['pkg'], msg.photo[-1].file_id)
    if ADMIN_ID:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅", callback_data=f"y_{pid}"), InlineKeyboardButton(text="❌", callback_data=f"n_{pid}")]])
        await bot.send_photo(ADMIN_ID, msg.photo[-1].file_id, caption=f"New Pay!\nID: {pid}\nUser: {msg.from_user.id}\nPkg: {d['pkg']}", reply_markup=kb)
    await msg.answer(get_text((await db.get_user(msg.from_user.id))['lang'], 'pay_sent'))
    await state.clear(); await menu(msg, (await db.get_user(msg.from_user.id))['lang'])

@dp.callback_query(F.data.startswith("y_"))
async def adm_y(cb: CallbackQuery):
    pid = int(cb.data.split("_")[1])
    uid = await db.approve_payment(pid)
    if uid:
        await cb.message.edit_caption(caption="✅ Approved")
        try: await bot.send_message(uid, "✅ To'lov tasdiqlandi!")
        except: pass

@dp.message(States.quiz, F.document)
async def quiz_h(msg: types.Message, state: FSMContext):
    u = await db.get_user(msg.from_user.id)
    w = await msg.answer(get_text(u['lang'], 'quiz_wait'))
    p = f"temp_{msg.from_user.id}"
    await bot.download(msg.document, destination=p)
    try:
        txt = ""
        if p.endswith('.pdf'): txt = "\n".join([x.extract_text() for x in pypdf.PdfReader(p).pages])
        elif p.endswith('.docx'): txt = "\n".join([x.text for x in Document(p).paragraphs])
        else: txt = open(p, 'r').read()
        
        res = await client.chat.completions.create(messages=[{"role":"user","content":f"Create 10 hard multiple choice questions in {u['lang']} from: {txt[:10000]}"}], model="llama-3.3-70b-versatile")
        ans = res.choices[0].message.content
        if len(ans) > 4000:
            with open("quiz.txt", "w") as f: f.write(ans)
            await bot.send_document(msg.chat.id, FSInputFile("quiz.txt"))
            os.remove("quiz.txt")
        else: await msg.answer(ans)
    except: await msg.answer("Error")
    finally: 
        if os.path.exists(p): os.remove(p)
        await w.delete(); await state.clear(); await menu(msg, u['lang'])

# --- 6. SERVER & RUN ---
async def health(r): return web.Response(text="OK")

async def start_server():
    app = web.Application()
    app.router.add_get('/', health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    logger.info(f"Web server started on port {PORT}")

async def main():
    await db.init()
    # Render uchun web serverni fonda ishga tushiramiz
    asyncio.create_task(start_server()) 
    
    # Pollingni ishga tushiramiz (Allowed updates ni cheklash tavsiya etiladi)
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped!")
