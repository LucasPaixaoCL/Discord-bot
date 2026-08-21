import urllib.request
import json
import re

print("Baixando lista de Pokémon da PokéAPI...")
url = "https://pokeapi.co/api/v2/pokemon-species?limit=1025"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})

pokemon_list = []
try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        for item in data['results']:
            # Pega o ID da URL ex: https://pokeapi.co/api/v2/pokemon-species/25/
            m = re.search(r'/(\d+)/$', item['url'])
            if m:
                poke_id = int(m.group(1))
                # Formata nome ex: "ho-oh" -> "Ho-Oh", "nidoran-m" -> "Nidoran♂" ou "Nidoran"
                raw_name = item['name'].capitalize()
                pokemon_list.append({'id': poke_id, 'name': raw_name})
    print(f"Sucesso! {len(pokemon_list)} Pokémons baixados.")
except Exception as e:
    print(f"Erro ao baixar da API: {e}")

# Lista de IDs de Lendários, Míticos e Ultra Beasts conhecidos
LEGENDARIES_AND_RARES = {
    # Gen 1
    144, 145, 146, 150, 151,
    # Gen 2
    243, 244, 245, 249, 250, 251,
    # Gen 3
    377, 378, 379, 380, 381, 382, 383, 384, 385, 386,
    # Gen 4
    480, 481, 482, 483, 484, 485, 486, 487, 488, 489, 490, 491, 492, 493, 494,
    # Gen 5
    638, 639, 640, 641, 642, 643, 644, 645, 646, 647, 648, 649,
    # Gen 6
    716, 717, 718, 719, 720, 721,
    # Gen 7 (Incluindo Ultra Beasts)
    772, 773, 785, 786, 787, 788, 789, 790, 791, 792, 793, 794, 795, 796, 797, 798, 799, 800, 801, 802, 803, 804, 805, 806, 807, 808, 809,
    # Gen 8
    888, 889, 890, 891, 892, 893, 894, 895, 896, 897, 898, 905,
    # Gen 9
    984, 985, 986, 987, 988, 989, 990, 991, 992, 993, 994, 995, 1001, 1002, 1003, 1004, 1007, 1008, 1014, 1015, 1016, 1017, 1024, 1025
}

# Salva arquivo python com os dados
with open("pokemon_data.py", "w", encoding="utf-8") as f:
    f.write("# Arquivo gerado automaticamente com dados de Pokémons\n\n")
    f.write(f"POKEMON_LIST = {json.dumps(pokemon_list, ensure_ascii=False, indent=2)}\n\n")
    f.write(f"POKEMON_BY_ID = {{item['id']: item['name'] for item in POKEMON_LIST}}\n")
    f.write(f"POKEMON_BY_NAME = {{item['name'].lower(): item['id'] for item in POKEMON_LIST}}\n")
    f.write(f"RARE_POKEMON_IDS = {set(LEGENDARIES_AND_RARES)}\n")

print("Gerado pokemon_data.py com sucesso!")
