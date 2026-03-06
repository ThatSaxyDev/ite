# Three.js Creative Features

A collection of advanced Three.js features and techniques for building immersive 3D web experiences.

---

## 1. Audio-Reactive Visuals

**What it does:** Creates 3D graphics that respond to audio input in real-time.

**How it works:**
- Uses Web Audio API to analyze frequency data (FFT)
- Maps audio frequencies to visual properties like scale, color, or position
- Microphone input via `navigator.mediaDevices.getUserMedia()`

**Use cases:** Music visualizers, live performance graphics, interactive installations

```javascript
const audioContext = new AudioContext();
const analyser = audioContext.createAnalyser();
analyser.fftSize = 256;
const dataArray = new Uint8Array(analyser.frequencyBinCount);
```

---

## 2. Custom GLSL Shaders

**What it does:** Creates custom visual effects using GPU-accelerated code.

**How it works:**
- Vertex shaders control geometry positioning
- Fragment shaders control pixel-level coloring
- Use Three.js `ShaderMaterial` to apply custom shaders

**Use cases:** Water simulation, fire effects, holographic displays, procedural textures

```javascript
const shaderMaterial = new THREE.ShaderMaterial({
  uniforms: { uTime: { value: 0 } },
  vertexShader: `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: `
    uniform float uTime;
    varying vec2 vUv;
    void main() {
      gl_FragColor = vec4(sin(uTime + vUv.x), 0.0, 1.0, 1.0);
    }
  `
});
```

---

## 3. Particle Explosion on Click

**What it does:** Spawns hundreds of particles that burst outward when user clicks.

**How it works:**
- Create particle system with velocity vectors
- On click, apply impulse force from click position
- Update particle positions each frame with physics

**Use cases:** Interactive games, click feedback, visual celebrations

```javascript
particles.forEach(p => {
  p.velocity.set(
    (Math.random() - 0.5) * speed,
    (Math.random() - 0.5) * speed,
    (Math.random() - 0.5) * speed
  );
});
```

---

## 4. 3D Text Geometry

**What it does:** Renders extruded 3D text that can be animated.

**How it works:**
- Use `FontLoader` to load JSON font files
- Create `TextGeometry` with custom parameters
- Animate using rotation, scale, or morph targets

**Use cases:** Title sequences, 3D logos, typography art

```javascript
loader.load('fonts/helvetiker_regular.json', (font) => {
  const textGeo = new TextGeometry('Hello', {
    font: font,
    size: 1,
    height: 0.2,
    curveSegments: 12
  });
});
```

---

## 5. Post-Processing Effects

**What it does:** Adds cinematic effects to the rendered scene.

**Available effects:**
- **Bloom** — glow effect on bright areas
- **Chromatic Aberration** — RGB color separation
- **Glitch** — digital distortion
- **Film Grain** — retro noise
- **Depth of Field** — focus blur

**Use cases:** Cinematic intros, retro aesthetics, visual polish

```javascript
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
composer.addPass(new UnrealBloomPass(resolution, strength, radius, threshold));
```

---

## 6. Terrain Generation

**What it does:** Creates procedural 3D landscapes using noise algorithms.

**How it works:**
- Use Perlin or Simplex noise for elevation
- Apply height map to plane geometry vertices
- Add texture based on height (grass, rock, snow)

**Use cases:** Games, flyovers, planetary surfaces

```javascript
const simplex = new SimplexNoise();
geometry.attributes.position.array[i] = simplex.noise2D(x * scale, z * scale) * amplitude;
```

---

## 7. Physics-Based Interactions

**What it does:** Adds realistic physics simulation to 3D objects.

**Physics engines:**
- **Cannon.js** — lightweight, pure JS
- **Ammo.js** — Bullet port, WASM
- **Rapier** — fast, Rust-based

**Use cases:** Collisions, gravity, constraints, ragdolls

```javascript
const world = new CANNON.World();
world.gravity.set(0, -9.82, 0);
const body = new CANNON.Body({ mass: 1, shape: new CANNON.Sphere(1) });
```

---

## 8. VR-Ready Experience

**What it does:** Creates immersive virtual reality experiences.

**How it works:**
- Use WebXR API via Three.js XR manager
- Set up stereoscopic rendering
- Add VR controllers support

**Use cases:** Virtual tours, training simulations, gaming

```javascript
renderer.xr.enabled = true;
document.body.appendChild(VRButton.createButton(renderer));
```

---

## 9. LOD (Level of Detail)

**What it does:** Optimizes performance by showing simpler geometry at distance.

**How it works:**
- Create multiple meshes at different detail levels
- `LOD` object switches based on camera distance
- Reduces polygon count for distant objects

**Use cases:** Large scenes, mobile optimization, open worlds

```javascript
const lod = new THREE.LOD();
lod.addLevel(highDetailMesh, 0);
lod.addLevel(mediumDetailMesh, 50);
lod.addLevel(lowDetailMesh, 100);
```

---

## 10. Scroll-Based Animations

**What it does:** Links 3D animations to page scroll position.

**How it works:**
- Track scroll position via `window.scrollY`
- Map scroll to animation timeline
- Use GSAP ScrollTrigger for complex sequences

**Use cases:** Scrollytelling, portfolio sites, product reveals

```javascript
window.addEventListener('scroll', () => {
  const scroll = window.scrollY / document.body.scrollHeight;
  camera.position.z = 30 - scroll * 20;
});
```

---

## 11. Shader Toy-Style Visualizer

**What it does:** Creates procedural art using mathematical formulas.

**How it works:**
- Full-screen quad with fragment shader
- Ray marching for 3D shapes
- Domain repetition and folding

**Use cases:** Generative art, math visualization, demos

```javascript
// Ray marching SDF example
float sdSphere(vec3 p, float r) { return length(p) - r; }
float map(vec3 p) { return sdSphere(p, 1.0); }
```

---

## 12. Pathfinding Visualization

**What it does:** Visualizes navigation algorithms in 3D space.

**Algorithms:**
- A* (A-Star)
- Dijkstra
- BFS/DFS
- Flow fields

**Use cases:** Game AI, robot navigation, maze solvers

```javascript
function findPath(start, end, grid) {
  // A* implementation
  const openSet = [start];
  const cameFrom = new Map();
  // ... algorithm implementation
}
```

---

## 13. Volumetric Lighting/Fog

**What it does:** Creates atmospheric depth with light rays and fog.

**Techniques:**
- Exponential fog for depth
- Volumetric light scattering (god rays)
- Fog shaders with depth texture

**Use cases:** Atmospheric scenes, horror games, environmental drama

```javascript
scene.fog = new THREE.FogExp2(0x000000, 0.02);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
```

---

## 14. Custom Camera Transitions

**What it does:** Smoothly animates between camera positions and angles.

**How it works:**
- Define keyframe positions
- Interpolate using lerp or spline curves
- Add easing functions for natural motion

**Use cases:** Guided tours, cutscenes, focus transitions

```javascript
gsap.to(camera.position, {
  x: target.x,
  y: target.y,
  z: target.z,
  duration: 2,
  ease: "power2.inOut"
});
```

---

## 15. Particle System Editor

**What it does:** Visual tool for creating and tuning particle effects.

**Editable properties:**
- Particle count and lifetime
- Emission shape and rate
- Velocity and acceleration
- Color over lifetime
- Texture and blending

**Use cases:** VFX prototyping, games, motion graphics

---

## 16. Dynamic Environment Mapping

**What it does:** Creates real-time reflections using cube camera captures.

**How it works:**
- Use `CubeCamera` to capture scene from object's perspective
- Apply captured texture as envMap to materials
- Update dynamically for moving reflective surfaces

**Use cases:** Car paint, mirrors, water reflections, metallic objects

```javascript
const cubeRenderTarget = new THREE.WebGLCubeRenderTarget(256);
const cubeCamera = new THREE.CubeCamera(0.1, 1000, cubeRenderTarget);
material.envMap = cubeRenderTarget.texture;
```

---

## 17. Skeletal Animation & Rigging

**What it does:** Animates character models using bone-based skeletal systems.

**How it works:**
- Load models with embedded skeletal data (GLTF)
- Use `AnimationMixer` to play/control animations
- Blend multiple animations (walk + aim)

**Use cases:** Characters, creatures, mechanical animations

```javascript
const mixer = new THREE.AnimationMixer(model);
const action = mixer.clipAction(gltf.animations[0]);
action.play();
```

---

## 18. Instanced Rendering

**What it does:** Renders thousands of identical objects with a single draw call.

**How it works:**
- Use `InstancedMesh` for repeated geometry
- Update instance matrices for transforms
- Use instance attributes for per-object properties

**Use cases:** Forests, crowds, debris fields, particle systems

```javascript
const instancedMesh = new THREE.InstancedMesh(geometry, material, 10000);
for (let i = 0; i < 10000; i++) {
  dummy.position.set(Math.random() * 100, 0, Math.random() * 100);
  dummy.updateMatrix();
  instancedMesh.setMatrixAt(i, dummy.matrix);
}
```

---

## 19. Cloth Simulation

**What it does:** Simulates realistic fabric physics with wind and gravity.

**How it works:**
- Use Verlet integration for particle constraints
- Apply forces (gravity, wind, collision)
- Update mesh vertices each frame

**Use cases:** Flags, clothing, curtains, banners

```javascript
const cloth = new Cloth(width, height, segments);
function simulate(delta) {
  for (let i = 0; i < constraints.length; i++) {
    // Verlet integration
  }
}
```

---

## 20. Raycasting & Mouse Picking

**What it does:** Detects 3D objects under the mouse cursor.

**How it works:**
- Create ray from camera through mouse position
- Intersect with scene objects
- Return closest hit with face/uv data

**Use cases:** Object selection, drag & drop, interactive 3D UI

```javascript
const raycaster = new THREE.Raycaster();
raycaster.setFromCamera(mouse, camera);
const intersects = raycaster.intersectObjects(scene.children);
```

---

## 21. Procedural City Generation

**What it does:** Generates infinite cityscapes algorithmically.

**How it works:**
- Use grid-based placement with rules
- Vary building height, style, materials
- Add roads and landmarks procedurally

**Use cases:** Open-world games, visualizations, architectural concepts

```javascript
for (let x = 0; x < gridSize; x++) {
  for (let z = 0; z < gridSize; z++) {
    if (Math.random() > 0.3) {
      createBuilding(x, z, randomHeight());
    }
  }
}
```

---

## 22. Morph Targets

**What it does:** Blends between multiple geometry shapes smoothly.

**How it works:**
- Define target positions for each vertex
- Use `morphTargetInfluences` to control blend
- Often used for facial expressions

**Use cases:** Character expressions, shape transitions, deformations

```javascript
mesh.morphTargetInfluences[0] = 0.5; // 50% to first morph target
```

---

## 23. Light Probes & Global Illumination

**What it does:** Simulates realistic bounced light and ambient occlusion.

**How it works:**
- Place light probes throughout scene
- Bake or compute ambient light data
- Apply to materials for realistic lighting

**Use cases:** Architectural viz, product renders, realistic games

```javascript
const lightProbe = new THREE.LightProbe();
lightProbe.sh.fromArray(coefficients);
scene.add(lightProbe);
```

---

## 24. GPGPU Particle Systems

**What it does:** Computes particle physics on GPU for massive particle counts.

**How it works:**
- Use GPUComputationRenderer for position/velocity textures
- Read/write from render targets each frame
- Achieve millions of particles at 60fps

**Use cases:** Massive crowds, fluid simulations, starfields

```javascript
const gpuCompute = new GPUComputationRenderer(width, height, renderer);
const velocityVariable = gpuCompute.addVariable("velocity", shader, texture);
gpuCompute.init();
```

---

## 25. Binary Geometry & Optimization

**What it does:** Optimizes scene with compressed geometry formats.

**Formats:**
- **Draco** — compressed mesh data
- **KTX2** — GPU-ready textures
- **Meshopt** — geometry + animation compression

**Use cases:** Large models, mobile optimization, fast loading

```javascript
const loader = new GLTFLoader();
loader.setDRACOLoader(new DRACOLoader());
loader.load('model.glb', (gltf) => {
  gltf.scene.traverse((child) => {
    if (child.isMesh) child.geometry.optimize();
  });
});
```

---

## 26. Audio Positional 3D Sound

**What it does:** Creates spatial audio that changes with listener position.

**How it works:**
- Use Web Audio API with Three.js AudioListener
- Attach sounds to 3D objects
- Volume/pitch changes with distance and orientation

**Use cases:** Games, ambient environments, VR

```javascript
const listener = new THREE.AudioListener();
camera.add(listener);
const sound = new THREE.PositionalAudio(listener);
sound.setRefDistance(20);
```

---

## 27. Motion Blur

**What it does:** Adds directional blur based on object/camera movement.

**How it works:**
- Velocity buffer stores per-pixel motion
- Post-processing applies directional blur
- Can be per-object or screen-space

**Use cases:** Racing games, fast action, cinematic feel

```javascript
const effect = new SavePass(new ShaderPass(MotionBlurShader));
composer.addPass(effect);
```

---

## 28. Screen Space Reflections

**What it does:** Real-time reflections on rough surfaces in screen space.

**How it works:**
- Render scene to depth buffer
- Ray march in screen space
- Blend reflection based on roughness

**Use cases:** Wet floors, puddles, polished surfaces

```javascript
const ssrPass = new SSRPass({
  renderer, scene, camera, width, height
});
composer.addPass(ssrPass);
```

---

## 29. GPU Picking

**What it does:** High-performance object selection using GPU color coding.

**How it works:**
- Render scene with unique color per object to offscreen buffer
- Read pixel under mouse to identify object
- Much faster than raycasting for complex scenes

**Use cases:** Large scenes, CAD, scientific visualization

```javascript
renderer.setRenderTarget(pickingTexture);
renderer.render(scene, camera);
const pixelBuffer = new Uint8Array(4);
gl.readPixels(x, y, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixelBuffer);
```

---

## 30. Custom Buffer Attributes

**What it does:** Pass custom per-vertex/per-face data to shaders.

**How it works:**
- Create `BufferAttribute` with custom data
- Access in shader via varying/attribute
- Update dynamically for animations

**Use cases:** Custom simulations, data visualization, advanced effects

```javascript
const attr = new THREE.BufferAttribute(new Float32Array(count * 3), 3);
geometry.setAttribute('customAttr', attr);
```

---

## 31. Object Pooling

**What it does:** Reuses objects to prevent memory allocation during runtime.

**How it works:**
- Pre-allocate pool of objects
- Activate/deactivate instead of create/destroy
- Reduces GC pauses

**Use cases:** Bullets, particles, enemies, UI elements

```javascript
const pool = [];
function getObject() {
  return pool.pop() || new Mesh();
}
function returnObject(obj) {
  pool.push(obj);
}
```

---

## 32. Scene Graph Optimization

**What it does:** Organizes scene for efficient culling and updates.

**Techniques:**
- Bounding sphere/frustum culling
- Spatial partitioning (octree, BSP)
- Manual culling for complex objects

**Use cases:** Large worlds, complex scenes, mobile

```javascript
const octree = new Octree();
octree.fromGraphNode(scene);
octree.cull(camera);
```

---

## Getting Started

1. Install Three.js: `npm install three`
2. Use Vite or webpack for bundling
3. Start with basic shapes, then add complexity
4. Explore Three.js examples for reference

## Resources

- [Three.js Documentation](https://threejs.org/docs/)
- [Three.js Examples](https://threejs.org/examples/)
- [Shadertoy](https://www.shadertoy.com/) — shader inspiration
- [Awwwards](https://www.awwwards.com/) — design inspiration
