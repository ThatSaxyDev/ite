import * as THREE from 'three';
import { Game } from '../core/Game';
import { Enemy } from '../enemies/Enemy';

export type ProjectileType = 'arrow' | 'cannon' | 'ice';

export class Projectile {
  private game: Game;
  private mesh: THREE.Mesh;
  private target: Enemy;
  private damage: number;
  private speed: number;
  private type: ProjectileType;
  private isDead: boolean = false;
  
  constructor(
    game: Game,
    startPos: THREE.Vector3,
    target: Enemy,
    damage: number,
    speed: number,
    type: ProjectileType
  ) {
    this.game = game;
    this.target = target;
    this.damage = damage;
    this.speed = speed;
    this.type = type;
    
    this.mesh = this.createMesh();
    this.mesh.position.copy(startPos);
    this.mesh.position.y = 0.5;
    
    game.sceneManager.add(this.mesh);
  }
  
  private createMesh(): THREE.Mesh {
    let geometry: THREE.BufferGeometry;
    let material: THREE.Material;
    
    switch (this.type) {
      case 'arrow':
        geometry = new THREE.ConeGeometry(0.05, 0.3, 4);
        material = new THREE.MeshStandardMaterial({ color: 0x8B4513 });
        break;
      case 'cannon':
        geometry = new THREE.SphereGeometry(0.15, 8, 8);
        material = new THREE.MeshStandardMaterial({ color: 0x222222 });
        break;
      case 'ice':
        geometry = new THREE.OctahedronGeometry(0.1);
        material = new THREE.MeshStandardMaterial({ 
          color: 0x87CEEB,
          transparent: true,
          opacity: 0.8
        });
        break;
      default:
        geometry = new THREE.SphereGeometry(0.1, 8, 8);
        material = new THREE.MeshStandardMaterial({ color: 0xffffff });
    }
    
    const mesh = new THREE.Mesh(geometry, material);
    mesh.castShadow = true;
    return mesh;
  }
  
  public update(dt: number): void {
    if (this.isDead || this.target.getIsDead()) {
      this.destroy();
      return;
    }
    
    // Get target position
    const targetPos = this.target.mesh.position.clone();
    targetPos.y = 0.5;
    
    // Move towards target
    const direction = targetPos.clone().sub(this.mesh.position);
    const distance = direction.length();
    
    if (distance < 0.3) {
      // Hit!
      this.hitTarget();
      return;
    }
    
    direction.normalize();
    const moveAmount = this.speed * dt;
    this.mesh.position.add(direction.multiplyScalar(moveAmount));
    
    // Rotate to face direction
    this.mesh.lookAt(targetPos);
  }
  
  private hitTarget(): void {
    const effect = this.type === 'ice' ? 'slow' : undefined;
    this.target.takeDamage(this.damage, effect);
    this.destroy();
  }
  
  public destroy(): void {
    this.isDead = true;
    this.game.sceneManager.remove(this.mesh);
  }
  
  public getIsDead(): boolean {
    return this.isDead;
  }
}
