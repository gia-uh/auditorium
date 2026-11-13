// The ball in the "descent" beat rolls down the valley as a function of time.
// A function of t is seekable; a requestAnimationFrame loop would not be.
const ball = document.getElementById("ball");

// The valley is the quadratic Bezier M 100 80 Q 800 1000 1500 80.
function valley(u) {
  const x = (1 - u) ** 2 * 100 + 2 * (1 - u) * u * 800 + u ** 2 * 1500;
  const y = (1 - u) ** 2 * 80 + 2 * (1 - u) * u * 1000 + u ** 2 * 80;
  return [x, y];
}

auditorium.track((s) => {
  // Gradient descent on the curve's parameter: big steps first, then small.
  const u = 0.5 - 0.42 * Math.exp(-2 * s);
  const [x, y] = valley(u);
  ball.setAttribute("cx", x.toFixed(1));
  ball.setAttribute("cy", (y - 24).toFixed(1));
}, { beat: "descent", from: 0, to: 2.5 });
