// iTE — Coming Soon Landing Page Script
// Ambient motion, waitlist form, progressive reveals

(function() {
  'use strict';

  // ===== Ambient Pointer Motion =====
  const hero = document.querySelector('.hero');
  const ambientField = document.querySelector('.ambient-field');
  let currentX = 0;
  let currentY = 0;
  let targetX = 0;
  let targetY = 0;

  function setPointerTarget(clientX, clientY) {
    const width = window.innerWidth || 1;
    const height = window.innerHeight || 1;
    targetX = ((clientX / width) - 0.5) * 28;
    targetY = ((clientY / height) - 0.5) * 24;
  }

  function animateAmbient() {
    currentX += (targetX - currentX) * 0.08;
    currentY += (targetY - currentY) * 0.08;
    document.body.style.setProperty('--pointer-x', currentX.toFixed(2) + 'px');
    document.body.style.setProperty('--pointer-y', currentY.toFixed(2) + 'px');
    requestAnimationFrame(animateAmbient);
  }

  if (hero && ambientField && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    hero.addEventListener('pointermove', (event) => {
      setPointerTarget(event.clientX, event.clientY);
    });

    hero.addEventListener('pointerleave', () => {
      targetX = 0;
      targetY = 0;
    });

    window.addEventListener('deviceorientation', (event) => {
      if (typeof event.gamma === 'number' && typeof event.beta === 'number') {
        targetX = Math.max(-18, Math.min(18, event.gamma * 0.8));
        targetY = Math.max(-16, Math.min(16, event.beta * 0.35));
      }
    }, { passive: true });
  }

  animateAmbient();

  // ===== Waitlist Form =====
  const form = document.getElementById('waitlistForm');
  const emailInput = document.getElementById('emailInput');
  const submitBtn = form?.querySelector('.btn-primary');
  const statusEl = document.getElementById('formStatus');

  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      
      const email = emailInput.value.trim();
      if (!email || !isValidEmail(email)) {
        showStatus('Please enter a valid email', 'error');
        return;
      }

      setLoading(true);

      try {
        // Try Formspree endpoint if configured, otherwise simulate
        const formAction = form.getAttribute('action');
        if (formAction && !formAction.includes('YOUR_FORM_ID')) {
          const response = await fetch(formAction, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email })
          });
          
          if (response.ok) {
            showStatus("You're on the list. We'll be in touch.", 'success');
            emailInput.value = '';
          } else {
            throw new Error('Submission failed');
          }
        } else {
          // Mock submission for demo
          await simulateSubmission();
          showStatus("Thanks! We'll reach out when spots open.", 'success');
          emailInput.value = '';
        }
      } catch (err) {
        showStatus('Something went wrong. DM @kiishidavid on X.', 'error');
      } finally {
        setLoading(false);
      }
    });
  }

  function isValidEmail(email) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  }

  function setLoading(isLoading) {
    submitBtn.disabled = isLoading;
    submitBtn.classList.toggle('loading', isLoading);
  }

  function showStatus(message, type) {
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.className = 'form-status ' + type;
    
    // Clear after 5 seconds
    setTimeout(() => {
      statusEl.textContent = '';
      statusEl.className = 'form-status';
    }, 5000);
  }

  function simulateSubmission() {
    return new Promise(resolve => setTimeout(resolve, 1000));
  }

  // ===== Console Welcome =====
  if (console) {
    console.log(
      '%ciTE',
      'font-family: "JetBrains Mono", monospace; font-size: 32px; font-weight: bold; color: #4edea3; text-shadow: 0 0 20px rgba(78,222,163,0.3);'
    );
    console.log(
      '%cBuilt for the way you code',
      'font-family: "Inter", sans-serif; font-size: 14px; color: #8c93a1;'
    );
    console.log(
      '%cComing soon. Kimi 2.5 inside a terminal-native workflow.',
      'font-family: "Inter", sans-serif; font-size: 12px; color: #6b7280;'
    );
  }

})();
