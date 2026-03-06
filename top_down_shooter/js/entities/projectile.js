export class Projectile {
    constructor(x, y, vx, vy, damage, isPlayer = false) {
        this.x = x;
        this.y = y;
        this.vx = vx;
        this.vy = vy;
        this.damage = damage;
        this.isPlayer = isPlayer;
        this.radius = 5;
        this.lifetime = 2;
    }
    
    update(dt, game) {
        this.x += this.vx * dt;
        this.y += this.vy * dt;
        this.lifetime -= dt;
        
        // Check collisions
        if (this.isPlayer) {
            // Check enemy collisions
            for (const enemy of game.enemies) {
                const dx = enemy.x - this.x;
                const dy = enemy.y - this.y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                
                if (dist < enemy.radius + this.radius) {
                    enemy.takeDamage(this.damage);
                    this.lifetime = 0;
                    
                    // Create hit particles
                    for (let i = 0; i < 5; i++) {
                        game.particles.push({
                            x: this.x,
                            y: this.y,
                            vx: (Math.random() - 0.5) * 200,
                            vy: (Math.random() - 0.5) * 200,
                            life: 0.3,
                            maxLife: 0.3,
                            color: '#e74c3c',
                            size: 4,
                            update: function(dt) {
                                this.x += this.vx * dt;
                                this.y += this.vy * dt;
                                this.life -= dt;
                                return this.life > 0;
                            },
                            render: function(ctx) {
                                ctx.globalAlpha = this.life / this.maxLife;
                                ctx.fillStyle = this.color;
                                ctx.beginPath();
                                ctx.arc(this.x, this.y, this.size * (this.life / this.maxLife), 0, Math.PI * 2);
                                ctx.fill();
                                ctx.globalAlpha = 1;
                            }
                        });
                    }
                    
                    game.camera.shake(2);
                    break;
                }
            }
        } else {
            // Check player collision
            const dx = game.player.x - this.x;
            const dy = game.player.y - this.y;
            const dist = Math.sqrt(dx * dx + dy * dy);
            
            if (dist < game.player.radius + this.radius) {
                game.player.takeDamage(this.damage);
                this.lifetime = 0;
                game.camera.shake(5);
            }
        }
        
        return this.lifetime > 0;
    }
    
    render(ctx) {
        ctx.fillStyle = this.isPlayer ? '#f1c40f' : '#e74c3c';
        ctx.beginPath();
        ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
        ctx.fill();
    }
}
