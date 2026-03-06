// Input Handler - Manages keyboard and mouse input
export class InputHandler {
    constructor() {
        this.keys = {};
        this.mouse = { x: 0, y: 0, down: false };
        
        window.addEventListener('keydown', (e) => {
            this.keys[e.code] = true;
        });
        
        window.addEventListener('keyup', (e) => {
            this.keys[e.code] = false;
        });
        
        const canvas = document.getElementById('game-canvas');
        canvas.addEventListener('mousemove', (e) => {
            const rect = canvas.getBoundingClientRect();
            this.mouse.x = e.clientX - rect.left;
            this.mouse.y = e.clientY - rect.top;
        });
        
        canvas.addEventListener('mousedown', () => {
            this.mouse.down = true;
        });
        
        canvas.addEventListener('mouseup', () => {
            this.mouse.down = false;
        });
    }
    
    isKeyDown(code) {
        return this.keys[code] || false;
    }
    
    getMousePos() {
        return { x: this.mouse.x, y: this.mouse.y };
    }
}
