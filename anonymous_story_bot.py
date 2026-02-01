import os
import sqlite3
import logging
import threading
from flask import Flask
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters
)

# Load .env file if it exists
load_dotenv()

# ================= CONFIG =================
# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load configuration from environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN", "8224578091:AAHkvhZ9DeFl4S_rRUHthfLOBJZRz7yKPAY")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "6904958031").split(",") if x.strip()]
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1002116750920"))
PORT = int(os.getenv("PORT", "8080")) # Railway/UptimeRobot port
# ==========================================

# ================= KEEP-ALIVE SERVER (FLASK) =================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Bot is alive! 🕊️"

def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT)

# ================= DATABASE =================
def init_db():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    # Stores approved stories
    cursor.execute('''CREATE TABLE IF NOT EXISTS stories 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, channel_msg_id INTEGER)''')
    # Stores stories awaiting approval
    cursor.execute('''CREATE TABLE IF NOT EXISTS pending_stories 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, user_id INTEGER)''')
    # Stores advice awaiting approval
    cursor.execute('''CREATE TABLE IF NOT EXISTS pending_advice 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, story_id INTEGER, text TEXT, user_id INTEGER)''')
    conn.commit()
    conn.close()

def db_query(query, params=(), fetchone=False, fetchall=False, commit=False):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute(query, params)
    result = None
    if fetchone:
        result = cursor.fetchone()
    elif fetchall:
        result = cursor.fetchall()
    
    # Return lastrowid if it was a commit (INSERT/UPDATE)
    if commit:
        conn.commit()
        result = cursor.lastrowid
        
    conn.close()
    return result

# =================== COMMANDS ===================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🕊️ እንኳን ደህና መጡ!\n\n"
        "• ለምስጢራዊ ታሪክ በቀጥታ ጽፈው ይላኩ።\n"
        "• ለአስተያየት ከታሪክ ጋር /advice <story_id> ይጻፉ።\n"
        "ስምዎ አይታይም።"
    )

# =================== MESSAGE HANDLING ===================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()

    # Check if user is in "advice submission mode"
    if context.user_data.get('state') == 'awaiting_advice':
        await receive_advice(update, context)
    else:
        # Otherwise, treat it as a new story
        await receive_story(update, context)

async def receive_story(update: Update, context: ContextTypes.DEFAULT_TYPE):
    story_text = update.message.text.strip()
    user_id = update.message.from_user.id

    # Insert into pending stories and get the ID
    story_id = db_query("INSERT INTO pending_stories (text, user_id) VALUES (?, ?)", 
                        (story_text, user_id), commit=True)

    keyboard = [
        [
            InlineKeyboardButton("✅ Approve Story", callback_data=f"app_s_{story_id}"),
            InlineKeyboardButton("❌ Reject Story", callback_data=f"rej_s_{story_id}")
        ]
    ]

    for admin in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin,
                text=f"📝 New Anonymous Story (ID {story_id}):\n\n{story_text}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Failed to send to admin {admin}: {e}")

    await update.message.reply_text("🙏 እናመሰግናለን። ")

async def advice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("❌ እባክዎ ትክክለኛ story ID ይጻፉ: /advice <story_id>")
        return

    story_id = int(args[0])
    # Check if story exists in approved stories
    story = db_query("SELECT id FROM stories WHERE id = ?", (story_id,), fetchone=True)
    if not story:
        await update.message.reply_text("❌ Story ID አልተገኘም ወይም ገና አልጸደቀም።")
        return

    context.user_data['advice_story_id'] = story_id
    context.user_data['state'] = 'awaiting_advice'
    await update.message.reply_text(f"✍️ እባክዎ ለ Story #{story_id} አስተያየትዎን ይላኩ።")

async def receive_advice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    story_id = context.user_data.get('advice_story_id')
    advice_text = update.message.text.strip()
    user_id = update.message.from_user.id

    if not story_id:
        await update.message.reply_text("❌ ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ።")
        context.user_data.clear()
        return

    # Insert into pending advice and get the ID
    advice_id = db_query("INSERT INTO pending_advice (story_id, text, user_id) VALUES (?, ?, ?)", 
                         (story_id, advice_text, user_id), commit=True)

    keyboard = [
        [
            InlineKeyboardButton("✅ Approve Advice", callback_data=f"app_a_{advice_id}"),
            InlineKeyboardButton("❌ Reject Advice", callback_data=f"rej_a_{advice_id}")
        ]
    ]

    for admin in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin,
                text=f"💬 New Advice for Story #{story_id}:\n\n{advice_text}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Failed to send to admin {admin}: {e}")

    await update.message.reply_text("🙏 ሰለ ሰጡት ምክር እናመሰግናልን")
    context.user_data.clear()

# =================== CALLBACK HANDLER ===================

async def handle_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # STORY APPROVAL
    if data.startswith("app_s_") or data.startswith("rej_s_"):
        story_id = int(data.split("_")[-1])
        row = db_query("SELECT text FROM pending_stories WHERE id = ?", (story_id,), fetchone=True)
        
        if not row:
            await query.edit_message_text("⚠️ Story not found in pending.")
            return

        story_text = row[0]

        if data.startswith("app_s_"):
            try:
                msg = await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=f"🕊️ ምስጢራዊ ታሪክ (ID {story_id}):\n\n{story_text}\n\n💬 አስተያየት ለማስገባት /advice {story_id} ይጻፉ።"
                )
                db_query("INSERT INTO stories (id, text, channel_msg_id) VALUES (?, ?, ?)", 
                         (story_id, story_text, msg.message_id), commit=True)
                await query.edit_message_text(f"✅ Story #{story_id} approved and posted.")
            except Exception as e:
                logger.error(f"Failed to post story to channel: {e}")
                await query.edit_message_text(f"❌ Error: Could not post to channel. Is the bot an admin in {CHANNEL_ID}?")
        else:
            await query.edit_message_text(f"❌ Story #{story_id} rejected.")
        
        db_query("DELETE FROM pending_stories WHERE id = ?", (story_id,), commit=True)

    # ADVICE APPROVAL
    elif data.startswith("app_a_") or data.startswith("rej_a_"):
        advice_id = int(data.split("_")[-1])
        row = db_query("SELECT story_id, text FROM pending_advice WHERE id = ?", (advice_id,), fetchone=True)

        if not row:
            await query.edit_message_text("⚠️ Advice not found in pending.")
            return

        story_id, advice_text = row
        
        if data.startswith("app_a_"):
            try:
                await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=f"💬 Anonymous Advice (Story #{story_id}):\n\n{advice_text}"
                )
                await query.edit_message_text(f"✅ Advice for Story #{story_id} approved.")
            except Exception as e:
                logger.error(f"Failed to post advice to channel: {e}")
                await query.edit_message_text(f"❌ Error: Could not post advice to channel.")
        else:
            await query.edit_message_text(f"❌ Advice for Story #{story_id} rejected.")

        db_query("DELETE FROM pending_advice WHERE id = ?", (advice_id,), commit=True)

# =================== MAIN ===================

def main():
    # Initialize DB
    init_db()

    # Start Flask keep-alive server in a background thread
    threading.Thread(target=run_flask, daemon=True).start()
    logger.info(f"Flask keep-alive server started on port {PORT}")

    # Build Telegram bot
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("advice", advice_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_review))

    # Always use polling for Railway (requested)
    logger.info("Bot started with polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
