import * as THREE from 'three';
import { Game } from '../core/Game';

export interface HeroAbility {
  name: string;
  cooldown: number;
  damage?: number;
  effect?: 'damage' | 'slow' | 'heal';
}

export const HERO_ABILITIES: HeroAbility[] = [
  { name: 'Fireball', cooldown: 10, damage: 50, effect: 'damage' },
  { name: 'Frost Nova', cooldown: 15, effect: 'slow' },
  { name: 'Heal', cooldown: 20, effect: 'heal' }
];

export class Hero {
  private game: Game;
  private mesh: THREE.Group;
  public x: number;
  public z: number;
  
  private abilities: HeroAbility[] = [...HERO_ABILITIES];
  private cooldowns: number[] = [0, 0, 0];
  
  constructor(game: Game) {
    this.game = game;
    this.x = 5;
    this.z = 5;
    this.mesh = this.createMesh();
    this.updatePosition();
    game.sceneManager.add(this.mesh);
  }
  
  private createMesh(): THREE.Group {
    const group = new THREE.Group();
    
    // Body
    const bodyGeo = new THREE.CylinderGeometry(0.3, 0.4, 1.2, 8);
    const bodyMat = new THREE.MeshStandardMaterial({ color: 0x4169e1 });
    const body = new THREE.Mesh(bodyGeo, bodyMat);
    body.position.y = 0.6;
    body.castShadow = true;
    group.add(body);
    
    // Head
    const headGeo = new THREE.SphereGeometry(0.25, 8, 8);
    const headMat = new THREE.MeshStandardMaterial({ color: 0xffdbac });
    const head = new THREE.Mesh(headGeo, headMat);
    head.position.y = 1.4;
    head.castShadow = true;
    group.add(head);
    
    // Staff
    const staffGeo = new THREE.CylinderGeometry(0.05, 0.05, 1.5, 6);
    const staffMat = new THREE.MeshStandardMaterial({ color: 0x8b4513 });
    const staff = new THREE.Mesh(staffGeo, staffMat);
    staff.position.set(0.4, 0.8, 0);
    staff.rotation.z = 0.2;
    group.add(staff);
    
    // Staff orb
    const orbGeo = new THREE.SphereGeometry(0.1, 8, 8);
    const orbMat = new THREE.MeshStandardMaterial({ 
      color: 0xffd700,
      emissive: 0xffa500,
      emissiveIntensity: 0.5
    });
    const orb = new THREE.Mesh(orbGeo, orbMat);
    orb.position.set(0.55, 1.5, 0);
    group.add(orb);
    
    return group;
  }
  
  private updatePosition(): void {
    const worldPos = this.game.gridSystem.getWorldPosition(this.x, this.z);
    this.mesh.position.set(worldPos.x, 0, worldPos.z);
  }
  
  public update(dt: number): void {
    // Update cooldowns
    for (let i = 0; i < this.cooldowns.length; i++) {
      if (this.cooldowns[i] > 0) {
        this.cooldowns[i] = Math.max(0, this.cooldowns[i] - dt);
      }
    }
  }
  
  public useAbility(index: number): boolean {
    if (index >= this.abilities.length) return false;
    if (this.cooldowns[index] > 0) return false;
    
    const ability = this.abilities[index];
    this.cooldowns[index] = ability.cooldown;
    
    // Apply ability effect
    if (ability.effect === 'damage' || ability.effect === 'slow') {
      const enemies = this.game.enemyWaveManager.getEnemies();
      for (const enemy of enemies) {
        const dist = Math.sqrt(
          Math.pow(enemy.x - this.x, 2) + 
          Math.pow(enemy.z - this.z, 2)
        );
        if (dist < 5) { // Range
          if (ability.damage) {
            enemy.takeDamage(ability.damage, ability.effect === 'slow' ? 'slow' : undefined);
          } else if (ability.effect === 'slow') {
            enemy.applySlow(3);
          }
        }
      }
    }
    
    return true;
  }
  
  public getCooldowns(): number[] {
    return this.cooldowns;
  }
  
  public destroy(): void {
    this.game.sceneManager.remove(this.mesh);
  }
}
