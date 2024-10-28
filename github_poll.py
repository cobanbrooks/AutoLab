import git
import os
import time
from datetime import datetime

class Computer1:
    def __init__(self, repo_path):
        self.repo_path = repo_path
        print(f"Initializing repository at {repo_path}")
        self.repo = git.Repo(repo_path)
        self.branch = self.repo.active_branch.name
        print(f"Using branch: {self.branch}")
        
    def check_for_updates(self):
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Checking for updates...")
        try:
            self.repo.remotes.origin.fetch()
            
            if self.repo.head.commit != self.repo.remotes.origin.refs[self.branch].commit:
                print("Changes detected!")
                self.repo.remotes.origin.pull()
                
                # Check if results.txt changed (instead of data.txt)
                for diff in self.repo.head.commit.diff('HEAD~1'):
                    if diff.a_path == 'results.txt':
                        print("results.txt changed, processing...")
                        self.process_results()
                        break
        except Exception as e:
            print(f"Error during update check: {e}")
    
    def process_results(self):
        try:
            # Read results
            with open(os.path.join(self.repo_path, 'results.txt'), 'r') as f:
                results = f.read()
            
            print("Received results:", results)
            
            # Here you can add code to process the results
            # and create new data.txt if needed
            
            # Create new data for next iteration
            with open(os.path.join(self.repo_path, 'data.txt'), 'w') as f:
                f.write(f"New data generated at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Commit and push new data
            self.repo.index.add(['data.txt'])
            self.repo.index.commit('Updated data.txt')
            self.repo.remotes.origin.push()
            print("Pushed new data to GitHub")
            
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
    computer1 = Computer1(repo_path=current_dir)
    computer1.run()