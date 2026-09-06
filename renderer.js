const { ipcRenderer } = require("electron");

let selectedFolderPath = null;
const chatHistory = [];
const BACKEND_URL = "http://127.0.0.1:8000";

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

document.getElementById("select-folder-btn").addEventListener("click", async () => {
    selectedFolderPath = await ipcRenderer.invoke("select-folder");
    if (selectedFolderPath) {
        document.getElementById("selected-folder").textContent = selectedFolderPath;
    }
});

document.getElementById("show-files-btn").addEventListener("click", async () => {
    if (!selectedFolderPath) {
        alert("Please select a folder first.");
        return;
    }

    const files = await ipcRenderer.invoke("show-files", selectedFolderPath);
    const fileListEl = document.getElementById("file-list");
    if (Array.isArray(files) && files.length > 0) {
        fileListEl.innerHTML = files.map(f => `📄 ${f}`).join("<br>");
    } else {
        fileListEl.innerHTML = "<em>No files found in directory.</em>";
    }
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

    const result = await ipcRenderer.invoke("start-monitor", selectedFolderPath);

    if (result === "already-watching") {
        alert("This folder is already being monitored.");
    } else {
        alert("Folder is now being monitored!");
    }
});

// --- Existing Live Event Formatters & Handlers ---

function describeEvent(payload) {
    const time = new Date(payload.timestamp * 1000).toLocaleTimeString();

    switch (payload.event) {
        case "watching":
            return `[${time}] Watching folder: ${payload.path}`;
        case "created":
            return `[${time}] New file detected: ${payload.path}`;
        case "deleted":
            return `[${time}] File deleted: ${payload.path}`;
        case "modified":
            return `[${time}] File modified: ${payload.path}`;
        case "moved":
            return `[${time}] File renamed/moved: ${payload.path} -> ${payload.destPath}`;
        default:
            return `[${time}] ${payload.event}: ${payload.path}`;
    }
}

ipcRenderer.on("file-detected", (event, payload) => {
    const notifications = document.getElementById("notifications");
    const entry = document.createElement("div");
    entry.textContent = describeEvent(payload);
    notifications.prepend(entry);
});

function describeDocumentResult(result) {
    const time = new Date().toLocaleTimeString();

    switch (result.status) {
        case "success": {
            const preview = (result.text || "").slice(0, 150).replace(/\s+/g, " ").trim();
            const chunkNote = typeof result.chunksIndexed === "number" ? `, indexed ${result.chunksIndexed} chunks` : "";
            return `[${time}] Processed ${result.filename}: "${preview}${result.text.length > 150 ? "..." : ""}" (${result.textLength} chars${chunkNote})`;
        }
        case "empty":
            return `[${time}] Processed ${result.filename}: no extractable text found`;
        case "error":
            return `[${time}] Failed to process ${result.filename}: ${result.error}`;
        case "unsupported":
            return `[${time}] Skipped ${result.filename}: unsupported file type`;
        default:
            return `[${time}] ${result.filename}: ${result.status}`;
    }
}

ipcRenderer.on("document-processed", (event, result) => {
    const notifications = document.getElementById("notifications");
    const entry = document.createElement("div");
    entry.textContent = describeDocumentResult(result);
    notifications.prepend(entry);
    checkBackendHealth();
});

ipcRenderer.on("document-deindexed", (event, result) => {
    const notifications = document.getElementById("notifications");
    const entry = document.createElement("div");
    const time = new Date().toLocaleTimeString();
    entry.textContent = `[${time}] Removed indexed chunks for deleted file: ${result.path}`;
    notifications.prepend(entry);
    checkBackendHealth();
});

// --- Helix AI Chat Controller ---

const chatHistoryEl = document.getElementById("chat-history");
const chatInputEl = document.getElementById("chat-input");
const chatSendBtn = document.getElementById("chat-send-btn");
const chatLoadingEl = document.getElementById("chat-loading");
const clearChatBtn = document.getElementById("clear-chat-btn");

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
    const msgEl = document.createElement("div");
    msgEl.className = "chat-message user-message";
    msgEl.innerHTML = `
        <div class="message-avatar">👤</div>
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
                    <div class="source-filename">📄 ${src.filename}</div>
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
        <div class="message-avatar">🤖</div>
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

    chatHistoryEl.appendChild(msgEl);
    chatHistoryEl.scrollTop = chatHistoryEl.scrollHeight;
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

async function handleSendMessage() {
    const query = chatInputEl.value.trim();
    if (!query) return;

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
                current_folder: selectedFolderPath
            })
        });

        if (!response.ok) {
            throw new Error(`Server returned HTTP ${response.status}`);
        }

        const data = await response.json();
        chatLoadingEl.classList.add("hidden");

        appendAssistantMessage(data.answer, data.sources, data.action);
        chatHistory.push({ role: "assistant", content: data.answer });

    } catch (err) {
        chatLoadingEl.classList.add("hidden");
        appendAssistantMessage(
            `⚠️ **Connection Issue with AI Engine**\n\nCould not reach the HelixOS FastAPI backend at \`${BACKEND_URL}\`.\n\nPlease ensure the backend server is running (\`python backend/main.py\`).\n*Details: ${err.message}*`,
            []
        );
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
    chatHistory.length = 0;
    chatHistoryEl.innerHTML = `
        <div class="chat-message assistant-message intro-message">
            <div class="message-avatar">🤖</div>
            <div class="message-content">
                <div class="message-author">Helix AI</div>
                <p>Chat history cleared. How can I assist you with your documents?</p>
            </div>
        </div>
    `;
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

async function checkBackendHealth() {
    const pill = document.getElementById("backend-status-indicator");
    const text = document.getElementById("backend-status-text");

    try {
        const res = await fetch(`${BACKEND_URL}/api/health`);
        if (res.ok) {
            const data = await res.json();
            pill.className = "status-pill status-online";
            const chunkInfo = data.total_chunks > 0 ? `${data.total_chunks} chunks indexed` : "Ready";
            text.textContent = `Helix Engine Online (${chunkInfo})`;
        } else {
            pill.className = "status-pill status-connecting";
            text.textContent = "AI Engine Initializing...";
        }
    } catch (e) {
        pill.className = "status-pill status-error";
        text.textContent = "AI Backend Offline";
    }
}

// Initial health check and periodic status poll
checkBackendHealth();
setInterval(checkBackendHealth, 5000);