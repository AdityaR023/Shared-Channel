// ── Auth guard ────────────────────────────────────────────────────────
requireAuth();
populateNavbarUser();

// ── Elements ──────────────────────────────────────────────────────────
const showUploadBtn   = document.getElementById("showUploadBtn");
const uploadPanel     = document.getElementById("uploadPanel");
const closeUploadBtn  = document.getElementById("closeUploadBtn");
const closeUploadBtn2 = document.getElementById("closeUploadBtn2");
const uploadForm      = document.getElementById("uploadForm");
const uploadBtn       = document.getElementById("uploadBtn");
const uploadError     = document.getElementById("uploadError");
const uploadSuccess   = document.getElementById("uploadSuccess");
const dropzone        = document.getElementById("dropzone");
const fileInput       = document.getElementById("fileInput");
const fileSelected    = document.getElementById("fileSelected");
const selectedFileName= document.getElementById("selectedFileName");
const docList         = document.getElementById("docList");
const emptyState      = document.getElementById("emptyState");
const loadingState    = document.getElementById("loadingState");

// ── Upload panel show / hide ──────────────────────────────────────────
showUploadBtn.addEventListener("click", () => {
  uploadPanel.style.display = "block";
  uploadPanel.scrollIntoView({ behavior: "smooth" });
});

[closeUploadBtn, closeUploadBtn2].forEach(btn => {
  btn.addEventListener("click", () => {
    uploadPanel.style.display = "none";
    resetForm();
  });
});

// ── Dropzone logic ────────────────────────────────────────────────────
dropzone.addEventListener("click", () => fileInput.click());

dropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropzone.classList.add("active");
});
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("active"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("active");
  if (e.dataTransfer.files.length) selectFile(e.dataTransfer.files[0]);
});

fileInput.addEventListener("change", (e) => {
  if (e.target.files.length) selectFile(e.target.files[0]);
});

function selectFile(file) {
  selectedFileName.textContent = `📄 ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
  fileSelected.style.display   = "flex";
  document.getElementById("dropText").innerHTML =
    'File selected — ready to upload';
  document.getElementById("fileErr").classList.remove("visible");
}

function removeFile() {
  fileInput.value              = "";
  fileSelected.style.display   = "none";
  document.getElementById("dropText").innerHTML =
    'Drag &amp; drop a file here, or <span class="browse-link">browse</span>';
}

// ── Upload form submit ────────────────────────────────────────────────
uploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearAlerts();

  if (!fileInput.files.length) {
    document.getElementById("fileErr").classList.add("visible");
    return;
  }

  const file     = fileInput.files[0];
  const formData = new FormData();
  formData.append("file", file);

  // No manual metadata — just send the file
  // Group A's /generate-metadata handles everything automatically

  setLoading(true);

  try {
    const response = await authFetch("/api/ingest", {
      method: "POST",
      body:   formData,
      // Don't set Content-Type — browser sets multipart boundary
    });

    if (!response) return;

    const data = await response.json();

    if (response.ok && data.success) {
      showSuccess(
        `✅ "${file.name}" uploaded successfully! ` +
        `${data.chunks_indexed ?? 0} chunks indexed.`
      );
      resetForm();
      uploadPanel.style.display = "none";
      loadDocuments();
    } else {
      showError(data.detail || data.message || "Upload failed. Please try again.");
    }

  } catch (err) {
    showError("Could not reach the server.");
  } finally {
    setLoading(false);
  }
});

// ── Load document list ────────────────────────────────────────────────
async function loadDocuments() {
  showLoadingState(true);
  docList.innerHTML = "";

  const search = document.getElementById("searchFilter").value.trim();
  const type   = document.getElementById("typeFilter").value;

  const params = new URLSearchParams();
  if (search) params.append("search", search);
  if (type)   params.append("type",   type);

  try {
    const response = await authFetch(`/api/documents?${params}`);
    if (!response) return;

    const data = await response.json();
    showLoadingState(false);

    const docs = data.documents || [];

    if (docs.length === 0) {
      emptyState.style.display = "block";
      return;
    }

    emptyState.style.display = "none";
    docs.forEach(doc => renderDocCard(doc));

  } catch (err) {
    showLoadingState(false);
    docList.innerHTML = `
      <div class="alert error visible" style="margin-bottom:12px">
        Could not load documents. Is the search service running?
      </div>`;
  }
}

// ── Render document card ──────────────────────────────────────────────
function renderDocCard(doc) {
  const card = document.createElement("div");
  card.className = "doc-card";

  const fileName    = doc.model || doc.id || "Unknown";
  const fileType    = (doc.content_type || "").toUpperCase();
  const category    = doc.domain || doc.generation || "";
  const uploadDate  = doc.uploaded_at
    ? new Date(doc.uploaded_at).toLocaleDateString("en-IN",
        { day: "numeric", month: "short", year: "numeric" })
    : "—";

  card.innerHTML = `
    <div class="doc-info">
      <div class="doc-title">${fileName}</div>
      <div class="doc-meta">
        ${category ? `<span class="doc-badge badge-domain">${category}</span>` : ""}
        ${fileType ? `<span class="doc-badge badge-type">${fileType}</span>`  : ""}
      </div>
      <div class="doc-date">Uploaded: ${uploadDate}</div>
    </div>
    <div class="doc-actions">
      <button class="btn-icon delete"
              onclick="openDeleteModal('${doc.id}', '${fileName}')">
        🗑️ Delete
      </button>
    </div>
  `;

  docList.appendChild(card);
}

// ── Delete modal ──────────────────────────────────────────────────────
let pendingDeleteId = null;

function openDeleteModal(docId, docName) {
  pendingDeleteId = docId;
  document.getElementById("deleteDocName").textContent = docName;
  document.getElementById("deleteModal").style.display = "flex";
}

function closeDeleteModal() {
  pendingDeleteId = null;
  document.getElementById("deleteModal").style.display = "none";
}

document.getElementById("confirmDeleteBtn").addEventListener("click", async () => {
  if (!pendingDeleteId) return;

  const btn      = document.getElementById("confirmDeleteBtn");
  btn.disabled   = true;
  btn.textContent= "Deleting...";

  try {
    await authFetch(`/api/documents/${pendingDeleteId}`, { method: "DELETE" });
    closeDeleteModal();
    loadDocuments();
  } catch {
    alert("Could not delete. Please try again.");
  } finally {
    btn.disabled   = false;
    btn.textContent= "Delete";
  }
});

document.getElementById("deleteModal").addEventListener("click", (e) => {
  if (e.target === document.getElementById("deleteModal")) closeDeleteModal();
});

// ── Live search filter ────────────────────────────────────────────────
let debounceTimer;
document.getElementById("searchFilter").addEventListener("input", () => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(loadDocuments, 400);
});

// ── Helpers ───────────────────────────────────────────────────────────
function showLoadingState(loading) {
  loadingState.style.display = loading ? "block" : "none";
  emptyState.style.display   = "none";
}

function clearAlerts() {
  [uploadError, uploadSuccess].forEach(el => {
    el.classList.remove("visible");
    el.textContent = "";
  });
  document.getElementById("fileErr").classList.remove("visible");
}

function showError(msg) {
  uploadError.textContent = msg;
  uploadError.classList.add("visible");
  uploadPanel.scrollIntoView({ behavior: "smooth" });
}

function showSuccess(msg) {
  uploadSuccess.textContent = msg;
  uploadSuccess.classList.add("visible");
}

function setLoading(loading) {
  uploadBtn.disabled  = loading;
  uploadBtn.innerHTML = loading
    ? '<span class="spinner"></span> Uploading...'
    : "Upload &amp; Index";
}

function resetForm() {
  uploadForm.reset();
  removeFile();
  clearAlerts();
}

// ── Init ──────────────────────────────────────────────────────────────
loadDocuments();
