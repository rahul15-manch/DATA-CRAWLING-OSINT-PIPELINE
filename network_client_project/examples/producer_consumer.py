import queue
import threading
import time
import logging
from typing import List

# Setup basic logging for the demo
logging.basicConfig(level=logging.INFO, format='%(threadName)s | %(message)s')
logger = logging.getLogger(__name__)

# --- THE THREAD-SAFE QUEUE ---
# queue.Queue in Python is natively thread-safe.
# It uses Locks internally so multiple threads can .put() and .get() without race conditions.
task_queue = queue.Queue()
results_list = []
results_lock = threading.Lock()

# --- PRODUCER ---
def url_producer(urls_to_scrape: List[str]):
    """
    The Producer's only job is to fill the queue with work.
    In a real system, this might read from a Database or an API.
    """
    logger.info("Producer starting...")
    for url in urls_to_scrape:
        # Put the task into the thread-safe queue
        task_queue.put(url)
        logger.info(f"Produced: {url}")
        time.sleep(0.1) # Simulate DB lookup time
        
    logger.info("Producer finished. All tasks are in the queue.")

# --- CONSUMER (WORKER) ---
def crawler_worker(worker_id: int):
    """
    The Consumer grabs work from the queue and processes it.
    Multiple workers will run this function concurrently.
    """
    logger.info(f"Worker {worker_id} started.")
    
    while True:
        try:
            # timeout=3 means if the queue is empty for 3 seconds, the worker shuts down.
            # This prevents zombie threads from hanging forever.
            target_url = task_queue.get(timeout=3.0)
            
            logger.info(f"Worker {worker_id} is crawling {target_url}...")
            # SIMULATING NETWORK REQUEST (e.g., client.get(target_url))
            time.sleep(1.0) 
            
            # --- CRITICAL SECTION: WRITING SHARED DATA ---
            # If 10 workers try to .append() to results_list at the exact same millisecond,
            # data corruption occurs. We MUST lock the list while appending.
            with results_lock:
                results_list.append(f"Data from {target_url}")
            
            # Tell the queue we finished this specific task
            task_queue.task_done()
            
        except queue.Empty:
            # Queue is empty, time to die.
            logger.info(f"Worker {worker_id} found no more tasks. Shutting down.")
            break

# --- ORCHESTRATOR ---
if __name__ == "__main__":
    urls = [f"https://target.com/page/{i}" for i in range(1, 21)]
    
    # 1. Start the Producer in the background
    producer_thread = threading.Thread(target=url_producer, args=(urls,), name="Producer-Thread")
    producer_thread.start()
    
    # 2. Start a Pool of 5 Workers
    worker_threads = []
    for i in range(5):
        t = threading.Thread(target=crawler_worker, args=(i,), name=f"Worker-{i}")
        t.start()
        worker_threads.append(t)
        
    # 3. Wait for the queue to be completely processed
    producer_thread.join()
    task_queue.join() # Blocks until task_done() is called for every item put() in the queue
    
    logger.info(f"All done! Extracted {len(results_list)} records.")
