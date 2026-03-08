# GUI Animation Improvement Plan

**Project**: iTE GUI (Flet-based)  
**Created**: 2026-03-08  
**Status**: Draft

---

## Executive Summary

This document outlines a comprehensive plan to improve animations in the iTE GUI application using Flet's native implicit animations. The current implementation lacks smooth transitions, uses generic loading indicators, and has limited visual feedback. This plan leverages Flet's built-in animation system for cleaner, more performant implementations.

---

## Current State Analysis

### Existing Animation Elements

1. **Thinking indicator** (`_show_thinking_indicator` in `app.py:243`)
   - Progress ring with animated dots ("Thinking", "Thinking.", etc.)
   - Uses `asyncio.sleep(0.36)` for phase cycling
   - Basic implementation, no smooth transitions

2. **Sidebar toggle** (`_apply_sidebar_state` in `layout.py:359`)
   - Immediate width change - no animation
   - Controls visibility toggle only

3. **Scroll behavior** (`scroll.py`)
   - Auto-scroll to bottom on new messages
   - No smooth scroll animation

4. **Loading states** (`_set_loading` in `layout.py:663`)
   - Progress ring indicator
   - Basic disabled state on input

### Missing Animations
- No fade-in for new messages
- No slide animations for sidebar
- No hover effects on interactive elements beyond color changes
- No transition animations for dialogs/overlays
- No skeleton loaders for async content
- No micro-interactions on buttons

---

## Flet Implicit Animations Overview

Flet provides **implicit animations** that automatically animate property changes. When you set a target value, the control animates from the old value to the new one.

### Available Animation Properties

From [Flet Documentation](https://docs.flet.dev/cookbook/animations/#implicit-animations):

- `animate_opacity` - Opacity transitions
- `animate_rotation` - Rotation changes
- `animate_scale` - Scale transformations
- `animate_offset` - Slide effects (uses `ft.Offset` scaled to control size)
- `animate_position` - Position changes (requires Stack or `page.overlay`)
- `animate` - Container properties (size, bgcolor, border, gradient)

### Animation Value Options

```python
# Option 1: Boolean - enables animation with 1000ms duration, LINEAR curve
animate_opacity=True

# Option 2: Integer - enables animation with specified duration (ms), LINEAR curve
animate_opacity=300

# Option 3: Animation object - full control over duration and curve
animate_opacity=ft.Animation(duration=300, curve=ft.AnimationCurve.EASE_OUT_CUBIC)
```

### Animation Curves

Common curves from `ft.AnimationCurve`:
- `EASE_OUT_CUBIC` - Fast start, slow end (recommended for UI)
- `EASE_IN_CUBIC` - Slow start, fast end
- `EASE_IN_OUT` - Smooth start and end
- `BOUNCE_OUT` - Bouncy effect
- `LINEAR` - Constant speed

### Animation End Callback

```python
container = ft.Container(
    animate_opacity=300,
    on_animation_end=lambda e: print(f"Animation ended: {e.data}")
)
```

---

## Animation Guidelines

### Timing Constants (Recommended)
```python
# Timing constants to add to tokens.py
ANIMATION_INSTANT = 0       # 0ms - immediate
ANIMATION_FAST = 100        # 100ms - quick feedback
ANIMATION_NORMAL = 200      # 200ms - standard transitions (DEFAULT)
ANIMATION_SLOW = 300        # 300ms - deliberate motion
ANIMATION_SMOOTH = 400      # 400ms - complex transitions

# Recommended defaults per use case
ANIMATION_FADE = 200        # Opacity changes
ANIMATION_SLIDE = 300       # Offset/slide effects
ANIMATION_SCALE = 250       # Scale transforms
```

### Performance Budget
- Animations must not exceed 16ms per frame (60fps target)
- Flet handles frame interpolation automatically
- Use `EASE_OUT_CUBIC` for most UI transitions (feels natural)

---

## Proposed Improvements (Updated with Flet Native APIs)

### 1. Message Entry Animations

**Problem**: Messages appear instantly without transition.

**Solution**: Use Flet's `animate_opacity` and `animate_offset` for smooth entrance.

```python
# In messages.py - when adding a new message card
def _create_message_container(self, message_content: ft.Control) -> ft.Container:
    """Create message container with entrance animation."""
    return ft.Container(
        content=message_content,
        opacity=0,
        offset=ft.Offset(0, 0.1),  # Slide up effect (10% of height)
        animate_opacity=ft.Animation(duration=200, curve=ft.AnimationCurve.EASE_OUT_CUBIC),
        animate_offset=ft.Animation(duration=200, curve=ft.AnimationCurve.EASE_OUT_CUBIC),
    )

def _add_message_with_animation(self, ...):
    """Add message with entrance animation."""
    container = self._create_message_container(...)
    container.opacity = 1  # Triggers animation
    container.offset = ft.Offset(0, 0)
    # After this, the container animates from opacity=0 to 1
    # and offset from (0, 0.1) to (0, 0)
```

**Implementation Steps**:
1. Wrap message cards in `ft.Container` with animation properties
2. Set initial `opacity=0` and `offset=(0, 0.1)`
3. Immediately set target values to trigger animation
4. Flet handles the interpolation automatically

### 2. Sidebar Slide Animation

**Problem**: Sidebar toggles instantly without transition.

**Solution**: Use `animate_width` via the `animate` property.

```python
# In layout.py - _toggle_sidebar
def _toggle_sidebar(self):
    self.sidebar_collapsed = not self.sidebar_collapsed
    self._apply_sidebar_state(animate=True)

def _apply_sidebar_state(self, update: bool = True, animate: bool = False):
    if not self.sidebar_root:
        return
    
    collapsed = self.sidebar_collapsed
    target_width = THREADS_WIDTH_COLLAPSED if collapsed else THREADS_WIDTH
    
    if animate:
        self.sidebar_root.width = target_width
        # Note: Container doesn't have animate_width directly
        # Use animate with duration as workaround
    else:
        self.sidebar_root.width = target_width
    
    # ... rest of state changes
```

**Alternative: Using AnimatedSwitcher**
```python
# For content transitions, use AnimatedSwitcher
sidebar_content = ft.AnimatedSwitcher(
    self.collapsed_content if collapsed else self.expanded_content,
    transition=ft.AnimatedSwitcherTransition.SCALE,
    duration=250,
    switch_in_curve=ft.AnimationCurve.EASE_OUT_CUBIC,
    switch_out_curve=ft.AnimationCurve.EASE_IN_CUBIC,
)
```

### 3. Enhanced Thinking Indicator

**Problem**: Current indicator is basic with choppy text changes.

**Solution**: Use smooth opacity transitions for text cycling.

```python
# In app.py - improved thinking indicator
def _show_thinking_indicator(self):
    # ... existing setup ...
    
    # Add smooth animation to thinking container
    self.thinking_row = ft.Container(
        content=self._wrap_in_lane(ft.Row([bubble], alignment=ft.MainAxisAlignment.START)),
        animate_opacity=ft.Animation(duration=150, curve=ft.AnimationCurve.EASE_OUT_CUBIC),
    )
    
    # Set initial state
    self.thinking_row.opacity = 0
    self._append_chat_control(self.thinking_row)
    
    # Animate in
    self.thinking_row.opacity = 1
    self.page.update()

async def _animate_thinking_text(self):
    phases = ["Thinking", "Thinking.", "Thinking..", "Thinking..."]
    i = 0
    try:
        while self._is_turn_running and self.thinking_text and self.page:
            # Fade out
            self.thinking_text.opacity = 0
            self.thinking_text.update()
            await asyncio.sleep(100)
            
            # Change text
            self.thinking_text.value = phases[i % len(phases)]
            i += 1
            
            # Fade in
            self.thinking_text.opacity = 1
            self.thinking_text.update()
            await asyncio.sleep(260)  # Total ~360ms per cycle
    except asyncio.CancelledError:
        return
```

### 4. Button Micro-interactions

**Problem**: Buttons have no hover/click feedback beyond color change.

**Solution**: Use `animate_scale` and shadow on hover.

```python
# In layout.py - create animated button wrapper
def _create_animated_button(
    self,
    content: ft.Control,
    on_click,
    tooltip: str = None,
) -> ft.Container:
    """Create button with hover/press animations."""
    def on_hover(e: ft.HoverEvent):
        if e.data == "true":  # Hovering
            button.scale = 1.02
            button.shadow = SHADOW_SUBTLE[0] if SHADOW_SUBTLE else None
        else:  # Not hovering
            button.scale = 1.0
            button.shadow = None
        button.update()
    
    button = ft.Container(
        content=content,
        scale=1.0,
        animate_scale=150,  # Flet native animation
        shadow=None,
        on_hover=on_hover,
        on_click=on_click,
    )
    if tooltip:
        button.tooltip = tooltip
    return button

# Usage for sidebar toggle button
self.sidebar_toggle_button = ft.Container(
    content=ft.IconButton(
        icon=ft.Icons.KEYBOARD_DOUBLE_ARROW_LEFT,
        on_click=lambda e: self._toggle_sidebar(),
    ),
    animate_scale=150,
    on_hover=self._on_button_hover,
)
```

### 5. Dialog/Modal Animations

**Problem**: Dialogs appear instantly.

**Solution**: Use `AnimatedSwitcher` for dialog content transitions.

```python
# In layout.py - animated dialog
def _show_animated_dialog(self, dialog: ft.AlertDialog):
    """Show dialog with scale and fade animation."""
    # Wrap dialog content with animation
    if dialog.content:
        dialog.content = ft.Container(
            content=dialog.content,
            opacity=0,
            scale=0.9,
            animate_opacity=ft.Animation(duration=200, curve=ft.AnimationCurve.EASE_OUT_CUBIC),
            animate_scale=ft.Animation(duration=200, curve=ft.AnimationCurve.EASE_OUT_CUBIC),
        )
    
    # Show dialog
    self.page.show_dialog(dialog)
    
    # Trigger entrance animation
    dialog.content.opacity = 1
    dialog.content.scale = 1.0
    self.page.update()

# Alternative: AnimatedSwitcher for dialog content changes
dialog_switcher = ft.AnimatedSwitcher(
    first_content,
    transition=ft.AnimatedSwitcherTransition.SCALE,
    duration=250,
    switch_in_curve=ft.AnimationCurve.EASE_OUT_CUBIC,
)
```

### 6. Skeleton Loaders

**Problem**: No loading state for async content (e.g., branch list).

**Solution**: Create skeleton containers with subtle opacity animation.

```python
# In layout.py or messages.py
def _create_skeleton(self, width: int, height: int) -> ft.Container:
    """Create a skeleton loader placeholder with pulse animation."""
    return ft.Container(
        width=width,
        height=height,
        border_radius=RADIUS_SM,
        bgcolor=SURFACE_3,
        animate_opacity=ft.Animation(duration=1000, curve=ft.AnimationCurve.EASE_IN_OUT),
        # Use a Stack with two overlapping containers for shimmer effect
    )

def _create_shimmer_skeleton(self, width: int, height: int) -> ft.Stack:
    """Create a skeleton with shimmer effect."""
    base = ft.Container(
        width=width,
        height=height,
        border_radius=RADIUS_SM,
        bgcolor=SURFACE_3,
    )
    
    # Shimmer overlay (animate width or offset)
    shimmer = ft.Container(
        width=width // 3,
        height=height,
        border_radius=RADIUS_SM,
        bgcolor=ft.Colors.WHITE,
        opacity=0.1,
        offset=ft.Offset(-1, 0),  # Start off-screen left
        animate_offset=ft.Animation(
            duration=1500,
            curve=ft.AnimationCurve.EASE_IN_OUT,
        ),
    )
    
    def animate_shimmer(e):
        # Reset to left
        shimmer.offset = ft.Offset(-1, 0)
        shimmer.update()
        # Animate to right
        shimmer.offset = ft.Offset(2, 0)  # Off-screen right
        shimmer.update()
    
    # Note: Would need a loop to continuously animate
    # This is a simplified version
    
    return ft.Stack([base, shimmer])

# Usage in branch list loading
def _show_branch_list_loading(self):
    """Show skeleton loaders while loading branches."""
    if not self.branch_picker_list:
        return
    
    self.branch_picker_list.controls = [
        self._create_shimmer_skeleton(200, 32),
        self._create_shimmer_skeleton(180, 32),
        self._create_shimmer_skeleton(220, 32),
    ]
    self.page.update()
```

### 7. Card/Component Entrance Animations

**Problem**: Cards appear instantly.

**Solution**: Staggered animation using `on_animation_end` callback.

```python
# Create cards with entrance animation
def _create_animated_card(self, content: ft.Control, delay_ms: int = 0) -> ft.Container:
    """Create card with staggered entrance animation."""
    card = ft.Container(
        content=content,
        opacity=0,
        scale=0.95,
        animate_opacity=ft.Animation(duration=200, curve=ft.AnimationCurve.EASE_OUT_CUBIC),
        animate_scale=ft.Animation(duration=200, curve=ft.AnimationCurve.EASE_OUT_CUBIC),
    )
    
    # Schedule animation after delay
    def trigger_animation():
        card.opacity = 1
        card.scale = 1.0
        self.page.update()
    
    if delay_ms > 0:
        asyncio.create_task(self._delayed_animation(card, delay_ms))
    else:
        trigger_animation()
    
    return card

async def _delayed_animation(self, control: ft.Control, delay_ms: int):
    await asyncio.sleep(delay_ms / 1000)
    control.opacity = 1
    control.scale = 1.0
    if self.page:
        self.page.update()

# Example: Staggered thread list loading
def _animate_thread_list(self, threads: list):
    """Add threads with staggered entrance."""
    for i, thread in enumerate(threads):
        thread_card = self._create_thread_card(thread)
        delay = i * 50  # 50ms stagger
        animated_card = self._create_animated_card(thread_card, delay)
        self.sidebar_threads_column.controls.append(animated_card)
    self.page.update()
```

---

## Implementation Roadmap

### Phase 1: Foundation (Low Effort, High Impact)
1. Add animation constants to `tokens.py`
2. Add fade-in for new messages (Section 1)
3. Add button hover scale effects (Section 4)

### Phase 2: Core Animations (Medium Effort)
4. Animate sidebar toggle (Section 2)
5. Improve thinking indicator (Section 3)
6. Add dialog entrance animations (Section 5)

### Phase 3: Polish (Higher Effort)
7. Skeleton loaders for async content (Section 6)
8. Staggered list animations (Section 7)
9. Micro-interactions on all interactive elements

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/ite/ui/gui/tokens.py` | Add animation timing constants and curves |
| `src/ite/ui/gui/builders/layout.py` | Sidebar animation, button interactions, skeleton loaders |
| `src/ite/ui/gui/builders/messages.py` | Message entry animations |
| `src/ite/ui/gui/app.py` | Thinking indicator animation |
| `src/ite/ui/gui/controllers/scroll.py` | Consider AnimatedSwitcher for content |

---

## Key Flet Animation Patterns

### Pattern 1: Implicit Opacity
```python
container = ft.Container(
    opacity=0,
    animate_opacity=200,  # Triggers animation when opacity changes
)
container.opacity = 1  # Animates from 0 to 1
```

### Pattern 2: Slide with Offset
```python
container = ft.Container(
    offset=ft.Offset(-1, 0),  # Off-screen left (1x width)
    animate_offset=300,
)
container.offset = ft.Offset(0, 0)  # Slides in
```

### Pattern 3: Scale Pop
```python
button = ft.Container(
    scale=1.0,
    animate_scale=ft.Animation(duration=200, curve=ft.AnimationCurve.BOUNCE_OUT),
)
button.scale = 1.1  # Bouncy scale effect
button.scale = 1.0  # Bouncy return
```

### Pattern 4: AnimatedSwitcher
```python
switcher = ft.AnimatedSwitcher(
    content,
    transition=ft.AnimatedSwitcherTransition.SCALE,
    duration=250,
    switch_in_curve=ft.AnimationCurve.EASE_OUT_CUBIC,
)
switcher.content = new_content  # Automatically animates
```

### Pattern 5: Chained Animations
```python
container = ft.Container(
    animate_opacity=300,
    on_animation_end=self._on_animation_complete,
)

def _on_animation_complete(self, e):
    if e.data == "opacity":
        # Trigger next animation
        self.next_control.scale = 1.0
        self.page.update()
```

---

## Testing Checklist

- [ ] Verify animations run at 60fps (no jank)
- [ ] Test sidebar animation on different window sizes
- [ ] Verify disabled users can still interact (keyboard nav)
- [ ] Test with reduced motion preference (accessibility)
- [ ] Verify no animation memory leaks (cleanup on dismiss)
- [ ] Test animation callbacks fire correctly
- [ ] Verify `on_animation_end` doesn't fire prematurely

---

## Accessibility Considerations

1. **Respect `prefers-reduced-motion`**
```python
def _should_animate(self) -> bool:
    # Check system preference via JavaScript in web mode
    # For now, use a config flag
    return self.config.enable_animations if hasattr(self.config, 'enable_animations') else True
```

2. **Disable animations when needed**
```python
# Use 0 duration to disable
container.animate_opacity = 0  # Instant, no animation

# Or set to False
container.animate_opacity = False
```

3. **Never convey meaning through animation alone** - ensure all animated states have static alternatives

4. **Duration limits** - no animation exceeding 500ms for state changes

---

## Future Considerations

- Consider using Lottie/rive files for complex animations (requires `flet-rive` package)
- Add animation preview in developer settings
- Track animation performance in production metrics
- Explore `AnimatedRotation`, `AnimatedScale` for specialized needs
