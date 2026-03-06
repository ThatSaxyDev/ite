import { InputHandler } from './systems/input.js';
import { Camera } from './systems/camera.js';
import { SoundSystem } from './systems/sound.js';
import { Player } from './entities/player.js';
import { Enemy } from './entities/enemy.js';
import { Projectile } from './entities/projectile.js';

class Game {
    constructor() {
        this.canvas = document.getElementById('game-canvas');
        this.ctx = this.canvas.getContext('2d');
        this.canvas.width = 1280;
        this.canvas.height = 720;
        
        this.input = new InputHandler();
        this.camera = new Camera(this.canvas.width, this.canvas.height);
        this.sound = new SoundSystem();
        
        this.state = 'menu'; // menu, playing, paused, gameover
        this.score = 0;
        this.wave = 1;
        this.lastTime = 0;
        
        this.player = null;
        this.projectiles = [];
        this.enemies = [];
        this.particles = [];
        this.pickups = [];
        
        this.waveTimer = 0;
        this.waveEnemiesRemaining = 0;
        
        this.setupUI();
    }
    
    setupUI() {
        document.getElementById('start-btn').addEventListener('click', () => this.start());
        document.getElementById('resume-btn').addEventListener('click', () => this.resume());
        document.getElementById('restart-btn').addEventListener('click', () => this.restart());
        document.getElementById('restart-btn-2').addEventListener('click', () => this.restart());
        
        window.addEventListener('keydown', (e) => {
            if (e.code === 'Escape' && this.state === 'playing') {
                this.pause();
            } else if (e.code === 'Escape' && this.state === 'paused') {
                this.resume();
            }
            
            // Weapon switching
            if (this.state === 'playing') {
                if (e.code === 'Digit1') this.player?.switchWeapon(0);
                if (e.code === 'Digit2') this.player?.switchWeapon(1);
                if (e.code === 'Digit3') this.player?.switchWeapon(2);
                if (e.code === 'Digit4') this.player?.switchWeapon(3);
            }
        });
    }
    
    start() {
        this.state = 'playing';
        this.score = 0;
        this.wave = 1;
        
        this.sound.init();
        
        this.player = new Player(this.canvas.width / 2, this.canvas.height / 2);
        this.projectiles = [];
        this.enemies = [];
        this.particles = [];
        this.pickups = [];
        
        this.spawnWave();
        
        document.getElementById('main-menu').classList.add('hidden');
        document.getElementById('game-over-menu').classList.add('hidden');
        document.getElementById('pause-menu').classList.add('hidden');
        
        this.lastTime = performance.now();
        requestAnimationFrame((t) => this.gameLoop(t));
    }
    
    pause() {
        this.state = 'paused';
        document.getElementById('pause-menu').classList.remove('hidden');
    }
    
    resume() {
        this.state = 'playing';
        document.getElementById('pause-menu').classList.add('hidden');
        this.lastTime = performance.now();
        requestAnimationFrame((t) => this.gameLoop(t));
    }
    
    restart() {
        this.start();
    }
    
    gameOver() {
        this.state = 'gameover';
        this.sound.playGameOver();
        document.getElementById('final-score').textContent = this.score;
        document.getElementById('game-over-menu').classList.remove('hidden');
    }
    
    spawnWave() {
        this.sound.playWaveStart();
        const enemyCount = 3 + this.wave * 2;
        this.waveEnemiesRemaining = enemyCount;
        
        for (let i = 0; i < enemyCount; i++) {
            const angle = (Math.PI * 2 / enemyCount) * i;
            const distance = 400 + Math.random() * 200;
            const x = this.player.x + Math.cos(angle) * distance;
            const y = this.player.y + Math.sin(angle) * distance;
            
            const type = Math.random() < 0.7 ? 'melee' : 'ranged';
            this.enemies.push(new Enemy(x, y, type));
        }
    }
    
    update(dt) {
        if (this.state !== 'playing') return;
        
        // Update player
        this.player.update(dt, this.input, this);
        
        // Update projectiles
        this.projectiles = this.projectiles.filter(p => p.update(dt, this));
        
        // Update enemies
        for (const enemy of this.enemies) {
            enemy.update(dt, this);
        }
        
        // Update particles
        this.particles = this.particles.filter(p => p.update(dt));
        
        // Update pickups
        this.pickups = this.pickups.filter(p => p.update(dt, this));
        
        // Check wave completion
        if (this.waveEnemiesRemaining <= 0) {
            this.wave++;
            this.spawnWave();
        }
        
        // Update camera
        this.camera.follow(this.player.x, this.player.y);
        
        // Update UI
        this.updateUI();
    }
    
    render() {
        // Clear canvas
        this.ctx.fillStyle = '#1a1a24';
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
        
        // Draw grid background
        this.drawGrid();
        
        this.ctx.save();
        this.ctx.translate(-this.camera.x, -this.camera.y);
        
        // Draw pickups
        for (const pickup of this.pickups) {
            pickup.render(this.ctx);
        }
        
        // Draw projectiles
        for (const projectile of this.projectiles) {
            projectile.render(this.ctx);
        }
        
        // Draw enemies
        for (const enemy of this.enemies) {
            enemy.render(this.ctx);
        }
        
        // Draw player
        if (this.player) {
            this.player.render(this.ctx);
        }
        
        // Draw particles
        for (const particle of this.particles) {
            particle.render(this.ctx);
        }
        
        this.ctx.restore();
    }
    
    drawGrid() {
        this.ctx.strokeStyle = '#2a2a3a';
        this.ctx.lineWidth = 1;
        
        const gridSize = 50;
        const offsetX = -this.camera.x % gridSize;
        const offsetY = -this.camera.y % gridSize;
        
        for (let x = offsetX; x < this.canvas.width; x += gridSize) {
            this.ctx.beginPath();
            this.ctx.moveTo(x, 0);
            this.ctx.lineTo(x, this.canvas.height);
            this.ctx.stroke();
        }
        
        for (let y = offsetY; y < this.canvas.height; y += gridSize) {
            this.ctx.beginPath();
            this.ctx.moveTo(0, y);
            this.ctx.lineTo(this.canvas.width, y);
            this.ctx.stroke();
        }
    }
    
    updateUI() {
        const healthPercent = (this.player.health / this.player.maxHealth) * 100;
        document.getElementById('health-bar').style.width = `${healthPercent}%`;
        
        const weapon = this.player.weapons[this.player.currentWeapon];
        document.getElementById('ammo-count').textContent = weapon.ammo;
        document.getElementById('weapon-name').textContent = weapon.name;
        
        document.getElementById('score').textContent = this.score;
        document.getElementById('wave').textContent = this.wave;
    }
    
    gameLoop(timestamp) {
        if (this.state !== 'playing') return;
        
        const dt = Math.min((timestamp - this.lastTime) / 1000, 0.1);
        this.lastTime = timestamp;
        
        this.update(dt);
        this.render();
        
        if (this.player.health <= 0) {
            this.gameOver();
            return;
        }
        
        requestAnimationFrame((t) => this.gameLoop(t));
    }
}

// Start game when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    new Game();
});
