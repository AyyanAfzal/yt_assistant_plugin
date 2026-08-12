import os
import re
import math
from typing import List, Dict, Any, AsyncGenerator
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound

from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from langchain_classic.chains import create_history_aware_retriever, create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from dotenv import load_dotenv

load_dotenv()

def extract_video_id(url_or_id: str) -> str:
    # Handle different YouTube URL formats
    youtube_regex = (
        r'(https?://)?(www\.)?'
        '(youtube|youtu|youtube-nocookie)\.(com|be)/'
        '(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
    )
    match = re.match(youtube_regex, url_or_id)
    if match:
        return match.group(6)
    
    if len(url_or_id) == 11 and re.match(r'^[a-zA-Z0-9_-]+$', url_or_id):
        return url_or_id
        
    raise ValueError("Invalid YouTube URL or Video ID")

def format_timestamp(seconds: float) -> str:
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"

class YouTubeRAGService:
    _docs_cache = {}
    _indexed_videos = set()

    def __init__(self):
        # Switched to Google API embeddings because Render free tier (512MB RAM) will crash trying to load local HuggingFace models
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-2",
            google_api_key=os.getenv("GOOGLE_API_KEY")
        )
        
        self.llm = ChatGoogleGenerativeAI(
            model="gemma-4-31b-it",
            temperature=0,
            max_tokens=None,
            timeout=None,
            max_retries=2,
            google_api_key=os.getenv("GOOGLE_API_KEY")
        )
        self.parser = StrOutputParser()

        self.pinecone_api_key = os.getenv("PINECONE_API_KEY")
        self.pinecone_index = os.getenv("PINECONE_INDEX_NAME")

    def save_client_transcript(self, video_id: str, transcript: List[Dict[str, Any]]):
        import json
        cache_file = f"transcript_cache_{video_id}.json"
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(transcript, f)
        except Exception:
            pass

    def fetch_transcript(self, video_id: str) -> List[Dict[str, Any]]:
        import json
        cache_file = f"transcript_cache_{video_id}.json"
        
        # 1. Try to load from local file cache first to avoid IP bans
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
                
        import requests
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
        yt_api = YouTubeTranscriptApi(http_client=session)
        
        try:
            transcript_list_obj = yt_api.list(video_id)
            try:
                transcript = transcript_list_obj.find_transcript(['en', 'en-US', 'en-GB'])
                data = transcript.fetch()
            except NoTranscriptFound:
                first_transcript = next(iter(transcript_list_obj))
                data = first_transcript.fetch()
                
            # Ensure it's a list of dicts (some versions return FetchedTranscriptSnippet dataclass)
            if data and not isinstance(data[0], dict):
                data = [{"text": getattr(x, "text", ""), "start": getattr(x, "start", 0.0), "duration": getattr(x, "duration", 0.0)} for x in data]
                
            # 2. Save to cache
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f)
            except Exception:
                pass
            return data
            
        except Exception as e:
            raise RuntimeError(f"Could not retrieve transcript for video '{video_id}'. API Failed: {str(e)}")

    def build_timestamp_documents(self, transcript: List[Dict[str, Any]], chunk_size: int = 1500) -> List[Document]:
        documents = []
        current_text = []
        current_length = 0
        start_time = 0.0

        for idx, item in enumerate(transcript):
            text = item.get("text", "").strip()
            if not text:
                continue
            
            if not current_text:
                start_time = item.get("start", 0.0)

            current_text.append(text)
            current_length += len(text) + 1

            if current_length >= chunk_size or idx == len(transcript) - 1:
                combined_content = " ".join(current_text)
                formatted_ts = format_timestamp(start_time)
                
                doc = Document(
                    page_content=combined_content,
                    metadata={
                        "start_seconds": math.floor(start_time),
                        "timestamp": formatted_ts,
                        "content_preview": combined_content[:60],
                        "video_id": "current"
                    }
                )
                documents.append(doc)
                current_text = []
                current_length = 0

        return documents

    def get_or_create_retriever(self, video_id: str):
        if video_id in self._docs_cache:
            documents = self._docs_cache[video_id]
        else:
            transcript = self.fetch_transcript(video_id)
            documents = self.build_timestamp_documents(transcript)
            for d in documents:
                d.metadata["video_id"] = video_id
            self._docs_cache[video_id] = documents

        if not documents:
            raise ValueError(f"No text content found in transcript for video {video_id}")

        # 1. Fast path: If already indexed in this session, skip all checks
        if video_id in self._indexed_videos:
            vectorstore = PineconeVectorStore(index_name=self.pinecone_index, embedding=self.embeddings, namespace=video_id)
            return vectorstore.as_retriever(search_kwargs={"k": 5})

        # 2. Check if Pinecone already has vectors for this video to avoid re-embedding
        try:
            from pinecone import Pinecone
            pc = Pinecone(api_key=self.pinecone_api_key)
            idx = pc.Index(self.pinecone_index)
            stats = idx.describe_index_stats()
            
            # If the namespace exists and has vectors, skip the expensive upload phase!
            if video_id in stats.get("namespaces", {}) and stats["namespaces"][video_id].get("vector_count", 0) > 0:
                print(f"Video {video_id} is already indexed in Pinecone! Skipping embedding phase.")
                self._indexed_videos.add(video_id)
                vectorstore = PineconeVectorStore(index_name=self.pinecone_index, embedding=self.embeddings, namespace=video_id)
                return vectorstore.as_retriever(search_kwargs={"k": 5})
        except Exception as e:
            print(f"Warning: Could not check Pinecone stats: {e}")

        print(f"Indexing video {video_id} to Pinecone... This may take a few minutes on CPU.")
        import time
        batch_size = 25  # Reduced batch size to stay under token limits
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i+batch_size]
            
            # Robust Retry Loop for API Rate Limits
            max_retries = 5
            base_delay = 5
            
            for attempt in range(max_retries):
                try:
                    PineconeVectorStore.from_documents(
                        batch, self.embeddings, index_name=self.pinecone_index, namespace=video_id
                    )
                    break # Success!
                except Exception as e:
                    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                        if attempt == max_retries - 1:
                            raise RuntimeError(f"Google Gemini API Rate Limit Exceeded permanently after {max_retries} attempts.")
                        wait_time = base_delay * (2 ** attempt)
                        print(f"Rate limit hit! Sleeping for {wait_time} seconds before retrying...")
                        time.sleep(wait_time)
                    else:
                        raise e # Not a rate limit error, throw it immediately
                        
            if i + batch_size < len(documents):
                time.sleep(5)  # 5-second baseline sleep to stay strictly under 15 RPM limits
                
        self._indexed_videos.add(video_id)
        vectorstore = PineconeVectorStore(index_name=self.pinecone_index, embedding=self.embeddings, namespace=video_id)
        return vectorstore.as_retriever(search_kwargs={"k": 5})

    def answer_question(self, video_url_or_id: str, question: str) -> Dict[str, Any]:
        video_id = extract_video_id(video_url_or_id)
        retriever = self.get_or_create_retriever(video_id)

        retrieved_docs = retriever.invoke(question)

        context_parts = []
        sources = []
        for doc in retrieved_docs:
            ts = doc.metadata.get("timestamp", "00:00")
            sec = doc.metadata.get("start_seconds", 0)
            context_parts.append(f"[{ts}] {doc.page_content}")
            sources.append({
                "timestamp": ts,
                "seconds": sec,
                "snippet": doc.page_content[:100] + "..."
            })

        context_str = "\n\n".join(context_parts)

        prompt_template = PromptTemplate(
            template="""You are an AI assistant answering questions about a YouTube video based ONLY on the transcript context provided.

TRANSCRIPT CONTEXT:
{context}

QUESTION:
{question}

INSTRUCTIONS:
1. Answer the question thoroughly and accurately using ONLY the provided transcript snippets.
2. Include timestamp references (e.g. [MM:SS]) in your answer wherever appropriate so the user knows when this was discussed.
3. If the answer is not mentioned in the transcript, state clearly: "I could not find information about that in the video transcript."
4. Note: The provided transcript is auto-generated by YouTube and often contains phonetic spelling errors (e.g., 'Rage' instead of 'RAG', or weird names). Please intelligently correct obvious phonetic transcription errors when generating your answer.

ANSWER:""",
            input_variables=["context", "question"]
        )

        chain = prompt_template | self.llm | self.parser
        raw_answer = chain.invoke({"context": context_str, "question": question})

        return {
            "video_id": video_id,
            "answer": raw_answer,
            "sources": sources
        }

    async def stream_answer(self, video_url_or_id: str, question: str, chat_history: List[Dict[str, str]] = None) -> AsyncGenerator[str, None]:
        video_id = extract_video_id(video_url_or_id)
        retriever = self.get_or_create_retriever(video_id)

        history_msgs = []
        if chat_history:
            for msg in chat_history:
                if msg["role"] == "user":
                    history_msgs.append(HumanMessage(content=msg["content"]))
                else:
                    history_msgs.append(AIMessage(content=msg["content"]))

        contextualize_q_prompt = ChatPromptTemplate.from_messages([
            ("system", "Given a chat history and the latest user question which might reference context in the chat history, formulate a standalone question which can be understood without the chat history. Do NOT answer the question, just reformulate it if needed and otherwise return it as is."),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
        ])
        
        history_aware_retriever = create_history_aware_retriever(
            self.llm, retriever, contextualize_q_prompt
        )

        qa_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an AI assistant answering questions about a YouTube video based ONLY on the transcript context provided.\n\nTRANSCRIPT CONTEXT:\n{context}\n\nINSTRUCTIONS:\n1. Answer thoroughly and accurately using ONLY the provided transcript snippets.\n2. STRICTLY include standardized timestamp references exactly formatted as [MM:SS] (or [HH:MM:SS]) in your answer whenever referencing the video content.\n3. If the answer is not mentioned, state clearly: 'I could not find information about that in the video transcript.'\n4. Note: The transcript is auto-generated by YouTube and often contains phonetic spelling errors (e.g., 'Rage' instead of 'RAG'). Intelligently correct obvious phonetic errors in your response."),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
        ])
        
        document_prompt = PromptTemplate(
            input_variables=["page_content", "timestamp"],
            template="[{timestamp}] {page_content}"
        )
        
        question_answer_chain = create_stuff_documents_chain(
            self.llm, 
            qa_prompt,
            document_prompt=document_prompt
        )
        rag_chain = create_retrieval_chain(history_aware_retriever, question_answer_chain)

        async for chunk in rag_chain.astream({"input": question, "chat_history": history_msgs}):
            if "answer" in chunk:
                ans = chunk["answer"]
                if isinstance(ans, list):
                    # Gemma sometimes outputs a list of dictionaries, e.g., [{'type': 'text', 'text': '...'}]
                    for part in ans:
                        if isinstance(part, dict) and part.get("type") == "text":
                            yield part.get("text", "")
                elif isinstance(ans, str):
                    yield ans

    def summarize_video(self, video_url_or_id: str) -> Dict[str, Any]:
        video_id = extract_video_id(video_url_or_id)
        if video_id in self._docs_cache:
            docs = self._docs_cache[video_id]
        else:
            transcript = self.fetch_transcript(video_id)
            docs = self.build_timestamp_documents(transcript)
            self._docs_cache[video_id] = docs

        sampled_docs = docs[:15]
        context_str = "\n\n".join([f"[{d.metadata['timestamp']}] {d.page_content}" for d in sampled_docs])

        summary_prompt = PromptTemplate(
            template="""You are an expert content analyzer. Based on the following YouTube video transcript snippets, generate a structured summary.

TRANSCRIPT SNIPPETS:
{context}

Provide your response in the following format:
- **Executive Overview**: A concise 2-3 sentence overview of the video's core topic.
- **Key Takeaways**: 4-5 bullet points highlighting main insights, each with its relevant timestamp [MM:SS] if available.

Note: The transcript is auto-generated by YouTube and often contains phonetic spelling errors (e.g., 'Rage' instead of 'RAG'). Please intelligently correct obvious phonetic transcription errors.

SUMMARY:""",
            input_variables=["context"]
        )

        chain = summary_prompt | self.llm | self.parser
        summary_text = chain.invoke({"context": context_str})

        return {
            "video_id": video_id,
            "summary": summary_text
        }
