/**
 * ITE — Ultimate Edition
 * WebGL particles, physics-based interactions, premium animations
 */

// ========================================
// Utilities
// ========================================

const Utils = {
  lerp: (start, end, factor) => start + (end - start) * factor,
  clamp: (value, min, max) => Math.max(min, Math.min(max, value)),
  map: (value, start1, end1, start2, end2) => 
    start2 + (end2 - start2) * ((value - start1) / (end1 - start1)),
  random: (min, max) => Math.random() * (max - min) + min,
 
  mouseDistance: (x1, y1, x2, y2) => {
    const dx = x2 - x1;
    const dy = y2 - y1;
    return Math.sqrt(dx * dx + dy * dy);
  },
 
  throttle: (fn, delay) => {
    let last = 0;
    return (...args) => {
      const now = Date.now();
      if (now - last > delay) {
        last = now;
        fn.apply(this, args);
      }
    };
  },
 
  wait: (ms) => new Promise(resolve => setTimeout(resolve, ms)),
 
  scrambleText: (element, finalText, duration = 500) => {
    const chars = '!<>-_\\/[]{}—=+*^?#________';
    const frameRate = 30;
    const totalFrames = (duration / 1000) * frameRate;
    let frame = 0;
    const originalText = finalText || element.textContent;
   
    const interval = setInterval(() => {
      let output = '';
      const progress = frame / totalFrames;
      
      for (let i = 0; i < originalText.length; i++) {
        if (i < progress * originalText.length) {
          output += originalText[i];
        } else if (originalText[i] === ' ') {
          output += ' ';
        } else {
          output += chars[Math.floor(Math.random() * chars.length)];
        }
      }
      
      element.textContent = output;
      frame++;
      
      if (frame > totalFrames) {
        clearInterval(interval);
        element.textContent = originalText;
      }
    }, 1000 / frameRate);
  }
};

// ========================================
// Preloader
// ========================================

class Preloader {
  constructor() {
    this.element = document.getElementById('preloader');
    this.text = document.querySelector('.preloader-logo .text');
    this.status = document.querySelector('.status-text');
    this.init();
  }
 
  async init() {
    if (!this.element) return;
   
    // Decrypt text effect
    await this.decryptText();
    
    // Status updates
    await this.updateStatus('Loading modules');
    await Utils.wait(800);
    await this.updateStatus('Initializing');
    await Utils.wait(600);
    await this.updateStatus('Ready');
    await Utils.wait(400);
   
    // Hide
    this.element.classList.add('hidden');
    document.body.classList.add('loaded');
  }
 
  async decryptText() {
    const finalText = this.text.textContent;
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
    const steps = 20;
   
    for (let i = 0; i < steps; i++) {
      await Utils.wait(50);
      let display = '';
      for (let j = 0; j < finalText.length; j++) {
        if (i / steps > j / finalText.length) {
          display += finalText[j];
        } else {
          display += chars[Math.floor(Math.random() * chars.length)];
        }
      }
      this.text.textContent = display;
    }
    this.text.textContent = finalText;
  }
 
  async updateStatus(text) {
    this.status.textContent = text;
  }
}

// ========================================
// WebGL Particle System
// ========================================

class WebGLParticles {
  constructor(container) {
    this.container = container;
    this.scene = null;
    this.camera = null;
    this.renderer = null;
    this.particles = null;
    this.material = null;
    this.geometry = null;
    this.mouse = new THREE.Vector2(-100, -100);
    this.targetMouse = new THREE.Vector2(-100, -100);
    this.clock = new THREE.Clock();
    this.count = Math.min(Math.floor(window.innerWidth * 0.08), 150);
    
    this.init();
  }
 
  init() {
    // Scene setup
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
    this.camera.position.z = 50;
   
    // Renderer
    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: 'high-performance'
    });
    this.renderer.setSize(window.innerWidth, window.innerHeight);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setClearColor(0x000000, 0);
    this.container.appendChild(this.renderer.domElement);
   
    // Create particles
    this.createParticles();
   
    // Events
    this.bindEvents();
   
    // Start loop
    this.animate();
  }
 
  createParticles() {
    this.geometry = new THREE.BufferGeometry();
   
    const positions = new Float32Array(this.count * 3);
    const velocities = new Float32Array(this.count * 3);
    const phases = new Float32Array(this.count);
    
    for (let i = 0; i < this.count; i++) {
      positions[i * 3] = Utils.random(-50, 50);
      positions[i * 3 + 1] = Utils.random(-30, 30);
      positions[i * 3 + 2] = Utils.random(-20, 20);
     
      velocities[i * 3] = Utils.random(-0.02, 0.02);
      velocities[i * 3 + 1] = Utils.random(-0.02, 0.02);
      velocities[i * 3 + 2] = Utils.random(-0.01, 0.01);
     
      phases[i] = Utils.random(0, Math.PI * 2);
    }
   
    this.geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    this.geometry.setAttribute('velocity', new THREE.BufferAttribute(velocities, 3));
    this.geometry.setAttribute('phase', new THREE.BufferAttribute(phases, 1));
   
    // Custom shader material
    this.material = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uMouse: { value: new THREE.Vector2(0, 0) },
        uColor: { value: new THREE.Color(0xffffff) }
      },
      vertexShader: `
        attribute float phase;
        attribute vec3 velocity;
        uniform float uTime;
        uniform vec2 uMouse;
        varying float vAlpha;
        varying float vSize;
       
        void main() {
          vec3 pos = position;
         
          // Base movement
          pos.x += velocity.x * uTime * 10.0;
          pos.y += velocity.y * uTime * 10.0;
          pos.z += velocity.z * uTime * 5.0;
         
          // Wrap around
          pos.x = mod(pos.x + 50.0, 100.0) - 50.0;
          pos.y = mod(pos.y + 30.0, 60.0) - 30.0;
         
          // Mouse repulsion
          vec2 mouseWorld = uMouse * vec2(50.0, 30.0);
          vec2 pos2d = pos.xy;
          float dist = distance(pos2d, mouseWorld);
         
          if (dist < 15.0) {
            vec2 dir = normalize(pos2d - mouseWorld);
            float force = (15.0 - dist) / 15.0;
            pos.xy += dir * force * 5.0;
          }
         
          // Pulsing
          float pulse = sin(uTime + phase) * 0.5 + 0.5;
          vAlpha = 0.3 + pulse * 0.4;
          vSize = 1.0 + pulse * 0.5;
         
          vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
          gl_PointSize = vSize * (300.0 / -mvPosition.z);
          gl_Position = projectionMatrix * mvPosition;
        }
      `,
      fragmentShader: `
        uniform vec3 uColor;
        varying float vAlpha;
       
        void main() {
          float dist = distance(gl_PointCoord, vec2(0.5));
          float alpha = 1.0 - smoothstep(0.0, 0.5, dist);
          alpha *= vAlpha;
         
          gl_FragColor = vec4(uColor, alpha * 0.8);
        }
      `,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending
    });
   
    this.particles = new THREE.Points(this.geometry, this.material);
    this.scene.add(this.particles);
   
    // Connections
    this.createConnections();
  }
 
  createConnections() {
    const lineGeometry = new THREE.BufferGeometry();
    const maxConnections = this.count * 3;
    const positions = new Float32Array(maxConnections * 6);
    lineGeometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    lineGeometry.setDrawRange(0, 0);
   
    const lineMaterial = new THREE.LineBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.1,
      blending: THREE.AdditiveBlending
    });
   
    this.lines = new THREE.LineSegments(lineGeometry, lineMaterial);
    this.scene.add(this.lines);
  }
 
  updateConnections() {
    const positions = this.particles.geometry.attributes.position.array;
    const linePositions = this.lines.geometry.attributes.position.array;
    let index = 0;
    let numConnections = 0;
    
    const maxDist = 12;
    
    for (let i = 0; i < this.count; i++) {
      let connections = 0;
      const x1 = positions[i * 3];
      const y1 = positions[i * 3 + 1];
      const z1 = positions[i * 3 + 2];
     
      for (let j = i + 1; j < this.count && connections < 3; j++) {
        const x2 = positions[j * 3];
        const y2 = positions[j * 3 + 1];
        const z2 = positions[j * 3 + 2];
        
        const dist = Math.sqrt(
          (x2 - x1) ** 2 +
          (y2 - y1) ** 2 +
          (z2 - z1) ** 2
        );
       
        if (dist < maxDist) {
          linePositions[index++] = x1;
          linePositions[index++] = y1;
          linePositions[index++] = z1;
          linePositions[index++] = x2;
          linePositions[index++] = y2;
          linePositions[index++] = z2;
          connections++;
          numConnections++;
        }
      }
    }
   
    this.lines.geometry.setDrawRange(0, numConnections * 2);
    this.lines.geometry.attributes.position.needsUpdate = true;
  }
 
  bindEvents() {
    window.addEventListener('resize', () => {
      this.camera.aspect = window.innerWidth / window.innerHeight;
      this.camera.updateProjectionMatrix();
      this.renderer.setSize(window.innerWidth, window.innerHeight);
    });
   
    window.addEventListener('mousemove', (e) => {
      this.targetMouse.x = (e.clientX / window.innerWidth) * 2 - 1;
      this.targetMouse.y = -(e.clientY / window.innerHeight) * 2 + 1;
    });
   
    document.addEventListener('visibilitychange', () => {
      this.isActive = !document.hidden;
    });
  }
 
  animate() {
    requestAnimationFrame(() => this.animate());
   
    if (!this.isActive) return;
   
    const delta = this.clock.getDelta();
    const time = this.clock.getElapsedTime();
   
    // Smooth mouse follow
    this.mouse.lerp(this.targetMouse, 0.05);
   
    // Update uniforms
    this.material.uniforms.uTime.value = time;
    this.material.uniforms.uMouse.value = this.mouse;
   
    // Update connections
    this.updateConnections();
   
    // Render
    this.renderer.render(this.scene, this.camera);
  }
 
  destroy() {
    this.renderer.dispose();
    this.geometry.dispose();
    this.material.dispose();
  }
}

// ========================================
// Cursor System
// ========================================

class CursorSystem {
  constructor() {
    this.dot = document.querySelector('.cursor-dot');
    this.ring = document.querySelector('.cursor-ring');
    this.trail = document.querySelector('.cursor-trail');
   
    if (!this.dot || !this.ring) return;
   
    this.isTouch = window.matchMedia('(pointer: coarse)').matches;
    if (this.isTouch) {
      document.body.style.cursor = 'auto';
      return;
    }
   
    this.pos = { x: window.innerWidth / 2, y: window.innerHeight / 2 };
    this.posDot = { x: this.pos.x, y: this.pos.y };
    this.posRing = { x: this.pos.x, y: this.pos.y };
    this.trailPositions = [];
   
    this.init();
  }
 
  init() {
    this.bindEvents();
    this.animate();
  }
 
  bindEvents() {
    document.addEventListener('mousemove', (e) => {
      this.pos.x = e.clientX;
      this.pos.y = e.clientY;
    });
   
    // Hover states
    const interactive = document.querySelectorAll('[data-magnetic], a, button, .tab-btn');
    interactive.forEach(el => {
      el.addEventListener('mouseenter', () => {
        this.ring.classList.add('hovering');
      });
      el.addEventListener('mouseleave', () => {
        this.ring.classList.remove('hovering');
      });
    });
  }
 
  animate() {
    // Dot follows quickly
    this.posDot.x = Utils.lerp(this.posDot.x, this.pos.x, 0.2);
    this.posDot.y = Utils.lerp(this.posDot.y, this.pos.y, 0.2);
   
    // Ring follows slowly
    this.posRing.x = Utils.lerp(this.posRing.x, this.pos.x, 0.08);
    this.posRing.y = Utils.lerp(this.posRing.y, this.pos.y, 0.08);
   
    // Apply positions
    this.dot.style.left = `${this.posDot.x}px`;
    this.dot.style.top = `${this.posDot.y}px`;
    this.ring.style.left = `${this.posRing.x}px`;
    this.ring.style.top = `${this.posRing.y}px`;
   
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
    const x = e.clientX - rect.left - rect.width / 2;
    const y = e.clientY - rect.top - rect.height / 2;
   
    el.style.transform = `translate(${x * this.strength}px, ${y * this.strength}px)`;
  }
 
  handleLeave(e, el) {
    el.style.transition = 'transform 0.4s cubic-bezier(0.16, 1, 0.3, 1)';
    el.style.transform = 'translate(0, 0)';
    
    setTimeout(() => {
      el.style.transition = '';
    }, 400);
  }
}

// ========================================
// Tilt Effect (3D Cards)
// ========================================

class TiltEffect {
  constructor() {
    this.elements = document.querySelectorAll('[data-tilt]');
   
    this.elements.forEach(el => {
      el.addEventListener('mousemove', (e) => this.handleMove(e, el));
      el.addEventListener('mouseleave', (e) => this.handleLeave(e, el));
    });
  }
 
  handleMove(e, el) {
    const rect = el.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
   
    const rotateX = (y - 0.5) * -20;
    const rotateY = (x - 0.5) * 20;
   
    el.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg)`;
  }
 
  handleLeave(e, el) {
    el.style.transform = 'perspective(1000px) rotateX(0) rotateY(0)';
    el.style.transition = 'transform 0.5s cubic-bezier(0.16, 1, 0.3, 1)';
    
    setTimeout(() => {
      el.style.transition = '';
    }, 500);
  }
}

// ========================================
// Scroll Progress & Reveal
// ========================================

class ScrollProgress {
  constructor() {
    this.bar = document.querySelector('.progress-bar');
    this.nav = document.querySelector('.nav');
   
    this.bindEvents();
  }
 
  bindEvents() {
    window.addEventListener('scroll', Utils.throttle(() => {
      const scroll = window.scrollY;
      const height = document.documentElement.scrollHeight - window.innerHeight;
      const progress = scroll / height;
     
      this.bar.style.transform = `scaleX(${progress})`;
     
      // Nav styling
      if (scroll > 100) {
        this.nav?.classList.add('scrolled');
      } else {
        this.nav?.classList.remove('scrolled');
      }
    }, 16), { passive: true });
  }
}

class ScrollReveal {
  constructor() {
    this.elements = document.querySelectorAll('[data-reveal]');
   
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1, rootMargin: '0px 0px -50px 0px' });
   
    this.elements.forEach((el, i) => {
      el.style.transitionDelay = `${i * 0.1}s`;
      observer.observe(el);
    });
  }
}

// ========================================
// Terminal Typewriter
// ========================================

class TerminalTypewriter {
  constructor() {
    this.body = document.getElementById('terminalBody');
    this.commands = [
      { text: 'pipx install ite-agent', type: 'command' },
      { text: '✓ installed ite-agent (v0.17.4)', type: 'success' },
      { text: 'ite', type: 'command' },
      { text: '════════════════════════════', type: 'divider' },
      { text: 'Welcome to ITE v0.17.4', type: 'center' },
      { text: 'What would you like to build?', type: 'prompt' }
    ];
    this.currentCommand = 0;
    this.visible = false;
    
    this.initObserver();
  }
 
  initObserver() {
    const terminal = document.querySelector('.terminal-window');
    if (!terminal) return;
   
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach(entry => {
          if (entry.isIntersecting && !this.visible) {
            this.visible = true;
            this.startSequence();
          }
        });
      },
      { threshold: 0.5 }
    );
   
    observer.observe(terminal);
  }
 
  async startSequence() {
    await Utils.wait(1000);
   
    for (const cmd of this.commands) {
      await this.typeCommand(cmd);
      await Utils.wait(cmd.type === 'command' ? 200 : 600);
    }
   
    // Final cursor
    this.addCursor();
  }
 
  async typeCommand(cmd) {
    const line = document.createElement('div');
    line.className = 'terminal-line';
    
    if (cmd.type === 'command') {
      line.innerHTML = `
        <span class="prompt">➜</span>
        <span class="text"></span>
      `;
      this.body.appendChild(line);
      
      const text = line.querySelector('.text');
      for (const char of cmd.text) {
        text.textContent += char;
        await Utils.wait(30 + Math.random() * 30);
      }
    } else if (cmd.type === 'success') {
      line.innerHTML = `<span class="text" style="color: #4ade80;">${cmd.text}</span>`;
      this.body.appendChild(line);
      line.style.opacity = '0';
      line.style.transform = 'translateY(10px)';
      line.style.transition = 'all 0.3s ease';
      await Utils.wait(50);
      line.style.opacity = '1';
      line.style.transform = 'translateY(0)';
    } else if (cmd.type === 'divider') {
      line.innerHTML = `<span class="text" style="color: var(--text-muted);">${cmd.text}</span>`;
      this.body.appendChild(line);
    } else if (cmd.type === 'center') {
      line.innerHTML = `<span class="text" style="color: var(--white); display: block; text-align: center;">${cmd.text}</span>`;
      this.body.appendChild(line);
    } else if (cmd.type === 'prompt') {
      line.innerHTML = `<span class="text" style="color: var(--text-muted); display: block;">${cmd.text}</span>`;
      this.body.appendChild(line);
    }
  }
 
  addCursor() {
    const line = document.createElement('div');
    line.className = 'terminal-line active';
    line.innerHTML = `
      <span class="prompt">➜</span>
      <span class="cursor"></span>
    `;
    this.body.appendChild(line);
  }
}

// ========================================
// Counter Animation
// ========================================

class CounterAnimation {
  constructor() {
    this.counters = document.querySelectorAll('.stat-value');
    this.duration = 2000;
   
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting && !entry.target.dataset.animated) {
          entry.target.dataset.animated = 'true';
          this.animate(entry.target);
        }
      });
    }, { threshold: 0.5 });
   
    this.counters.forEach(counter => observer.observe(counter));
  }
 
  animate(el) {
    const target = parseInt(el.dataset.count);
    const start = Date.now();
    let frame;
   
    const update = () => {
      const elapsed = Date.now() - start;
      const progress = Math.min(elapsed / this.duration, 1);
      const eased = 1 - Math.pow(1 - progress, 4);
      const current = Math.floor(eased * target);
     
      el.textContent = target > 5000 ? (current / 1000).toFixed(0) : current;
     
      if (progress < 1) {
        frame = requestAnimationFrame(update);
      } else {
        el.textContent = target > 5000 ? (target / 1000).toFixed(0) : target;
      }
    };
   
    frame = requestAnimationFrame(update);
  }
}

// ========================================
// Tab System
// ========================================

class TabSystem {
  constructor() {
    this.buttons = document.querySelectorAll('.tab-btn');
    this.panels = document.querySelectorAll('.code-panel');
   
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
    this.panels.forEach(panel => {
      panel.classList.remove('active');
      if (panel.id === `code-${tab}`) {
        panel.classList.add('active');
      }
    });
  }
}

// ========================================
// Copy System
// ========================================

class CopySystem {
  constructor() {
    this.btn = document.querySelector('.copy-btn');
    if (!this.btn) return;
   
    this.btn.addEventListener('click', () => this.copy());
  }
 
  async copy() {
    const active = document.querySelector('.code-panel.active code');
    if (!active) return;
   
    const text = active.textContent;
   
    try {
      await navigator.clipboard.writeText(text);
      this.showFeedback('Copied!');
    } catch {
      this.showFeedback('Failed');
    }
  }
 
  showFeedback(text) {
    const span = this.btn.querySelector('.copy-text');
    const original = span.textContent;
   
    span.textContent = text;
    this.btn.classList.add('copied');
   
    setTimeout(() => {
      span.textContent = original;
      this.btn.classList.remove('copied');
    }, 1500);
  }
}

// ========================================
// Scramble Effect
// ========================================

class ScrambleEffect {
  constructor() {
    this.elements = document.querySelectorAll('[data-scramble]');
   
    this.elements.forEach(el => {
      el.addEventListener('mouseenter', () => {
        Utils.scrambleText(el, el.textContent, 400);
      });
    });
  }
}

// ========================================
// Ripple Effect
// ========================================

class RippleEffect {
  constructor() {
    this.elements = document.querySelectorAll('[data-ripple]');
   
    this.elements.forEach(el => {
      el.addEventListener('click', (e) => this.createRipple(e, el));
    });
  }
 
  createRipple(e, el) {
    const rect = el.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height);
    const x = e.clientX - rect.left - size / 2;
    const y = e.clientY - rect.top - size / 2;
   
    const ripple = document.createElement('span');
    ripple.className = 'ripple';
    ripple.style.cssText = `
      width: ${size}px;
      height: ${size}px;
      left: ${x}px;
      top: ${y}px;
    `;
   
    el.appendChild(ripple);
   
    setTimeout(() => ripple.remove(), 600);
  }
}

// ========================================
// Mouse Illumination Effect
// ========================================

class MouseIllumination {
  constructor() {
    this.illumination = document.createElement('div');
    this.illumination.className = 'mouse-illumination';
    this.illumination.style.cssText = `
      position: fixed;
      width: 400px;
      height: 400px;
      background: radial-gradient(circle, rgba(255,255,255,0.12) 0%, rgba(255,255,255,0.04) 50%, transparent 75%);
      border-radius: 50%;
      pointer-events: none;
      z-index: 9981;
      opacity: 0;
      transition: opacity 0.2s ease;
      mix-blend-mode: overlay;
      transform: translate(-50%, -50%);
    `;
    document.body.appendChild(this.illumination);
   
    this.x = 0;
    this.y = 0;
    this.isVisible = false;
   
    this.bindEvents();
    this.animate();
  }
 
  bindEvents() {
    document.addEventListener('mousemove', (e) => {
      this.x = e.clientX;
      this.y = e.clientY;
      if (!this.isVisible) {
        this.isVisible = true;
        this.illumination.style.opacity = '1';
      }
    });
   
    document.addEventListener('mouseleave', () => {
      this.isVisible = false;
      this.illumination.style.opacity = '0';
    });
  }
 
  animate() {
    this.illumination.style.left = `${this.x}px`;
    this.illumination.style.top = `${this.y}px`;
    requestAnimationFrame(() => this.animate());
  }
}

// ========================================
// Smooth Scroll
// ========================================

class SmoothScroll {
  constructor() {
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
      anchor.addEventListener('click', (e) => {
        e.preventDefault();
        const target = document.querySelector(anchor.getAttribute('href'));
        if (target) {
          target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      });
    });
  }
}

// ========================================
// Initialize
// ========================================

document.addEventListener('DOMContentLoaded', () => {
  // Preloader first
  new Preloader();
 
  // Initialize all systems
  const webglContainer = document.getElementById('webglContainer');
  if (webglContainer && typeof THREE !== 'undefined') {
    new WebGLParticles(webglContainer);
  }
 
  new CursorSystem();
  new MagneticEffect();
  new TiltEffect();
  new ScrollProgress();
  new ScrollReveal();
  new TerminalTypewriter();
  new CounterAnimation();
  new TabSystem();
  new CopySystem();
  new ScrambleEffect();
  new RippleEffect();
  new SmoothScroll();
  new MouseIllumination();
  
  // Debug
  console.log('🔥 ITE Ultimate — All systems online');
});

// Error handling
window.addEventListener('error', (e) => {
  console.error('System error:', e.message);
});
