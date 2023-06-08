import discord
from discord.ext import commands
import mcrcon
import os
import asyncio
from pyngrok import ngrok
from mcstatus import JavaServer
import time
import json

intents = discord.Intents.all()
intents.typing = True
intents.presences = True
intents.messages = True

def load_credentials():
    with open('config.json') as file:
        credentials = json.load(file)#get credentials from config.json
    return credentials

credentials = load_credentials()

prefix = credentials['prefix']
bot_token = credentials['token']
ip_channel_id = credentials['channel_for_ip']
chat_channel_id = credentials['channel_for_chat']
log_channel_id = credentials['channel_for_log']
log_path = credentials['path_to_latestlog'] #path to: logs/latest.log
rcon_host = credentials['minecraft_ip'] #localhost
rcon_port = credentials['rcon_port'] #25575
ip_port = credentials['ip_port'] #25565
rcon_password = credentials['rcon_password']
server_name = credentials['server_name']
admin = credentials['admin_role']

filter = ['Thread RCON Client', '[Server thread/INFO]: RCON']# filter RCON lines
max_players_to_show = 10 #max players to be showed in "players" command

bot = commands.Bot(command_prefix=prefix, intents=intents)

bot.remove_command('help')

nueva_ip = None
progress ={}
current_time={}

def create_embed(texto1, texto2, texto3):
    global server_name
    embed = discord.Embed(title=server_name, color=discord.Color.blue())
    embed.add_field(name="state", value=texto1, inline=False)
    embed.add_field(name="IP adress", value=texto2, inline=False)
    embed.add_field(name="players", value=texto3, inline=False)
    embed.set_footer(text="updates every minute")
    return embed


async def check_log():
    await bot.wait_until_ready()
    channel = bot.get_channel(log_channel_id)
    previous_line = ""
    while not bot.is_closed():
        last_line = await get_last_line(log_path)
        if last_line and last_line != previous_line and not word_filter(last_line):
            await channel.send(last_line)
            previous_line = last_line
        await asyncio.sleep(0.5)


async def purge_channel():
    channel = bot.get_channel(log_channel_id)
    deleted = 0
    while True:
        messages = []
        async for message in channel.history(limit=100):
            messages.append(message)
        if not messages:
            print('No more messages were found to delete.')
            break
        await channel.delete_messages(messages)
        deleted += len(messages)
        print(f'Deleted {deleted} messages in total')
        if len(messages) < 100:
            print('No more posts can be deleted due to Discord restrictions or there are no more messages')
            break
        await asyncio.sleep(1)


async def minecraft_to_discord():
    global chat_channel_id
    await bot.wait_until_ready()
    chat_channel = bot.get_channel(chat_channel_id)

    previous_line = ""
    while not bot.is_closed():
        last_line = await get_last_line(log_path)
        if last_line and last_line != previous_line:
            if "" in last_line and "INFO]:" in last_line and "<" in last_line:
                player_message = last_line.split("<", 1)[1]
                await chat_channel.send(player_message)
            previous_line = last_line
        await asyncio.sleep(0.5)



@bot.event
async def on_message(message):
    if message.author.bot:
        return 
    if message.channel.id == chat_channel_id:
        username = message.author.name
        content = message.content
        command = f'tellraw @a ["",{{"text":"[Discord]","color":"aqua"}},{{"text":" {username} "}},{{"text":":","color":"gray"}},{{"text":" {content}","color":"white"}}]'
        with mcrcon.MCRcon(rcon_host, rcon_password, port=rcon_port) as rcon:
            response = rcon.command(command)
            print(response)
    await bot.process_commands(message)




@bot.event
async def on_ready():
    print(f'Bot logged in as: {bot.user.name}')
    global nueva_ip
    bot.loop.create_task(check_log())
    bot.loop.create_task(minecraft_to_discord())
    await purge_channel()

    await bot.change_presence(activity=discord.Game(name="?help"))
    
    ngrok_tunnel = ngrok.connect(ip_port, 'tcp')

    nueva_ip = ngrok_tunnel.public_url.replace("tcp://", "")

    print("=== IP Details ===")
    print(f"IP address: {nueva_ip}")
    print(f"IP address full: {ngrok_tunnel.public_url}")
    print(f"Protocol: {ngrok_tunnel.proto}")
    print(f"========================")

    canal = bot.get_channel(ip_channel_id)

    async for mensaje in canal.history():
        if mensaje.author == bot.user and isinstance(mensaje.embeds, list) and len(mensaje.embeds) > 0:
            await mensaje.delete()

    await canal.edit(topic=f'turning on the server -\nPublic IP: {nueva_ip}')
    
    create_embed("turning on", nueva_ip, "0")

    await asyncio.sleep(30)
    
    jugadores = await get_players(rcon_host, ip_port)
    if jugadores is not None:
        print("Connection established with the server")
    else:
        print("Could not establish connection to the server")
    
    while True:
        jugadores = await get_players(rcon_host, ip_port)
        if jugadores is not None:
            descripcion = f'Jugadores: {jugadores} -\nPublic IP: {nueva_ip}'
            texto1 = "Online"
            texto2 = f"{nueva_ip}"
            texto3 = f"{jugadores}"
        else:
            descripcion = f'Server off -\nPublic IP: {nueva_ip}'
            texto1 = "Offline"
            texto2 = f"{nueva_ip}"
            texto3 = "0"

        await canal.edit(topic=descripcion)

        mensaje_embebido = create_embed(texto1, texto2, texto3)

        async for mensaje in canal.history():
            if mensaje.author == bot.user and isinstance(mensaje.embeds, list) and len(mensaje.embeds) > 0:
                await mensaje.edit(embed=mensaje_embebido)
                break
        else:
            await canal.send(embed=mensaje_embebido)
    
        await asyncio.sleep(60)



async def control(ctx,prkey,wait):
    global admin

    if ctx.author.bot:
        return True

    if any(role.name == admin for role in ctx.author.roles):
        return False

    if not prkey in progress or not progress.get(prkey):
        progress[prkey] = True
        current_time[prkey] = time.time()
        return False

    if time.time() - current_time.get(prkey) < wait and progress.get(prkey):
        return True

    progress[prkey]= False
    return False


async def get_players(ip, puerto):
    try:
        server = JavaServer(ip, puerto)
        status = server.status()
        return status.players.online
    except Exception as e:
        print(f"Error getting players: {e}")
        return None


async def get_last_line(filename):
    with open(filename, 'rb') as f:
        f.seek(-2, os.SEEK_END)
        while f.read(1) != b'\n':
            f.seek(-2, os.SEEK_CUR)
        last_line = f.readline().decode().strip()
    return last_line


def word_filter(texto):
    for palabra in filter:
        if palabra.lower() in texto.lower():
            return True
    return False



@bot.command(aliases=['IP', 'Ip', 'server', 'Server'])
async def ip(ctx):
    if await control(ctx, 'ip', 3):
        return
    if nueva_ip is not None:
        await ctx.send(f'This is the IP of the server: {nueva_ip}')
    else:
        await ctx.send('The server IP is not yet available.')


@bot.command(aliases=['player', 'Players', 'Players', 'list' , 'List'])
async def players(ctx):
    if await control(ctx, 'players', 3):
        return
    with mcrcon.MCRcon(rcon_host, rcon_password, port=rcon_port) as rcon:
        response = rcon.command('list')
        players = response.split(':')[1].strip().split(', ')

        if len(players) == 1 and players[0] == '':
            await ctx.send("There are currently no players on the server.")
            return

        players_remaining = len(players) - max_players_to_show

        if players_remaining > 0:
            players_list = '\n'.join(players[:max_players_to_show])
            players_list += f'\n... y {players_remaining} more.'
        else:
            players_list = '\n'.join(players)

        embed = discord.Embed(title='Players list', description=players_list, color=discord.Color.blue())
        await ctx.send(embed=embed)

@bot.command(aliases=['H', 'h', 'commands' , 'Commands'])
async def help(ctx):
    if await control(ctx, 'help', 3):
        return
    embed = discord.Embed(title='Help command', color=discord.Color.green())

    commands_info = [
        {'name': 'ip', 'description': 'Shows the IP of the server.'},
        {'name': 'players', 'description': 'Shows the list of players on the server'},
        {'name': 'command', 'description': 'Run a command in the server console (administrators only).'},
        {'name': 'help', 'description': 'Shows this message.'},
    ]

    for cmd_info in commands_info:
        command_name = cmd_info['name']
        command_description = cmd_info['description']
        embed.add_field(name=command_name, value=command_description, inline=False)

    await ctx.send(embed=embed)

@bot.command(aliases=['comand', 'Comand', 'Command', 'execute' , 'Execute' , 'exe' , 'Exe'])
async def command(ctx, *, command):
    global admin
    if not any(role.name == admin for role in ctx.author.roles):
        await ctx.send(f"you don't have the necessary role")
        return
    with mcrcon.MCRcon(rcon_host, rcon_password, port=rcon_port) as rcon:
        response = rcon.command(command)
        await ctx.send(f'server response: {response}')

bot.run(bot_token)
