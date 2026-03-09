import { Game } from '../core/Game';
import { Tower } from './Tower';
import { ArrowTower, CannonTower, IceTower, TOWER_STATS } from './ArrowTower';
import { GridSystem } from '../grid/GridSystem';

export type TowerType = 'arrow' | 'cannon' | 'ice';

export class TowerFactory {
  private game: Game;
  private towers: Tower[] = [];
  private selectedType: TowerType = 'arrow';
  
  constructor(game: Game) {
    this.game = game;
  }
  
  public setSelectedTowerType(type: TowerType): void {
    this.selectedType = type;
  }
  
  public getSelectedTowerType(): TowerType {
    return this.selectedType;
  }
  
  public createTower(x: number, z: number): Tower | null {
    const grid = this.game.gridSystem;
    const stats = TOWER_STATS[this.selectedType];
    
    // Check if can afford
    if (!this.game.spendGold(stats.cost)) {
      return null;
    }
    
    // Check if can place
    if (!grid.canPlaceTower(x, z)) {
      this.game.addGold(stats.cost); // Refund
      return null;
    }
    
    // Place tower in grid
    grid.placeTower(x, z);
    
    // Create tower instance
    let tower: Tower;
    switch (this.selectedType) {
      case 'arrow':
        tower = new ArrowTower(this.game, x, z, { ...stats });
        break;
      case 'cannon':
        tower = new CannonTower(this.game, x, z, { ...stats });
        break;
      case 'ice':
        tower = new IceTower(this.game, x, z, { ...stats });
        break;
    }
    
    this.towers.push(tower);
    return tower;
  }
  
  public removeTower(tower: Tower): void {
    const index = this.towers.indexOf(tower);
    if (index > -1) {
      this.towers.splice(index, 1);
      tower.destroy();
      this.game.gridSystem.removeTower(tower.x, tower.z);
    }
  }
  
  public getTowers(): Tower[] {
    return this.towers;
  }
  
  public update(dt: number): void {
    for (const tower of this.towers) {
      tower.update(dt);
    }
  }
  
  public getTowerAt(x: number, z: number): Tower | null {
    for (const tower of this.towers) {
      if (tower.x === x && tower.z === z) {
        return tower;
      }
    }
    return null;
  }
}
