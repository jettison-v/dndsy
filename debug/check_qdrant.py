from qdrant_client import QdrantClient
import os
import json

# Setup client
qdrant_host = os.getenv("QDRANT_HOST", "localhost")
qdrant_port = int(os.getenv("QDRANT_PORT", 6333))
print(f"Connecting to Qdrant at {qdrant_host}:{qdrant_port}")

# Check if it's a cloud instance
is_cloud = qdrant_host.startswith("http")
if is_cloud:
    client = QdrantClient(url=qdrant_host, api_key=os.getenv("QDRANT_API_KEY"))
else:
    client = QdrantClient(host=qdrant_host, port=qdrant_port)

# Check collections
collections = client.get_collections().collections
print(f"Available collections: {[col.name for col in collections]}")

# Check point counts in each collection
print("\nPoint counts:")
for col_name in ["dnd_knowledge", "dnd_semantic"]:
    try:
        point_count = client.count(col_name).count
        print(f"  {col_name}: {point_count} points")
        
        # Get a sample if there are points
        if point_count > 0:
            print(f"\nSample point from {col_name}:")
            sample = client.scroll(
                collection_name=col_name,
                limit=1,
                with_payload=True,
                with_vectors=False
            )[0]
            if sample:
                print(f"  ID: {sample[0].id}")
                metadata = sample[0].payload.get("metadata", {})
                print(f"  Metadata keys: {list(metadata.keys())}")
                if "source" in metadata:
                    print(f"  Source: {metadata['source']}")
                if "page" in metadata:
                    print(f"  Page: {metadata['page']}")
    except Exception as e:
        print(f"  Error with {col_name}: {str(e)}") 