import os
import faiss
from datetime import datetime
from collections import defaultdict, deque
from langchain_community.vectorstores.faiss import FAISS as LCFAISS
from langchain_community.docstore.in_memory import InMemoryDocstore
from langchain_community.docstore.document import Document

class MemoryManager:
    def __init__(self, base_dir="memory", embeddings=None, llm=None):
        from langchain_openai import OpenAIEmbeddings  # Lazy import to avoid circular issues
        self.base_dir = base_dir
        self.embeddings = embeddings or OpenAIEmbeddings()
        self.cache_memory = defaultdict(lambda: deque(maxlen=15))
        self.dialogue_counter = defaultdict(int)
        self.llm = llm

    def _get_group_path(self, group_id, memory_type):
        return os.path.join(self.base_dir, group_id, memory_type)

    def load_or_create_index(self, group_id, memory_type):
        path = self._get_group_path(group_id, memory_type)
        os.makedirs(path, exist_ok=True)
        if os.path.exists(os.path.join(path, "index.faiss")):
            return LCFAISS.load_local(
                folder_path=path,
                embeddings=self.embeddings,
                allow_dangerous_deserialization=True
            )
        else:
            dim = len(self.embeddings.embed_query("測試句子"))
            index = faiss.IndexFlatL2(dim)
            docstore = InMemoryDocstore({})
            index_to_docstore_id = {}
            return LCFAISS(
                embedding_function=self.embeddings,
                index=index,
                docstore=docstore,
                index_to_docstore_id=index_to_docstore_id,
            )

    def add_texts(self, group_id, memory_type, texts):
        docs = [Document(page_content=t) for t in texts]
        index = self.load_or_create_index(group_id, memory_type)
        index.add_documents(docs)
        index.save_local(self._get_group_path(group_id, memory_type))

    def query_memory(self, group_id, memory_type, query, k=3):
        index = self.load_or_create_index(group_id, memory_type)
        results = index.similarity_search(query, k=k)
        return [doc.page_content for doc in results]

    def add_to_cache(self, group_id, user, text):
        print(len(self.cache_memory[group_id]))
        timestamp = datetime.now().isoformat()
        self.cache_memory[group_id].append({"user": user, "text": text, "timestamp": timestamp})

    def get_cache(self, group_id):
        return self.cache_memory[group_id]

    def add_dialogue_with_summary(self, group_id, user, text, k=5):
        # Add to cache and increment counter
        self.add_to_cache(group_id, user, text)
        self.dialogue_counter[group_id] += 1

        # Every k messages, summarize and extract facts
        if self.dialogue_counter[group_id] % k == 0 and self.llm:
            messages = self.get_cache(group_id)
            context = "\n".join([f"{m['user']}：{m['text']}" for m in messages])
            prompt = (
                "請從以下對話中，提取可能值得記錄的知識點，以條列式列出。例如：\n"
                "- 小明的生日是6月23日\n- 小美將於週五搬宿舍 - 林大恩的綽號是呆呆\n如果沒有就回答「無」。\n\n對話如下：\n" + context
            )
            print("Context for Knowledge Extraction:")
            print(context)
            completion = self.llm.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "你是一個會提取知識點的筆記小幫手。"},
                    {"role": "user", "content": prompt}
                ]
            )
            print(f"[Knowledge Extraction] {completion.choices[0].message.content.strip()}")
            result = completion.choices[0].message.content.strip()[:-1]
            if result.lower() != "無":
                # add timestamp to each line
                lines = [line.strip("- ") for line in result.splitlines() if line.strip()]
                timestamped_lines = [f"{line}（{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}）" for line in lines]
                print("Timestamped Knowledge Points:")
                print("\n".join(timestamped_lines))
                self.add_texts(group_id, "dialogue", timestamped_lines)
