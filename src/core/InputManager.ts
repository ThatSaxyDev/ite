import * as THREE from 'three';
import { Game, GameState } from './Game';

export class InputManager {
  private game: Game;
  private mouse: THREE.Vector2;
  private raycaster: THREE.Raycaster;
  private groundPlane: THREE.Plane;
  
  constructor() {
    this.game = Game.getInstance();
    this.mouse = new THREE.Vector2();
    this.raycaster = new THREE.Raycaster();
    this.groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    
    this.setupListeners();
  }
  
  private setupListeners(): void {
    window.addEventListener('mousemove', this.onMouseMove);
    window.addEventListener('click', this.onClick);
    window.addEventListener('contextmenu', (e) => e.preventDefault());
    window.addEventListener('keydown', this.onKeyDown);
  }
  
  private onMouseMove = (event: MouseEvent): void => {
    this.mouse.x = (event.clientX / window.innerWidth) * 2 - 1;
    this.mouse.y = -(event.clientY / window.innerHeight) * 2 + 1;
  };
  
  private onClick = (event: MouseEvent): void => {
    if (event.button === 0) { // Left click
      this.handleLeftClick();
    } else if (event.button === 2) { // Right click
      this.handleRightClick();
    }
  };
  
  private handleLeftClick(): void {
    const gridPos = this.getGridPosition();
    if (gridPos) {
      this.game.gridSystem.onGridClick(gridPos.x, gridPos.z);
    }
  }
  
  private handleRightClick(): void {
    // Deselect tower
    this.game.gridSystem.deselectCell();
  }
  
  private onKeyDown = (event: KeyboardEvent): void => {
    if (event.key === 'Escape') {
      this.game.setState(GameState.PAUSED);
    } else if (event.key === '1') {
      this.game.towerFactory.setSelectedTowerType('arrow');
    } else if (event.key === '2') {
      this.game.towerFactory.setSelectedTowerType('cannon');
    } else if (event.key === '3') {
      this.game.towerFactory.setSelectedTowerType('ice');
    }
  };
  
  public getGridPosition(): { x: number; z: number } | null {
    const sceneManager = this.game.sceneManager;
    this.raycaster.setFromCamera(this.mouse, sceneManager.camera);
    
    const intersection = new THREE.Vector3();
    const hit = this.raycaster.ray.intersectPlane(this.groundPlane, intersection);
    
    if (hit) {
      const grid = this.game.gridSystem;
      const x = Math.floor(intersection.x + grid.getWidth() / 2);
      const z = Math.floor(intersection.z + grid.getHeight() / 2);
      
      if (x >= 0 && x < grid.getWidth() && z >= 0 && z < grid.getHeight()) {
        return { x, z };
      }
    }
    return null;
  }
  
  public getMouseWorldPosition(): THREE.Vector3 | null {
    const sceneManager = this.game.sceneManager;
    this.raycaster.setFromCamera(this.mouse, sceneManager.camera);
    
    const intersection = new THREE.Vector3();
    const hit = this.raycaster.ray.intersectPlane(this.groundPlane, intersection);
    
    return hit ? intersection : null;
  }
  
  public isMouseOverUI(): boolean {
    // Simple check - can be enhanced with actual UI detection
    return false;
  }
}
