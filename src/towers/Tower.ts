import * as THREE from 'three';
import { Game } from '../core/Game';
import { Enemy } from '../enemies/Enemy';

export interface TowerStats {
  name: string;
  cost: number;
  damage: number;
  range: number;
  fireRate: number;
  color: number;
  projectileSpeed: number;
}

export abstract class Tower {
  protected game: Game;
  public x: number;
  public z: number;
  public stats: TowerStats;
  
  protected mesh: THREE.Group;
  protected lastFireTime: number = 0;
  protected target: Enemy | null = null;
  
  constructor(game: Game, x: number, z: number, stats: TowerStats) {
    this.game = game;
    this.x = x;
    this.z = z;
    this.stats = stats;
    this.mesh = this.createMesh();
    
    this.updatePosition();
    game.sceneManager.add(this.mesh);
  }
  
  protected abstract createMesh(): THREE.Group;
  
  protected updatePosition(): void {
    const worldPos = this.game.gridSystem.getWorldPosition(this.x, this.z);
    this.mesh.position.set(worldPos.x, 0, worldPos.z);
  }
  
  public update(dt: number): void {
    this.findTarget();
    this.rotateTowardsTarget();
    
    if (this.target && this.canFire()) {
      this.fire();
    }
  }
  
  protected findTarget(): void {
    const enemies = this.game.enemyWaveManager.getEnemies();
    let closestEnemy: Enemy | null = null;
    let closestDist = this.stats.range;
    
    for (const enemy of enemies) {
      const dx = enemy.x - this.x;
      const dz = enemy.z - this.z;
      const dist = Math.sqrt(dx * dx + dz * dz);
      
      if (dist < closestDist) {
        closestDist = dist;
        closestEnemy = enemy;
      }
    }
    
    this.target = closestEnemy;
  }
  
  protected rotateTowardsTarget(): void {
    if (!this.target) return;
    
    const dx = this.target.x - this.x;
    const dz = this.target.z - this.z;
    const angle = Math.atan2(dx, dz);
    
    this.mesh.rotation.y = angle;
  }
  
  protected canFire(): boolean {
    const now = performance.now() / 1000;
    return now - this.lastFireTime >= 1 / this.stats.fireRate;
  }
  
  protected abstract fire(): void;
  
  public getPosition(): THREE.Vector3 {
    return this.mesh.position.clone();
  }
  
  public destroy(): void {
    this.game.sceneManager.remove(this.mesh);
  }
  
  public upgrade(): void {
    this.stats.damage *= 1.2;
    this.stats.range *= 1.1;
    this.stats.fireRate *= 1.1;
  }
}
