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

# Helper para normalizar nomes (remove pontuações e espaços)
def normalize_name(name: str):
    return re.sub(r'[^a-z0-9]', '', name.lower())

POKEMON_NORMALIZED_MAP = {normalize_name(p["name"]): p["name"] for p in POKEMON_LIST}

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

wishlists = load_json(WISHLIST_FILE, {})

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

def generate_hint_pattern(pokemon_name: str):
    """Gera uma string de hint oculta para testes (ex: Pikachu -> P_k_c_u)"""
    chars = list(pokemon_name)
    for i in range(len(chars)):
        if i % 2 == 1 and chars[i].isalnum():
            chars[i] = '_'
    return "".join(chars)

def extract_pokemon_id_from_url(url: str):
    if not url:
        return None
    m = re.search(r'/(\d+)\.(png|jpg|jpeg|webp)', url, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None

def get_users_with_pokemon_in_wishlist(pokemon_name: str):
    target_norm = normalize_name(pokemon_name)
    user_ids = []
    for user_id, user_list in wishlists.items():
        if any(normalize_name(p) == target_norm for p in user_list):
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
# 5. PROCESSAMENTO DE NOTIFICAÇÃO ÚNICA DE SPAWN/HINT
# ---------------------------------------------------------
async def process_spawn_notification(channel, content: str, embed_image_url: str = None, force_poke_name: str = None, is_shiny_override: bool = False):
    """
    Função centralizada para notificação de Spawns com prioridade estrita:
    Shiny > Raro > Comum, incluindo marcas da Wishlist sem duplicação de mensagens.
    """
    increment_stat("total_spawns")
    
    is_shiny = is_shiny_override or ("✨" in content or "shiny" in content.lower())
    is_rare = False
    poke_name = force_poke_name
    wishlist_users = []

    # Se recebeu URL de imagem do embed, descobre o ID e Nome
    if embed_image_url and not poke_name:
        poke_id = extract_pokemon_id_from_url(embed_image_url)
        if poke_id and poke_id in POKEMON_BY_ID:
            poke_name = POKEMON_BY_ID[poke_id]
            if poke_id in RARE_POKEMON_IDS:
                is_rare = True

    # Se o nome do pokémon foi forçado no teste, verifica se é raro
    if poke_name:
        norm = normalize_name(poke_name)
        if norm in POKEMON_NORMALIZED_MAP:
            poke_id = POKEMON_BY_NAME.get(norm)
            if poke_id and poke_id in RARE_POKEMON_IDS:
                is_rare = True
        wishlist_users = get_users_with_pokemon_in_wishlist(poke_name)

    wishlist_tag = ""
    if wishlist_users:
        increment_stat("wishlist_pings")
        wishlist_tag = " 🎯 " + " ".join([f"<@{uid}>" for uid in wishlist_users])

    # SISTEMA DE NOTIFICAÇÃO ÚNICA COM HIERARQUIA
    if is_shiny:
        increment_stat("shiny_spawns")
        embed_shiny = discord.Embed(
            title="✨ POKÉMON SHINY DETECTADO! ✨",
            description=f"Um Pokémon **SHINY** selvagem acabou de aparecer!{wishlist_tag}",
            color=discord.Color.from_rgb(255, 215, 0)
        )
        await channel.send(content=f"<@&{ROLE_ID}>", embed=embed_shiny)

    elif is_rare:
        increment_stat("rare_spawns")
        embed_rare = discord.Embed(
            title="🌟 POKÉMON RARO DETECTADO!",
            description=f"Um Pokémon raro (**{poke_name or 'Lendário/Mítico'}**) apareceu no canal!{wishlist_tag}",
            color=discord.Color.purple()
        )
        await channel.send(content=f"<@&{ROLE_ID}>", embed=embed_rare)

    else:
        msg_content = f"<@&{ROLE_ID}> 🚨 **Um novo Pokémon selvagem apareceu!**{wishlist_tag}"
        await channel.send(msg_content)

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    await bot.process_commands(message)

    if message.channel.id != CHANNEL_ID:
        return

    if message.author.id == POKETWO_BOT_ID:
        
        # --- A. DETECÇÃO DE HINT DO POKÉTWO ---
        if "the pokémon is" in message.content.lower():
            matches = solve_hint(message.content)
            if matches:
                increment_stat("hints_solved")
                matched_name = matches[0] if len(matches) == 1 else ", ".join(matches)
                
                wishlist_mentions = []
                for p_name in matches:
                    u_ids = get_users_with_pokemon_in_wishlist(p_name)
                    for uid in u_ids:
                        if f"<@{uid}>" not in wishlist_mentions:
                            wishlist_mentions.append(f"<@{uid}>")

                wishlist_text = ""
                if wishlist_mentions:
                    increment_stat("wishlist_pings")
                    wishlist_text = f"\n🎯 **Wishlist:** {' '.join(wishlist_mentions)} este Pokémon está na sua lista!"

                embed_hint = discord.Embed(
                    title="💡 Hint Resolvido!",
                    description=f"O Pokémon é: **{matched_name}**{wishlist_text}",
                    color=discord.Color.blue()
                )
                await message.channel.send(embed=embed_hint)
            return

        # --- B. DETECÇÃO DE SPAWN ---
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
            await process_spawn_notification(
                channel=message.channel,
                content=message.content,
                embed_image_url=embed_image_url
            )

# ---------------------------------------------------------
# 6. COMANDOS SLASH (/wishlist, /ping, /status, /stats, /testspawn)
# ---------------------------------------------------------

@bot.tree.command(name="ping", description="Verifica a latência do bot.")
async def slash_ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 **Pong!** Latência da API: `{latency}ms`", ephemeral=True)

@bot.tree.command(name="status", description="Exibe o status atual do bot.")
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
    embed.add_field(name="Uptime", value=f"`{uptime_str}`", inline=True)
    embed.add_field(name="Latência API", value=f"`{round(bot.latency * 1000)}ms`", inline=True)
    embed.add_field(name="Canal Monitorado", value=f"<#{CHANNEL_ID}>", inline=False)
    embed.add_field(name="Cargo Notificado", value=f"<@&{ROLE_ID}>", inline=False)
    embed.set_footer(text="Bot desenvolvido para o Mestre Lucas")

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="stats", description="Exibe estatísticas de spawns e hints.")
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

# --- COMANDO DE TESTE EXCLUSIVO DE ADMINISTRADOR ---
@bot.tree.command(name="testspawn", description="[ADM] Simula eventos do Pokétwo para testar notificações e Wishlist.")
@app_commands.describe(
    tipo="Escolha o tipo de teste a ser simulado",
    pokemon="Nome de um Pokémon opcional para testar (ex: Pikachu, Rayquaza)"
)
@app_commands.choices(tipo=[
    app_commands.Choice(name="1. Spawn Comum", value="comum"),
    app_commands.Choice(name="2. Spawn Raro (Lendário/Mítico)", value="raro"),
    app_commands.Choice(name="3. Spawn Shiny", value="shiny"),
    app_commands.Choice(name="4. Pokétwo Hint", value="hint")
])
@app_commands.default_permissions(administrator=True)
async def slash_testspawn(interaction: discord.Interaction, tipo: app_commands.Choice[str], pokemon: str = None):
    # Trava de Segurança: Apenas Administradores do servidor podem executar
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Apenas Administradores do servidor podem usar este comando de teste!", ephemeral=True)
        return

    channel = bot.get_channel(CHANNEL_ID) or interaction.channel
    test_type = tipo.value
    target_poke = pokemon.strip() if pokemon else None

    # Resposta ephemeral apenas para o Admin confirmando que o teste foi iniciado
    await interaction.response.send_message(
        f"🧪 **[Simulação ADM]** Disparando teste do tipo `{test_type}` (Pokémon: `{target_poke or 'Padrão'}`)...",
        ephemeral=True
    )

    if test_type == "comum":
        chosen_poke = target_poke or "Pidgey"
        await process_spawn_notification(channel=channel, content="A wild pokémon has appeared!", force_poke_name=chosen_poke)

    elif test_type == "raro":
        chosen_poke = target_poke or "Rayquaza"
        await process_spawn_notification(channel=channel, content="A wild pokémon has appeared!", force_poke_name=chosen_poke)

    elif test_type == "shiny":
        chosen_poke = target_poke or "Pikachu"
        await process_spawn_notification(channel=channel, content="✨ A wild shiny pokémon has appeared!", force_poke_name=chosen_poke, is_shiny_override=True)

    elif test_type == "hint":
        chosen_poke = target_poke or "Pikachu"
        # Garante que o nome exista ou usa Pikachu
        norm = normalize_name(chosen_poke)
        official_name = POKEMON_NORMALIZED_MAP.get(norm, "Pikachu")
        pattern = generate_hint_pattern(official_name)
        hint_msg = f"The pokémon is {pattern}."
        
        matches = solve_hint(hint_msg)
        increment_stat("hints_solved")
        matched_name = matches[0] if matches else official_name

        wishlist_mentions = []
        u_ids = get_users_with_pokemon_in_wishlist(official_name)
        for uid in u_ids:
            if f"<@{uid}>" not in wishlist_mentions:
                wishlist_mentions.append(f"<@{uid}>")

        wishlist_text = ""
        if wishlist_mentions:
            increment_stat("wishlist_pings")
            wishlist_text = f"\n🎯 **Wishlist:** {' '.join(wishlist_mentions)} este Pokémon está na sua lista!"

        embed_hint = discord.Embed(
            title="💡 [TESTE SIMULADO] Hint Resolvido!",
            description=f"O Pokémon é: **{matched_name}**{wishlist_text}",
            color=discord.Color.blue()
        )
        await channel.send(embed=embed_hint)

# --- GRUPO DE COMANDOS /WISHLIST ---
wishlist_group = app_commands.Group(name="wishlist", description="Gerencie sua Lista de Desejos de Pokémons.")

@wishlist_group.command(name="add", description="Adiciona um Pokémon à sua Lista de Desejos.")
@app_commands.describe(pokemon="Nome do Pokémon (ex: Pikachu, Charizard, Rayquaza)")
async def wishlist_add(interaction: discord.Interaction, pokemon: str):
    user_id_str = str(interaction.user.id)
    input_norm = normalize_name(pokemon)
    
    if input_norm not in POKEMON_NORMALIZED_MAP:
        await interaction.response.send_message(
            f"❌ **\"{pokemon}\"** não foi encontrado na Pokédex oficial! Por favor, verifique o nome (em inglês) e tente novamente.",
            ephemeral=True
        )
        return

    official_name = POKEMON_NORMALIZED_MAP[input_norm]
    user_list = wishlists.get(user_id_str, [])

    if any(normalize_name(p) == input_norm for p in user_list):
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
        f"✅ **{official_name}** foi validado e adicionado à sua wishlist com sucesso!", ephemeral=True
    )

@wishlist_group.command(name="remove", description="Remove um Pokémon da sua Lista de Desejos.")
@app_commands.describe(pokemon="Nome do Pokémon a ser removido")
async def wishlist_remove(interaction: discord.Interaction, pokemon: str):
    user_id_str = str(interaction.user.id)
    input_norm = normalize_name(pokemon)

    user_list = wishlists.get(user_id_str, [])
    new_list = [p for p in user_list if normalize_name(p) != input_norm]

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

bot.tree.add_command(wishlist_group)

if __name__ == "__main__":
    keep_alive()
    if not DISCORD_TOKEN:
        print("❌ ERRO: O Token do Discord não foi configurado nas Variáveis de Ambiente (DISCORD_TOKEN).")
    else:
        bot.run(DISCORD_TOKEN)