import os
import threading
import discord
from flask import Flask

# ---------------------------------------------------------
# 1. SERVIDOR WEB HTTP (Para manter o bot 24/7 no Render/UptimeRobot)
# ---------------------------------------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Bot Pokétwo Notifier está ONLINE e funcionando perfeitamente!", 200

@app.route('/ping')
def ping():
    return "pong", 200

def run_web_server():
    # Porta enviada automaticamente pela plataforma de hospedagem (Render usa PORT)
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    server_thread = threading.Thread(target=run_web_server)
    server_thread.daemon = True
    server_thread.start()

# ---------------------------------------------------------
# 2. CONFIGURAÇÕES E CREDENCIAIS
# ---------------------------------------------------------
# Pegamos as variáveis de ambiente ou usamos os valores padrão definidos pelo Mestre Lucas
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", 1540050291947348140))
ROLE_ID = int(os.environ.get("ROLE_ID", 1540052647900487690))
POKETWO_BOT_ID = int(os.environ.get("POKETWO_BOT_ID", 716390085896962058))

# Permissões necessárias para ler mensagens e embeds
intents = discord.Intents.default()
intents.message_content = True 

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"✅ Bot logado com sucesso como: {client.user}")
    print(f"📌 Monitorando canal ID: {CHANNEL_ID}")
    print(f"🔔 Pingando cargo ID: {ROLE_ID}")

@client.event
async def on_message(message):
    # Evita que o próprio bot responda a si mesmo
    if message.author == client.user:
        return

    # Garante que o bot só responda no canal configurado
    if message.channel.id != CHANNEL_ID:
        return

    # Verifica se a mensagem veio do Pokétwo
    if message.author.id == POKETWO_BOT_ID:
        is_spawn = False
        
        # 1. Verifica no texto da mensagem
        if "a wild pokémon has appeared!" in message.content.lower():
            is_spawn = True
        
        # 2. Verifica nos Embeds enviados pelo Pokétwo
        for embed in message.embeds:
            if embed.title and "a wild pokémon has appeared!" in embed.title.lower():
                is_spawn = True
            elif embed.description and "guess the pokémon" in embed.description.lower():
                is_spawn = True

        # Se for um spawn de Pokémon, envia o ping do cargo
        if is_spawn:
            print("🚨 Spawn detectado! Enviando notificação...")
            await message.channel.send(f"<@&{ROLE_ID}> 🚨 **Um novo Pokémon selvagem apareceu!**")

if __name__ == "__main__":
    # Inicia o servidor HTTP em segundo plano
    keep_alive()
    
    # Inicia o bot do Discord
    if not DISCORD_TOKEN:
        print("❌ ERRO: O Token do Discord não foi configurado nas Variáveis de Ambiente (DISCORD_TOKEN).")
    else:
        client.run(DISCORD_TOKEN)