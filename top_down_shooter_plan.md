# Top-Down Shooter Game Plan

## Project Overview
- **Tech Stack**: HTML5 Canvas, CSS, JavaScript (vanilla)
- **Type**: Top-Down Shooter (2D)
- **Style**: Arcade / Twin-stick
- **Target Platforms**: Browser (Desktop primary)

---

## Phase 1: Project Setup (Week 1)
- [ ] Create project structure
  - `index.html` - Game container
  - `style.css` - Styling
  - `js/main.js` - Entry point
  - `js/entities/` - Game objects
  - `js/systems/` - Game systems
  - `assets/` - Sprites, sounds
- [ ] Set up Canvas element
- [ ] Game loop (requestAnimationFrame)
- [ ] Input handling (keyboard, mouse)
- [ ] Basic rendering pipeline

---

## Phase 2: Player Controller (Week 1-2)
- [ ] Player entity with position, velocity
- [ ] Movement system:
  - 8-directional movement (WASD)
  - Acceleration/deceleration
- [ ] Aiming system:
  - Mouse look (rotate toward cursor)
- [ ] Shooting system:
  - Projectile spawning
  - Fire rate & cooldown
- [ ] Health system
- [ ] Sprite/visual representation

---

## Phase 3: Weapons & Projectiles (Week 2-3)
- [ ] Bullet entity
- [ ] Weapon system:
  - [ ] Pistol (default)
  - [ ] Shotgun (spread)
  - [ ] Machine gun (rapid fire)
  - [ ] Sniper (long range, slow)
- [ ] Ammo system
- [ ] Weapon switching

---

## Phase 4: Enemies & AI (Week 3-4)
- [ ] Enemy base class
- [ ] Enemy types:
  - [ ] Melee chaser (rush player)
  - [ ] Ranged shooter (fire at player)
  - [ ] Turret (stationary)
- [ ] AI behaviors:
  - Chase player
  - Shoot at player
- [ ] Enemy spawning system
- [ ] Wave management

---

## Phase 5: Level Design (Week 4-5)
- [ ] Tile/grid system
- [ ] Level maps (array-based or JSON)
- [ ] Collision detection (AABB)
- [ ] Camera system (follow player)
- [ ] Obstacles & cover

---

## Phase 6: Game Systems (Week 5-6)
- [ ] Health system (player & enemies)
- [ ] Damage system
- [ ] Collectibles (health pickups, ammo)
- [ ] Score system
- [ ] Game over / restart
- [ ] Pause functionality

---

## Phase 7: UI/HUD (Week 6)
- [ ] Health bar
- [ ] Ammo counter
- [ ] Score display
- [ ] Wave counter
- [ ] Weapon indicator
- [ ] Main menu
- [ ] Game over screen

---

## Phase 8: Polish & Effects (Week 7)
- [ ] Screen shake
- [ ] Muzzle flash visual
- [ ] Hit effects
- [ ] Death animations
- [ ] Sound effects (Web Audio API)
- [ ] Background music
- [ ] Particle effects

---

## Phase 9: Progression & Persistence (Week 7-8)
- [ ] LocalStorage for high scores
- [ ] Unlockable weapons
- [ ] Statistics tracking

---

## Phase 10: Build & Release (Week 8)
- [ ] Performance optimization
- [ ] Bug testing
- [ ] Package for web (or use local server)
- [ ] Create itch.io page (if releasing)

---

## Key JavaScript Concepts
1. Canvas 2D rendering context
2. Game loop with delta time
3. Entity-Component pattern (simplified)
4. AABB collision detection
5. State management
6. Web Audio API for sound
7. LocalStorage for persistence

---

## Suggested Libraries (Optional)
- **Phaser.js** - Full game framework (if wanted)
- **Pixi.js** - Rendering only
- Or stick with vanilla for learning
