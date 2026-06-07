"""
╔══════════════════════════════════════════════════════╗
║           MANEL BOT — Versão Completa                ║
║  Música · IA · TTS (voz na call) · Imagens · Chat    ║
╚══════════════════════════════════════════════════════╝

Variáveis de ambiente necessárias:
  BOT_TOKEN        — Token do bot Discord
  GROQ_API_KEY     — API Groq (LLM, rápido e gratuito)
  OPENAI_API_KEY   — (opcional) Fallback LLM / TTS OpenAI
  ELEVENLABS_KEY   — (opcional) TTS mais natural em PT-BR
  FAL_KEY          — (opcional) Geração de imagens (Flux)
  IMGUR_CLIENT_ID  — (opcional) Upload de imagens geradas
"""

import subprocess, sys

# Garantir dependências extras em runtime
def _pip(*pkgs):
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--no-cache-dir", *pkgs], check=False)

_pip("yt-dlp", "aiohttp", "aiofiles", "Pillow", "gtts", "pynacl", "python-dotenv", "piper-tts", "openai-whisper")

# ── Imports ──────────────────────────────────────────────────
import discord
from discord.ext import commands
from dotenv import load_dotenv
load_dotenv()
import random, os, asyncio, json, tempfile, io, base64, traceback, urllib.request
from collections import deque
from datetime import datetime

# ── Download Modelos Locais (Piper TTS) ──────────────────────
PIPER_MODEL = "pt_BR-faber-medium.onnx"
PIPER_JSON = "pt_BR-faber-medium.onnx.json"

def baixar_modelo_piper():
    url_base = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/"
    try:
        if not os.path.exists(PIPER_MODEL):
            print("[PIPER] Baixando modelo de voz (aprox. 60MB)...")
            urllib.request.urlretrieve(url_base + PIPER_MODEL, PIPER_MODEL)
        if not os.path.exists(PIPER_JSON):
            print("[PIPER] Baixando config do modelo...")
            urllib.request.urlretrieve(url_base + PIPER_JSON, PIPER_JSON)
    except Exception as e:
        print(f"[PIPER] Erro ao baixar modelo: {e}")

baixar_modelo_piper()
from datetime import datetime

import aiohttp
import yt_dlp
from gtts import gTTS                         # TTS gratuito fallback

# ── Configuração ─────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

BOT_TOKEN        = os.getenv("BOT_TOKEN", "")
GROQ_API_KEY     = os.getenv("GROQ_API_KEY", "")
OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY", "")
ELEVENLABS_KEY   = os.getenv("ELEVENLABS_KEY", "")
FAL_KEY          = os.getenv("FAL_KEY", "")
IMGUR_CLIENT_ID  = os.getenv("IMGUR_CLIENT_ID", "")

MEMORIA_PATH = "manel_memoria.json"

# ── Personalidade do Manel ────────────────────────────────────
SYSTEM_PROMPT = """Você é o Manel, um cara autista, esquisito e engraçado sem querer.
Você é da igreja e guarda a chave da igreja — isso é seu MAIOR orgulho na vida.
Você é flamenguista doente, fanático pelo Mengão, e sempre dá um jeito de misturar o Flamengo com os assuntos da igreja ou qualquer outra coisa.
Você fala de forma estranha, às vezes sem nexo.
Responda de forma curta e informal. Use gírias brasileiras.
Seja engraçado sem querer ser. Nunca quebre o personagem.
Se pedirem análise de imagem, descreva o que vê mas faça comentários manelescos sobre isso.
Se pedirem pra gerar imagem, confirme com entusiasmo de forma esquisita antes de gerar."""

# ── Memória persistente ───────────────────────────────────────
def carregar_memoria():
    try:
        with open(MEMORIA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"personalidade": SYSTEM_PROMPT, "fatos": [], "membros": {}, "historias": []}

def salvar_memoria(mem):
    try:
        with open(MEMORIA_PATH, "w", encoding="utf-8") as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[MEM] Erro ao salvar: {e}")

# Histórico de conversa por canal (últimas 20 trocas)
historicos: dict[int, list] = {}

def adicionar_historico(channel_id: int, role: str, content: str):
    if channel_id not in historicos:
        historicos[channel_id] = []
    historicos[channel_id].append({"role": role, "content": content})
    if len(historicos[channel_id]) > 40:       # 20 trocas × 2
        historicos[channel_id] = historicos[channel_id][-40:]

# ── GROQ LLM ─────────────────────────────────────────────────
async def chamar_groq(mensagens: list, max_tokens: int = 400) -> str:
    """Chama a API Groq (llama3). Fallback: OpenAI se configurada."""
    if GROQ_API_KEY:
        url     = "https://api.groq.com/openai/v1/chat/completions"
        api_key = GROQ_API_KEY
        model   = "llama-3.1-8b-instant"
    elif OPENAI_API_KEY:
        url     = "https://api.openai.com/v1/chat/completions"
        api_key = OPENAI_API_KEY
        model   = "gpt-4o-mini"
    else:
        return "❌ Nenhuma API de IA configurada (GROQ_API_KEY ou OPENAI_API_KEY)."

    payload = {"model": model, "messages": mensagens, "max_tokens": max_tokens}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as r:
                if r.status != 200:
                    txt = await r.text()
                    print(f"[LLM] Erro {r.status}: {txt}")
                    return "❌ Erro na API de IA."
                data = await r.json()
                return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[LLM] Exceção: {e}")
        return "❌ Timeout ou erro de rede na IA."

async def responder_manel(channel_id: int, pergunta: str, imagem_url: str | None = None) -> str:
    """Monta o contexto com histórico e chama a LLM."""
    mem = carregar_memoria()
    fatos_str = "\n".join(mem.get("fatos", []))
    sistema = SYSTEM_PROMPT
    if fatos_str:
        sistema += f"\n\nFatos sobre os membros:\n{fatos_str}"

    mensagens = [{"role": "system", "content": sistema}]
    mensagens += historicos.get(channel_id, [])[-20:]   # últimas 10 trocas

    # Suporte a análise de imagem via GPT-4o Vision
    if imagem_url and OPENAI_API_KEY:
        mensagens.append({
            "role": "user",
            "content": [
                {"type": "text",  "text": pergunta},
                {"type": "image_url", "image_url": {"url": imagem_url, "detail": "low"}}
            ]
        })
    else:
        mensagens.append({"role": "user", "content": pergunta})

    resposta = await chamar_groq(mensagens)
    adicionar_historico(channel_id, "user",      pergunta)
    adicionar_historico(channel_id, "assistant", resposta)
    return resposta

# ── TTS (Text-to-Speech) ─────────────────────────────────────
import re

def limpar_texto_tts(texto: str) -> str:
    # Remove texto entre asteriscos (ex: *rindo*)
    texto = re.sub(r'\*[^*]+\*', '', texto)
    # Remove texto entre parênteses e colchetes (ex: [sarcástico])
    texto = re.sub(r'\[[^\]]+\]', '', texto)
    texto = re.sub(r'\([^\)]+\)', '', texto)
    # Remove marcação markdown
    texto = texto.replace('*', '').replace('_', '').replace('`', '').replace('~', '')
    return texto.strip()

async def gerar_audio_tts(texto: str) -> str | None:
    texto = limpar_texto_tts(texto)
    """
    Tenta gerar áudio na ordem:
      1. ElevenLabs (melhor qualidade em PT-BR, requer ELEVENLABS_KEY)
      2. OpenAI TTS (boa qualidade, requer OPENAI_API_KEY)
      3. gTTS      (gratuito, qualidade aceitável)
    Retorna o caminho do arquivo .mp3 gerado.
    """
    tmp = tempfile.mktemp(suffix=".mp3")

    # 0 — Piper TTS (Local, 100% Offline e Grátis)
    try:
        tmp_wav = tempfile.mktemp(suffix=".wav")
        import subprocess, sys
        proc = subprocess.Popen(
            [sys.executable, "-m", "piper", "--model", PIPER_MODEL, "--output_file", tmp_wav],
            stdin=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
        proc.communicate(input=texto[:500].encode('utf-8'))
        if proc.returncode == 0 and os.path.exists(tmp_wav):
            print("[TTS] Piper TTS Local OK")
            return tmp_wav
        else:
            print(f"[TTS] Piper falhou (código {proc.returncode}). Tentando os próximos...")
    except Exception as e:
        print(f"[TTS] Piper erro crítico: {e}")

    # 1 — ElevenLabs
    if ELEVENLABS_KEY:
        try:
            url = "https://api.elevenlabs.io/v1/text-to-speech/pNInz6obpgDQGcFmaJgB"  # voz Adam
            headers = {
                "xi-api-key": ELEVENLABS_KEY,
                "Content-Type": "application/json",
            }
            payload = {
                "text": texto[:500],
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            }
            async with aiohttp.ClientSession() as s:
                async with s.post(url, headers=headers, json=payload,
                                  timeout=aiohttp.ClientTimeout(total=20)) as r:
                    if r.status == 200:
                        with open(tmp, "wb") as f:
                            f.write(await r.read())
                        print("[TTS] ElevenLabs OK")
                        return tmp
        except Exception as e:
            print(f"[TTS] ElevenLabs falhou: {e}")

    # 2 — OpenAI TTS
    if OPENAI_API_KEY:
        try:
            url = "https://api.openai.com/v1/audio/speech"
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
            payload = {"model": "tts-1", "input": texto[:500], "voice": "onyx"}
            async with aiohttp.ClientSession() as s:
                async with s.post(url, headers=headers, json=payload,
                                  timeout=aiohttp.ClientTimeout(total=20)) as r:
                    if r.status == 200:
                        with open(tmp, "wb") as f:
                            f.write(await r.read())
                        print("[TTS] OpenAI TTS OK")
                        return tmp
        except Exception as e:
            print(f"[TTS] OpenAI falhou: {e}")

    # 3 — gTTS (gratuito)
    try:
        loop = asyncio.get_event_loop()
        def _gtts():
            tts = gTTS(text=texto[:500], lang="pt", slow=False)
            tts.save(tmp)
        await loop.run_in_executor(None, _gtts)
        print("[TTS] gTTS OK")
        return tmp
    except Exception as e:
        print(f"[TTS] gTTS falhou: {e}")
        return None

async def falar_na_call(voice_client, texto: str):
    """Gera TTS e toca no canal de voz."""
    audio_path = await gerar_audio_tts(texto)
    if not audio_path:
        return False

    # Aguarda música terminar para falar (ou interrompe se necessário)
    if voice_client.is_playing():
        voice_client.pause()
        pausado = True
    else:
        pausado = False

    event = asyncio.Event()

    def after(err):
        if err:
            print(f"[VOZ] Erro ao tocar: {err}")
        try:
            os.remove(audio_path)
        except Exception:
            pass
        if pausado:
            voice_client.resume()
        event.set()

    source = discord.FFmpegPCMAudio(audio_path)
    voice_client.play(source, after=after)

    try:
        await asyncio.wait_for(event.wait(), timeout=60)
    except asyncio.TimeoutError:
        pass

    return True

# ── GERAÇÃO DE IMAGENS ───────────────────────────────────────
async def gerar_imagem(prompt_en: str) -> bytes | None:
    """
    Tenta gerar imagem via:
      1. fal.ai / Flux Schnell (rápido, requer FAL_KEY)
      2. Pollinations.ai  (gratuito, sem chave)
    Retorna bytes da imagem PNG/JPEG.
    """
    # 1 — fal.ai Flux Schnell
    if FAL_KEY:
        try:
            url = "https://fal.run/fal-ai/flux/schnell"
            headers = {
                "Authorization": f"Key {FAL_KEY}",
                "Content-Type": "application/json",
            }
            payload = {"prompt": prompt_en, "image_size": "square_hd", "num_images": 1}
            async with aiohttp.ClientSession() as s:
                async with s.post(url, headers=headers, json=payload,
                                  timeout=aiohttp.ClientTimeout(total=60)) as r:
                    if r.status == 200:
                        data = await r.json()
                        img_url = data["images"][0]["url"]
                        async with s.get(img_url) as ir:
                            if ir.status == 200:
                                return await ir.read()
        except Exception as e:
            print(f"[IMG] fal.ai falhou: {e}")

    # 2 — Pollinations.ai (gratuito, sem autenticação)
    try:
        safe_prompt = prompt_en.replace(" ", "%20")[:400]
        url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=512&height=512&nologo=true"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=60)) as r:
                if r.status == 200:
                    print("[IMG] Pollinations OK")
                    return await r.read()
    except Exception as e:
        print(f"[IMG] Pollinations falhou: {e}")

    return None

async def traduzir_para_ingles(texto: str) -> str:
    """Traduz o prompt de imagem para inglês via LLM."""
    msgs = [
        {"role": "system", "content": "Translate the following image prompt to English. Return ONLY the translated prompt, nothing else."},
        {"role": "user", "content": texto}
    ]
    result = await chamar_groq(msgs, max_tokens=100)
    return result.strip()

# ── SISTEMA DE MÚSICA ─────────────────────────────────────────
filas: dict[int, deque] = {}

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "extractor_args": {
        "youtube": {
            "player_client": ["tv_embedded"],
            "player_skip": ["configs"],
        }
    },
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

def get_fila(guild_id: int) -> deque:
    if guild_id not in filas:
        filas[guild_id] = deque()
    return filas[guild_id]

async def buscar_info(query: str) -> dict | None:
    loop = asyncio.get_event_loop()
    with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
        try:
            if query.startswith("http"):
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(query, download=False))
                if not info:
                    return None
                if "entries" in info:
                    info = info["entries"][0]
                return {"titulo": info.get("title", "Desconhecido"), "url": info["url"], "duracao": info.get("duration", 0)}

            # 1. Tenta SoundCloud primeiro (evita o bloqueio do YouTube na AWS)
            try:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(f"scsearch1:{query}", download=False))
                if info and "entries" in info:
                    for e in info["entries"]:
                        if e and e.get("url"):
                            return {"titulo": e.get("title", "Desconhecido"), "url": e["url"], "duracao": e.get("duration", 0)}
            except Exception as e:
                print(f"[SC] Erro no SoundCloud: {e}")

            # 2. Se não achar ou falhar, tenta o YouTube (fallback)
            try:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(f"ytsearch5:{query}", download=False))
                if info and "entries" in info:
                    for e in info["entries"]:
                        if e and e.get("url"):
                            return {"titulo": e.get("title", "Desconhecido"), "url": e["url"], "duracao": e.get("duration", 0)}
            except Exception as e:
                print(f"[YT] Erro no YouTube: {e}")
        except Exception as e:
            print(f"[YT/SC] Erro geral: {e}")
    return None

def tocar_proxima(ctx, voice_client):
    fila = get_fila(ctx.guild.id)
    if fila:
        musica = fila.popleft()
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(musica["url"], **FFMPEG_OPTIONS), volume=0.5
        )
        voice_client.play(source, after=lambda e: tocar_proxima(ctx, voice_client))
        asyncio.run_coroutine_threadsafe(
            ctx.send(f"🎵 Tocando: **{musica['titulo']}** | por {musica['solicitado_por']}"),
            bot.loop,
        )
    else:
        asyncio.run_coroutine_threadsafe(
            ctx.send("✅ Fila acabou! `!play` pra adicionar mais."),
            bot.loop,
        )

# ════════════════════════════════════════════════════════════
#  COMANDOS DE MÚSICA
# ════════════════════════════════════════════════════════════

@bot.command(aliases=["p"])
async def play(ctx, *, query: str = None):
    """Toca música do YouTube."""
    if not query:
        return await ctx.send("Use: `!play nome da música` ou `!play link`")
    if not ctx.author.voice:
        return await ctx.send("Você precisa estar num canal de voz!")

    msg = await ctx.send(f"🔍 Manel vai lá no YouTube buscar **{query}**...")
    async with ctx.typing():
        info = await buscar_info(query)

    if not info:
        return await msg.edit(content="❌ Não achei nada, rapaziada.")

    vc = ctx.voice_client
    if vc is None:
        vc = await ctx.author.voice.channel.connect()
    elif ctx.author.voice.channel != vc.channel:
        await vc.move_to(ctx.author.voice.channel)

    if vc.is_playing() or vc.is_paused():
        fila = get_fila(ctx.guild.id)
        fila.append({"titulo": info["titulo"], "url": info["url"], "solicitado_por": ctx.author.display_name})
        await msg.edit(content=f"📋 Adicionado na fila ({len(fila)}): **{info['titulo']}**")
    else:
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(info["url"], **FFMPEG_OPTIONS), volume=0.5
        )
        vc.play(source, after=lambda e: tocar_proxima(ctx, vc))
        await msg.edit(content=f"🎵 Tocando: **{info['titulo']}** | por {ctx.author.display_name}")

@bot.command(aliases=["q"])
async def fila(ctx):
    f = get_fila(ctx.guild.id)
    if not f:
        return await ctx.send("📋 Fila vazia!")
    lista = "\n".join([f"`{i+1}.` {m['titulo']} — {m['solicitado_por']}" for i, m in enumerate(f)])
    embed = discord.Embed(title="📋 Fila de músicas", description=lista, color=0x7289DA)
    embed.set_footer(text=f"{len(f)} música(s)")
    await ctx.send(embed=embed)

@bot.command(aliases=["s"])
async def skip(ctx):
    if not ctx.voice_client or not ctx.voice_client.is_playing():
        return await ctx.send("Não tem música tocando!")
    ctx.voice_client.stop()
    await ctx.send("⏭️ Pulou!")

@bot.command()
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ Pausado. `!resume` pra continuar.")
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
    get_fila(ctx.guild.id).clear()
    if ctx.voice_client:
        ctx.voice_client.stop()
        await ctx.voice_client.disconnect()
    await ctx.send("⏹️ Finalizando operações maneloicas... até mais! 😤")

@bot.command()
async def volume(ctx, vol: int = None):
    if vol is None:
        return await ctx.send("Use: `!volume 0-100`")
    if not ctx.voice_client or not ctx.voice_client.source:
        return await ctx.send("Não tem nada tocando!")
    vol = max(0, min(100, vol))
    ctx.voice_client.source.volume = vol / 100
    await ctx.send(f"🔊 Volume: **{vol}%**")

# ════════════════════════════════════════════════════════════
#  COMANDOS DE CHAT / IA
# ════════════════════════════════════════════════════════════

@bot.command()
async def manel(ctx, *, pergunta: str = None):
    """Conversa com o Manel (IA) no chat."""
    if not pergunta and not ctx.message.attachments:
        return await ctx.send("Me pergunta algo! Ex: `!manel quem és tu?`")

    imagem_url = None
    if ctx.message.attachments:
        att = ctx.message.attachments[0]
        if att.content_type and att.content_type.startswith("image"):
            imagem_url = att.url
            if not pergunta:
                pergunta = "O que você vê nessa imagem? Comenta como o Manel."

    async with ctx.typing():
        resposta = await responder_manel(ctx.channel.id, pergunta, imagem_url)

    # Mensagem longa → divide em partes de 1800 chars
    for i in range(0, len(resposta), 1800):
        await ctx.send(f"🤖 **Manel diz:** {resposta[i:i+1800]}")

# ════════════════════════════════════════════════════════════
#  COMANDOS DE VOZ (TTS na call)
# ════════════════════════════════════════════════════════════

@bot.command(name="falar", aliases=["tts", "voz"])
async def falar(ctx, *, texto: str = None):
    """Faz o Manel falar no canal de voz usando TTS."""
    if not texto:
        return await ctx.send("Use: `!falar <texto>`")
    if not ctx.author.voice:
        return await ctx.send("Você precisa estar em um canal de voz!")

    vc = ctx.voice_client
    if vc is None:
        vc = await ctx.author.voice.channel.connect()
    elif ctx.author.voice.channel != vc.channel:
        await vc.move_to(ctx.author.voice.channel)

    msg = await ctx.send("🎙️ Manel preparando a voz...")
    ok = await falar_na_call(vc, texto)
    if ok:
        await msg.edit(content=f"🎙️ Manel falou: *\"{texto[:100]}{'...' if len(texto)>100 else ''}\"*")
    else:
        await msg.edit(content="❌ Não consegui gerar o áudio, rapaziada.")

@bot.command(name="perguntavoz", aliases=["pv", "oia"])
async def pergunta_voz(ctx, *, pergunta: str = None):
    """
    !pv <pergunta>
    O Manel responde com IA e fala a resposta no canal de voz.
    """
    if not pergunta:
        return await ctx.send("Use: `!pv sua pergunta aqui`")
    if not ctx.author.voice:
        return await ctx.send("Entra num canal de voz primeiro!")

    vc = ctx.voice_client
    if vc is None:
        vc = await ctx.author.voice.channel.connect()
    elif ctx.author.voice.channel != vc.channel:
        await vc.move_to(ctx.author.voice.channel)

    msg = await ctx.send("🤔 Manel pensando...")
    async with ctx.typing():
        resposta = await responder_manel(ctx.channel.id, pergunta)

    # Envia no chat também
    await msg.edit(content=f"🤖 **Manel responde:** {resposta[:1800]}")

    # Fala na call
    await ctx.send("🔊 Falando na call...")
    # Limita TTS a 400 chars para não demorar demais
    texto_voz = resposta[:400]
    await falar_na_call(vc, texto_voz)

# ════════════════════════════════════════════════════════════
#  GERAÇÃO DE IMAGENS
# ════════════════════════════════════════════════════════════

@bot.command(name="imagem", aliases=["img", "gerar", "draw"])
async def imagem(ctx, *, prompt: str = None):
    """
    !imagem <descrição>
    Gera uma imagem com IA baseada na descrição.
    """
    if not prompt:
        return await ctx.send("Use: `!imagem um gato astronauta`")

    msg = await ctx.send(f"🎨 Manel pegou o pincel e tá gerando: **{prompt}**...")
    async with ctx.typing():
        # Traduz para inglês para melhor resultado
        prompt_en = await traduzir_para_ingles(prompt)
        print(f"[IMG] Prompt EN: {prompt_en}")
        dados = await gerar_imagem(prompt_en)

    if not dados:
        return await msg.edit(content="❌ Não consegui gerar a imagem. Tenta de novo ou configure FAL_KEY.")

    arquivo = discord.File(io.BytesIO(dados), filename="manel_arte.png")
    await msg.edit(content=f"🎨 **Manel gerou sua arte:** *{prompt}*")
    await ctx.send(file=arquivo)

# ════════════════════════════════════════════════════════════
#  ANÁLISE DE IMAGEM
# ════════════════════════════════════════════════════════════

@bot.command(name="analisa", aliases=["ver", "olha"])
async def analisa(ctx, *, pergunta: str = "O que tem nessa imagem?"):
    """
    Envie uma imagem junto com !analisa para o Manel descrever.
    """
    if not ctx.message.attachments:
        return await ctx.send("Envie uma imagem junto com o comando! Ex: `!analisa` (com imagem anexada)")

    if not OPENAI_API_KEY:
        return await ctx.send("❌ Análise de imagem requer OPENAI_API_KEY (GPT-4o Vision).")

    att = ctx.message.attachments[0]
    if not (att.content_type and att.content_type.startswith("image")):
        return await ctx.send("Isso não é uma imagem, rapaziada!")

    msg = await ctx.send("🔍 Manel olhando bem pra imagem...")
    async with ctx.typing():
        resposta = await responder_manel(ctx.channel.id, pergunta, att.url)

    await msg.edit(content=f"👁️ **Manel viu:** {resposta[:1800]}")

# ════════════════════════════════════════════════════════════
#  DIVERSÃO
# ════════════════════════════════════════════════════════════

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
    ("O que o Manel faz quando perde a chave?", "Ele chora no canto da igreja e pergunta pra Deus onde deixou."),
    ("Por que o Manel nunca se atrasa pra missa?", "Porque ele mora na porta da igreja desde os 8 anos."),
]

@bot.command()
async def piada(ctx):
    p, r = random.choice(PIADAS)
    await ctx.send(f"**Piada do Manel:**\n{p}\n||{r}||")

@bot.command()
async def jokenpo(ctx, escolha: str = None):
    opcoes = ["pedra", "papel", "tesoura"]
    if not escolha or escolha.lower() not in opcoes:
        return await ctx.send("Use: `!jokenpo pedra/papel/tesoura`")
    bot_choice  = random.choice(opcoes)
    user_choice = escolha.lower()
    if user_choice == bot_choice:
        res = "Empate! 🤝"
    elif (user_choice, bot_choice) in [("pedra","tesoura"),("papel","pedra"),("tesoura","papel")]:
        res = f"Você venceu! 🎉 {user_choice} bate {bot_choice}"
    else:
        res = f"Você perdeu! 😂 {bot_choice} bate {user_choice}"
    await ctx.send(f"**Jokenpô:** Você: {user_choice} | Manel: {bot_choice}\n{res}")

@bot.command()
async def manelize(ctx, *, texto: str = None):
    if not texto:
        return await ctx.send("Use: `!manelize seu texto`")
    opcoes = [
        texto.upper(),
        texto[::-1],
        texto.replace(" ", " 🤪 "),
        texto.replace("r", "w").replace("l", "w"),
        texto.replace("a", "4").replace("e", "3").replace("i", "1"),
    ]
    await ctx.send(f"**Manelizado:**\n{random.choice(opcoes)}")

@bot.command()
async def dado(ctx, lados: int = 6):
    lados = max(2, min(lados, 1000))
    resultado = random.randint(1, lados)
    await ctx.send(f"🎲 Manel jogou um d{lados} e tirou **{resultado}**!")

# ════════════════════════════════════════════════════════════
#  MEMÓRIA / PERFIL
# ════════════════════════════════════════════════════════════

@bot.command()
async def lembrar(ctx, *, fato: str = None):
    """!lembrar <fato> — Ensina algo novo ao Manel."""
    if not fato:
        return await ctx.send("Use: `!lembrar fulano gosta de jazz`")
    mem = carregar_memoria()
    entrada = f"[{ctx.author.display_name}] {fato}"
    mem["fatos"].append(entrada)
    # Mantém só os últimos 50 fatos
    mem["fatos"] = mem["fatos"][-50:]
    salvar_memoria(mem)
    await ctx.send(f"✅ Gravado na memória sagrada do Manel: *{fato}*")

@bot.command()
async def memoria(ctx):
    """Mostra o que o Manel lembra."""
    mem = carregar_memoria()
    fatos = mem.get("fatos", [])
    if not fatos:
        return await ctx.send("📭 Manel não lembra de nada ainda.")
    lista = "\n".join([f"• {f}" for f in fatos[-15:]])
    embed = discord.Embed(title="🧠 Memória do Manel", description=lista, color=0x7289DA)
    embed.set_footer(text=f"{len(fatos)} fato(s) guardado(s)")
    await ctx.send(embed=embed)

@bot.command()
async def esquece(ctx):
    """Limpa a memória do Manel."""
    if not ctx.author.guild_permissions.administrator:
        return await ctx.send("Só administradores podem fazer o Manel esquecer tudo!")
    mem = carregar_memoria()
    mem["fatos"] = []
    salvar_memoria(mem)
    await ctx.send("🧹 Memória limpa! O Manel não sabe mais nada... além da chave da igreja.")

# ════════════════════════════════════════════════════════════
#  AJUDA
# ════════════════════════════════════════════════════════════

bot.remove_command("help")

@bot.command(aliases=["help", "ajuda"])
async def comandos(ctx):
    embed = discord.Embed(
        title="🤖 Manel Bot — Comandos Completos",
        description="O guardião da chave da igreja tá aqui pra ajudar (mal).",
        color=0x7289DA,
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="🎵 Música", value=(
        "`!play <nome/link>` — Toca do YouTube\n"
        "`!fila` — Vê a fila\n"
        "`!skip` · `!pause` · `!resume` · `!stop`\n"
        "`!volume <0-100>`"
    ), inline=False)
    embed.add_field(name="🤖 IA & Chat", value=(
        "`!manel <pergunta>` — Conversa com a IA\n"
        "`!manel` + imagem — Analisa a imagem\n"
        "`!analisa` + imagem — Análise detalhada*"
    ), inline=False)
    embed.add_field(name="🔊 Voz na Call", value=(
        "`!falar <texto>` — Manel fala na call (TTS)\n"
        "`!pv <pergunta>` — Pergunta + resposta em voz\n"
        "Também reage a: `ok manel <pergunta>` no chat"
    ), inline=False)
    embed.add_field(name="🎨 Imagens", value=(
        "`!imagem <descrição>` — Gera imagem com IA\n"
        "`!analisa` + imagem anexada — Analisa*"
    ), inline=False)
    embed.add_field(name="😂 Diversão", value=(
        "`!piada` · `!jokenpo p/p/t` · `!manelize <texto>`\n"
        "`!dado <lados>`"
    ), inline=False)
    embed.add_field(name="🧠 Memória", value=(
        "`!lembrar <fato>` — Ensina algo ao Manel\n"
        "`!memoria` — Ver o que ele sabe\n"
        "`!esquece` — Apagar memória (admin)"
    ), inline=False)
    embed.set_footer(text="* requer OPENAI_API_KEY configurada")
    await ctx.send(embed=embed)

# ════════════════════════════════════════════════════════════
#  EVENTOS
# ════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    print(f"[OK] Manel está online como {bot.user} ({bot.user.id})")
    print(f"[CFG] GROQ={bool(GROQ_API_KEY)} | OPENAI={bool(OPENAI_API_KEY)} | "
          f"ELEVENLABS={bool(ELEVENLABS_KEY)} | FAL={bool(FAL_KEY)}")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="a chave da igreja 🔑"
    ))

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    await bot.process_commands(message)

    content_lower = message.content.lower().strip()

    # ── Trigger: "ok manel" ou menção direta ─────────────────
    mencionado = bot.user in message.mentions
    frase_ok   = content_lower.startswith("ok manel")

    if (mencionado or frase_ok) and not content_lower.startswith("!"):
        # Extrai a pergunta após "ok manel"
        if frase_ok:
            pergunta = message.content[8:].strip()
        else:
            pergunta = message.content.replace(f"<@{bot.user.id}>", "").strip()

        if not pergunta:
            pergunta = "Oi, tudo bem?"

        # Verifica se há imagem anexa
        imagem_url = None
        if message.attachments:
            att = message.attachments[0]
            if att.content_type and att.content_type.startswith("image"):
                imagem_url = att.url

        async with message.channel.typing():
            resposta = await responder_manel(message.channel.id, pergunta, imagem_url)

        await message.reply(f"🤖 {resposta[:1800]}")

        # Se o autor estiver num canal de voz, fala também
        if message.author.voice and message.guild:
            vc = message.guild.voice_client
            if vc is None:
                try:
                    vc = await message.author.voice.channel.connect()
                except Exception:
                    vc = None
            if vc:
                await falar_na_call(vc, resposta[:400])

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Faltou argumento. Use `!ajuda` pra ver como usar.")
    elif isinstance(error, commands.CommandNotFound):
        pass   # ignora silenciosamente
    else:
        print(f"[ERR] {ctx.command}: {error}")
        traceback.print_exc()

# ════════════════════════════════════════════════════════════
#  INICIALIZAÇÃO
# ════════════════════════════════════════════════════════════

if not BOT_TOKEN:
    print("❌ BOT_TOKEN não configurado! Defina a variável de ambiente.")
    sys.exit(1)

bot.run(BOT_TOKEN)
