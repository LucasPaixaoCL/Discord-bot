import os
import re
import json
import time
import threading
import discord
from discord.ext import commands
from discord import app_commands
from flask import Flask

# Importa a base de dados de 1025 Pokémons gerada
try:
    from pokemon_data import POKEMON_LIST, POKEMON_BY_ID, POKEMON_BY_NAME, RARE_POKEMON_IDS
except ImportError:
    print("⚠️ Aviso: pokemon_data.py não encontrado. Execute generate_db.py primeiro.")
    POKEMON_LIST = []
    POKEMON_BY_ID = {}
    POKEMON_BY_NAME = {}
    RARE_POKEMON_IDS = set()

# ---------------------------------------------------------
# 1. SERVIDOR WEB FLASK (Health Check para Render / UptimeRobot)
# ---------------------------------------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Bot Pokétwo Notifier & Wishlist está ONLINE e ativo!", 200

@app.route('/ping')
def ping():
    return "pong", 200

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    server_thread = threading.Thread(target=run_web_server)
    server_thread.daemon = True
    server_thread.start()

# ---------------------------------------------------------
# 2. SISTEMA DE ARQUIVOS (Wishlist e Estatísticas)
# ---------------------------------------------------------
WISHLIST_FILE = "wishlist.json"
STATS_FILE = "stats.json"

def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Erro ao carregar {filepath}: {e}")
    return default

def save_json(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Erro ao salvar {filepath}: {e}")

# Wishlist formato: { "user_id_str": ["Pikachu", "Charizard"] }
wishlists = load_json(WISHLIST_FILE, {})

# Stats formato: { "total_spawns": 0, "rare_spawns": 0, "shiny_spawns": 0, "hints_solved": 0, "wishlist_pings": 0 }
stats_data = load_json(STATS_FILE, {
    "total_spawns": 0,
    "rare_spawns": 0,
    "shiny_spawns": 0,
    "hints_solved": 0,
    "wishlist_pings": 0
})

def increment_stat(key):
    stats_data[key] = stats_data.get(key, 0) + 1
    save_json(STATS_FILE, stats_data)

# ---------------------------------------------------------
# 3. HELPER DE HINT SOLVER & DETECÇÃO DE IMAGEM
# ---------------------------------------------------------
def solve_hint(hint_text: str):
    """
    Decodifica o formato de hint do Pokétwo (ex: "The pokémon is P_k_c_u.")
    e compara com a lista de Pokémons conhecidos.
    """
    match = re.search(r"the pokémon is ([^\.\n]+)", hint_text, re.IGNORECASE)
    if not match:
        return []
    
    raw_pattern = match.group(1).strip()
    regex_pattern = "^"
    for char in raw_pattern:
        if char == '_':
            regex_pattern += r"[a-zA-Z0-9]"
        else:
            regex_pattern += re.escape(char)
    regex_pattern += r"$"

    try:
        compiled = re.compile(regex_pattern, re.IGNORECASE)
    except Exception:
        return []
    
    matches = [poke["name"] for poke in POKEMON_LIST if compiled.match(poke["name"])]
    return matches

def extract_pokemon_id_from_url(url: str):
    """
    Extrai o ID do Pokémon da URL da imagem do Pokétwo
    ex: https://cdn.poketwo.net/images/25.png -> 25
    """
    if not url:
        return None
    m = re.search(r'/(\d+)\.(png|jpg|jpeg|webp)', url, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None

def get_users_with_pokemon_in_wishlist(pokemon_name: str):
    """Retorna lista de IDs de usuários (mencionais <@id>) que têm o pokémon na wishlist."""
    target = pokemon_name.lower()
    user_ids = []
    for user_id, user_list in wishlists.items():
        if any(p.lower() == target for p in user_list):
            user_ids.append(user_id)
    return user_ids

# ---------------------------------------------------------
# 4. CONFIGURAÇÃO DO BOT DISCORD
# ---------------------------------------------------------
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", 1540050291947348140))
ROLE_ID = int(os.environ.get("ROLE_ID", 1540052647900487690))
POKETWO_BOT_ID = int(os.environ.get("POKETWO_BOT_ID", 716390085896962058))

START_TIME = time.time()

intents = discord.Intents.default()
intents.message_content = True 

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Bot logado com sucesso como: {bot.user}")
    print(f"📌 Monitorando canal ID: {CHANNEL_ID}")
    print(f"🔔 Pingando cargo ID: {ROLE_ID}")
    try:
        synced = await bot.tree.sync()
        print(f"⚡ Sincronizados {len(synced)} comandos Slash com sucesso!")
    except Exception as e:
        print(f"❌ Erro ao sincronizar comandos Slash: {e}")

# ---------------------------------------------------------
# 5. PROCESSAMENTO DE MENSAGENS (Pokétwo, Hints, Spawns, Wishlist)
# ---------------------------------------------------------
@bot.event
async def on_message(message):
    # Evita que o bot responda a si mesmo
    if message.author == bot.user:
        return

    # Processa comandos prefixados se houver
    await bot.process_commands(message)

    # Só atua no canal de spawn configurado
    if message.channel.id != CHANNEL_ID:
        return

    # Garante que a mensagem venha do Pokétwo
    if message.author.id == POKETWO_BOT_ID:
        
        # --- A. DETECÇÃO DE HINT DO POKÉTWO ---
        if "the pokémon is" in message.content.lower():
            matches = solve_hint(message.content)
            if matches:
                increment_stat("hints_solved")
                matched_name = matches[0] if len(matches) == 1 else ", ".join(matches)
                
                # Resposta de Hint Resolvido
                embed_hint = discord.Embed(
                    title="💡 Hint Resolvido!",
                    description=f"O Pokémon é: **{matched_name}**",
                    color=discord.Color.blue()
                )
                await message.channel.send(embed=embed_hint)

                # Checa Wishlist para Pokémons encontrados no hint
                for p_name in matches:
                    users = get_users_with_pokemon_in_wishlist(p_name)
                    if users:
                        increment_stat("wishlist_pings")
                        mentions = " ".join([f"<@{uid}>" for uid in users])
                        await message.channel.send(
                            f"🎯 {mentions} O Pokémon **{p_name}** que está na sua Wishlist foi identificado pelo Hint!"
                        )
            return

        # --- B. DETECÇÃO DE SPAWN DE POKÉMON ---
        is_spawn = False
        embed_image_url = None
        
        if "a wild pokémon has appeared!" in message.content.lower():
            is_spawn = True
        
        for embed in message.embeds:
            if embed.title and "a wild pokémon has appeared!" in embed.title.lower():
                is_spawn = True
            elif embed.description and "guess the pokémon" in embed.description.lower():
                is_spawn = True
            
            if embed.image and embed.image.url:
                embed_image_url = embed.image.url

        if is_spawn:
            increment_stat("total_spawns")
            print("🚨 Spawn detectado! Enviando notificação...")
            
            # Ping padrão do cargo configurado
            await message.channel.send(f"<@&{ROLE_ID}> 🚨 **Um novo Pokémon selvagem apareceu!**")

            # --- C. DETECÇÃO DE SHINY ---
            if "✨" in message.content or "shiny" in message.content.lower():
                increment_stat("shiny_spawns")
                await message.channel.send("✨ **POKÉMON SHINY DETECTADO NO SPAWN!** ✨")

            # --- D. DETECÇÃO POR URL DA IMAGEM (Raridade & Wishlist Imediata) ---
            if embed_image_url:
                poke_id = extract_pokemon_id_from_url(embed_image_url)
                if poke_id and poke_id in POKEMON_BY_ID:
                    poke_name = POKEMON_BY_ID[poke_id]
                    
                    # 1. Filtro de Raridade (Lendário / Mítico / Ultra Beast)
                    if poke_id in RARE_POKEMON_IDS:
                        increment_stat("rare_spawns")
                        embed_rare = discord.Embed(
                            title="🌟 POKÉMON RARO DETECTADO!",
                            description=f"Um Pokémon de alta raridade (**{poke_name}**) apareceu no canal!",
                            color=discord.Color.gold()
                        )
                        await message.channel.send(content=f"<@&{ROLE_ID}>", embed=embed_rare)

                    # 2. Wishlist no Spawn Imediato
                    users = get_users_with_pokemon_in_wishlist(poke_name)
                    if users:
                        increment_stat("wishlist_pings")
                        mentions = " ".join([f"<@{uid}>" for uid in users])
                        await message.channel.send(
                            f"🎯 {mentions} O Pokémon **{poke_name}** apareceu no spawn e está na sua Wishlist!"
                        )

# ---------------------------------------------------------
# 6. COMANDOS SLASH (/wishlist, /ping, /status, /stats)
# ---------------------------------------------------------

# --- COMANDO /PING ---
@bot.tree.command(name="ping", description="Verifica a latência e tempo de resposta do bot.")
async def slash_ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 **Pong!** Latência da API: `{latency}ms`", ephemeral=True)

# --- COMANDO /STATUS ---
@bot.tree.command(name="status", description="Exibe o status atual e painel de informações do bot.")
async def slash_status(interaction: discord.Interaction):
    uptime_seconds = int(time.time() - START_TIME)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"

    embed = discord.Embed(
        title="🤖 Status do Bot Notifier",
        color=discord.Color.green()
    )
    embed.add_field(name="Status HTTP Server", value="🟢 Online (24/7 Keep-Alive)", inline=False)
    embed.add_field(name="Tempo de Atividade (Uptime)", value=f"`{uptime_str}`", inline=True)
    embed.add_field(name="Latência API", value=f"`{round(bot.latency * 1000)}ms`", inline=True)
    embed.add_field(name="Canal Monitorado", value=f"<#{CHANNEL_ID}>", inline=False)
    embed.add_field(name="Cargo Notificado", value=f"<@&{ROLE_ID}>", inline=False)
    embed.set_footer(text="Bot desenvolvido para o Mestre Lucas")

    await interaction.response.send_message(embed=embed)

# --- COMANDO /STATS ---
@bot.tree.command(name="stats", description="Exibe estatísticas de spawns, raros e hints resolvidos no servidor.")
async def slash_stats(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📊 Estatísticas do Servidor",
        color=discord.Color.purple()
    )
    embed.add_field(name="Total de Spawns", value=f"**{stats_data.get('total_spawns', 0)}**", inline=True)
    embed.add_field(name="Spawns Raros", value=f"⭐ **{stats_data.get('rare_spawns', 0)}**", inline=True)
    embed.add_field(name="Spawns Shiny", value=f"✨ **{stats_data.get('shiny_spawns', 0)}**", inline=True)
    embed.add_field(name="Hints Resolvidos", value=f"💡 **{stats_data.get('hints_solved', 0)}**", inline=True)
    embed.add_field(name="Alertas de Wishlist", value=f"🎯 **{stats_data.get('wishlist_pings', 0)}**", inline=True)

    await interaction.response.send_message(embed=embed)

# --- GRUPO DE COMANDOS /WISHLIST ---
wishlist_group = app_commands.Group(name="wishlist", description="Gerencie sua Lista de Desejos de Pokémons.")

@wishlist_group.command(name="add", description="Adiciona um Pokémon à sua Lista de Desejos.")
@app_commands.describe(pokemon="Nome do Pokémon (ex: Pikachu, Charizard)")
async def wishlist_add(interaction: discord.Interaction, pokemon: str):
    user_id_str = str(interaction.user.id)
    search_name = pokemon.strip().lower()
    
    # Valida nome do Pokémon contra a base de 1025 Pokémons
    official_name = None
    if search_name in POKEMON_BY_NAME:
        # Encontra nome com capitalização oficial
        for p in POKEMON_LIST:
            if p["name"].lower() == search_name:
                official_name = p["name"]
                break
    else:
        official_name = pokemon.strip().capitalize()

    user_list = wishlists.get(user_id_str, [])
    if any(p.lower() == search_name for p in user_list):
        await interaction.response.send_message(
            f"⚠️ **{official_name}** já está na sua wishlist!", ephemeral=True
        )
        return

    if len(user_list) >= 20:
        await interaction.response.send_message(
            "⚠️ Você atingiu o limite máximo de 20 Pokémons na wishlist!", ephemeral=True
        )
        return

    user_list.append(official_name)
    wishlists[user_id_str] = user_list
    save_json(WISHLIST_FILE, wishlists)

    await interaction.response.send_message(
        f"✅ **{official_name}** foi adicionado à sua wishlist com sucesso!", ephemeral=True
    )

@wishlist_group.command(name="remove", description="Remove um Pokémon da sua Lista de Desejos.")
@app_commands.describe(pokemon="Nome do Pokémon a ser removido")
async def wishlist_remove(interaction: discord.Interaction, pokemon: str):
    user_id_str = str(interaction.user.id)
    search_name = pokemon.strip().lower()

    user_list = wishlists.get(user_id_str, [])
    new_list = [p for p in user_list if p.lower() != search_name]

    if len(new_list) == len(user_list):
        await interaction.response.send_message(
            f"⚠️ **{pokemon}** não foi encontrado na sua wishlist.", ephemeral=True
        )
        return

    wishlists[user_id_str] = new_list
    save_json(WISHLIST_FILE, wishlists)

    await interaction.response.send_message(
        f"🗑️ **{pokemon.capitalize()}** foi removido da sua wishlist!", ephemeral=True
    )

@wishlist_group.command(name="list", description="Exibe todos os Pokémons cadastrados na sua wishlist.")
async def wishlist_list(interaction: discord.Interaction):
    user_id_str = str(interaction.user.id)
    user_list = wishlists.get(user_id_str, [])

    if not user_list:
        await interaction.response.send_message(
            "📋 Sua wishlist está vazia! Use `/wishlist add <pokémon>` para cadastrar.", ephemeral=True
        )
        return

    poke_formatted = "\n".join([f"• **{p}**" for p in user_list])
    embed = discord.Embed(
        title=f"📋 Wishlist de {interaction.user.display_name}",
        description=f"Total: **{len(user_list)}/20** Pokémons\n\n{poke_formatted}",
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@wishlist_group.command(name="clear", description="Limpa toda a sua wishlist.")
async def wishlist_clear(interaction: discord.Interaction):
    user_id_str = str(interaction.user.id)
    if user_id_str in wishlists:
        wishlists[user_id_str] = []
        save_json(WISHLIST_FILE, wishlists)
    await interaction.response.send_message("🧹 Sua wishlist foi limpa!", ephemeral=True)

# Adiciona o grupo de comandos /wishlist ao bot
bot.tree.add_command(wishlist_group)

# ---------------------------------------------------------
# 7. INICIALIZAÇÃO
# ---------------------------------------------------------
if __name__ == "__main__":
    keep_alive()
    if not DISCORD_TOKEN:
        print("❌ ERRO: O Token do Discord não foi configurado nas Variáveis de Ambiente (DISCORD_TOKEN).")
    else:
        bot.run(DISCORD_TOKEN)