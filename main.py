import discord
from discord.ext import commands
import random
import aiohttp
import os
import asyncio
from collections import deque
import yt_dlp

# CONFIGURAÇÃO INICIAL
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix='!', intents=intents)

GROQ_API_KEY = os.getenv('GROQ_API_KEY', 'SUA_CHAVE_GROQ_AQUI')
BOT_TOKEN = os.getenv('BOT_TOKEN', 'SEU_TOKEN_AQUI')

# ── SISTEMA DE MÚSICA ─────────────────────────────────────────
# Fila de músicas por servidor
filas = {}  # guild_id -> deque de dicts {titulo, url, solicitado_por}

YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

def get_fila(guild_id):
    if guild_id not in filas:
        filas[guild_id] = deque()
    return filas[guild_id]

async def buscar_info(query):
    """Busca info da música no YouTube sem baixar"""
    loop = asyncio.get_event_loop()
    with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
        try:
            # Se não for URL, busca no YouTube
            if not query.startswith('http'):
                query = f"ytsearch:{query}"
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(query, download=False))
            if 'entries' in info:
                info = info['entries'][0]
            return {
                'titulo': info.get('title', 'Desconhecido'),
                'url': info['url'],
                'webpage_url': info.get('webpage_url', ''),
                'duracao': info.get('duration', 0)
            }
        except Exception as e:
            return None

def tocar_proxima(ctx, voice_client):
    """Callback chamado quando a música termina"""
    fila = get_fila(ctx.guild.id)
    if fila:
        musica = fila.popleft()
        source = discord.FFmpegPCMAudio(musica['url'], **FFMPEG_OPTIONS)
        source = discord.PCMVolumeTransformer(source, volume=0.5)
        voice_client.play(source, after=lambda e: tocar_proxima(ctx, voice_client))
        asyncio.run_coroutine_threadsafe(
            ctx.send(f"🎵 Tocando agora: **{musica['titulo']}** | Pedido por {musica['solicitado_por']}"),
            bot.loop
        )
    else:
        asyncio.run_coroutine_threadsafe(
            ctx.send("✅ Fila acabou! Use `!play` para adicionar mais músicas."),
            bot.loop
        )

@bot.command(aliases=['p'])
async def play(ctx, *, query: str = None):
    """Toca ou adiciona música à fila. Uso: !play <nome ou link>"""
    if not query:
        await ctx.send("Use: `!play nome da música` ou `!play link do youtube`")
        return

    if not ctx.author.voice:
        await ctx.send("Você precisa estar em um canal de voz!")
        return

    msg = await ctx.send(f"🔍 Buscando **{query}**...")

    info = await buscar_info(query)
    if not info:
        await msg.edit(content="❌ Não encontrei essa música, tenta outro nome!")
        return

    fila = get_fila(ctx.guild.id)

    # Conecta ao canal se não estiver
    voice_client = ctx.voice_client
    if voice_client is None:
        voice_client = await ctx.author.voice.channel.connect()
    elif ctx.author.voice.channel != voice_client.channel:
        await voice_client.move_to(ctx.author.voice.channel)

    if voice_client.is_playing() or voice_client.is_paused():
        # Adiciona à fila
        fila.append({
            'titulo': info['titulo'],
            'url': info['url'],
            'solicitado_por': ctx.author.display_name
        })
        pos = len(fila)
        await msg.edit(content=f"📋 Adicionado à fila (posição {pos}): **{info['titulo']}**")
    else:
        # Toca direto
        source = discord.FFmpegPCMAudio(info['url'], **FFMPEG_OPTIONS)
        source = discord.PCMVolumeTransformer(source, volume=0.5)
        voice_client.play(source, after=lambda e: tocar_proxima(ctx, voice_client))
        await msg.edit(content=f"🎵 Tocando agora: **{info['titulo']}** | Pedido por {ctx.author.display_name}")

@bot.command(aliases=['q'])
async def fila(ctx):
    """Mostra a fila de músicas. Uso: !fila"""
    fila = get_fila(ctx.guild.id)
    if not fila:
        await ctx.send("📋 A fila está vazia! Use `!play` para adicionar músicas.")
        return

    lista = "\n".join([f"`{i+1}.` {m['titulo']} — {m['solicitado_por']}" for i, m in enumerate(fila)])
    embed = discord.Embed(title="📋 Fila de músicas", description=lista, color=0x7289da)
    embed.set_footer(text=f"{len(fila)} música(s) na fila")
    await ctx.send(embed=embed)

@bot.command(aliases=['s'])
async def skip(ctx):
    """Pula a música atual. Uso: !skip"""
    if not ctx.voice_client or not ctx.voice_client.is_playing():
        await ctx.send("Não tem nenhuma música tocando agora!")
        return
    ctx.voice_client.stop()
    await ctx.send("⏭️ Pulando música...")

@bot.command()
async def pause(ctx):
    """Pausa a música. Uso: !pause"""
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ Música pausada. Use `!resume` para continuar.")
    else:
        await ctx.send("Não tem nada tocando!")

@bot.command()
async def resume(ctx):
    """Retoma a música pausada. Uso: !resume"""
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶️ Continuando!")
    else:
        await ctx.send("Não tem nada pausado!")

@bot.command()
async def stop(ctx):
    """Para a música e limpa a fila. Uso: !stop"""
    fila = get_fila(ctx.guild.id)
    fila.clear()
    if ctx.voice_client:
        ctx.voice_client.stop()
        await ctx.voice_client.disconnect()
    await ctx.send("⏹️ Música parada e fila limpa!")

@bot.command()
async def volume(ctx, vol: int = None):
    """Ajusta o volume (0-100). Uso: !volume 50"""
    if vol is None:
        await ctx.send("Use: `!volume 0-100`")
        return
    if not ctx.voice_client or not ctx.voice_client.source:
        await ctx.send("Não tem nada tocando!")
        return
    vol = max(0, min(100, vol))
    ctx.voice_client.source.volume = vol / 100
    await ctx.send(f"🔊 Volume: **{vol}%**")

# ── PIADA (Groq) ──────────────────────────────────────────────
@bot.command()
async def piada(ctx):
    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama3-8b-8192",
            "messages": [
                {"role": "system", "content": "Você é um bot engraçado brasileiro. Responda APENAS com uma piada curta e engraçada em português do Brasil. Formato: pergunta na primeira linha, resposta na segunda linha."},
                {"role": "user", "content": "Me conta uma piada!"}
            ],
            "max_tokens": 150
        }
        try:
            async with session.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload) as resp:
                data = await resp.json()
                piada_texto = data['choices'][0]['message']['content']
                linhas = piada_texto.strip().split('\n', 1)
                if len(linhas) == 2:
                    await ctx.send(f"**Piada do Manel:**\n{linhas[0]}\n||{linhas[1]}||")
                else:
                    await ctx.send(f"**Piada do Manel:**\n{piada_texto}")
        except:
            await ctx.send("Ops! Não consegui buscar uma piada agora, tenta de novo!")

# ── JOKENPÔ ───────────────────────────────────────────────────
@bot.command()
async def jokenpo(ctx, escolha: str = None):
    opcoes = ['pedra', 'papel', 'tesoura']
    if not escolha or escolha.lower() not in opcoes:
        await ctx.send("Use: `!jokenpo pedra/papel/tesoura`")
        return
    bot_choice = random.choice(opcoes)
    user_choice = escolha.lower()
    if user_choice == bot_choice:
        resultado = "Empate! 🤝"
    elif (user_choice == 'pedra' and bot_choice == 'tesoura') or \
         (user_choice == 'papel' and bot_choice == 'pedra') or \
         (user_choice == 'tesoura' and bot_choice == 'papel'):
        resultado = f"Você venceu! 🎉 {user_choice} vence {bot_choice}"
    else:
        resultado = f"Você perdeu! 😂 {bot_choice} vence {user_choice}"
    await ctx.send(f"**Jokenpô:** Você: {user_choice} | Bot: {bot_choice}\n{resultado}")

# ── MANELIZE ──────────────────────────────────────────────────
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

# ── AJUDA ─────────────────────────────────────────────────────
@bot.command()
async def ajuda(ctx):
    embed = discord.Embed(title="🤖 Manel AI — Comandos", color=0x7289da)
    embed.add_field(name="🎵 Música", value=(
        "`!play <nome/link>` — Toca ou adiciona à fila\n"
        "`!fila` — Mostra a fila\n"
        "`!skip` — Pula a música\n"
        "`!pause` / `!resume` — Pausa/retoma\n"
        "`!stop` — Para tudo e sai\n"
        "`!volume <0-100>` — Ajusta volume"
    ), inline=False)
    embed.add_field(name="😂 Diversão", value=(
        "`!piada` — Piada em português\n"
        "`!jokenpo pedra/papel/tesoura` — Jokenpô\n"
        "`!manelize <texto>` — Transforma texto"
    ), inline=False)
    await ctx.send(embed=embed)

# ── ON READY ──────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f'Manel AI está online!')

bot.run(BOT_TOKEN)
