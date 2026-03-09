import * as THREE from 'three';
import { Game } from '../core/Game';

export interface EnemyStats {
  health: number;
  speed: number;
  reward: number;
  color: number;
  size: number;
}

export const ENEMY_STATS: Record<string, EnemyStats> = {
  goblin: { health: 30, speed: 1.5, reward: 10, color: 0x228b22, size: 0.3 },
  orc: { health: 80, speed: 1.0, reward: 25, color: 0x006400, size: 0.45 },
  troll: { health: 200, speed: 0.6, reward: 50, color: 0x4a6741, size: 0.6 },
  boss: { health: 500, speed: 0.4, reward: 200, color: 0x8b0000, size: 0.9 }
};

export class Enemy {
  protected game: Game;
  public x: number;
  public z: number;
  public stats: EnemyStats;
  public health: number;
  
  public mesh: THREE.Group;
  protected path: { x: number; z: number }[] = [];
  protected pathIndex: number = 0;
  protected speed: number;
  protected isDead: boolean = false;
  protected isSlowed: boolean = false;
  protected slowTimer: number = 0;
  
  constructor(game: Game, x: number, z: number, stats: EnemyStats) {
    this.game = game;
    this.x = x;
    this.z = z;
    this.stats = stats;
    this.health = stats.health;
    this.speed = stats.speed;
    this.mesh = this.createMesh();
    
    this.updatePosition();
    game.sceneManager.add(this.mesh);
  }
  
  protected createMesh(): THREE.Group {
    const group = new THREE.Group();
    
    // Body (simple sphere/blob for now)
    const bodyGeo = new THREE.SphereGeometry(this.stats.size, 8, 6);
    const bodyMat = new THREE.MeshStandardMaterial({ 
      color: this.stats.color,
      roughness: 0.8
    });
    const body = new THREE.Mesh(bodyGeo, bodyMat);
    body.position.y = this.stats.size;
    body.castShadow = true;
    group.add(body);
    
    // Eyes
    const eyeGeo = new THREE.SphereGeometry(0.08, 4, 4);
    const eyeMat = new THREE.MeshBasicMaterial({ color: 0xff0000 });
    
    const leftEye = new THREE.Mesh(eyeGeo, eyeMat);
    leftEye.position.set(-0.15, this.stats.size + 0.15, this.stats.size * 0.7);
    group.add(leftEye);
    
    const rightEye = new THREE.Mesh(eyeGeo, eyeMat);
    rightEye.position.set(0.15, this.stats.size + 0.15, this.stats.size * 0.7);
    group.add(rightEye);
    
    return group;
  }
  
  public setPath(path: { x: number; z: number }[]): void {
    this.path = path;
    this.pathIndex = 0;
    
    if (path.length > 0) {
      this.x = path[0].x;
      this.z = path[0].z;
      this.updatePosition();
    }
  }
  
  private updatePosition(): void {
    const worldPos = this.game.gridSystem.getWorldPosition(this.x, this.z);
    this.mesh.position.set(worldPos.x, 0, worldPos.z);
  }
  
  public update(dt: number): void {
    if (this.isDead || this.path.length === 0) return;
    
    // Handle slow effect
    if (this.isSlowed) {
      this.slowTimer -= dt;
      if (this.slowTimer <= 0) {
        this.isSlowed = false;
        this.speed = this.stats.speed;
      }
    }
    
    // Move along path
    if (this.pathIndex < this.path.length) {
      const target = this.path[this.pathIndex];
      const dx = target.x - this.x;
      const dz = target.z - this.z;
      const dist = Math.sqrt(dx * dx + dz * dz);
      
      if (dist < 0.1) {
        this.pathIndex++;
        if (this.pathIndex >= this.path.length) {
          this.reachEnd();
          return;
        }
      } else {
        const moveSpeed = this.speed * dt;
        this.x += (dx / dist) * moveSpeed;
        this.z += (dz / dist) * moveSpeed;
      }
      
      this.updatePosition();
    }
  }
  
  private reachEnd(): void {
    this.isDead = true;
    this.game.loseLife();
    this.destroy();
  }
  
  public takeDamage(amount: number, effect?: 'slow'): void {
    this.health -= amount;
    
    if (effect === 'slow') {
      this.isSlowed = true;
      this.slowTimer = 2; // 2 seconds
      this.speed = this.stats.speed * 0.5;
    }
    
    if (this.health <= 0) {
      this.die();
    }
  }
  
  private die(): void {
    this.isDead = true;
    this.game.addGold(this.stats.reward);
    this.destroy();
  }
  
  public destroy(): void {
    this.game.sceneManager.remove(this.mesh);
  }
  
  public getIsDead(): boolean {
    return this.isDead;
  }
  
  public applySlow(duration: number): void {
    this.isSlowed = true;
    this.slowTimer = duration;
    this.speed = this.stats.speed * 0.5;
  }
}
