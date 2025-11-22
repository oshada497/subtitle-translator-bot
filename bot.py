import os
import logging
import re
import sqlite3
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Database setup
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, api_key TEXT)''')
    conn.commit()
    conn.close()

def save_api_key(user_id, api_key):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO users (user_id, api_key) VALUES (?, ?)',
              (user_id, api_key))
    conn.commit()
    conn.close()

def get_api_key(user_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT api_key FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

# Parse SRT file
def parse_srt(content):
    pattern = r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\n((?:.+\n?)+?)(?=\n\d+\n|\Z)'
    matches = re.findall(pattern, content, re.MULTILINE)
    return matches

# Create SRT file
def create_srt(subtitles):
    srt_content = ""
    for index, timestamp, text in subtitles:
        srt_content += f"{index}\n{timestamp}\n{text}\n\n"
    return srt_content

# Translate text using Gemini
async def translate_with_gemini(text, api_key):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-pro')
        
        prompt = f"""Translate the following English subtitle text to Sinhala. 
        Keep the translation natural and conversational. 
        Only provide the translated text without any explanations.
        
        Text: {text}"""
        
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Translation error: {e}")
        return None

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    api_key = get_api_key(user_id)
    
    if api_key:
        await update.message.reply_text(
            "🎬 Welcome back! Your Gemini API key is already saved.\n\n"
            "Send me an English subtitle file (.srt) and I'll translate it to Sinhala!\n\n"
            "Commands:\n"
            "/start - Show this message\n"
            "/setapi - Change your API key\n"
            "/help - Get help"
        )
    else:
        await update.message.reply_text(
            "🎬 Welcome to Subtitle Translator Bot!\n\n"
            "To get started, I need your Gemini API key.\n\n"
            "📝 How to get your Gemini API key:\n"
            "1. Visit: https://makersuite.google.com/app/apikey\n"
            "2. Click 'Create API Key'\n"
            "3. Copy the key and send it here\n\n"
            "Send me your API key now:"
        )

async def setapi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Please send me your Gemini API key:\n\n"
        "Get it from: https://makersuite.google.com/app/apikey"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 How to use this bot:\n\n"
        "1️⃣ Set up your Gemini API key (first time only)\n"
        "2️⃣ Send me an English subtitle file (.srt)\n"
        "3️⃣ Wait for the translation (may take a minute)\n"
        "4️⃣ Download your Sinhala subtitle file\n\n"
        "Commands:\n"
        "/start - Start the bot\n"
        "/setapi - Update your API key\n"
        "/help - Show this help message"
    )

# Handle API key input
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    # Check if user is sending an API key
    api_key = get_api_key(user_id)
    if not api_key and text.startswith('AIza'):
        # Save API key
        save_api_key(user_id, text)
        await update.message.reply_text(
            "✅ API key saved successfully!\n\n"
            "Now send me an English subtitle file (.srt) to translate it to Sinhala."
        )
    elif not api_key:
        await update.message.reply_text(
            "⚠️ Please set up your Gemini API key first.\n"
            "Use /start to get instructions."
        )
    else:
        await update.message.reply_text(
            "Please send me a subtitle file (.srt) to translate."
        )

# Handle file upload
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    api_key = get_api_key(user_id)
    
    if not api_key:
        await update.message.reply_text(
            "⚠️ Please set up your Gemini API key first.\n"
            "Use /start to get instructions."
        )
        return
    
    document = update.message.document
    
    # Check if it's an SRT file
    if not document.file_name.endswith('.srt'):
        await update.message.reply_text(
            "⚠️ Please send a valid .srt subtitle file."
        )
        return
    
    await update.message.reply_text("⏳ Downloading subtitle file...")
    
    try:
        # Download file
        file = await context.bot.get_file(document.file_id)
        file_path = f"temp_{user_id}.srt"
        await file.download_to_drive(file_path)
        
        # Read and parse SRT
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        subtitles = parse_srt(content)
        
        if not subtitles:
            await update.message.reply_text("⚠️ Could not parse the subtitle file.")
            os.remove(file_path)
            return
        
        await update.message.reply_text(
            f"📝 Found {len(subtitles)} subtitles.\n"
            f"🔄 Starting translation... This may take a few minutes."
        )
        
        # Translate subtitles
        translated_subtitles = []
        for i, (index, timestamp, text) in enumerate(subtitles):
            if (i + 1) % 10 == 0:
                await update.message.reply_text(f"⏳ Translated {i + 1}/{len(subtitles)}...")
            
            translated_text = await translate_with_gemini(text.strip(), api_key)
            if translated_text:
                translated_subtitles.append((index, timestamp, translated_text))
            else:
                translated_subtitles.append((index, timestamp, text))  # Keep original if translation fails
        
        # Create translated SRT file
        translated_content = create_srt(translated_subtitles)
        output_file = f"translated_{user_id}.srt"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(translated_content)
        
        # Send translated file
        await update.message.reply_document(
            document=open(output_file, 'rb'),
            filename=f"sinhala_{document.file_name}",
            caption="✅ Translation complete! Here's your Sinhala subtitle file."
        )
        
        # Cleanup
        os.remove(file_path)
        os.remove(output_file)
        
    except Exception as e:
        logger.error(f"Error processing file: {e}")
        await update.message.reply_text(
            f"❌ An error occurred while processing your file.\n"
            f"Please try again or check your API key."
        )
        if os.path.exists(f"temp_{user_id}.srt"):
            os.remove(f"temp_{user_id}.srt")
        if os.path.exists(f"translated_{user_id}.srt"):
            os.remove(f"translated_{user_id}.srt")

def main():
    # Initialize database
    init_db()
    
    # Get bot token from environment variable
    TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
    
    if not TOKEN:
        logger.error("No TELEGRAM_BOT_TOKEN found!")
        return
    
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setapi", setapi))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    # Start bot
    logger.info("Bot started!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
