// Counts on the wall clock: a render cannot reproduce it.
const clock = document.getElementById("clock");
setInterval(() => { clock.textContent = String(Number(clock.textContent) + 1); }, 1000);
