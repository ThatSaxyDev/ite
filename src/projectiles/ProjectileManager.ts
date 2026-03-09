import { Game } from '../core/Game';
import { Projectile } from './Projectile';

export class ProjectileManager {
  private _game: Game;
  private projectiles: Projectile[] = [];
  
  constructor(game: Game) {
    this._game = game;
  }
  
  public add(projectile: Projectile): void {
    this.projectiles.push(projectile);
  }
  
  public update(dt: number): void {
    for (const projectile of this.projectiles) {
      projectile.update(dt);
    }
    
    // Remove dead projectiles
    this.projectiles = this.projectiles.filter(p => !p.getIsDead());
  }
  
  public getProjectiles(): Projectile[] {
    return this.projectiles;
  }
  
  public clear(): void {
    for (const projectile of this.projectiles) {
      projectile.destroy();
    }
    this.projectiles = [];
  }
}
