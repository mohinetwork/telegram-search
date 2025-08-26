import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler
import requests
import asyncio
import base64
import secrets
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

# ============= RENDER CONFIGURATION =============
BOT_TOKEN = os.getenv('BOT_TOKEN')
PAYMENT_API_KEY = os.getenv('PAYMENT_API_KEY')
CREATE_ORDER_URL = os.getenv('CREATE_ORDER_URL')
STATUS_CHECK_URL = os.getenv('STATUS_CHECK_URL')
SEARCH_API_URL = os.getenv('SEARCH_API_URL', 'https://api.example.com/search')

# Render port configuration
PORT = int(os.getenv('PORT', 10000))

# Admin IDs from environment
ADMIN_IDS = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]
SEARCH_COST = float(os.getenv('SEARCH_COST', '5'))

# Validate required environment variables
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global storage
user_wallets = {}
premium_users = set()
user_search_count = {}
user_settings = {}
pending_payments = {}

# Conversation states
(AMOUNT, BROADCAST_MESSAGE, ADMIN_ADD_FUNDS, SET_GLOBAL_PRICE, 
 SET_USER_PRICE, REMOVE_PREMIUM, MAKE_PREMIUM) = range(7)

# ============= SEARCH FUNCTION =============
async def search_mobile(mobile):
    """Search mobile number using API"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Content-Type': 'application/json'
        }
        
        payload = {'mobile': mobile}
        if PAYMENT_API_KEY:
            payload['api_key'] = PAYMENT_API_KEY
            
        response = requests.post(
            SEARCH_API_URL,
            json=payload,
            headers=headers,
            timeout=15
        )
        
        logger.info(f"Search API Response: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success') or result.get('status'):
                return {
                    "success": True,
                    "results": result.get('data', result.get('results', []))
                }
            else:
                return {
                    "success": False,
                    "error": result.get('message', 'No data found')
                }
        else:
            return {
                "success": False,
                "error": f"API Error: {response.status_code}"
            }
            
    except Exception as e:
        logger.error(f"Search error: {e}")
        return {"success": False, "error": "Search failed. Please try again."}

def format_result(data):
    """Format search results - from your original code"""
    if not data.get("success") or not data.get("results"):
        return "❌ No results found."

    results = []
    results_data = data.get("results", [])
    
    if isinstance(results_data, dict):
        results_data = [results_data]
    
    for r in results_data[:5]:
        result_text = "🔍 **Search Result**\n\n"
        
        # Build address - from your original logic
        address_parts = []
        if r.get('address') and r.get('address').strip():
            address_parts.append(r.get('address').strip())
        if r.get('state') and r.get('state').strip():
            address_parts.append(r.get('state').strip())
        if r.get('city') and r.get('city').strip():
            address_parts.append(r.get('city').strip())
            
        address = ", ".join(address_parts) if address_parts else None

        # Format result text - exactly from your original
        if r.get('mobile'):
            result_text += f"📱 `{r.get('mobile')}`\n"

        if r.get('name'):
            result_text += f"🪪 `{r.get('name').strip()}`\n"

        if r.get('fname'):
            result_text += f"👨‍👦 `{r.get('fname')}`\n"

        if address:
            result_text += f"🏠 `{address}`\n"

        if r.get('alt') and r.get('alt') != 'N/A':
            result_text += f"☎️ `{r.get('alt')}`\n"

        if r.get('email') and r.get('email') != 'N/A':
            result_text += f"✉️ `{r.get('email')}`\n"

        if r.get('id'):
            result_text += f"🆔 `{r.get('id')}`\n"

        if r.get('circle'):
            result_text += f"🌐 `{r.get('circle')}`"

        results.append(result_text.strip())

    return "\n\n".join(results)

# ============= PAYMENT FUNCTIONS - Your Original Code =============
async def create_payment_order(user_id, amount, update: Update):
    # Generate unique order ID
    order_id = f"order_{secrets.token_hex(12)}"

    # Get user details
    user = update.effective_user
    user_details = {
        'name': user.first_name or "User",
        'mobile': '0000000000',
        'email': f"{user.id}@telegram.user"
    }

    # Create payment order with proper headers
    payment_data = {
        'api_key': PAYMENT_API_KEY,
        'txn_amount': str(amount),
        'redirectUrl': f'https://t.me/{(await update.get_bot().get_me()).username}',
        'order_id': order_id,
        'txn_note': 'Wallet Top-up',
        'txn_note2': f'User: {user_id}',
        'txn_note3': 'Telegram Bot Payment',
        'txn_note4': '',
        'customer_name': user_details['name'],
        'customer_mobile': user_details['mobile'],
        'customer_email': user_details['email']
    }

    try:
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        response = requests.post(
            CREATE_ORDER_URL,
            json=payment_data,
            headers=headers,
            timeout=15
        )

        logger.info(f"Payment API Response: {response.status_code}, {response.text}")

        if response.status_code != 200:
            return None, f"Payment gateway error: {response.status_code}"

        result = response.json()
        if not result.get('status'):
            error_msg = result.get('message', 'Unknown error')
            return None, f"Payment failed: {error_msg}"

        return order_id, result['results']

    except requests.exceptions.Timeout:
        return None, "Payment gateway timeout. Please try again."
    except requests.exceptions.RequestException as e:
        logger.error(f"Payment request error: {e}")
        return None, "Payment gateway is currently unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Unexpected payment error: {e}")
        return None, "Error creating payment order. Please try again."

async def check_payment_status(order_id):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        response = requests.get(
            f"{STATUS_CHECK_URL}?order_id={order_id}",
            headers=headers,
            timeout=10
        )

        logger.info(f"Payment status check: {response.status_code}, {response.text}")

        if response.status_code == 200:
            result = response.json()
            if result.get('status') and result.get('data', {}).get('status') == 'TXN_SUCCESS':
                return True, result['data']
        return False, None

    except Exception as e:
        logger.error(f"Payment status check error: {e}")
        return False, None

async def update_timer_message(context, chat_id, message_id, order_id, amount, time_left):
    try:
        payment_info = pending_payments.get(order_id)
        if not payment_info:
            return False

        # Update message with remaining time
        await context.bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=f"**Please complete your payment of ₹{amount} within {time_left} seconds**\n\n"
                   f"Scan the QR code to pay.\n\n"
                   f"Order ID: '{order_id}'\n\n"
                   f"⏰ Time remaining: {time_left}s"
        )

        return True

    except Exception as e:
        logger.error(f"Error updating timer: {e}")
        return False

async def schedule_payment_check(context, order_id, chat_id, message_id):
    payment_info = pending_payments.get(order_id)
    if not payment_info:
        return

    amount = payment_info['amount']
    user_id = payment_info['user_id']

    # Update timer every 5 seconds for 1 minute
    for i in range(12):
        time_left = 60 - (i * 5)
        if time_left < 0:
            time_left = 0

        # Update timer message
        if time_left > 0:
            await update_timer_message(context, chat_id, message_id, order_id, amount, time_left)

        await asyncio.sleep(5)

        if order_id not in pending_payments:
            return

        # Check if payment is completed
        is_paid, payment_data = await check_payment_status(order_id)
        if is_paid:
            # Payment successful
            # Update user wallet
            if user_id not in user_wallets:
                user_wallets[user_id] = 0
            user_wallets[user_id] += amount

            # Delete the payment message
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception as e:
                logger.error(f"Error deleting message: {e}")

            # Create keyboard for buttons
            keyboard = [
                [InlineKeyboardButton("🔍 Search", callback_data='new_search'),
                 InlineKeyboardButton("💳 Wallet", callback_data='wallet')],
                [InlineKeyboardButton("🔙 Back to Main", callback_data='main_menu')]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            # Send success message with buttons
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Payment of ₹{amount} received! Your wallet has been updated.\n\nNew balance: ₹{user_wallets[user_id]}",
                reply_markup=reply_markup
            )

            # Remove from pending payments
            if order_id in pending_payments:
                del pending_payments[order_id]
            return

    # Payment timeout after 1 minute
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.error(f"Error deleting message: {e}")

    # Send timeout message
    await context.bot.send_message(
        chat_id=chat_id,
        text="⏰ Payment session expired. Please initiate a new payment if needed."
    )

    # Remove from pending payments
    if order_id in pending_payments:
        del pending_payments[order_id]

# ============= ADMIN FUNCTIONS =============
def is_admin(user_id):
    return user_id in ADMIN_IDS

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.effective_message.reply_text("❌ You are not authorized to access this panel.")
        return

    keyboard = [
        [InlineKeyboardButton("➕ Add Funds to User", callback_data='admin_add_funds')],
        [InlineKeyboardButton("⭐ Make Premium User", callback_data='admin_make_premium')],
        [InlineKeyboardButton("🔽 Remove Premium", callback_data='admin_remove_premium')],
        [InlineKeyboardButton("📊 Statistics", callback_data='admin_stats')],
        [InlineKeyboardButton("💰 Set Global Search Price", callback_data='admin_set_global_price')],
        [InlineKeyboardButton("👤 Set User Search Price", callback_data='admin_set_user_price')],
        [InlineKeyboardButton("📢 Broadcast Message", callback_data='admin_broadcast')],
        [InlineKeyboardButton("🔙 Back to Main", callback_data='main_menu')]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.effective_message.reply_text(
        "👨‍💼 **Admin Control Panel**\n\nSelect an option:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def admin_add_funds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.message.reply_text(
        "➕ **Add Funds to User**\n\n"
        "Please enter user ID and amount:\n\n"
        "`user_id amount`\n\n"
        "Example:\n"
        "`123456789 100`",
        parse_mode='Markdown'
    )

    return ADMIN_ADD_FUNDS

async def admin_add_funds_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip().split()

    if len(user_input) != 2:
        await update.message.reply_text(
            "❌ Invalid format. Please use:\n\n"
            "`user_id amount`\n\n"
            "Example:\n"
            "`123456789 100`",
            parse_mode='Markdown'
        )
        return ADMIN_ADD_FUNDS

    try:
        target_user_id = int(user_input[0])
        amount = float(user_input[1])

        if target_user_id not in user_wallets:
            user_wallets[target_user_id] = 0

        user_wallets[target_user_id] += amount

        await update.message.reply_text(
            f"✅ Added ₹{amount} to user {target_user_id}'s wallet.\n"
            f"New balance: ₹{user_wallets[target_user_id]}"
        )

        # Notify user
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"🎉 **Admin Credit**\n\n"
                    f"₹{amount} has been added to your wallet by admin.\n"
                    f"New balance: ₹{user_wallets[target_user_id]}",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Could not notify user {target_user_id}: {e}")

        # Show admin panel again
        await admin_command(update, context)

    except ValueError:
        await update.message.reply_text(
            "❌ Invalid input. User ID must be a number and amount must be a valid number."
        )
        return ADMIN_ADD_FUNDS

    return ConversationHandler.END

async def admin_make_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.message.reply_text(
        "⭐ **Make User Premium**\n\n"
        "Please enter user ID:\n\n"
        "Example: `123456789`",
        parse_mode='Markdown'
    )

    return MAKE_PREMIUM

async def admin_make_premium_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = int(update.message.text.strip())
        premium_users.add(user_id)

        await update.message.reply_text(
            f"✅ User {user_id} is now premium!\nThey can now search for free."
        )

        # Notify user
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="🎉 **Congratulations!**\n\n"
                    "You are now a **Premium User**!\n"
                    "Enjoy unlimited free searches!",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Could not notify user {user_id}: {e}")

        await admin_command(update, context)

    except ValueError:
        await update.message.reply_text("❌ Please enter a valid user ID (number).")
        return MAKE_PREMIUM

    return ConversationHandler.END

async def admin_remove_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.message.reply_text(
        "🔽 **Remove Premium Status**\n\n"
        "Please enter user ID:\n\n"
        "Example: `123456789`",
        parse_mode='Markdown'
    )

    return REMOVE_PREMIUM

async def admin_remove_premium_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = int(update.message.text.strip())
        
        if user_id in premium_users:
            premium_users.remove(user_id)
            await update.message.reply_text(f"✅ Premium status removed for user {user_id}")
        else:
            await update.message.reply_text(f"ℹ️ User {user_id} was not premium.")

        await admin_command(update, context)

    except ValueError:
        await update.message.reply_text("❌ Please enter a valid user ID (number).")
        return REMOVE_PREMIUM

    return ConversationHandler.END

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Calculate statistics
    total_users = len(user_wallets)
    total_premium = len(premium_users)
    total_balance = sum(user_wallets.values())
    total_searches = sum(user_search_count.values())

    stats_text = (
        f"📊 **Bot Statistics**\n\n"
        f"👥 Total Users: `{total_users}`\n"
        f"⭐ Premium Users: `{total_premium}`\n"
        f"💰 Total Wallet Balance: `₹{total_balance}`\n"
        f"🔍 Total Searches: `{total_searches}`\n"
        f"🔍 Search Cost: `₹{SEARCH_COST}`"
    )

    keyboard = [[InlineKeyboardButton("🔙 Back to Admin", callback_data='admin_panel')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.reply_text(
        stats_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.message.reply_text(
        "📢 **Broadcast Message**\n\n"
        "Send the message you want to broadcast to all users:",
        parse_mode='Markdown'
    )

    return BROADCAST_MESSAGE

async def admin_broadcast_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text.strip()
    
    broadcast_text = f"📢 **Admin Announcement**\n\n{message}"
    
    success_count = 0
    fail_count = 0
    
    for user_id in user_wallets.keys():
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=broadcast_text,
                parse_mode='Markdown'
            )
            success_count += 1
        except Exception as e:
            logger.error(f"Could not send broadcast to {user_id}: {e}")
            fail_count += 1

    await update.message.reply_text(
        f"📊 **Broadcast Results**\n\n"
        f"✅ Sent: {success_count} users\n"
        f"❌ Failed: {fail_count} users"
    )

    await admin_command(update, context)
    return ConversationHandler.END

# ============= USER COMMANDS =============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    # Initialize user wallet if not exists
    if user_id not in user_wallets:
        user_wallets[user_id] = 0

    keyboard = [
        [InlineKeyboardButton("🔍 Search", callback_data='new_search')],
        [InlineKeyboardButton("💳 Wallet", callback_data='wallet')],
        [InlineKeyboardButton("ℹ️ Help", callback_data='help')]
    ]

    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("👨‍💼 Admin Panel", callback_data='admin_panel')])

    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_text = (
        f"🎉 **Welcome {user.first_name or 'User'}!**\n\n"
        f"🔍 Send a mobile number to search for information\n"
        f"💳 Balance: ₹{user_wallets[user_id]}\n"
        f"💰 Search cost: ₹{SEARCH_COST}\n\n"
        f"Use buttons below to get started!"
    )

    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balance = user_wallets.get(user_id, 0)

    keyboard = [
        [InlineKeyboardButton("➕ Add Funds", callback_data='add_funds')],
        [InlineKeyboardButton("🔙 Back to Main", callback_data='main_menu')]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"💳 **Your Wallet**\n\n"
        f"Balance: ₹{balance}\n"
        f"Search cost: ₹{SEARCH_COST}\n\n"
        f"Click 'Add Funds' to top up your wallet.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balance = user_wallets.get(user_id, 0)

    await update.message.reply_text(
        f"💰 Your current wallet balance: ₹{balance}\n\n"
        f"Each search costs ₹{SEARCH_COST}.\n\n"
        "Use /wallet to add more funds."
    )

# ============= CONVERSATION HANDLERS =============
async def add_funds_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.message.reply_text(
        "💳 Please enter the amount you want to add to your wallet:"
    )

    return AMOUNT

async def amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    amount_text = update.message.text.strip()

    try:
        amount = float(amount_text)

        if amount <= 0:
            await update.message.reply_text("Please enter a valid amount greater than 0.")
            return ConversationHandler.END

        if amount > 10000:
            await update.message.reply_text("Maximum amount is ₹10,000 per transaction.")
            return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("Please enter a valid number for the amount.")
        return ConversationHandler.END

    # Show processing message
    processing_msg = await update.message.reply_text("🔄 Creating payment order...")

    # Create payment order
    order_id, result = await create_payment_order(user_id, amount, update)

    if not order_id:
        await processing_msg.edit_text(result)  # Error message
        return ConversationHandler.END

    # Delete processing message
    await processing_msg.delete()

    qr_image_base64 = result.get('qr_image', '')

    # Store payment information first
    pending_payments[order_id] = {
        'user_id': user_id,
        'amount': amount,
        'chat_id': update.effective_chat.id,
        'timestamp': datetime.now(),
        'status': 'pending'
    }

    # Decode and send QR code
    if qr_image_base64:
        try:
            qr_image_data = base64.b64decode(qr_image_base64)

            # Send message with QR code only (no buttons)
            sent_message = await update.message.reply_photo(
                photo=qr_image_data,
                caption=f"**Please complete your payment of ₹{amount} within 60 seconds**\n\n"
                       f"Scan the QR code to pay.\n\n"
                       f"Order ID: '{order_id}'\n\n"
                       f"⏰ Time remaining: 60s"
            )

            # Update payment information with message ID
            pending_payments[order_id]['message_id'] = sent_message.message_id

            # Schedule payment status check
            asyncio.create_task(schedule_payment_check(context, order_id, update.effective_chat.id, sent_message.message_id))

        except Exception as e:
            logger.error(f"QR code error: {e}")
            # Remove from pending payments if QR code failed
            if order_id in pending_payments:
                del pending_payments[order_id]
            await update.message.reply_text("Error generating payment QR code. Please try again.")
    else:
        # Remove from pending payments if no QR code
        if order_id in pending_payments:
            del pending_payments[order_id]
        await update.message.reply_text("Failed to generate payment QR code. Please try again.")

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('Operation cancelled.')
    return ConversationHandler.END

# ============= MESSAGE HANDLER - Your Original Logic =============
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if message is part of a conversation
    if context.user_data.get('state') in [AMOUNT, BROADCAST_MESSAGE, ADMIN_ADD_FUNDS, SET_GLOBAL_PRICE, SET_USER_PRICE, REMOVE_PREMIUM, MAKE_PREMIUM]:
        return

    # Check if message is a command
    if update.message.text.startswith('/'):
        return

    mobile = update.message.text.strip()

    # Validate mobile number
    if not mobile.isdigit():
        await update.message.reply_text("❌ Please enter a valid mobile number (digits only).")
        return

    if len(mobile) != 10:
        await update.message.reply_text("❌ Please enter a 10-digit mobile number.")
        return

    user_id = update.effective_user.id

    # Check if user is premium
    is_premium = user_id in premium_users

    # Get user's search cost
    user_cost = SEARCH_COST
    if user_id in user_settings and 'search_price' in user_settings[user_id]:
        user_cost = user_settings[user_id]['search_price']

    # Check wallet balance (skip for premium users)
    balance = user_wallets.get(user_id, 0)

    if not is_premium and balance < user_cost:
        keyboard = [
            [InlineKeyboardButton("➕ Add Funds", callback_data='add_funds')],
            [InlineKeyboardButton("🔙 Back to Main", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        error_msg = (
            f"❌ **Insufficient Balance**\n\n"
            f"Your balance: ₹{balance}\n"
            f"Search cost: ₹{user_cost}\n\n"
            f"Please add funds to your wallet."
        )

        await update.message.reply_text(error_msg, reply_markup=reply_markup, parse_mode='Markdown')
        return

    # Show searching message
    searching_msg = await update.message.reply_text("🔍 Searching...")

    try:
        # Perform search
        data = await search_mobile(mobile)

        # Delete searching message
        await searching_msg.delete()

        if not data.get("success"):
            error_msg = (
                f"❌ **Search Failed**\n\n"
                f"Error: {data.get('error', 'Unknown error')}\n\n"
                f"Balance: ₹{user_wallets.get(user_id, 0)}"
            )
            await update.message.reply_text(error_msg, parse_mode='Markdown')
            return

        # Only deduct if search was successful
        if data.get("success") and not is_premium:
            user_wallets[user_id] = balance - user_cost

        # Update search count
        user_search_count[user_id] = user_search_count.get(user_id, 0) + 1

        message_text = format_result(data)

        # Add search info
        if is_premium:
            search_info = f"\n\n⭐ **Premium User** - Free search"
        else:
            search_info = f"\n\n💰 **Cost:** ₹{user_cost}"
            search_info += f"\n💳 **Balance:** ₹{user_wallets.get(user_id, 0)}"

        message_text += search_info

        # Ensure message doesn't exceed limits
        if len(message_text) > 4000:
            message_text = message_text[:3900] + "\n\n... (results truncated)"

        # Add search again button
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Search Again", callback_data='new_search'),
             InlineKeyboardButton("💳 Wallet", callback_data='wallet')],
            [InlineKeyboardButton("🔙 Back to Main", callback_data='main_menu')]
        ])

        try:
            await update.message.reply_text(message_text, reply_markup=keyboard, parse_mode='Markdown')
        except Exception as e:
            await update.message.reply_text(f"⚠️ Error: {str(e)[:100]}")

    except Exception as e:
        # Delete searching message
        try:
            await searching_msg.delete()
        except:
            pass

        logger.error(f"Search error: {e}")
        await update.message.reply_text("❌ An error occurred while searching. Please try again.")

# ============= BUTTON HANDLER =============
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'new_search':
        await query.message.reply_text("🔍 Please send a mobile number to search:")

    elif query.data == 'wallet':
        user_id = query.from_user.id
        balance = user_wallets.get(user_id, 0)

        keyboard = [
            [InlineKeyboardButton("➕ Add Funds", callback_data='add_funds')],
            [InlineKeyboardButton("🔙 Back to Main", callback_data='main_menu')]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.reply_text(
            f"💳 **Your Wallet**\n\n"
            f"Balance: ₹{balance}\n"
            f"Search cost: ₹{SEARCH_COST}",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    elif query.data == 'main_menu':
        user = query.from_user
        user_id = user.id

        keyboard = [
            [InlineKeyboardButton("🔍 Search", callback_data='new_search')],
            [InlineKeyboardButton("💳 Wallet", callback_data='wallet')],
            [InlineKeyboardButton("ℹ️ Help", callback_data='help')]
        ]

        if is_admin(user_id):
            keyboard.append([InlineKeyboardButton("👨‍💼 Admin Panel", callback_data='admin_panel')])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.reply_text(
            f"🏠 **Main Menu**\n\n"
            f"Balance: ₹{user_wallets.get(user_id, 0)}\n"
            f"Search cost: ₹{SEARCH_COST}",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    elif query.data == 'help':
        help_text = (
            f"ℹ️ **How to use this bot:**\n\n"
            f"1. 🔍 Send a 10-digit mobile number\n"
            f"2. 💳 Make sure you have sufficient balance\n"
            f"3. 📊 View results instantly\n\n"
            f"**Commands:**\n"
            f"• /start - Start the bot\n"
            f"• /wallet - Check wallet balance\n"
            f"• /balance - Quick balance check\n"
            f"• /admin - Admin panel (admins only)\n\n"
            f"**Search Cost:** ₹{SEARCH_COST} per search"
        )

        keyboard = [[InlineKeyboardButton("🔙 Back to Main", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.reply_text(help_text, reply_markup=reply_markup, parse_mode='Markdown')

    elif query.data == 'admin_panel':
        await admin_command(query, context)

# ============= RENDER HEALTH CHECK ENDPOINT =============
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health' or self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bot is running!')
        else:
            self.send_response(404)
            self.end_headers()
            
    def log_message(self, format, *args):
        # Suppress default logging
        pass

def run_health_server():
    server = HTTPServer(('0.0.0.0', PORT), HealthCheckHandler)
    server.serve_forever()

# ============= MAIN FUNCTION FOR RENDER =============
def main():
    """Start the bot for Render deployment"""
    logger.info("🚀 Starting Telegram Bot on Render...")
    logger.info(f"🌐 Port: {PORT}")
    logger.info(f"🤖 Bot Token: {BOT_TOKEN[:10]}..." if BOT_TOKEN else "❌ No token")
    logger.info(f"👨‍💼 Admin IDs: {ADMIN_IDS}")
    
    # Start health check server in background thread
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    logger.info(f"💚 Health check server started on port {PORT}")
    
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("wallet", wallet_command))
    application.add_handler(CommandHandler("balance", balance_command))

    # Add conversation handlers
    add_funds_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_funds_callback, pattern='^add_funds$')],
        states={
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, amount_input)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )
    application.add_handler(add_funds_handler)

    admin_add_funds_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_funds, pattern='^admin_add_funds$')],
        states={
            ADMIN_ADD_FUNDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_funds_input)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    application.add_handler(admin_add_funds_handler)

    admin_make_premium_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_make_premium, pattern='^admin_make_premium$')],
        states={
            MAKE_PREMIUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_make_premium_input)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    application.add_handler(admin_make_premium_handler)

    admin_remove_premium_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_remove_premium, pattern='^admin_remove_premium$')],
        states={
            REMOVE_PREMIUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_remove_premium_input)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    application.add_handler(admin_remove_premium_handler)

    admin_broadcast_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_broadcast, pattern='^admin_broadcast$')],
        states={
            BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_input)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    application.add_handler(admin_broadcast_handler)

    # Add callback query handler
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Add message handler for mobile search
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Start the bot with polling (better for Render free tier)
    logger.info("🎯 Bot is running with polling...")
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
