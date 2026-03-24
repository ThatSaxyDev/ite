# ITE Landing Page

A powerful monochromatic landing page for ITE — Interactive Terminal Environment.

## Quick Start

### Preview (Static)
```bash
# Open index.html directly in browser
open index.html

# Or use a simple HTTP server
python3 -m http.server 8080
```

### Development (Go Server)
```bash
# Run the Go server
go run server.go

# Open browser
open http://localhost:8080
```

## Features

### Visual Effects
- **Loading Screen** — Animated loader with staggered bounce
- **Grid Background** — Perspective grid with parallax scroll
- **Particle System** — Floating particles with random timing
- **Noise Overlay** — Subtle film grain texture
- **Vignette** — Edge darkening for depth

### Animations
- **Glitch Effect** — Periodic glitch on title text
- **Cursor Blink** — Terminal-style cursor animation
- **Orbit Animation** — Rotating rings with orbiting dots
- **Magnetic Buttons** — Buttons respond to mouse proximity
- **Scroll Reveal** — Elements animate in on scroll

### Interactions
- **Terminal Replay** — Click terminal to replay animation
- **Copy to Clipboard** — One-click copy install command
- **Smooth Scroll** — Anchor navigation with smooth scroll
- **Nav Blur** — Navigation gains backdrop blur on scroll

## File Structure

```
landing/
├── index.html   # Complete landing page (HTML/CSS/JS)
├── server.go    # Go server with embedded assets
└── README.md    # This file
```

## Customization

### Colors
All colors are CSS variables in `:root`:
```css
--bg-deep: #000000;
--text-white: #ffffff;
--text-muted: #606060;
--border: #1a1a1a;
```

### Typography
- **Headings**: Space Grotesk (Google Fonts)
- **Body/Code**: JetBrains Mono (Google Fonts)

### Content
Edit the HTML directly to update:
- Hero text and badges
- Feature cards
- How it works steps
- CTA section
- Footer links

## Browser Support

- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

## Performance

- No external dependencies (pure vanilla JS)
- CSS animations (GPU accelerated)
- Embedded fonts (preconnect optimization)
- Minimal DOM manipulation
