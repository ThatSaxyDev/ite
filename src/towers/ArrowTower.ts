import * as THREE from 'three';
import { Tower, TowerStats } from './Tower';
import { Projectile } from '../projectiles/Projectile';

export const TOWER_STATS: Record<string, TowerStats> = {
  arrow: {
    name: 'Arrow Tower',
    cost: 50,
    damage: 10,
    range: 5,
    fireRate: 2,
    color: 0x8B4513,
    projectileSpeed: 15
  },
  cannon: {
    name: 'Cannon Tower',
    cost: 100,
    damage: 30,
    range: 4,
    fireRate: 0.5,
    color: 0x2F4F4F,
    projectileSpeed: 10
  },
  ice: {
    name: 'Ice Tower',
    cost: 75,
    damage: 5,
    range: 4,
    fireRate: 1.5,
    color: 0x87CEEB,
    projectileSpeed: 12
  }
};

export class ArrowTower extends Tower {
  protected createMesh(): THREE.Group {
    const group = new THREE.Group();
    
    // Base
    const baseGeo = new THREE.CylinderGeometry(0.4, 0.5, 0.3, 8);
    const baseMat = new THREE.MeshStandardMaterial({ color: 0x654321 });
    const base = new THREE.Mesh(baseGeo, baseMat);
    base.position.y = 0.15;
    base.castShadow = true;
    group.add(base);
    
    // Tower body
    const bodyGeo = new THREE.CylinderGeometry(0.25, 0.35, 0.6, 8);
    const bodyMat = new THREE.MeshStandardMaterial({ color: this.stats.color });
    const body = new THREE.Mesh(bodyGeo, bodyMat);
    body.position.y = 0.6;
    body.castShadow = true;
    group.add(body);
    
    // Arrow launcher
    const launcherGeo = new THREE.CylinderGeometry(0.1, 0.1, 0.4, 6);
    const launcherMat = new THREE.MeshStandardMaterial({ color: 0x8B4513 });
    const launcher = new THREE.Mesh(launcherGeo, launcherMat);
    launcher.rotation.x = Math.PI / 2;
    launcher.position.set(0, 0.7, 0.3);
    group.add(launcher);
    
    return group;
  }
  
  protected fire(): void {
    if (!this.target) return;
    
    const projectile = new Projectile(
      this.game,
      this.getPosition(),
      this.target,
      this.stats.damage,
      this.stats.projectileSpeed,
      'arrow'
    );
    
    this.game.projectileManager.add(projectile);
    this.lastFireTime = performance.now() / 1000;
  }
}

export class CannonTower extends Tower {
  protected createMesh(): THREE.Group {
    const group = new THREE.Group();
    
    // Base
    const baseGeo = new THREE.CylinderGeometry(0.5, 0.6, 0.3, 8);
    const baseMat = new THREE.MeshStandardMaterial({ color: 0x333333 });
    const base = new THREE.Mesh(baseGeo, baseMat);
    base.position.y = 0.15;
    base.castShadow = true;
    group.add(base);
    
    // Tower body (square)
    const bodyGeo = new THREE.BoxGeometry(0.5, 0.7, 0.5);
    const bodyMat = new THREE.MeshStandardMaterial({ color: this.stats.color });
    const body = new THREE.Mesh(bodyGeo, bodyMat);
    body.position.y = 0.65;
    body.castShadow = true;
    group.add(body);
    
    // Cannon barrel
    const barrelGeo = new THREE.CylinderGeometry(0.15, 0.2, 0.6, 8);
    const barrelMat = new THREE.MeshStandardMaterial({ color: 0x222222 });
    const barrel = new THREE.Mesh(barrelGeo, barrelMat);
    barrel.rotation.x = Math.PI / 2;
    barrel.position.set(0, 0.75, 0.4);
    group.add(barrel);
    
    return group;
  }
  
  protected fire(): void {
    if (!this.target) return;
    
    const projectile = new Projectile(
      this.game,
      this.getPosition(),
      this.target,
      this.stats.damage,
      this.stats.projectileSpeed,
      'cannon'
    );
    
    this.game.projectileManager.add(projectile);
    this.lastFireTime = performance.now() / 1000;
  }
}

export class IceTower extends Tower {
  protected createMesh(): THREE.Group {
    const group = new THREE.Group();
    
    // Base (icy platform)
    const baseGeo = new THREE.CylinderGeometry(0.4, 0.5, 0.2, 6);
    const baseMat = new THREE.MeshStandardMaterial({ 
      color: this.stats.color,
      transparent: true,
      opacity: 0.8,
      roughness: 0.2
    });
    const base = new THREE.Mesh(baseGeo, baseMat);
    base.position.y = 0.1;
    base.castShadow = true;
    group.add(base);
    
    // Crystal tower
    const crystalGeo = new THREE.OctahedronGeometry(0.35);
    const crystalMat = new THREE.MeshStandardMaterial({ 
      color: 0xaaddff,
      transparent: true,
      opacity: 0.7,
      roughness: 0.1,
      metalness: 0.3
    });
    const crystal = new THREE.Mesh(crystalGeo, crystalMat);
    crystal.position.y = 0.6;
    crystal.scale.y = 1.5;
    crystal.castShadow = true;
    group.add(crystal);
    
    return group;
  }
  
  protected fire(): void {
    if (!this.target) return;
    
    const projectile = new Projectile(
      this.game,
      this.getPosition(),
      this.target,
      this.stats.damage,
      this.stats.projectileSpeed,
      'ice'
    );
    
    this.game.projectileManager.add(projectile);
    this.lastFireTime = performance.now() / 1000;
  }
}
