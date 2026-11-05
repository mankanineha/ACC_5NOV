// API Endpoint (Always routed through Nginx reverse proxy)
const API_BASE = "";

let activeRoute = null;
let activeShuttle = null;
let selectedSeat = null;
let currentLockTimer = null;
let lockExpiresIn = 0;

// Audio Synthesizer for tactile feedback (Pure Web Audio API, no external files)
const audioCtx = new (window.AudioContext || window.webkitAudioContext)();

function playTone(freq, type = "sine", duration = 0.15) {
  try {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
    gain.gain.setValueAtTime(0.12, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + duration);
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start();
    osc.stop(audioCtx.currentTime + duration);
  } catch (e) {
    // Audio might be blocked until user interacts with page
  }
}

function playSuccessChime() {
  playTone(523.25, "triangle", 0.12); // C5
  setTimeout(() => playTone(659.25, "triangle", 0.12), 100); // E5
  setTimeout(() => playTone(783.99, "triangle", 0.25), 200); // G5
}

function playRejectSound() {
  playTone(180, "sawtooth", 0.18);
  setTimeout(() => playTone(140, "sawtooth", 0.22), 120);
}

// DOM Elements
const currentPodNameEl = document.getElementById("current-pod-name");
const routeOriginEl = document.getElementById("route-origin");
const routeDestinationEl = document.getElementById("route-destination");
const activeVehicleNoEl = document.getElementById("active-vehicle-no");
const activeAvailableEl = document.getElementById("active-available");
const seatGridContainer = document.getElementById("seat-grid-container");

const studentIdInput = document.getElementById("student-id");
const studentNameInput = document.getElementById("student-name");
const btnLockSeat = document.getElementById("btn-lock-seat");
const btnConfirmBook = document.getElementById("btn-confirm-book");
const btnResetDemo = document.getElementById("btn-reset-demo");
const lockStatusBox = document.getElementById("lock-status-box");
const lockedSeatDisplay = document.getElementById("locked-seat-display");
const lockTimerEl = document.getElementById("lock-timer");
const timerBar = document.getElementById("timer-bar");
const toastMessage = document.getElementById("toast-message");

const ticketCard = document.getElementById("ticket-card");
const tktStudentName = document.getElementById("tkt-student-name");
const tktStudentId = document.getElementById("tkt-student-id");
const tktSeatNo = document.getElementById("tkt-seat-no");
const tktRefCode = document.getElementById("tkt-ref-code");


async function checkHealth() {
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    if (res.ok) {
      const data = await res.json();
      currentPodNameEl.textContent = data.pod_name || "k8s-pod";
    }
  } catch (err) {
    currentPodNameEl.textContent = "Offline";
  }
}


async function loadRoutesAndShuttle() {
  try {
    const res = await fetch(`${API_BASE}/api/routes`);
    const routes = await res.json();
    if (routes && routes.length > 0) {
      activeRoute = routes[0];
      routeOriginEl.textContent = activeRoute.source;
      routeDestinationEl.textContent = activeRoute.destination;

      const shuttlesRes = await fetch(`${API_BASE}/api/shuttles?route_id=${activeRoute.id}`);
      const shuttles = await shuttlesRes.json();
      if (shuttles && shuttles.length > 0) {
        activeShuttle = shuttles[0];
        activeVehicleNoEl.textContent = activeShuttle.vehicle_number;
        await loadSeats();
      }
    }
  } catch (err) {
    showToast("Connecting to Kubernetes backend...", "error");
  }
}


async function loadSeats() {
  if (!activeShuttle) return;

  try {
    const res = await fetch(`${API_BASE}/api/shuttles/${activeShuttle.id}/seats`);
    const seats = await res.json();
    
    // Count remaining available seats
    const freeCount = seats.filter(s => !s.is_reserved && !s.is_locked).length;
    activeAvailableEl.textContent = `${freeCount} Seats Free`;

    renderSeats(seats);
  } catch (err) {
    console.error("Error loading seats:", err);
  }
}


function renderSeats(seats) {
  seatGridContainer.innerHTML = "";

  // Group seats by row (e.g. 1A, 1B, 1C, 1D -> row 1)
  const rows = {};
  seats.forEach(seat => {
    const rowNum = seat.seat_number.slice(0, -1);
    if (!rows[rowNum]) rows[rowNum] = [];
    rows[rowNum].push(seat);
  });

  Object.keys(rows).forEach(rowNum => {
    const rowDiv = document.createElement("div");
    rowDiv.className = "seat-row";

    const rowSeats = rows[rowNum];
    const seatA = rowSeats.find(s => s.seat_number.endsWith("A"));
    const seatB = rowSeats.find(s => s.seat_number.endsWith("B"));
    const seatC = rowSeats.find(s => s.seat_number.endsWith("C"));
    const seatD = rowSeats.find(s => s.seat_number.endsWith("D"));

    if (seatA) rowDiv.appendChild(createSeatElement(seatA));
    if (seatB) rowDiv.appendChild(createSeatElement(seatB));

    // Aisle walkway space
    const aisle = document.createElement("div");
    aisle.className = "aisle-space";
    aisle.textContent = `ROW ${rowNum}`;
    rowDiv.appendChild(aisle);

    if (seatC) rowDiv.appendChild(createSeatElement(seatC));
    if (seatD) rowDiv.appendChild(createSeatElement(seatD));

    seatGridContainer.appendChild(rowDiv);
  });
}


function createSeatElement(seat) {
  const btn = document.createElement("button");
  btn.className = "seat-button";
  btn.dataset.seatId = seat.id;
  btn.dataset.seatNumber = seat.seat_number;

  let label = "AVAILABLE";
  if (seat.is_reserved) {
    btn.classList.add("booked");
    label = "TAKEN 👤";
    btn.disabled = true;
  } else if (seat.is_locked) {
    btn.classList.add("locked");
    label = `HELD ${seat.lock_ttl_remaining}s`;
    btn.disabled = true;
  } else if (selectedSeat && selectedSeat.id === seat.id) {
    btn.classList.add("selected");
    label = "CHOSEN ⭐";
  }

  btn.innerHTML = `
    <span class="seat-btn-no">${seat.seat_number}</span>
    <span class="seat-btn-tag">${label}</span>
  `;

  if (!seat.is_reserved && !seat.is_locked) {
    btn.onclick = () => selectSeat(seat);
  }

  return btn;
}


function selectSeat(seat) {
  playTone(440, "sine", 0.08); // pleasant tactile pop
  selectedSeat = seat;
  btnLockSeat.disabled = false;
  btnConfirmBook.disabled = false;
  btnLockSeat.textContent = `🔒 Hold Seat ${seat.seat_number} (30s)`;
  btnConfirmBook.textContent = `✅ Book Seat ${seat.seat_number} Now`;

  loadSeats();
}


// Provisional Lock (Redis SETNX)
btnLockSeat.addEventListener("click", async () => {
  if (!selectedSeat) return;

  const studentId = studentIdInput.value.trim();
  if (!studentId) {
    showToast("Please enter your Student ID", "error");
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/api/seats/lock`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        seat_id: selectedSeat.id,
        student_id: studentId
      })
    });

    const data = await res.json();
    if (res.ok) {
      playTone(587.33, "triangle", 0.15);
      showToast(`Seat ${selectedSeat.seat_number} provisionally locked for 30s!`, "success");
      startLockCountdown(data.expires_in_seconds || 30);
      btnLockSeat.disabled = true;
      loadSeats();
    } else {
      playRejectSound();
      showToast(data.detail || "Seat lock conflict: another student took it!", "error");
      selectedSeat = null;
      btnLockSeat.disabled = true;
      btnConfirmBook.disabled = true;
      loadSeats();
    }
  } catch (err) {
    playRejectSound();
    showToast("Network error acquiring provisional lock.", "error");
  }
});


function startLockCountdown(seconds) {
  clearInterval(currentLockTimer);
  lockExpiresIn = seconds;
  lockStatusBox.style.display = "block";
  lockedSeatDisplay.textContent = selectedSeat.seat_number;
  lockTimerEl.textContent = lockExpiresIn;
  timerBar.style.width = "100%";

  const total = seconds;
  currentLockTimer = setInterval(() => {
    lockExpiresIn--;
    lockTimerEl.textContent = lockExpiresIn;
    const pct = (lockExpiresIn / total) * 100;
    timerBar.style.width = `${pct}%`;

    if (lockExpiresIn <= 0) {
      clearInterval(currentLockTimer);
      lockStatusBox.style.display = "none";
      playRejectSound();
      showToast(`Hold on Seat ${selectedSeat.seat_number} expired! Released to others.`, "error");
      selectedSeat = null;
      btnLockSeat.disabled = true;
      btnConfirmBook.disabled = true;
      loadSeats();
    }
  }, 1000);
}


// Confirm & Persist Booking (PostgreSQL + Lua unlock)
document.getElementById("booking-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!selectedSeat) {
    showToast("Select an available seat first!", "error");
    return;
  }

  const studentId = studentIdInput.value.trim();
  const studentName = studentNameInput.value.trim();

  btnConfirmBook.disabled = true;
  btnConfirmBook.textContent = "Processing Transaction...";

  try {
    const res = await fetch(`${API_BASE}/api/book`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        seat_id: selectedSeat.id,
        student_id: studentId,
        student_name: studentName
      })
    });

    const data = await res.json();
    if (res.status === 201) {
      clearInterval(currentLockTimer);
      lockStatusBox.style.display = "none";
      playSuccessChime();
      showToast(`🎉 Booking Confirmed! Ticket: ${data.booking_reference}`, "success");

      // Populate Boarding Pass
      tktStudentName.textContent = data.student_name;
      tktStudentId.textContent = data.student_id;
      tktSeatNo.textContent = data.seat_number;
      tktRefCode.textContent = data.booking_reference;
      ticketCard.style.display = "block";

      selectedSeat = null;
      btnLockSeat.disabled = true;
      btnConfirmBook.textContent = "✅ Confirm & Get Boarding Pass";
      await loadSeats();
      await checkHealth();
    } else {
      playRejectSound();
      showToast(data.detail || "Booking failed due to concurrency conflict.", "error");
      btnConfirmBook.textContent = "✅ Confirm & Get Boarding Pass";
      await loadSeats();
    }
  } catch (err) {
    playRejectSound();
    showToast("Server transaction error during booking.", "error");
    btnConfirmBook.textContent = "✅ Confirm & Get Boarding Pass";
  }
});


// Reset Demo
btnResetDemo.addEventListener("click", async () => {
  if (!confirm("Reset all bookings & locks for a fresh demo?")) return;

  try {
    const res = await fetch(`${API_BASE}/api/admin/reset`, { method: "POST" });
    if (res.ok) {
      clearInterval(currentLockTimer);
      lockStatusBox.style.display = "none";
      ticketCard.style.display = "none";
      selectedSeat = null;
      btnLockSeat.disabled = true;
      btnConfirmBook.disabled = true;
      playTone(600, "sine", 0.2);
      showToast("Demo reset! All 24 shuttle seats are now free.", "success");
      await loadSeats();
    }
  } catch (err) {
    showToast("Failed to reset demo.", "error");
  }
});


function showToast(msg, type = "success") {
  toastMessage.textContent = msg;
  toastMessage.className = `toast-card toast-${type}`;
  toastMessage.style.display = "block";
  setTimeout(() => {
    toastMessage.style.display = "none";
  }, 4000);
}


// Start App
checkHealth();
loadRoutesAndShuttle();

// Periodic sync every 3s
setInterval(() => {
  checkHealth();
  loadSeats();
}, 3000);
