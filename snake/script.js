const canvas = document.getElementById('game');
const ctx = canvas.getContext('2d');
const scoreEl = document.getElementById('score');
const highScoreEl = document.getElementById('highScore');
const speedLevelEl = document.getElementById('speedLevel');
const startBtn = document.getElementById('startBtn');
const pauseBtn = document.getElementById('pauseBtn');

const GRID_SIZE = 20;
const TILE_COUNT = canvas.width / GRID_SIZE;
const BASE_SPEED = 150;
const MIN_SPEED = 50;
const SPEED_INCREMENT = 15;

let snake = [];
let food = { x: 0, y: 0 };
let dx = 0;
let dy = 0;
let score = 0;
let highScore = localStorage.getItem('snakeHighScore') || 0;
let speedLevel = 1;
let gameLoop = null;
let isRunning = false;
let isPaused = false;

highScoreEl.textContent = highScore;

function initGame() {
    snake = [
        { x: 10, y: 10 },
        { x: 9, y: 10 },
        { x: 8, y: 10 }
    ];
    dx = 1;
    dy = 0;
    score = 0;
    speedLevel = 1;
    scoreEl.textContent = score;
    speedLevelEl.textContent = speedLevel;
    spawnFood();
    draw();
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
        score += 10 * speedLevel;
        scoreEl.textContent = score;
        
        // Increase speed every 50 points
        const newSpeedLevel = Math.floor(score / 50) + 1;
        if (newSpeedLevel > speedLevel && newSpeedLevel <= 10) {
            speedLevel = newSpeedLevel;
            speedLevelEl.textContent = speedLevel;
            updateGameSpeed();
        }
        
        spawnFood();
    } else {
        snake.pop();
    }
}

function updateGameSpeed() {
    clearInterval(gameLoop);
    const newSpeed = Math.max(MIN_SPEED, BASE_SPEED - (speedLevel - 1) * SPEED_INCREMENT);
    gameLoop = setInterval(gameLoopFn, newSpeed);
}

function draw() {
    // Clear with dark background
    ctx.fillStyle = '#0a0a14';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    // Draw grid
    ctx.strokeStyle = 'rgba(74, 222, 128, 0.05)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= TILE_COUNT; i++) {
        ctx.beginPath();
        ctx.moveTo(i * GRID_SIZE, 0);
        ctx.lineTo(i * GRID_SIZE, canvas.height);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(0, i * GRID_SIZE);
        ctx.lineTo(canvas.width, i * GRID_SIZE);
        ctx.stroke();
    }
    
    // Draw snake with glow effect
    ctx.shadowColor = '#4ade80';
    ctx.shadowBlur = 15;
    for (let i = 0; i < snake.length; i++) {
        ctx.fillStyle = i === 0 ? '#22c55e' : `rgb(${74 + i * 3}, ${222 - i * 2}, ${128})`;
        ctx.fillRect(snake[i].x * GRID_SIZE + 1, snake[i].y * GRID_SIZE + 1, GRID_SIZE - 2, GRID_SIZE - 2);
        
        // Eyes on head
        if (i === 0) {
            ctx.fillStyle = '#0a0a14';
            const eyeSize = 3;
            const eyeOffset = 5;
            if (dx === 1) {
                ctx.fillRect(snake[i].x * GRID_SIZE + 12, snake[i].y * GRID_SIZE + 5, eyeSize, eyeSize);
                ctx.fillRect(snake[i].x * GRID_SIZE + 12, snake[i].y * GRID_SIZE + 12, eyeSize, eyeSize);
            } else if (dx === -1) {
                ctx.fillRect(snake[i].x * GRID_SIZE + 5, snake[i].y * GRID_SIZE + 5, eyeSize, eyeSize);
                ctx.fillRect(snake[i].x * GRID_SIZE + 5, snake[i].y * GRID_SIZE + 12, eyeSize, eyeSize);
            } else if (dy === -1) {
                ctx.fillRect(snake[i].x * GRID_SIZE + 5, snake[i].y * GRID_SIZE + 5, eyeSize, eyeSize);
                ctx.fillRect(snake[i].x * GRID_SIZE + 12, snake[i].y * GRID_SIZE + 5, eyeSize, eyeSize);
            } else {
                ctx.fillRect(snake[i].x * GRID_SIZE + 5, snake[i].y * GRID_SIZE + 12, eyeSize, eyeSize);
                ctx.fillRect(snake[i].x * GRID_SIZE + 12, snake[i].y * GRID_SIZE + 12, eyeSize, eyeSize);
            }
        }
    }
    ctx.shadowBlur = 0;
    
    // Draw food with pulsing glow
    ctx.shadowColor = '#f43f5e';
    ctx.shadowBlur = 15 + Math.sin(Date.now() / 100) * 5;
    ctx.fillStyle = '#f43f5e';
    ctx.beginPath();
    const foodCenterX = food.x * GRID_SIZE + GRID_SIZE / 2;
    const foodCenterY = food.y * GRID_SIZE + GRID_SIZE / 2;
    ctx.arc(foodCenterX, foodCenterY, GRID_SIZE / 2 - 2, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
    
    // Food inner glow
    ctx.fillStyle = '#fb7185';
    ctx.beginPath();
    ctx.arc(foodCenterX, foodCenterY, GRID_SIZE / 4, 0, Math.PI * 2);
    ctx.fill();
}

function gameLoopFn() {
    if (!isPaused) {
        update();
        draw();
    }
}

function gameOver() {
    isRunning = false;
    clearInterval(gameLoop);
    
    if (score > highScore) {
        highScore = score;
        localStorage.setItem('snakeHighScore', highScore);
        highScoreEl.textContent = highScore;
    }
    
    startBtn.textContent = 'Play Again';
    pauseBtn.textContent = '⏸';
    alert(`Game Over! Score: ${score}\nSpeed Level: ${speedLevel}`);
}

function startGame() {
    if (isRunning) return;
    initGame();
    isRunning = true;
    isPaused = false;
    startBtn.textContent = 'Restart';
    pauseBtn.textContent = '⏸';
    gameLoop = setInterval(gameLoopFn, BASE_SPEED);
}

function togglePause() {
    if (!isRunning) return;
    
    isPaused = !isPaused;
    pauseBtn.textContent = isPaused ? '▶' : '⏸';
    
    if (isPaused) {
        // Draw pause overlay on canvas
        ctx.fillStyle = 'rgba(10, 10, 20, 0.7)';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        
        ctx.fillStyle = '#4ade80';
        ctx.font = 'bold 36px Courier New';
        ctx.textAlign = 'center';
        ctx.shadowColor = '#4ade80';
        ctx.shadowBlur = 20;
        ctx.fillText('PAUSED', canvas.width / 2, canvas.height / 2);
        ctx.shadowBlur = 0;
        ctx.textAlign = 'start';
    } else {
        draw();
    }
}

function changeDirection(newDx, newDy) {
    if (!isRunning || isPaused) return;
    
    // Prevent reversing
    if (newDx !== 0 && dx === -newDx) return;
    if (newDy !== 0 && dy === -newDy) return;
    
    dx = newDx;
    dy = newDy;
}

// Keyboard controls
document.addEventListener('keydown', (e) => {
    switch(e.key) {
        case 'ArrowUp':
        case 'w':
        case 'W':
            e.preventDefault();
            changeDirection(0, -1);
            break;
        case 'ArrowDown':
        case 's':
        case 'S':
            e.preventDefault();
            changeDirection(0, 1);
            break;
        case 'ArrowLeft':
        case 'a':
        case 'A':
            e.preventDefault();
            changeDirection(-1, 0);
            break;
        case 'ArrowRight':
        case 'd':
        case 'D':
            e.preventDefault();
            changeDirection(1, 0);
            break;
        case ' ':
        case 'p':
        case 'P':
            e.preventDefault();
            togglePause();
            break;
    }
});

// Button controls
startBtn.addEventListener('click', startGame);
pauseBtn.addEventListener('click', togglePause);

// Mobile touch controls
document.getElementById('upBtn').addEventListener('click', () => changeDirection(0, -1));
document.getElementById('downBtn').addEventListener('click', () => changeDirection(0, 1));
document.getElementById('leftBtn').addEventListener('click', () => changeDirection(-1, 0));
document.getElementById('rightBtn').addEventListener('click', () => changeDirection(1, 0));

// Initial draw
initGame();