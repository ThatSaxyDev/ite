import * as THREE from 'three';
import { Game } from '../core/Game';
  EMPTY = 0,
  PATH = 1,
  TOWER = 2,
  OBSTACLE = 3
}

export class GridSystem {
  private width: number;
  private height: number;
  private cells: CellType[][];
  private cellMeshes: THREE.Mesh[][];
  private cellSize: number = 1;
  
  private highlightMesh: THREE.Mesh | null = null;
  private selectedCell: { x: number; z: number } | null = null;
  
  constructor(width: number, height: number) {
    this.width = width;
    this.height = height;
    this.cells = [];
    this.cellMeshes = [];
    
    this.initializeGrid();
    this.createVisuals();
  }
  
  private initializeGrid(): void {
    for (let x = 0; x < this.width; x++) {
      this.cells[x] = [];
      this.cellMeshes[x] = [];
      for (let z = 0; z < this.height; z++) {
        this.cells[x][z] = CellType.EMPTY;
      }
    }
    
    // Create a default path (center horizontal)
    const midZ = Math.floor(this.height / 2);
    for (let x = 0; x < this.width; x++) {
      this.cells[x][midZ] = CellType.PATH;
    }
  }
  
  private createVisuals(): void {
    const game = Game.getInstance();
    const scene = game.sceneManager;
    
    // Ground plane
    const groundGeo = new THREE.PlaneGeometry(this.width, this.height);
    const groundMat = new THREE.MeshStandardMaterial({ 
      color: 0x2d4a3e,
      roughness: 0.9,
      metalness: 0.1
    });
    const ground = new THREE.Mesh(groundGeo, groundMat);
    ground.rotation.x = -Math.PI / 2;
    ground.position.set(0, -0.01, 0);
    ground.receiveShadow = true;
    scene.add(ground);
    
    // Cell outlines
    const edgeGeo = new THREE.EdgesGeometry(
      new THREE.BoxGeometry(this.cellSize * 0.98, 0.1, this.cellSize * 0.98)
    );
    const edgeMat = new THREE.LineBasicMaterial({ color: 0x3d5a4e });
    
    for (let x = 0; x < this.width; x++) {
      for (let z = 0; z < this.height; z++) {
        const edges = new THREE.LineSegments(edgeGeo, edgeMat);
        edges.position.set(
          x - this.width / 2 + 0.5,
          0,
          z - this.height / 2 + 0.5
        );
        scene.add(edges);
      }
    }
    
    // Highlight mesh (for hover)
    const highlightGeo = new THREE.BoxGeometry(this.cellSize * 0.95, 0.15, this.cellSize * 0.95);
    const highlightMat = new THREE.MeshBasicMaterial({ 
      color: 0xffff00, 
      transparent: true, 
      opacity: 0.3 
    });
    this.highlightMesh = new THREE.Mesh(highlightGeo, highlightMat);
    this.highlightMesh.visible = false;
    scene.add(this.highlightMesh);
  }
  
  public update(dt: number): void {
    const game = Game.getInstance();
    const input = game.inputManager;
    const gridPos = input.getGridPosition();
    
    if (this.highlightMesh) {
      if (gridPos) {
        this.highlightMesh.position.set(
          gridPos.x - this.width / 2 + 0.5,
          0.1,
          gridPos.z - this.height / 2 + 0.5
        );
        this.highlightMesh.visible = true;
        
        // Change color based on validity
        const isValid = this.canPlaceTower(gridPos.x, gridPos.z);
        const mat = this.highlightMesh.material as THREE.MeshBasicMaterial;
        mat.color.setHex(isValid ? 0x00ff00 : 0xff0000);
      } else {
        this.highlightMesh.visible = false;
      }
    }
  }
  
  public onGridClick(x: number, z: number): void {
    if (this.canPlaceTower(x, z)) {
      this.placeTower(x, z);
    }
  }
  
  public deselectCell(): void {
    this.selectedCell = null;
  }
  
  public canPlaceTower(x: number, z: number): boolean {
    if (x < 0 || x >= this.width || z < 0 || z >= this.height) {
      return false;
    }
    return this.cells[x][z] === CellType.EMPTY;
  }
  
  public isPath(x: number, z: number): boolean {
    if (x < 0 || x >= this.width || z < 0 || z >= this.height) {
      return false;
    }
    return this.cells[x][z] === CellType.PATH;
  }
  
  public placeTower(x: number, z: number): boolean {
    if (!this.canPlaceTower(x, z)) return false;
    
    this.cells[x][z] = CellType.TOWER;
    return true;
  }
  
  public removeTower(x: number, z: number): void {
    if (x >= 0 && x < this.width && z >= 0 && z < this.height) {
      this.cells[x][z] = CellType.EMPTY;
    }
  }
  
  public getWorldPosition(x: number, z: number): THREE.Vector3 {
    return new THREE.Vector3(
      x - this.width / 2 + 0.5,
      0,
      z - this.height / 2 + 0.5
    );
  }
  
  public getWidth(): number { return this.width; }
  public getHeight(): number { return this.height; }
  public getCells(): CellType[][] { return this.cells; }
}
