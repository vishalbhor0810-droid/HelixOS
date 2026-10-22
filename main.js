const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

let mainWindow;
let backendProcess = null;
const activeWatchers = new Map(); // folderPath -> child process
let isQuitting = false;

const SUPPORTED_EXTENSIONS = new Set([
    ".pdf", ".txt", ".docx", ".md", ".csv",
    ".xlsx", ".xlsm", ".pptx",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"
]);
const DOCUMENT_DEBOUNCE_MS = 1000;
const pendingDocumentTimers = new Map(); // filePath -> Timeout

// Start FastAPI Backend Process automatically
function startBackend() {
    try {
        backendProcess = spawn("python", ["backend/main.py"], {
            cwd: __dirname,
            stdio: ["ignore", "pipe", "pipe"]
        });

        backendProcess.stdout.on("data", (data) => {
            console.log(`[FastAPI stdout]: ${data.toString().trim()}`);
        });

        backendProcess.stderr.on("data", (data) => {
            console.log(`[FastAPI stderr]: ${data.toString().trim()}`);
        });

        backendProcess.on("close", (code) => {
            console.log(`FastAPI backend exited with code ${code}`);
            backendProcess = null;
        });
    } catch (err) {
        console.error("Failed to start FastAPI backend:", err);
    }
}

// Rapid-fire "modified" events get collapsed into a single processing run per file
function scheduleDocumentProcessing(filePath) {
    if (pendingDocumentTimers.has(filePath)) {
        clearTimeout(pendingDocumentTimers.get(filePath));
    }

    const timer = setTimeout(() => {
        pendingDocumentTimers.delete(filePath);
        runIndexer(filePath, { deleteMode: false });
    }, DOCUMENT_DEBOUNCE_MS);

    pendingDocumentTimers.set(filePath, timer);
}

const http = require("http");
const BACKEND_URL = "http://127.0.0.1:8000";

function postToBackend(method, apiPath, payload, replyChannel) {
    const body = JSON.stringify(payload);
    const options = {
        hostname: "127.0.0.1",
        port: 8000,
        path: apiPath,
        method: method,
        headers: {
            "Content-Type": "application/json",
            "Content-Length": Buffer.byteLength(body)
        }
    };

    const req = http.request(options, (res) => {
        let data = "";
        res.on("data", (chunk) => { data += chunk; });
        res.on("end", () => {
            try {
                const result = JSON.parse(data);
                if (mainWindow && !mainWindow.isDestroyed()) {
                    mainWindow.webContents.send(replyChannel, result);
                }
            } catch (err) {
                console.error("Failed to parse indexer response:", data);
            }
        });
    });

    req.on("error", (err) => {
        console.error("Indexer HTTP request failed:", err.message);
    });

    req.write(body);
    req.end();
}

function runIndexer(filePath, { deleteMode }) {
    postToBackend(
        deleteMode ? "DELETE" : "POST",
        "/api/index/file",
        { file_path: filePath },
        deleteMode ? "document-deindexed" : "document-processed"
    );
}

function cancelPendingProcessing(filePath) {
    if (pendingDocumentTimers.has(filePath)) {
        clearTimeout(pendingDocumentTimers.get(filePath));
        pendingDocumentTimers.delete(filePath);
    }
}

function isSupported(filePath) {
    if (path.basename(filePath).startsWith("~$")) return false; // Office lock files (~$Budget.xlsx)
    return SUPPORTED_EXTENSIONS.has(path.extname(filePath).toLowerCase());
}

app.whenReady().then(() => {
    startBackend();

    mainWindow = new BrowserWindow({
        width: 1200,
        height: 850,
        minWidth: 950,
        minHeight: 650,
        title: "HelixOS",
        backgroundColor: "#080b12",
        autoHideMenuBar: true, // press Alt to show File/Edit/View/Window
        webPreferences: {
            nodeIntegration: true,
            contextIsolation: false
        }
    });

    mainWindow.loadFile("index.html");

    ipcMain.handle("select-folder", async () => {
        const result = await dialog.showOpenDialog({
            properties: ["openDirectory"]
        });

        return result.filePaths[0];
    });

    // Safe File Opening Handler
    ipcMain.handle("open-file", async (event, targetPath) => {
        if (!targetPath || typeof targetPath !== "string") {
            return { success: false, error: "Invalid path provided." };
        }

        const resolvedPath = path.resolve(targetPath);
        if (!fs.existsSync(resolvedPath)) {
            return { success: false, error: `File not found on disk: ${resolvedPath}` };
        }

        try {
            const errorMsg = await shell.openPath(resolvedPath);
            if (errorMsg) {
                return { success: false, error: errorMsg };
            }
            return { success: true, path: resolvedPath };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
});

ipcMain.handle("show-files", async (event, folderPath) => {
    if (!folderPath || !fs.existsSync(folderPath)) {
        return [];
    }
    // Folders first, then files, each alphabetically; full paths so the UI can act on selections
    return fs.readdirSync(folderPath, { withFileTypes: true })
        .filter(entry => !entry.name.startsWith("~$")) // Office lock files
        .map(entry => ({
            name: entry.name,
            path: path.join(folderPath, entry.name),
            isDirectory: entry.isDirectory()
        }))
        .sort((a, b) => (b.isDirectory - a.isDirectory) || a.name.localeCompare(b.name));
});

ipcMain.handle("organize-files", async (event, folderPath) => {
    if (!folderPath || !fs.existsSync(folderPath)) {
        return "invalid-folder";
    }

    const files = fs.readdirSync(folderPath);

    for (const file of files) {
        const fullPath = path.join(folderPath, file);
        try {
            if (fs.statSync(fullPath).isDirectory()) continue;
        } catch (e) {
            continue;
        }

        const extension = path.extname(file).toLowerCase();

        const categories = {
            ".pdf": "PDFs",
            ".docx": "Documents",
            ".txt": "Documents",
            ".md": "Documents",
            ".xlsx": "Excel",
            ".xls": "Excel",
            ".png": "Images",
            ".jpg": "Images",
            ".jpeg": "Images"
        };

        const category = categories[extension];

        if (category) {
            const categoryFolder = path.join(folderPath, category);
            fs.mkdirSync(categoryFolder, { recursive: true });
            const source = fullPath;
            const destination = path.join(categoryFolder, file);

            try {
                fs.renameSync(source, destination);
            } catch (err) {
                console.error(`Failed to move ${source}:`, err);
            }
        }
    }
    return "done";
});

ipcMain.handle("start-monitor", async (event, folderPath) => {
    if (!folderPath || !fs.existsSync(folderPath)) {
        return "invalid-folder";
    }

    if (activeWatchers.has(folderPath)) {
        return "already-watching";
    }

    const watcher = spawn("python", ["watcher.py", folderPath], { cwd: __dirname });
    activeWatchers.set(folderPath, watcher);

    let buffer = "";
    watcher.stdout.on("data", (data) => {
        buffer += data.toString();
        const lines = buffer.split("\n");
        buffer = lines.pop(); // keep incomplete trailing line for next chunk

        for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) continue;

            try {
                const parsed = JSON.parse(trimmed);
                if (mainWindow && !mainWindow.isDestroyed()) {
                    mainWindow.webContents.send("file-detected", parsed);
                }

                if (parsed.event === "moved") {
                    // Checked before the extension filter: editors like Word save by renaming
                    // a temp file onto the real name, so the source may be unsupported
                    cancelPendingProcessing(parsed.path);
                    if (parsed.isDirectory || isSupported(parsed.path) || isSupported(parsed.destPath)) {
                        postToBackend(
                            "POST",
                            "/api/index/move",
                            { src_path: parsed.path, dest_path: parsed.destPath },
                            "document-moved"
                        );
                    }
                } else if (!parsed.isDirectory && isSupported(parsed.path)) {
                    if (parsed.event === "created" || parsed.event === "modified") {
                        scheduleDocumentProcessing(parsed.path);
                    } else if (parsed.event === "deleted") {
                        cancelPendingProcessing(parsed.path);
                        runIndexer(parsed.path, { deleteMode: true });
                    }
                }
            } catch (err) {
                console.error("Failed to parse watcher output:", trimmed);
            }
        }
    });

    watcher.stderr.on("data", (data) => {
        console.error("watcher.py error:", data.toString());
    });

    watcher.on("close", () => {
        // Only clear the entry if it still belongs to this process (a stop + restart may have replaced it)
        if (activeWatchers.get(folderPath) === watcher) {
            activeWatchers.delete(folderPath);
        }
        // Tell the UI about unexpected exits (e.g. folder deleted); not when stopped on purpose or quitting,
        // otherwise the saved folder list would be wiped on every app close
        if (!watcher.stoppedByUser && !isQuitting && mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send("monitor-stopped", { path: folderPath });
        }
    });

    return "started";
});

ipcMain.handle("stop-monitor", async (event, folderPath) => {
    const watcher = activeWatchers.get(folderPath);
    if (!watcher) {
        return "not-watching";
    }

    watcher.stoppedByUser = true;
    activeWatchers.delete(folderPath);
    try { watcher.kill(); } catch (e) {}

    // Drop debounced indexing runs for files inside the folder we just stopped watching
    const prefix = path.resolve(folderPath) + path.sep;
    for (const filePath of [...pendingDocumentTimers.keys()]) {
        if (path.resolve(filePath).startsWith(prefix)) {
            cancelPendingProcessing(filePath);
        }
    }

    return "stopped";
});

ipcMain.handle("is-monitoring", async (event, folderPath) => {
    return activeWatchers.has(folderPath);
});

// App Cleanup
app.on("before-quit", () => {
    isQuitting = true;
    for (const [folder, proc] of activeWatchers.entries()) {
        try { proc.kill(); } catch (e) {}
    }
    activeWatchers.clear();

    if (backendProcess) {
        try { backendProcess.kill(); } catch (e) {}
        backendProcess = null;
    }
});

app.on("window-all-closed", () => {
    if (process.platform !== "darwin") {
        app.quit();
    }
});
