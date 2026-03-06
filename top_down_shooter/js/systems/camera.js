export class Camera {
    constructor(width, height) {
        this.x = 0;
        this.y = 0;
        this.width = width;
        this.height = height;
        
        this.shakeAmount = 0;
        this.shakeDecay = 10;
    }
    
    follow(targetX, targetY) {
        // Center on target with smooth following
        this.x = targetX - this.width / 2;
        this.y = targetY - this.height / 2;
        
        // Apply shake
        if (this.shakeAmount > 0) {
            this.x += (Math.random() - 0.5) * this.shakeAmount;
            this.y += (Math.random() - 0.5) * this.shakeAmount;
            this.shakeAmount -= this.shakeDecay * (1/60); // Approximate
            if (this.shakeAmount < 0) this.shakeAmount = 0;
        }
        
        // Clamp to world bounds
        this.x = Math.max(0, Math.min(this.x, 2000 - this.width));
        this.y = Math.max(0, Math.min(this.y, 2000 - this.height));
    }
    
    shake(amount) {
        this.shakeAmount = amount;
    }
}
