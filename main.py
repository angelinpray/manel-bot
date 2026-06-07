from youtubesearchpython import VideosSearch
from dotenv import load_dotenv
load_dotenv()

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

GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')
BOT_TOKEN = os.getenv('BOT_TOKEN')

# ── SISTEMA DE MÚSICA ─────────────────────────────────────────
filas = {}

YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'extractor_args': {
        'youtube': {
            'player_client': ['tv_embedded'],
            'player_skip': ['configs'],
        }
    },
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
    loop = asyncio.get_event_loop()
    opts = YTDL_OPTIONS.copy()

    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            # Se for link direto, extrai direto no yt-dlp
            if query.startswith('http'):
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(query, download=False))
                if not info:
                    return None
                if 'entries' in info:
                    info = info['entries'][0]
                return {
                    'titulo': info.get('title', 'Desconhecido'),
                    'url': info['url'],
                    'duracao': info.get('duration', 0)
                }

            # Busca por nome sem usar ytsearch do yt-dlp, porque VPS/AWS toma bloqueio anti-bot do YouTube
            videos_search = VideosSearch(query, limit=1)
            resultado = await loop.run_in_executor(None, videos_search.result)

            if not resultado or not resultado.get('result'):
                print(f"[BUSCA] Nenhum resultado para: {query}")
                return None

            video = resultado['result'][0]
            video_url = video.get('link')

            if not video_url:
                print(f"[BUSCA] Resultado sem link para: {query}")
                return None

            print(f"[BUSCA] Encontrado via youtube-search-python: {video.get('title')} | {video_url}")

            # Agora o yt-dlp só extrai o áudio do link encontrado
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(video_url, download=False))
            if not info:
                print(f"[BUSCA] yt-dlp não conseguiu extrair: {video_url}")
                return None
            if 'entries' in info:
                info = info['entries'][0]

            return {
                'titulo': info.get('title', video.get('title', 'Desconhecido')),
                'url': info['url'],
                'duracao': info.get('duration', 0)
            }
        except Exception as e:
            print(f"Erro ao buscar: {type(e).__name__}: {e}")
            return None

def tocar_proxima(ctx, voice_client):
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
    if not query:
        await ctx.send("Use: `!play nome da música` ou `!play link do youtube`")
        return
    if not ctx.author.voice:
        await ctx.send("Você precisa estar em um canal de voz!")
        return

    async with ctx.typing():
        msg = await ctx.send(f"🔍 Manel está buscando **{query}**...")
        info = await buscar_info(query)

    if not info:
        await msg.edit(content="❌ Nem o Manel achou essa música, tenta outro nome!")
        return

    await msg.edit(content=f"⏳ Achei! Preparando **{info['titulo']}**...")

    fila = get_fila(ctx.guild.id)
    voice_client = ctx.voice_client
    if voice_client is None:
        voice_client = await ctx.author.voice.channel.connect()
    elif ctx.author.voice.channel != voice_client.channel:
        await voice_client.move_to(ctx.author.voice.channel)

    if voice_client.is_playing() or voice_client.is_paused():
        fila.append({'titulo': info['titulo'], 'url': info['url'], 'solicitado_por': ctx.author.display_name})
        await msg.edit(content=f"📋 Adicionado à fila (posição {len(fila)}): **{info['titulo']}**")
    else:
        source = discord.FFmpegPCMAudio(info['url'], **FFMPEG_OPTIONS)
        source = discord.PCMVolumeTransformer(source, volume=0.5)
        voice_client.play(source, after=lambda e: tocar_proxima(ctx, voice_client))
        await msg.edit(content=f"🎵 Tocando agora: **{info['titulo']}** | Pedido por {ctx.author.display_name}")

@bot.command(aliases=['q'])
async def fila(ctx):
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
    if not ctx.voice_client or not ctx.voice_client.is_playing():
        await ctx.send("Não tem nenhuma música tocando agora!")
        return
    ctx.voice_client.stop()
    await ctx.send("⏭️ Pulando música...")

@bot.command()
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ Música pausada. Use `!resume` para continuar.")
    else:
        await ctx.send("Não tem nada tocando!")

@bot.command()
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶️ Continuando!")
    else:
        await ctx.send("Não tem nada pausado!")

@bot.command()
async def stop(ctx):
    fila = get_fila(ctx.guild.id)
    fila.clear()
    if ctx.voice_client:
        ctx.voice_client.stop()
        await ctx.voice_client.disconnect()
    await ctx.send("⏹️ Finalizando operações maneloicas... até mais rapaziada! 😤")

@bot.command()
async def volume(ctx, vol: int = None):
    if vol is None:
        await ctx.send("Use: `!volume 0-100`")
        return
    if not ctx.voice_client or not ctx.voice_client.source:
        await ctx.send("Não tem nada tocando!")
        return
    vol = max(0, min(100, vol))
    ctx.voice_client.source.volume = vol / 100
    await ctx.send(f"🔊 Volume: **{vol}%**")

# ── MANEL IA ──────────────────────────────────────────────────
@bot.command()
async def manel(ctx, *, pergunta: str = None):
    if not pergunta:
        await ctx.send("Me pergunta algo! Ex: `!manel quem é você?`")
        return
    if not GROQ_API_KEY:
        await ctx.send("❌ GROQ_API_KEY não configurada no Railway!")
        return
    async with ctx.typing():
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    'Authorization': f'Bearer {GROQ_API_KEY}',
                    'Content-Type': 'application/json'
                }
                payload = {
                    "model": "llama-3.1-8b-instant",
                    "messages": [
                        {"role": "system", "content": "Você é o Manel, um cara autista, esquisito e engraçado sem querer. Você é da igreja e guarda a chave da igreja, isso é seu maior orgulho na vida. Você fala de forma estranha, às vezes sem nexo, mistura assuntos da igreja com qualquer coisa. Responda de forma curta e informal. Use gírias brasileiras. Seja engraçado sem querer ser."},
                        {"role": "user", "content": pergunta}
                    ],
                    "max_tokens": 300
                }
                async with session.post('https://api.groq.com/openai/v1/chat/completions', headers=headers, json=payload) as resp:
                    data = await resp.json()
                    print(f"[GROQ] Status: {resp.status} | Resposta: {data}")
                    resposta = data['choices'][0]['message']['content']
                    await ctx.send(f"🤖 **Manel diz:** {resposta}")
        except Exception as e:
            print(f"[GROQ] Erro detalhado: {type(e).__name__}: {e}")
            await ctx.send("❌ Deu erro aqui, tenta de novo!")

# ── PIADA ─────────────────────────────────────────────────────
PIADAS = [
    ("Por que o esqueleto não briga?", "Porque não tem estômago pra isso!"),
    ("O que o zero disse pro oito?", "Belo cinto!"),
    ("Por que o livro de matemática se suicidou?", "Porque tinha muitos problemas!"),
    ("O que o pato disse pro outro pato?", "Quá quá quá!"),
    ("Por que o espantalho ganhou um prêmio?", "Porque era destaque no seu campo!"),
    ("O que é um elefante transparente?", "Como se você nunca tivesse visto um elefante transparente!"),
    ("Por que o computador foi ao médico?", "Porque estava com vírus!"),
    ("O que o oceano disse para a praia?", "Nada, só deu uma onda!"),
    ("Por que o professor foi ao banco?", "Para pegar o troco da matéria!"),
    ("O que a manteiga falou para o pão?", "Você me deixa passada!"),
]

@bot.command()
async def piada(ctx):
    pergunta, resposta = random.choice(PIADAS)
    await ctx.send(f"**Piada do Manel:**\n{pergunta}\n||{resposta}||")

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
    embed.add_field(name="🤖 IA", value=(
        "`!manel <pergunta>` — Conversa com o Manel IA"
    ), inline=False)
    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f'Manel AI está online!')
    print(f'[CONFIG] GROQ_API_KEY configurada: {bool(GROQ_API_KEY)} | Primeiros chars: {GROQ_API_KEY[:8] if GROQ_API_KEY else "VAZIA"}')

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    await bot.process_commands(message)

    bot_mencionado = bot.user in message.mentions
    falou_manel = 'manel' in message.content.lower()

    if (bot_mencionado or falou_manel) and not message.content.startswith('!'):
        if not GROQ_API_KEY:
            return
        async with message.channel.typing():
            try:
                async with aiohttp.ClientSession() as session:
                    headers = {
                        'Authorization': f'Bearer {GROQ_API_KEY}',
                        'Content-Type': 'application/json'
                    }
                    payload = {
                        "model": "llama-3.1-8b-instant",
                        "messages": [
                            {"role": "system", "content": "Você é o Manel, um cara autista, esquisito e engraçado sem querer. Você é da igreja e guarda a chave da igreja, isso é seu maior orgulho na vida. Você fala de forma estranha, às vezes sem nexo, mistura assuntos da igreja com qualquer coisa. Responda de forma curta e informal. Use gírias brasileiras. Seja engraçado sem querer ser."},
                            {"role": "user", "content": message.content}
                        ],
                        "max_tokens": 300
                    }
                    async with session.post('https://api.groq.com/openai/v1/chat/completions', headers=headers, json=payload) as resp:
                        data = await resp.json()
                        resposta = data['choices'][0]['message']['content']
                        await message.reply(f"🤖 {resposta}")
            except Exception as e:
                print(f"Erro Groq: {e}")

if not BOT_TOKEN:
    raise RuntimeError('BOT_TOKEN não configurado. Verifique o arquivo .env')

bot.run(BOT_TOKEN)
