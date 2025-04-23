import os
import logging
import base64
import markdown2
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from bs4 import BeautifulSoup
from langchain.globals import set_llm_cache
from langchain_community.cache import SQLiteCache

"""
This bot listens for replies to meme images and uses OpenAI's GPT-4 Vision model to explain the meme.

Required environment variables:

- TELEGRAM_BOT_TOKEN: Your Telegram bot token.
- OPENAI_API_KEY: Your OpenAI API key.

Optinal environment variables:

- BOT_AUTHORIZED_GROUPS: Comma-separated list of group IDs where the bot is allowed to operate. If not set, the bot is allowed in all groups.
"""

# 
# Configurable options
#
DEBUG_ALL_MESSAGES = False  # Set to True to log all messages for debugging
ENABLE_LLM_CACHE = True  # Set to False to disable LangChain LLM caching

token = os.getenv('TELEGRAM_BOT_TOKEN')
if not token:
    raise ValueError("Please set the TELEGRAM_BOT_TOKEN environment variable.")

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("meme-explainer-bot")

# Create the Telegram application (async)
telegram_app = Application.builder().token(token).build()

# --- LangChain/OpenAI setup ---
openai_api_key = os.getenv('OPENAI_API_KEY')
if not openai_api_key:
    raise ValueError("Please set the OPENAI_API_KEY environment variable.")

llm = ChatOpenAI(model="gpt-4.1", api_key=openai_api_key)

if ENABLE_LLM_CACHE:
    set_llm_cache(SQLiteCache(database_path=".langchain.db"))
    logger.info("LangChain LLM cache enabled (SQLiteCache at .langchain.db)")
else:
    logger.info("LangChain LLM cache disabled")

# Prompt template for meme explanation (tune as needed)
prompt_template = ChatPromptTemplate.from_messages([
    (
        "human",
        """
        You are a meme explainer bot. Given an image, extract the text, detect the language, and provide a concise explanation of the meme's meaning.
        You must always respond in the same language as the meme text as much as possible as long as the langauge is either 
        English or Spanish. If it is not one of those languages, respond in English.
        If the image contains no text, then just describe at the image and try to explain the meme.
        Your responses must only contain the explanation and nothing else, no need to specify the language or extracted text.
        """
    )
])

# --- Authorized groups setup ---
def parse_authorized_groups(env_value):
    if not env_value:
        return None  # None means allow all
    try:
        return set(int(x.strip()) for x in env_value.split(",") if x.strip())
    except Exception as e:
        logger.error(f"Error parsing BOT_AUTHORIZED_GROUPS: {e}")
        return None

BOT_AUTHORIZED_GROUPS = parse_authorized_groups(os.getenv("BOT_AUTHORIZED_GROUPS", ""))
if BOT_AUTHORIZED_GROUPS is not None:
    logger.info(f"Bot restricted to authorized group IDs: {BOT_AUTHORIZED_GROUPS}")
else:
    logger.info("Bot allowed in all groups (no restriction set)")

def clean_telegram_html(html: str) -> str:
    """
    Remove unsupported HTML tags for Telegram and keep only allowed ones.
    Telegram supports: b, strong, i, em, u, ins, s, strike, del, span, a, code, pre
    """
    allowed_tags = {'b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del', 'span', 'a', 'code', 'pre'}
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(True):
        if tag.name not in allowed_tags:
            tag.unwrap()
    return str(soup)

async def explain_meme(image_bytes: bytes) -> str:
    logger.info("Calling OpenAI to explain meme image (%d bytes)", len(image_bytes))
    prompt = prompt_template.format_messages()
    try:
        # Proper base64 encoding for image
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
        image_url = f"data:image/jpeg;base64,{image_b64}"
        # Log the request payload to LLM
        logger.info("LLM Request: prompt=%r, image_url=[base64 omitted, %d bytes]", prompt[0].content, len(image_b64))
        response = await llm.ainvoke([
            HumanMessage(
                content=[
                    {"type": "text", "text": prompt[0].content},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            )
        ])
        logger.info("Received response from OpenAI")
        # Log the raw LLM response
        logger.info("LLM Response: %r", response.content if hasattr(response, 'content') else str(response))
        # Convert Markdown to HTML for Telegram
        html_response = markdown2.markdown(response.content if hasattr(response, 'content') else str(response))
        html_response = clean_telegram_html(html_response)
        return html_response
    except Exception as e:
        logger.error(f"Error calling OpenAI: {e}")
        raise

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Received /start command from user_id=%s", update.effective_user.id)
    await update.message.reply_text('Hello! I explain memes. Mention me in a reply to a meme image!')

async def groupid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await update.message.reply_text(f"This group's chat ID is: <code>{chat.id}</code>", parse_mode="HTML")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    chat_id = message.chat_id
    logger.info("Received message in chat_id=%s from user_id=%s", chat_id, message.from_user.id)
    # Restrict to authorized groups if set
    if BOT_AUTHORIZED_GROUPS is not None and chat_id not in BOT_AUTHORIZED_GROUPS:
        logger.warning(f"Received message from unauthorized group chat_id={chat_id}. Ignoring.")
        return
    if message.reply_to_message and message.reply_to_message.photo:
        logger.info("Message is a reply to a photo. Checking for bot mention...")
        if any(entity.type == 'mention' and message.text[entity.offset:entity.offset+entity.length] == f"@{context.bot.username}" for entity in (message.entities or [])):
            logger.info("Bot was mentioned in reply. Downloading image...")
            photo = message.reply_to_message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            image_bytes = await file.download_as_bytearray()
            try:
                explanation_html = await explain_meme(image_bytes)
            except Exception as e:
                explanation_html = f"Error processing meme: {e}"
                logger.error(explanation_html)
            await message.reply_text(explanation_html, parse_mode="HTML")
            logger.info("Sent explanation back to chat_id=%s", message.chat_id)
        else:
            logger.info("Bot was not mentioned in the reply. Ignoring message.")
    else:
        logger.info("Message is not a reply to a photo. Ignoring message.")

# Debug handler for logging all messages. Can be used for troubleshooting prup
async def debug_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    logger.info("[DEBUG] Received message: %s", message)

# --- Register handlers ---
telegram_app.add_handler(CommandHandler('start', start))
telegram_app.add_handler(CommandHandler('groupid', groupid))
telegram_app.add_handler(MessageHandler(filters.TEXT & filters.REPLY, handle_message))
if DEBUG_ALL_MESSAGES:
    logger.info("Debugging all messages enabled.")
    telegram_app.add_handler(MessageHandler(filters.ALL, debug_handler))

if __name__ == '__main__':
    telegram_app.run_polling()