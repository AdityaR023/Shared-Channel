
# import chromadb
# from chromadb.config import Settings
# from openai import OpenAI
# from langchain_core.embeddings import Embeddings
# from dotenv import load_dotenv
# import os 
# load_dotenv()
# # print(os.getenv("x-api-key"))
# # Create OpenAI client (Titan via Capgemini Gateway)
# def create_client():
#     return OpenAI(
#         base_url="https://openai.generative.engine.capgemini.com/v1",
#         api_key=os.getenv("x-api-key")
#     )


# # ✅ Titan Embedding Class (OPTIMIZED)
# class TitanEmbeddings(Embeddings):

#     def __init__(self):
#         # ✅ Create client ONCE (important for performance)
#         self.client = create_client()

#     def embed_documents(self, texts):
#         response = self.client.embeddings.create(
#             model="amazon.titan-embed-text-v2:0",
#             input=texts
#         )
#         return [item.embedding for item in response.data]

#     def embed_query(self, text):
#         response = self.client.embeddings.create(
#             model="amazon.titan-embed-text-v2:0",
#             input=text
#         )
#         return response.data[0].embedding


# # ✅ Initialize embedding model
# titan_embeddings = TitanEmbeddings()




# class TitanChromaEmbeddingFunction:
#     def __call__(self, input):
#         return titan_embeddings.embed_documents(input)

#     def name(self):
#         return "titan_embedding"




# # ✅ Persistent ChromaDB client (CRITICAL ✅)
# client = chromadb.Client(
#     Settings(
#         persist_directory="./chroma_db"   # ✅ saves DB to disk
#     )
# )


# # ✅ Create or load collection
# collection = client.get_or_create_collection(
#     name="mobile_data",
#     embedding_function=TitanChromaEmbeddingFunction()
# )

import chromadb
from chromadb.utils import embedding_functions
from chromadb.config import Settings


# client = chromadb.Client()

embedding_function = embedding_functions.DefaultEmbeddingFunction()

# ✅ Persistent ChromaDB client (CRITICAL ✅)
client = chromadb.PersistentClient(path="./chroma_db")

collection = client.get_or_create_collection(
    name="mobile_data",
    embedding_function=embedding_function
)