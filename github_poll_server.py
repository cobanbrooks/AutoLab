import git
import os
import time
from datetime import datetime

class Computer2:
    def __init__(self, repo_path):
        self.repo_path = repo_path
        print(f"Initializing repository at {repo_path}")
        self.repo = git.Repo(repo_path)
        # Get the current branch name
        self.branch = self.repo.active_branch.name
        print(f"Using branch: {self.branch}")
        
    def check_for_updates(self):
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Checking for updates...")
        try:
            self.repo.remotes.origin.fetch()
            
            if self.repo.head.commit != self.repo.remotes.origin.refs[self.branch].commit:
                print("Changes detected!")
                self.repo.remotes.origin.pull()
                
                # Check if data.txt changed
                for diff in self.repo.head.commit.diff('HEAD~1'):
                    if diff.a_path == 'data.txt':
                        print("data.txt changed, processing...")
                        self.process_data()
                        break
        except Exception as e:
            print(f"Error during update check: {e}")
    
    def process_data(self):
        try:
            # Read input data
            with open(os.path.join(self.repo_path, 'data.txt'), 'r') as f:
                input_data = f.read()
            
            print("Processing data:", input_data)
            time.sleep(2)  # Simulate processing time
            
            # Write results
            with open(os.path.join(self.repo_path, 'results.txt'), 'w') as f:
                f.write(f"Processed {input_data} at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Commit and push changes
            self.repo.index.add(['results.txt'])
            self.repo.index.commit('Updated results.txt')
            self.repo.remotes.origin.push()
            print("Pushed results to GitHub")
            
        except Exception as e:
            print(f"Error during processing: {e}")
    
    def run(self, check_interval=10):
        print("\nStarting periodic checks...")
        print(f"Will check for updates every {check_interval} seconds")
        print("Press Ctrl+C to stop\n")
        
        while True:
            self.check_for_updates()
            time.sleep(check_interval)

if __name__ == '__main__':
    current_dir = os.getcwd()
    computer2 = Computer2(repo_path=current_dir)
    computer2.run()