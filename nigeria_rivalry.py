#!/usr/bin/env python3
"""Nigerian Regional Rivalry Simulator - A stat-based competition game."""

import random

REGIONS = {
    "Hausa-Fulani (North)": {
        "states": ["Kano", "Katsina", "Borno", "Jigawa", "Yobe", "Sokoto", "Zamfara", "Kebbi", "Niger"],
        "names": ["Mohammed", "Abdullahi", "Sani", "Musa", "Ibrahim", "Bukar", "Ali", "Umar", "Lawal"],
        "strengths": ["farming", "trade", "herding"],
        "rival": "Yoruba (SW)",
    },
    "Yoruba (SW)": {
        "states": ["Lagos", "Oyo", "Ogun", "Osun", "Ekiti", "Ondo"],
        "names": ["Ade", "Taiwo", "Kehinde", "Segun", "Dayo", "Olu", "Bose", "Morenike"],
        "strengths": ["commerce", "education", "arts"],
        "rival": "Hausa-Fulani (North)",
    },
    "Igbo (SE)": {
        "states": ["Anambra", "Imo", "Enugu", "Abia", "Ebonyi", "Delta"],
        "names": ["Chukwuemeka", "Ngozi", "Nneka", "Obiora", "Emeka", "Uzoma", "Obinna"],
        "strengths": ["business", "innovation", "education"],
        "rival": "Hausa-Fulani (North)",
    },
    "Niger Delta (SS)": {
        "states": ["Rivers", "Bayelsa", "Akwa Ibom", "Cross River", "Edo"],
        "names": ["Oke", "Chukwuemeka", "Prince", "Wokoma", "Utibe", "Effiong", "Idara"],
        "strengths": ["oil", "fishing", "trading"],
        "rival": "Yoruba (SW)",
    },
    "Middle Belt": {
        "states": ["Benue", "Plateau", "Nasarawa", "Kwara", "Kogi"],
        "names": ["Terkaa", "Terna", "Joseph", "Emmanuel", "Ishaya", "Luka", "Ali", "Ade"],
        "strengths": ["farming", "mining", "diplomacy"],
        "rival": None,
    },
}

OCCUPATIONS = [
    "Trader", "Engineer", "Teacher", "Doctor", "Farmer", "Driver",
    "Business Owner", "Student", "Nurse", "Accountant", "Civil Servant",
    "Tailor", "Mechanic", "Chef", "Artist", "Police Officer", "Pastor", "Footballer"
]

SKILLS = {
    "strength": ["farming", "trading", "negotiating", "labor"],
    "intelligence": ["studying", "innovating", "planning", "analyzing"],
    "charisma": ["persuading", "leading", "entertaining", "inspiring"],
}

EVENTS = [
    {"name": "Local Festival", "stat": "charisma", "gain": 15, "desc": "Won the dance competition!"},
    {"name": "Business Deal", "stat": "intelligence", "gain": 20, "desc": "Closed a major deal!"},
    {"name": "Farm Harvest", "stat": "strength", "gain": 15, "desc": " bumper harvest!"},
    {"name": "Robbery", "stat": "strength", "loss": 10, "desc": "Lost goods to thieves."},
    {"name": "Sickness", "stat": "strength", "loss": 15, "desc": "Fell ill for a week."},
    {"name": "Scam", "stat": "intelligence", "loss": 10, "desc": "Got scammed by a con artist."},
    {"name": "Promotion", "stat": "charisma", "gain": 20, "desc": "Got promoted at work!"},
    {"name": "Accident", "stat": "strength", "loss": 20, "desc": "Had an accident."},
    {"name": "Wedding", "stat": "charisma", "gain": 10, "desc": "Attended a lavish wedding."},
    {"name": "Exam Results", "stat": "intelligence", "gain": 15, "desc": "Passed with flying colors!"},
]

def create_character(region_name):
    """Create a character from a specific region."""
    region = REGIONS[region_name]
    return {
        "name": random.choice(region["names"]),
        "region": region_name,
        "state": random.choice(region["states"]),
        "strength": random.randint(30, 80),
        "intelligence": random.randint(30, 80),
        "charisma": random.randint(30, 80),
        "occupation": random.choice(OCCUPATIONS),
        "wins": 0,
    }

def stat_bar(value, max_val=100, length=8):
    """Create a text bar for a stat."""
    filled = int((value / max_val) * length)
    return "▰" * filled + "▱" * (length - filled)

def print_character(char, show_stats=True):
    """Print character info."""
    print(f"  👤 {char['name']} ({char['region']})")
    print(f"     📍 {char['state']} | 💼 {char['occupation']}")
    if show_stats:
        print(f"     💪 {stat_bar(char['strength'])} {char['strength']}")
        print(f"     🧠 {stat_bar(char['intelligence'])} {char['intelligence']}")
        print(f"     🎭 {stat_bar(char['charisma'])} {char['charisma']}")
        print(f"     🏆 Wins: {char['wins']}")

def get_rivalry_bonus(char1, char2):
    """Calculate rivalry bonus."""
    r1 = REGIONS[char1["region"]]
    r2 = REGIONS[char2["region"]]
    
    if r1["rival"] == char2["region"]:
        return 20, "RIVALRY FUELED! 🔥"
    elif r2["rival"] == char1["region"]:
        return 20, "RIVALRY FUELED! 🔥"
    return 0, ""

def battle(char1, char2):
    """Simulate a battle between two characters."""
    print("\n" + "=" * 50)
    print("  ⚔️  RIVALRY MATCHUP  ⚔️")
    print("=" * 50)
    print()
    print_character(char1)
    print()
    print_character(char2)
    print()
    print("-" * 50)
    
    # Check for rivalry
    bonus, rivalry_msg = get_rivalry_bonus(char1, char2)
    if bonus > 0:
        print(f"  {rivalry_msg}")
        print()
    
    # Random event
    event = random.choice(EVENTS)
    print(f"  📰 EVENT: {event['name']}")
    print(f"     {event['desc']}")
    
    # Determine winner based on stat + randomness
    if event["stat"] == "strength":
        c1_score = char1["strength"] + random.randint(-10, 20)
        c2_score = char2["strength"] + random.randint(-10, 20)
        stat_name = "Strength"
    elif event["stat"] == "intelligence":
        c1_score = char1["intelligence"] + random.randint(-10, 20)
        c2_score = char2["intelligence"] + random.randint(-10, 20)
        stat_name = "Intelligence"
    else:
        c1_score = char1["charisma"] + random.randint(-10, 20)
        c2_score = char2["charisma"] + random.randint(-10, 20)
        stat_name = "Charisma"
    
    # Apply rivalry bonus
    c1_score += bonus
    c2_score += bonus
    
    print(f"  🎯 Test: {stat_name}")
    print(f"     {char1['name']}: {c1_score} vs {char2['name']}: {c2_score}")
    
    print("-" * 50)
    
    if c1_score > c2_score:
        print(f"  🏆 {char1['name']} WINS!")
        char1["wins"] += 1
        winner = char1
    elif c2_score > c1_score:
        print(f"  🏆 {char2['name']} WINS!")
        char2["wins"] += 1
        winner = char2
    else:
        print("  ⚖️  IT'S A DRAW!")
        winner = None
    
    print("=" * 50)
    return winner

def main():
    print("🇳🇬" * 20)
    print("  NIGERIAN REGIONAL RIVALRY SIMULATOR")
    print("🇳🇬" * 20)
    print()
    print("Choose your region:")
    for i, region in enumerate(REGIONS.keys(), 1):
        rival = REGIONS[region]["rival"]
        rival_str = f" (Rival: {rival})" if rival else ""
        print(f"  {i}. {region}{rival_str}")
    print()
    
    try:
        choice = int(input("Enter region (1-5): ")) - 1
        player_region = list(REGIONS.keys())[choice]
    except (ValueError, IndexError):
        player_region = random.choice(list(REGIONS.keys()))
    
    player = create_character(player_region)
    
    print(f"\nYou chose: {player_region}")
    print(f"Character created: {player['name']}")
    print()
    
    # Generate opponent from rival region if possible
    rival_region = REGIONS[player_region].get("rival")
    if rival_region:
        opponent = create_character(rival_region)
    else:
        opponent = create_character(random.choice(list(REGIONS.keys())))
    
    # Battle!
    battle(player, opponent)
    
    print("\nPlay again? (y/n): ", end="")
    if input().lower() == "y":
        main()

if __name__ == "__main__":
    main()
