export class Player {
    constructor(x, y) {
        this.x = x;
        this.y = y;
        this.radius = 20;
        this.speed = 300;
        this.health = 100;
        this.maxHealth = 100;
        
        this.angle = 0;
        
        this.weapons = [
            { name: 'Pistol', damage: 25, fireRate: 0.4, ammo: 999, maxAmmo: 999, spread: 0, projectileSpeed: 600, projectileCount: 1 },
            { name: 'Shotgun', damage: 15, fireRate: 0.8, ammo: 20, maxAmmo: 50, spread: 0.3, projectileSpeed: 500, projectileCount: 5 },
            { name: 'Machine Gun', damage: 12, fireRate: 0.1, ammo: 100, maxAmmo: 200, spread: 0.1, projectileSpeed: 550, projectileCount: 1 },
            { name: 'Sniper', damage: 80, fireRate: 1.2, ammo: 10, maxAmmo: 20, spread: 0, projectileSpeed: 1000, projectileCount: 1 }
        ];
        this.currentWeapon = 0;
        this.lastShot = 0;
    }
    
    update(dt, input, game) {
        // Movement
        let dx = 0;
        let dy = 0;
        
        if (input.isKeyDown('KeyW')) dy -= 1;
        if (input.isKeyDown('KeyS')) dy += 1;
        if (input.isKeyDown('KeyA')) dx -= 1;
        if (input.isKeyDown('KeyD')) dx += 1;
        
        // Normalize diagonal movement
        if (dx !== 0 && dy !== 0) {
            const length = Math.sqrt(dx * dx + dy * dy);
            dx /= length;
            dy /= length;
        }
        
        this.x += dx * this.speed * dt;
        this.y += dy * this.speed * dt;
        
        // Keep in bounds
        this.x = Math.max(this.radius, Math.min(this.x, 2000 - this.radius));
        this.y = Math.max(this.radius, Math.min(this.y, 2000 - this.radius));
        
        // Aiming
        const mousePos = input.getMousePos();
        const screenX = this.x - game.camera.x;
        const screenY = this.y - game.camera.y;
        this.angle = Math.atan2(mousePos.y - screenY, mousePos.x - screenX);
        
        // Shooting
        const weapon = this.weapons[this.currentWeapon];
        if (input.mouse.down && Date.now() - this.lastShot > weapon.fireRate * 1000 && weapon.ammo > 0) {
            this.shoot(game);
            this.lastShot = Date.now();
        }
    }
    
    switchWeapon(index) {
        if (index >= 0 && index < this.weapons.length) {
            this.currentWeapon = index;
        }
    }
    
    shoot(game) {
        const weapon = this.weapons[this.currentWeapon];
        
        for (let i = 0; i < weapon.projectileCount; i++) {
            const spreadAngle = (Math.random() - 0.5) * weapon.spread;
            const angle = this.angle + spreadAngle;
            
            game.projectiles.push({
                x: this.x + Math.cos(this.angle) * 30,
                y: this.y + Math.sin(this.angle) * 30,
                vx: Math.cos(angle) * weapon.projectileSpeed,
                vy: Math.sin(angle) * weapon.projectileSpeed,
                damage: weapon.damage,
                isPlayer: true,
                radius: 5,
                lifetime: 2,
                update: function(dt) {
                    this.x += this.vx * dt;
                    this.y += this.vy * dt;
                    this.lifetime -= dt;
                    return this.lifetime > 0;
                },
                render: function(ctx) {
                    ctx.fillStyle = '#f1c40f';
                    ctx.beginPath();
                    ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
                    ctx.fill();
                }
            });
        }
        
        weapon.ammo--;
        
        // Play sound and screen shake
        game.sound.playShoot();
        game.camera.shake(3);
    }
    
    takeDamage(amount) {
        this.health -= amount;
    }
    
    render(ctx) {
        ctx.save();
        ctx.translate(this.x, this.y);
        ctx.rotate(this.angle);
        
        // Body
        ctx.fillStyle = '#3498db';
        ctx.beginPath();
        ctx.arc(0, 0, this.radius, 0, Math.PI * 2);
        ctx.fill();
        
        // Gun
        ctx.fillStyle = '#2c3e50';
        ctx.fillRect(10, -4, 25, 8);
        
        // Direction indicator
        ctx.fillStyle = '#ecf0f1';
        ctx.beginPath();
        ctx.arc(12, 0, 4, 0, Math.PI * 2);
        ctx.fill();
        
        ctx.restore();
    }
}
