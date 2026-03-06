const canvas = document.getElementById('game');
const ctx = canvas.getContext('2d');
const scoreEl = document.getElementById('score');
const startBtn = document.getElementById('startBtn');

const GRID_SIZE = 20;
const TILE_COUNT = canvas.width / GRID_SIZE;

let snake = [];
let food = { x: 0, y: 0 };
let dx = 0;
let dy = 0;
let score = 0;
let gameLoop = null;
let isRunning = false;

function initGame() {
    snake = [
        { x: 10, y: 10 },
        { x: 9, y: 10 },
        { x: 8, y: 10 }
    ];
    dx = 1;
    dy = 0;
    score = 0;
    scoreEl.textContent = score;
    spawnFood();
}

function spawnFood() {
    food.x = Math.floor(Math.random() * TILE_COUNT);
    food.y = Math.floor(Math.random() * TILE_COUNT);
    
    for (let part of snake) {
        if (part.x === food.x && part.y === food.y) {
            spawnFood();
            break;
        }
    }
}

function update() {
    const head = { x: snake[0].x + dx, y: snake[0].y + dy };
    
    if (head.x < 0 || head.x >= TILE_COUNT || head.y < 0 || head.y >= TILE_COUNT) {
        gameOver();
        return;
    }
    
    for (let part of snake) {
        if (head.x === part.x && head.y === part.y) {
            gameOver();
            return;
        }
    }
    
    snake.unshift(head);
    
    if (head.x === food.x && head.y === food.y) {
        score += 10;
        scoreEl.textContent = score;
        spawnFood();
    } else {
        snake.pop();
    }
}

function draw() {
    ctx.fillStyle = '#0f0f1a';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    ctx.fillStyle = '#4ade80';
    for (let i = 0; i < snake.length; i++) {
        ctx.fillStyle = i === 0 ? '#22c55e' : '#4ade80';
        ctx.fillRect(snake[i].x * GRID_SIZE + 1, snake[i].y * GRID_SIZE + 1, GRID_SIZE - 2, GRID_SIZE - 2);
    }
    
    ctx.fillStyle = '#f43f5e';
    ctx.fillRect(food.x * GRID_SIZE + 2, food.y * GRID_SIZE + 2, GRID_SIZE - 4, GRID_SIZE - 4);
}

function gameLoopFn() {
    update();
    draw();
}

function gameOver() {
    isRunning = false;
    clearInterval(gameLoop);
    startBtn.textContent = 'Play Again';
    alert(`Game Over! Score: ${score}`);
}

function startGame() {
    if (isRunning) return;
    initGame();
    isRunning = true;
    startBtn.textContent = 'Restart';
    gameLoop = setInterval(gameLoopFn, 100);
}

document.addEventListener('keydown', (e) => {
    if (!isRunning) return;
    
    switch(e.key) {
        case 'ArrowUp':
        case 'w':
        case 'W':
            if (dy !== 1) { dx = 0; dy = -1; }
            break;
        case 'ArrowDown':
        case 's':
        case 'S':
            if (dy !== -1) { dx = 0; dy = 1; }
            break;
        case 'ArrowLeft':
        case 'a':
        case 'A':
            if (dx !== 1) { dx = -1; dy = 0; }
            break;
        case 'ArrowRight':
        case 'd':
        case 'D':
            if (dx !== -1) { dx = 1; dy = 0; }
            break;
    }
});

startBtn.addEventListener('click', startGame);
