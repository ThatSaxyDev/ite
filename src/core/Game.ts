import { SceneManager } from './SceneManager';
import { InputManager } from './InputManager';
import { GridSystem } from '../grid/GridSystem';
import { Pathfinder } from '../pathfinding/Pathfinder';
import { TowerFactory } from '../towers/TowerFactory';
import { EnemyWaveManager } from '../enemies/EnemyWaveManager';
import { ProjectileManager } from '../projectiles/ProjectileManager';
import { PlayerProfile } from '../progression/PlayerProfile';
import { Hero } from '../hero/Hero';
import { HUD } from '../ui/HUD';

export enum GameState {
  MENU = 'menu',
  PLAYING = 'playing',
  PAUSED = 'paused',
  GAME_OVER = 'game_over',
  VICTORY = 'victory'
}

export class Game {
  private static instance: Game;
  
  public sceneManager: SceneManager;
  public inputManager: InputManager;
  public gridSystem: GridSystem;
  public pathfinder: Pathfinder;
  public towerFactory: TowerFactory;
  public enemyWaveManager: EnemyWaveManager;
  public projectileManager: ProjectileManager;
  public playerProfile: PlayerProfile;
  public hero: Hero;
  public hud: HUD;
  
  private state: GameState = GameState.MENU;
  private lastTime: number = 0;
  private deltaTime: number = 0;
  
  private constructor() {
    this.sceneManager = new SceneManager();
    this.inputManager = new InputManager();
    this.gridSystem = new GridSystem(20, 20);
    this.pathfinder = new Pathfinder(this.gridSystem);
    this.towerFactory = new TowerFactory(this);
    this.enemyWaveManager = new EnemyWaveManager(this);
    this.projectileManager = new ProjectileManager(this);
    this.playerProfile = new PlayerProfile();
    this.hero = new Hero(this);
    this.hud = new HUD(this);
  }
  
  public static getInstance(): Game {
    if (!Game.instance) {
      Game.instance = new Game();
    }
    return Game.instance;
  }
  
  public start(): void {
    this.lastTime = performance.now();
    this.setState(GameState.PLAYING);
    this.enemyWaveManager.startWave(0);
    this.loop();
  }
  
  public getState(): GameState {
    return this.state;
  }
  
  public setState(newState: GameState): void {
    this.state = newState;
    this.hud.onStateChange(newState);
  }
  
  public getDeltaTime(): number {
    return this.deltaTime;
  }
  
  private loop = (): void => {
    requestAnimationFrame(this.loop);
    
    const currentTime = performance.now();
    this.deltaTime = Math.min((currentTime - this.lastTime) / 1000, 0.1);
    this.lastTime = currentTime;
    
    if (this.state === GameState.PLAYING) {
      this.update(this.deltaTime);
    }
    
    this.render();
  };
  
  private update(dt: number): void {
    this.gridSystem.update(dt);
    this.towerFactory.update(dt);
    this.enemyWaveManager.update(dt);
    this.projectileManager.update(dt);
    this.hero.update(dt);
    this.hud.update(dt);
  }
  
  private render(): void {
    this.sceneManager.render();
  }
  
  public getGold(): number {
    return this.playerProfile.gold;
  }
  
  public addGold(amount: number): void {
    this.playerProfile.gold += amount;
    this.hud.updateGold(this.playerProfile.gold);
  }
  
  public spendGold(amount: number): boolean {
    if (this.playerProfile.gold >= amount) {
      this.playerProfile.gold -= amount;
      this.hud.updateGold(this.playerProfile.gold);
      return true;
    }
    return false;
  }
  
  public getLives(): number {
    return this.playerProfile.lives;
  }
  
  public loseLife(): void {
    this.playerProfile.lives--;
    this.hud.updateLives(this.playerProfile.lives);
    if (this.playerProfile.lives <= 0) {
      this.setState(GameState.GAME_OVER);
    }
  }
  
  public getWave(): number {
    return this.enemyWaveManager.getCurrentWave();
  }
}
