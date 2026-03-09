import { Game, GameState } from '../core/Game';

export class HUD {
  private game: Game;
  private container: HTMLElement;
  private goldElement: HTMLElement | null = null;
  private livesElement: HTMLElement | null = null;
  private waveElement: HTMLElement | null = null;
  private towerMenuElement: HTMLElement | null = null;
  
  constructor(game: Game) {
    this.game = game;
    this.container = document.getElementById('game-container')!;
    this.createHUD();
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
          align-items: center;
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
    const menu = document.createElement('div');
    menu.className = 'tower-menu';
    menu.innerHTML = `
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
    hud.appendChild(menu);
    
    this.container.appendChild(hud);
    
    // Store references
    this.goldElement = document.getElementById('gold-display');
    this.livesElement = document.getElementById('lives-display');
    this.waveElement = document.getElementById('wave-display');
    this.towerMenuElement = menu;
    
    // Tower selection handlers
    menu.querySelectorAll('.tower-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const type = (btn as HTMLElement).dataset.tower;
        this.game.towerFactory.setSelectedTowerType(type as 'arrow' | 'cannon' | 'ice');
        menu.querySelectorAll('.tower-btn').forEach(b => b.classList.remove('selected'));
        btn.classList.add('selected');
      });
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
  
  public update(dt: number): void {
    // Update wave display
    const wave = this.game.getWave();
    this.updateWave(wave);
  }
  
  public onStateChange(state: GameState): void {
    // Could show/hide elements based on state
    console.log('Game state changed to:', state);
  }
}
