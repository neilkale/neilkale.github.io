(function () {
  const canvas = document.querySelector("[data-monsoon-rain]");
  const cloudLayer = document.querySelector(".monsoon-clouds");
  if (!canvas || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    return;
  }

  const context = canvas.getContext("2d");
  if (!context) {
    return;
  }

  const rainDelay = Number.parseInt(canvas.dataset.rainDelay || "2400", 10);
  const drops = [];
  const startTime = performance.now();
  let previousTime = startTime;
  let spawnCarry = 0;
  let burstStrength = 0.7;
  let nextBurstAt = startTime + rainDelay;
  let width = 0;
  let height = 0;
  let deviceScale = 1;
  let rainFadeStart = 0;
  let rainFadeEnd = 1;

  const resize = () => {
    width = window.innerWidth;
    height = window.innerHeight;
    deviceScale = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * deviceScale);
    canvas.height = Math.round(height * deviceScale);
    context.setTransform(deviceScale, 0, 0, deviceScale, 0, 0);

    if (cloudLayer) {
      const cloudBounds = cloudLayer.getBoundingClientRect();
      rainFadeStart = Math.max(0, cloudBounds.top + cloudBounds.height * 0.62);
      rainFadeEnd = Math.max(rainFadeStart + 1, cloudBounds.bottom);
    }
  };

  const makeDrop = () => {
    const depth = 0.35 + Math.random() * 0.65;
    return {
      x: Math.random() * (width + 120) - 60,
      y: rainFadeStart - 8 - Math.random() * 28,
      length: 5 + depth * (8 + Math.random() * 13),
      speed: 180 + depth * (260 + Math.random() * 260),
      wind: -18 + Math.random() * 38,
      alpha: 0.035 + depth * (0.035 + Math.random() * 0.07),
      width: 0.35 + depth * 0.5,
    };
  };

  const updateBurst = (now) => {
    if (now < nextBurstAt) {
      return;
    }
    burstStrength = 0.45 + Math.random() * 1.05;
    nextBurstAt = now + 700 + Math.random() * 1700;
  };

  const draw = (now) => {
    const deltaSeconds = Math.min((now - previousTime) / 1000, 0.05);
    previousTime = now;
    context.clearRect(0, 0, width, height);

    const elapsed = now - startTime;
    if (elapsed >= rainDelay) {
      canvas.classList.add("is-raining");
      updateBurst(now);

      const ramp = Math.min((elapsed - rainDelay) / 6000, 1);
      const dropsPerSecond = (width / 42) * ramp * burstStrength;
      spawnCarry += dropsPerSecond * deltaSeconds;
      while (spawnCarry >= 1 && drops.length < 320) {
        drops.push(makeDrop());
        spawnCarry -= 1;
      }
    }

    const darkMode = document.body.classList.contains("dark");
    context.strokeStyle = darkMode ? "rgb(235, 235, 230)" : "rgb(30, 30, 28)";
    context.lineCap = "round";

    for (let index = drops.length - 1; index >= 0; index -= 1) {
      const drop = drops[index];
      const lengthScale = darkMode ? 1 : 1.2;
      const visibleLength = drop.length * lengthScale;
      drop.x += drop.wind * deltaSeconds;
      drop.y += drop.speed * deltaSeconds;

      if (drop.y - visibleLength > height || drop.x < -100 || drop.x > width + 100) {
        drops.splice(index, 1);
        continue;
      }

      const fadeProgress = Math.min(
        Math.max((drop.y - rainFadeStart) / (rainFadeEnd - rainFadeStart), 0),
        1,
      );
      const emergence = fadeProgress * fadeProgress * (3 - 2 * fadeProgress);
      context.globalAlpha = Math.min(
        drop.alpha * emergence * (darkMode ? 1 : 2.4),
        0.34,
      );
      context.lineWidth = drop.width * (darkMode ? 1 : 1.45);
      context.beginPath();
      context.moveTo(drop.x, drop.y);
      context.lineTo(
        drop.x - (drop.wind * visibleLength) / drop.speed,
        drop.y - visibleLength,
      );
      context.stroke();
    }
    context.globalAlpha = 1;
    requestAnimationFrame(draw);
  };

  resize();
  window.addEventListener("resize", resize, { passive: true });
  requestAnimationFrame(draw);
})();
