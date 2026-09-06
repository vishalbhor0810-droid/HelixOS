const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

let mainWindow;
let backendProcess = null;
const activeWatchers = new Map(); // folderPath -> child process

const SUPPORTED_EXTENSIONS = new Set([
    ".pdf", ".txt", ".docx", ".md", ".csv",
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

function runIndexer(filePath, { deleteMode }) {
    const args = ["indexer.py", filePath];
    if (deleteMode) args.push("--delete");

    const proc = spawn("python", args, { cwd: __dirname });

    let output = "";
    proc.stdout.on("data", (data) => {
        output += data.toString();
    });

    proc.stderr.on("data", (data) => {
        console.error("indexer.py error:", data.toString());
    });

    proc.on("close", () => {
        const trimmed = output.trim();
        if (!trimmed) return;

        try {
            const result = JSON.parse(trimmed);
            if (mainWindow && !mainWindow.isDestroyed()) {
                mainWindow.webContents.send(deleteMode ? "document-deindexed" : "document-processed", result);
            }
        } catch (err) {
            console.error("Failed to parse indexer output:", trimmed);
        }
    });
}

app.whenReady().then(() => {
    startBackend();

    mainWindow = new BrowserWindow({
        width: 1200,
        height: 850,
        minWidth: 950,
        minHeight: 650,
        title: "HelixOS",
        backgroundColor: "#0d1117",
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
    return fs.readdirSync(folderPath);
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

                if (!parsed.isDirectory && SUPPORTED_EXTENSIONS.has(path.extname(parsed.path).toLowerCase())) {
                    if (parsed.event === "created" || parsed.event === "modified") {
                        scheduleDocumentProcessing(parsed.path);
                    } else if (parsed.event === "deleted") {
                        if (pendingDocumentTimers.has(parsed.path)) {
                            clearTimeout(pendingDocumentTimers.get(parsed.path));
                            pendingDocumentTimers.delete(parsed.path);
                        }
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
        activeWatchers.delete(folderPath);
    });

    return "started";
});

// App Cleanup
app.on("before-quit", () => {
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
