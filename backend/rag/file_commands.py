"""
Turns chat commands like "create a folder named Major and move these 4 documents into it"
into a plan the user confirms in the UI. Nothing is changed on disk here; execution happens
in backend.core.file_ops.execute_plan after the user clicks Confirm.
"""
import os
import re
import json
import logging
from typing import List, Optional, Dict, Any

from backend.models.schemas import ChatRequest, ChatResponse, ActionItem
from backend.rag.llm_client import llm_client
from backend.core import file_ops

logger = logging.getLogger("helix.file_commands")

_FOLDER_WORD = re.compile(r"\b(folder|directory)\b", re.IGNORECASE)
_ACTION_WORD = re.compile(
    r"\b(create|make|move|put|add|copy|place|transfer|group|organi[sz]e)\b", re.IGNORECASE
)

PARSER_PROMPT = """You convert file-management requests into a JSON plan. Reply with JSON only, no other text.

Schema:
{"intent": "organize" or "none",
 "folder": "<name of the folder to create or use>",
 "mode": "move" or "copy",
 "files": ["<path copied exactly from AVAILABLE FILES>"],
 "unmatched": ["<any file the user mentioned that has no match in AVAILABLE FILES>"]}

Rules:
- intent is "organize" only when the user asks to put/move/copy/add files into a folder. Otherwise intent is "none".
- "these", "those", "them", "the above files", "these N documents" mean the files in RECENT FILES.
- Only use paths that appear in AVAILABLE FILES, copied exactly. Never invent a path.
- Descriptive references are fine when exactly one file clearly fits (e.g. "my resume" -> "Resume_2026.pdf").
- If a mentioned file could be more than one path, or none, put the user's wording in "unmatched".
- mode is "copy" only if the user says copy/duplicate; otherwise "move".
- folder is a single folder name with no slashes.
"""


def looks_like_file_command(query: str) -> bool:
    """Cheap pre-filter so ordinary questions don't pay for an extra LLM call."""
    return bool(_FOLDER_WORD.search(query) and _ACTION_WORD.search(query))


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _reply(answer: str, action: Optional[ActionItem] = None) -> ChatResponse:
    return ChatResponse(answer=answer, sources=[], action=action, confidence="high")


async def handle_file_command(request: ChatRequest) -> Optional[ChatResponse]:
    """Return a ChatResponse for file commands, or None to fall through to normal RAG answering."""
    query = request.message.strip()
    if not looks_like_file_command(query) or not llm_client.is_configured():
        return None

    root = request.current_folder
    if not root or not os.path.isdir(root):
        return _reply("Please select a workspace folder first (📂 Select Folder), then repeat the command.")
    root = os.path.abspath(root)

    available, truncated = file_ops.list_workspace_files(root)
    recent = [
        os.path.relpath(p, root) for p in request.recent_files
        if os.path.isfile(p) and file_ops.is_inside(p, root)
    ]

    user_message = (
        f"REQUEST: {query}\n\n"
        f"RECENT FILES (shown in my previous answer):\n" + ("\n".join(recent) or "(none)") + "\n\n"
        f"AVAILABLE FILES:\n" + ("\n".join(available) or "(none)")
    )
    raw = await llm_client.generate_response(
        system_prompt=PARSER_PROMPT,
        user_message=user_message,
        conversation_history=None,
        temperature=0.0
    )
    plan = _extract_json(raw)
    logger.info("File command plan: %s", plan)

    if plan is None:
        return _reply("I couldn't understand that as a file command, so nothing was changed. "
                      "Try: *Create a folder named Major and move report.pdf and notes.docx into it.*")
    if plan.get("intent") != "organize":
        return None  # not a file command after all; answer normally

    folder = str(plan.get("folder") or "").strip()
    name_error = file_ops.validate_folder_name(folder)
    if name_error:
        return _reply(f"{name_error} Nothing was changed.")

    unmatched = [str(u) for u in plan.get("unmatched") or [] if str(u).strip()]
    resolved, invalid = file_ops.resolve_files(root, [str(f) for f in plan.get("files") or []])

    # Refuse partial plans: better to ask than to quietly move the wrong set of files
    if unmatched or invalid:
        missing = ", ".join(f"`{m}`" for m in unmatched + invalid)
        hint = " (only the first 200 files in this folder were searched)" if truncated else ""
        return _reply(
            f"I couldn't match these files exactly: {missing}{hint}. Nothing was changed.\n\n"
            "Please repeat the command using the exact file names."
        )
    if not resolved:
        return _reply("I couldn't tell which files you meant, so nothing was changed. "
                      "Please name the files, or ask about them first so I can refer to them as \"these\".")

    mode = "copy" if plan.get("mode") == "copy" else "move"
    dest_dir = os.path.join(root, folder)
    folder_note = "existing folder" if os.path.isdir(dest_dir) else "new folder"
    rel_files = [os.path.relpath(p, root) for p in resolved]

    answer = (
        f"Here's the plan: **{mode}** {len(resolved)} file(s) into the {folder_note} **{folder}/**\n\n"
        + "\n".join(f"- {f}" for f in rel_files)
        + "\n\nClick **Confirm** to run it, or **Cancel**."
    )
    return _reply(answer, ActionItem(
        action_type="confirm_file_operation",
        label=f"{mode.capitalize()} {len(resolved)} file(s) into {folder}/",
        payload={"root": root, "folder": folder, "mode": mode, "files": resolved}
    ))
