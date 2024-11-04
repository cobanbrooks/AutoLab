import os
import time
from git import Repo
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import datetime
import hashlib

class PlateDataHandler(FileSystemEventHandler):
    def __init__(self, repo_path):
        self.repo_path = repo_path
        self.repo = Repo(repo_path)
        self.last_md5 = None
        
    def get_file_md5(self, file_path):
        """Calculate MD5 hash of file to detect actual content changes"""
        with open(file_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    
    def on_created(self, event):
        if event.src_path.endswith('plate_data.csv'):
            self.handle_plate_data(event.src_path, "created")
            
    def on_modified(self, event):
        if event.src_path.endswith('plate_data.csv'):
            self.handle_plate_data(event.src_path, "modified")
    
    def handle_plate_data(self, file_path, event_type):
        try:
            # Check if content has actually changed
            current_md5 = self.get_file_md5(file_path)
            if current_md5 == self.last_md5:
                print("File content unchanged, skipping commit")
                return
                
            self.last_md5 = current_md5
            
            # Get the relative path of the file from the repo root
            relative_path = os.path.relpath(file_path, self.repo_path)
            
            # Stage the file
            self.repo.index.add([relative_path])
            
            # Create commit message with timestamp
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            commit_message = f"{'Update' if event_type == 'modified' else 'Add'} plate data from {timestamp}"
            
            # Commit changes
            self.repo.index.commit(commit_message)
            
            # Push changes
            origin = self.repo.remote('origin')
            origin.push()
            
            print(f"Successfully pushed {relative_path} to GitHub ({event_type} at {timestamp})")
            
        except Exception as e:
            print(f"Error pushing to GitHub: {str(e)}")

def watch_directory(path):
    event_handler = PlateDataHandler(path)
    observer = Observer()
    observer.schedule(event_handler, path, recursive=False)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    # Replace with your repository path
    REPO_PATH = "/Users/cobanbrooks/Documents/RESEARCH/auto_lab"
    
    print("Starting plate data monitor...")
    watch_directory(REPO_PATH)