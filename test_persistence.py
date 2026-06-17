import asyncio
import sys
from headroom.memory.backends.local import LocalBackend, LocalBackendConfig

async def read_memory():
    config = LocalBackendConfig(
        db_path="/Users/rihan/.headroom/memory.db",
        embedder_backend="onnx",
        embedder_model="all-MiniLM-L6-v2",
        vector_dimension=384,
    )
    backend = LocalBackend(config)
    await backend._ensure_initialized()
    
    results = await backend.search_memories(
        query="Phase 1 hard kill persistence test",
        user_id="rihan-test",
        top_k=3,
    )
    print(f"Search found {len(results)} results")
    found = False
    for r in results:
        content = getattr(r.memory, 'content', '')
        print(f"  - id={r.memory.id}, content={content[:80]}")
        if "Phase 1 hard kill persistence test" in content:
            found = True
    await backend.close()
    if found:
        print("SUCCESS: Target memory was found.")
    else:
        print("FAILURE: Target memory NOT found.")

if __name__ == "__main__":
    asyncio.run(read_memory())
