import { GridSystem, CellType } from '../grid/GridSystem';

interface PathNode {
  x: number;
  z: number;
  g: number;
  h: number;
  f: number;
  parent: PathNode | null;
}

export class Pathfinder {
  private grid: GridSystem;
  
  constructor(grid: GridSystem) {
    this.grid = grid;
  }
  
  public findPath(startX: number, startZ: number, endX: number, endZ: number): { x: number; z: number }[] | null {
    const width = this.grid.getWidth();
    const height = this.grid.getHeight();
    const cells = this.grid.getCells();
    
    // Validate start and end
    if (!this.isValidCell(startX, startZ) || !this.isValidCell(endX, endZ)) {
      return null;
    }
    
    const startNode: PathNode = { x: startX, z: startZ, g: 0, h: 0, f: 0, parent: null };
    const openList: PathNode[] = [startNode];
    const closedList: boolean[][] = [];
    
    // Initialize closed list
    for (let x = 0; x < width; x++) {
      closedList[x] = [];
      for (let z = 0; z < height; z++) {
        closedList[x][z] = false;
      }
    }
    
    while (openList.length > 0) {
      // Get node with lowest f score
      let currentIndex = 0;
      for (let i = 1; i < openList.length; i++) {
        if (openList[i].f < openList[currentIndex].f) {
          currentIndex = i;
        }
      }
      
      const current = openList[currentIndex];
      
      // Check if reached goal
      if (current.x === endX && current.z === endZ) {
        return this.reconstructPath(current);
      }
      
      // Move from open to closed
      openList.splice(currentIndex, 1);
      closedList[current.x][current.z] = true;
      
      // Check neighbors (4-directional)
      const neighbors = [
        { x: current.x - 1, z: current.z },
        { x: current.x + 1, z: current.z },
        { x: current.x, z: current.z - 1 },
        { x: current.x, z: current.z + 1 }
      ];
      
      for (const neighbor of neighbors) {
        if (!this.isValidCell(neighbor.x, neighbor.z)) continue;
        if (closedList[neighbor.x][neighbor.z]) continue;
        
        // Can only move through paths or empty cells
        if (cells[neighbor.x][neighbor.z] !== CellType.PATH && 
            cells[neighbor.x][neighbor.z] !== CellType.EMPTY) {
          continue;
        }
        
        const gScore = current.g + 1;
        const hScore = this.heuristic(neighbor.x, neighbor.z, endX, endZ);
        
        // Check if already in open list
        const existingNode = openList.find(n => n.x === neighbor.x && n.z === neighbor.z);
        
        if (!existingNode) {
          const newNode: PathNode = {
            x: neighbor.x,
            z: neighbor.z,
            g: gScore,
            h: hScore,
            f: gScore + hScore,
            parent: current
          };
          openList.push(newNode);
        } else if (gScore < existingNode.g) {
          existingNode.g = gScore;
          existingNode.f = gScore + existingNode.h;
          existingNode.parent = current;
        }
      }
    }
    
    return null; // No path found
  }
  
  private isValidCell(x: number, z: number): boolean {
    const width = this.grid.getWidth();
    const height = this.grid.getHeight();
    return x >= 0 && x < width && z >= 0 && z < height;
  }
  
  private heuristic(x1: number, z1: number, x2: number, z2: number): number {
    // Manhattan distance
    return Math.abs(x1 - x2) + Math.abs(z1 - z2);
  }
  
  private reconstructPath(node: PathNode): { x: number; z: number }[] {
    const path: { x: number; z: number }[] = [];
    let current: PathNode | null = node;
    
    while (current) {
      path.unshift({ x: current.x, z: current.z });
      current = current.parent;
    }
    
    return path;
  }
  
  public findPathFromEdge(startEdge: 'left' | 'right' | 'top' | 'bottom', endX: number, endZ: number): { x: number; z: number }[] | null {
    let startX: number, startZ: number;
    const width = this.grid.getWidth();
    const height = this.grid.getHeight();
    
    switch (startEdge) {
      case 'left':
        startX = 0;
        startZ = Math.floor(height / 2);
        break;
      case 'right':
        startX = width - 1;
        startZ = Math.floor(height / 2);
        break;
      case 'top':
        startX = Math.floor(width / 2);
        startZ = 0;
        break;
      case 'bottom':
        startX = Math.floor(width / 2);
        startZ = height - 1;
        break;
    }
    
    return this.findPath(startX, startZ, endX, endZ);
  }
}
