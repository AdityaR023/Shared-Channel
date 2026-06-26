// ── Auth guard ────────────────────────────────────────────────────────
requireAuth();
populateNavbarUser();

// Domain descriptions
const DOMAIN_DESC = {
  "2G":      "Legacy devices — Nokia, early Samsung",
  "3G":      "Third generation smartphones",
  "4G":      "Mid-range — Redmi, Realme, Samsung M-series",
  "5G":      "Premium — iPhone, S-series, Pixel",
  "Sales":   "Pricing, availability, offers",
  "Reviews": "User reviews and expert opinions",
};

// Index mapping
const INDEX_MAP = {
  "2G":      "smartqna_2g",
  "3G":      "smartqna_3g",
  "4G":      "smartqna_4g",
  "5G":      "smartqna_5g",
  "Sales":   "smartqna_sales",
  "Reviews": "smartqna_reviews",
};

// ── Load profile from API ─────────────────────────────────────────────
async function loadProfile() {
  try {
    const response = await authFetch("/api/profile");
    if (!response) return;

    const user = await response.json();

    // Username + email
    const initial = (user.username || user.email || "?")[0].toUpperCase();
    document.getElementById("profileAvatar").textContent   = initial;
    document.getElementById("profileUsername").textContent = user.username || "—";
    document.getElementById("profileEmail").textContent    = user.email    || "—";

    // API Key
    document.getElementById("apiKeyDisplay").textContent =
      user.api_key || "Not available";

    // Domains — from what user selected at signup
    renderDomains(user.domains || []);

    // Index mapping table
    renderIndexTable(user.domains || []);

  } catch (err) {
    console.error("Failed to load profile:", err);
  }
}

// ── Render assigned domains as chips ──────────────────────────────────
function renderDomains(domains) {
  const grid = document.getElementById("profileDomains");
  grid.innerHTML = "";

  if (!domains || domains.length === 0) {
    grid.innerHTML = `<p style="font-size:13px; color:#888;">No domains assigned.</p>`;
    return;
  }

  domains.forEach(domain => {
    const chip = document.createElement("div");
    chip.className = "domain-chip";
    chip.innerHTML = `
      <span class="chip-gen">${domain}</span>
      <span class="chip-desc">${DOMAIN_DESC[domain] || ""}</span>
    `;
    grid.appendChild(chip);
  });
}

// ── Render domain → index mapping table ──────────────────────────────
function renderIndexTable(domains) {
  const tbody = document.getElementById("indexTableBody");
  tbody.innerHTML = "";

  if (!domains || domains.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="3" style="color:#bbb; font-size:13px;">No domains assigned</td>
      </tr>`;
    return;
  }

  domains.forEach(domain => {
    const indexName = INDEX_MAP[domain] || `smartqna_${domain.toLowerCase()}`;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${domain}</td>
      <td><span class="index-name">${indexName}</span></td>
      <td>
        <span class="status-dot active"></span>Active
      </td>
    `;
    tbody.appendChild(tr);
  });
}

// ── API Secret reveal toggle ──────────────────────────────────────────
let secretRevealed = false;

function toggleReveal() {
  const secretEl = document.getElementById("apiSecretDisplay");
  const revealBtn= document.getElementById("revealBtn");
  const copyBtn  = document.getElementById("secretCopyBtn");

  if (!secretRevealed) {
    secretEl.textContent = "Your secret was shown once at signup. Regenerate if lost.";
    secretEl.classList.remove("masked");
    revealBtn.textContent= "Hide";
    copyBtn.style.display= "none";
    secretRevealed       = true;
  } else {
    secretEl.textContent = "••••••••••••••••••";
    secretEl.classList.add("masked");
    revealBtn.textContent= "Reveal";
    secretRevealed       = false;
  }
}

// ── Copy to clipboard ─────────────────────────────────────────────────
function copyField(elementId, btn) {
  const text = document.getElementById(elementId).textContent;
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent           = "Copied!";
    btn.classList.add("copied");
    setTimeout(() => {
      btn.textContent           = "Copy";
      btn.classList.remove("copied");
    }, 2000);
  });
}

// ── Init ──────────────────────────────────────────────────────────────
loadProfile();
