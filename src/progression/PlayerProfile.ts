export class PlayerProfile {
  public gold: number = 200;
  public lives: number = 20;
  public level: number = 1;
  public experience: number = 0;
  public unlockedTowers: string[] = ['arrow'];
  public towerUpgrades: Record<string, number> = {
    arrow: 0,
    cannon: 0,
    ice: 0
  };
  public heroLevel: number = 1;
  public completedLevels: number[] = [];
  
  constructor() {
    this.load();
  }
  
  public addExperience(amount: number): void {
    this.experience += amount;
    this.checkLevelUp();
  }
  
  private checkLevelUp(): void {
    const expNeeded = this.level * 100;
    while (this.experience >= expNeeded) {
      this.experience -= expNeeded;
      this.level++;
    }
  }
  
  public unlockTower(towerType: string): void {
    if (!this.unlockedTowers.includes(towerType)) {
      this.unlockedTowers.push(towerType);
      this.save();
    }
  }
  
  public upgradeTower(towerType: string): void {
    if (this.towerUpgrades[towerType] !== undefined) {
      this.towerUpgrades[towerType]++;
      this.save();
    }
  }
  
  public completeLevel(levelId: number): void {
    if (!this.completedLevels.includes(levelId)) {
      this.completedLevels.push(levelId);
      this.save();
    }
  }
  
  public save(): void {
    const data = {
      gold: this.gold,
      lives: this.lives,
      level: this.level,
      experience: this.experience,
      unlockedTowers: this.unlockedTowers,
      towerUpgrades: this.towerUpgrades,
      heroLevel: this.heroLevel,
      completedLevels: this.completedLevels
    };
    localStorage.setItem('towerDefenseProfile', JSON.stringify(data));
  }
  
  public load(): void {
    const saved = localStorage.getItem('towerDefenseProfile');
    if (saved) {
      try {
        const data = JSON.parse(saved);
        this.gold = data.gold ?? 200;
        this.lives = data.lives ?? 20;
        this.level = data.level ?? 1;
        this.experience = data.experience ?? 0;
        this.unlockedTowers = data.unlockedTowers ?? ['arrow'];
        this.towerUpgrades = data.towerUpgrades ?? { arrow: 0, cannon: 0, ice: 0 };
        this.heroLevel = data.heroLevel ?? 1;
        this.completedLevels = data.completedLevels ?? [];
      } catch (e) {
        console.error('Failed to load profile:', e);
      }
    }
  }
  
  public reset(): void {
    this.gold = 200;
    this.lives = 20;
    this.level = 1;
    this.experience = 0;
    this.unlockedTowers = ['arrow'];
    this.towerUpgrades = { arrow: 0, cannon: 0, ice: 0 };
    this.heroLevel = 1;
    this.completedLevels = [];
    this.save();
  }
}
