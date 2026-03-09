import { Game } from '../core/Game';
import { Enemy, ENEMY_STATS, EnemyStats } from './Enemy';

export interface WaveConfig {
  enemies: { type: string; count: number; interval: number }[];
  spawnDelay: number;
}

export const WAVE_CONFIGS: WaveConfig[] = [
  // Wave 1 - Goblins only
  { enemies: [{ type: 'goblin', count: 5, interval: 1.5 }], spawnDelay: 2 },
  // Wave 2 - More goblins
  { enemies: [{ type: 'goblin', count: 8, interval: 1.2 }], spawnDelay: 3 },
  // Wave 3 - Goblins + Orcs
  { enemies: [
    { type: 'goblin', count: 5, interval: 1.5 },
    { type: 'orc', count: 3, interval: 2 }
  ], spawnDelay: 3 },
  // Wave 4 - Mixed
  { enemies: [
    { type: 'goblin', count: 10, interval: 1 },
    { type: 'orc', count: 5, interval: 2 }
  ], spawnDelay: 3 },
  // Wave 5 - Introduce Troll
  { enemies: [
    { type: 'goblin', count: 8, interval: 1 },
    { type: 'orc', count: 5, interval: 1.5 },
    { type: 'troll', count: 2, interval: 3 }
  ], spawnDelay: 4 },
  // Wave 6+
  { enemies: [
    { type: 'goblin', count: 15, interval: 0.8 },
    { type: 'orc', count: 8, interval: 1.5 },
    { type: 'troll', count: 3, interval: 3 }
  ], spawnDelay: 4 }
];

export class EnemyWaveManager {
  private game: Game;
  private enemies: Enemy[] = [];
  private currentWave: number = 0;
  private waveInProgress: boolean = false;
  private spawnQueue: { type: string; stats: EnemyStats }[] = [];
  private spawnTimer: number = 0;
  private waveComplete: boolean = false;
  
  constructor(game: Game) {
    this.game = game;
  }
  
  public startWave(waveNumber: number): void {
    if (waveNumber >= WAVE_CONFIGS.length) {
      // Endless mode - scale difficulty
      waveNumber = WAVE_CONFIGS.length - 1;
    }
    
    this.currentWave = waveNumber;
    const config = WAVE_CONFIGS[waveNumber];
    
    // Build spawn queue
    this.spawnQueue = [];
    for (const group of config.enemies) {
      const stats = ENEMY_STATS[group.type];
      for (let i = 0; i < group.count; i++) {
        this.spawnQueue.push({ type: group.type, stats });
      }
    }
    
    // Shuffle spawn queue slightly for variety
    this.shuffleArray(this.spawnQueue);
    
    this.spawnTimer = config.spawnDelay;
    this.waveInProgress = true;
    this.waveComplete = false;
  }
  
  private shuffleArray<T>(array: T[]): void {
    for (let i = array.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [array[i], array[j]] = [array[j], array[i]];
    }
  }
  
  public update(dt: number): void {
    // Spawn enemies
    if (this.waveInProgress && this.spawnQueue.length > 0) {
      this.spawnTimer -= dt;
      if (this.spawnTimer <= 0) {
        this.spawnEnemy(this.spawnQueue.shift()!);
        this.spawnTimer = 0.5; // Small delay between spawns
      }
    }
    
    // Update all enemies
    for (const enemy of this.enemies) {
      enemy.update(dt);
    }
    
    // Remove dead enemies
    this.enemies = this.enemies.filter(e => !e.getIsDead());
    
    // Check wave completion
    if (this.waveInProgress && this.spawnQueue.length === 0 && this.enemies.length === 0) {
      this.waveComplete = true;
      this.waveInProgress = false;
    }
  }
  
  private spawnEnemy(spawnData: { type: string; stats: EnemyStats }): void {
    const pathfinder = this.game.pathfinder;
    const grid = this.game.gridSystem;
    
    // Find path from left edge to right edge
    const path = pathfinder.findPathFromEdge('left', grid.getWidth() - 1, Math.floor(grid.getHeight() / 2));
    
    if (path && path.length > 0) {
      const enemy = new Enemy(this.game, path[0].x, path[0].z, { ...spawnData.stats });
      enemy.setPath(path);
      this.enemies.push(enemy);
    }
  }
  
  public getEnemies(): Enemy[] {
    return this.enemies;
  }
  
  public getCurrentWave(): number {
    return this.currentWave + 1;
  }
  
  public isWaveComplete(): boolean {
    return this.waveComplete;
  }
  
  public nextWave(): void {
    this.waveComplete = false;
    this.startWave(this.currentWave + 1);
  }
  
  public getWaveInProgress(): boolean {
    return this.waveInProgress;
  }
}
