import os
from typing import List, Dict, Any
from backend.models.schemas import ChatRequest, ChatResponse, SourceItem, ActionItem
from backend.rag.retriever import retriever
from backend.rag.llm_client import llm_client


class RAGService:
    def __init__(self):
        pass

    async def answer_query(self, request: ChatRequest) -> ChatResponse:
        """
        Process user chat request through hybrid retrieval and LLM grounding.
        """
        user_query = request.message.strip()
        history_dicts = [{"role": m.role, "content": m.content} for m in request.history]

        # 1. Retrieve relevant sources and match confidence
        sources, primary_action, confidence = retriever.retrieve(
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
            "Your job is to read, understand, summarize, and answer questions about the user's documents and files.\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. Ground all your answers in the RETRIEVED CONTEXT below.\n"
            "2. When asked to summarize, explain, or answer questions (e.g. 'What are the main topics covered in Unit 1?'):\n"
            "   - Directly explain the topics, concepts, definitions, and key points contained in the document.\n"
            "   - Use structured Markdown formatting with headings, bullet points, and clear explanations.\n"
            "   - Focus on delivering the actual knowledge and content rather than just referencing the file.\n"
            "3. When specifically asked to locate or find a file (e.g. 'Where is my resume?'):\n"
            "   - State the filename and file path clearly along with a brief summary of what it contains.\n"
            "4. If the retrieved context is empty or lacks information to answer, state that clearly.\n"
            "5. Do NOT make up facts or content that cannot be verified from the retrieved context.\n\n"
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
