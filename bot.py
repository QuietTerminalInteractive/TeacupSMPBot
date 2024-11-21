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
import signal


# Configuration
log_level = logging.DEBUG
log_dir = './logs'
token_file = './token.txt'
settings_file = './settings.json'
twitch_api_url = "http://127.0.0.1:5002/notify_discord"
people_who_can_marry_the_bot = [606918160146235405, 479325312023396373, 779052381312516126, 1219369222933708862]
easter_egg_guilds = [1227640355625766963,1091009808431325184]

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

def signal_handler(sig, frame):
    logging.info("KeyboardInterrupt received. Exiting...")
    os._exit(0)

def calculate_sum(expression: str) -> str:
    """
    Calculates the sum of a mathematical expression.

    Args:
        expression (str): The expression to be calculated.

    Returns:
        The result of the expression as a string, or 'Invalid expression' if the expression is invalid.
    """
    if not re.match(r'^[\d+\-*/().\sx]*$', expression):
        return 'Invalid expression'

    try:
        expression = expression.replace('^', '**').replace('x', '*').replace(' ', '')
        result = eval(expression)
        return f"`{expression}={result}`"
    except ZeroDivisionError:
        return 'inf'
    except Exception:
        return 'Invalid expression'

def load_settings():
    """Loads the settings from the settings.json file."""
    if os.path.exists(settings_file):
        with open(settings_file, 'r') as f:
            return json.load(f)
    return {"servers": {}}

def save_settings(settings):
    """Saves the settings to the settings.json file."""
    with open(settings_file, 'w') as f:
        json.dump(settings, f, indent=4)

def load_ping_channel(guild_id):
    """
    Loads the ping channel ID for a specific Discord server (guild).
    """
    settings = load_settings()
    guild_settings = settings["servers"].get(str(guild_id), {})
    logging.debug(f"Guild settings: {guild_settings}")
    return guild_settings.get("ping_channel_id", None)

def save_ping_channel(guild_id, channel_id):
    """Saves the ping channel ID for a specific guild."""
    settings = load_settings()
    if str(guild_id) not in settings["servers"]:
        settings["servers"][str(guild_id)] = {}
    settings["servers"][str(guild_id)]["ping_channel_id"] = channel_id
    logging.debug(f"Saving settings: {settings}")
    save_settings(settings)

def load_users():
    """Loads all registered users across all guilds."""
    settings = load_settings()
    users = {}
    for guild_id, guild_data in settings["servers"].items():
        users[guild_id] = guild_data.get("users", {})
    logging.debug(f"Users: {users}")
    return users

def save_users(guild_id, users):
    """Saves the registered users for a specific guild."""
    settings = load_settings()
    if str(guild_id) not in settings["servers"]:
        settings["servers"][str(guild_id)] = {"users": {}}
    settings["servers"][str(guild_id)]["users"] = users
    logging.debug(f"Saving settings: {settings}")
    save_settings(settings)

async def send_announcement(user_name, stream_title, guild_id):
    """Send a Twitch stream notification to the Discord channel."""
    channel_id = load_ping_channel(guild_id)
    if not channel_id:
        logging.error(f"Ping channel not set for guild {guild_id}. Cannot send notification.")
        return

    channel = bot.get_channel(channel_id)
    if not channel:
        logging.error(f"Channel with ID {channel_id} not found in guild {guild_id}.")
        return

    message = f"🔴 {user_name} is live on Twitch! \n**{stream_title}**\nhttps://www.twitch.tv/{user_name}"
    try:
        await channel.send(message)
        logging.info(f"Notification sent for {user_name} in guild {guild_id}.")
    except Exception as e:
        logging.error(f"Failed to send notification to guild {guild_id}: {e}")

# Global variables
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

            users = load_users()
            logging.debug(f"Loaded users: {users}")

            # Adjusted logic to handle nested structure
            registered_guilds = [
                guild_id
                for guild_id, guild_users in users.items()
                if any(user_name in usernames for usernames in guild_users.values())
            ]
            logging.debug(f"Registered guilds for {user_name}: {registered_guilds}")

            for guild_id in registered_guilds:
                announcement_queue.put((user_name, stream_title, guild_id))

            logging.info(f"Webhook processed for {user_name}, queued for {len(registered_guilds)} guild(s).")
            return jsonify({'status': 'processed', 'guilds_notified': len(registered_guilds)})
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

        return jsonify({"status": "success", "message": f"User {username} registered"}), 200
    except Exception as e:
        return jsonify({'error': f"Internal server error: {e}"}), 500

def run_flask():
    """Run Flask server."""
    app.run(host='0.0.0.0', port=5002)

# Background task to process announcements
async def process_announcements():
    while True:
        user_name, stream_title, guild_id = await bot.loop.run_in_executor(None, announcement_queue.get)
        await send_announcement(user_name, stream_title, guild_id)

# Commands
@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user}.")
    try:
        await bot.tree.sync()
        logging.info("Slash commands synced.")
    except Exception as e:
        logging.error(f"Error syncing commands: {e}")

    for guild in bot.guilds:
        try:
            ping_channel_id = load_ping_channel(guild.id)
            if ping_channel_id:
                channel = bot.get_channel(ping_channel_id)
                if channel:
                    if log_level == logging.DEBUG:
                        message = f"`DEBUG: Start scheduled at {time.strftime('%d/%m/%Y-%H:%M:%S')}`"
                        await channel.send(message)
                        logging.debug(f"Sent debug message to guild {guild.name} ({guild.id}) in channel {channel.name}")
                    else:
                        logging.info(f"guild {guild.name} has ping channel set to {channel.name}")
                    
                else:
                    logging.warning(f"Channel with ID {ping_channel_id} not found in guild {guild.name} ({guild.id}).")
            else:
                logging.warning(f"No ping channel set for guild {guild.name} ({guild.id}).")
        except Exception as e:
            logging.error(f"Error sending debug message to guild {guild.name} ({guild.id}): {e}")
        continue

    bot.loop.create_task(process_announcements())
    logging.info("Bot is ready and announcements are being processed.")

def marry_the_bot_RE(messageText):
    regex = re.compile(r"(?<!not\s)marry\ssteven", re.IGNORECASE)
    if regex.search(messageText):
        logging.debug("Passed check 2")
        return True
    else:
        logging.debug("Failed check 2")
        return False

def random_trigger(chance):
    if random.randint(1, chance) == 1:
        return True
    else:
        return False



@bot.event
async def on_message(message):
    
    if message.author == bot.user:
        return
    if message.guild.id in easter_egg_guilds:
        if "circle" in message.content.lower() or "c i r c l e" in message.content.lower():
            await message.add_reaction('🔵')


        if "marry steven" in message.content.lower().strip():
            logging.debug(f"Passed check 1")
            if message.author.id in people_who_can_marry_the_bot or not marry_the_bot_RE(message.content.lower()):
                await message.reply("Yes.")
            else:
                await message.reply("No.")
        if message.content.lower() == "tea":
            await message.reply("Coffee is better.")
        if random_trigger(10000):
            await message.reply("🔵")

    if message.content.lower().startswith("c!"):
        message.content = message.content[2:]
        regex = re.compile(r"\b2\s*\+\s*2\b", re.IGNORECASE)
        if regex.search(message.content) and random_trigger(4):
            await message.reply("`2+2=5`")
        else:
            responce = calculate_sum(message.content)
            await message.reply(responce)



    await bot.process_commands(message)

@bot.tree.command(name="setchannel", description="Sets the ping channel to the current channel.")
async def set_ping_channel(interaction: discord.Interaction):
    save_ping_channel(interaction.guild.id, interaction.channel.id)
    await interaction.response.send_message(f"Ping channel set to: {interaction.channel.name}")

@bot.tree.command(name="register", description="Register a Twitch username for notifications.")
async def register_twitch_user(interaction: discord.Interaction, username: str):
    guild_id = interaction.guild.id
    users = load_users().get(str(guild_id), {})
    discord_id = str(interaction.user.id)

    if discord_id in users and username in users[discord_id]:
        await interaction.response.send_message(f"You are already registered for {username}.")
        return

    users.setdefault(discord_id, []).append(username)
    save_users(guild_id, users)

    await interaction.response.send_message(f"Registered Twitch username: {username}")

@bot.tree.command(name="unregister", description="Unregister a Twitch username.")
async def unregister_twitch_user(interaction: discord.Interaction, username: str):
    guild_id = interaction.guild.id
    users = load_users().get(str(guild_id), {})
    discord_id = str(interaction.user.id)

    if discord_id not in users or username not in users[discord_id]:
        await interaction.response.send_message(f"You are not registered for {username}.")
        return

    users[discord_id].remove(username)
    if not users[discord_id]:
        del users[discord_id]
    save_users(guild_id, users)

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
    signal.signal(signal.SIGINT, signal_handler)
    bot.run(token)