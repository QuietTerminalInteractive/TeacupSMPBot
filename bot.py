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
import re
import random


# Configuration
log_level = logging.INFO
log_dir = './logs'
users_file = './users.json'
token_file = './token.txt'
twitch_api_url = "http://127.0.0.1:5002/notify_discord"
ping_channel_file = './ping_channel.json'
people_who_can_marry_the_bot = [606918160146235405, 
479325312023396373,
779052381312516126,
1219369222933708862]

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

def load_settings():
    """
    Loads the settings from the users.json file.

    If the file doesn't exist, returns a default structure with an empty 'servers' dictionary.

    Returns:
        dict: A dictionary containing the settings, including the 'servers' key.
    """
    if os.path.exists(users_file):
        with open(users_file, 'r') as f:
            return json.load(f)
    return {"servers": {}}

def save_settings(settings):
    """
    Saves the given settings to the users.json file.

    Args:
        settings (dict): The settings to save, typically containing the 'servers' key.
    """
    with open(users_file, 'w') as f:
        json.dump(settings, f, indent=4)

def load_users(guild_id):
    """
    Loads the registered users for a specific Discord server (guild).

    Args:
        guild_id (str): The Discord guild ID to load the users for.

    Returns:
        dict: A dictionary of users for the specified server, including a list of registered users.
    """
    settings = load_settings()
    return settings["servers"].get(str(guild_id), {}).get("users", {})

def save_users(guild_id, users):
    """
    Saves the user data for a specific Discord server (guild).

    Args:
        guild_id (str): The Discord guild ID where the users should be saved.
        users (dict): A dictionary of user data to save under the specified guild ID.
    """
    settings = load_settings()
    if str(guild_id) not in settings["servers"]:
        settings["servers"][str(guild_id)] = {"users": {}}
    settings["servers"][str(guild_id)]["users"] = users
    save_settings(settings)

def load_ping_channel(guild_id):
    """
    Loads the ping channel ID for a specific Discord server (guild).

    Args:
        guild_id (str): The Discord guild ID to load the ping channel for.

    Returns:
        int or None: The ID of the ping channel for the guild, or None if not set.
    """
    settings = load_settings()
    return settings["servers"].get(str(guild_id), {}).get("ping_channel_id", None)

def save_ping_channel(guild_id, channel_id):
    """
    Saves the ping channel ID for a specific Discord server (guild).

    Args:
        guild_id (str): The Discord guild ID where the ping channel should be saved.
        channel_id (int): The ID of the channel to be used for ping notifications.
    """
    settings = load_settings()
    if str(guild_id) not in settings["servers"]:
        settings["servers"][str(guild_id)] = {}
    settings["servers"][str(guild_id)]["ping_channel_id"] = channel_id
    save_settings(settings)

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

    channel = bot.get_channel(load_ping_channel())
    message = f"`DEBUG: Start scheduled at {time.strftime('%d/%m/%Y-%H:%M:%S')}`"
    await channel.send(message)

    # Start processing announcements
    bot.loop.create_task(process_announcements())

def marry_the_bot_RE(messageText):
    regex = re.compile(r"(?<!not\s)marry\ssteven", re.IGNORECASE)
    return regex.search(messageText)


@bot.event
async def on_message(message):
    num = random.randint(1, 10000)
    if message.author == bot.user:
        return

    if "circle" in message.content.lower() or "c i r c l e" in message.content.lower():
        await message.add_reaction('🔵')

    if message.content.lower() == "marry steven":

        if message.author.id in people_who_can_marry_the_bot or not marry_the_bot_RE(message.content.lower()):
            await message.reply("Yes.")
        else:
            await message.reply("No.")
    if message.content.lower() == "tea":
        await message.reply("Coffee is better.")
    if num == 52:
        message.reply("🔵")

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
