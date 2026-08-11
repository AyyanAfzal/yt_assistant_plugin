import os
import sys
import time
import asyncio

# Ensure backend directory is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.youtube_rag_service import YouTubeRAGService

TEST_VIDEO_ID = "YLPNA1j7kmQ"

QUESTIONS = [
    ("Retrieval", "What exact version of the framework did the creator say they are using at the beginning of the video?"),
    ("Summarization", "Briefly outline the architecture of the application the developer built during this 2-hour stream."),
    ("Timestamp Accuracy", "At exactly what timestamp does the speaker introduce the main topic/guest?"),
    ("Timestamp Accuracy", "I want to skip the introduction. At what timestamp does the actual tutorial/content begin?"),
    ("Hallucination Resistance", "Does the creator mention how to deploy this application to AWS? (Assume the video is strictly about local development)")
]

async def run_evaluation():
    print("Initializing YouTube RAG Service for Evaluation...")
    service = YouTubeRAGService()
    
    print(f"Indexing test video: {TEST_VIDEO_ID}...")
    service.get_or_create_retriever(TEST_VIDEO_ID)
    
    results = []
    
    for category, question in QUESTIONS:
        print(f"\n[{category}] {question}")
        start_time = time.time()
        
        # Collect streaming answer
        answer_parts = []
        try:
            async for chunk in service.stream_answer(TEST_VIDEO_ID, question):
                answer_parts.append(chunk)
                print(chunk, end="", flush=True)
        except Exception as e:
            answer_parts.append(f"ERROR: {e}")
            
        print("\n")
        latency = time.time() - start_time
        full_answer = "".join(answer_parts)
        
        results.append({
            "category": category,
            "question": question,
            "answer": full_answer,
            "latency": latency
        })
        
    print("\nGenerating Evaluation Report...")
    report_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evaluation_results.md")
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 🧪 Automated RAG Evaluation Results\n\n")
        f.write(f"**Test Video ID:** `{TEST_VIDEO_ID}`\n")
        f.write(f"**Model:** `gemma-4-31b-it`\n\n")
        f.write("---\n\n")
        
        for idx, res in enumerate(results, 1):
            f.write(f"### Q{idx}: {res['question']} `[{res['category']}]`\n")
            f.write(f"⏱️ **Latency:** {res['latency']:.2f} seconds\n\n")
            f.write(f"**AI Answer:**\n> {res['answer'].replace(chr(10), chr(10) + '> ')}\n\n")
            f.write("#### Scoring (1-5):\n")
            f.write("- [ ] Retrieval Accuracy: \n")
            f.write("- [ ] Timestamp Precision: \n")
            f.write("- [ ] Format Adherence: \n")
            f.write("- [ ] Hallucination Penalty: \n\n")
            f.write("---\n\n")
            
    print(f"Evaluation complete! Report saved to {report_path}")

if __name__ == "__main__":
    asyncio.run(run_evaluation())
