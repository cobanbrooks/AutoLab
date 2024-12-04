import os
import sys
import yaml
import git
import json
import time
import logging
import hashlib
import subprocess
from enum import Enum
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Status Tracking
class LabState(Enum):
    IDLE = "Waiting for new sequence"
    SEQUENCE_RECEIVED = "New sequence received, generating instructions"
    EXPERIMENTING = "Robot performing DNA assembly, amplification, expression, assay"
    PROCESSING = "Processing plate data"
    ERROR = "Error encountered"

class LabStatus:
    def __init__(self, repo_path, status_file='lab_status.json'):
        self.status_file = os.path.join(repo_path, status_file)
        self.repo = git.Repo(repo_path)
        self.state = LabState.IDLE
        self.current_step = None
        self.error = None
        
    def update_state(self, state: LabState, step_details: str = None, error: str = None):
        """Update the lab's current state and push to GitHub"""
        self.state = state
        self.current_step = step_details
        self.error = error
        self._write_and_push_status()
    
    def get_status(self):
        """Get current status"""
        return {
            'state': self.state.value,
            'current_step': self.current_step,
            'error': self.error,
            'last_updated': datetime.now().isoformat()
        }
    
    def _write_and_push_status(self):
        """Write status to file and push to GitHub"""
        try:
            # Write status locally
            with open(self.status_file, 'w') as f:
                json.dump(self.get_status(), f, indent=2)
            
            # Push to GitHub
            self.repo.index.add([os.path.basename(self.status_file)])
            self.repo.index.commit('Update lab status')
            self.repo.remotes.origin.push()
        except Exception as e:
            print(f"Error updating status: {e}")

class PlateDataHandler(FileSystemEventHandler):
    def __init__(self, repo_path, input_file, output_file, status):
        self.repo_path = repo_path
        self.input_file = input_file
        self.output_file = output_file
        self.repo = git.Repo(repo_path)
        self.logger = logging.getLogger('lab_automation')
        self.status = status
        
    def on_modified(self, event):
        if event.src_path.endswith(self.input_file):
            self.logger.info("Plate data modified, processing...")
            self.status.update_state(LabState.PROCESSING, "Processing plate data")
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
            self.status.update_state(LabState.IDLE, "Processing complete") 

            
        except Exception as e:
            self.logger.error(f"Error processing plate data: {e}")

class LabController:
    def __init__(self, config_path):
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(), logging.FileHandler('lab_controller.log')]
        )
        self.logger = logging.getLogger('lab_controller')
        
        # Load config
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
            
        self.repo = git.Repo(self.config['repo_path'])
        self.sequence_hash = None
        self.status = LabStatus(self.config['repo_path'])
        
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
            'processed_plate_data.csv',
            self.status
        )
        
        observer = Observer()
        observer.schedule(handler, self.config['repo_path'], recursive=False)
        observer.start()
        return observer
        
    def run(self):
        self.logger.info("Starting lab automation system")
        self.status.update_state(LabState.IDLE)
        observer = None
        
        try:
            while True:
                # Check for sequence updates
                if self.check_sequence_updates():
                    self.logger.info("New sequence detected")
                    self.status.update_state(LabState.SEQUENCE_RECEIVED)
                    
                    # Stop existing monitoring if active
                    if observer:
                        observer.stop()
                        observer.join()
                    
                    # Generate new lab files
                    if self.generate_lab_files():
                        self.status.update_state(LabState.EXPERIMENTING)
                        # Start monitoring plate data
                        observer = self.start_plate_monitoring()
                        
                time.sleep(self.config.get('poll_interval', 60))
                
        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
            self.status.update_state(LabState.IDLE, "Shutdown complete")
            if observer:
                observer.stop()
                observer.join()
        except Exception as e:
            self.status.update_state(LabState.ERROR, error=str(e))
            self.logger.error(f"Error: {e}")

if __name__ == "__main__":
    # Default configuration
    default_config = {
        'repo_path': '/path/to/repo',
        'poll_interval': 60  # seconds
    }
    
    config_path = 'lab_config.yml'
    if not os.path.exists(config_path):
        with open(config_path, 'w') as f:
            yaml.dump(default_config, f)
        print(f"Created default config at {config_path}")
        exit(1)
        
    automation = LabAutomation(config_path)
    automation.run()