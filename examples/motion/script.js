// An arm sweeping a circle, driven by auditorium.track(): a function of t is
// seekable, which a requestAnimationFrame loop is not.
const arm = document.getElementById("arm");
const tip = document.getElementById("tip");

auditorium.track((s) => {
  const angle = s * Math.PI;  // half a turn per second
  const x = (200 * Math.cos(angle)).toFixed(1);
  const y = (200 * Math.sin(angle)).toFixed(1);
  arm.setAttribute("x2", x);
  arm.setAttribute("y2", y);
  tip.setAttribute("cx", x);
  tip.setAttribute("cy", y);
}, { beat: "track", from: 0, to: 4 });
