import os
from memory import MemoryManager
from flask import Flask

app = Flask(__name__)
app.config["USER_DATA_DIR"] = "user_data"
app.instance_path = os.path.abspath("instance")

with app.app_context():
    # We need to know which user_id was used.
    # The models show current_user.id is used. In a local single-user app it's often 1.
    user_id = 1 
    mm = MemoryManager(user_id=user_id)
    
    print(f"Dumping memory for user {user_id}...")
    
    # Check user collection
    if mm.user_collection:
        try:
            data = mm.user_collection.get()
            print("\n--- USER COLLECTION ---")
            print(f"IDs: {data['ids']}")
            print(f"Documents: {data['documents']}")
            print(f"Metadatas: {data['metadatas']}")
        except Exception as e:
            print(f"User collection error: {e}")
    else:
        print("User collection not initialized.")

    # Check all collections in chroma
    if mm.chroma_client:
        try:
            colls = mm.chroma_client.list_collections()
            for c_info in colls:
                if c_info.name == f"user_memory_{user_id}":
                    continue
                print(f"\n--- COLLECTION {c_info.name} ---")
                c = mm.chroma_client.get_collection(name=c_info.name)
                data = c.get()
                print(f"IDs: {data['ids']}")
                print(f"Documents: {data['documents']}")
        except Exception as e:
            print(f"Chroma client error: {e}")
