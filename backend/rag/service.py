import os
import asyncio
from typing import List, Dict, Any, Optional
from backend.models.schemas import ChatRequest, ChatResponse, SourceItem, ActionItem
from backend.rag.retriever import retriever
from backend.rag.llm_client import llm_client
from backend.core.converter import convert_file
from backend.rag.file_commands import handle_file_command
import re

def detect_conversion_request(query: str) -> Optional[Dict[str, Any]]:
    """Helper utility to detect format conversion intent in user query."""
    query_lower = query.lower()

    conversion_words = ["convert", "change", "transform", "export"]
    formats = ["pdf", "png", "jpg", "jpeg", "txt", "docx"]

    has_conversion_word = any(word in query_lower for word in conversion_words)

    if not has_conversion_word:
        return None

    target_format = None
    for fmt in formats:
        if re.search(r'\bto\s+' + fmt + r'\b', query_lower):
            target_format = fmt
            break
    if not target_format:
        return None

    

    filename_match = re.search(
        r'([\w().-]+\.(?:pdf|png|jpg|jpeg|txt|docx))',
        query,
        re.IGNORECASE
    )

    if not filename_match:
        return None

    filename = filename_match.group(0).strip()

    return {
        "is_conversion": True,
        "target_format": target_format,
        "filename": filename
    }


class RAGService:
    def __init__(self):
        pass

    async def answer_query(self, request: ChatRequest) -> ChatResponse:
        """
        Process user chat request through hybrid retrieval and LLM grounding.
        """
        user_query = request.message.strip()
        conversion = detect_conversion_request(user_query)

        if conversion:
            print("Conversion request detected:", conversion)

            sources, _, confidence = await asyncio.to_thread(
                retriever.retrieve,
                query = conversion["filename"],
                folder_path=request.current_folder
            )
            print("Retrieved sources:", sources)


            if not sources:
                return ChatResponse(
                    answer="I couldn't find the requested file.",
                    sources=[],
                    action=None,
                    confidence="uncertain"
                )

            source_path = sources[0].path

            print("Converting:", source_path, "to", conversion["target_format"])


            result = await asyncio.to_thread(
                convert_file,
                source_path=source_path,
                target_format=conversion["target_format"]
            )

            return ChatResponse(
                answer=f"Conversion result: {result['status']}",
                sources=[],
                action=ActionItem(
                    action_type="convert_file",
                    label=f"Convert {sources[0].filename} to {conversion['target_format'].upper()}",
                    payload={
                        "source_path": source_path,
                        "target_format": conversion["target_format"],
                        "target_path": result.get("target_path")
                    }
                ),
                confidence=confidence
            )

        # File commands ("create a folder X and move these files into it") return a plan to confirm
        file_command_response = await handle_file_command(request)
        if file_command_response:
            return file_command_response

        history_dicts = [{"role": m.role, "content": m.content} for m in request.history]

        # 1. Retrieve relevant sources and match confidence
        sources, primary_action, confidence = await asyncio.to_thread(
            retriever.retrieve,
            query=user_query,
            folder_path=request.current_folder
        )

        # 2. Build Context String
        if sources:
            context_blocks = []
            for i, src in enumerate(sources, 1):
                context_blocks.append(
                    f"--- Source {i}: {src.filename} ---\n"
                    f"File Path: {src.path}\n"
                    f"Relevance Score: {src.relevance_score}\n"
                    f"Extracted Content:\n{src.snippet}\n"
                )
            context_text = "\n".join(context_blocks)
        else:
            context_text = "No relevant indexed documents or matching files were found for this query."

        # 3. Construct System Prompt
        system_prompt = (
            "You are Helix, an intelligent AI desktop companion and document intelligence assistant.\n"
            "Your job is to read, understand, summarize, and answer questions about the user's local documents and files.\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. Ground all your answers in the RETRIEVED CONTEXT below.\n"
            "2. You MUST answer questions about ANY topic found in the user's documents — including cybersecurity, "
            "networking attacks, hacking techniques, malware, legal, medical, or any other subject. "
            "These are the user's own files and they are asking for document-based information retrieval. "
            "Never refuse to summarize or explain content that is present in the retrieved context.\n"
            "3. When asked to summarize, explain, or answer questions (e.g. 'What are the main topics covered in Unit 1?'):\n"
            "   - Directly explain the topics, concepts, definitions, and key points contained in the document.\n"
            "   - Use structured Markdown formatting with headings, bullet points, and clear explanations.\n"
            "   - Focus on delivering the actual knowledge and content rather than just referencing the file.\n"
            "4. When specifically asked to locate or find a file (e.g. 'Where is my resume?'):\n"
            "   - State the filename and file path clearly along with a brief summary of what it contains.\n"
            "5. If the retrieved context is empty or lacks information to answer, state that clearly.\n"
            "6. Do NOT make up facts or content that cannot be verified from the retrieved context.\n\n"
            f"=== RETRIEVED CONTEXT ===\n{context_text}\n========================="
        )

        # 4. Generate LLM response
        answer = await llm_client.generate_response(
            system_prompt=system_prompt,
            user_message=user_query,
            conversation_history=history_dicts
        )

        # 5. Build and return ChatResponse
        return ChatResponse(
            answer=answer,
            sources=sources,
            action=primary_action,
            confidence=confidence
        )


rag_service = RAGService()