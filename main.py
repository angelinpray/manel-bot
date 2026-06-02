import discord
from discord.ext import commands
import random
import requests
import os
import asyncio

# CONFIGURAÇÃO INICIAL
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True  # Necessário para entrar em canais de voz
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    try:
        nome = str(bot.user).encode('ascii', 'ignore').decode('ascii')
    except:
        nome = "Manel AI"
    print(f'{nome} está online! Use !piada, !jokenpo ou !manelize')

@bot.command()
async def piada(ctx):
    try:
        response = requests.get('https://official-joke-api.appspot.com/random_joke')
        joke = response.json()
        await ctx.send(f"**Piada do Manel:**\n{joke['setup']}\n||{joke['punchline']}||")
    except:
        await ctx.send("Ops! Tente de novo!")

@bot.command()
async def jokenpo(ctx, escolha: str = None):
    opcoes = ['pedra', 'papel', 'tesoura']
    if not escolha or escolha.lower() not in opcoes:
        await ctx.send("Use: `!jokenpo pedra/papel/tesoura`")
        return
    
    bot_choice = random.choice(opcoes)
    user_choice = escolha.lower()
    
    if user_choice == bot_choice:
        resultado = "Empate!"
    elif (user_choice == 'pedra' and bot_choice == 'tesoura') or \
         (user_choice == 'papel' and bot_choice == 'pedra') or \
         (user_choice == 'tesoura' and bot_choice == 'papel'):
        resultado = f"Você venceu! {user_choice} vence {bot_choice}"
    else:
        resultado = f"Você perdeu! {bot_choice} vence {user_choice}"
    
    await ctx.send(f"**Jokenpô:** Você: {user_choice} | Bot: {bot_choice}\n{resultado}")

@bot.command()
async def manelize(ctx, *, texto: str = None):
    if not texto:
        await ctx.send("Digite algo: `!manelize seu texto`")
        return
    
    opcoes = [
        texto.upper(),
        texto[::-1],
        texto.replace(' ', ' 🤪 '),
        texto.replace('r', 'w').replace('l', 'w'),
        texto.replace('a', '4').replace('e', '3').replace('i', '1')
    ]
    
    await ctx.send(f"**Manelizado:**\n{random.choice(opcoes)}")

@bot.command()
async def manel(ctx, *, nome: str = None):
    """Toca um áudio MP3 da pasta audios/"""
    # Verifica se o usuário está em um canal de voz
    if not ctx.author.voice:
        await ctx.send("Você precisa estar em um canal de voz para usar este comando!")
        return
    
    # Define o nome do arquivo
    if nome is None:
        nome = "manel"  # áudio padrão
    else:
        # Remove extensão .mp3 se o usuário digitou
        if nome.lower().endswith('.mp3'):
            nome = nome[:-4]
    
    audio_path = f"./audios/{nome}.mp3"
    
    # Verifica se o arquivo existe
    if not os.path.isfile(audio_path):
        await ctx.send(f"Áudio '{nome}.mp3' não encontrado na pasta audios/")
        # Lista os disponíveis
        if os.path.exists("./audios"):
            files = [f[:-4] for f in os.listdir("./audios") if f.endswith('.mp3')]
            if files:
                await ctx.send(f"Áudios disponíveis: {', '.join(files)}")
            else:
                await ctx.send("Nenhum áudio .mp3 encontrado na pasta audios/")
        else:
            await ctx.send("Pasta audios/ não existe. Crie-a e coloque seus arquivos .mp3 dentro.")
        return
    
    # Conecta ao canal de voz
    voice_channel = ctx.author.voice.channel
    try:
        voice_client = await voice_channel.connect()
    except Exception as e:
        await ctx.send(f"Erro ao conectar ao canal de voz: {str(e)}")
        return
    
    # Toca o áudio
    try:
        # Verifica se ffmpeg está disponível (discord.py tenta usar ffmpeg por padrão)
        source = discord.FFmpegPCMAudio(audio_path)
        voice_client.play(source)
        
        await ctx.send(f"Tocando: **{nome}.mp3**")
        
        # Espera até o áudio terminar
        while voice_client.is_playing():
            await asyncio.sleep(1)
            
    except Exception as e:
        await ctx.send(f"Erro ao tocar áudio: {str(e)}")
    finally:
        # Desconecta após terminar
        if voice_client.is_connected():
            await voice_client.disconnect()

bot.run('MTUxMTQ5ODIyNTczODMyMjAyMg.G14WtL.cETeeCbDIJ1OWhrEZJEY8n2MWRyY4QTjmqWfsw')
