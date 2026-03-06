#!/usr/bin/env python3
"""Random Nigerian name pair generator with simulated game stats."""

import random

NIGERIAN_NAMES = {
    # Northern States (Hausa/Fulani)
    "Kano": ["Mohammed", "Abdullahi", "Sani", "Musa", "Ibrahim"],
    "Katsina": ["Mohammed", "Lawal", "Musa", "Ibrahim"],
    "Borno": ["Mohammed", "Bukar", "Ali", "Umar"],
    "Jigawa": ["Mohammed", "Abdullahi", "Ibrahim"],
    "Yobe": ["Mohammed", "Bukar", "Ali"],
    "Sokoto": ["Mohammed", "Attahiru", "Aliyu"],
    "Zamfara": ["Mohammed", "Ibrahim", "Sani"],
    "Kebbi": ["Mohammed", "Aliyu", "Bala"],
    "Niger": ["Mohammed", "Ibrahim", "Musa"],
    "Kogi": ["Mohammed", "Ali", "Olu"],
    # Middle Belt
    "Benue": ["Terkaa", "Terna", "Joseph", "Emmanuel"],
    "Plateau": ["Ishaya", "Joseph", "Musa"],
    "Nasarawa": ["Mohammed", "Ibrahim", "Luka"],
    "Kwara": ["Mohammed", "Ade", "Ali"],
    # Southwest (Yoruba)
    "Lagos": ["Ade", "Taiwo", "Kehinde", "Segun", "Bose"],
    "Oyo": ["Ade", "Dayo", "Taiwo", "Kehinde"],
    "Ogun": ["Olu", "Segun", "Dayo"],
    "Osun": ["Ade", "Oluwatobi", "Morenike"],
    "Ekiti": ["Ade", "Oluwatobi", "Dayo"],
    "Ondo": ["Olu", "Ade", "Dayo"],
    # Southeast (Igbo)
    "Anambra": ["Chukwuemeka", "Ngozi", "Nneka", "Obiora"],
    "Imo": ["Chukwuemeka", "Ngozi", "Nneka", "Uzoma"],
    "Enugu": ["Chukwuemeka", "Ngozi", "Nneka", "Emeka"],
    "Abia": ["Chukwuemeka", "Ngozi", "Nneka", "Obinna"],
    "Ebonyi": ["Chukwuemeka", "Ngozi", "Sunday"],
    "Delta": ["Oke", "Ejike", "Ngozi"],
    # South-South
    "Rivers": ["Oke", "Chukwuemeka", "Prince"],
    "Bayelsa": ["Oke", "Wokoma", "Soyo"],
    "Akwa Ibom": ["Utibe", "Imo", "Sunday"],
    "Cross River": ["Effiong", "Idara", "Egbe"],
    "Edo": ["Igbe", "Omo", "Ewe"],
}

OCCUPATIONS = [
    "Trader", "Engineer", "Teacher", "Doctor", "Farmer", "Driver",
    "Business Owner", "Student", "Nurse", "Accountant", "Civil Servant",
    "Tailor", "Mechanic", "Chef", "Artist", "Police Officer", "Pastor"
]

def generate_stats():
    """Generate random stats for a character."""
    return {
        "age": random.randint(18, 65),
        "health": random.randint(40, 100),
        "happiness": random.randint(30, 100),
        "wealth": random.randint(1, 100),
        "occupation": random.choice(OCCUPATIONS),
    }

def stat_bar(value, max_val=100, length=10):
    """Create a text bar for a stat."""
    filled = int((value / max_val) * length)
    return "█" * filled + "░" * (length - filled)

def generate_pair():
    """Generate a random matching pair of names from a random state with stats."""
    state = random.choice(list(NIGERIAN_NAMES.keys()))
    names = NIGERIAN_NAMES[state]
    
    if len(names) < 2:
        pair = names + names
    else:
        pair = random.sample(names, 2)
    
    stats1 = generate_stats()
    stats2 = generate_stats()
    
    return state, pair[0], stats1, pair[1], stats2

def print_stats(name, stats):
    """Print stats for a character."""
    print(f"  {name}")
    print(f"    Age: {stats['age']} | Job: {stats['occupation']}")
    print(f"    Health:  {stat_bar(stats['health'])} {stats['health']}")
    print(f"    Happiness: {stat_bar(stats['happiness'])} {stats['happiness']}")
    print(f"    Wealth:  {stat_bar(stats['wealth'])} {stats['wealth']}")

def main():
    print("=" * 50)
    print("  🇳🇬  Nigerian Name Pair Simulator  🇳🇬")
    print("=" * 50)
    print()
    
    state, name1, stats1, name2, stats2 = generate_pair()
    
    print(f"📍 State: {state}")
    print("-" * 50)
    print_stats(name1, stats1)
    print()
    print_stats(name2, stats2)
    print("-" * 50)
    
    # Calculate compatibility
    compat = (
        (100 - abs(stats1['happiness'] - stats2['happiness'])) +
        (100 - abs(stats1['wealth'] - stats2['wealth'])) +
        (100 - abs(stats1['health'] - stats2['health']))
    ) // 3
    
    print(f"💕 Compatibility: {stat_bar(compat)} {compat}%")
    print("=" * 50)

if __name__ == "__main__":
    main()
