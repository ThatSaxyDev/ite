# Godot Top-Down Shooter Game Plan

## Project Overview
- **Engine**: Godot 4.x (GDScript)
- **Type**: Top-Down Shooter (2D)
- **Style**: Arcade / Twin-stick / Rogue-like (specify)
- **Target Platforms**: Desktop (primary), Mobile, Web

---

## Phase 1: Project Setup (Week 1)
- [ ] Install Godot 4.x
- [ ] Create new 2D project
- [ ] Set up Git repository
- [ ] Configure project settings:
  - Resolution: 1280x720 (16:9)
  - Window stretch mode: `canvas_items`
  - Input map: WASD movement, Arrow keys/Mouse aim & shoot
- [ ] Create base scene structure

---

## Phase 2: Player Controller (Week 1-2)
- [ ] Player scene with `CharacterBody2D`
- [ ] Movement system:
  - 8-directional movement
  - Acceleration/deceleration
  - Speed variable (walk/run)
- [ ] Aiming system:
  - Mouse look (rotate toward cursor)
  - Or 8-directional facing
- [ ] Shooting system:
  - Projectile spawning
  - Fire rate & cooldown
  - Bullet trajectory
- [ ] Health & damage system
- [ ] Animation state machine (idle, run, shoot)

---

## Phase 3: Weapons & Projectiles (Week 2-3)
- [ ] Bullet scene (`Area2D` or `RigidBody2D`)
- [ ] Weapon base class
- [ ] Weapon types:
  - [ ] Pistol (default)
  - [ ] Shotgun (spread)
  - [ ] Machine gun (rapid fire)
  - [ ] Sniper (long range, slow)
- [ ] Ammo system
- [ ] Reload mechanic
- [ ] Weapon pickup/drop system

---

## Phase 4: Enemies & AI (Week 3-4)
- [ ] Enemy base class
- [ ] Enemy types:
  - [ ] Melee chaser (rush player)
  - [ ] Ranged shooter (fire at player)
  - [ ] Turret (stationary)
- [ ] AI behaviors:
  - Patrol path
  - Chase player
  - Shoot at player
  - Dodge/evade
- [ ] Enemy spawning system
- [ ] Wave management (if applicable)

---

## Phase 5: Level Design (Week 4-5)
- [ ] TileMap setup (tileset import)
- [ ] Level templates
- [ ] Obstacles & cover
- [ ] Spawn points
- [ ] Camera system (follow player, bounds)
- [ ] Multiple levels/maps

---

## Phase 6: Game Systems (Week 5-6)
- [ ] Health system (player & enemies)
- [ ] Damage types & resistances
- [ ] Collectibles (health pickups, ammo, coins)
- [ ] Score system
- [ ] Game over / restart
- [ ] Pause menu

---

## Phase 7: UI/HUD (Week 6)
- [ ] Health bar
- [ ] Ammo counter
- [ ] Score display
- [ ] Wave counter
- [ ] Weapon selector
- [ ] Main menu
- [ ] Pause menu
- [ ] Game over screen

---

## Phase 8: Polish & Effects (Week 7)
- [ ] Screen shake
- [ ] Muzzle flash
- [ ] Hit effects (particles)
- [ ] Death explosions
- [ ] Sound effects (gunfire, hits, explosions)
- [ ] Background music
- [ ] Post-processing (optional)

---

## Phase 9: Progression & Persistence (Week 7-8)
- [ ] Save/Load system
- [ ] High scores
- [ ] Unlockable weapons
- [ ] Upgrade system (if rogue-like)
- [ ] Statistics tracking

---

## Phase 10: Build & Release (Week 8)
- [ ] Performance optimization
- [ ] Bug testing
- [ ] Export presets:
  - [ ] Windows (.exe)
  - [ ] Mac (.app)
  - [ ] Linux
  - [ ] Web (HTML5)
- [ ] Create itch.io page (if releasing there)

---

## Recommended Assets
- **Kenney Assets**: Top-down shooter pack
- **Godot Asset Library**: Free tilesets, sprites
- **Audio**: Freesound.org for SFX

---

## Key Godot Concepts to Master
1. `CharacterBody2D` for player/enemies
2. `Area2D` for detection & projectiles
3. `StateMachine` for animations
4. `TileMap` for levels
5. Signals for loose coupling
6. Resource (.tres) files for data
