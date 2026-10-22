const { ipcRenderer } = require("electron");

let selectedFolderPath = null;
const chatHistory = [];
let lastSourcePaths = []; // files shown in the previous answer; lets "move these files" work
const BACKEND_URL = "http://127.0.0.1:8000";

// Line icons (Lucide-style) used in markup built from JS
const svgIcon = (paths) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;
const ICONS = {
    folder: svgIcon('<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>'),
    folderOpen: svgIcon('<path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"/>'),
    file: svgIcon('<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>'),
    eye: svgIcon('<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>'),
    stop: svgIcon('<rect x="6" y="6" width="12" height="12" rx="2"/>'),
    sparkles: svgIcon('<path d="M12 3l1.9 5.6 5.6 1.9-5.6 1.9L12 18l-1.9-5.6-5.6-1.9 5.6-1.9Z"/><path d="M19 3v4"/><path d="M21 5h-4"/>'),
    user: svgIcon('<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/>')
};

// --- Existing Navigation & Workspace Handlers ---

document.getElementById("dashboard-btn").addEventListener("click", () => {
    setActiveNav("dashboard-btn");
    // Preserve view
});

document.getElementById("files-btn").addEventListener("click", () => {
    setActiveNav("files-btn");
    if (selectedFolderPath) {
        document.getElementById("show-files-btn").click();
    }
});

document.getElementById("search-btn").addEventListener("click", () => {
    setActiveNav("search-btn");
    document.getElementById("chat-input").focus();
});

document.getElementById("settings-btn").addEventListener("click", () => {
    setActiveNav("settings-btn");
    alert("HelixOS Settings:\n- LLM Configuration: via .env\n- Persistence: ChromaDB (Local)\n- Port: 8000");
});

function setActiveNav(buttonId) {
    document.querySelectorAll(".nav-btn").forEach(btn => btn.classList.remove("active"));
    const target = document.getElementById(buttonId);
    if (target) target.classList.add("active");
}

// --- Monitored folder persistence ---

const MONITORED_KEY = "helix.monitoredFolders";
const SELECTED_KEY = "helix.selectedFolder";

// localStorage can throw (e.g. storage disabled), so every access is guarded
function loadMonitoredFolders() {
    try {
        const saved = JSON.parse(localStorage.getItem(MONITORED_KEY) || "[]");
        return Array.isArray(saved) ? saved : [];
    } catch (e) {
        return [];
    }
}

function saveMonitoredFolders(folders) {
    try {
        localStorage.setItem(MONITORED_KEY, JSON.stringify(folders));
    } catch (e) {
        console.error("Failed to save monitored folders:", e);
    }
}

function setMonitoredFolder(folderPath, isMonitored) {
    const folders = loadMonitoredFolders().filter(f => f !== folderPath);
    if (isMonitored) folders.push(folderPath);
    saveMonitoredFolders(folders);
}

function setSelectedFolder(folderPath) {
    selectedFolderPath = folderPath;
    document.getElementById("selected-folder").textContent = folderPath || "No folder selected";
    try {
        if (folderPath) localStorage.setItem(SELECTED_KEY, folderPath);
    } catch (e) {}
}

async function updateMonitorButton() {
    const btn = document.getElementById("monitor-btn");
    const isMonitoring = selectedFolderPath
        ? await ipcRenderer.invoke("is-monitoring", selectedFolderPath)
        : false;
    btn.innerHTML = isMonitoring ? `${ICONS.stop} Stop Monitoring` : `${ICONS.eye} Monitor Folder`;
    btn.classList.toggle("monitoring", isMonitoring);
    document.getElementById("folder-badge").classList.toggle("monitoring", isMonitoring);
}

// kind: "info" | "success" | "warn" | "error" | "muted" (sets the dot colour)
function addNotification(text, kind = "info", time = new Date()) {
    const entry = document.createElement("div");
    entry.className = `feed-entry feed-${kind}`;

    const body = document.createElement("div");
    body.className = "feed-body";
    const textEl = document.createElement("span");
    textEl.className = "feed-text";
    textEl.textContent = text;
    const timeEl = document.createElement("span");
    timeEl.className = "feed-time";
    timeEl.textContent = time.toLocaleTimeString();

    body.append(textEl, timeEl);
    entry.appendChild(body);
    document.getElementById("notifications").prepend(entry);
}

// Replaces the file list with a centred message and an optional button that clicks another button
function setFileListMessage(message, action = null) {
    const actionHtml = action
        ? `<button class="empty-action" data-click="${action.target}">${escapeHtml(action.label)}</button>`
        : "";
    document.getElementById("file-list").innerHTML =
        `<div class="empty-state">${ICONS.folderOpen}<p>${escapeHtml(message)}</p>${actionHtml}</div>`;
}

document.addEventListener("click", (e) => {
    const action = e.target.closest(".empty-action");
    if (action) document.getElementById(action.dataset.click)?.click();
});

// Restart watchers for every folder that was being monitored when the app last closed
async function restoreMonitoredFolders() {
    try {
        const lastSelected = localStorage.getItem(SELECTED_KEY);
        if (lastSelected) setSelectedFolder(lastSelected);
    } catch (e) {}

    for (const folderPath of loadMonitoredFolders()) {
        const result = await ipcRenderer.invoke("start-monitor", folderPath);
        if (result === "invalid-folder") {
            setMonitoredFolder(folderPath, false);
            addNotification(`Stopped remembering ${folderPath}: folder no longer exists`, "warn");
        }
    }
    await updateMonitorButton();
}

ipcRenderer.on("monitor-stopped", async (event, { path }) => {
    setMonitoredFolder(path, false);
    addNotification(`Monitoring stopped unexpectedly: ${path}`, "error");
    await updateMonitorButton();
});

document.getElementById("select-folder-btn").addEventListener("click", async () => {
    const folderPath = await ipcRenderer.invoke("select-folder");
    if (folderPath) {
        setSelectedFolder(folderPath);
        await updateMonitorButton();
        // The old list's checkboxes belong to the previous folder
        hideConfirmBar();
        fileActionsEl.classList.add("hidden");
        setFileListMessage("Folder selected", { label: "Show files", target: "show-files-btn" });
    }
});

document.getElementById("show-files-btn").addEventListener("click", async () => {
    if (!selectedFolderPath) {
        alert("Please select a folder first.");
        return;
    }

    await renderFileList();
});

// --- File list with checkboxes: select files, then Move/Copy them into a folder ---

const fileActionsEl = document.getElementById("file-actions");
const selectAllEl = document.getElementById("select-all-files");
const selectedCountEl = document.getElementById("selected-count");
const targetFolderInputEl = document.getElementById("target-folder-input");
const moveSelectedBtn = document.getElementById("move-selected-btn");
const copySelectedBtn = document.getElementById("copy-selected-btn");
const confirmBarEl = document.getElementById("file-op-confirm-bar");
const confirmTextEl = document.getElementById("file-op-confirm-text");
let pendingSelectionPlan = null;

function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function getSelectedFilePaths() {
    return [...document.querySelectorAll(".file-select:checked")].map(cb => cb.dataset.path);
}

function updateSelectionControls() {
    const boxes = document.querySelectorAll(".file-select");
    const selected = getSelectedFilePaths().length;
    selectedCountEl.textContent = `${selected} selected`;
    selectAllEl.checked = boxes.length > 0 && selected === boxes.length;
    selectAllEl.indeterminate = selected > 0 && selected < boxes.length;

    const ready = selected > 0 && targetFolderInputEl.value.trim() !== "" && !pendingSelectionPlan;
    moveSelectedBtn.disabled = !ready;
    copySelectedBtn.disabled = !ready;
}

function hideConfirmBar() {
    pendingSelectionPlan = null;
    confirmBarEl.classList.add("hidden");
    updateSelectionControls();
}

async function renderFileList() {
    const fileListEl = document.getElementById("file-list");
    hideConfirmBar();

    const entries = await ipcRenderer.invoke("show-files", selectedFolderPath);
    if (!Array.isArray(entries) || entries.length === 0) {
        setFileListMessage("This folder is empty");
        fileActionsEl.classList.add("hidden");
        return;
    }

    // Only files get a checkbox; folders are shown for context
    fileListEl.innerHTML = entries.map(entry => entry.isDirectory
        ? `<div class="file-row folder-row">${ICONS.folder}<span class="file-name">${escapeHtml(entry.name)}</span></div>`
        : `<label class="file-row" title="${escapeHtml(entry.name)}">
               <input type="checkbox" class="file-select" data-path="${escapeHtml(entry.path)}">
               ${ICONS.file}<span class="file-name">${escapeHtml(entry.name)}</span>
           </label>`
    ).join("");

    fileListEl.querySelectorAll(".file-select").forEach(cb => cb.addEventListener("change", updateSelectionControls));
    fileActionsEl.classList.toggle("hidden", fileListEl.querySelectorAll(".file-select").length === 0);
    updateSelectionControls();
}

selectAllEl.addEventListener("change", () => {
    document.querySelectorAll(".file-select").forEach(cb => { cb.checked = selectAllEl.checked; });
    updateSelectionControls();
});

targetFolderInputEl.addEventListener("input", updateSelectionControls);

function askToConfirmSelection(mode) {
    const files = getSelectedFilePaths();
    const folder = targetFolderInputEl.value.trim();
    if (!selectedFolderPath || files.length === 0 || !folder) return;

    pendingSelectionPlan = { root: selectedFolderPath, folder, mode, files };
    confirmTextEl.textContent = `${mode === "copy" ? "Copy" : "Move"} ${files.length} file(s) into ${folder}/ ?`;
    confirmBarEl.classList.remove("hidden");
    updateSelectionControls();
}

moveSelectedBtn.addEventListener("click", () => askToConfirmSelection("move"));
copySelectedBtn.addEventListener("click", () => askToConfirmSelection("copy"));
document.getElementById("file-op-cancel-btn").addEventListener("click", hideConfirmBar);

document.getElementById("file-op-confirm-btn").addEventListener("click", async () => {
    const plan = pendingSelectionPlan;
    if (!plan) return;
    confirmBarEl.classList.add("hidden");

    let result;
    try {
        result = await runFileOperation(plan);
    } catch (err) {
        addNotification(`File operation failed: ${err.message}`, "error");
        hideConfirmBar();
        return;
    }

    if (result.error) {
        addNotification(`Nothing was changed: ${result.error}`, "error");
    } else {
        const folderName = result.folder_path.split(/[\\/]/).pop();
        const verb = result.mode === "copy" ? "Copied" : "Moved";
        for (const r of result.results) {
            if (r.status === "done") {
                const savedAs = r.renamed ? ` (saved as ${r.dest.split(/[\\/]/).pop()})` : "";
                addNotification(`${verb} ${r.file} into ${folderName}/${savedAs}`, "success");
            } else if (r.status === "skipped") {
                addNotification(`Skipped ${r.file}: ${r.error}`, "warn");
            } else {
                addNotification(`Failed ${r.file}: ${r.error}`, "error");
            }
        }
        targetFolderInputEl.value = "";
    }
    await renderFileList();
});

document.getElementById("organize-btn").addEventListener("click", async () => {
    if (!selectedFolderPath) {
        alert("Please select a folder first.");
        return;
    }

    await ipcRenderer.invoke("organize-files", selectedFolderPath);
    alert("Files organized!");
    document.getElementById("show-files-btn").click();
});

document.getElementById("monitor-btn").addEventListener("click", async () => {
    if (!selectedFolderPath) {
        alert("Please select a folder first.");
        return;
    }

    const btn = document.getElementById("monitor-btn");
    btn.disabled = true; // prevent double clicks while the watcher starts/stops
    try {
        const isMonitoring = await ipcRenderer.invoke("is-monitoring", selectedFolderPath);
        if (isMonitoring) {
            await ipcRenderer.invoke("stop-monitor", selectedFolderPath);
            setMonitoredFolder(selectedFolderPath, false);
            addNotification(`Stopped monitoring: ${selectedFolderPath}`, "muted");
        } else {
            const result = await ipcRenderer.invoke("start-monitor", selectedFolderPath);
            if (result === "invalid-folder") {
                alert("This folder no longer exists.");
            } else {
                setMonitoredFolder(selectedFolderPath, true);
            }
        }
    } finally {
        btn.disabled = false;
        await updateMonitorButton();
    }
});

// --- Existing Live Event Formatters & Handlers ---

// Each describe* returns [text, kind] for addNotification
function describeEvent(payload) {
    switch (payload.event) {
        case "watching":
            return [`Watching folder: ${payload.path}`, "info"];
        case "created":
            return [`New file detected: ${payload.path}`, "success"];
        case "deleted":
            return [`File deleted: ${payload.path}`, "muted"];
        case "modified":
            return [`File modified: ${payload.path}`, "info"];
        case "moved":
            return [`File renamed/moved: ${payload.path} -> ${payload.destPath}`, "info"];
        default:
            return [`${payload.event}: ${payload.path}`, "info"];
    }
}

ipcRenderer.on("file-detected", (event, payload) => {
    const [text, kind] = describeEvent(payload);
    addNotification(text, kind, new Date(payload.timestamp * 1000));
});

function describeDocumentResult(result) {
    switch (result.status) {
        case "success": {
            // IndexFileResponse doesn't carry the extracted text, so only show a preview if one is present
            const text = result.text || "";
            const preview = text.slice(0, 150).replace(/\s+/g, " ").trim();
            const previewNote = preview ? ` "${preview}${text.length > 150 ? "..." : ""}"` : "";
            const chunkNote = typeof result.chunksIndexed === "number" ? `, indexed ${result.chunksIndexed} chunks` : "";
            return [`Processed ${result.filename}:${previewNote} (${result.textLength} chars${chunkNote})`, "success"];
        }
        case "empty":
            return [`Processed ${result.filename}: no extractable text found`, "warn"];
        case "error":
            return [`Failed to process ${result.filename}: ${result.error}`, "error"];
        case "unsupported":
            return [`Skipped ${result.filename}: unsupported file type`, "muted"];
        default:
            return [`${result.filename}: ${result.status}`, "info"];
    }
}

ipcRenderer.on("document-processed", (event, result) => {
    addNotification(...describeDocumentResult(result));
    checkBackendHealth();
});

ipcRenderer.on("document-deindexed", (event, result) => {
    addNotification(`Removed indexed chunks for deleted file: ${result.path}`, "muted");
    checkBackendHealth();
});

ipcRenderer.on("document-moved", (event, result) => {
    switch (result.status) {
        case "moved":
            addNotification(`Index updated for move: ${result.path} (${result.chunksMoved} chunks)`, "info");
            break;
        case "success":
            addNotification(`Re-indexed ${result.filename} after rename (${result.chunksIndexed} chunks)`, "success");
            break;
        case "deleted":
            addNotification(`Removed indexed chunks for renamed file: ${result.path}`, "muted");
            break;
        default:
            addNotification(
                `${result.filename}: ${result.status}${result.error ? ` (${result.error})` : ""}`,
                result.error ? "error" : "info"
            );
    }

    checkBackendHealth();
});

// --- Helix AI Chat Controller ---

const chatHistoryEl = document.getElementById("chat-history");
const chatInputEl = document.getElementById("chat-input");
const chatSendBtn = document.getElementById("chat-send-btn");
const chatLoadingEl = document.getElementById("chat-loading");
const clearChatBtn = document.getElementById("clear-chat-btn");
const welcomeHtml = chatHistoryEl.innerHTML; // restored by Clear

// Simple markdown formatter helper for bold, code, and newlines
function formatMarkdown(text) {
    if (!text) return "";
    let formatted = text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

    // Code blocks
    formatted = formatted.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
    // Inline code
    formatted = formatted.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Bold
    formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    // Italic
    formatted = formatted.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    // Newlines to br
    formatted = formatted.replace(/\n/g, '<br>');

    return formatted;
}

function appendUserMessage(text) {
    chatHistoryEl.querySelector(".welcome")?.remove();

    const msgEl = document.createElement("div");
    msgEl.className = "chat-message user-message";
    msgEl.innerHTML = `
        <div class="message-avatar">${ICONS.user}</div>
        <div class="message-content">
            <div class="message-author">You</div>
            <div>${formatMarkdown(text)}</div>
        </div>
    `;
    chatHistoryEl.appendChild(msgEl);
    chatHistoryEl.scrollTop = chatHistoryEl.scrollHeight;
}

function appendAssistantMessage(answer, sources = [], action = null) {
    const msgEl = document.createElement("div");
    msgEl.className = "chat-message assistant-message";

    let sourcesHtml = "";
    if (sources && sources.length > 0) {
        // Sort descending by relevance score (highest match percentage at the top)
        const sortedSources = [...sources].sort((a, b) => (b.relevance_score || 0) - (a.relevance_score || 0));

        const sourceCards = sortedSources.map(src => `
            <div class="source-card">
                <div class="source-info">
                    <div class="source-filename" title="${src.filename}">${ICONS.file}<span class="source-name">${src.filename}</span></div>
                    <div class="source-path" title="${src.path}">${src.path}</div>
                </div>
                <div class="source-actions">
                    <span class="relevance-tag">${Math.round(src.relevance_score * 100)}% match</span>
                    <button class="open-file-btn" data-path="${encodeURIComponent(src.path)}">Open File</button>
                </div>
            </div>
        `).join("");

        sourcesHtml = `
            <div class="sources-container">
                <div class="sources-title">Verified Sources & Discovered Files (${sortedSources.length})</div>
                ${sourceCards}
            </div>
        `;
    }

    msgEl.innerHTML = `
        <div class="message-avatar">${ICONS.sparkles}</div>
        <div class="message-content">
            <div class="message-author">Helix AI</div>
            <div>${formatMarkdown(answer)}</div>
            ${sourcesHtml}
        </div>
    `;

    // Attach open-file listeners
    msgEl.querySelectorAll(".open-file-btn").forEach(btn => {
        btn.addEventListener("click", async (e) => {
            const rawPath = decodeURIComponent(btn.getAttribute("data-path"));
            await handleOpenFile(rawPath);
        });
    });
    // Handle conversion action
    // Handle conversion action
    if (action && action.action_type === "convert_file") {
        const openBtn = document.createElement("button");
        openBtn.className = "convert-file-btn";
        openBtn.textContent = "Open Converted File";

        openBtn.addEventListener("click", async () => {
            const targetPath = action.payload.target_path;

            if (targetPath) {
                await handleOpenFile(targetPath);
            }
        });

        msgEl.querySelector(".message-content").appendChild(openBtn);
    }

    if (action && action.action_type === "confirm_file_operation") {
        msgEl.querySelector(".message-content").appendChild(buildFileOperationControls(action.payload));
    }

    if (action && action.action_type === "open_folder") {
        const openBtn = document.createElement("button");
        openBtn.className = "convert-file-btn";
        openBtn.textContent = "Open Folder";
        openBtn.addEventListener("click", () => handleOpenFile(action.payload.path));
        msgEl.querySelector(".message-content").appendChild(openBtn);
    }

    chatHistoryEl.appendChild(msgEl);
    chatHistoryEl.scrollTop = chatHistoryEl.scrollHeight;
}

// --- Chat file commands (create folder + move/copy files), run only after Confirm ---

function isUnderMonitoredFolder(folderPath) {
    const target = folderPath.toLowerCase().replace(/[\\/]+$/, "");
    return loadMonitoredFolders().some(f => {
        const watched = f.toLowerCase().replace(/[\\/]+$/, "");
        return target === watched || target.startsWith(watched + "\\") || target.startsWith(watched + "/");
    });
}

function buildFileOperationControls(plan) {
    const container = document.createElement("div");
    container.className = "file-op-controls";

    const confirmBtn = document.createElement("button");
    confirmBtn.className = "file-op-btn file-op-confirm";
    confirmBtn.textContent = "Confirm";

    const cancelBtn = document.createElement("button");
    cancelBtn.className = "file-op-btn file-op-cancel";
    cancelBtn.textContent = "Cancel";

    const finish = (label) => {
        confirmBtn.disabled = true;
        cancelBtn.disabled = true;
        container.dataset.state = label;
    };

    cancelBtn.addEventListener("click", () => {
        finish("cancelled");
        appendAssistantMessage("Cancelled. Nothing was changed.");
        chatHistory.push({ role: "assistant", content: "Cancelled. Nothing was changed." });
    });

    confirmBtn.addEventListener("click", async () => {
        finish("confirmed");
        await executeFileOperation(plan);
    });

    container.append(confirmBtn, cancelBtn);
    return container;
}

// Shared by chat commands and the file-list checkboxes
async function runFileOperation(plan) {
    const response = await fetch(`${BACKEND_URL}/api/files/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            ...plan,
            // When the folder is watched, watcher.py already updates the index for these moves
            sync_index: !isUnderMonitoredFolder(plan.root)
        })
    });
    if (!response.ok) throw new Error(`Server returned HTTP ${response.status}`);
    return response.json();
}

async function executeFileOperation(plan) {
    let result;
    try {
        result = await runFileOperation(plan);
    } catch (err) {
        appendAssistantMessage(`⚠️ **File operation failed**: ${err.message}`);
        return;
    }
    // Keep the checkbox list in sync if it's showing the same folder
    if (plan.root === selectedFolderPath && !fileActionsEl.classList.contains("hidden")) {
        renderFileList();
    }

    const verb = result.mode === "copy" ? "Copied" : "Moved";
    const lines = (result.results || []).map(r => {
        if (r.status === "done") {
            const name = r.dest.split(/[\\/]/).pop();
            return `- ✅ ${r.file}${r.renamed ? ` (saved as ${name}, a file with that name already existed)` : ""}`;
        }
        if (r.status === "skipped") return `- ⏭️ ${r.file}: ${r.error}`;
        return `- ❌ ${r.file}: ${r.error}`;
    });

    let answer;
    if (result.error) {
        answer = `❌ **Nothing was changed**: ${result.error}`;
    } else {
        const done = result.results.filter(r => r.status === "done").length;
        const folderName = result.folder_path.split(/[\\/]/).pop();
        answer = `${result.created_folder ? `Created **${folderName}/**. ` : ""}` +
            `${verb} ${done} of ${result.results.length} file(s) into **${folderName}/**:\n\n${lines.join("\n")}`;
        // So a follow-up like "move these to X" refers to the files where they are now
        lastSourcePaths = result.results.filter(r => r.status === "done").map(r => r.dest);
    }

    const action = result.folder_path
        ? { action_type: "open_folder", label: "Open Folder", payload: { path: result.folder_path } }
        : null;
    appendAssistantMessage(answer, [], action);
    chatHistory.push({ role: "assistant", content: answer });
}

async function handleOpenFile(filePath) {
    try {
        const res = await ipcRenderer.invoke("open-file", filePath);
        if (!res.success) {
            alert(`Could not open file:\n${res.error}`);
        }
    } catch (err) {
        alert(`Error opening file: ${err.message}`);
    }
}

const CHAT_TIMEOUT_MS = 90000;
let activeChatController = null; // in-flight /api/chat request; Clear and new questions abort it

async function handleSendMessage() {
    const query = chatInputEl.value.trim();
    if (!query) return;

    activeChatController?.abort("replaced");
    const controller = new AbortController();
    activeChatController = controller;
    const timeoutId = setTimeout(() => controller.abort("timeout"), CHAT_TIMEOUT_MS);

    chatInputEl.value = "";
    appendUserMessage(query);
    chatHistory.push({ role: "user", content: query });

    chatLoadingEl.classList.remove("hidden");
    chatHistoryEl.scrollTop = chatHistoryEl.scrollHeight;

    try {
        const response = await fetch(`${BACKEND_URL}/api/chat`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                message: query,
                history: chatHistory.slice(-6),
                current_folder: selectedFolderPath,
                recent_files: lastSourcePaths
            }),
            signal: controller.signal
        });

        if (!response.ok) {
            throw new Error(`Server returned HTTP ${response.status}`);
        }

        const data = await response.json();

        appendAssistantMessage(data.answer, data.sources, data.action);
        chatHistory.push({ role: "assistant", content: data.answer });
        // Keep the previous file list when this answer had no sources (e.g. a plan awaiting Confirm)
        if (data.sources && data.sources.length > 0) {
            lastSourcePaths = data.sources.map(s => s.path);
        }

    } catch (err) {
        const reason = controller.signal.aborted ? controller.signal.reason : null;
        if (reason === "timeout") {
            appendAssistantMessage(
                `⚠️ **Helix took too long to answer**\n\nNo reply after ${CHAT_TIMEOUT_MS / 1000} seconds. The backend may be busy indexing a large or scanned file. Please try again in a moment.`,
                []
            );
        } else if (!reason) {
            appendAssistantMessage(
                `⚠️ **Connection Issue with AI Engine**\n\nCould not reach the HelixOS FastAPI backend at \`${BACKEND_URL}\`.\n\nPlease ensure the backend server is running (\`python backend/main.py\`).\n*Details: ${err.message}*`,
                []
            );
        }
        // Cleared or replaced by a newer question: show nothing
    } finally {
        clearTimeout(timeoutId);
        if (activeChatController === controller) {
            activeChatController = null;
            chatLoadingEl.classList.add("hidden");
        }
    }
}

chatSendBtn.addEventListener("click", handleSendMessage);

chatInputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSendMessage();
    }
});

clearChatBtn.addEventListener("click", () => {
    activeChatController?.abort("cleared");
    chatLoadingEl.classList.add("hidden");
    chatHistory.length = 0;
    lastSourcePaths = [];
    chatHistoryEl.innerHTML = welcomeHtml;
});

// Suggestion chip quick triggers
document.addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (chip) {
        const prompt = chip.getAttribute("data-prompt");
        if (prompt) {
            chatInputEl.value = prompt;
            handleSendMessage();
        }
    }
});

// --- Backend Health Check & Status Polling ---

// The backend takes a while to boot (model + vector store load), so an unreachable
// backend counts as "starting" until it has been online once or the timeout passes
const BACKEND_STARTUP_TIMEOUT_MS = 120000;
const appStartTime = Date.now();
let backendWasOnline = false;

async function checkBackendHealth() {
    const pill = document.getElementById("backend-status-indicator");
    const text = document.getElementById("backend-status-text");

    try {
        const res = await fetch(`${BACKEND_URL}/api/health`);
        if (res.ok) {
            const data = await res.json();
            backendWasOnline = true;
            pill.className = "status-pill status-online";
            const chunkInfo = data.total_chunks > 0 ? `${data.total_chunks} chunks indexed` : "Ready";
            text.textContent = `Helix Engine Online (${chunkInfo})`;
        } else {
            pill.className = "status-pill status-connecting";
            text.textContent = "AI Engine Initializing...";
        }
    } catch (e) {
        const stillStarting = !backendWasOnline && Date.now() - appStartTime < BACKEND_STARTUP_TIMEOUT_MS;
        if (stillStarting) {
            pill.className = "status-pill status-connecting";
            text.textContent = "Starting AI Engine...";
        } else {
            pill.className = "status-pill status-error";
            text.textContent = "AI Backend Offline";
        }
    }
}

// Initial health check and periodic status poll
checkBackendHealth();
setInterval(checkBackendHealth, 5000);
restoreMonitoredFolders();