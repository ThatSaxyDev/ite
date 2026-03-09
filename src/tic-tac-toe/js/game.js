// Game Configuration
const CONFIG = {
    boardSize: 3,
    tileSize: 2,
    tileGap: 0.2,
    colors: {
        background: 0x0a0a1a,
        tile: 0x1a1a3e,
        tileHover: 0x2a2a5e,
        tileGlow: 0x00ffff,
        xColor: 0xff0066,
        oColor: 0x00ff66,
        winLine: 0xffff00,
        gridLine: 0xff00ff
    },
    animations: {
        pieceScaleSpeed: 0.15,
        piecePopScale: 1.2
    }
};

// Game State
let gameState = {
    board: Array(9).fill(null),
    currentPlayer: 'X',
    gameMode: 'pvp', // 'pvp' or 'pve'
    difficulty: 'easy',
    gameOver: false,
    winner: null,
    pieces: []
};

// ThreeJS Variables
let scene, camera, renderer, raycaster, mouse;
let tiles = [];
let hoverMarker;
let tileGroup;
let hoveredTile = null;

// DOM Elements
const statusText = document.getElementById('status-text');
const currentModeText = document.getElementById('current-mode');
const modeSelect = document.getElementById('mode-select');
const difficultyGroup = document.getElementById('difficulty-group');
const difficultySelect = document.getElementById('difficulty-select');
const resetBtn = document.getElementById('reset-btn');
const winnerModal = document.getElementById('winner-modal');
const winnerText = document.getElementById('winner-text');
const playAgainBtn = document.getElementById('play-again-btn');

// Initialize
console.log('Initializing game...');
init();
animate();

function init() {
    console.log('init called');
    // Scene
    scene = new THREE.Scene();
    scene.background = new THREE.Color(CONFIG.colors.background);

    // Camera
    camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.set(0, 6, 8);
    camera.lookAt(0, 0, 0);

    // Renderer
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(window.devicePixelRatio);
    document.getElementById('game-container').appendChild(renderer.domElement);

    // Raycaster for click detection
    raycaster = new THREE.Raycaster();
    raycaster.params.Mesh.threshold = 0.5;
    mouse = new THREE.Vector2();

    // Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
    scene.add(ambientLight);

    const pointLight1 = new THREE.PointLight(0xff00ff, 1, 50);
    pointLight1.position.set(5, 10, 5);
    scene.add(pointLight1);

    const pointLight2 = new THREE.PointLight(0x00ffff, 1, 50);
    pointLight2.position.set(-5, 10, -5);
    scene.add(pointLight2);

    // Create game board
    createBoard();

    // Create hover marker (shows where click will happen)
    createHoverMarker();

    // Create grid lines
    createGridLines();

    // Event listeners
    window.addEventListener('resize', onWindowResize);
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('click', onMouseClick);
    
    // Touch support
    window.addEventListener('touchstart', onTouchStart, { passive: false });

    // UI Event listeners
    modeSelect.addEventListener('change', onModeChange);
    difficultySelect.addEventListener('change', onDifficultyChange);
    resetBtn.addEventListener('click', () => {
        console.log('Reset button clicked!');
        resetGame();
    });
    playAgainBtn.addEventListener('click', () => {
        console.log('Play again button clicked!');
        resetGame();
    });

    // Initial UI update
    onModeChange();
}

function createBoard() {
    tileGroup = new THREE.Group();
    
    const totalSize = CONFIG.boardSize * CONFIG.tileSize + (CONFIG.boardSize - 1) * CONFIG.tileGap;
    const offset = totalSize / 2 - CONFIG.tileSize / 2;

    for (let i = 0; i < 9; i++) {
        const row = Math.floor(i / 3);
        const col = i % 3;
        
        const x = col * (CONFIG.tileSize + CONFIG.tileGap) - offset;
        const z = row * (CONFIG.tileSize + CONFIG.tileGap) - offset;

        const tileGeometry = new THREE.BoxGeometry(CONFIG.tileSize, 0.6, CONFIG.tileSize);
        const tileMaterial = new THREE.MeshStandardMaterial({
            color: 0x3a3a6e,
            emissive: CONFIG.colors.tile,
            emissiveIntensity: 0.3,
            metalness: 0.5,
            roughness: 0.5
        });
        
        const tile = new THREE.Mesh(tileGeometry, tileMaterial);
        tile.position.set(x, -0.3, z);
        tile.userData = { index: i, isTile: true };
        
        // Add invisible hitbox for easier clicking
        const hitboxGeometry = new THREE.BoxGeometry(CONFIG.tileSize * 1.5, 2, CONFIG.tileSize * 1.5);
        const hitboxMaterial = new THREE.MeshBasicMaterial({ visible: false });
        const hitbox = new THREE.Mesh(hitboxGeometry, hitboxMaterial);
        hitbox.position.set(x, 0.5, z);
        hitbox.userData = { index: i, isTile: true, isHitbox: true };
        tileGroup.add(hitbox);
        tiles.push(hitbox);
        
        // Add glow edge
        const edgeGeometry = new THREE.EdgesGeometry(tileGeometry);
        const edgeMaterial = new THREE.LineBasicMaterial({ 
            color: CONFIG.colors.tileGlow,
            linewidth: 2
        });
        const edges = new THREE.LineSegments(edgeGeometry, edgeMaterial);
        tile.add(edges);

        // Only add hitbox to tiles array for raycasting (not the visible tile)
        // This ensures clicks are detected on the larger hitbox area
    }

    scene.add(tileGroup);
}

function createHoverMarker() {
    // Create a visible ring that shows which cell is being hovered
    const geometry = new THREE.RingGeometry(0.7, 0.9, 32);
    const material = new THREE.MeshBasicMaterial({ 
        color: 0xffff00, 
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.6
    });
    hoverMarker = new THREE.Mesh(geometry, material);
    hoverMarker.rotation.x = -Math.PI / 2;
    hoverMarker.position.y = 0.1;
    hoverMarker.visible = false;
    hoverMarker.userData = { isHoverMarker: true };
    scene.add(hoverMarker);
}

function createGridLines() {
    const totalSize = CONFIG.boardSize * CONFIG.tileSize + (CONFIG.boardSize - 1) * CONFIG.tileGap;
    const offset = totalSize / 2;
    
    // Create glowing grid lines
    const lineMaterial = new THREE.LineBasicMaterial({ 
        color: CONFIG.colors.gridLine,
        linewidth: 2
    });

    // Vertical lines
    for (let i = 1; i < 3; i++) {
        const x = -offset + i * (CONFIG.tileSize + CONFIG.tileGap);
        const points = [
            new THREE.Vector3(x, 0.01, -offset - CONFIG.tileSize/2),
            new THREE.Vector3(x, 0.01, offset + CONFIG.tileSize/2)
        ];
        const geometry = new THREE.BufferGeometry().setFromPoints(points);
        const line = new THREE.Line(geometry, lineMaterial);
        scene.add(line);
    }

    // Horizontal lines
    for (let i = 1; i < 3; i++) {
        const z = -offset + i * (CONFIG.tileSize + CONFIG.tileGap);
        const points = [
            new THREE.Vector3(-offset - CONFIG.tileSize/2, 0.01, z),
            new THREE.Vector3(offset + CONFIG.tileSize/2, 0.01, z)
        ];
        const geometry = new THREE.BufferGeometry().setFromPoints(points);
        const line = new THREE.Line(geometry, lineMaterial);
        scene.add(line);
    }
}

function createPiece(type, index) {
    const row = Math.floor(index / 3);
    const col = index % 3;
    const totalSize = CONFIG.boardSize * CONFIG.tileSize + (CONFIG.boardSize - 1) * CONFIG.tileGap;
    const offset = totalSize / 2 - CONFIG.tileSize / 2;
    
    const x = col * (CONFIG.tileSize + CONFIG.tileGap) - offset;
    const z = row * (CONFIG.tileSize + CONFIG.tileGap) - offset;

    let piece;
    
    if (type === 'X') {
        // Create X shape using two cylinders
        piece = new THREE.Group();
        
        const armMaterial = new THREE.MeshStandardMaterial({
            color: CONFIG.colors.xColor,
            emissive: CONFIG.colors.xColor,
            emissiveIntensity: 0.3,
            metalness: 0.7,
            roughness: 0.3
        });
        
        const armGeometry = new THREE.CylinderGeometry(0.15, 0.15, 1.2, 8);
        
        const arm1 = new THREE.Mesh(armGeometry, armMaterial);
        arm1.rotation.z = Math.PI / 4;
        
        const arm2 = new THREE.Mesh(armGeometry, armMaterial);
        arm2.rotation.z = -Math.PI / 4;
        
        piece.add(arm1);
        piece.add(arm2);
        
        // Glow effect
        const glowGeometry = new THREE.SphereGeometry(0.8, 16, 16);
        const glowMaterial = new THREE.MeshBasicMaterial({
            color: CONFIG.colors.xColor,
            transparent: true,
            opacity: 0.15
        });
        const glow = new THREE.Mesh(glowGeometry, glowMaterial);
        piece.add(glow);
    } else {
        // Create O shape using torus
        piece = new THREE.Group();
        
        const ringMaterial = new THREE.MeshStandardMaterial({
            color: CONFIG.colors.oColor,
            emissive: CONFIG.colors.oColor,
            emissiveIntensity: 0.3,
            metalness: 0.7,
            roughness: 0.3
        });
        
        const ringGeometry = new THREE.TorusGeometry(0.4, 0.15, 16, 32);
        const ring = new THREE.Mesh(ringGeometry, ringMaterial);
        ring.rotation.x = Math.PI / 2;
        piece.add(ring);
        
        // Glow effect
        const glowGeometry = new THREE.TorusGeometry(0.4, 0.25, 16, 32);
        const glowMaterial = new THREE.MeshBasicMaterial({
            color: CONFIG.colors.oColor,
            transparent: true,
            opacity: 0.15
        });
        const glow = new THREE.Mesh(glowGeometry, glowMaterial);
        glow.rotation.x = Math.PI / 2;
        piece.add(glow);
    }
    
    piece.position.set(x, 0.6, z);
    piece.scale.set(0, 0, 0);
    piece.userData = { index, type, animating: true, targetScale: 1 };
    
    scene.add(piece);
    gameState.pieces.push(piece);
    
    return piece;
}

function animatePieces() {
    gameState.pieces.forEach(piece => {
        if (piece.userData.animating) {
            const scale = piece.scale.x + CONFIG.animations.pieceScaleSpeed;
            if (scale >= piece.userData.targetScale) {
                piece.scale.set(piece.userData.targetScale, piece.userData.targetScale, piece.userData.targetScale);
                piece.userData.animating = false;
            } else {
                piece.scale.set(scale, scale, scale);
            }
        }
        
        // Gentle floating animation
        piece.position.y = 0.6 + Math.sin(Date.now() * 0.003 + piece.userData.index) * 0.05;
        
        // Rotation for X
        if (piece.userData.type === 'X') {
            piece.rotation.y += 0.02;
        }
    });
}

function onWindowResize() {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
}

function onMouseMove(event) {
    mouse.x = (event.clientX / window.innerWidth) * 2 - 1;
    mouse.y = -(event.clientY / window.innerHeight) * 2 + 1;
    
    raycaster.setFromCamera(mouse, camera);
    const intersects = raycaster.intersectObjects(tiles);
    
    // Reset previous hover
    if (hoveredTile) {
        hoveredTile.material.color.setHex(0x3a3a6e);
        hoveredTile.material.emissiveIntensity = 0.3;
        hoveredTile = null;
    }
    
    // Hide marker by default
    if (hoverMarker) hoverMarker.visible = false;
    document.body.style.cursor = 'default';
    
    // Set new hover
    if (intersects.length > 0 && !gameState.gameOver) {
        const tile = intersects[0].object;
        if (gameState.board[tile.userData.index] === null) {
            hoveredTile = tile;
            tile.material.color.setHex(0x7a7aae);
            tile.material.emissiveIntensity = 0.6;
            
            // Show marker at tile position
            if (hoverMarker) {
                hoverMarker.position.x = tile.position.x;
                hoverMarker.position.z = tile.position.z;
                hoverMarker.visible = true;
            }
            
            document.body.style.cursor = 'pointer';
        }
    }
}

function onMouseClick(event) {
    if (gameState.gameOver) return;
    
    // Update mouse position for click
    mouse.x = (event.clientX / window.innerWidth) * 2 - 1;
    mouse.y = -(event.clientY / window.innerHeight) * 2 + 1;
    
    raycaster.setFromCamera(mouse, camera);
    const intersects = raycaster.intersectObjects(tiles);
    
    if (intersects.length > 0) {
        const hitObj = intersects[0].object;
        const index = hitObj.userData.index;
        
        console.log('Clicked tile:', index);
        
        if (gameState.board[index] === null) {
            makeMove(index);
        }
    }
}

function onTouchStart(event) {
    if (event.touches.length > 0) {
        const touch = event.touches[0];
        mouse.x = (touch.clientX / window.innerWidth) * 2 - 1;
        mouse.y = -(touch.clientY / window.innerHeight) * 2 + 1;
        
        raycaster.setFromCamera(mouse, camera);
        const intersects = raycaster.intersectObjects(tiles);
        
        if (intersects.length > 0) {
            event.preventDefault();
            const hitObj = intersects[0].object;
            const index = hitObj.userData.index;
            
            console.log('Touched tile:', index);
            
            if (gameState.board[index] === null) {
                makeMove(index);
            }
        }
    }
}

function makeMove(index) {
    gameState.board[index] = gameState.currentPlayer;
    createPiece(gameState.currentPlayer, index);
    
    // Check for win
    const winResult = checkWin();
    if (winResult) {
        endGame(gameState.currentPlayer, winResult);
        return;
    }
    
    // Check for draw
    if (!gameState.board.includes(null)) {
        endGame('draw');
        return;
    }
    
    // Switch player
    gameState.currentPlayer = gameState.currentPlayer === 'X' ? 'O' : 'X';
    updateStatusText();
    
    // AI move if in PVE mode
    if (gameState.gameMode === 'pve' && gameState.currentPlayer === 'O' && !gameState.gameOver) {
        setTimeout(aiMove, 500);
    }
}

function aiMove() {
    if (gameState.gameOver) return;
    
    let move;
    
    switch (gameState.difficulty) {
        case 'easy':
            move = getRandomMove();
            break;
        case 'medium':
            // 50% chance of smart move, 50% random
            move = Math.random() < 0.5 ? getSmartMove() : getRandomMove();
            break;
        case 'hard':
            move = getSmartMove();
            break;
    }
    
    if (move !== null) {
        makeMove(move);
    }
}

function getRandomMove() {
    const available = gameState.board
        .map((val, idx) => val === null ? idx : null)
        .filter(val => val !== null);
    
    if (available.length === 0) return null;
    return available[Math.floor(Math.random() * available.length)];
}

function getSmartMove() {
    // Try to win
    for (let i = 0; i < 9; i++) {
        if (gameState.board[i] === null) {
            gameState.board[i] = 'O';
            if (checkWin()) {
                gameState.board[i] = null;
                return i;
            }
            gameState.board[i] = null;
        }
    }
    
    // Block opponent
    for (let i = 0; i < 9; i++) {
        if (gameState.board[i] === null) {
            gameState.board[i] = 'X';
            if (checkWin()) {
                gameState.board[i] = null;
                return i;
            }
            gameState.board[i] = null;
        }
    }
    
    // Take center
    if (gameState.board[4] === null) return 4;
    
    // Take corners
    const corners = [0, 2, 6, 8];
    const availableCorners = corners.filter(c => gameState.board[c] === null);
    if (availableCorners.length > 0) {
        return availableCorners[Math.floor(Math.random() * availableCorners.length)];
    }
    
    // Take sides
    const sides = [1, 3, 5, 7];
    const availableSides = sides.filter(s => gameState.board[s] === null);
    if (availableSides.length > 0) {
        return availableSides[Math.floor(Math.random() * availableSides.length)];
    }
    
    return getRandomMove();
}

function checkWin() {
    const lines = [
        [0, 1, 2], [3, 4, 5], [6, 7, 8], // Rows
        [0, 3, 6], [1, 4, 7], [2, 5, 8], // Columns
        [0, 4, 8], [2, 4, 6] // Diagonals
    ];
    
    for (const line of lines) {
        const [a, b, c] = line;
        if (gameState.board[a] && 
            gameState.board[a] === gameState.board[b] && 
            gameState.board[a] === gameState.board[c]) {
            return line;
        }
    }
    
    return null;
}

function endGame(winner, winLine) {
    gameState.gameOver = true;
    gameState.winner = winner;
    
    if (winLine) {
        highlightWinLine(winLine);
    }
    
    setTimeout(() => {
        if (winner === 'draw') {
            winnerText.textContent = "IT'S A DRAW!";
            winnerText.style.color = '#00ffff';
        } else {
            winnerText.textContent = `PLAYER ${winner} WINS!`;
            winnerText.style.color = winner === 'X' ? '#ff0066' : '#00ff66';
        }
        winnerModal.classList.remove('hidden');
    }, 500);
}

function highlightWinLine(winLine) {
    const row = Math.floor(winLine[1] / 3);
    const col = winLine[1] % 3;
    const totalSize = CONFIG.boardSize * CONFIG.tileSize + (CONFIG.boardSize - 1) * CONFIG.tileGap;
    const offset = totalSize / 2 - CONFIG.tileSize / 2;
    
    const x = col * (CONFIG.tileSize + CONFIG.tileGap) - offset;
    const z = row * (CONFIG.tileSize + CONFIG.tileGap) - offset;
    
    const isDiagonal = winLine[0] + winLine[2] === 8 || winLine[0] + winLine[2] === 8;
    const isMainDiagonal = winLine[0] === 0 && winLine[2] === 8;
    const isAntiDiagonal = winLine[0] === 2 && winLine[2] === 6;
    
    let length = CONFIG.tileSize * 3 + CONFIG.tileGap * 2;
    let angle = 0;
    
    if (winLine[0] === winLine[1] - 1 && winLine[1] === winLine[2] - 1) {
        // Row - horizontal
        angle = 0;
    } else if (winLine[0] !== 0 && winLine[0] !== 6 && winLine[0] !== 3) {
        // Column - vertical
        angle = Math.PI / 2;
    } else if (isMainDiagonal) {
        angle = Math.PI / 4;
    } else if (isAntiDiagonal) {
        angle = -Math.PI / 4;
    }
    
    const geometry = new THREE.BoxGeometry(length, 0.1, 0.3);
    const material = new THREE.MeshBasicMaterial({
        color: CONFIG.colors.winLine,
        transparent: true,
        opacity: 0.8
    });
    
    const winLineMesh = new THREE.Mesh(geometry, material);
    winLineMesh.position.set(x, 0.5, z);
    winLineMesh.rotation.y = angle;
    winLineMesh.userData = { animating: true, startTime: Date.now() };
    
    scene.add(winLineMesh);
    
    // Animate win line
    function animateWinLine() {
        const elapsed = Date.now() - winLineMesh.userData.startTime;
        winLineMesh.material.opacity = 0.5 + Math.sin(elapsed * 0.01) * 0.3;
        
        if (!gameState.gameOver) {
            scene.remove(winLineMesh);
            return;
        }
        
        requestAnimationFrame(animateWinLine);
    }
    animateWinLine();
}

function updateStatusText() {
    if (gameState.gameMode === 'pve') {
        if (gameState.currentPlayer === 'X') {
            statusText.textContent = "Your Turn (X)";
        } else {
            statusText.textContent = "AI Thinking...";
        }
    } else {
        statusText.textContent = `Player ${gameState.currentPlayer}'s Turn`;
    }
}

function onModeChange() {
    gameState.gameMode = modeSelect.value;
    difficultyGroup.style.display = gameState.gameMode === 'pve' ? 'flex' : 'none';
    currentModeText.textContent = gameState.gameMode === 'pve' ? 'vs AI' : '2-Player Mode';
    resetGame();
}

function onDifficultyChange() {
    gameState.difficulty = difficultySelect.value;
    resetGame();
}

function resetGame() {
    // Clear pieces
    gameState.pieces.forEach(piece => scene.remove(piece));
    gameState.pieces = [];
    
    // Clear win lines (any remaining BoxGeometry that was added)
    scene.children.forEach(child => {
        if (child.userData && child.userData.animating === true && 
            child.geometry && child.geometry.type === 'BoxGeometry' &&
            child.material.color.getHex() === CONFIG.colors.winLine) {
            scene.remove(child);
        }
    });
    
    // Reset state
    gameState.board = Array(9).fill(null);
    gameState.currentPlayer = 'X';
    gameState.gameOver = false;
    gameState.winner = null;
    
    // Hide modal
    winnerModal.classList.add('hidden');
    
    // Update UI
    updateStatusText();
}

function animate() {
    requestAnimationFrame(animate);
    
    // Rotate tile group slightly
    if (tileGroup) {
        tileGroup.rotation.y = Math.sin(Date.now() * 0.0005) * 0.05;
    }
    
    // Animate pieces
    animatePieces();
    
    renderer.render(scene, camera);
}
