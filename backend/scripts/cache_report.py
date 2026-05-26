import os
import sqlite3
from datetime import datetime
from pathlib import Path

# Paths (relative to the script location or project root)
DB_PATH = Path("./token_usage.db")

def get_cache_metrics():
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # 1. Total Requests (Cache Hits + LLM Completions)
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM token_usage 
            WHERE operation IN ('cache_hit', 'chat_completion')
        """)
        total_requests = cursor.fetchone()['count']

        if total_requests == 0:
            print("No chat records found in database yet.")
            return

        # 2. Cache Hits
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM token_usage 
            WHERE operation = 'cache_hit'
        """)
        cache_hits = cursor.fetchone()['count']

        # 3. LLM Completions (Cache Misses)
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM token_usage 
            WHERE operation = 'chat_completion'
        """)
        cache_misses = cursor.fetchone()['count']

        # 4. Token Savings (Estimated)
        # Assuming average input tokens saved per hit
        cursor.execute("""
            SELECT AVG(input_tokens) as avg_input 
            FROM token_usage 
            WHERE operation = 'chat_completion'
        """)
        avg_input_tokens = cursor.fetchone()['avg_input'] or 0

        # Calculate Rate
        hit_rate = (cache_hits / total_requests) * 100

        # Print Report
        print("="*50)
        print(f"CACHE REPORT - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print("="*50)
        print(f"{'Total Queries:':<25} {total_requests}")
        print(f"{'Cache Hits [OK]:':<25} {cache_hits}")
        print(f"{'Cache Misses [X]:':<25} {cache_misses}")
        print(f"{'Cache Hit Rate:':<25} {hit_rate:.2f}%")
        print("-"*50)
        
        if cache_hits > 0:
            est_saved = cache_hits * avg_input_tokens
            print(f"Est. Tokens Saved:     ~{int(est_saved):,} tokens")
            print(f"Avg. Input per Query:   {int(avg_input_tokens)} tokens")
        
        print("="*50)

        # Breakdown by Mode
        print("\nBreakdown by Mode:")
        cursor.execute("""
            SELECT mode, 
                   COUNT(CASE WHEN operation = 'cache_hit' THEN 1 END) as hits,
                   COUNT(CASE WHEN operation = 'chat_completion' THEN 1 END) as misses
            FROM token_usage
            WHERE operation IN ('cache_hit', 'chat_completion')
            GROUP BY mode
        """)
        rows = cursor.fetchall()
        print(f"{'Mode':<15} | {'Hits':<8} | {'Misses':<8} | {'Rate'}")
        print("-" * 45)
        for row in rows:
            m_total = row['hits'] + row['misses']
            m_rate = (row['hits'] / m_total * 100) if m_total > 0 else 0
            print(f"{row['mode'] or 'Unknown':<15} | {row['hits']:<8} | {row['misses']:<8} | {m_rate:.1f}%")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    # Ensure we are in the right directory if run from root
    if not DB_PATH.exists() and os.path.exists("backend/token_usage.db"):
        DB_PATH = Path("backend/token_usage.db")
    
    get_cache_metrics()
