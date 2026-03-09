import { Game, GameState } from '../core/Game';
import { HERO_ABILITIES } from '../hero/Hero';

export class HUD {
  private game: Game;
  private container: HTMLElement;
  private goldElement: HTMLElement | null = null;
  private livesElement: HTMLElement | null = null;
  private waveElement: HTMLElement | null = null;
  private abilityElements: HTMLElement[] = [];
  
  constructor(game: Game) {
    this.game = game;
    this.container = document.getElementById('game-container')!;
    this.createHUD();
    this.setupKeyboard();
  }
  
  private createHUD(): void {
    // HUD container
    const hud = document.createElement('div');
    hud.id = 'hud';
    hud.innerHTML = `
      <style>
        #hud {
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          padding: 15px 20px;
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
          pointer-events: none;
        }
        #hud > * { pointer-events: auto; }
        .hud-stat {
          background: rgba(0, 0, 0, 0.7);
          color: #fff;
          padding: 8px 16px;
          border-radius: 8px;
          font-size: 16px;
          font-weight: bold;
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .hud-stat span { color: #ffd700; }
        .tower-menu {
          display: flex;
          gap: 10px;
          background: rgba(0, 0, 0, 0.7);
          padding: 10px;
          border-radius: 8px;
        }
        .tower-btn {
          width: 60px;
          height: 60px;
          border: 2px solid #444;
          border-radius: 8px;
          background: #222;
          color: #fff;
          cursor: pointer;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          font-size: 12px;
          transition: all 0.2s;
        }
        .tower-btn:hover { border-color: #888; }
        .tower-btn.selected {
          border-color: #00ff00;
          box-shadow: 0 0 10px rgba(0, 255, 0, 0.5);
        }
        .tower-btn .key {
          font-size: 10px;
          color: #888;
          margin-bottom: 2px;
        }
        .ability-panel {
          display: flex;
          flex-direction: column;
          gap: 8px;
          background: rgba(0, 0, 0, 0.7);
          padding: 10px;
          border-radius: 8px;
        }
        .ability-btn {
          width: 70px;
          height: 40px;
          border: 2px solid #666;
          border-radius: 6px;
          background: #333;
          color: #fff;
          cursor: pointer;
          font-size: 11px;
          transition: all 0.2s;
          position: relative;
        }
        .ability-btn:hover { border-color: #ff8800; }
        .ability-btn.on-cooldown {
          border-color: #333;
          opacity: 0.6;
          cursor: not-allowed;
        }
        .ability-btn .key {
          position: absolute;
          top: 2px;
          left: 4px;
          font-size: 9px;
          color: #888;
        }
        .ability-btn .cooldown-overlay {
          position: absolute;
          bottom: 0;
          left: 0;
          right: 0;
          background: rgba(0, 0, 0, 0.7);
          height: 0%;
          transition: height 0.1s;
        }
      </style>
    `;
    
    // Stats
    const stats = document.createElement('div');
    stats.innerHTML = `
      <div class="hud-stat">💰 <span id="gold-display">200</span></div>
      <div class="hud-stat">❤️ <span id="lives-display">20</span></div>
      <div class="hud-stat">🌊 Wave <span id="wave-display">1</span></div>
    `;
    hud.appendChild(stats);
    
    // Tower menu
    const towerMenu = document.createElement('div');
    towerMenu.className = 'tower-menu';
    towerMenu.innerHTML = `
      <button class="tower-btn selected" data-tower="arrow">
        <span class="key">[1]</span>
        🏹 50g
      </button>
      <button class="tower-btn" data-tower="cannon">
        <span class="key">[2]</span>
        💣 100g
      </button>
      <button class="tower-btn" data-tower="ice">
        <span class="key">[3]</span>
        ❄️ 75g
      </button>
    `;
    hud.appendChild(towerMenu);
    
    // Ability panel
    const abilityPanel = document.createElement('div');
    abilityPanel.className = 'ability-panel';
    const abilityKeys = ['Q', 'W', 'E'];
    HERO_ABILITIES.forEach((ability, index) => {
      const btn = document.createElement('button');
      btn.className = 'ability-btn';
      btn.dataset.ability = index.toString();
      btn.innerHTML = `
        <span class="key">[${abilityKeys[index]}]</span>
        ${ability.name}
        <div class="cooldown-overlay"></div>
      `;
      abilityPanel.appendChild(btn);
      this.abilityElements.push(btn);
    });
    hud.appendChild(abilityPanel);
    
    this.container.appendChild(hud);
    
    // Store references
    this.goldElement = document.getElementById('gold-display');
    this.livesElement = document.getElementById('lives-display');
    this.waveElement = document.getElementById('wave-display');
    
    // Tower selection handlers
    towerMenu.querySelectorAll('.tower-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const type = (btn as HTMLElement).dataset.tower;
        this.game.towerFactory.setSelectedTowerType(type as 'arrow' | 'cannon' | 'ice');
        towerMenu.querySelectorAll('.tower-btn').forEach(b => b.classList.remove('selected'));
        btn.classList.add('selected');
      });
    });
    
    // Ability button handlers
    abilityPanel.querySelectorAll('.ability-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const index = parseInt((btn as HTMLElement).dataset.ability || '0');
        this.game.hero.useAbility(index);
      });
    });
  }
  
  private setupKeyboard(): void {
    window.addEventListener('keydown', (e) => {
      if (e.key === 'q' || e.key === 'Q') {
        this.game.hero.useAbility(0);
      } else if (e.key === 'w' || e.key === 'W') {
        this.game.hero.useAbility(1);
      } else if (e.key === 'e' || e.key === 'E') {
        this.game.hero.useAbility(2);
      }
    });
  }
  
  public updateGold(amount: number): void {
    if (this.goldElement) {
      this.goldElement.textContent = amount.toString();
    }
  }
  
  public updateLives(amount: number): void {
    if (this.livesElement) {
      this.livesElement.textContent = amount.toString();
    }
  }
  
  public updateWave(wave: number): void {
    if (this.waveElement) {
      this.waveElement.textContent = wave.toString();
    }
  }
  
  public update(_dt: number): void {
    const wave = this.game.getWave();
    this.updateWave(wave);
    
    // Update ability cooldowns
    const cooldowns = this.game.hero.getCooldowns();
    const abilities = HERO_ABILITIES;
    cooldowns.forEach((cd, index) => {
      const btn = this.abilityElements[index];
      if (btn && abilities[index]) {
        const overlay = btn.querySelector('.cooldown-overlay') as HTMLElement;
        if (cd > 0) {
          btn.classList.add('on-cooldown');
          const pct = (cd / abilities[index].cooldown) * 100;
          overlay.style.height = pct + '%';
        } else {
          btn.classList.remove('on-cooldown');
          overlay.style.height = '0%';
        }
      }
    });
  }
  
  public onStateChange(state: GameState): void {
    console.log('Game state changed to:', state);
  }
}
