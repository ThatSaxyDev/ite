export class Enemy {
    constructor(x, y, type = 'melee') {
        this.x = x;
        this.y = y;
        this.type = type;
        
        if (type === 'melee') {
            this.radius = 18;
            this.speed = 120;
            this.health = 50;
            this.maxHealth = 50;
            this.damage = 15;
            this.color = '#e74c3c';
        } else if (type === 'ranged') {
            this.radius = 20;
            this.speed = 80;
            this.health = 40;
            this.maxHealth = 40;
            this.damage = 20;
            this.color = '#9b59b6';
            this.shootRange = 300;
            this.lastShot = 0;
            this.fireRate = 1.5;
        }
        
        this.angle = 0;
        this.pushX = 0;
        this.pushY = 0;
    }
    
    update(dt, game) {
        const dx = game.player.x - this.x;
        const dy = game.player.y - this.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        
        this.angle = Math.atan2(dy, dx);
        
        // Push recovery
        this.pushX *= 0.9;
        this.pushY *= 0.9;
        
        if (this.type === 'melee') {
            // Chase player
            if (dist > this.radius + game.player.radius + 10) {
                this.x += Math.cos(this.angle) * this.speed * dt;
                this.y += Math.sin(this.angle) * this.speed * dt;
            }
            
            // Deal damage when touching
            if (dist < this.radius + game.player.radius) {
                game.player.takeDamage(this.damage * dt);
            }
        } else if (this.type === 'ranged') {
            // Keep distance
            if (dist < this.shootRange - 50) {
                this.x -= Math.cos(this.angle) * this.speed * dt;
                this.y -= Math.sin(this.angle) * this.speed * dt;
            } else if (dist > this.shootRange + 50) {
                this.x += Math.cos(this.angle) * this.speed * dt;
                this.y += Math.sin(this.angle) * this.speed * dt;
            }
            
            // Shoot at player
            if (dist < this.shootRange && Date.now() - this.lastShot > this.fireRate * 1000) {
                this.shoot(game);
                this.lastShot = Date.now();
            }
        }
        
        // Apply push
        this.x += this.pushX * dt;
        this.y += this.pushY * dt;
        
        // Keep in bounds
        this.x = Math.max(this.radius, Math.min(this.x, 2000 - this.radius));
        this.y = Math.max(this.radius, Math.min(this.y, 2000 - this.radius));
        
        // Collision with other enemies
        for (const other of game.enemies) {
            if (other === this) continue;
            const odx = other.x - this.x;
            const ody = other.y - this.y;
            const odist = Math.sqrt(odx * odx + ody * ody);
            if (odist < this.radius + other.radius) {
                const overlap = (this.radius + other.radius - odist) / 2;
                this.x -= (odx / odist) * overlap;
                this.y -= (ody / odist) * overlap;
            }
        }
    }
    
    shoot(game) {
        game.projectiles.push({
            x: this.x + Math.cos(this.angle) * 25,
            y: this.y + Math.sin(this.angle) * 25,
            vx: Math.cos(this.angle) * 350,
            vy: Math.sin(this.angle) * 350,
            damage: this.damage,
            isPlayer: false,
            radius: 6,
            lifetime: 3,
            update: function(dt) {
                this.x += this.vx * dt;
                this.y += this.vy * dt;
                this.lifetime -= dt;
                return this.lifetime > 0;
            },
            render: function(ctx) {
                ctx.fillStyle = '#e74c3c';
                ctx.beginPath();
                ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
                ctx.fill();
            }
        });
    }
    
    takeDamage(amount) {
        this.health -= amount;
        
        // Push back
        const pushForce = 100;
        this.pushX = -Math.cos(this.angle) * pushForce;
        this.pushY = -Math.sin(this.angle) * pushForce;
    }
    
    render(ctx) {
        ctx.save();
        ctx.translate(this.x, this.y);
        
        // Body
        ctx.fillStyle = this.color;
        ctx.beginPath();
        ctx.arc(0, 0, this.radius, 0, Math.PI * 2);
        ctx.fill();
        
        // Eye/direction
        ctx.fillStyle = '#fff';
        ctx.beginPath();
        ctx.arc(Math.cos(this.angle) * 8, Math.sin(this.angle) * 8, 5, 0, Math.PI * 2);
        ctx.fill();
        
        // Health bar
        const healthPercent = this.health / this.maxHealth;
        ctx.fillStyle = '#2c3e50';
        ctx.fillRect(-15, -this.radius - 12, 30, 5);
        ctx.fillStyle = healthPercent > 0.5 ? '#2ecc71' : '#e74c3c';
        ctx.fillRect(-15, -this.radius - 12, 30 * healthPercent, 5);
        
        ctx.restore();
    }
}
