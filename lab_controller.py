import os
import time
import yaml
import git
import logging
import hashlib
import subprocess
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class PlateDataHandler(FileSystemEventHandler):
    def __init__(self, repo_path, input_file, output_file):
        self.repo_path = repo_path
        self.input_file = input_file
        self.output_file = output_file
        self.repo = git.Repo(repo_path)
        self.logger = logging.getLogger('lab_automation')
        
    def on_modified(self, event):
        if event.src_path.endswith(self.input_file):
            self.logger.info("Plate data modified, processing...")
            self.process_and_push()
            
    def process_and_push(self):
        try:
            # Process plate data
            subprocess.run(['python', 'process_plate_data.py',
                          '--input', self.input_file,
                          '--output', self.output_file], check=True)
            
            # Push to GitHub
            self.repo.index.add([self.output_file])
            self.repo.index.commit('Update processed plate data')
            self.repo.remotes.origin.push()
            self.logger.info("Processed data pushed to GitHub")
            
        except Exception as e:
            self.logger.error(f"Error processing plate data: {e}")

class LabController:
    def __init__(self, config_path):

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(), logging.FileHandler('lab_automation.log')]
        )
        self.logger = logging.getLogger('lab_automation')
        
        # Load config
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
            
        self.repo = git.Repo(self.config['repo_path'])
        self.sequence_hash = None
        
    def check_sequence_updates(self):
        """Check for updates to sequence_query.txt on GitHub"""
        try:
            self.repo.remotes.origin.fetch()
            self.repo.remotes.origin.pull()
            
            with open(os.path.join(self.config['repo_path'], 'sequence_query.txt'), 'rb') as f:
                current_hash = hashlib.md5(f.read()).hexdigest()
                
            if current_hash != self.sequence_hash:
                self.sequence_hash = current_hash
                return True
        except Exception as e:
            self.logger.error(f"Error checking sequence updates: {e}")
        return False
    
    def generate_lab_files(self):
        """Generate worklist and plate layout files"""
        try:
            # Generate pipetting worklist
            subprocess.run([
                'python', 'seq_to_pipetting_steps.py',
                'sequence_query.txt',
                'sequence_segments.csv',
                'output'
            ], check=True)
            
            # Generate plate layout
            subprocess.run([
                'python', 'generate_assay_plate.py',
                'sequence_query.txt',
                'sequence_segments.csv',
                'plate_layout.json'
            ], check=True)
            
            self.logger.info("Generated worklist and plate layout")
            return True
            
        except Exception as e:
            self.logger.error(f"Error generating lab files: {e}")
            return False
            
    def start_plate_monitoring(self):
        """Start monitoring plate_data.csv for changes"""
        handler = PlateDataHandler(
            self.config['repo_path'],
            'plate_data.csv',
            'processed_plate_data.csv'
        )
        
        observer = Observer()
        observer.schedule(handler, self.config['repo_path'], recursive=False)
        observer.start()
        return observer
        
    def run(self):
        self.logger.info("Starting lab automation system")
        observer = None
        
        try:
            while True:
                # Check for sequence updates
                if self.check_sequence_updates():
                    self.logger.info("New sequence detected")
                    
                    # Stop existing monitoring if active
                    if observer:
                        observer.stop()
                        observer.join()
                    
                    # Generate new lab files
                    if self.generate_lab_files():
                        # Start monitoring plate data
                        observer = self.start_plate_monitoring()
                        
                time.sleep(self.config.get('poll_interval', 60))
                
        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
            if observer:
                observer.stop()
                observer.join()

if __name__ == "__main__":

    config_path = 'lab_config.yml'
    if not os.path.exists(config_path):
        with open(config_path, 'w') as f:
            yaml.dump(default_config, f)
        print(f"Created default config at {config_path}")
        exit(1)
        
    automation = LabAutomation(config_path)
    automation.run()