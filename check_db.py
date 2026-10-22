from backend.core.vector_store import get_collection

col = get_collection()
data = col.get(limit=2, include=["documents"])
print(data["documents"])