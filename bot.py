# bot.py

import logging
import time
import os
import discord
from discord.ext import commands
import json
import requests
from threading import Thread
from queue import Queue
from flask import Flask, request, jsonify
import asyncio

# Configuration
log_level = logging.INFO
log_dir = './logs'
users_file = './users.json'
token_file = './token.txt'
twitch_api_url = "http://127.0.0.1:5002/notify_discord"
ping_channel_file = './ping_channel.json'

# Initialize Logging
if not os.path.exists(log_dir):
    os.makedirs(log_dir)
logging.basicConfig(
    filename=f"{log_dir}/bot-{time.strftime('%d%m%Y-%H%M%S')}.log",
    level=log_level,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
console = logging.StreamHandler()
console.setLevel(log_level)
logging.getLogger('').addHandler(console)

# Load Bot Token
try:
    with open(token_file) as f:
        token = f.read().strip()
except FileNotFoundError:
    logging.error(f"Token file '{token_file}' not found!")
    raise

# Bot Setup
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix='.', intents=intents)

# Utility Functions
def load_users():
    if os.path.exists(users_file):
        with open(users_file, 'r') as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(users_file, 'w') as f:
        json.dump(users, f, indent=4)

def save_ping_channel(channel_id):
    with open(ping_channel_file, 'w') as f:
        json.dump({"ping_channel_id": channel_id}, f)

def load_ping_channel():
    if os.path.exists(ping_channel_file):
        with open(ping_channel_file, 'r') as f:
            data = json.load(f)
            return data.get("ping_channel_id", None)

async def send_announcement(user_name, stream_title):
    """Send a Twitch stream notification to the Discord channel."""
    global ping_channel_id

    if not ping_channel_id:
        logging.error("Ping channel ID is not set. Cannot send notification.")
        return

    channel = bot.get_channel(ping_channel_id)
    if not channel:
        logging.error(f"Channel with ID {ping_channel_id} not found.")
        return

    message = f"🔴 {user_name} is live on Twitch! \n**{stream_title}**\nhttps://www.twitch.tv/{user_name}"
    try:
        await channel.send(message)
        logging.info(f"Notification sent for {user_name}: {stream_title}")
    except Exception as e:
        logging.error(f"Failed to send notification: {e}")

# Global variables
ping_channel_id = load_ping_channel()
if ping_channel_id:
    logging.info(f"Ping channel loaded: {ping_channel_id}")
else:
    logging.info("Ping channel not set.")

start_time = time.time()

# Initialize a Queue for announcements
announcement_queue = Queue()

# Flask App Setup
app = Flask(__name__)

@app.route('/twitch-webhook', methods=['POST'])
def twitch_webhook():
    """Handle Twitch webhook callbacks."""
    try:
        data = request.json
        if 'event' in data:
            user_name = data['event']['broadcaster_user_name']
            stream_title = data['event'].get('title', 'No title provided')
            announcement_queue.put((user_name, stream_title))
            logging.debug("Received webhook event and added to queue.")
            return jsonify({'status': 'received'})
        return jsonify({'status': 'ignored'})
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return jsonify({'error': f"An error occurred: {e}"}), 500

@app.route('/notify_discord', methods=['POST'])
def notify_discord():
    """Endpoint to register a Twitch username."""
    try:
        data = request.get_json()
        username = data.get("username")
        if not username:
            return jsonify({"error": "'username' is required"}), 400

        users = load_users()
        users.setdefault("registered", []).append(username)
        with open(users_file, 'w') as f:
            json.dump(users, f, indent=4)

        return jsonify({"status": "success", "message": f"User {username} registered"}), 200
    except Exception as e:
        return jsonify({'error': f"Internal server error: {e}"}), 500

def run_flask():
    """Run Flask server."""
    app.run(host='0.0.0.0', port=5002)

# Background task to process announcements
async def process_announcements():
    while True:
        user_name, stream_title = await bot.loop.run_in_executor(None, announcement_queue.get)
        await send_announcement(user_name, stream_title)

# Commands
@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user}.")
    try:
        await bot.tree.sync()
        logging.info("Slash commands synced.")
    except Exception as e:
        logging.error(f"Error syncing commands: {e}")

    channel = bot.get_channel(1308431320141139989)
    message = f"`DEBUG: Start scheduled at {time.strftime('%d/%m/%Y-%H:%M:%S')}`"
    await channel.send(message)

    # Start processing announcements
    bot.loop.create_task(process_announcements())

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if "circle" in message.content.lower() or "c i r c l e" in message.content.lower():
        await message.add_reaction('🔵')

    elif "marry steven" in message.content.lower():
        if message.author.id == 606918160146235405:
            await message.reply("Yes.")
        else:
            await message.reply("No.")

    await bot.process_commands(message)

@bot.tree.command(name="setchannel", description="Sets the ping channel to the current channel.")
async def set_ping_channel(interaction: discord.Interaction):
    global ping_channel_id
    ping_channel_id = interaction.channel.id
    save_ping_channel(ping_channel_id)
    await interaction.response.send_message(f"Ping channel set to: {interaction.channel.name}")

@bot.tree.command(name="register", description="Register a Twitch username for notifications.")
async def register_twitch_user(interaction: discord.Interaction, username: str):
    users = load_users()
    discord_id = str(interaction.user.id)

    if discord_id in users and username in users[discord_id]:
        await interaction.response.send_message(f"You are already registered for {username}.")
        return

    users.setdefault(discord_id, []).append(username)
    save_users(users)

    try:
        response = requests.post(twitch_api_url, json={"username": username})
        if response.status_code == 200:
            await interaction.response.send_message(f"Registered Twitch username: {username}")
        else:
            await interaction.response.send_message(f"Failed to register {username} with Twitch API.")
    except Exception as e:
        logging.error(f"Twitch API error: {e}")
        await interaction.response.send_message("Error setting up notifications.")

@bot.tree.command(name="unregister", description="Unregister a Twitch username.")
async def unregister_twitch_user(interaction: discord.Interaction, username: str):
    users = load_users()
    discord_id = str(interaction.user.id)

    if discord_id not in users or username not in users[discord_id]:
        await interaction.response.send_message(f"You are not registered for {username}.")
        return

    users[discord_id].remove(username)
    if not users[discord_id]:
        del users[discord_id]
    save_users(users)

    await interaction.response.send_message(f"Unregistered Twitch username: {username}")

@bot.tree.command(name="info", description="Display bot information.")
async def info_command(interaction: discord.Interaction):
    uptime = int(time.time() - start_time)

    embed = discord.Embed(
        title="Bot Information",
        description="Details about the bot:",
        color=discord.Color.blue(),
    )
    embed.add_field(name="Bot Name", value=bot.user.name, inline=False)
    embed.add_field(name="Uptime", value=f"{uptime // 3600}h {(uptime % 3600) // 60}m", inline=False)
    embed.add_field(name="Developers", value="[GitHub](https://github.com/QuietTerminalInteractive)", inline=False)
    embed.add_field(name="Source Code", value="[Repository](https://github.com/quietterminalinteractive/TeacupSMPBot)", inline=False)
    embed.add_field(name="Total Users", value=sum(guild.member_count for guild in bot.guilds), inline=False)
    embed.set_footer(text="Use /help for available commands.")

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="help", description="Show a list of available commands.")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Help - Commands",
        description="List of all available commands:",
        color=discord.Color.blue(),
    )

    for command in bot.tree.get_commands():
        embed.add_field(
            name=f"/{command.name}",
            value=command.description or "No description available.",
            inline=False,
        )

    await interaction.response.send_message(embed=embed)

# Run Flask in a separate thread
flask_thread = Thread(target=run_flask, daemon=True)
flask_thread.start()

# Run Bot
if __name__ == '__main__':
    bot.run(token)
