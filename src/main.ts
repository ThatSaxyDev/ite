import { Game } from './core/Game';

const game = Game.getInstance();

// Expose game for debugging
(window as unknown as { game: Game }).game = game;

// Start the game
game.start();
