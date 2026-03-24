/**
 * ITE Landing Page - Main JavaScript
 * Advanced particle effects, scroll animations, and cursor interactions
 */

class ParticleSystem {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.particles = [];
    this.connections = [];
    this.maxConnections = 3;
    this.maxDistance = 150;
    this.mouse = { x: null, y: null, radius: 150 };
    this.isActive = true;
    
    this.init();
    this.bindEvents();
    this.animate();
  }
  
  init() {
    this.resize();
    this.createParticles();
  }
  
  resize() {
    const dpr = Math.min(window.devicePixelRatio, 1.5);
    this.canvas.width = window.innerWidth * dpr;
    this.canvas.height = window.innerHeight * dpr;
    this.canvas.style.width = `${window.innerWidth}px`;
    this.canvas.style.height = `${window.innerHeight}px`;
    this.ctx.scale(dpr, dpr);
    this.width = window.innerWidth;
    this.height = window.innerHeight;
  }
  
  createParticles() {
    const count = Math.min(Math.floor(window.innerWidth * 0.05), 100);
    this.particles = [];
    
    for (let i = 0; i < count; i++) {
      this.particles.push({
        x: Math.random() * this.width,
        y: Math.random() * this.height,
        vx: (Math.random() - 0.5) * 0.5,
        vy: (Math.random() - 0.5) * 0.5,
        size: Math.random() * 2 + 1,
        opacity: Math.random() * 0.5 + 0.2,
        baseOpacity: Math.random() * 0.5 + 0.2
      });
    }
  }
  
  bindEvents() {
    window.addEventListener('resize', () => {
      this.resize();
      this.createParticles();
    });
    
    this.canvas.addEventListener('mousemove', (e) => {
      const rect = this.canvas.getBoundingClientRect();
      this.mouse.x = e.clientX - rect.left;
      this.mouse.y = e.clientY - rect.top;
    });
    
    this.canvas.addEventListener('mouseleave', () => {
      this.mouse.x = null;
      this.mouse.y = null;
    });
    
    // Pause when not visible
    document.addEventListener('visibilitychange', () => {
      this.isActive = !document.hidden;
    });
  }
  
  drawParticle(p) {
    this.ctx.beginPath();
    this.ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
    this.ctx.fillStyle = `rgba(255, 255, 255, ${p.opacity})`;
    this.ctx.fill();
    
    // Glow effect
    this.ctx.beginPath();
    this.ctx.arc(p.x, p.y, p.size * 2, 0, Math.PI * 2);
    this.ctx.fillStyle = `rgba(255, 255, 255, ${p.opacity * 0.2})`;
    this.ctx.fill();
  }
  
  drawConnection(p1, p2, distance) {
    const opacity = (1 - distance / this.maxDistance) * 0.3;
    this.ctx.beginPath();
    this.ctx.moveTo(p1.x, p1.y);
    this.ctx.lineTo(p2.x, p2.y);
    this.ctx.strokeStyle = `rgba(255, 255, 255, ${opacity})`;
    this.ctx.lineWidth = 0.5;
    this.ctx.stroke();
  }
  
  animate() {
    if (!this.isActive) {
      requestAnimationFrame(() => this.animate());
      return;
    }
    
    this.ctx.clearRect(0, 0, this.width, this.height);
    
    // Update and draw particles
    this.particles.forEach(p => {
      // Move
      p.x += p.vx;
      p.y += p.vy;
      
      // Wrap around edges
      if (p.x < 0) p.x = this.width;
      if (p.x > this.width) p.x = 0;
      if (p.y < 0) p.y = this.height;
      if (p.y > this.height) p.y = 0;
      
      // Mouse interaction
      if (this.mouse.x !== null && this.mouse.y !== null) {
        const dx = p.x - this.mouse.x;
        const dy = p.y - this.mouse.y;
        const distance = Math.sqrt(dx * dx + dy * dy);
        
        if (distance < this.mouse.radius) {
          const force = (this.mouse.radius - distance) / this.mouse.radius;
          p.opacity = p.baseOpacity + force * 0.3;
          
          // Gentle push away
          const angle = Math.atan2(dy, dx);
          p.x += Math.cos(angle) * force * 0.5;
          p.y += Math.sin(angle) * force * 0.5;
        } else {
          p.opacity += (p.baseOpacity - p.opacity) * 0.05;
        }
      }
      
      this.drawParticle(p);
    });
    
    // Draw connections
    for (let i = 0; i < this.particles.length; i++) {
      let connections = 0;
      for (let j = i + 1; j < this.particles.length; j++) {
        const dx = this.particles[i].x - this.particles[j].x;
        const dy = this.particles[i].y - this.particles[j].y;
        const distance = Math.sqrt(dx * dx + dy * dy);
        
        if (distance < this.maxDistance && connections < this.maxConnections) {
          this.drawConnection(this.particles[i], this.particles[j], distance);
          connections++;
        }
      }
    }
    
    requestAnimationFrame(() => this.animate());
  }
}

// ========================================
// Cursor System
// ========================================

class CursorSystem {
  constructor() {
    this.dot = document.querySelector('.cursor-dot');
    this.ring = document.querySelector('.cursor-ring');
    this.mouse = { x: window.innerWidth / 2, y: window.innerHeight / 2 };
    this.dotPos = { x: window.innerWidth / 2, y: window.innerHeight / 2 };
    this.ringPos = { x: window.innerWidth / 2, y: window.innerHeight / 2 };
    this.isTouch = window.matchMedia('(pointer: coarse)').matches;
    
    if (!this.isTouch) {
      this.init();
    }
  }
  
  init() {
    this.bindEvents();
    this.animate();
  }
  
  bindEvents() {
    document.addEventListener('mousemove', (e) => {
      this.mouse.x = e.clientX;
      this.mouse.y = e.clientY;
    });
    
    // Hover states
    const interactiveElements = document.querySelectorAll('[data-magnetic], a, button, .feature-card');
    interactiveElements.forEach(el => {
      el.addEventListener('mouseenter', () => this.ring.classList.add('hovering'));
      el.addEventListener('mouseleave', () => this.ring.classList.remove('hovering'));
    });
  }
  
  animate() {
    // Smooth follow with different easing
    this.dotPos.x += (this.mouse.x - this.dotPos.x) * 0.2;
    this.dotPos.y += (this.mouse.y - this.dotPos.y) * 0.2;
    this.ringPos.x += (this.mouse.x - this.ringPos.x) * 0.1;
    this.ringPos.y += (this.mouse.y - this.ringPos.y) * 0.1;
    
    this.dot.style.left = `${this.dotPos.x}px`;
    this.dot.style.top = `${this.dotPos.y}px`;
    this.ring.style.left = `${this.ringPos.x}px`;
    this.ring.style.top = `${this.ringPos.y}px`;
    
    requestAnimationFrame(() => this.animate());
  }
}

// ========================================
// Magnetic Effect
// ========================================

class MagneticEffect {
  constructor() {
    this.elements = document.querySelectorAll('[data-magnetic]');
    this.strength = 0.3;
    
    this.elements.forEach(el => {
      el.addEventListener('mousemove', (e) => this.handleMove(e, el));
      el.addEventListener('mouseleave', (e) => this.handleLeave(e, el));
    });
  }
  
  handleMove(e, el) {
    const rect = el.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const deltaX = (e.clientX - centerX) * this.strength;
    const deltaY = (e.clientY - centerY) * this.strength;
    
    el.style.transform = `translate(${deltaX}px, ${deltaY}px)`;
  }
  
  handleLeave(e, el) {
    el.style.transition = 'transform 0.3s cubic-bezier(0.16, 1, 0.3, 1)';
    el.style.transform = 'translate(0, 0)';
    
    setTimeout(() => {
      el.style.transition = '';
    }, 300);
  }
}

// ========================================
// Scroll Progress
// ========================================

class ScrollProgress {
  constructor() {
    this.bar = document.querySelector('.progress-bar');
    this.nav = document.querySelector('.nav');
    
    this.bindEvents();
  }
  
  bindEvents() {
    let ticking = false;
    
    window.addEventListener('scroll', () => {
      if (!ticking) {
        requestAnimationFrame(() => {
          this.update();
          ticking = false;
        });
        ticking = true;
      }
    }, { passive: true });
  }
  
  update() {
    const scrollTop = window.scrollY;
    const docHeight = document.documentElement.scrollHeight - window.innerHeight;
    const progress = scrollTop / docHeight;
    
    this.bar.style.transform = `scaleX(${progress})`;
    
    // Nav styling
    if (scrollTop > 50) {
      this.nav?.classList.add('scrolled');
    } else {
      this.nav?.classList.remove('scrolled');
    }
  }
}

// ========================================
// Scroll Reveal
// ========================================

class ScrollReveal {
  constructor() {
    this.elements = document.querySelectorAll('[data-reveal]');
    
    const observer = new IntersectionObserver(
      (entries) => this.handleIntersect(entries),
      { threshold: 0.1, rootMargin: '0px 0px -50px 0px' }
    );
    
    this.elements.forEach((el, i) => {
      el.style.transitionDelay = `${i * 0.1}s`;
      observer.observe(el);
    });
  }
  
  handleIntersect(entries) {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
      }
    });
  }
}

// ========================================
// Feature Card Spotlight
// ========================================

class FeatureSpotlight {
  constructor() {
    this.cards = document.querySelectorAll('.feature-card');
    
    this.cards.forEach(card => {
      card.addEventListener('mousemove', (e) => this.handleMove(e, card));
      card.addEventListener('mouseleave', () => this.handleLeave(card));
    });
  }
  
  handleMove(e, card) {
    const rect = card.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 100;
    const y = ((e.clientY - rect.top) / rect.height) * 100;
    
    card.style.setProperty('--mouse-x', `${x}%`);
    card.style.setProperty('--mouse-y', `${y}%`);
  }
  
  handleLeave(card) {
    card.style.setProperty('--mouse-x', '50%');
    card.style.setProperty('--mouse-y', '50%');
  }
}

// ========================================
// Animated Counter
// ========================================

class AnimatedCounter {
  constructor() {
    this.counters = document.querySelectorAll('.stat-num');
    this.duration = 2000;
    
    const observer = new IntersectionObserver(
      (entries) => this.handleIntersect(entries),
      { threshold: 0.5 }
    );
    
    this.counters.forEach(counter => {
      observer.observe(counter);
    });
  }
  
  handleIntersect(entries) {
    entries.forEach(entry => {
      if (entry.isIntersecting && !entry.target.classList.contains('counted')) {
        entry.target.classList.add('counted');
        this.animate(entry.target);
      }
    });
  }
  
  animate(el) {
    const target = parseInt(el.dataset.target);
    const start = Date.now();
    const format = el.dataset.target === '98000' ? (n) => Math.floor(n).toLocaleString() : 
                   el.dataset.target === '98' ? (n) => Math.floor(n) + '%' :
                   (n) => Math.floor(n) + '+';
    
    const frame = () => {
      const elapsed = Date.now() - start;
      const progress = Math.min(elapsed / this.duration, 1);
      
      // Easing
      const easeOutQuart = 1 - Math.pow(1 - progress, 4);
      const current = easeOutQuart * target;
      
      el.textContent = format(current);
      
      if (progress < 1) {
        requestAnimationFrame(frame);
      }
    };
    
    requestAnimationFrame(frame);
  }
}

// ========================================
// Tab System
// ========================================

class TabSystem {
  constructor() {
    this.buttons = document.querySelectorAll('.tab-btn');
    this.panels = {
      pipx: document.getElementById('code-pipx'),
      pip: document.getElementById('code-pip'),
      brew: document.getElementById('code-brew')
    };
    
    this.buttons.forEach(btn => {
      btn.addEventListener('click', () => this.switchTab(btn));
    });
  }
  
  switchTab(activeBtn) {
    const tab = activeBtn.dataset.tab;
    
    // Update buttons
    this.buttons.forEach(btn => btn.classList.remove('active'));
    activeBtn.classList.add('active');
    
    // Update panels
    Object.values(this.panels).forEach(panel => panel.classList.add('hidden'));
    this.panels[tab].classList.remove('hidden');
  }
}

// ========================================
// Copy Button
// ========================================

class CopyButton {
  constructor() {
    this.button = document.querySelector('.copy-btn');
    this.init();
  }
  
  init() {
    if (!this.button) return;
    
    this.button.addEventListener('click', () => this.copy());
  }
  
  async copy() {
    const activeCode = document.querySelector('.code-content pre:not(.hidden) code');
    if (!activeCode) return;
    
    const text = activeCode.textContent;
    
    try {
      await navigator.clipboard.writeText(text);
      this.showFeedback('Copied!');
    } catch (err) {
      this.showFeedback('Failed');
    }
  }
  
  showFeedback(text) {
    const span = this.button.querySelector('.copy-text');
    const original = span.textContent;
    
    span.textContent = text;
    this.button.classList.add('copied');
    
    setTimeout(() => {
      span.textContent = original;
      this.button.classList.remove('copied');
    }, 1500);
  }
}

// ========================================
// Terminal Animation
// ========================================

class TerminalAnimation {
  constructor() {
    this.lines = document.querySelectorAll('.terminal-line[data-type], .terminal-line[data-appear]');
    this.initObserver();
  }
  
  initObserver() {
    const observer = new IntersectionObserver(
      (entries) => this.handleIntersect(entries),
      { threshold: 0.3 }
    );
    
    const terminal = document.querySelector('.terminal-window');
    if (terminal) observer.observe(terminal);
  }
  
  handleIntersect(entries) {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        this.animate();
      }
    });
  }
  
  animate() {
    this.lines.forEach((line, i) => {
      const delay = i * 800;
      
      setTimeout(() => {
        line.classList.add('visible');
      }, delay + 2000);
    });
  }
}

// ========================================
// Parallax Effect
// ========================================

class ParallaxEffect {
  constructor() {
    this.elements = document.querySelectorAll('[data-parallax]');
    
    if (this.elements.length === 0) return;
    
    let ticking = false;
    
    window.addEventListener('scroll', () => {
      if (!ticking) {
        requestAnimationFrame(() => {
          this.update();
          ticking = false;
        });
        ticking = true;
      }
    }, { passive: true });
  }
  
  update() {
    const scrollY = window.scrollY;
    
    this.elements.forEach(el => {
      const speed = parseFloat(el.dataset.parallax) || 0.1;
      const rect = el.getBoundingClientRect();
      const offset = rect.top * speed;
      
      el.style.transform = `translateY(${offset}px)`;
    });
  }
}

// ========================================
// Initialize
// ========================================

document.addEventListener('DOMContentLoaded', () => {
  // Initialize all systems
  const canvas = document.getElementById('particleCanvas');
  if (canvas) new ParticleSystem(canvas);
  
  new CursorSystem();
  new MagneticEffect();
  new ScrollProgress();
  new ScrollReveal();
  new FeatureSpotlight();
  new AnimatedCounter();
  new TabSystem();
  new CopyButton();
  new TerminalAnimation();
  new ParallaxEffect();
  
  // Smooth scroll for anchor links
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function(e) {
      e.preventDefault();
      const target = document.querySelector(this.getAttribute('href'));
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });
});

// ========================================
// Prefers Reduced Motion
// ========================================

if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
  document.documentElement.style.setProperty('--animation-duration', '0.01ms');
}
